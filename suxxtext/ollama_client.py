"""Minimal Ollama HTTP client (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("SUXXTEXT_OLLAMA_MODEL", "gemma4:e4b")


class OllamaError(RuntimeError):
    """Ollama API or connectivity failure."""


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def default_model() -> str:
    return os.environ.get("SUXXTEXT_OLLAMA_MODEL", DEFAULT_MODEL)


def ping(host: Optional[str] = None, timeout: float = 5.0) -> bool:
    """Return True if Ollama answers /api/tags."""
    base = (host or ollama_host()).rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def list_models(host: Optional[str] = None, timeout: float = 10.0) -> list:
    base = (host or ollama_host()).rstrip("/")
    req = urllib.request.Request(f"{base}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise OllamaError(f"Cannot list models at {base}: {e}") from e
    return [m.get("name") for m in data.get("models", []) if m.get("name")]


def generate(
    prompt: str,
    *,
    model: Optional[str] = None,
    host: Optional[str] = None,
    system: Optional[str] = None,
    format_json: bool = True,
    temperature: float = 0.2,
    num_predict: int = 512,
    timeout: float = 300.0,
) -> str:
    """
    Call Ollama /api/generate (non-streaming). Returns response text.
    When format_json=True, asks the model for a JSON object.
    """
    base = (host or ollama_host()).rstrip("/")
    payload: Dict[str, Any] = {
        "model": model or default_model(),
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    if system:
        payload["system"] = system
    if format_json:
        payload["format"] = "json"

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OllamaError(f"Ollama request failed ({base}): {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Invalid JSON from Ollama: {e}") from e

    if data.get("error"):
        raise OllamaError(str(data["error"]))

    text = data.get("response")
    if text is None:
        raise OllamaError(f"No response field in Ollama payload: {list(data.keys())}")
    return text
