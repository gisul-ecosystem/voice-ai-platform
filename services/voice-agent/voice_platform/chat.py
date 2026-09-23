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
    words = [token.strip(".,!?;:\"'").lower() for token in text.split() if token.strip()]
    words = [word for word in words if word]
    if len(words) < max(1, min_words):
        return False
    if len(words) >= 6 and len(set(words)) <= 3:
        return False
    joined = " ".join(words)
    # Common Sarvam mis-hears of TTS while speakers are open.
    if joined.startswith("there are") and len(words) <= 12:
        return False
    agent_words = [
        token.strip(".,!?;:\"'").lower()
        for token in last_agent_text.split()
        if token.strip()
    ]
    agent_words = [word for word in agent_words if word]
    if agent_words:
        agent_set = set(agent_words)
        stop_words = {"what", "the", "you", "that", "how", "i", "can", "are", "is", "a", "of", "and", "in", "to", "did", "my", "your", "it", "this", "on", "for", "with", "as", "at"}
        filtered_words = [w for w in words if w not in stop_words]
        if filtered_words:
            overlap = sum(1 for word in filtered_words if word in agent_set) / len(filtered_words)
            if overlap >= 0.75:
                return False
        agent_joined = " ".join(agent_words)
        if len(words) >= 5:
            prefix = " ".join(words[:8])
            if prefix and prefix in agent_joined:
                return False
        if len(joined) >= 12 and (joined in agent_joined or agent_joined in joined):
            return False
    return True
