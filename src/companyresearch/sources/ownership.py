from __future__ import annotations

from typing import Any

from companyresearch import cache
from companyresearch.net import is_ssl_error, use_insecure_ssl, yfinance_ticker
from companyresearch.sources.market import normalize_ticker


def _frame_records(frame: Any, limit: int = 8) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        if getattr(frame, "empty", True):
            return []
        records = frame.head(limit).reset_index().to_dict(orient="records")
    except Exception:
        return []
    clean = []
    for row in records:
        clean.append({str(k): (None if v is None else str(v)) for k, v in row.items()})
    return clean


def _pull(symbol: str) -> dict[str, Any]:
    stock = yfinance_ticker(symbol)
    payload: dict[str, Any] = {
        "major": [],
        "institutions": [],
        "insiders": [],
        "notes": [],
    }
    try:
        payload["major"] = _frame_records(stock.major_holders, 8)
    except Exception:
        payload["notes"].append("Major holders table unavailable.")
    try:
        payload["institutions"] = _frame_records(stock.institutional_holders, 8)
    except Exception:
        payload["notes"].append("Institutional holders (13F-style) unavailable.")
    try:
        payload["insiders"] = _frame_records(stock.insider_transactions, 8)
    except Exception:
        payload["notes"].append("Insider transactions unavailable.")
    return payload


def fetch_ownership(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    cached = cache.get(f"own:{symbol}", ttl_seconds=60 * 60)
    if cached:
        return cached
    try:
        payload = _pull(symbol)
    except Exception as exc:
        if not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        payload = _pull(symbol)
    cache.put(f"own:{symbol}", payload)
    return payload
