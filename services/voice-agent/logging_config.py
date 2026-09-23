"""JSON-lines logging shared by the voice-agent process.

Format is one JSON object per line so these logs can later be scraped into
the observability stack without rewriting call sites.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

_BUILTIN = {
    "args",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}

# Client-provided keys must never land in log files or observability tooling.
_SECRET_EXACT = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "openai_api_key",
        "llm_api_key",
        "stt_api_key",
        "tts_api_key",
        "api_key_override",
    }
)


def _is_secret_field(name: str) -> bool:
    n = name.lower().replace("-", "_")
    if n in _SECRET_EXACT:
        return True
    return n.endswith("_api_key") or n.endswith("_apikey")


def redact_secrets(value: Any, key: str | None = None) -> Any:
    """Strip API keys from log payloads, including nested dicts."""
    if key is not None and _is_secret_field(key):
        return "***"
    if isinstance(value, dict):
        return {k: redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _BUILTIN and not key.startswith("_"):
                payload[key] = redact_secrets(value, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        payload["service"] = "voice-agent"
        return json.dumps(redact_secrets(payload), default=str)


class _RateLimitLoopMonitor(logging.Filter):
    """Stop LiveKit loop-monitor warnings from amplifying the stall.

    Writing large stack dumps under a logging lock while the loop is already
    blocked creates a feedback loop → "job executor is unresponsive".
    Allow one sample per window so production still sees the signal.
    """

    _MARKERS = (
        "event loop blocked",
        "job executor is unresponsive",
    )

    def __init__(self, interval_seconds: float = 30.0) -> None:
        super().__init__()
        self._interval = max(1.0, float(interval_seconds))
        self._last_emit = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not any(marker in message for marker in self._MARKERS):
            return True
        now = time.monotonic()
        if now - self._last_emit < self._interval:
            return False
        self._last_emit = now
        # Drop the huge stack sample so emit stays cheap under pressure.
        if hasattr(record, "stack"):
            record.stack = "(rate-limited; see prior sample)"
        return True


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_RateLimitLoopMonitor())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("livekit").setLevel(logging.INFO)
