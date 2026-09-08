# Company Research

A local research assistant that looks up a public company the way a careful person would: numbers and filings first, then several search angles (rivals, the bear case, why the share moved), then a few actual pages and a skim of the filing — not just the first Yahoo headline.

It does **not** place trades and it is **not** investment advice.

## Run on this PC

```powershell
cd F:\Local3DStudio\CompanyResearch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m companyresearch
```

Open http://127.0.0.1:8787

Tick **Keep watching on this machine** so the helper runs every ~10 minutes while this PC stays on (browser can close).

## Free phone / PC-off test (no paid host)

The paid Fly app was removed so nothing keeps billing. Use one of these **£0** paths:

### A) PC off — free GitHub timer + phone scoreboard

1. Push this repo to GitHub (public is easiest for free Actions minutes).
2. In the repo: **Settings → Pages → Source: GitHub Actions**.
3. **Actions → Free pretend helper watch → Run workflow** once.
4. After it finishes, open the Pages URL (Settings → Pages shows it), e.g. `https://YOURUSER.github.io/CompanyResearch/`.
5. It refreshes itself about every 30 minutes and every 5 minutes in the browser. Your desk PC can be off.

This is a **read-only scoreboard** on the phone (cash / holdings / last thoughts). Full clicky desk UI still needs the PC or a paid always-on box later.

### B) Phone while this PC stays on — free tunnel

```powershell
winget install Cloudflare.cloudflared
.\.venv\Scripts\Activate.ps1
python -m companyresearch
# other terminal:
cloudflared tunnel --url http://127.0.0.1:8787
```

Open the `https://….trycloudflare.com` link on your phone. Set `ACCESS_CODE` in `.env` first so strangers cannot use the desk. PC must stay awake.

### Paid later (optional)

`Dockerfile` / `fly.toml` / `deploy-fly.ps1` remain if you want a full always-on desk again (~a few pounds a month). Not needed for the free test.

Still pretend money only. A good fake week is not going live.
