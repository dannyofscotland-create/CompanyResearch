from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from companyresearch import watch as paper_watch
from companyresearch.gate import AccessGate, check_code, gate_required, login_page, set_gate_cookie
from companyresearch.memo import DISCLAIMER, write_memo
from companyresearch.net import using_insecure_ssl
from companyresearch.paper import autopilot as paper_autopilot
from companyresearch.paper import buy as paper_buy
from companyresearch.paper import reset as paper_reset
from companyresearch.paper import sell as paper_sell
from companyresearch.paper import snapshot as paper_snapshot
from companyresearch.pipeline import iter_research
from companyresearch.screens import run_screens

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    paper_watch.start_if_needed()
    yield


app = FastAPI(title="Company Research", version="0.1.0", lifespan=lifespan)
app.add_middleware(AccessGate)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login() -> HTMLResponse:
    return login_page()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "gate": gate_required()}


class LoginBody(BaseModel):
    code: str = Field(default="", max_length=120)


@app.post("/api/login")
def api_login(body: LoginBody, request: Request) -> JSONResponse:
    if not check_code(body.code):
        raise HTTPException(401, "Wrong code.")
    response = JSONResponse({"ok": True})
    if gate_required():
        set_gate_cookie(response, secure=request.url.scheme == "https")
    return response


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/api/screens")
def screens() -> dict:
    return run_screens()


class PaperBuy(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    amount_gbp: float = Field(gt=0, le=10000)


class PaperSell(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)


class WatchBody(BaseModel):
    enabled: bool


@app.get("/api/paper")
def paper_get() -> dict:
    out = paper_snapshot()
    out["watch"] = paper_watch.status()
    return out


@app.post("/api/paper/buy")
def paper_buy_route(body: PaperBuy) -> dict:
    try:
        out = paper_buy(body.ticker, body.amount_gbp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out["watch"] = paper_watch.status()
    return out


@app.post("/api/paper/sell")
def paper_sell_route(body: PaperSell) -> dict:
    try:
        out = paper_sell(body.ticker)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out["watch"] = paper_watch.status()
    return out


@app.post("/api/paper/reset")
def paper_reset_route() -> dict:
    out = paper_reset()
    out["watch"] = paper_watch.status()
    return out


@app.post("/api/paper/autopilot")
def paper_autopilot_route() -> dict:
    out = paper_autopilot()
    out["watch"] = paper_watch.status()
    return out


@app.get("/api/paper/watch")
def paper_watch_get() -> dict:
    return paper_watch.status()


@app.post("/api/paper/watch")
def paper_watch_set(body: WatchBody) -> dict:
    return paper_watch.set_enabled(body.enabled)


@app.get("/api/research")
def research(q: str = Query(..., min_length=1, max_length=80)) -> StreamingResponse:
    query = q.strip()
    if not query:
        raise HTTPException(400, "Enter a ticker or company name.")

    def generate():
        packet = None
        try:
            for kind, data in iter_research(query):
                if kind == "status":
                    yield _sse("status", data)
                else:
                    packet = data
            if packet is None:
                yield _sse("fail", {"message": "Research returned nothing."})
                return
            if using_insecure_ssl() and "TLS certificate checks were skipped" not in str(packet.get("errors")):
                packet.setdefault("errors", []).append(
                    "TLS certificate checks were skipped after this PC's certificate store failed."
                )
            yield _sse("status", {"step": "memo", "label": "Writing up what the dig found"})
            markdown, engine = write_memo(packet)
            yield _sse(
                "done",
                {
                    "memo": markdown,
                    "engine": engine,
                    "disclaimer": DISCLAIMER,
                    "ticker": packet["ticker"],
                    "name": packet["name"],
                    "confidence": packet["confidence"],
                    "sources": packet["sources"],
                    "investigation": packet.get("investigation") or {},
                    "ownership": packet["ownership"],
                    "snapshot": packet["snapshot"],
                    "errors": packet["errors"],
                    "as_of": packet["as_of"],
                    "guide": packet.get("guide") or {},
                },
            )
        except Exception as exc:
            yield _sse("fail", {"message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
