const form = document.getElementById("form");
const input = document.getElementById("q");
const statusEl = document.getElementById("status");
const stepsEl = document.getElementById("steps");
const errorEl = document.getElementById("error");
const desk = document.getElementById("desk");
const empty = document.getElementById("empty");
const memoEl = document.getElementById("memo");
const go = document.getElementById("go");

let stream;
let lastBrief = null;

document.getElementById("chips").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-q]");
  if (!btn) return;
  input.value = btn.dataset.q;
  form.requestSubmit();
});

document.getElementById("boards").addEventListener("click", (event) => {
  const btn = event.target.closest("button.pick[data-q]");
  if (!btn) return;
  input.value = btn.dataset.q;
  form.requestSubmit();
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  start(q);
});

function start(q) {
  if (stream) stream.close();
  errorEl.hidden = true;
  empty.hidden = true;
  desk.hidden = true;
  statusEl.hidden = false;
  stepsEl.innerHTML = "";
  go.disabled = true;
  go.textContent = "Looking…";
  stream = new EventSource("/api/research?q=" + encodeURIComponent(q));
  stream.addEventListener("status", (ev) => {
    const data = JSON.parse(ev.data);
    addStep(data.label);
  });
  stream.addEventListener("done", (ev) => {
    const data = JSON.parse(ev.data);
    render(data);
    finish();
  });
  stream.addEventListener("fail", (ev) => {
    let message = "Research failed.";
    try {
      message = JSON.parse(ev.data).message || message;
    } catch {
      message = ev.data || message;
    }
    showError(message);
    finish();
  });
  stream.onerror = () => {
    const finishedOk = !desk.hidden;
    finish();
    if (!finishedOk && errorEl.hidden) {
      showError("Connection dropped while researching. Try again.");
    }
  };
}

function finish() {
  go.disabled = false;
  go.textContent = "Explain this";
  if (stream) {
    stream.close();
    stream = null;
  }
}

function addStep(label) {
  const li = document.createElement("li");
  li.textContent = label;
  li.className = "on";
  stepsEl.appendChild(li);
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function nfmt(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (Math.abs(num) >= 1e12) return (num / 1e12).toFixed(2) + "T";
  if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(2) + "B";
  if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(2) + "M";
  if (Math.abs(num) >= 1000) return num.toLocaleString();
  if (Math.abs(num) < 1 && Math.abs(num) > 0) return (num * 100).toFixed(1) + "%";
  return String(num);
}

function render(data) {
  desk.hidden = false;
  document.getElementById("asOf").textContent = data.as_of || "";
  document.getElementById("engine").textContent = "Writer: " + (data.engine || "template");
  const conf = data.confidence || {};
  const stamp = document.getElementById("stamp");
  stamp.className = "stamp " + String(conf.label || "").toLowerCase();
  document.getElementById("stampLabel").textContent = "How much we found";
  document.getElementById("stampScore").textContent = (conf.score ?? "—") + "";
  const snap = data.snapshot || {};
  lastBrief = { ticker: data.ticker, name: data.name };
  renderGuide(data.guide, snap.price);
  memoEl.innerHTML = window.marked ? marked.parse(data.memo || "") : "<pre></pre>";
  if (!window.marked) memoEl.querySelector("pre").textContent = data.memo || "";

  fillChased(data.investigation || {});
  const rows = [
    ["Name", data.ticker],
    ["Share price", snap.price],
    ["How big the company is", snap.marketCap],
    ["What kind of business", snap.sector],
    ["Price vs last year's profit", snap.trailingPE],
    ["Sales growing?", snap.revenueGrowth],
    ["How much debt", snap.debtToEquity],
    ["Insiders", snap.heldPercentInsiders],
    ["Institutions", snap.heldPercentInstitutions],
    ["Already shorted", snap.shortPercentOfFloat],
    ["Days to cover", snap.shortRatio],
  ];
  document.getElementById("snap").innerHTML = rows
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(nfmt(v))}</dd>`)
    .join("");

  fillSources("src-primary", (data.sources || []).filter((s) => s.class === "primary"));
  fillSources(
    "src-secondary",
    (data.sources || []).filter((s) => s.class === "secondary" && !s.echo)
  );
  fillSources(
    "src-noise",
    (data.sources || []).filter((s) => s.class === "noise" || s.echo || s.class === "unknown")
  );

  const own = data.ownership || {};
  const inst = (own.institutions || []).slice(0, 5);
  const bits = [];
  if (inst.length) {
    bits.push("<p class='hint'>Big funds (this list is often months late):</p><ul class='src'>");
    for (const row of inst) {
      const holder = row.Holder || row.holder || "Unknown";
      const shares = row.Shares || row.shares || "";
      bits.push(`<li>${escapeHtml(holder)}<div class='meta'>${escapeHtml(String(shares))}</div></li>`);
    }
    bits.push("</ul>");
  } else {
    bits.push("<p class='hint'>No institutional table this time.</p>");
  }
  document.getElementById("owners").innerHTML = bits.join("");
}

function fillChased(inv) {
  const el = document.getElementById("chased");
  if (!el) return;
  const bits = [];
  for (const q of inv.questions || []) {
    bits.push({ title: q.why || q.q, meta: "first pass" });
  }
  for (const q of inv.chased || []) {
    bits.push({ title: q.why || q.q, meta: q.how || "follow-up" });
  }
  for (const note of inv.tensions || []) {
    bits.push({ title: note, meta: "disagreement" });
  }
  const clues = inv.clues || {};
  for (const light of (clues.crash && clues.crash.lights) || []) {
    bits.push({ title: light, meta: "crash clue · " + (clues.crash.level || "") });
  }
  for (const light of (clues.endorsement && clues.endorsement.lights) || []) {
    bits.push({ title: light, meta: "endorsement / pump" });
  }
  if (!bits.length) {
    el.innerHTML = "<li class='meta'>This run did not record follow-up questions.</li>";
    return;
  }
  el.innerHTML = bits
    .slice(0, 12)
    .map((item) => `<li>${escapeHtml(item.title)}<div class="meta">${escapeHtml(item.meta)}</div></li>`)
    .join("");
}

function fillSources(id, items) {
  const el = document.getElementById(id);
  if (!items.length) {
    el.innerHTML = "<li class='meta'>None in this pull.</li>";
    return;
  }
  el.innerHTML = items
    .slice(0, 10)
    .map((item) => {
      const title = escapeHtml(item.title || "Untitled");
          const meta = [item.domain || item.publisher, item.angle, item.filed || item.published, item.copies > 1 ? item.copies + " copies" : ""]
        .filter(Boolean)
        .join(" · ");
      if (item.url) {
        return `<li><a href="${escapeAttr(item.url)}" target="_blank" rel="noopener">${title}</a><div class="meta">${escapeHtml(meta)}</div></li>`;
      }
      return `<li>${title}<div class="meta">${escapeHtml(meta)}</div></li>`;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function fillBoard(id, items) {
  const el = document.getElementById(id);
  if (!items || !items.length) {
    el.innerHTML = "<li class='empty'>Nothing cleared the bar this run.</li>";
    return;
  }
  el.innerHTML = items
    .map((item) => {
      const why = escapeHtml((item.why || []).join(" · "));
      const name = escapeHtml(item.name || item.ticker);
      const ticker = escapeHtml(item.ticker);
      const market = item.market ? escapeHtml(item.market) + " · " : "";
      return `<li><button type="button" class="pick" data-q="${escapeAttr(item.ticker)}">
        <span class="sym">${ticker}</span>
        <span class="nm">${name}</span>
        <span class="sc">${escapeHtml(String(item.score))}</span>
        <span class="why">${market}${why}</span>
      </button></li>`;
    })
    .join("");
}

async function loadBoards() {
  const note = document.getElementById("board-note");
  try {
    const res = await fetch("/api/screens");
    if (!res.ok) throw new Error("screen failed");
    const data = await res.json();
    fillBoard("board-quality", data.quality);
    fillBoard("board-spec", data.speculative);
    fillBoard("board-longshot", data.longshot);
    fillBoard("board-bear", data.bear);
    fillBoard("board-endorsement", data.endorsement);
    note.textContent =
      "Steadier names already make money. Long shots are lottery-ticket shaped. Shorts and endorsement boards are warning shapes — not tips, and not a way to sell ‘just before’ a crash. Updated " +
      (data.as_of || "") +
      ".";
  } catch {
    document.getElementById("board-quality").innerHTML = "<li class='empty'>Could not score the quality board.</li>";
    document.getElementById("board-spec").innerHTML = "<li class='empty'>Could not score the high-upside board.</li>";
    document.getElementById("board-longshot").innerHTML = "<li class='empty'>Could not score the long-shot board.</li>";
    const bearBoard = document.getElementById("board-bear");
    if (bearBoard) bearBoard.innerHTML = "<li class='empty'>Could not score the short-interest board.</li>";
    const endBoard = document.getElementById("board-endorsement");
    if (endBoard) endBoard.innerHTML = "<li class='empty'>Could not score the endorsement board.</li>";
  }
}

loadBoards();

let lastGuide = null;

function gbp(n) {
  if (!Number.isFinite(n)) return "—";
  if (n < 0) n = 0;
  return "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  const sign = num > 0 ? "+" : "";
  return sign + (num * 100).toFixed(0) + "%";
}

function annuityFuture(pmt, annualRate, years, timesPerYear) {
  const n = years * timesPerYear;
  const r = annualRate / timesPerYear;
  if (Math.abs(r) < 1e-8) return pmt * n;
  return pmt * (Math.pow(1 + r, n) - 1) / r;
}

function updateMoney() {
  if (!lastGuide || !lastGuide.annual) return;
  const amount = Math.max(1, Number(document.getElementById("pounds").value) || 10);
  const years = Math.max(1, Number(document.getElementById("years").value) || 5);
  const annual = lastGuide.annual;
  document.getElementById("path-tough").textContent = gbp(amount * Math.pow(1 + Number(annual.tough || 0), years));
  document.getElementById("path-middle").textContent = gbp(amount * Math.pow(1 + Number(annual.middle || 0), years));
  document.getElementById("path-lucky").textContent = gbp(amount * Math.pow(1 + Number(annual.lucky || 0), years));

  const drip = Math.max(1, Number(document.getElementById("dripPounds").value) || 10);
  const perYear = Number(document.getElementById("dripEvery").value) || 52;
  const dripYears = Number(document.getElementById("dripYears").value) || 20;
  const putIn = drip * perYear * dripYears;
  document.getElementById("dripIn").textContent = gbp(putIn);
  // Quiet mixed-market sketch for retirement — not "doubled in a week".
  document.getElementById("drip-tough").textContent = gbp(annuityFuture(drip, 0.02, dripYears, perYear));
  document.getElementById("drip-middle").textContent = gbp(annuityFuture(drip, 0.06, dripYears, perYear));
  document.getElementById("drip-lucky").textContent = gbp(annuityFuture(drip, 0.09, dripYears, perYear));
}

function renderGuide(guide, sharePrice) {
  lastGuide = guide || {};
  const kind = lastGuide.kind || "mixed";
  const labels = { steadier: "Steadier", gamble: "Bigger gamble", longshot: "Long shot", endorsement: "Endorsement lottery", bear: "Shorts pick on", mixed: "In the middle" };
  const tag = document.getElementById("kindTag");
  tag.textContent = labels[kind] || "In the middle";
  tag.className = "kind-tag " + kind;
  document.getElementById("headline").textContent = lastGuide.headline || "";
  document.getElementById("oneLiner").textContent = lastGuide.one_liner || "";
  document.getElementById("blurb").textContent = lastGuide.blurb || "";
  document.getElementById("guideWarn").textContent = lastGuide.warning || "";
  const price = Number(sharePrice);
  const slice = document.getElementById("sliceNote");
  if (Number.isFinite(price) && price > 0) {
    slice.textContent =
      "One whole share is about " +
      price.toLocaleString("en-GB", { maximumFractionDigits: 2 }) +
      " dollars. You do not need that much. Many UK apps sell you a slice for £10 or £60. Your slice goes up and down by the same percent as a big investor’s pile.";
  } else {
    slice.textContent =
      "You do not need to buy a whole share. Many UK apps let you put in £10 or £60 and own a crumb of a big company.";
  }
  const bits = [];
  if (lastGuide.if_10_then && lastGuide.historical_years) {
    bits.push(
      "If you had put £10 in about " +
        lastGuide.historical_years +
        " years ago, it would be about " +
        gbp(Number(lastGuide.if_10_then)) +
        " today. The next years will not copy the last ones."
    );
  }
  if (lastGuide.last_year_return != null) {
    bits.push("Over the last year the share moved about " + pct(lastGuide.last_year_return) + ".");
  }
  if (lastGuide.analyst_1y != null) {
    bits.push("Other analysts’ 12-month guesses imply about " + pct(lastGuide.analyst_1y) + " over a year. Those guesses are often wrong.");
  }
  document.getElementById("hist").textContent = bits.join(" ");
  const shortEl = document.getElementById("shortNote");
  if (shortEl) shortEl.textContent = lastGuide.short_note || "";
  updateMoney();
}

document.getElementById("pounds").addEventListener("input", updateMoney);
document.getElementById("years").addEventListener("change", updateMoney);
document.getElementById("dripPounds").addEventListener("input", updateMoney);
document.getElementById("dripEvery").addEventListener("change", updateMoney);
document.getElementById("dripYears").addEventListener("change", updateMoney);

function paintWallet(data) {
  document.getElementById("w-cash").textContent = gbp(data.cash_gbp);
  document.getElementById("w-hold").textContent = gbp(data.holdings_gbp);
  document.getElementById("w-total").textContent = gbp(data.total_gbp);
  const pnl = Number(data.profit_gbp);
  const pnlEl = document.getElementById("w-pnl");
  pnlEl.textContent = (pnl >= 0 ? "+" : "") + gbp(Math.abs(pnl)).replace("£", "£");
  if (Number(data.profit_gbp) < 0) pnlEl.textContent = "-" + gbp(Math.abs(pnl)).slice(1);
  if (pnl > 0) pnlEl.style.color = "#8fbf9a";
  else if (pnl < 0) pnlEl.style.color = "#e0a0a0";
  else pnlEl.style.color = "";
  const helper = data.helper || {};
  const helperEl = document.getElementById("helper-note");
  if (helperEl) {
    helperEl.textContent = helper.note || "";
  }
  paintWatch(data.watch);
  const log = document.getElementById("auto-log");
  const steps = data.last_autopilot || [];
  if (log) {
    log.innerHTML = steps.length
      ? steps.map((s) => `<li>${escapeHtml((s.action || "") + (s.ticker ? " " + s.ticker : "") + " — " + (s.why || ""))}</li>`).join("")
      : "";
  }
  const list = document.getElementById("hold-list");
  const rows = data.holdings || [];
  if (!rows.length) {
    list.innerHTML = "<li class='empty'>No pretend holdings yet.</li>";
    return;
  }
  list.innerHTML = rows
    .map((row) => {
      const ch = Number(row.change_gbp);
      const chs = (ch >= 0 ? "+" : "") + gbp(ch);
      const kind = row.kind ? " · " + row.kind : "";
      return `<li>
        <button type="button" class="pick-hold" data-q="${escapeAttr(row.ticker)}">${escapeHtml(row.ticker)} · ${escapeHtml(row.name || "")}<div class="meta">${gbp(row.now_gbp)} (${chs})${escapeHtml(kind)}</div></button>
        <button type="button" class="sell-hold" data-sell="${escapeAttr(row.ticker)}">Sell pretend</button>
      </li>`;
    })
    .join("");
}

async function refreshWallet() {
  try {
    const res = await fetch("/api/paper");
    if (!res.ok) return;
    paintWallet(await res.json());
  } catch {
    /* wallet stays empty */
  }
}

function failDetail(data) {
  if (!data) return "That did not work.";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((x) => x.msg || x).join(" ");
  return "That did not work.";
}

document.getElementById("paperBuy").addEventListener("click", async () => {
  const msg = document.getElementById("paperBuyMsg");
  if (!lastBrief || !lastBrief.ticker) {
    msg.textContent = "Look a company up first, then put pretend money in.";
    return;
  }
  const amount = Math.max(1, Number(document.getElementById("paperBuyAmt").value) || 10);
  msg.textContent = "Using pretend cash…";
  const res = await fetch("/api/paper/buy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker: lastBrief.ticker, amount_gbp: amount }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    msg.textContent = failDetail(data);
    return;
  }
  msg.textContent = "Pretend £" + amount + " is now in " + lastBrief.ticker + ". Not a pension. Not a bank.";
  paintWallet(data);
});

document.getElementById("w-reset").addEventListener("click", async () => {
  if (!window.confirm("Wipe only the pretend wallet on this PC? Real pensions cannot be touched.")) return;
  const res = await fetch("/api/paper/reset", { method: "POST" });
  if (res.ok) paintWallet(await res.json());
});

let watchTimer = null;

function paintWatch(watch) {
  const box = document.getElementById("w-watch");
  const status = document.getElementById("watch-status");
  if (!watch) return;
  if (box && document.activeElement !== box) {
    box.checked = !!watch.enabled;
  }
  if (status) {
    if (watch.enabled) {
      status.textContent =
        "Watching on this machine" +
        (watch.last_run ? " · last pass " + watch.last_run : "") +
        (watch.last_error ? " · " + watch.last_error : "");
    } else {
      status.textContent = "Watching is off. Helper only moves when you click the button.";
    }
  }
}

async function setWatch(enabled) {
  const res = await fetch("/api/paper/watch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !!enabled }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showError(failDetail(data));
    return;
  }
  paintWatch(data);
  refreshWallet();
}

async function runAutopilot() {
  const btn = document.getElementById("w-auto");
  btn.disabled = true;
  btn.textContent = "Helper is thinking…";
  try {
    const res = await fetch("/api/paper/autopilot", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showError(failDetail(data));
      return;
    }
    paintWallet(data);
  } finally {
    btn.disabled = false;
    btn.textContent = "Let the helper move pretend money";
  }
}

document.getElementById("w-auto").addEventListener("click", () => {
  runAutopilot();
});

document.getElementById("w-watch").addEventListener("change", (event) => {
  setWatch(event.target.checked);
});

// Refresh the scoreboard while watching so you can leave the tab open or come back later.
watchTimer = setInterval(() => {
  const box = document.getElementById("w-watch");
  if (box && box.checked) refreshWallet();
}, 60 * 1000);

document.getElementById("hold-list").addEventListener("click", async (event) => {
  const look = event.target.closest("button.pick-hold[data-q]");
  if (look) {
    input.value = look.dataset.q;
    form.requestSubmit();
    return;
  }
  const sell = event.target.closest("button.sell-hold[data-sell]");
  if (!sell) return;
  const res = await fetch("/api/paper/sell", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker: sell.dataset.sell }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showError(failDetail(data));
    return;
  }
  paintWallet(data);
});

refreshWallet();
