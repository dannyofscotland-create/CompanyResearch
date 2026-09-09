from __future__ import annotations

import json
from typing import Any

from companyresearch import cache
from companyresearch.clues import confirm_attack, deepen_if_needed
from companyresearch.llm import complete_json
from companyresearch.screens import (
    _bear_score,
    _endorsement_score,
    _longshot_score,
    _quality_score,
    _speculative_score,
)
from companyresearch.sources.market import fetch_snapshot, normalize_ticker
from companyresearch.sources.news import search_angle

PLAN_SYS = """You run a pretend wallet in a free test. Research each name, then decide.
Goal of the test: see if your choices make or lose fake money — not to churn.
If after research you like a stock, BUY it. Size by conviction: large / medium / small.
Do NOT flip-flop. If hours_held is under 8, HOLD unless attack_level is confirmed with a named short report or going-concern.
Do NOT sell just because you re-read headlines that were already around when you bought.
SELL only for a real thesis break, confirmed attack, a serious loss after the hold period, or locking a large win after the hold period.
Hold when nothing important changed.
Skip a buy if the file is thin, attack_level is confirmed, or the name was sold recently (recently_sold).
Do NOT sell or skip because of Wikipedia, forums, video-game pages, or a headline that is not about this ticker.
Return ONLY JSON:
{"moves":[{"ticker":"X","action":"buy"|"sell"|"hold"|"skip","why":"plain words as if talking","size":"small"|"medium"|"large"}]}
This is pretend. Never tell anyone to hand over real cash.
"""

MIN_HOLD_HOURS = 8.0
CONFIRMED_HOLD_HOURS = 2.0
REBUY_COOLDOWN_HOURS = 24.0



def kind_of(snap: dict[str, Any]) -> str:
    quality, _ = _quality_score(snap)
    speculative, _ = _speculative_score(snap)
    longshot, _ = _longshot_score(snap)
    endorsement, _ = _endorsement_score(snap)
    bear, _ = _bear_score(snap)
    mcap = snap.get("marketCap")
    try:
        mcap_n = float(mcap) if mcap is not None else None
    except (TypeError, ValueError):
        mcap_n = None
    if endorsement >= 50:
        return "endorsement"
    if bear >= 55 and (quality < 56):
        return "bear"
    if longshot >= 52 and (mcap_n is None or mcap_n < 1.5e10):
        return "longshot"
    if quality >= speculative + 6 and quality >= 56:
        return "steadier"
    if speculative >= quality + 4 and speculative >= 50:
        return "gamble"
    return "mixed"


def assemble_file(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    cached = cache.get(f"desk:v3:{symbol}", ttl_seconds=25 * 60)
    if cached:
        return cached
    snap = fetch_snapshot(symbol)
    quality, q_why = _quality_score(snap)
    longshot, l_why = _longshot_score(snap)
    endorsement, e_why = _endorsement_score(snap)
    bear, b_why = _bear_score(snap)
    kind = kind_of(snap)
    name = str(snap.get("name") or symbol)
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(search_angle(f'"{symbol}" {name}', "news", "what is being written about this company", 6))
        rows.extend(search_angle(f'"{symbol}" {name} earnings OR results OR guidance', "news", "latest results", 4))
        rows.extend(
            search_angle(
                f'"{symbol}" {name} Hindenburg OR "short report" OR "going concern" OR dilution',
                "text",
                "is there an actual attack on this ticker",
                5,
            )
        )
    except Exception:
        rows = []
    headlines = [str(r.get("title") or "") for r in rows if r.get("title")][:8]
    attack = confirm_attack(symbol, name, rows)
    attack = deepen_if_needed(symbol, name, rows, attack)
    payload = {
        "ticker": symbol,
        "name": name,
        "kind": kind,
        "price": snap.get("price"),
        "profitMargins": snap.get("profitMargins"),
        "revenueGrowth": snap.get("revenueGrowth"),
        "debtToEquity": snap.get("debtToEquity"),
        "shortPercentOfFloat": snap.get("shortPercentOfFloat"),
        "quality": quality,
        "quality_why": q_why,
        "longshot": longshot,
        "endorsement": endorsement,
        "bear": bear,
        "headlines": headlines,
        "attack": attack,
        "attack_level": attack.get("level") or "clear",
        "crash_headline": attack.get("headline") if attack.get("level") == "confirmed" else None,
        "ugly": attack.get("level") == "confirmed",
        "ignored_junk": attack.get("ignored") or [],
        "why_bits": (q_why or l_why or e_why or b_why)[:3],
    }
    cache.put(f"desk:v3:{symbol}", payload)
    return payload


def jumpy_kind(kind: str) -> bool:
    return kind in {"longshot", "gamble", "endorsement", "bear"}


def heuristic_move(file: dict[str, Any], *, mode: str, pnl: float | None = None) -> dict[str, Any]:
    ticker = file["ticker"]
    kind = file.get("kind") or "mixed"
    ugly = file.get("attack_level") == "confirmed"
    quality = int(file.get("quality") or 0)
    hours_held = float(file.get("hours_held") or 999)
    recently_sold = bool(file.get("recently_sold"))
    headlines = [str(h) for h in (file.get("headlines") or []) if h][:3]
    bits = ", ".join(headlines) if headlines else "thin headlines"
    if mode == "review":
        drop = pnl if pnl is not None else 0.0
        # Fresh buys get a settle period — no "buy then regret next pass".
        if ugly and hours_held >= CONFIRMED_HOLD_HOURS:
            hit = file.get("crash_headline") or "a confirmed report about this company"
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Second look on {ticker}: confirmed trouble about this ticker ({hit}). Selling pretend.",
            }
        if hours_held < MIN_HOLD_HOURS:
            return {
                "ticker": ticker,
                "action": "hold",
                "size": "all",
                "why": (
                    f"Looked at {ticker} again after only ~{hours_held:.0f}h. "
                    "Giving the bet time to play — not flipping on a second skim."
                ),
            }
        if drop <= -0.25:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Looked again at {ticker}: pretend stake down about {abs(drop)*100:.0f}% after a fair hold. Cutting the loss.",
            }
        if drop >= 0.50:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"{ticker} is up about {drop*100:.0f}% on pretend money after a fair hold. Banking the test win.",
            }
        if file.get("attack_level") == "watch" and drop <= -0.12:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Looked at {ticker} again: proper ugly headline and down ~{abs(drop)*100:.0f}% after a fair hold. Selling.",
            }
        return {
            "ticker": ticker,
            "action": "hold",
            "size": "all",
            "why": f"Looked at {ticker} again. Still want it on the file ({bits}). Holding pretend.",
        }
    # buy
    if recently_sold:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Sold {ticker} recently. Not buying it straight back — that was the flip-flop.",
        }
    if ugly:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Looked at {ticker}. Confirmed trouble about this company, not a forum post. Not putting fake money in.",
        }
    if file.get("attack_level") == "watch" and jumpy_kind(kind):
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Looked at {ticker}: already on a watch for ugly headlines. Not buying into that for the test.",
        }
    if quality < 38 and kind in {"mixed", "gamble"} and not jumpy_kind(kind):
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Looked at {ticker}. File is too thin or messy. Skipping.",
        }
    if kind == "steadier" and quality >= 52:
        size = "large"
        why = f"Looked at {ticker}: already makes money on the public numbers. Buying for the test."
    elif jumpy_kind(kind):
        size = "medium" if quality >= 40 else "small"
        why = (
            f"Looked at {ticker} ({kind}). Research file is interesting enough for a real pretend bet "
            f"({bits}). Buying — and will hold it a while, not flip next pass."
        )
    elif quality >= 45:
        size = "large" if quality >= 58 else "medium"
        why = f"Looked at {ticker}: research looks ok ({bits}). Putting pretend money in."
    else:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Looked at {ticker}. Not convinced after research. Skipping.",
        }
    return {"ticker": ticker, "action": "buy", "size": size, "why": why}


def plan_pass(
    holding_rows: list[dict[str, Any]],
    candidate_tickers: list[str],
    cash: float,
    total: float,
    *,
    recently_sold: set[str] | None = None,
    hours_held_of: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Research holdings and candidates, then decide like a person. One LLM pass if available."""
    sold = {str(t).upper() for t in (recently_sold or set())}
    held_hours = {str(k).upper(): float(v) for k, v in (hours_held_of or {}).items()}
    files: list[dict[str, Any]] = []
    for row in holding_rows:
        ticker = row.get("ticker")
        if not ticker:
            continue
        try:
            file = assemble_file(ticker)
        except Exception as exc:
            files.append({"ticker": ticker, "kind": row.get("kind"), "error": str(exc), "mode": "review"})
            continue
        spent = float(row.get("spent_gbp") or 0) or 1.0
        now = float(row.get("now_gbp") or 0)
        file["mode"] = "review"
        file["pnl"] = (now - spent) / spent
        file["spent_gbp"] = spent
        file["now_gbp"] = now
        file["hours_held"] = held_hours.get(str(ticker).upper(), 999.0)
        files.append(file)
    seen = {f.get("ticker") for f in files}
    for ticker in candidate_tickers:
        if ticker in seen:
            continue
        try:
            file = assemble_file(ticker)
        except Exception:
            continue
        file["mode"] = "buy"
        file["recently_sold"] = str(ticker).upper() in sold
        files.append(file)
        seen.add(ticker)
        if sum(1 for f in files if f.get("mode") == "buy") >= 10:
            break

    planned = _llm_plan(files, cash, total)
    if planned:
        return _calm_moves(planned, files)

    moves = []
    for file in files:
        mode = file.get("mode") or "buy"
        moves.append(heuristic_move(file, mode=mode, pnl=file.get("pnl")))
    return moves


def _calm_moves(moves: list[dict[str, Any]], files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Block junk panic sells and stop buy→regret churn before the hold period ends."""
    by = {str(f.get("ticker") or "").upper(): f for f in files}
    out = []
    for move in moves:
        ticker = str(move.get("ticker") or "").upper()
        file = by.get(ticker) or {}
        level = file.get("attack_level") or "clear"
        action = move.get("action")
        why = str(move.get("why") or "").lower()
        hours_held = float(file.get("hours_held") or 999)
        junk_scare = any(w in why for w in ("wikipedia", "forum", "reddit", "wiki", "video game", "fandom"))
        if action == "sell" and file.get("mode") == "review":
            if level == "clear" and junk_scare:
                move = {
                    **move,
                    "action": "hold",
                    "why": "Wanted to sell on a junk page. Wikipedia/forums do not count. Holding.",
                }
            elif level == "confirmed" and hours_held < CONFIRMED_HOLD_HOURS:
                move = {
                    **move,
                    "action": "hold",
                    "why": f"Trouble headline on {ticker}, but only held ~{hours_held:.0f}h. Waiting a bit before dumping.",
                }
            elif level != "confirmed" and hours_held < MIN_HOLD_HOURS:
                move = {
                    **move,
                    "action": "hold",
                    "why": (
                        f"Wanted to sell {ticker} after only ~{hours_held:.0f}h. "
                        "Not flip-flopping on a second skim — holding."
                    ),
                }
        if action == "buy" and file.get("recently_sold"):
            move = {
                **move,
                "action": "skip",
                "why": f"Sold {ticker} recently. Not buying it straight back.",
            }
        out.append(move)
    return out


def _llm_plan(files: list[dict[str, Any]], cash: float, total: float) -> list[dict[str, Any]] | None:
    slim = []
    for file in files:
        slim.append(
            {
                "ticker": file.get("ticker"),
                "name": file.get("name"),
                "mode": file.get("mode"),
                "kind": file.get("kind"),
                "quality": file.get("quality"),
                "pnl": file.get("pnl"),
                "hours_held": file.get("hours_held"),
                "recently_sold": bool(file.get("recently_sold")),
                "headlines": (file.get("headlines") or [])[:5],
                "attack_level": file.get("attack_level") or "clear",
                "attack_hits": (file.get("attack") or {}).get("hits") or [],
                "ignored_junk": (file.get("ignored_junk") or [])[:4],
                "profitMargins": file.get("profitMargins"),
                "why_bits": file.get("why_bits"),
            }
        )
    payload = {
        "cash_gbp": round(cash, 2),
        "total_gbp": round(total, 2),
        "note": "Free test: buy what research likes, sell when you change your mind. Leave only crumbs idle.",
        "desk": slim,
    }
    try:
        out = complete_json(PLAN_SYS, json.dumps(payload, default=str)[:12000])
    except Exception:
        return None
    if not isinstance(out, dict):
        return None
    rows = out.get("moves")
    if not isinstance(rows, list) or not rows:
        return None
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").lower()
        ticker = str(row.get("ticker") or "").upper().strip()
        if action not in {"buy", "sell", "hold", "skip"} or not ticker:
            continue
        size = str(row.get("size") or "medium").lower()
        if size not in {"small", "medium", "large", "all"}:
            size = "medium"
        why = str(row.get("why") or "Looked at the file and decided.").strip()
        clean.append({"ticker": ticker, "action": action, "size": size, "why": why})
    return clean or None
