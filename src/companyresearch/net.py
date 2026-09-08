from __future__ import annotations

import ssl
from typing import Any

import httpx

from companyresearch.config import settings

_insecure = not settings.ssl_verify
_yf_session = None


def using_insecure_ssl() -> bool:
    return _insecure


def use_insecure_ssl() -> None:
    global _insecure, _yf_session
    _insecure = True
    _yf_session = None
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass


def verify() -> bool:
    if _insecure:
        return False
    return True


def is_ssl_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".upper()
    return "CERTIFICATE" in text or "SSL" in text or "CERT" in text


def http_client(**kwargs) -> httpx.Client:
    kwargs.setdefault("timeout", 20.0)
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("verify", verify())
    return httpx.Client(**kwargs)


def http_get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    try:
        with http_client(headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        if _insecure or not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        with http_client(headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()


def http_get_text(url: str, *, headers: dict[str, str] | None = None, max_bytes: int = 400_000) -> str:
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; CompanyResearch/0.1; local research)", **(headers or {})}

    def _read() -> str:
        with http_client(headers=hdrs, timeout=25.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content[:max_bytes].decode(response.encoding or "utf-8", errors="replace")

    try:
        return _read()
    except Exception as exc:
        if _insecure or not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        return _read()


def yfinance_session():
    global _yf_session
    if _yf_session is not None:
        return _yf_session
    from curl_cffi import requests as cffi_requests

    _yf_session = cffi_requests.Session(impersonate="chrome", verify=verify())
    return _yf_session


def yfinance_ticker(symbol: str):
    import yfinance as yf

    try:
        return yf.Ticker(symbol, session=yfinance_session())
    except Exception as exc:
        if _insecure or not is_ssl_error(exc):
            raise
        use_insecure_ssl()
        return yf.Ticker(symbol, session=yfinance_session())
