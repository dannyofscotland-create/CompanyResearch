from __future__ import annotations

from typing import Any

from ddgs import DDGS

from companyresearch import cache
from companyresearch.sources.classify import classify_url, collapse_stories, domain_of


def _search_news(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    key = f"ddgs:news:{query}:{max_results}"
    cached = cache.get(key, ttl_seconds=20 * 60)
    if cached:
        return cached
    rows: list[dict[str, Any]] = []
    try:
        for item in DDGS().news(query, max_results=max_results):
            url = item.get("url") or item.get("link") or ""
            rows.append(
                {
                    "title": item.get("title") or "",
                    "url": url,
                    "publisher": item.get("source") or item.get("publisher") or "",
                    "published": item.get("date") or item.get("published") or "",
                    "summary": item.get("body") or item.get("excerpt") or "",
                    "domain": domain_of(url),
                    "class": classify_url(url, "news"),
                    "origin": "web_news",
                }
            )
    except Exception:
        rows = []
    cache.put(key, rows)
    return rows


def _search_text(query: str, max_results: int = 6) -> list[dict[str, Any]]:
    key = f"ddgs:text:{query}:{max_results}"
    cached = cache.get(key, ttl_seconds=20 * 60)
    if cached:
        return cached
    rows: list[dict[str, Any]] = []
    try:
        for item in DDGS().text(query, max_results=max_results):
            url = item.get("href") or item.get("url") or ""
            rows.append(
                {
                    "title": item.get("title") or "",
                    "url": url,
                    "publisher": domain_of(url),
                    "published": "",
                    "summary": item.get("body") or "",
                    "domain": domain_of(url),
                    "class": classify_url(url),
                    "origin": "web_search",
                }
            )
    except Exception:
        rows = []
    cache.put(key, rows)
    return rows


def search_angle(query: str, kind: str, why: str, max_results: int = 5) -> list[dict[str, Any]]:
    """One search a person might type, tagged with why we typed it."""
    rows = _search_news(query, max_results) if kind == "news" else _search_text(query, max_results)
    tagged = []
    for row in rows:
        tagged.append({**row, "query": query, "angle": why})
    if kind != "news" and not tagged:
        for row in _search_news(query, max_results):
            tagged.append({**row, "query": query, "angle": why})
    return tagged


def fetch_coverage(name: str, ticker: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(search_angle(f"{ticker} {name} stock", "news", "What is being written this week", 8))
    items.extend(search_angle(f'"{name}" {ticker} earnings', "news", "Latest results", 6))
    items.extend(search_angle(f'"{name}" lawsuit OR investigation OR risk', "text", "Trouble the company page skips", 6))
    items.sort(key=lambda r: {"primary": 0, "secondary": 1, "unknown": 2, "noise": 3}.get(r.get("class"), 4))
    return collapse_stories(items)
