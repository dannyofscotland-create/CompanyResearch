from __future__ import annotations

import json
import re

import httpx

from companyresearch.config import settings


def complete(system: str, user: str, *, temperature: float = 0.2, timeout: float = 90.0) -> tuple[str | None, str]:
    """Ask OpenAI, then Ollama. Returns (text, engine) or (None, "none")."""
    if settings.openai_api_key:
        try:
            return _openai(system, user, temperature, timeout), f"openai:{settings.llm_model}"
        except Exception:
            pass
    try:
        with httpx.Client(timeout=2.0) as client:
            live = client.get(settings.ollama_host.rstrip("/") + "/api/tags")
        if live.status_code == 200:
            return _ollama(system, user, temperature, min(timeout, 120.0)), f"ollama:{settings.ollama_model}"
    except Exception:
        pass
    return None, "none"


def complete_json(system: str, user: str) -> dict | list | None:
    text, _engine = complete(system, user, temperature=0.1, timeout=25.0)
    if not text:
        return None
    return _parse_json(text)


def _openai(system: str, user: str, temperature: float, timeout: float) -> str:
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    body = {
        "model": settings.llm_model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def _ollama(system: str, user: str, temperature: float, timeout: float) -> str:
    url = settings.ollama_host.rstrip("/") + "/api/chat"
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "options": {"temperature": temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        return r.json()["message"]["content"]


def _parse_json(text: str) -> dict | list | None:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None
