from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from companyresearch import cache
from companyresearch.config import settings
from companyresearch.desk import jumpy_kind, kind_of, plan_pass
from companyresearch.net import yfinance_ticker
from companyresearch.screens import run_screens
from companyresearch.sources.market import fetch_snapshot, normalize_ticker

WALLET_PATH = settings.data_dir / "paper_wallet.json"
STARTING_GBP = 500.0
MIN_CASH = 2.0
MAX_HOLDINGS = 8
# Keep a pocket for tiny lottery / endorsement / short-hunted slices so steadier names cannot eat the whole pile.
RISK_POCKET_FRAC = 0.24
NOTE = (
    "Pretend money on this PC only. This app cannot see or touch pensions, "
    "banks, brokers, or any real account. A few days of fake pounds is not going live."
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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


def usd_to_gbp(usd: float) -> float:
    return float(usd) / dollars_per_pound()


def _price_usd(ticker: str) -> tuple[float, str]:
    snap = fetch_snapshot(ticker)
    price = snap.get("price") or snap.get("currentPrice") or snap.get("regularMarketPrice")
    if price is None:
        raise ValueError("No live price for this name.")
    name = snap.get("name") or ticker
    return float(price), str(name)


def _mark(data: dict[str, Any]) -> dict[str, Any]:
    fx = dollars_per_pound()
    holdings_value = 0.0
    valued = []
    for row in data.get("holdings") or []:
        ticker = row.get("ticker")
        shares = float(row.get("shares") or 0)
        spent = float(row.get("spent_gbp") or 0)
        name = row.get("name") or ticker
        now_gbp = None
        try:
            usd, live_name = _price_usd(ticker)
            name = live_name or name
            now_gbp = shares * (usd / fx)
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
        "fx_usd_per_gbp": round(fx, 4),
        "helper": {
            "started_gbp": round(starting, 2),
            "now_gbp": round(total, 2),
            "profit_gbp": round(total - starting, 2),
            "trade_count": len(trades),
            "endorsement_n": sum(1 for h in valued if h.get("kind") == "endorsement"),
            "bear_n": sum(1 for h in valued if h.get("kind") == "bear"),
            "note": (
                "Pretend helper scoreboard. It may use almost all fake cash after it has looked at a file. "
                "A good few days here is not a reason to go live. This app cannot take real money."
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
    usd, name = _price_usd(symbol)
    px_gbp = usd_to_gbp(usd)
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
    usd, name = _price_usd(symbol)
    now_gbp = float(row.get("shares") or 0) * usd_to_gbp(usd)
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
    """Size a pretend buy. `keep` is cash reserved for later risk tickets."""
    if cash < 10:
        return 0.0
    spendable = max(0.0, cash - max(0.0, keep))
    if spendable < 10:
        return 0.0
    jumpy = jumpy_kind(kind)
    cap = max(10.0, total * (0.14 if jumpy else 0.28))
    if size == "small":
        want = min(cap, max(10.0, total * 0.08), 40.0)
    elif size == "large":
        want = min(cap, max(10.0, total * 0.24))
    else:
        want = min(cap, max(10.0, total * 0.16))
    want = min(want, spendable)
    if want < 10:
        return 0.0
    leftover = cash - want
    # Only vacuum crumbs into a steadier name when nothing is reserved for risk.
    if keep <= 0 and leftover < 10 and leftover >= 0 and not jumpy:
        want = cash
    if cash - want < MIN_CASH and cash - want > 0 and keep <= 0 and not jumpy:
        want = cash
    return round(want, 2)


def _candidates(boards: dict[str, Any], held: set[str]) -> list[str]:
    # Risk tickets first so a pile of Apple-style names cannot spend the cash before them.
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


def _risk_kinds_held(holdings: list[dict[str, Any]]) -> set[str]:
    return {str(h.get("kind") or "") for h in holdings if jumpy_kind(str(h.get("kind") or ""))}


def _risk_pocket_needed(holdings: list[dict[str, Any]], total: float) -> float:
    held = _risk_kinds_held(holdings)
    missing = 0
    for kind in ("endorsement", "longshot", "bear"):
        if kind not in held:
            missing += 1
    if missing <= 0:
        return 0.0
    return round(max(30.0, total * RISK_POCKET_FRAC), 2)


def autopilot() -> dict[str, Any]:
    """Research, then buy/sell pretend money. Mostly steadier, with a reserved risk pocket. Never real accounts."""
    log: list[dict[str, Any]] = []
    marked = snapshot()
    boards = run_screens()
    held_rows = marked.get("holdings") or []
    held = {h.get("ticker") for h in held_rows if h.get("ticker")}
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    moves = plan_pass(held_rows, _candidates(boards, held), cash, total)

    for move in moves:
        if move.get("action") != "sell":
            continue
        ticker = move.get("ticker")
        why = move.get("why") or "Looked again and sold pretend."
        try:
            sell(ticker, reason=why)
            log.append({"action": "sell", "ticker": ticker, "why": why})
        except ValueError:
            continue

    marked = snapshot()
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    raw = load_wallet().get("holdings") or []
    held = {h.get("ticker") for h in raw if h.get("ticker")}
    now_of = {h.get("ticker"): float(h.get("now_gbp") or 0) for h in marked.get("holdings") or []}
    pocket = _risk_pocket_needed(raw, total)

    buy_moves = [m for m in moves if m.get("action") == "buy"]
    other_moves = [m for m in moves if m.get("action") in {"hold", "skip"}]
    for move in other_moves:
        log.append({"action": move.get("action"), "ticker": move.get("ticker") or "", "why": move.get("why") or ""})

    def _try_buy(move: dict[str, Any], *, keep: float) -> None:
        nonlocal cash, held, now_of, pocket, raw
        ticker = move.get("ticker")
        why = move.get("why") or ""
        if not ticker:
            return
        if cash < 10:
            log.append({"action": "skip", "ticker": ticker, "why": "Wanted to buy but pretend cash is gone this pass."})
            return
        if ticker not in held and len(held) >= MAX_HOLDINGS:
            log.append({"action": "skip", "ticker": ticker, "why": "Already have enough names. A person would not own the whole board."})
            return
        try:
            kind, _ = classify_ticker(ticker)
        except Exception:
            kind = "mixed"
        already = now_of.get(ticker, 0.0)
        cap = total * (0.14 if jumpy_kind(kind) else 0.28)
        room = max(0.0, cap - already)
        pool = min(cash, room) if ticker in held else cash
        amount = _stake_amount(str(move.get("size") or "medium"), kind, pool, total, keep=keep)
        if ticker in held:
            amount = min(amount, room)
        if amount < 10:
            log.append(
                {
                    "action": "skip",
                    "ticker": ticker,
                    "why": f"Looked at {ticker} but left cash for risk tickets / size limits.",
                }
            )
            return
        try:
            buy(ticker, amount, kind=kind, reason=why)
            log.append({"action": "buy", "ticker": ticker, "why": why})
            held.add(ticker)
            cash -= amount
            now_of[ticker] = now_of.get(ticker, 0.0) + amount
            raw = load_wallet().get("holdings") or []
            pocket = _risk_pocket_needed(raw, total)
        except ValueError as exc:
            log.append({"action": "skip", "ticker": ticker, "why": str(exc)})

    # Risk tickets first while the pocket is reserved.
    for move in buy_moves:
        ticker = move.get("ticker")
        try:
            kind, _ = classify_ticker(ticker) if ticker else ("mixed", None)
        except Exception:
            kind = "mixed"
        if jumpy_kind(kind):
            _try_buy(move, keep=0.0)

    # Then steadier names, keeping the pocket until risk slots are filled.
    for move in buy_moves:
        ticker = move.get("ticker")
        try:
            kind, _ = classify_ticker(ticker) if ticker else ("mixed", None)
        except Exception:
            kind = "mixed"
        if not jumpy_kind(kind):
            _try_buy(move, keep=pocket)

    marked = snapshot()
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    raw = load_wallet().get("holdings") or []
    held = {h.get("ticker") for h in raw if h.get("ticker")}
    pocket = _risk_pocket_needed(raw, total)

    # Fill missing risk tickets from the pocket, then put leftover into steadier names.
    if cash >= 10:
        for ticker in _candidates(boards, held):
            if cash < 10:
                break
            if ticker not in held and len(held) >= MAX_HOLDINGS:
                continue
            try:
                kind, _ = classify_ticker(ticker)
            except Exception:
                continue
            if not jumpy_kind(kind):
                continue
            if kind in _risk_kinds_held(raw):
                continue
            amount = _stake_amount("small", kind, cash, total, keep=0.0)
            if amount < 10:
                continue
            why = (
                f"Reserved a tiny pretend risk ticket in {ticker} (£{amount:.0f}, {kind}). "
                "Most of the pile stays in steadier names. Only fake money."
            )
            try:
                buy(ticker, amount, kind=kind, reason=why)
                log.append({"action": "buy", "ticker": ticker, "why": why})
                held.add(ticker)
                cash -= amount
                raw = load_wallet().get("holdings") or []
                pocket = _risk_pocket_needed(raw, total)
            except ValueError:
                continue

    marked = snapshot()
    cash = float(marked.get("cash_gbp") or 0)
    total = float(marked.get("total_gbp") or STARTING_GBP)
    raw = load_wallet().get("holdings") or []
    held = {h.get("ticker") for h in raw if h.get("ticker")}
    pocket = _risk_pocket_needed(raw, total)

    if cash >= 10:
        for ticker in _candidates(boards, held):
            if cash < 10:
                break
            if ticker not in held and len(held) >= MAX_HOLDINGS:
                continue
            try:
                kind, _ = classify_ticker(ticker)
            except Exception:
                continue
            if kind != "steadier":
                continue
            amount = _stake_amount("large", kind, cash, total, keep=pocket)
            if amount < 10:
                continue
            why = (
                f"Still had pretend £{amount:.0f} after the risk pocket. Looked at {ticker} — a real business on paper — and put it to work."
            )
            try:
                buy(ticker, amount, kind=kind, reason=why)
                log.append({"action": "buy", "ticker": ticker, "why": why})
                held.add(ticker)
                cash -= amount
                raw = load_wallet().get("holdings") or []
                pocket = _risk_pocket_needed(raw, total)
            except ValueError:
                continue

    if cash >= 10:
        log.append(
            {
                "action": "wait",
                "ticker": "",
                "why": f"Still £{cash:.0f} pretend cash idle (risk pocket or no clean name left).",
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
