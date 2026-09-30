"""Shared prohibited-content patterns for extraction, compilation, and publish."""
from __future__ import annotations

import os
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

# ---------------------------------------------------------------------------
# Guardrail: competency label validation
# Rejects entries that are not skills (seniority, years of experience,
# education requirements, or generic sentences).
# Config flag: GUARDRAIL_COMPETENCY_LABEL_VALIDATION (default ON)
# ---------------------------------------------------------------------------

def _flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val not in {"0", "false", "off", "no"}


GUARDRAIL_COMPETENCY_LABEL_VALIDATION: bool = _flag(
    "GUARDRAIL_COMPETENCY_LABEL_VALIDATION"
)

# Patterns that indicate a competency label is NOT a skill.
_NON_SKILL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Experience/years patterns: "5+ years", "2 years of", "years experience"
    re.compile(r"\b\d+\s*\+?\s*years?\b", re.I),
    re.compile(r"\byears?\s+of\s+(experience|exp)\b", re.I),
    re.compile(r"\bexperience\s+(?:in|with|of)\b", re.I),
    # Seniority labels used as competencies
    re.compile(r"^(senior|junior|mid[- ]?level|entry[- ]?level|lead|principal|staff)\s+\w", re.I),
    # Education requirements
    re.compile(r"\b(bachelor|master|phd|degree|diploma|b\.?tech|m\.?tech|b\.?e\.?|m\.?e\.?|mba)\b", re.I),
    re.compile(r"\b(computer science|engineering degree|graduate|undergraduate)\b", re.I),
    # Generic non-skill sentences (too long, likely a JD sentence)
    # A competency name should be short; sentences over 80 chars are rejected
)

_MIN_COMPETENCY_LENGTH = 2
_MAX_COMPETENCY_LENGTH = 80


def validate_competency_label(label: str) -> tuple[bool, str]:
    """Return (is_valid, reason).

    Returns (True, "") when the label is a valid skill/competency name.
    Returns (False, reason) when the label should be rejected.
    """
    if not GUARDRAIL_COMPETENCY_LABEL_VALIDATION:
        return True, ""

    cleaned = (label or "").strip()
    if len(cleaned) < _MIN_COMPETENCY_LENGTH:
        return False, "Competency name is too short."
    if len(cleaned) > _MAX_COMPETENCY_LENGTH:
        return (
            False,
            f"Competency name is too long ({len(cleaned)} chars). "
            "Use a skill name, not a full sentence.",
        )
    for pattern in _NON_SKILL_PATTERNS:
        if pattern.search(cleaned):
            return (
                False,
                f"'{cleaned}' looks like a seniority requirement, education requirement, "
                "or years-of-experience clause rather than a skill or competency. "
                "Use a skill name instead (e.g. 'Python', 'System Design', 'REST APIs').",
            )
    if contains_prohibited_content(cleaned):
        return False, f"'{cleaned}' contains a prohibited attribute."
    if contains_prompt_injection(cleaned):
        return False, f"'{cleaned}' contains a prompt injection attempt."
    return True, ""


def contains_prohibited_content(text: str) -> bool:
    blob = text or ""
    return any(pattern.search(blob) for pattern in PROHIBITED_PATTERNS)


def contains_prompt_injection(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _INJECTION_MARKERS)
