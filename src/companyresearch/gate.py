from __future__ import annotations

import hashlib
import secrets
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from companyresearch.config import settings

COOKIE = "cr_gate"


def _token() -> str:
    code = (settings.access_code or "").strip()
    if not code:
        return ""
    return hashlib.sha256(f"companyresearch:{code}".encode("utf-8")).hexdigest()


def gate_required() -> bool:
    return bool((settings.access_code or "").strip())


def check_code(code: str) -> bool:
    expected = (settings.access_code or "").strip()
    if not expected:
        return True
    return secrets.compare_digest(code.strip(), expected)


def cookie_ok(request: Request) -> bool:
    if not gate_required():
        return True
    got = request.cookies.get(COOKIE) or ""
    return secrets.compare_digest(got, _token())


def is_public(path: str) -> bool:
    if path.startswith("/static/"):
        return True
    return path in {"/login", "/api/login", "/api/health", "/favicon.ico"}


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>Company Research — unlock</title>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
    .gate {
      max-width: 420px;
      margin: 12vh auto 40px;
      padding: 0 20px;
    }
    .gate h1 {
      font-family: Newsreader, Georgia, serif;
      font-size: 32px;
      margin: 0 0 10px;
    }
    .gate p { color: var(--muted); line-height: 1.45; }
    .gate form {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 22px;
    }
    .gate input {
      background: var(--chip);
      border: 1px solid var(--line);
      color: var(--ink);
      padding: 14px 12px;
      font-size: 16px;
    }
    .gate button {
      background: var(--brass);
      color: #1c1812;
      border: 0;
      padding: 14px 12px;
      font-size: 16px;
      font-weight: 600;
    }
    .gate .err { color: #e0a0a0; min-height: 1.2em; }
  </style>
</head>
<body>
  <div class="gate">
    <p class="eyebrow">Pretend wallet — phone unlock</p>
    <h1>Enter your access code</h1>
    <p>This keeps strangers off your pretend scoreboard. Still not a bank. Still cannot take cash.</p>
    <form id="gate">
      <label class="sr" for="code">Access code</label>
      <input id="code" name="code" type="password" autocomplete="current-password" inputmode="text" placeholder="Access code" required />
      <button type="submit">Open</button>
      <p class="err" id="err"></p>
    </form>
  </div>
  <script>
    document.getElementById("gate").addEventListener("submit", async (event) => {
      event.preventDefault();
      const err = document.getElementById("err");
      err.textContent = "";
      const code = document.getElementById("code").value;
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) {
        err.textContent = "Wrong code.";
        return;
      }
      location.href = "/";
    });
  </script>
</body>
</html>
"""


class AccessGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if not gate_required() or is_public(request.url.path):
            return await call_next(request)
        if cookie_ok(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Unlock with your access code."}, status_code=401)
        return RedirectResponse("/login", status_code=303)


def set_gate_cookie(response: Response, *, secure: bool) -> None:
    response.set_cookie(
        COOKIE,
        _token(),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=60 * 60 * 24 * 90,
    )


def login_page() -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML)
