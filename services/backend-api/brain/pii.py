"""PII stripping for LLM prompt inputs.

Guardrail: GUARDRAIL_PII_STRIP (default ON).
Strips phone numbers, email addresses, home addresses, and government ID
patterns from text before it is sent to the LLM. The interview proceeds
on content and skills; personal identifiers add no value and create risk.

Only applied when sending to the LLM (extract/recommend endpoints).
Does NOT modify data stored in MongoDB — retention/encryption handles that.

Config flag: GUARDRAIL_PII_STRIP (env, default ON).
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("backend-api.pii")


def _flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val not in {"0", "false", "off", "no"}


GUARDRAIL_PII_STRIP: bool = _flag("GUARDRAIL_PII_STRIP")

# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

# Email addresses: local@domain.tld
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)

# Phone numbers: handles +91-XXXXX-XXXXX, (555) 123-4567, 555.123.4567, etc.
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.])?(?:\(?\d{2,4}\)?[\s\-.])\d{3,4}[\s\-.]?\d{4,6}",
)

# Indian Aadhaar: 12-digit number optionally space/dash separated in groups of 4
_AADHAAR = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")

# PAN card: AAAAA9999A
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

# Passport numbers: common international patterns (6–9 alphanumeric)
_PASSPORT = re.compile(r"\b[A-Z][0-9]{6,8}\b")

# Home address lines: "123 Any Street", "Flat 4B, Tower ...", "No. 7, ..."
# Heuristic: digit followed by street/avenue/road/lane/colony/nagar/sector keywords
_ADDRESS_LINE = re.compile(
    r"\b\d{1,5}[A-Za-z]?[,\s]+(?:[A-Za-z0-9,\s]+\s+)?(?:street|st|avenue|ave|road|rd|lane|ln|"
    r"colony|nagar|sector|block|phase|floor|flat|apartment|apt|building|bldg|"
    r"house|plot|villa|residency|residences|enclave|park|garden|layout|extension|extn)\b",
    re.IGNORECASE,
)

# ZIP / postal codes: 5-digit US, 6-digit India, UK-style
_POSTAL = re.compile(r"\b\d{5,6}\b|\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b")

# Social Security Number (US) — 9 digits in groups
_SSN = re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b")

_ALL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", _EMAIL),
    ("phone", _PHONE),
    ("aadhaar", _AADHAAR),
    ("pan", _PAN),
    ("passport", _PASSPORT),
    ("address", _ADDRESS_LINE),
    ("postal", _POSTAL),
    ("ssn", _SSN),
]

_REDACT_TOKEN = "[REDACTED]"


def strip_pii(text: str | None, *, label: str = "text") -> str:
    """Remove PII patterns from text before it is sent to an LLM.

    Returns the stripped text. If GUARDRAIL_PII_STRIP is OFF, returns text unchanged.
    Logs one line summarising what was found, never logging the actual PII values.
    """
    if not text:
        return text or ""
    if not GUARDRAIL_PII_STRIP:
        return text

    result = text
    found: list[str] = []
    for kind, pattern in _ALL_PATTERNS:
        before = result
        result = pattern.sub(_REDACT_TOKEN, result)
        if result != before:
            found.append(kind)

    if found:
        logger.info(
            "guardrail_pii_stripped",
            extra={
                "event": "guardrail_pii_stripped",
                "guardrail": "GUARDRAIL_PII_STRIP",
                "label": label,
                "pii_types_found": found,
                "chars_before": len(text),
                "chars_after": len(result),
            },
        )

    return result


def strip_pii_from_resume(resume_text: str | None) -> str:
    """Convenience wrapper for resume text."""
    return strip_pii(resume_text, label="resume")


def strip_pii_from_jd(jd_text: str | None) -> str:
    """Convenience wrapper for job description text."""
    return strip_pii(jd_text, label="job_description")
