from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from companyresearch import cache
from companyresearch.sources.market import fetch_snapshot, normalize_ticker

# Cash-making giants plus smaller “could 10x or go to nothing” names across world markets.
# Yahoo suffixes: .L London, .DE/.PA/.AS/.SW Europe, .T Tokyo, .HK Hong Kong, .TO Canada,
# .AX Australia, .NS India, .KS Korea, .SA Brazil. US names have no suffix.
UNIVERSE = [
    # United States
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "AMD", "CRM",
    "BRK-B", "JNJ", "PG", "KO", "COST", "WMT", "UNH", "V", "MA", "HD",
    "JPM", "XOM", "PEP", "MCD", "ABBV", "LLY", "ACN", "NEE", "CAT", "LIN",
    "TSLA", "PLTR", "NFLX", "ADBE", "SHOP", "UBER", "CRWD", "NET", "SNOW", "ARM",
    "COIN", "HOOD", "SOFI", "SMCI", "MSTR", "IONQ", "RKLB", "RIVN", "LCID", "NIO",
    "GME", "DKNG", "RBLX", "UPST", "AFRM", "SNAP", "SMR", "OKLO", "MARA", "PATH",
    "RIOT", "CLSK", "HUT", "IREN", "WULF", "CIFR", "BTBT", "BITF",
    "RGTI", "QUBT", "QBTS", "ASTS", "LUNR", "SPCE", "JOBY", "ACHR",
    "LEU", "UUUU", "UEC", "DNN", "SOUN", "BBAI", "CRSP", "RXRX",
    "XPEV", "PLUG", "FCEL", "OPEN", "DJT",
    # United Kingdom
    "SHEL.L", "AZN.L", "HSBA.L", "BP.L", "ULVR.L", "VOD.L", "GSK.L", "DGE.L",
    "RIO.L", "BATS.L", "NG.L", "RR.L", "LLOY.L", "BARC.L", "AAL.L", "REL.L",
    # Europe
    "SAP.DE", "SIE.DE", "BMW.DE", "ALV.DE", "DTE.DE",
    "AIR.PA", "TTE.PA", "SAN.PA", "OR.PA", "MC.PA",
    "ASML.AS", "INGA.AS", "PHIA.AS", "ADYEN.AS",
    "NESN.SW", "NOVN.SW", "ROG.SW",
    "ENEL.MI", "ISP.MI", "UCG.MI",
    "EQNR.OL", "ERIC-B.ST", "NOVO-B.CO", "NOKIA.HE",
    # Japan
    "7203.T", "6758.T", "9984.T", "6861.T", "8306.T", "6098.T", "8035.T", "4063.T",
    # Hong Kong / China ADRs & local
    "0700.HK", "9988.HK", "3690.HK", "1810.HK", "0941.HK", "1299.HK",
    "BABA", "PDD", "JD",
    # Canada / Australia
    "RY.TO", "TD.TO", "ENB.TO", "SHOP.TO", "CNQ.TO",
    "BHP.AX", "CBA.AX", "CSL.AX", "WBC.AX", "NAB.AX", "WES.AX",
    # Korea / India / Brazil
    "005930.KS", "000660.KS",
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "PETR4.SA", "VALE3.SA", "ITUB4.SA",
]


DISCLAIMER = (
    "Screens from public numbers on a fixed watchlist. Not advice, not a forecast, "
    "not a recommendation to buy or sell."
)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _story_tags(s: dict[str, Any]) -> list[str]:
    blob = " ".join(
        [
            str(s.get("sector") or ""),
            str(s.get("industry") or ""),
            str(s.get("longName") or ""),
            str(s.get("name") or ""),
            str(s.get("longBusinessSummary") or "")[:500],
        ]
    ).lower()
    mapping = [
        ("bitcoin", "tied to bitcoin"),
        ("crypto", "crypto-linked"),
        ("blockchain", "crypto-linked"),
        ("digital asset", "crypto-linked"),
        ("quantum", "quantum computing"),
        ("spacecraft", "space bet"),
        ("launch vehicle", "space bet"),
        ("lunar", "space bet"),
        ("satellite", "space bet"),
        ("uranium", "nuclear / uranium"),
        ("nuclear", "nuclear / uranium"),
        ("small modular", "nuclear / uranium"),
        ("gene", "early science"),
        ("biotech", "early science"),
        ("electric vehicle", "unproven EV"),
        ("air taxi", "flying-car bet"),
        ("hydrogen", "unproven energy"),
        ("fuel cell", "unproven energy"),
        ("trump", "Trump-linked"),
        ("truth social", "Trump-linked"),
        ("donald j. trump", "Trump-linked"),
    ]
    tags: list[str] = []
    for needle, label in mapping:
        if needle in blob and label not in tags:
            tags.append(label)
    return tags


def _quality_score(s: dict[str, Any]) -> tuple[int, list[str]]:
    why: list[str] = []
    score = 12
    profit = _num(s.get("profitMargins"))
    fcf = _num(s.get("freeCashflow"))
    roe = _num(s.get("returnOnEquity"))
    growth = _num(s.get("revenueGrowth"))
    debt = _num(s.get("debtToEquity"))
    inst = _num(s.get("heldPercentInstitutions"))
    mcap = _num(s.get("marketCap"))
    pe = _num(s.get("trailingPE"))
    short = _num(s.get("shortPercentOfFloat"))

    if profit is not None and profit > 0.2:
        score += 14
        why.append("fat profit margin")
    elif profit is not None and profit > 0.1:
        score += 10
        why.append("solid profit margin")
    elif profit is not None and profit > 0:
        score += 6
        why.append("profitable")
    elif profit is not None and profit <= 0:
        score -= 24

    if fcf is not None and fcf > 1e10:
        score += 12
        why.append("heavy free cash flow")
    elif fcf is not None and fcf > 0:
        score += 8
        why.append("positive free cash flow")
    elif fcf is not None and fcf < 0:
        score -= 10

    if roe is not None and roe > 0.25:
        score += 10
        why.append("excellent ROE")
    elif roe is not None and roe > 0.12:
        score += 6
        why.append("good ROE")

    if growth is not None and 0.05 <= growth <= 0.22:
        score += 8
        why.append("steady growth")
    elif growth is not None and growth > 0.22:
        score += 3
    elif growth is not None and growth < 0:
        score -= 8

    if debt is not None and debt < 50:
        score += 7
        why.append("light debt")
    elif debt is not None and debt < 120:
        score += 3
    elif debt is not None and debt > 220:
        score -= 10

    if inst is not None and inst > 0.6:
        score += 5
        why.append("institutions already in")

    if mcap is not None and mcap >= 2e11:
        score += 6
    elif mcap is not None and mcap >= 4e10:
        score += 3
    elif mcap is not None and mcap < 2e9:
        score -= 10

    if pe is not None and 10 <= pe <= 28:
        score += 7
        why.append("valuation not stretched")
    elif pe is not None and pe > 50:
        score -= 8

    if short is not None and short > 0.1:
        score -= 8

    return max(0, min(99, score)), why[:4]


def _speculative_score(s: dict[str, Any]) -> tuple[int, list[str]]:
    why: list[str] = []
    score = 18
    profit = _num(s.get("profitMargins"))
    growth = _num(s.get("revenueGrowth"))
    mcap = _num(s.get("marketCap"))
    short = _num(s.get("shortPercentOfFloat"))
    beta = _num(s.get("beta"))
    pe = _num(s.get("trailingPE"))
    high = _num(s.get("fiftyTwoWeekHigh"))
    low = _num(s.get("fiftyTwoWeekLow"))
    hooks = 0

    if growth is not None and growth > 0.35:
        score += 22
        hooks += 1
        why.append("very fast revenue growth")
    elif growth is not None and growth > 0.18:
        score += 12
        hooks += 1
        why.append("fast growth")

    if profit is not None and profit <= 0:
        score += 14
        hooks += 1
        why.append("not profitable yet")
    elif profit is not None and profit < 0.04:
        score += 6
        why.append("thin margins")

    if mcap is not None and mcap < 5e9:
        score += 16
        hooks += 1
        why.append("smaller name")
    elif mcap is not None and mcap < 2.5e10:
        score += 8
        why.append("still mid-cap")
    elif mcap is not None and mcap > 4e11:
        score -= 10

    if short is not None and short > 0.12:
        score += 14
        hooks += 1
        why.append("heavy short interest")
    elif short is not None and short > 0.06:
        score += 7
        why.append("shorts are active")

    if beta is not None and beta > 2:
        score += 12
        hooks += 1
        why.append("high beta")
    elif beta is not None and beta > 1.4:
        score += 7
        why.append("swings hard")

    if high and low and low > 0 and (high - low) / low > 0.7:
        score += 8
        hooks += 1
        why.append("wide 52-week range")

    if pe is None or (pe is not None and pe > 70):
        score += 6

    tags = _story_tags(s)
    if tags:
        score += 8
        hooks += 1
        why.append(tags[0])

    if hooks < 2:
        score -= 18
        why.append("not enough lottery-ticket traits")

    why.append("can go to zero-ish if the story fails")
    return max(0, min(99, score)), why[:4]


def _longshot_score(s: dict[str, Any]) -> tuple[int, list[str]]:
    """Small, story-shaped names — the '£10 could become a lot, or nothing' bin."""
    why: list[str] = []
    score = 8
    mcap = _num(s.get("marketCap"))
    profit = _num(s.get("profitMargins"))
    beta = _num(s.get("beta"))
    high = _num(s.get("fiftyTwoWeekHigh"))
    low = _num(s.get("fiftyTwoWeekLow"))
    tags = _story_tags(s)

    if mcap is not None and mcap > 1.5e10:
        return 0, ["too big to be an early-bitcoin shape"]
    if mcap is not None and mcap < 4e8:
        score += 28
        why.append("tiny company (early bitcoin was tiny too)")
    elif mcap is not None and mcap < 2e9:
        score += 20
        why.append("still small")
    elif mcap is not None and mcap < 8e9:
        score += 12
        why.append("small enough that £10 can still matter")
    else:
        score += 4

    if tags:
        score += 16
        why.extend(tags[:2])
    else:
        score -= 8

    if profit is not None and profit <= 0:
        score += 10
        why.append("not profitable yet")

    if high and low and low > 0 and (high - low) / low > 1.2:
        score += 10
        why.append("wild price swings")
    if beta is not None and beta > 2:
        score += 8
        why.append("moves like a rollercoaster")

    if not tags and (mcap is None or mcap > 5e9):
        score -= 20

    why.append("most bets like this fail; a few become legends")
    return max(0, min(99, score)), why[:4]


def short_blurb(s: dict[str, Any]) -> str:
    """Plain English on legal shorts vs illegal tricks. Never a how-to."""
    pct = _num(s.get("shortPercentOfFloat"))
    days = _num(s.get("shortRatio"))
    bits: list[str] = []
    if pct is not None:
        bits.append(
            f"About {pct * 100:.1f}% of the freely traded shares are already sold short "
            "(borrowed and sold, hoping the price falls). That is usually legal in the UK and US."
        )
    if days is not None:
        bits.append(f"‘Days to cover’ is about {days:.1f} — a rough guess of how long it could take shorts to buy back.")
    if pct is not None and pct >= 0.15:
        bits.append(
            "That is a crowded bet against the company. If the price jumps, shorts can get squeezed and the share can spike. "
            "This app cannot short anything. Spreading rumours or fake news to crash a price is illegal."
        )
    elif pct is not None and pct >= 0.05:
        bits.append("Some people already have a bet that this share will fall. That is not proof they are right.")
    if not bits:
        bits.append(
            "No short-interest figure in this snapshot. Borrowing shares to short is usually legal; lying to smash a price is not. "
            "This pretend wallet cannot short."
        )
    return " ".join(bits)


def _bear_score(s: dict[str, Any]) -> tuple[int, list[str]]:
    """How much this looks like a name critics and shorts pick apart — not a short recommendation."""
    why: list[str] = []
    score = 10
    profit = _num(s.get("profitMargins"))
    fcf = _num(s.get("freeCashflow"))
    growth = _num(s.get("revenueGrowth"))
    debt = _num(s.get("debtToEquity"))
    pe = _num(s.get("trailingPE"))
    short = _num(s.get("shortPercentOfFloat"))
    days = _num(s.get("shortRatio"))
    mcap = _num(s.get("marketCap"))
    tags = _story_tags(s)
    hooks = 0

    if profit is not None and profit <= 0:
        score += 18
        hooks += 1
        why.append("not making a profit")
    elif profit is not None and profit < 0.04:
        score += 8
        why.append("thin profit")

    if fcf is not None and fcf < 0:
        score += 12
        hooks += 1
        why.append("burning cash")

    if growth is not None and growth < 0:
        score += 10
        hooks += 1
        why.append("sales shrinking")

    if debt is not None and debt > 200:
        score += 12
        hooks += 1
        why.append("heavy debt")

    if pe is not None and pe > 70:
        score += 10
        why.append("price looks stretched")
    elif pe is None and profit is not None and profit <= 0:
        score += 8
        why.append("price is a story, not earnings")

    if short is not None and short >= 0.15:
        score += 16
        hooks += 1
        why.append("lots of people already short it")
    elif short is not None and short >= 0.08:
        score += 10
        hooks += 1
        why.append("shorts are active")

    if days is not None and days >= 6:
        score += 8
        why.append("slow to cover — squeeze risk too")

    if tags:
        score += 8
        why.append(tags[0])

    if mcap is not None and mcap < 2e9:
        score += 6
        why.append("small enough for a story to snap")

    if hooks < 2:
        score -= 16

    why.append("not a short tip — crowded shorts can blow up")
    return max(0, min(99, score)), why[:4]


def _endorsement_score(s: dict[str, Any]) -> tuple[int, list[str]]:
    """Political / celebrity pump shape. Lottery posters, not a get-rich method."""
    why: list[str] = []
    ticker = str(s.get("ticker") or "").upper()
    tags = _story_tags(s)
    political = [t for t in tags if "Trump" in t or "trump" in t.lower()]
    blob = " ".join(
        [
            str(s.get("longName") or ""),
            str(s.get("name") or ""),
            str(s.get("longBusinessSummary") or "")[:600],
        ]
    ).lower()
    hooked = ticker == "DJT" or bool(political) or "trump" in blob or "truth social" in blob
    if not hooked:
        return 0, ["no politician or celebrity pump in the public write-up"]

    score = 40
    why.append("Trump-linked or endorsement-shaped")
    profit = _num(s.get("profitMargins"))
    high = _num(s.get("fiftyTwoWeekHigh"))
    low = _num(s.get("fiftyTwoWeekLow"))
    beta = _num(s.get("beta"))
    if ticker == "DJT":
        score += 18
        why.append("Trump Media itself")
    if profit is not None and profit <= 0:
        score += 10
        why.append("the business is not the poster")
    if high and low and low > 0 and (high - low) / low > 0.8:
        score += 12
        why.append("wild swings — winners get screenshots")
    if beta is not None and beta > 1.6:
        score += 8
        why.append("moves on headlines")
    why.append("most people who chase this buy the top")
    return max(0, min(99, score)), why[:4]


def _load_row(ticker: str) -> dict[str, Any] | None:
    try:
        snap = fetch_snapshot(ticker)
    except Exception:
        return None
    if not snap.get("price") and not snap.get("marketCap"):
        return None
    q_score, q_why = _quality_score(snap)
    s_score, s_why = _speculative_score(snap)
    l_score, l_why = _longshot_score(snap)
    b_score, b_why = _bear_score(snap)
    e_score, e_why = _endorsement_score(snap)
    return {
        "snapshot": snap,
        "quality": q_score,
        "quality_why": q_why,
        "speculative": s_score,
        "speculative_why": s_why,
        "longshot": l_score,
        "longshot_why": l_why,
        "bear": b_score,
        "bear_why": b_why,
        "endorsement": e_score,
        "endorsement_why": e_why,
    }


def _market_label(snap: dict[str, Any]) -> str:
    ticker = str(snap.get("ticker") or "")
    exchange = str(snap.get("fullExchangeName") or snap.get("exchange") or "")
    suffix_map = {
        ".L": "London",
        ".DE": "Germany",
        ".F": "Frankfurt",
        ".PA": "Paris",
        ".AS": "Amsterdam",
        ".SW": "Switzerland",
        ".MI": "Milan",
        ".ST": "Stockholm",
        ".OL": "Oslo",
        ".CO": "Copenhagen",
        ".HE": "Helsinki",
        ".T": "Tokyo",
        ".HK": "Hong Kong",
        ".TO": "Toronto",
        ".AX": "Australia",
        ".NS": "India NSE",
        ".BO": "India BSE",
        ".KS": "Korea",
        ".SA": "Brazil",
        ".SS": "Shanghai",
        ".SZ": "Shenzhen",
    }
    for suf, label in suffix_map.items():
        if ticker.endswith(suf):
            return label
    if exchange:
        return exchange
    return "US"


def _row_card(row: dict[str, Any], score_key: str, why_key: str) -> dict[str, Any]:
    snap = row["snapshot"]
    return {
        "ticker": snap.get("ticker"),
        "name": snap.get("name"),
        "sector": snap.get("sector"),
        "market": _market_label(snap),
        "currency": snap.get("currency"),
        "price": snap.get("price"),
        "marketCap": snap.get("marketCap"),
        "score": row[score_key],
        "why": row[why_key],
    }


def run_screens(limit: int = 8) -> dict[str, Any]:
    cached = cache.get("screens:v6", ttl_seconds=45 * 60)
    if cached:
        return cached

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(_load_row, normalize_ticker(t)): t for t in UNIVERSE}
        for fut in as_completed(futs):
            item = fut.result()
            if item:
                rows.append(item)

    quality_ranked = sorted(
        [r for r in rows if r["quality"] >= 56 and _num(r["snapshot"].get("profitMargins")) is not None and _num(r["snapshot"].get("profitMargins")) > 0],
        key=lambda r: (-r["quality"], -(_num(r["snapshot"].get("returnOnEquity")) or 0)),
    )
    longshot_ranked = sorted(
        [r for r in rows if r["longshot"] >= 50],
        key=lambda r: -r["longshot"],
    )
    spec_ranked = sorted(
        [r for r in rows if r["speculative"] >= 48],
        key=lambda r: -r["speculative"],
    )

    quality = []
    quality_tickers: set[str] = set()
    for row in quality_ranked:
        quality.append(_row_card(row, "quality", "quality_why"))
        quality_tickers.add(row["snapshot"]["ticker"])
        if len(quality) >= limit:
            break

    longshot = []
    longshot_tickers: set[str] = set()
    for row in longshot_ranked:
        ticker = row["snapshot"]["ticker"]
        if ticker in quality_tickers:
            continue
        longshot.append(_row_card(row, "longshot", "longshot_why"))
        longshot_tickers.add(ticker)
        if len(longshot) >= 10:
            break

    speculative = []
    for row in spec_ranked:
        ticker = row["snapshot"]["ticker"]
        if ticker in quality_tickers and row["speculative"] < row["quality"] + 10:
            continue
        if ticker in longshot_tickers:
            continue
        speculative.append(_row_card(row, "speculative", "speculative_why"))
        if len(speculative) >= limit:
            break

    bear_ranked = sorted(
        [r for r in rows if r["bear"] >= 48],
        key=lambda r: (-r["bear"], -(_num(r["snapshot"].get("shortPercentOfFloat")) or 0)),
    )
    bear = []
    for row in bear_ranked:
        bear.append(_row_card(row, "bear", "bear_why"))
        if len(bear) >= limit:
            break

    endorsement_ranked = sorted(
        [r for r in rows if r["endorsement"] >= 50],
        key=lambda r: -r["endorsement"],
    )
    endorsement = []
    for row in endorsement_ranked:
        endorsement.append(_row_card(row, "endorsement", "endorsement_why"))
        if len(endorsement) >= 6:
            break

    payload = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "disclaimer": DISCLAIMER,
        "watchlist_size": len(UNIVERSE),
        "scored": len(rows),
        "quality": quality,
        "speculative": speculative,
        "longshot": longshot,
        "bear": bear,
        "endorsement": endorsement,
    }
    cache.put("screens:v6", payload)
    return payload
