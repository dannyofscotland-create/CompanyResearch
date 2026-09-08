from __future__ import annotations

import re
from typing import Any

from companyresearch import cache
from companyresearch.config import settings
from companyresearch.net import http_get_json
from companyresearch.sources.classify import classify_url

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_FORMS = {"10-K", "10-Q", "8-K", "8-K/A", "20-F", "6-K", "4", "13F-HR", "SC 13D", "SC 13G"}


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


def _ticker_map() -> list[dict[str, Any]]:
    cached = cache.get("sec:tickers", ttl_seconds=24 * 60 * 60)
    if cached:
        return cached
    data = http_get_json(TICKERS_URL, headers=_headers())
    rows = list(data.values()) if isinstance(data, dict) else data
    cache.put("sec:tickers", rows)
    return rows


def lookup_company(query: str) -> dict[str, Any] | None:
    q = query.strip().upper()
    if not q:
        return None
    try:
        rows = _ticker_map()
    except Exception:
        return None
    exact = None
    name_hits: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        title = str(row.get("title") or "")
        cik = str(row.get("cik_str") or "").zfill(10)
        item = {"ticker": ticker, "title": title, "cik": cik}
        if ticker == q or ticker.replace("-", ".") == q.replace("-", "."):
            exact = item
            break
        if q.lower() in title.lower():
            name_hits.append(item)
    if exact:
        return exact
    if len(q) >= 3 and name_hits:
        name_hits.sort(key=lambda r: (len(r["title"]), r["title"]))
        return name_hits[0]
    return None


def fetch_filings(cik: str, limit: int = 12) -> list[dict[str, Any]]:
    cached = cache.get(f"sec:sub:{cik}", ttl_seconds=60 * 60)
    if cached:
        return cached[:limit]
    url = SUBMISSIONS_URL.format(cik=cik)
    payload = http_get_json(url, headers=_headers())
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    descriptions = recent.get("primaryDocDescription") or []
    primaries = recent.get("primaryDocument") or []
    items = []
    for i, form in enumerate(forms):
        if form not in FILING_FORMS:
            continue
        accession = accessions[i] if i < len(accessions) else ""
        primary = primaries[i] if i < len(primaries) else ""
        acc_path = accession.replace("-", "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_path}/{primary}" if accession and primary else ""
        items.append(
            {
                "title": f"{form} — {descriptions[i] if i < len(descriptions) else form}",
                "form": form,
                "filed": dates[i] if i < len(dates) else "",
                "url": filing_url,
                "domain": "sec.gov",
                "class": classify_url(filing_url, "sec"),
                "origin": "sec_edgar",
            }
        )
        if len(items) >= 40:
            break
    cache.put(f"sec:sub:{cik}", items)
    return items[:limit]


def _excerpt_from_text(form: str, text: str) -> str:
    from companyresearch.sources.pages import html_to_text

    body = html_to_text(text)
    lower = body.lower()
    if form in {"10-K", "10-Q", "20-F"}:
        for marker in ("item 1a", "item 1a.", "risk factors", "principal risks"):
            i = lower.find(marker)
            if i >= 0:
                chunk = body[i : i + 2800]
                stop = re.search(r"\n\s*item 1b|\n\s*item 2\b", chunk[80:], flags=re.I)
                if stop:
                    chunk = chunk[: 80 + stop.start()]
                return chunk.strip()
    return body[:1600].strip()


def fetch_filing_excerpts(filings: list[dict[str, Any]], limit: int = 2) -> list[dict[str, Any]]:
    """Read a couple of actual filings, the way a person would open the PDF/HTML."""
    from companyresearch.net import http_get_text

    rank = {"10-K": 0, "20-F": 1, "10-Q": 2, "8-K": 3, "8-K/A": 4, "6-K": 5}
    ranked = sorted(filings, key=lambda f: rank.get(str(f.get("form") or ""), 9))
    out: list[dict[str, Any]] = []
    for filing in ranked:
        url = filing.get("url") or ""
        form = str(filing.get("form") or "")
        if not url:
            continue
        key = f"sec:ex:{url}"
        cached = cache.get(key, ttl_seconds=24 * 60 * 60)
        if cached:
            if cached.get("excerpt"):
                out.append(cached)
            if len(out) >= limit:
                break
            continue
        try:
            raw = http_get_text(url, headers=_headers(), max_bytes=1_800_000)
            excerpt = _excerpt_from_text(form, raw)
        except Exception:
            excerpt = ""
        row = {
            "form": form,
            "filed": filing.get("filed"),
            "title": filing.get("title"),
            "url": url,
            "excerpt": excerpt,
        }
        cache.put(key, row)
        if excerpt:
            out.append(row)
        if len(out) >= limit:
            break
    return out
