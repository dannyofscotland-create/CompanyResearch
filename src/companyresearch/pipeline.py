from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from companyresearch.investigate import iter_investigate
from companyresearch.projections import build_guide, fetch_price_history
from companyresearch.sources.classify import collapse_stories
from companyresearch.sources.market import fetch_market, normalize_ticker
from companyresearch.sources.ownership import fetch_ownership
from companyresearch.sources.sec import fetch_filings, lookup_company

ProgressFn = Callable[[str, str], None]


def _score_confidence(
    sources: list[dict[str, Any]],
    snapshot: dict[str, Any],
    filings: list,
    investigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    investigation = investigation or {}
    classes = [s.get("class") for s in sources]
    primary = sum(1 for c in classes if c == "primary")
    secondary = sum(1 for c in classes if c == "secondary")
    noise = sum(1 for c in classes if c == "noise")
    independent_news = {
        s.get("domain")
        for s in sources
        if s.get("origin") in {"web_news", "yahoo_finance", "web_search"} and s.get("class") in {"secondary", "primary"}
    }
    echo_count = sum(1 for s in sources if s.get("echo"))
    reasons = []
    score = 35
    if snapshot.get("longBusinessSummary"):
        score += 10
        reasons.append("Company description available.")
    if snapshot.get("marketCap"):
        score += 8
        reasons.append("Market snapshot loaded.")
    if filings:
        score += 15
        reasons.append(f"{len(filings)} recent SEC filings.")
    if investigation.get("reads"):
        score += 8
        reasons.append("Opened actual pages, not only headlines.")
    if investigation.get("chased"):
        score += 6
        reasons.append("Chased follow-up questions after the first pass.")
    if investigation.get("filing_excerpts"):
        score += 6
        reasons.append("Skimmed filing text, not just the form name.")
    if primary:
        score += min(12, primary * 2)
    if len(independent_news) >= 3:
        score += 12
        reasons.append(f"{len(independent_news)} independent news domains.")
    elif len(independent_news) >= 1:
        score += 5
        reasons.append("Some independent news coverage.")
    else:
        reasons.append("Little independent news coverage.")
    if secondary:
        score += min(8, secondary)
    if echo_count:
        score -= min(10, echo_count * 2)
        reasons.append("Some headlines look like copies of the same story.")
    if noise and noise >= secondary:
        score -= 6
        reasons.append("A lot of coverage is social or aggregator noise.")
    score = max(8, min(92, score))
    if score >= 70:
        label = "High"
        stance = "Enough public record to brief — still not a forecast."
    elif score >= 45:
        label = "Medium"
        stance = "Usable sketch; several facts still thin or one-sided."
    else:
        label = "Low"
        stance = "Thin or noisy public record. Do not treat this as a decision."
    return {
        "score": score,
        "label": label,
        "stance": stance,
        "primary": primary,
        "secondary": secondary,
        "noise": noise,
        "independent_news_domains": len(independent_news),
        "reasons": reasons,
    }


def iter_research(query: str):
    yield ("status", {"step": "lookup", "label": "Finding the company"})
    ident = lookup_company(query)
    ticker = ident["ticker"] if ident else normalize_ticker(query)
    cik = ident["cik"] if ident else None
    sec_name = ident["title"] if ident else None

    errors: list[str] = []
    market: dict[str, Any] = {"snapshot": {}, "financials": {}, "news": []}
    filings: list[dict[str, Any]] = []
    ownership: dict[str, Any] = {"major": [], "institutions": [], "insiders": [], "notes": []}
    investigation: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []

    yield ("status", {"step": "gather", "label": "Getting the numbers and who already owns it"})
    hist: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_market, ticker): "market",
            pool.submit(fetch_ownership, ticker): "owners",
            pool.submit(fetch_price_history, ticker): "hist",
        }
        if cik:
            futures[pool.submit(fetch_filings, cik)] = "sec"
        else:
            errors.append("No SEC CIK match — filings skipped. Try the official ticker.")
        for fut in as_completed(futures):
            kind = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                errors.append(f"{kind} failed: {exc}")
                continue
            if kind == "market":
                market = result
            elif kind == "owners":
                ownership = result
            elif kind == "sec":
                filings = result
            elif kind == "hist":
                hist = result or {}

    snapshot = market.get("snapshot") or {}
    name = snapshot.get("name") or sec_name or ticker

    try:
        for kind, data in iter_investigate(name, ticker, snapshot, filings, hist, market.get("news") or []):
            if kind == "status":
                yield (kind, data)
            else:
                sources = collapse_stories([*(data.get("sources") or []), *filings])
                investigation = data.get("investigation") or {}
    except Exception as exc:
        errors.append(f"investigation failed: {exc}")
        sources = collapse_stories([*(market.get("news") or []), *filings])

    confidence = _score_confidence(sources, snapshot, filings, investigation)
    guide = build_guide(snapshot, hist)
    yield (
        "packet",
        {
            "query": query,
            "ticker": ticker,
            "cik": cik,
            "name": name,
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "snapshot": snapshot,
            "financials": market.get("financials") or {},
            "filings": filings,
            "ownership": ownership,
            "sources": sources,
            "investigation": investigation,
            "confidence": confidence,
            "guide": guide,
            "errors": errors,
        },
    )


def run_research(query: str, on_progress: ProgressFn | None = None) -> dict[str, Any]:
    packet: dict[str, Any] = {}
    for kind, data in iter_research(query):
        if kind == "status":
            if on_progress:
                on_progress(data["step"], data["label"])
        else:
            packet = data
    return packet
