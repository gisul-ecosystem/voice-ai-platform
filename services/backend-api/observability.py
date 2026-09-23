"""Request correlation without carrying user content into telemetry."""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_CORRELATION_ID = ContextVar("correlation_id", default="")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def set_correlation_id(value: str | None) -> str:
    selected = (
        value.strip()
        if value and _SAFE_ID.fullmatch(value.strip())
        else f"cor_{uuid.uuid4().hex}"
    )
    _CORRELATION_ID.set(selected)
    return selected


def get_correlation_id() -> str:
    return _CORRELATION_ID.get() or set_correlation_id(None)
