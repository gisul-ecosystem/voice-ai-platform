"""Shared prohibited-content patterns for extraction, compilation, and publish."""
from __future__ import annotations

import re

PROHIBITED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(age|birthday|birth ?date)\b", re.I),
    re.compile(r"\b(marital|married|spouse|children|pregnant)\b", re.I),
    re.compile(r"\b(religion|caste|race|ethnicity|nationality)\b", re.I),
    re.compile(r"\b(disability|medical|illness|health condition)\b", re.I),
    re.compile(r"\b(gender|sex orientation|sexual orientation)\b", re.I),
)

_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "disregard previous",
    "system prompt",
    "you are now",
    "jailbreak",
)


def contains_prohibited_content(text: str) -> bool:
    blob = text or ""
    return any(pattern.search(blob) for pattern in PROHIBITED_PATTERNS)


def contains_prompt_injection(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _INJECTION_MARKERS)
