from __future__ import annotations

import json
from typing import Any

from companyresearch.llm import complete

DISCLAIMER = (
    "This is a public-source briefing, not investment advice, not a prediction, "
    "and not a recommendation to buy or sell anything."
)

SYSTEM = """You are a careful researcher writing for someone who is not an investor.
You did not stop at the company page. The JSON includes an investigation notebook:
questions asked, follow-ups chased, pages opened, filing excerpts, and tensions.
Write from ONLY that JSON. If a search found little, say so. Do not invent numbers.
Do not tell the reader to buy, sell, or short. Do not promise returns.
If crash clues or a politician/celebrity pump show up, say so plainly.
You cannot time a crash. Screenshots of people getting rich on Trump-linked names are the winners — many others buy the top.
Do not tell the reader they will get rich. Do not tell them to hand over cash.
The pretend helper may take a tiny fake slice of endorsement or short-hunted names so the user can watch the scoreboard.
Use short words. Explain jargon in a parenthesis if you must use it.
Sound like a person who went looking, not a press-release rewriter.
Start with `# {name} ({ticker})`. Put the disclaimer in italics under the date.
Use these headings exactly:
## What I went looking for
## In plain English
## What they do
## The money picture
## What the shorts might be thinking
## Crash clues and political pumps
## What official filings actually say
## What I found when I dug
## Where the stories disagree
## Gossip to ignore
## Why someone might like it
## Why someone might lose money
## What I still could not settle
Keep it short enough to read with a cup of tea.
"""


def _template_memo(packet: dict[str, Any]) -> str:
    s = packet.get("snapshot") or {}
    f = packet.get("financials") or {}
    conf = packet.get("confidence") or {}
    inv = packet.get("investigation") or {}
    name = packet.get("name")
    ticker = packet.get("ticker")
    g = packet.get("guide") or {}
    lines = [
        f"# {name} ({ticker})",
        f"_{packet.get('as_of')}_",
        "",
        f"*{DISCLAIMER}*",
        "",
        "## What I went looking for",
        "Not just the first ticker page. A person would also ask: who competes, why the share moved, the ugly news, who pays them, and what the filing actually says.",
        "",
    ]
    for q in (inv.get("questions") or [])[:8]:
        lines.append(f"- {q.get('why') or q.get('q')}")
    if inv.get("chased"):
        lines.append("")
        lines.append("Then I chased:")
        for q in inv["chased"][:6]:
            lines.append(f"- {q.get('why') or q.get('q')}")
    lines += [
        "",
        "## In plain English",
        g.get("headline") or "Here is what we can say from public numbers.",
        "",
        g.get("one_liner") or "",
        "",
        g.get("blurb") or "",
        "",
        "The £10 illustration is in the box above the notes — change the amount and the years. It is not a promise.",
        "",
        "## What they do",
        s.get("longBusinessSummary") or "No plain-English summary was in the public snapshot.",
        "",
        "## The money picture",
    ]
    if f:
        for k, v in f.items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- Annual financial table was empty.")
    for label, key in [
        ("Trailing P/E", "trailingPE"),
        ("Profit margin", "profitMargins"),
        ("Revenue growth", "revenueGrowth"),
        ("Debt/equity", "debtToEquity"),
        ("Free cash flow", "freeCashflow"),
        ("Insider ownership", "heldPercentInsiders"),
        ("Institutional ownership", "heldPercentInstitutions"),
    ]:
        if s.get(key) not in (None, ""):
            lines.append(f"- {label}: {s[key]}")
    lines += ["", "## What the shorts might be thinking"]
    note = (packet.get("guide") or {}).get("short_note")
    if note:
        lines.append(note)
    else:
        lines.append(
            "Borrowing shares to short is usually legal. Lying to crash a price is not. This app cannot short."
        )
    if g.get("bear_why"):
        lines.append("Why this name can look like a short’s hunting ground:")
        for bit in g["bear_why"]:
            lines.append(f"- {bit}")
    lines += ["", "## Crash clues and political pumps"]
    clues = inv.get("clues") or {}
    crash = clues.get("crash") or {}
    pump = clues.get("endorsement") or {}
    lines.append(crash.get("note") or "Nobody reliably sells just before a crash.")
    for light in crash.get("lights") or []:
        lines.append(f"- Crash clue: {light}")
    if not crash.get("lights"):
        lines.append("- No loud crash campaign in this pull.")
    lines.append("")
    lines.append(pump.get("note") or "A politician mentioning a company is not a business plan.")
    for light in pump.get("lights") or []:
        lines.append(f"- Pump / endorsement clue: {light}")
    if not pump.get("lights"):
        lines.append("- No Trump or celebrity pump jumped out in this pull.")
    lines += ["", "## What official filings actually say"]
    excerpts = inv.get("filing_excerpts") or []
    if excerpts:
        for item in excerpts:
            lines.append(f"**{item.get('filed')} {item.get('form')}** — skim, not the whole document:")
            lines.append("")
            lines.append((item.get("excerpt") or "")[:900])
            lines.append("")
    filings = packet.get("filings") or []
    if not filings:
        lines.append("No recent SEC filings pulled (unknown CIK or SEC request failed).")
    else:
        lines.append("Recent forms:")
        for item in filings[:8]:
            lines.append(f"- {item.get('filed')} {item.get('form')}: {item.get('title')}")
    own = packet.get("ownership") or {}
    lines += ["", "## Who already has shares"]
    inst = own.get("institutions") or []
    ins = own.get("insiders") or []
    if inst:
        lines.append("Biggest funds we can see (this list is often months late):")
        for row in inst[:5]:
            holder = row.get("Holder") or row.get("holder") or "Unknown holder"
            shares = row.get("Shares") or row.get("shares") or ""
            lines.append(f"- {holder} {shares}".rstrip())
    else:
        lines.append("Institutional holder table unavailable.")
    if ins:
        lines.append("Recent insider transactions (as reported):")
        for row in ins[:5]:
            bits = [f"{k}: {v}" for k, v in row.items() if k.lower() != "index" and v not in (None, "", "nan")]
            lines.append("- " + ", ".join(bits[:5]))
    else:
        lines.append("Insider transaction table unavailable. Insider % of shares is in the snapshot if present.")
    sources = packet.get("sources") or []
    agreed = [x for x in sources if x.get("class") == "secondary" and not x.get("echo") and x.get("origin") != "sec_edgar"]
    noise = [x for x in sources if x.get("class") == "noise" or x.get("echo")]
    lines += ["", "## What I found when I dug"]
    reads = inv.get("reads") or []
    if reads:
        for item in reads[:5]:
            why = f" (looked because: {item['angle']})" if item.get("angle") else ""
            lines.append(f"- {item.get('title')} — {item.get('domain')}{why}")
            if item.get("excerpt"):
                lines.append(f"  {item['excerpt'][:280]}")
    elif agreed:
        for item in agreed[:8]:
            copies = f" ({item['copies']} copies)" if item.get("copies", 1) > 1 else ""
            angle = f" — {item['angle']}" if item.get("angle") else ""
            lines.append(f"- {item.get('title')} — {item.get('domain') or item.get('publisher')}{copies}{angle}")
    else:
        lines.append("Could not open pages this run. Headlines only — a weak file.")
    lines += ["", "## Where the stories disagree"]
    tensions = inv.get("tensions") or []
    if tensions:
        for note in tensions:
            lines.append(f"- {note}")
    else:
        lines.append("No obvious tug-of-war in this pull. That can mean quiet news — or that we still missed the other side.")
    lines += ["", "## Gossip to ignore"]
    if noise:
        for item in noise[:6]:
            why = "echo of one story" if item.get("echo") else item.get("class")
            lines.append(f"- {item.get('title')} ({why})")
    else:
        lines.append("No obvious social/echo pile-up in this pull.")
    lines += [
        "",
        "## Why someone might like it",
        "Without a language model I will not invent a story. Look at profits, cash, and what the dig found.",
        "",
        "## Why someone might lose money",
        "Share prices fall. This is not a piggy bank. If it is a gamble-style name, you could lose most of the £10.",
        "",
        "## What I still could not settle",
    ]
    for note in inv.get("open") or []:
        lines.append(f"- {note}")
    if not inv.get("open"):
        lines.append("- Anything that is not on this page: secret deals, a surprise product flop, a boss leaving.")
        lines.append("- Big-fund lists are often months old. Chat rumours are not proof.")
    lines += [
        "",
        "## How complete this file is",
        f"**{conf.get('label')} ({conf.get('score')}/100)** — {conf.get('stance')}",
    ]
    for reason in conf.get("reasons") or []:
        lines.append(f"- {reason}")
    if packet.get("errors"):
        lines += ["", "### Source errors", *(f"- {e}" for e in packet["errors"])]
    from companyresearch.net import using_insecure_ssl

    if using_insecure_ssl():
        lines += [
            "",
            "### Note",
            "- This run skipped TLS certificate checks because this PC's certificate store failed. Treat sources as unverified transport.",
        ]
    return "\n".join(lines)


def _prompt_packet(packet: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for item in (packet.get("sources") or [])[:36]:
        sources.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "class": item.get("class"),
                "origin": item.get("origin"),
                "domain": item.get("domain"),
                "copies": item.get("copies"),
                "echo": item.get("echo"),
                "independent_domains": item.get("independent_domains"),
                "published": item.get("published") or item.get("filed"),
                "summary": (item.get("summary") or "")[:400],
                "angle": item.get("angle"),
            }
        )
    inv = packet.get("investigation") or {}
    reads = []
    for item in (inv.get("reads") or [])[:6]:
        reads.append(
            {
                "title": item.get("title"),
                "domain": item.get("domain"),
                "url": item.get("url"),
                "angle": item.get("angle"),
                "excerpt": (item.get("excerpt") or "")[:1200],
            }
        )
    excerpts = []
    for item in (inv.get("filing_excerpts") or [])[:3]:
        excerpts.append(
            {
                "form": item.get("form"),
                "filed": item.get("filed"),
                "title": item.get("title"),
                "excerpt": (item.get("excerpt") or "")[:1800],
            }
        )
    return {
        "ticker": packet.get("ticker"),
        "name": packet.get("name"),
        "as_of": packet.get("as_of"),
        "snapshot": packet.get("snapshot"),
        "financials": packet.get("financials"),
        "ownership": packet.get("ownership"),
        "filings": [
            {"form": x.get("form"), "filed": x.get("filed"), "title": x.get("title"), "url": x.get("url")}
            for x in (packet.get("filings") or [])[:12]
        ],
        "sources": sources,
        "investigation": {
            "questions": inv.get("questions") or [],
            "chased": inv.get("chased") or [],
            "reads": reads,
            "filing_excerpts": excerpts,
            "tensions": inv.get("tensions") or [],
            "clues": inv.get("clues") or {},
            "empty_searches": inv.get("empty_searches") or [],
            "open": inv.get("open") or [],
        },
        "confidence": packet.get("confidence"),
        "guide": packet.get("guide"),
        "errors": packet.get("errors"),
        "disclaimer": DISCLAIMER,
    }


def write_memo(packet: dict[str, Any]) -> tuple[str, str]:
    """Returns (markdown, engine_name)."""
    user = (
        "Write this for a complete beginner. Use the investigation notebook — that is the work, not just the snapshot.\n"
        "Start with `# {name} ({ticker})`.\n"
        "Put the disclaimer in italics under the date. Do not promise any return.\n\n"
        + json.dumps(_prompt_packet(packet), default=str)[:28000]
    )
    text, engine = complete(SYSTEM, user)
    if text:
        return text, engine
    return _template_memo(packet), "template"
