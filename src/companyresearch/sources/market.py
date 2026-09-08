from __future__ import annotations

from typing import Any

from companyresearch import cache
from companyresearch.net import is_ssl_error, use_insecure_ssl, yfinance_ticker
from companyresearch.sources.classify import classify_url, domain_of

YF_TICKER_FIX = str.maketrans({".": "-"})


def normalize_ticker(raw: str) -> str:
    return raw.strip().upper().translate(YF_TICKER_FIX)


def _jsonish(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _jsonish(value.item())
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _pick(info: dict, keys: list[str]) -> dict[str, Any]:
    out = {}
    for key in keys:
        if key in info and info[key] not in (None, "", [], {}):
            out[key] = _jsonish(info[key])
    return out


SNAPSHOT_KEYS = [
    "longName",
    "shortName",
    "symbol",
    "sector",
    "industry",
    "country",
    "website",
    "fullTimeEmployees",
    "longBusinessSummary",
    "currency",
    "currentPrice",
    "previousClose",
    "regularMarketPrice",
    "marketCap",
    "enterpriseValue",
    "trailingPE",
    "forwardPE",
    "pegRatio",
    "priceToBook",
    "profitMargins",
    "operatingMargins",
    "grossMargins",
    "returnOnEquity",
    "returnOnAssets",
    "revenueGrowth",
    "earningsGrowth",
    "earningsQuarterlyGrowth",
    "revenuePerShare",
    "totalRevenue",
    "ebitda",
    "totalCash",
    "totalDebt",
    "debtToEquity",
    "currentRatio",
    "quickRatio",
    "freeCashflow",
    "operatingCashflow",
    "dividendYield",
    "payoutRatio",
    "recommendationKey",
    "numberOfAnalystOpinions",
    "targetMeanPrice",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "averageVolume",
    "sharesOutstanding",
    "floatShares",
    "heldPercentInsiders",
    "heldPercentInstitutions",
    "shortRatio",
    "shortPercentOfFloat",
    "beta",
]


def _snapshot_from_info(symbol: str, info: dict[str, Any]) -> dict[str, Any]:
    snapshot = _pick(info, SNAPSHOT_KEYS)
    price = snapshot.get("currentPrice") or snapshot.get("regularMarketPrice") or snapshot.get("previousClose")
    snapshot["price"] = price
    snapshot["ticker"] = symbol
    snapshot["name"] = snapshot.get("longName") or snapshot.get("shortName") or symbol
    return snapshot


def fetch_snapshot(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    cached = cache.get(f"snap:{symbol}", ttl_seconds=45 * 60)
    if cached:
        return cached
    market = cache.get(f"market:{symbol}", ttl_seconds=15 * 60)
    if market and market.get("snapshot"):
        return market["snapshot"]
    stock = yfinance_ticker(symbol)
    try:
        info = stock.info or {}
    except Exception as exc:
        if not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        stock = yfinance_ticker(symbol)
        info = stock.info or {}
    snapshot = _snapshot_from_info(symbol, info)
    cache.put(f"snap:{symbol}", snapshot)
    return snapshot


def fetch_market(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    cached = cache.get(f"market:{symbol}", ttl_seconds=15 * 60)
    if cached:
        return cached

    stock = yfinance_ticker(symbol)
    try:
        info = stock.info or {}
    except Exception as exc:
        if not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        stock = yfinance_ticker(symbol)
        info = stock.info or {}
    snapshot = _snapshot_from_info(symbol, info)
    cache.put(f"snap:{symbol}", snapshot)

    financials: dict[str, Any] = {}
    try:
        annual = stock.financials
        if annual is not None and not annual.empty:
            col = str(annual.columns[0])
            financials["latest_period"] = col
            for label in ("Total Revenue", "Net Income", "Gross Profit", "EBIT", "Diluted EPS"):
                if label in annual.index:
                    financials[label] = _jsonish(annual.loc[label].iloc[0])
    except Exception:
        pass

    news_raw = []
    try:
        news_raw = stock.news or []
    except Exception:
        news_raw = []

    news = []
    for item in news_raw[:12]:
        parsed = _parse_yf_news(item)
        if parsed:
            news.append(parsed)

    payload = {"snapshot": snapshot, "financials": financials, "news": news}
    cache.put(f"market:{symbol}", payload)
    return payload


def _parse_yf_news(item: dict) -> dict | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else None
    if content:
        url = ""
        canonical = content.get("canonicalUrl") or {}
        click = content.get("clickThroughUrl") or {}
        if isinstance(canonical, dict):
            url = canonical.get("url") or ""
        if not url and isinstance(click, dict):
            url = click.get("url") or ""
        title = content.get("title") or ""
        publisher = (content.get("provider") or {}).get("displayName") or ""
        published = content.get("pubDate") or content.get("displayTime") or ""
        summary = content.get("summary") or ""
    else:
        title = item.get("title") or ""
        url = item.get("link") or item.get("url") or ""
        publisher = item.get("publisher") or ""
        published = item.get("providerPublishTime") or item.get("pubDate") or ""
        summary = item.get("summary") or ""
    if not title:
        return None
    return {
        "title": title,
        "url": url,
        "publisher": publisher,
        "published": str(published),
        "summary": summary,
        "domain": domain_of(url),
        "class": classify_url(url, "news"),
        "origin": "yahoo_finance",
    }
