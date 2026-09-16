"""Keyword/substring retrieval over kb.json. No embeddings or vector store."""
from __future__ import annotations

import json
import re
from pathlib import Path

_KB_PATH = Path(__file__).resolve().parent / "kb.json"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "long",
    "my",
    "of",
    "on",
    "or",
    "take",
    "the",
    "to",
    "what",
    "when",
    "where",
    "you",
    "your",
}

_entries: list[dict] | None = None


def _load_kb() -> list[dict]:
    global _entries
    if _entries is None:
        _entries = json.loads(_KB_PATH.read_text(encoding="utf-8"))
    return _entries


def _tokens(text: str) -> set[str]:
    return {tok for tok in _TOKEN.findall((text or "").lower()) if tok not in _STOPWORDS and len(tok) >= 3}


def _overlap(query_tokens: set[str], blob_tokens: set[str]) -> int:
    score = 0
    for q in query_tokens:
        if q in blob_tokens:
            score += 2
            continue
        if len(q) < 4:
            continue
        if any(b.startswith(q) or q.startswith(b) for b in blob_tokens if len(b) >= 4):
            score += 1
    return score


def retrieve_context(query: str) -> list[str]:
    """Return the top 2–3 KB snippets by substring/keyword overlap."""
    raw = (query or "").strip().lower()
    if not raw:
        return []
    q_tokens = _tokens(raw)
    scored: list[tuple[int, dict]] = []
    for entry in _load_kb():
        topic = str(entry.get("topic") or "")
        content = str(entry.get("content") or "")
        blob = f"{topic} {content}".lower()
        score = 0
        if raw in blob:
            score += 8
        score += _overlap(q_tokens, _tokens(topic)) * 2
        score += _overlap(q_tokens, _tokens(blob))
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [f"{e.get('topic', '')}: {e.get('content', '')}".strip() for _, e in scored[:3]]
