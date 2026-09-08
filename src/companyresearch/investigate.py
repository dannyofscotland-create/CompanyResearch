from __future__ import annotations

import json
import re
from typing import Any

from companyresearch.clues import assess_clues
from companyresearch.llm import complete_json
from companyresearch.sources.classify import collapse_stories
from companyresearch.sources.news import search_angle
from companyresearch.sources.pages import read_leads
from companyresearch.sources.sec import fetch_filing_excerpts

BULL = re.compile(
    r"\b(beat|beats|surge|soars|record|upgrade|outperform|breakthrough|win|wins|contract)\b",
    re.I,
)
BEAR = re.compile(
    r"\b(miss|misses|lawsuit|sued|probe|investigation|dilution|offering|layoff|fraud|downgrade|"
    r"recall|bankrupt|going concern|warning|plunge|crash|short)\b",
    re.I,
)
NAMED = re.compile(
    r"\b(lawsuit|sued|probe|investigation|offering|dilution|atm offering|bankruptcy|fda|"
    r"recall|layoff|guidance|short seller|fraud|merger|acquire|downgrade|halt|going concern|"
    r"class action|doj|ftc|sec charges)\b",
    re.I,
)


def iter_investigate(
    name: str,
    ticker: str,
    snapshot: dict[str, Any],
    filings: list[dict[str, Any]],
    hist: dict[str, Any],
    yahoo_news: list[dict[str, Any]],
):
    """Yield (status|packet-bits). Dig past the first company page."""
    yahoo = [{**item, "angle": item.get("angle") or "Already on the ticker page"} for item in yahoo_news]
    questions = _playbook(name, ticker, snapshot, hist, filings)
    yield ("status", {"step": "angles", "label": "Searching several angles, not just the company page"})
    first: list[dict[str, Any]] = []
    empty: list[dict[str, Any]] = []
    for spec in questions:
        rows = search_angle(spec["q"], spec["kind"], spec["why"], spec.get("n") or 5)
        first.extend(rows)
        if not rows:
            empty.append(spec)

    yield ("status", {"step": "leads", "label": "Noticing odd bits and chasing them"})
    follow = _heuristic_followups(name, ticker, snapshot, hist, filings, first)
    yield ("status", {"step": "skeptic", "label": "Asking what a skeptic would look up next"})
    try:
        llm_follow = _llm_followups(
            name, ticker, snapshot, filings, first, already=[q["q"] for q in questions + follow]
        )
    except Exception:
        llm_follow = []
    chased = follow + llm_follow
    extra: list[dict[str, Any]] = []
    for spec in chased[:5]:
        rows = search_angle(spec["q"], spec.get("kind") or "text", spec["why"], 5)
        extra.extend(rows)
        if not rows:
            empty.append(spec)

    yield ("status", {"step": "pages", "label": "Opening a few pages instead of stopping at headlines"})
    combined = collapse_stories([*yahoo, *first, *extra])
    reads = read_leads(combined, limit=5)

    yield ("status", {"step": "filings", "label": "Skimming the filing itself, not just the title"})
    excerpts = []
    try:
        excerpts = fetch_filing_excerpts(filings, limit=2)
    except Exception:
        excerpts = []

    tensions = _tensions(snapshot, combined, excerpts)
    clues = assess_clues(name, ticker, snapshot, combined, filings)
    notebook = {
        "questions": [{"q": q["q"], "why": q["why"]} for q in questions],
        "chased": [{"q": q["q"], "why": q["why"], "how": q.get("how") or "desk"} for q in chased],
        "reads": reads,
        "filing_excerpts": excerpts,
        "tensions": tensions,
        "clues": clues,
        "empty_searches": [q["why"] for q in empty[:6]],
        "open": _still_open(snapshot, filings, reads, excerpts, empty),
    }
    yield (
        "dig",
        {
            "sources": combined,
            "investigation": notebook,
        },
    )


def _playbook(name: str, ticker: str, snapshot: dict[str, Any], hist: dict[str, Any], filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sector = snapshot.get("sector") or snapshot.get("industry") or ""
    return [
        {"q": f"{ticker} {name}", "kind": "news", "why": "What is being written this week", "n": 6},
        {"q": f"{name} {ticker} earnings OR results OR guidance", "kind": "news", "why": "Latest results, not just the share price", "n": 5},
        {"q": f"{name} competitors OR rivals OR versus", "kind": "text", "why": "Who they actually compete with", "n": 5},
        {"q": f"{ticker} {name} why stock dropped OR rally OR selloff", "kind": "text", "why": "Why the share moved, not the press line", "n": 5},
        {"q": f"{name} lawsuit OR investigation OR probe OR recall", "kind": "text", "why": "Trouble a company page will not volunteer", "n": 5},
        {"q": f"{name} {ticker} short seller OR overvalued OR dilution OR offering", "kind": "text", "why": "The skeptical case — what a short might argue", "n": 5},
        {"q": f"{name} customers OR contract win OR customer concentration", "kind": "text", "why": "Who actually pays them", "n": 4},
        {"q": f"{name} {ticker} CEO OR CFO OR resignation OR layoff", "kind": "news", "why": "Who is running it, and whether they are leaving", "n": 4},
        {"q": f"{name} {sector} risk OR regulation".strip(), "kind": "text", "why": "What can go wrong in this kind of business", "n": 4},
        {"q": _filing_query(name, ticker, filings), "kind": "text", "why": "The latest sudden filing, if there was one", "n": 4},
        {"q": f"{ticker} {name} Hindenburg OR \"short report\" OR \"pump and dump\" OR crash", "kind": "text", "why": "Whether someone is trying to crash the story", "n": 5},
        {"q": f"{ticker} {name} Trump OR endorsement OR celebrity OR meme stock", "kind": "news", "why": "Whether a politician or celebrity is pumping it", "n": 5},
    ]


def _filing_query(name: str, ticker: str, filings: list[dict[str, Any]]) -> str:
    sudden = [f for f in filings if str(f.get("form") or "").startswith("8-K")]
    if sudden:
        title = sudden[0].get("title") or "8-K"
        return f"{name} {ticker} {title}"[:90]
    return f"{name} {ticker} 10-K risk factors"


def _heuristic_followups(
    name: str,
    ticker: str,
    snapshot: dict[str, Any],
    hist: dict[str, Any],
    filings: list[dict[str, Any]],
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(q: str, why: str) -> None:
        key = q.lower().strip()
        if key in seen or len(q) < 8:
            return
        seen.add(key)
        out.append({"q": q, "why": why, "kind": "text", "how": "from the numbers and headlines"})

    margins = _num(snapshot.get("profitMargins"))
    if margins is not None and margins < 0:
        add(f"{name} path to profitability cash burn", "They are not making a profit yet")
    debt = _num(snapshot.get("debtToEquity"))
    if debt is not None and debt > 150:
        add(f"{name} debt refinancing interest expense", "Debt looks heavy on the snapshot")
    ret = _num(hist.get("return_1y"))
    if ret is not None and ret <= -0.25:
        add(f"{ticker} stock decline 2025 2026 reasons", "The share had a rough year")
    elif ret is not None and ret >= 0.8:
        add(f"{ticker} rally justified valuation", "The share ran hard — worth asking if the story kept up")
    if _num(snapshot.get("heldPercentInsiders")) is not None and _num(snapshot.get("heldPercentInsiders")) == 0:
        add(f"{name} insider selling OR buying", "Insiders do not seem to own much")
    short_pct = _num(snapshot.get("shortPercentOfFloat"))
    if short_pct is not None and short_pct >= 0.08:
        add(
            f"{ticker} {name} short squeeze OR days to cover",
            "Lots of shares are already shorted — look at squeeze risk, not only the bear story",
        )
        add(
            f"{ticker} short thesis OR Hindenburg OR Muddy Waters OR Spruce Point",
            "See if a named short report exists, and whether it was answered",
        )

    for item in hits:
        title = item.get("title") or ""
        hit = NAMED.search(title)
        if not hit:
            continue
        word = hit.group(0)
        add(f'{name} {ticker} "{word}"', f"A headline mentioned {word.lower()} — follow that, do not stop at the headline")

    forms = {str(f.get("form") or "") for f in filings}
    if any(f.startswith("S-") or "424" in f for f in forms):
        add(f"{name} {ticker} share offering dilution", "They filed to sell more shares")
    return out[:6]


def _llm_followups(
    name: str,
    ticker: str,
    snapshot: dict[str, Any],
    filings: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    already: list[str],
) -> list[dict[str, Any]]:
    headlines = [{"title": h.get("title"), "domain": h.get("domain"), "angle": h.get("angle")} for h in hits[:18]]
    payload = {
        "name": name,
        "ticker": ticker,
        "sector": snapshot.get("sector"),
        "industry": snapshot.get("industry"),
        "profitMargins": snapshot.get("profitMargins"),
        "revenueGrowth": snapshot.get("revenueGrowth"),
        "debtToEquity": snapshot.get("debtToEquity"),
        "recent_filings": [f.get("form") for f in filings[:8]],
        "headlines_so_far": headlines,
        "already_tried": already[:20],
    }
    planned = complete_json(
        "You help a skeptical company researcher. A careful human does not stop at the first Yahoo page. "
        "Return ONLY JSON: {\"queries\":[{\"q\":\"short search box query\",\"why\":\"plain English reason\"}]}. "
        "At most 4 queries. Do not repeat already_tried. Chase the bear case, a named rival, a lawsuit, "
        "dilution, a regulator, a product flop, or a customer. No buy or sell advice.",
        json.dumps(payload, default=str)[:8000],
    )
    if not isinstance(planned, dict):
        return []
    rows = planned.get("queries") or []
    out = []
    for row in rows[:4]:
        if not isinstance(row, dict):
            continue
        q = str(row.get("q") or "").strip()
        why = str(row.get("why") or "A follow-up a person would type next").strip()
        if len(q) < 6:
            continue
        out.append({"q": q, "why": why, "kind": "text", "how": "asked after reading the first pass"})
    return out


def _tensions(snapshot: dict[str, Any], sources: list[dict[str, Any]], excerpts: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    titles = [s.get("title") or "" for s in sources]
    bull = sum(1 for t in titles if BULL.search(t))
    bear = sum(1 for t in titles if BEAR.search(t))
    if bull >= 2 and bear >= 2:
        notes.append("Cheerful headlines and ugly headlines are both in this pile — that is a sign to slow down, not pick a team.")
    margins = _num(snapshot.get("profitMargins"))
    if margins is not None and margins > 0 and bear:
        notes.append("The snapshot shows a profit, but some coverage is about trouble. Check which story is newer.")
    if margins is not None and margins < 0 and bull >= 3:
        notes.append("A lot of coverage sounds excited while the company is still losing money.")
    target = _num(snapshot.get("targetMeanPrice"))
    price = _num(snapshot.get("currentPrice") or snapshot.get("regularMarketPrice") or snapshot.get("price"))
    if target and price and target > price * 1.4 and bear:
        notes.append("Analyst price targets look rosy next to the skeptical headlines. Targets are often late and often wrong.")
    if excerpts and any("going concern" in (e.get("excerpt") or "").lower() for e in excerpts):
        notes.append("A filing uses ‘going concern’ language — that is the company saying survival is not a given.")
    return notes


def _still_open(
    snapshot: dict[str, Any],
    filings: list[dict[str, Any]],
    reads: list[dict[str, Any]],
    excerpts: list[dict[str, Any]],
    empty: list[dict[str, Any]],
) -> list[str]:
    open_q = [
        "Anything that is not public: a quiet deal, a product that has not shipped, a boss about to leave.",
        "Big-fund holder lists are often months old.",
    ]
    if not excerpts:
        open_q.append("Could not skim a 10-K or 8-K body this run — only filing titles.")
    if not reads:
        open_q.append("Could not open news pages (paywalls or blocks). Headlines alone are a weak file.")
    if not snapshot.get("longBusinessSummary"):
        open_q.append("No plain-English company description in the snapshot.")
    if not filings:
        open_q.append("No SEC filings matched. If this is not a US filer, the official paperwork is elsewhere.")
    for q in empty[:3]:
        why = q.get("why") or q.get("q") or "that"
        open_q.append(f"Looked for this and found little: {why}")
    return open_q


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
