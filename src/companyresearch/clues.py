from __future__ import annotations

import re
from typing import Any

from companyresearch import cache
from companyresearch.sources.classify import classify_url, domain_of
from companyresearch.sources.market import fetch_snapshot, normalize_ticker
from companyresearch.sources.news import search_angle
from companyresearch.sources.pages import fetch_snippet

# Named attacks / official trouble — these can matter.
# Firm names alone are not enough (e.g. "Kerrisdale cuts holdings" is not a short report).
HARD = re.compile(
    r"(hindenburg|muddy waters|spruce point|citron research|wolfpack|kerrisdale).{0,70}"
    r"(report|short|fraud|accuse|target|initiate)|"
    r"(report|short|fraud|accuse).{0,70}"
    r"(hindenburg|muddy waters|spruce point|citron research|wolfpack|kerrisdale)|"
    r"going concern|sec charges|trading halt|\bhalted\b|accounting fraud",
    re.I,
)
# Scary words that also appear in routine news and filings.
SOFT = re.compile(
    r"pump and dump|class action|short report|going to zero|dilution|atm offering|share offering",
    re.I,
)
ENDORSE = re.compile(
    r"\btrump\b|truth social|endorsement|endorsed by|celebrity pump|meme stock|"
    r"going to the moon|to the moon|100x",
    re.I,
)
# Kept for callers that import CRASH; now means “worth a second look”, not “sell”.
CRASH = re.compile(HARD.pattern + r"|" + SOFT.pattern, re.I)
HARMLESS = re.compile(
    r"\bdismiss(ed|es|al)\b|\bdenied\b|\bwhat is\b|wikipedia|definition|"
    r"steam|video game|forum|forums|how to spot|explained",
    re.I,
)
NAME_SKIP = {
    "inc",
    "inc.",
    "corp",
    "corp.",
    "corporation",
    "company",
    "co",
    "co.",
    "the",
    "group",
    "holdings",
    "limited",
    "ltd",
    "plc",
    "sa",
    "ag",
    "nv",
}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blob(item: dict[str, Any]) -> str:
    return " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("url") or ""),
            str(item.get("publisher") or ""),
        ]
    )


def about_this_company(item: dict[str, Any], ticker: str, name: str) -> bool:
    text = _blob(item).lower()
    sym = ticker.lower().replace("-", "")
    if ticker.lower() in text or (len(sym) >= 3 and re.search(rf"\b{re.escape(sym)}\b", text)):
        return True
    tokens = [w for w in re.findall(r"[A-Za-z]{4,}", name) if w.lower() not in NAME_SKIP]
    if not tokens:
        return False
    hits = sum(1 for w in tokens[:4] if w.lower() in text)
    return hits >= 2 or (hits >= 1 and ticker.lower()[:3] in text)


def junk_source(item: dict[str, Any]) -> bool:
    url = item.get("url") or ""
    host = item.get("domain") or domain_of(url)
    klass = item.get("class") or classify_url(url)
    if klass == "noise":
        return True
    if any(bit in host for bit in ("wikipedia.", "forum", "fandom.", "steam", "quora", "pinterest")):
        return True
    title = item.get("title") or ""
    if HARMLESS.search(title) or HARMLESS.search(url):
        return True
    return False


def confirm_attack(ticker: str, name: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """A person would check the source and whether the story is even about this company."""
    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []
    ignored: list[str] = []
    for item in sources:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        if junk_source(item):
            ignored.append(title)
            continue
        if not about_this_company(item, ticker, name):
            ignored.append(title)
            continue
        row = {
            "title": title,
            "domain": item.get("domain") or domain_of(item.get("url") or ""),
            "class": item.get("class") or classify_url(item.get("url") or ""),
            "url": item.get("url"),
        }
        if HARD.search(title) or HARD.search(item.get("summary") or ""):
            hard.append(row)
        elif SOFT.search(title):
            if row["class"] in {"primary", "secondary"}:
                soft.append(row)
            else:
                ignored.append(title)

    independent = {r["domain"] for r in hard + soft if r.get("domain")}
    if hard:
        level = "confirmed"
        hits = hard[:4]
        note = "A named report or official-sounding trouble about this company, from a source that is not a forum."
    elif soft:
        # Soft headlines (class actions, dilution talk) are a watch — not an automatic dump.
        level = "watch"
        hits = soft[:3]
        note = (
            "Ugly soft headlines about this ticker. Watch closely, but do not treat that alone "
            "like a named short report."
        )
    else:
        level = "clear"
        hits = []
        note = "No confirmed crash campaign about this company. Wikipedia, forums, and unrelated ‘pump and dump’ pages were ignored."
    return {
        "level": level,
        "hits": hits,
        "ignored": ignored[:6],
        "note": note,
        "headline": (hits[0]["title"] if hits else None),
        "hard_n": len(hard),
        "soft_n": len(soft),
        "independent_n": len(independent),
    }


def assess_clues(
    name: str,
    ticker: str,
    snapshot: dict[str, Any],
    sources: list[dict[str, Any]],
    filings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Warning lights from public text. Shape is not the same as a confirmed attack."""
    shape: list[str] = []
    pump_lights: list[str] = []
    short = _num(snapshot.get("shortPercentOfFloat"))
    fcf = _num(snapshot.get("freeCashflow"))
    profit = _num(snapshot.get("profitMargins"))
    blob = " ".join(
        [
            str(snapshot.get("name") or ""),
            str(snapshot.get("longBusinessSummary") or "")[:800],
        ]
    )

    if short is not None and short >= 0.15:
        shape.append("A lot of the freely traded shares are already sold short. That is a shape, not a crash timer.")
    if fcf is not None and fcf < 0 and profit is not None and profit <= 0:
        shape.append("Losing money and burning cash — the shape a crash campaign likes to point at.")
    for item in filings or []:
        form = str(item.get("form") or "")
        title = str(item.get("title") or "")
        if form.startswith("S-") or "424" in form or "offering" in title.lower():
            shape.append(f"Filing looks like they may sell more shares ({form}).")
            break

    attack = confirm_attack(ticker, name, sources)
    for item in sources:
        title = item.get("title") or ""
        if junk_source(item) or not about_this_company(item, ticker, name):
            continue
        if ENDORSE.search(title) or ENDORSE.search(blob):
            pump_lights.append(title.strip() or "Name or summary is tied to a politician or a meme pump.")

    if ENDORSE.search(blob) and not pump_lights:
        pump_lights.append("The company write-up is tied to Trump or a celebrity-style story.")

    crash_level = attack["level"] if attack["level"] != "clear" else ("watch" if shape else "clear")
    lights = [h["title"] for h in attack.get("hits") or []] + shape
    pump_level = "red" if len(pump_lights) >= 3 else "amber" if pump_lights else "clear"
    return {
        "crash": {
            "level": "red" if attack["level"] == "confirmed" else "amber" if crash_level != "clear" else "clear",
            "lights": _uniq(lights)[:8],
            "attack": attack,
            "note": (
                "A person would not sell on Wikipedia or a forum. "
                "Confirmed means a real report or two proper sources about this ticker. "
                "Spreading lies to crash a share is illegal."
            ),
        },
        "endorsement": {
            "level": pump_level,
            "lights": _uniq(pump_lights)[:8],
            "note": (
                "A Trump mention or a celebrity pump can spike a price. The screenshots of people getting rich are the winners. "
                "Plenty of people buy the top and lose. The pretend helper may put a tiny fake slice in so you can watch."
            ),
        },
    }


def quick_crash_warning(ticker: str, *, headlines_only: bool = False) -> str | None:
    """Only a confirmed attack about this company. Forums and encyclopedia pages do not count."""
    symbol = normalize_ticker(ticker)
    key = f"crashwarn:v2:{symbol}:{'h' if headlines_only else 'a'}"
    cached = cache.get(key, ttl_seconds=30 * 60)
    if cached is not None:
        return cached or None
    try:
        snap = fetch_snapshot(symbol)
    except Exception:
        cache.put(key, "")
        return None
    name = str(snap.get("name") or symbol)
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(
            search_angle(
                f'"{symbol}" {name} Hindenburg OR "short report" OR "going concern" OR fraud',
                "news",
                "crash clues",
                5,
            )
        )
        rows.extend(
            search_angle(
                f'"{symbol}" {name} dilution OR "share offering" OR "class action"',
                "text",
                "crash clues",
                4,
            )
        )
    except Exception:
        rows = []
    attack = confirm_attack(symbol, name, rows)
    msg = ""
    if attack["level"] == "confirmed":
        msg = attack.get("headline") or ""
        if not headlines_only:
            clues = assess_clues(name, symbol, snap, rows)
            crash = clues.get("crash") or {}
            if crash.get("level") == "red" and crash.get("lights"):
                msg = crash["lights"][0]
    cache.put(key, msg)
    return msg or None


def deepen_if_needed(ticker: str, name: str, sources: list[dict[str, Any]], attack: dict[str, Any]) -> dict[str, Any]:
    """If something looks ugly, open a page — a person would not stop at the headline."""
    if attack.get("level") == "clear":
        return attack
    for hit in attack.get("hits") or []:
        url = hit.get("url") or ""
        if not url:
            continue
        snippet = fetch_snippet(url, max_chars=900)
        if not snippet:
            continue
        hit["excerpt"] = snippet[:500]
        low = snippet.lower()
        if HARMLESS.search(snippet) and not HARD.search(snippet):
            attack["level"] = "watch"
            attack["note"] = "Opened the page. It looks less like a crash of this company than the headline suggested."
        elif ticker.lower() not in low and name.split(" ")[0].lower() not in low:
            attack["level"] = "watch"
            attack["note"] = "Opened the page. It may not even be about this company."
        break
    return attack


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
