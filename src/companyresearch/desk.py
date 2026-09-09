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

PLAN_SYS = """You run a pretend wallet like a professional investor with a months-to-couple-years horizon — not a 10-year pension autopilot, and not a meme lottery.
CRITICAL: only BUY if research_depth is "full".
Pros buy: (1) quality growth — real businesses with profits and/or rising revenue, (2) a researched opportunity sleeve when the file is strong.
Pros avoid: endorsement/meme pumps, buying on a skim, ignoring confirmed short reports.
Allocation vibe: most of the pile in quality/growth, up to about 40% in higher-upside researched names (longshot/bear/gamble) if the dig clears.
SELL when the thesis breaks, confirmed attack, a real loss after the hold period, or bank a solid gain (~20%+) — do not sit forever on a flat defensive name if better researched growth exists.
Do NOT flip under ~4 hours held unless attack_level is confirmed.
Skip recently_sold. Skip endorsement lotteries.
Do NOT sell on Wikipedia/forums.
Return ONLY JSON:
{"moves":[{"ticker":"X","action":"buy"|"sell"|"hold"|"skip","why":"plain words as if talking","size":"small"|"medium"|"large"}]}
This is pretend. Never tell anyone to hand over real cash.
"""

MIN_HOLD_HOURS = 4.0
CONFIRMED_HOLD_HOURS = 1.5
REBUY_COOLDOWN_HOURS = 18.0
# Higher-upside sleeve (researched) — pros take measured risk for return.
RISK_MAX_FRAC = 0.40



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


def assemble_file(ticker: str, *, deep: bool = False) -> dict[str, Any]:
    """Build a research file. deep=True = full pre-buy dig (must finish before any buy)."""
    symbol = normalize_ticker(ticker)
    cache_key = f"desk:v6:{'deep' if deep else 'lite'}:{symbol}"
    cached = cache.get(cache_key, ttl_seconds=(50 if deep else 25) * 60)
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
                f'"{symbol}" {name} Hindenburg OR Kerrisdale OR "short report" OR "going concern" OR dilution OR fraud',
                "text",
                "is there an actual attack on this ticker",
                6,
            )
        )
        if deep:
            rows.extend(
                search_angle(
                    f'"{symbol}" {name} lawsuit OR investigation OR SEC OR "class action"',
                    "news",
                    "legal or regulator trouble",
                    5,
                )
            )
            rows.extend(
                search_angle(
                    f'"{symbol}" {name} bankruptcy OR "going concern" OR offering OR dilution OR "share sale"',
                    "text",
                    "cash and dilution risk",
                    5,
                )
            )
            rows.extend(
                search_angle(
                    f'"{symbol}" {name} "earnings beat" OR "raises guidance" OR "analyst upgrade" OR institutional',
                    "news",
                    "what pros watch: earnings and institutional flow",
                    5,
                )
            )
            rows.extend(
                search_angle(
                    f'"{symbol}" {name} why stock dropped OR selloff OR risks OR overvalued',
                    "text",
                    "bear case before buying",
                    5,
                )
            )
    except Exception:
        rows = []
    headlines = [str(r.get("title") or "") for r in rows if r.get("title")][:10]
    attack = confirm_attack(symbol, name, rows)
    if deep:
        attack = _prebuy_vet(symbol, name, rows, attack)
    else:
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
        "research_depth": "full" if deep else "lite",
        "researched": True if deep else False,
    }
    cache.put(cache_key, payload)
    return payload


def _prebuy_vet(ticker: str, name: str, sources: list[dict[str, Any]], attack: dict[str, Any]) -> dict[str, Any]:
    """Open real pages before buying — do not buy on headlines alone."""
    from companyresearch.sources.pages import fetch_snippet

    attack = deepen_if_needed(ticker, name, sources, attack)
    opened = 0
    for item in sources:
        if opened >= 4:
            break
        url = item.get("url") or ""
        title = str(item.get("title") or "")
        if not url or not title:
            continue
        blob = f"{title} {item.get('summary') or ''}"
        if not any(
            w in blob.lower()
            for w in (
                "short",
                "lawsuit",
                "fraud",
                "concern",
                "dilution",
                "offering",
                "investigation",
                "bankrupt",
                "halt",
                "overvalued",
                "risk",
                "loss",
                "miss",
            )
        ):
            continue
        snippet = fetch_snippet(url, max_chars=900)
        if not snippet:
            continue
        opened += 1
        item["excerpt"] = snippet[:400]
        # Re-score with excerpts folded into titles for confirm_attack
        enriched = []
        for src in sources:
            row = dict(src)
            if src.get("excerpt"):
                row["summary"] = f"{src.get('summary') or ''} {src['excerpt']}"
            enriched.append(row)
        attack = confirm_attack(ticker, name, enriched)
        attack = deepen_if_needed(ticker, name, enriched, attack)
    attack["prebuy_pages_opened"] = opened
    attack["note"] = (
        (attack.get("note") or "")
        + f" Pre-buy dig opened {opened} page(s) before any pretend money moves."
    ).strip()
    return attack


def jumpy_kind(kind: str) -> bool:
    return kind in {"longshot", "gamble", "endorsement", "bear"}


def _num_field(file: dict[str, Any], key: str) -> float | None:
    try:
        value = file.get(key)
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pro_growth(file: dict[str, Any]) -> bool:
    """Rough 'pro growth' tell: rising sales and/or real profits."""
    growth = _num_field(file, "revenueGrowth")
    margins = _num_field(file, "profitMargins")
    quality = int(file.get("quality") or 0)
    if margins is not None and margins > 0.08 and quality >= 52:
        return True
    if growth is not None and growth >= 0.12 and quality >= 48:
        return True
    if growth is not None and growth >= 0.20:
        return True
    return False


def heuristic_move(file: dict[str, Any], *, mode: str, pnl: float | None = None) -> dict[str, Any]:
    ticker = file["ticker"]
    kind = file.get("kind") or "mixed"
    ugly = file.get("attack_level") == "confirmed"
    quality = int(file.get("quality") or 0)
    hours_held = float(file.get("hours_held") or 999)
    recently_sold = bool(file.get("recently_sold"))
    risk_ok = file.get("risk_room", True)
    growth = _pro_growth(file)
    headlines = [str(h) for h in (file.get("headlines") or []) if h][:3]
    bits = ", ".join(headlines) if headlines else "thin headlines"
    if mode == "review":
        drop = pnl if pnl is not None else 0.0
        if ugly and hours_held >= CONFIRMED_HOLD_HOURS:
            hit = file.get("crash_headline") or "a confirmed report about this company"
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Second look on {ticker}: confirmed trouble ({hit}). Pros cut when the story breaks.",
            }
        if hours_held < MIN_HOLD_HOURS:
            return {
                "ticker": ticker,
                "action": "hold",
                "size": "all",
                "why": f"Only ~{hours_held:.0f}h in {ticker}. Pros do not flip every skim.",
            }
        # Bank gains on a pro horizon — do not wait a decade.
        if drop >= 0.22:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"{ticker} up ~{drop*100:.0f}%. Banking like a pro and freeing cash for the next researched idea.",
            }
        if jumpy_kind(kind) and drop <= -0.16:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"Higher-upside {ticker} down ~{abs(drop)*100:.0f}%. Cutting the loser — pros do not marry names.",
            }
        if not jumpy_kind(kind) and drop <= -0.22:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"{ticker} down ~{abs(drop)*100:.0f}% after a fair hold. Thesis soft — rotating.",
            }
        # Flat defensive names: free cash if something better may exist (mild nudge via sell of dead money).
        if kind == "steadier" and not growth and -0.03 <= drop <= 0.05 and hours_held >= 48:
            return {
                "ticker": ticker,
                "action": "sell",
                "size": "all",
                "why": f"{ticker} is flat/defensive with little growth tell. Rotating toward stronger growth research.",
            }
        return {
            "ticker": ticker,
            "action": "hold",
            "size": "all",
            "why": f"{ticker} still fits a pro-style book ({bits}). Holding.",
        }
    if recently_sold:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Sold {ticker} recently. Not buying it straight back.",
        }
    if file.get("research_depth") != "full":
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Research on {ticker} not finished. Pros do not buy headlines only.",
        }
    if ugly:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Confirmed trouble on {ticker}. Pros pass.",
        }
    if kind == "endorsement":
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Skipping {ticker} endorsement/meme shape — not how pros size a book.",
        }
    if jumpy_kind(kind) and file.get("attack_level") == "watch":
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Watch flag on higher-upside {ticker}. Passing until cleaner.",
        }
    if jumpy_kind(kind) and not risk_ok:
        return {
            "ticker": ticker,
            "action": "skip",
            "size": "small",
            "why": f"Opportunity sleeve full — skipped {ticker}. Keeping room in the book.",
        }
    pages = int((file.get("attack") or {}).get("prebuy_pages_opened") or 0)
    dig = f" after opening {pages} page(s)" if pages else " after full dig"
    # Core: quality growth (pro bread and butter).
    if (kind == "steadier" or not jumpy_kind(kind)) and (growth or quality >= 56):
        size = "large" if (growth and quality >= 54) or quality >= 60 else "medium"
        label = "quality growth" if growth else "quality"
        return {
            "ticker": ticker,
            "action": "buy",
            "size": size,
            "why": f"Pro-style {label} buy on {ticker}{dig} ({bits}).",
        }
    # Opportunity sleeve: researched upside with a bar.
    if jumpy_kind(kind) and quality >= 46 and risk_ok:
        size = "medium" if quality >= 52 or growth else "small"
        return {
            "ticker": ticker,
            "action": "buy",
            "size": size,
            "why": (
                f"Researched opportunity sleeve: {ticker} ({kind}){dig}. "
                f"Sized for upside, not the whole pile. ({bits})"
            ),
        }
    if quality >= 50 and file.get("attack_level") != "watch":
        return {
            "ticker": ticker,
            "action": "buy",
            "size": "medium",
            "why": f"Clear enough file on {ticker}{dig} for a pro-sized stake ({bits}).",
        }
    return {
        "ticker": ticker,
        "action": "skip",
        "size": "small",
        "why": f"{ticker} does not clear a pro research bar. Skipping.",
    }


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
    risk_used = 0.0
    for row in holding_rows:
        if jumpy_kind(str(row.get("kind") or "")):
            risk_used += float(row.get("now_gbp") or row.get("spent_gbp") or 0)
    risk_room = risk_used < max(1.0, total * RISK_MAX_FRAC)
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
    deep_budget = 8
    for ticker in candidate_tickers:
        if ticker in seen:
            continue
        if deep_budget <= 0:
            break
        try:
            # Full dig before any buy decision — no skim-then-regret.
            file = assemble_file(ticker, deep=True)
        except Exception:
            continue
        deep_budget -= 1
        file["mode"] = "buy"
        file["recently_sold"] = str(ticker).upper() in sold
        file["risk_room"] = risk_room
        files.append(file)
        seen.add(ticker)

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
        if action == "buy" and file.get("research_depth") != "full":
            move = {
                **move,
                "action": "skip",
                "why": f"Blocked buy of {ticker}: full research was not finished.",
            }
        if action == "buy" and file.get("attack_level") == "confirmed":
            move = {
                **move,
                "action": "skip",
                "why": f"Full research flagged {ticker} (confirmed). Not buying.",
            }
        if action == "buy" and jumpy_kind(str(file.get("kind") or "")) and file.get("attack_level") == "watch":
            move = {
                **move,
                "action": "skip",
                "why": f"Full research flagged flyer {ticker} (watch). Not buying.",
            }
        if action == "buy" and jumpy_kind(str(file.get("kind") or "")) and file.get("risk_room") is False:
            move = {
                **move,
                "action": "skip",
                "why": f"Flyer pocket full — skipped {ticker} for steadier cash use.",
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
                "research_depth": file.get("research_depth") or "lite",
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
        "note": "Pro-style: quality growth + researched opportunity sleeve. Bank gains; skip meme pumps.",
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
