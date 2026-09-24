"""Helpers for reading provider-neutral text from LiveKit chat contexts."""
from __future__ import annotations

from typing import Any


def last_text(chat_ctx: Any, *, role: str = "user") -> str:
    """Return the most recent text item for a role."""
    for item in reversed(list(getattr(chat_ctx, "items", ()))):
        if getattr(item, "role", None) != role:
            continue
        text = _item_text(item)
        if text:
            return text
    return ""


def word_count(text: str) -> int:
    words = [token.strip(".,!?;:\"'").lower() for token in text.split() if token.strip()]
    return len([word for word in words if word])


def looks_like_agent_echo(text: str, last_agent_text: str = "") -> bool:
    """True when STT likely captured the agent's own TTS (not a short answer)."""
    words = [token.strip(".,!?;:\"'").lower() for token in text.split() if token.strip()]
    words = [word for word in words if word]
    if not words:
        return False
    joined = " ".join(words)
    if joined.startswith("there are") and len(words) <= 12:
        return True
    if len(words) >= 6 and len(set(words)) <= 3:
        return True
    agent_words = [
        token.strip(".,!?;:\"'").lower()
        for token in last_agent_text.split()
        if token.strip()
    ]
    agent_words = [word for word in agent_words if word]
    if not agent_words:
        return False
    agent_set = set(agent_words)
    overlap = sum(1 for word in words if word in agent_set) / len(words)
    if overlap >= 0.45:
        return True
    agent_joined = " ".join(agent_words)
    if len(words) >= 5:
        prefix = " ".join(words[:8])
        if prefix and prefix in agent_joined:
            return True
    if len(joined) >= 12 and (joined in agent_joined or agent_joined in joined):
        return True
    return False


def _item_text(item: Any) -> str:
    text = getattr(item, "text_content", None)
    if callable(text):
        try:
            text = text()
        except TypeError:
            text = None
    if text:
        return str(text).strip()
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(part for part in content if isinstance(part, str)).strip()
    return ""


def is_usable_candidate_turn(
    text: str,
    last_agent_text: str = "",
    *,
    min_words: int = 3,
) -> bool:
    """Drop echo, one-word noise, and collapsed STT loops before follow-ups."""
    if word_count(text) < max(1, min_words):
        return False
    if looks_like_agent_echo(text, last_agent_text):
        return False
    return True
