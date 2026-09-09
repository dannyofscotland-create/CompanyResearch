from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from companyresearch import cache
from companyresearch.config import settings
from companyresearch.desk import (
    REBUY_COOLDOWN_HOURS,
    assemble_file,
    heuristic_move,
    kind_of,
    plan_pass,
)
from companyresearch.net import yfinance_ticker
from companyresearch.screens import run_screens
from companyresearch.sources.market import fetch_snapshot, normalize_ticker

WALLET_PATH = settings.data_dir / "paper_wallet.json"
STARTING_GBP = 500.0
MIN_CASH = 2.0
MAX_HOLDINGS = 12
NOTE = (
    "Pretend money on this PC only. This app cannot see or touch pensions, "
    "banks, brokers, or any real account. A few days of fake pounds is not going live."
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _parse_when(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            if fmt.endswith("Z"):
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            if "%z" in fmt:
                return datetime.strptime(text.replace("Z", "+0000"), fmt.replace("%z", "%z"))
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _hours_ago(when: Any) -> float | None:
    dt = _parse_when(when)
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def _hours_held_map(data: dict[str, Any]) -> dict[str, float]:
    trades = data.get("trades") or []
    out: dict[str, float] = {}
    for row in data.get("holdings") or []:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        hours = _hours_ago(row.get("bought_at"))
        if hours is None:
            for trade in reversed(trades):
                if trade.get("action") == "buy" and str(trade.get("ticker") or "").upper() == ticker:
                    hours = _hours_ago(trade.get("when"))
                    break
        out[ticker] = float(hours if hours is not None else 999.0)
    return out


def _recently_sold_set(data: dict[str, Any], *, within_hours: float = REBUY_COOLDOWN_HOURS) -> set[str]:
    sold: set[str] = set()
    for trade in reversed(data.get("trades") or []):
        if trade.get("action") != "sell":
            continue
        ticker = str(trade.get("ticker") or "").upper()
        hours = _hours_ago(trade.get("when"))
        if ticker and hours is not None and hours <= within_hours:
            sold.add(ticker)
    return sold


def _empty() -> dict[str, Any]:
    return {
        "starting_gbp": STARTING_GBP,
        "cash_gbp": STARTING_GBP,
        "holdings": [],
        "trades": [],
        "last_autopilot": [],
        "note": NOTE,
    }


def load_wallet() -> dict[str, Any]:
    WALLET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not WALLET_PATH.exists():
        data = _empty()
        save_wallet(data)
        return data
    try:
        data = json.loads(WALLET_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = _empty()
    data.setdefault("holdings", [])
    data.setdefault("trades", [])
    data.setdefault("last_autopilot", [])
    data.setdefault("starting_gbp", STARTING_GBP)
    data.setdefault("cash_gbp", STARTING_GBP)
    data["note"] = NOTE
    return data


def save_wallet(data: dict[str, Any]) -> None:
    WALLET_PATH.parent.mkdir(parents=True, exist_ok=True)
    WALLET_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def dollars_per_pound() -> float:
    cached = cache.get("fx:gbpusd", ttl_seconds=60 * 60)
    if cached:
        return float(cached)
    rate = 1.27
    try:
        stock = yfinance_ticker("GBPUSD=X")
        info = stock.info or {}
        raw = info.get("regularMarketPrice") or info.get("previousClose") or info.get("bid")
        if raw:
            rate = float(raw)
    except Exception:
        pass
    if rate <= 0.5 or rate > 3:
        rate = 1.27
    cache.put("fx:gbpusd", rate)
    return rate


def _fx_pair_rate(pair: str) -> float | None:
    cached = cache.get(f"fx:{pair}", ttl_seconds=60 * 60)
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            return None
    try:
        stock = yfinance_ticker(pair)
        info = stock.info or {}
        raw = info.get("regularMarketPrice") or info.get("previousClose") or info.get("bid")
        if raw is None:
            return None
        rate = float(raw)
        if rate <= 0:
            return None
        cache.put(f"fx:{pair}", rate)
        return rate
    except Exception:
        return None


def currency_to_gbp(amount: float, currency: str | None) -> float:
    """Turn a local market price into pounds (handles GBp pence and major FX)."""
    raw = currency or "USD"
    value = float(amount)
    # Yahoo lists many London names in pence.
    if raw in {"GBp", "GBX"} or raw == "ZAc" or raw == "ILA":
        value /= 100.0
        raw = "GBP" if raw in {"GBp", "GBX"} else ("ZAR" if raw == "ZAc" else "ILS")
    cur = raw.upper()
    if cur == "GBP":
        return value
    if cur == "USD":
        return value / dollars_per_pound()
    direct = _fx_pair_rate(f"{cur}GBP=X")
    if direct:
        return value * direct
    inverse = _fx_pair_rate(f"GBP{cur}=X")
    if inverse:
        return value / inverse
    # Last resort: via USD.
    via_usd = _fx_pair_rate(f"{cur}USD=X")
    if via_usd:
        return (value * via_usd) / dollars_per_pound()
    usd_via = _fx_pair_rate(f"USD{cur}=X")
    if usd_via:
        return (value / usd_via) / dollars_per_pound()
    return value / dollars_per_pound()


def usd_to_gbp(usd: float) -> float:
    return currency_to_gbp(usd, "USD")


def _price_gbp(ticker: str) -> tuple[float, str, str]:
    snap = fetch_snapshot(ticker)
    price = snap.get("price") or snap.get("currentPrice") or snap.get("regularMarketPrice")
    if price is None:
        raise ValueError("No live price for this name.")
    currency = str(snap.get("currency") or "USD")
    name = snap.get("name") or ticker
    return currency_to_gbp(float(price), currency), str(name), currency


def _mark(data: dict[str, Any]) -> dict[str, Any]:
    valued = []
    holdings_value = 0.0
    for row in data.get("holdings") or []:
        ticker = row.get("ticker")
        shares = float(row.get("shares") or 0)
        spent = float(row.get("spent_gbp") or 0)
        name = row.get("name") or ticker
        now_gbp = None
        try:
            px_gbp, live_name, _currency = _price_gbp(ticker)
            name = live_name or name
            now_gbp = shares * px_gbp
        except Exception:
            now_gbp = spent
        holdings_value += now_gbp
        valued.append(
            {
                "ticker": ticker,
                "name": name,
                "shares": round(shares, 6),
                "spent_gbp": round(spent, 2),
                "now_gbp": round(now_gbp, 2),
                "change_gbp": round(now_gbp - spent, 2),
                "kind": row.get("kind") or "mixed",
            }
        )
    cash = float(data.get("cash_gbp") or 0)
    starting = float(data.get("starting_gbp") or STARTING_GBP)
    total = cash + holdings_value
    trades = data.get("trades") or []
    return {
        "note": NOTE,
        "starting_gbp": round(starting, 2),
        "cash_gbp": round(cash, 2),
        "holdings_gbp": round(holdings_value, 2),
        "total_gbp": round(total, 2),
        "profit_gbp": round(total - starting, 2),
        "holdings": valued,
        "trades": trades[-12:][::-1],
        "last_autopilot": data.get("last_autopilot") or [],
        "fx_usd_per_gbp": round(dollars_per_pound(), 4),
        "helper": {
            "started_gbp": round(starting, 2),
            "now_gbp": round(total, 2),
            "profit_gbp": round(total - starting, 2),
            "trade_count": len(trades),
            "endorsement_n": sum(1 for h in valued if h.get("kind") == "endorsement"),
            "bear_n": sum(1 for h in valued if h.get("kind") == "bear"),
            "note": (
                "Pretend helper scoreboard across world markets (Yahoo tickers). "
                "Prices are converted into pretend pounds. Not a real broker."
            ),
        },
    }


def snapshot() -> dict[str, Any]:
    return _mark(load_wallet())


def reset() -> dict[str, Any]:
    data = _empty()
    save_wallet(data)
    return _mark(data)


def classify_ticker(ticker: str) -> tuple[str, dict[str, Any]]:
    symbol = normalize_ticker(ticker)
    snap = fetch_snapshot(symbol)
    return kind_of(snap), snap


def buy(ticker: str, amount_gbp: float, kind: str | None = None, reason: str | None = None) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    amount = round(float(amount_gbp), 2)
    if amount < 1:
        raise ValueError("Put in at least £1 of pretend money.")
    data = load_wallet()
    cash = float(data.get("cash_gbp") or 0)
    if amount > cash + 1e-9:
        raise ValueError(f"Only £{cash:.2f} pretend cash left.")
    px_gbp, name, _currency = _price_gbp(symbol)
    if px_gbp <= 0:
        raise ValueError("Could not turn the share price into pounds.")
    shares = amount / px_gbp
    holdings = data.get("holdings") or []
    found = None
    for row in holdings:
        if row.get("ticker") == symbol:
            found = row
            break
    if not kind:
        try:
            kind, _ = classify_ticker(symbol)
        except Exception:
            kind = "mixed"
    if found:
        found["shares"] = float(found.get("shares") or 0) + shares
        found["spent_gbp"] = float(found.get("spent_gbp") or 0) + amount
        found["name"] = name
        found["kind"] = kind
        found["bought_at"] = _now()
        if reason:
            found["thesis"] = reason
    else:
        holdings.append(
            {
                "ticker": symbol,
                "name": name,
                "shares": shares,
                "spent_gbp": amount,
                "kind": kind,
                "thesis": reason or "",
                "bought_at": _now(),
            }
        )
    data["holdings"] = holdings
    data["cash_gbp"] = cash - amount
    data.setdefault("trades", []).append(
        {
            "when": _now(),
            "action": "buy",
            "ticker": symbol,
            "name": name,
            "gbp": amount,
            "why": reason or "You put pretend money in.",
        }
    )
    save_wallet(data)
    return _mark(data)


def sell(ticker: str, reason: str | None = None) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    data = load_wallet()
    holdings = data.get("holdings") or []
    row = next((h for h in holdings if h.get("ticker") == symbol), None)
    if not row:
        raise ValueError("You do not hold that name in the pretend wallet.")
    px_gbp, name, _currency = _price_gbp(symbol)
    now_gbp = float(row.get("shares") or 0) * px_gbp
    data["cash_gbp"] = float(data.get("cash_gbp") or 0) + now_gbp
    data["holdings"] = [h for h in holdings if h.get("ticker") != symbol]
    data.setdefault("trades", []).append(
        {
            "when": _now(),
            "action": "sell",
            "ticker": symbol,
            "name": name,
            "gbp": round(now_gbp, 2),
            "why": reason or "You sold the pretend holding.",
        }
    )
    save_wallet(data)
    return _mark(data)


def _stake_amount(size: str, kind: str, cash: float, total: float, *, keep: float = 0.0) -> float:
    """Size a pretend buy from research conviction. `keep` is unused in free-test mode."""
    if cash < 10:
        return 0.0
    spendable = max(0.0, cash - max(0.0, keep))
    if spendable < 10:
        return 0.0
    # Free test: let research size the bet — large can be a real chunk of the pile.
    if size == "small":
        want = min(max(10.0, total * 0.10), 60.0, spendable)
    elif size == "large":
        want = min(max(10.0, total * 0.40), spendable)
    else:
        want = min(max(10.0, total * 0.22), spendable)
    leftover = cash - want
    if leftover < MIN_CASH and leftover >= 0:
        want = cash
    return round(want, 2)


def _candidates(boards: dict[str, Any], held: set[str]) -> list[str]:
    order = ("endorsement", "longshot", "bear", "quality", "speculative")
    out: list[str] = []
    seen: set[str] = set(held)
    for key in order:
        for item in boards.get(key) or []:
            ticker = item.get("ticker")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            out.append(ticker)
    return out


def autopilot() -> dict[str, Any]:
    """Research, then freely buy/sell pretend money for the test. Never real accounts."""
    log: list[dict[str, Any]] = []
    marked = snapshot()
    wallet = load_wallet()
    boards = run_screens()
    held_rows = marked.get("holdings") or []
    held = {h.get("ticker") for h in held_rows if h.get("ticker")}
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    sold_recent = _recently_sold_set(wallet)
    hours_held = _hours_held_map(wallet)
    moves = plan_pass(
        held_rows,
        _candidates(boards, held),
        cash,
        total,
        recently_sold=sold_recent,
        hours_held_of=hours_held,
    )

    for move in moves:
        if move.get("action") != "sell":
            continue
        ticker = move.get("ticker")
        why = move.get("why") or "Looked again and sold pretend."
        try:
            sell(ticker, reason=why)
            log.append({"action": "sell", "ticker": ticker, "why": why})
            if ticker:
                sold_recent.add(str(ticker).upper())
        except ValueError:
            continue

    marked = snapshot()
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    raw = load_wallet().get("holdings") or []
    held = {h.get("ticker") for h in raw if h.get("ticker")}
    now_of = {h.get("ticker"): float(h.get("now_gbp") or 0) for h in marked.get("holdings") or []}

    buy_moves = [m for m in moves if m.get("action") == "buy"]
    other_moves = [m for m in moves if m.get("action") in {"hold", "skip"}]
    for move in other_moves:
        log.append({"action": move.get("action"), "ticker": move.get("ticker") or "", "why": move.get("why") or ""})

    def _try_buy(move: dict[str, Any]) -> None:
        nonlocal cash, held, now_of
        ticker = move.get("ticker")
        why = move.get("why") or ""
        if not ticker:
            return
        if str(ticker).upper() in sold_recent:
            log.append(
                {
                    "action": "skip",
                    "ticker": ticker,
                    "why": f"Sold {ticker} recently. Not buying it straight back — that was the flip-flop.",
                }
            )
            return
        if cash < 10:
            log.append({"action": "skip", "ticker": ticker, "why": "Wanted to buy but pretend cash is gone this pass."})
            return
        if ticker not in held and len(held) >= MAX_HOLDINGS:
            log.append({"action": "skip", "ticker": ticker, "why": "Wallet full — sell something first if you want this name."})
            return
        try:
            kind, _ = classify_ticker(ticker)
        except Exception:
            kind = "mixed"
        amount = _stake_amount(str(move.get("size") or "medium"), kind, cash, total, keep=0.0)
        if amount < 10:
            log.append({"action": "skip", "ticker": ticker, "why": f"Liked {ticker} but not enough pretend cash left to size a bet."})
            return
        try:
            buy(ticker, amount, kind=kind, reason=why)
            log.append({"action": "buy", "ticker": ticker, "why": why})
            held.add(ticker)
            cash -= amount
            now_of[ticker] = now_of.get(ticker, 0.0) + amount
        except ValueError as exc:
            log.append({"action": "skip", "ticker": ticker, "why": str(exc)})

    for move in buy_moves:
        _try_buy(move)

    # If research left cash idle, keep shopping candidates it would like — no forced steadier bias.
    marked = snapshot()
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    raw = load_wallet().get("holdings") or []
    held = {h.get("ticker") for h in raw if h.get("ticker")}
    if cash >= 15:
        extra_deep = 0
        for ticker in _candidates(boards, held):
            if cash < 15:
                break
            if ticker not in held and len(held) >= MAX_HOLDINGS:
                break
            if str(ticker).upper() in sold_recent:
                continue
            if extra_deep >= 3:
                break
            try:
                file = assemble_file(ticker, deep=True)
                extra_deep += 1
                file["recently_sold"] = str(ticker).upper() in sold_recent
                move = heuristic_move(file, mode="buy")
            except Exception:
                continue
            if move.get("action") != "buy":
                if move.get("action") == "skip":
                    log.append(
                        {
                            "action": "skip",
                            "ticker": ticker,
                            "why": move.get("why") or "Full research said skip.",
                        }
                    )
                continue
            _try_buy(move)
            cash = float(snapshot().get("cash_gbp") or 0)
            held = {h.get("ticker") for h in (load_wallet().get("holdings") or []) if h.get("ticker")}

    if cash >= 10:
        log.append(
            {
                "action": "wait",
                "ticker": "",
                "why": f"Still £{cash:.0f} pretend cash idle — no research buy left this pass.",
            }
        )

    if not log:
        log.append(
            {
                "action": "wait",
                "ticker": "",
                "why": "Looked at the desk. Nothing to buy or sell this pass.",
            }
        )
    data = load_wallet()
    data["last_autopilot"] = [{"when": _now(), **item} for item in log[:16]]
    save_wallet(data)
    out = snapshot()
    out["last_autopilot"] = data["last_autopilot"]
    return out
