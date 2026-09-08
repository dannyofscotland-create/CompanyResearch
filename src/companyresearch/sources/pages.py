from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

from companyresearch import cache
from companyresearch.net import http_get_text
from companyresearch.sources.classify import domain_of

SKIP_HOSTS = {
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "yahoo.com",
    "finance.yahoo.com",
    "seekingalpha.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "youtube.com",
    "tiktok.com",
}


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|h1|h2|h3|li|tr)>", "\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = unescape(html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n[ \t]+", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _host_ok(url: str) -> bool:
    host = domain_of(url)
    if not host:
        return False
    if host in SKIP_HOSTS:
        return False
    if any(host.endswith("." + h) for h in SKIP_HOSTS):
        return False
    scheme = urlparse(url).scheme
    return scheme in {"http", "https"}


def fetch_snippet(url: str, max_chars: int = 1800) -> str:
    if not _host_ok(url):
        return ""
    key = f"page:{url}:{max_chars}"
    cached = cache.get(key, ttl_seconds=12 * 60 * 60)
    if cached is not None:
        return cached
    try:
        raw = http_get_text(url)
    except Exception:
        cache.put(key, "")
        return ""
    text = html_to_text(raw)
    snippet = text[:max_chars]
    cache.put(key, snippet)
    return snippet


def read_leads(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Open a few pages a human would click, not every headline."""
    ranked = sorted(
        items,
        key=lambda r: (
            0 if r.get("class") == "primary" else 1 if r.get("class") == "secondary" else 2,
            0 if r.get("origin") in {"web_search", "web_news", "followup"} else 1,
            -(len(r.get("summary") or "")),
        ),
    )
    seen: set[str] = set()
    reads: list[dict[str, Any]] = []
    for item in ranked:
        url = item.get("url") or ""
        if not url or url in seen or not _host_ok(url):
            continue
        if item.get("origin") == "sec_edgar":
            continue
        seen.add(url)
        snippet = fetch_snippet(url)
        if len(snippet) < 80:
            continue
        reads.append(
            {
                "title": item.get("title"),
                "url": url,
                "domain": item.get("domain") or domain_of(url),
                "angle": item.get("angle") or "",
                "excerpt": snippet,
            }
        )
        if len(reads) >= limit:
            break
    return reads
