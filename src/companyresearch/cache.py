from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from companyresearch.config import settings


def _cache_dir() -> Path:
    path = settings.data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return _cache_dir() / f"{digest}.json"


def get(key: str, ttl_seconds: int) -> Any | None:
    path = _path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - payload.get("ts", 0) > ttl_seconds:
        return None
    return payload.get("data")


def put(key: str, data: Any) -> None:
    path = _path(key)
    path.write_text(json.dumps({"ts": time.time(), "data": data}, default=str), encoding="utf-8")
