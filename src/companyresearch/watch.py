from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from companyresearch.config import settings

INTERVAL_SECONDS = 10 * 60
_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def _path() -> Path:
    path = settings.data_dir / "watch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def status() -> dict[str, Any]:
    path = _path()
    enabled = False
    last_run = ""
    last_error = ""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            enabled = bool(data.get("enabled"))
            last_run = str(data.get("last_run") or "")
            last_error = str(data.get("last_error") or "")
        except (OSError, json.JSONDecodeError):
            pass
    alive = _thread is not None and _thread.is_alive()
    return {
        "enabled": enabled,
        "running": enabled and alive,
        "interval_minutes": INTERVAL_SECONDS // 60,
        "last_run": last_run,
        "last_error": last_error,
        "note": (
            "While this is on, the helper keeps researching and trading pretend money on the machine "
            "where the app is running — even if you close the browser. "
            "If you turn that machine off, everything stops. For a few days with the PC off, "
            "run the app on a cheap always-on server (see README)."
        ),
    }


def _save(enabled: bool, *, last_run: str | None = None, last_error: str | None = None) -> None:
    path = _path()
    data: dict[str, Any] = {"enabled": enabled}
    if path.exists():
        try:
            data = {**json.loads(path.read_text(encoding="utf-8")), "enabled": enabled}
        except (OSError, json.JSONDecodeError):
            data = {"enabled": enabled}
    if last_run is not None:
        data["last_run"] = last_run
    if last_error is not None:
        data["last_error"] = last_error
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_enabled(enabled: bool) -> dict[str, Any]:
    with _lock:
        _save(bool(enabled))
        if enabled:
            _ensure_thread()
        else:
            _stop.set()
    return status()


def start_if_needed() -> None:
    """Call on app startup so a previous ‘keep watching’ survives a restart."""
    if status()["enabled"]:
        _ensure_thread()


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="paper-watch", daemon=True)
    _thread.start()


def _loop() -> None:
    from companyresearch.paper import autopilot
    from datetime import datetime, timezone

    # First pass soon after enabling, then every INTERVAL.
    while not _stop.is_set():
        if not status()["enabled"]:
            break
        try:
            autopilot()
            _save(
                True,
                last_run=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                last_error="",
            )
        except Exception as exc:
            _save(
                True,
                last_run=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                last_error=str(exc)[:300],
            )
        if _stop.wait(INTERVAL_SECONDS):
            break
