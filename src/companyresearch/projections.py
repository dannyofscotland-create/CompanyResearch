from __future__ import annotations

from typing import Any

from companyresearch import cache
from companyresearch.net import is_ssl_error, use_insecure_ssl, yfinance_ticker
from companyresearch.screens import _bear_score, _endorsement_score, _longshot_score, _quality_score, _speculative_score, short_blurb
from companyresearch.sources.market import normalize_ticker


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _cagr(start: float, end: float, years: float) -> float | None:
    if start <= 0 or years <= 0 or end is None:
        return None
    return (end / start) ** (1 / years) - 1


def fetch_price_history(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    cached = cache.get(f"hist:{symbol}", ttl_seconds=12 * 60 * 60)
    if cached:
        return cached
    stock = yfinance_ticker(symbol)
    try:
        frame = stock.history(period="5y", auto_adjust=True)
    except Exception as exc:
        if not is_ssl_error(exc):
            return {}
        use_insecure_ssl()
        stock = yfinance_ticker(symbol)
        try:
            frame = stock.history(period="5y", auto_adjust=True)
        except Exception:
            return {}
    if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
        return {}
    start = float(frame["Close"].iloc[0])
    end = float(frame["Close"].iloc[-1])
    days = max(1, (frame.index[-1] - frame.index[0]).days)
    years = days / 365.25
    one_year = None
    try:
        import pandas as pd

        cutoff = frame.index[-1] - pd.DateOffset(years=1)
        recent = frame.loc[frame.index >= cutoff]
        if len(recent) >= 2:
            one_year = float(recent["Close"].iloc[-1]) / float(recent["Close"].iloc[0]) - 1
    except Exception:
        one_year = None
    payload = {
        "years": round(years, 2),
        "start": start,
        "end": end,
        "cagr_5y": _cagr(start, end, years),
        "return_1y": one_year,
    }
    cache.put(f"hist:{symbol}", payload)
    return payload


def build_guide(snapshot: dict[str, Any], history: dict[str, Any] | None = None) -> dict[str, Any]:
    history = history or {}
    quality, _ = _quality_score(snapshot)
    speculative, _ = _speculative_score(snapshot)
    longshot, _ = _longshot_score(snapshot)
    bear, bear_why = _bear_score(snapshot)
    endorsement, endorsement_why = _endorsement_score(snapshot)
    hist = history.get("cagr_5y")
    hist_years = history.get("years")
    mcap = _num(snapshot.get("marketCap"))

    if endorsement >= 50:
        kind = "endorsement"
        headline = "This moves on politics and posters, not a piggy bank"
        blurb = (
            "A Trump mention or a celebrity pump can spike a share. The photos of people getting rich fast are the winners. "
            "Plenty of people buy after the spike and lose. The pretend helper may put a tiny fake slice in so you can watch how it does. "
            "A lucky pretend week is not a reason to hand over cash. If crash-style headlines flash, it may sell — that is not a timer."
        )
        middle = _clamp(hist if hist is not None else 0.0, -0.40, 0.20)
        tough = _clamp(middle - 0.55, -0.80, -0.20)
        lucky = _clamp(middle + 0.55, 0.20, 0.90)
    elif longshot >= 52 and (mcap is None or mcap < 1.5e10):
        kind = "longshot"
        headline = "This is the ‘£10 might become a fortune’ shape"
        blurb = (
            "Early bitcoin looked like this: small, easy to ignore, and a huge range of outcomes. "
            "Almost every name like that does not become bitcoin. If the story fails, the £10 can go near zero. "
            "Only money you could burn."
        )
        middle = _clamp(hist if hist is not None else 0.05, -0.30, 0.18)
        tough = _clamp(middle - 0.50, -0.75, -0.15)
        lucky = _clamp(middle + 0.45, 0.20, 0.80)
    elif quality >= speculative + 6 and quality >= 56:
        kind = "steadier"
        headline = "More like a real business than a lottery ticket"
        blurb = (
            "This company already makes money, on paper. That does not mean the share price will go up. "
            "It usually means the ride is less wild than a story stock — still not a savings account."
        )
        middle = _clamp(hist if hist is not None else 0.08, 0.02, 0.14)
        tough = _clamp(middle - 0.12, -0.18, 0.03)
        lucky = _clamp(middle + 0.07, 0.08, 0.20)
    elif speculative >= quality + 4 and speculative >= 50:
        kind = "gamble"
        headline = "More like a gamble than a piggy bank"
        blurb = (
            "This looks like a bet: it could grow a lot, or shrink a lot. "
            "Only think about money you could stand to lose. Do not use rent or food money."
        )
        middle = _clamp(hist if hist is not None else 0.10, -0.20, 0.22)
        tough = _clamp(middle - 0.35, -0.60, -0.08)
        lucky = _clamp(middle + 0.28, 0.12, 0.55)
    else:
        kind = "mixed"
        headline = "Not clearly safe, and not clearly a rocket"
        blurb = (
            "The numbers do not shout ‘steady business’ or ‘lottery ticket’. "
            "Treat it carefully and read the briefing before you do anything."
        )
        middle = _clamp(hist if hist is not None else 0.07, -0.05, 0.14)
        tough = _clamp(middle - 0.18, -0.30, 0.0)
        lucky = _clamp(middle + 0.12, 0.08, 0.28)

    summary = (snapshot.get("longBusinessSummary") or "").strip()
    one_liner = summary.split(". ")[0].strip()
    if one_liner and not one_liner.endswith("."):
        one_liner += "."
    if not one_liner:
        name = snapshot.get("name") or snapshot.get("ticker") or "This company"
        sector = snapshot.get("sector") or "its industry"
        one_liner = f"{name} is a {sector} company."

    past_10 = None
    if hist is not None and hist_years:
        past_10 = round(10 * (1 + hist) ** float(hist_years), 2)

    price = _num(snapshot.get("price"))
    target = _num(snapshot.get("targetMeanPrice"))
    analyst = None
    if price and target and price > 0:
        analyst = target / price - 1

    return {
        "kind": kind,
        "headline": headline,
        "blurb": blurb,
        "one_liner": one_liner,
        "quality_score": quality,
        "speculative_score": speculative,
        "longshot_score": longshot,
        "bear_score": bear,
        "bear_why": bear_why[:3],
        "endorsement_score": endorsement,
        "endorsement_why": endorsement_why[:3],
        "short_note": short_blurb(snapshot),
        "annual": {
            "tough": round(tough, 4),
            "middle": round(middle, 4),
            "lucky": round(lucky, 4),
        },
        "historical_cagr": hist,
        "historical_years": hist_years,
        "if_10_then": past_10,
        "last_year_return": history.get("return_1y"),
        "analyst_1y": analyst,
        "warning": (
            "Nobody can know what a share will be worth later. "
            "The three paths are a sketch from how the stock behaved before, stretched a bit for bad luck and good luck. "
            "You can get back less than you put in, including nothing."
        ),
    }
