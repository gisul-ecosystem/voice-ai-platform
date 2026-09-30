"""Helpers for reading provider-neutral text from LiveKit chat contexts."""
from __future__ import annotations

from typing import Any


def last_text(chat_ctx: Any, *, role: str = "user") -> str:
    """Return the most recent text item for a role."""
    for item in reversed(list(getattr(chat_ctx, "items", ()))):
        if getattr(item, "role", None) != role:
            continue
        text = getattr(item, "text_content", None)
        if not text:
            content = getattr(item, "content", None)
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(part for part in content if isinstance(part, str))
        if text:
            return text
    return ""
