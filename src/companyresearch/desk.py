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

PLAN_SYS = """You are a careful person with a pretend wallet. Research first, then decide.
Use most of the fake cash on steadier businesses that already make money.
Also take a FEW tiny risks: one endorsement/Trump-shaped name, one long shot, and/or one short-hunted name if those files look ok.
Do not put most of the pile in one lottery. Do not fill the whole wallet with only Apple-style names and leave no risk tickets.
Do NOT sell or skip because of Wikipedia, forums, video-game pages, or a headline that is not about this ticker.
A dismissed lawsuit is not a crash. Short interest alone is not a sell.
Only treat attack_level "confirmed" as a real crash campaign (a named short report or two proper news sources about THIS company).
"watch" means keep an eye on it, not dump.
Sell if the business story broke, attack_level is confirmed, or a jumpy name already doubled.
Hold if nothing important changed.
Skip a buy only if the file is thin or attack_level is confirmed.
Return ONLY JSON:
{"moves":[{"ticker":"X","action":"buy"|"sell"|"hold"|"skip","why":"plain words as if talking","size":"small"|"medium"|"large"}]}
This is pretend. Never tell anyone to hand over real cash.
"""


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
    if mode == "review":
        drop = pnl if pnl is not None else 0.0
        if jumpy_kind(kind) and drop <= -0.25:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Looked again at {ticker}: jumpy and the pretend stake is down about {abs(drop)*100:.0f}%. Selling.",
            }
        if kind == "steadier" and drop <= -0.35:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Looked again at {ticker}: even a steadier name should not be down ~{abs(drop)*100:.0f}% without a think. Selling.",
            }
        if jumpy_kind(kind) and drop >= 1.0:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"{ticker} roughly doubled on pretend money. Taking the fake chips off the table.",
            }
        if ugly:
            hit = file.get("crash_headline") or "a confirmed report about this company"
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Second look on {ticker}: confirmed trouble about this ticker ({hit}). Selling pretend.",
            }
        watch = file.get("attack_level") == "watch"
        extra = " One proper headline looks ugly, so watching — not dumping." if watch else ""
        return {
            "ticker": ticker,
            "action": "hold",
            "size": "all",
            "why": f"Looked at {ticker} again. No confirmed crash campaign. Holding pretend.{extra}",
        }
    # buy
    if ugly:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Looked at {ticker}. Confirmed trouble about this company, not a forum post. Not putting fake money in.",
        }
    if kind == "steadier" and quality >= 56:
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "large",
            "why": f"Looked at {ticker}: already makes money on the public numbers. That looks good enough for pretend. Investing.",
        }
    if kind == "endorsement":
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "small",
            "why": f"Looked at {ticker}: endorsement lottery. Tiny pretend slice so we can watch — not a plan.",
        }
    if kind == "bear":
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "small",
            "why": f"Looked at {ticker}: shorts pick on this shape. Tiny pretend slice. Will sell only if a confirmed report about this company shows up.",
        }
    if kind == "longshot" and quality < 56:
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "small",
            "why": f"Looked at {ticker}: long-shot shape. Tiny pretend lottery ticket. Most of these fail.",
        }
    if quality >= 48:
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "medium",
            "why": f"Looked at {ticker}: not a piggy bank, not nothing. Putting some pretend money in.",
        }
    return {
        "ticker": ticker,
        "action": "skip",
        "size": "small",
        "why": f"Looked at {ticker}. File is too thin or messy. Skipping.",
    }


def plan_pass(
    holding_rows: list[dict[str, Any]],
    candidate_tickers: list[str],
    cash: float,
    total: float,
) -> list[dict[str, Any]]:
    """Research holdings and candidates, then decide like a person. One LLM pass if available."""
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
        files.append(file)
        seen.add(ticker)
        if sum(1 for f in files if f.get("mode") == "buy") >= 6:
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
    """Do not let a twitchy language model dump Coca-Cola because Wikipedia said ‘pump and dump’."""
    by = {str(f.get("ticker") or "").upper(): f for f in files}
    out = []
    for move in moves:
        ticker = str(move.get("ticker") or "").upper()
        file = by.get(ticker) or {}
        level = file.get("attack_level") or "clear"
        action = move.get("action")
        if action == "sell" and file.get("mode") == "review" and level != "confirmed":
            drop = float(file.get("pnl") or 0)
            kind = file.get("kind") or "mixed"
            if not (jumpy_kind(kind) and (drop <= -0.25 or drop >= 1.0)) and not (
                kind == "steadier" and drop <= -0.35
            ):
                move = {
                    **move,
                    "action": "hold",
                    "why": (
                        move.get("why")
                        or "Wanted to sell, but the scare was not a confirmed story about this company."
                    )
                    + " Holding. Wikipedia/forums do not count.",
                }
        if action == "skip" and file.get("mode") == "buy" and level != "confirmed":
            move = heuristic_move(file, mode="buy", pnl=file.get("pnl"))
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
        "note": "Use the fake cash. Leave only crumbs idle. Split across names.",
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
