from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from companyresearch.paper import snapshot


def write_scoreboard(out_dir: str | Path) -> Path:
    """Write a phone-friendly HTML scoreboard (for free GitHub Pages)."""
    data = snapshot()
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "wallet.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    path = dest / "index.html"
    path.write_text(_html(data), encoding="utf-8")
    return path


def _money(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"£{n:,.2f}"


def _html(data: dict[str, Any]) -> str:
    holdings = data.get("holdings") or []
    log = data.get("last_autopilot") or []
    rows = []
    for row in holdings:
        ch = float(row.get("change_gbp") or 0)
        sign = "+" if ch >= 0 else ""
        rows.append(
            "<li><strong>{ticker}</strong> · {name}<div class='meta'>{now} ({sign}{ch}) · {kind}</div></li>".format(
                ticker=html.escape(str(row.get("ticker") or "")),
                name=html.escape(str(row.get("name") or "")),
                now=_money(row.get("now_gbp")),
                sign=sign,
                ch=_money(abs(ch)),
                kind=html.escape(str(row.get("kind") or "")),
            )
        )
    log_rows = [
        "<li>{action} {ticker} — {why}</li>".format(
            action=html.escape(str(item.get("action") or "")),
            ticker=html.escape(str(item.get("ticker") or "")),
            why=html.escape(str(item.get("why") or "")),
        )
        for item in log[:12]
    ]
    profit = float(data.get("profit_gbp") or 0)
    profit_s = ("+" if profit > 0 else "−" if profit < 0 else "") + _money(abs(profit))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta http-equiv="refresh" content="300" />
  <title>Pretend helper scoreboard</title>
  <style>
    :root {{ --bg:#12110c; --ink:#ece6d6; --muted:#9a917f; --brass:#c4a574; --line:#2a271f; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family: system-ui, sans-serif; padding:20px 16px 48px; }}
    h1 {{ font-size:28px; margin:0 0 8px; }}
    p {{ color:var(--muted); line-height:1.45; }}
    .nums {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:18px 0; }}
    .nums div {{ border:1px solid var(--line); padding:12px; }}
    .nums span {{ display:block; color:var(--muted); font-size:12px; }}
    .nums strong {{ font-size:20px; }}
    ul {{ list-style:none; padding:0; margin:0; }}
    li {{ border-top:1px solid var(--line); padding:12px 0; }}
    .meta {{ color:var(--muted); font-size:13px; margin-top:4px; }}
    .lock {{ color:var(--brass); text-transform:uppercase; letter-spacing:.08em; font-size:12px; }}
  </style>
</head>
<body>
  <p class="lock">Free pretend scoreboard · not a bank · cannot take cash</p>
  <h1>Helper practice run</h1>
  <p>Updated from a free GitHub timer. Your desk PC can be off. This is not live investing.</p>
  <div class="nums">
    <div><span>Cash</span><strong>{_money(data.get("cash_gbp"))}</strong></div>
    <div><span>Holdings</span><strong>{_money(data.get("holdings_gbp"))}</strong></div>
    <div><span>Total</span><strong>{_money(data.get("total_gbp"))}</strong></div>
    <div><span>Up / down</span><strong>{profit_s}</strong></div>
  </div>
  <h2>Holdings</h2>
  <ul>{"".join(rows) or "<li class='meta'>No pretend holdings yet.</li>"}</ul>
  <h2>Last helper thoughts</h2>
  <ul>{"".join(log_rows) or "<li class='meta'>No pass logged yet.</li>"}</ul>
</body>
</html>
"""
