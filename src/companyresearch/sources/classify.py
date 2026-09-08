from __future__ import annotations

from urllib.parse import urlparse

PRIMARY_DOMAINS = {
    "sec.gov",
    "www.sec.gov",
    "data.sec.gov",
    "efts.sec.gov",
}

STRONG_SECONDARY = {
    "reuters.com",
    "www.reuters.com",
    "bloomberg.com",
    "www.bloomberg.com",
    "ft.com",
    "www.ft.com",
    "wsj.com",
    "www.wsj.com",
    "apnews.com",
    "www.apnews.com",
    "nytimes.com",
    "www.nytimes.com",
    "economist.com",
    "www.economist.com",
    "associatedpress.com",
}

SECONDARY = {
    "cnbc.com",
    "www.cnbc.com",
    "bbc.com",
    "www.bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "www.theguardian.com",
    "forbes.com",
    "www.forbes.com",
    "marketwatch.com",
    "www.marketwatch.com",
    "barrons.com",
    "www.barrons.com",
    "fortune.com",
    "www.fortune.com",
    "wsj.com",
    "finance.yahoo.com",
    "yahoo.com",
    "www.yahoo.com",
    "seekingalpha.com",
    "www.seekingalpha.com",
    "investopedia.com",
    "www.investopedia.com",
    "businesswire.com",
    "www.businesswire.com",
    "prnewswire.com",
    "www.prnewswire.com",
}

NOISE = {
    "reddit.com",
    "www.reddit.com",
    "twitter.com",
    "x.com",
    "www.x.com",
    "stocktwits.com",
    "youtube.com",
    "www.youtube.com",
    "tiktok.com",
    "www.tiktok.com",
    "facebook.com",
    "www.facebook.com",
    "motleyfool.com",
    "www.fool.com",
    "fool.com",
    "wikipedia.org",
    "en.wikipedia.org",
    "quora.com",
    "pinterest.com",
    "tumblr.com",
    "steamcommunity.com",
    "steampowered.com",
    "fandom.com",
    "wikia.com",
}


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_url(url: str, source_kind: str = "") -> str:
    if source_kind in {"sec", "filing", "financials"}:
        return "primary"
    host = domain_of(url)
    if not host:
        return "unknown"
    if host == "sec.gov" or host.endswith(".sec.gov"):
        return "primary"
    if host in STRONG_SECONDARY or any(host.endswith("." + d) for d in ("reuters.com", "bloomberg.com", "ft.com", "wsj.com")):
        return "secondary"
    if host in SECONDARY:
        return "secondary"
    if host in NOISE or any(n in host for n in ("reddit.", "stocktwits", "youtube", "tiktok", "wikipedia.", "fandom.", "steam")):
        return "noise"
    if any(bit in host for bit in ("forum", "boards.", "disqus")):
        return "noise"
    return "unknown"


def title_fingerprint(title: str) -> str:
    words = [w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in title).split() if len(w) > 2]
    return " ".join(words[:8])


def collapse_stories(items: list[dict]) -> list[dict]:
    """Keep one item per similar headline; note how many copies existed."""
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        if item.get("origin") == "sec_edgar" or item.get("class") == "primary":
            key = item.get("url") or f"sec:{item.get('form')}:{item.get('filed')}:{item.get('title')}"
        else:
            key = title_fingerprint(item.get("title") or "") or item.get("url") or str(len(order))
        if key not in grouped:
            grouped[key] = {**item, "copies": 1, "copy_domains": [item.get("domain") or ""]}
            order.append(key)
        else:
            grouped[key]["copies"] += 1
            domain = item.get("domain") or ""
            if domain and domain not in grouped[key]["copy_domains"]:
                grouped[key]["copy_domains"].append(domain)
    out = []
    for key in order:
        row = grouped[key]
        independent = len({d for d in row["copy_domains"] if d})
        row["independent_domains"] = independent
        row["echo"] = row.get("class") != "primary" and row["copies"] > 1 and independent <= 1
        out.append(row)
    return out
