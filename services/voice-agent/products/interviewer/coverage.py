"""Live competency coverage and answer classification."""
from __future__ import annotations

import re
from typing import Any

from products.interviewer.policy import classify_answer_usability

_WS = re.compile(r"\s+")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "establish_context": (
        "situation",
        "when",
        "team",
        "project",
        "role",
        "context",
        "working on",
        "assigned",
        "customer",
        "client",
    ),
    "establish_ownership": (
        "i handled",
        "i led",
        "i built",
        "i owned",
        "i was responsible",
        "my responsibility",
        "i implemented",
        "i ran",
        "i managed",
        "personally",
    ),
    "applied_understanding": (
        "how i",
        "approach",
        "method",
        "process",
        "steps",
        "we used",
        "i used",
        "designed",
        "because",
    ),
    "problem_or_complexity": (
        "difficult",
        "challenge",
        "failed",
        "issue",
        "constraint",
        "risk",
        "blocked",
        "incident",
        "problem",
    ),
    "tradeoff_or_transfer": (
        "tradeoff",
        "trade-off",
        "alternative",
        "instead",
        "would change",
        "next time",
        "learned",
        "chose",
    ),
    "candidate_map": (
        "background",
        "experience",
        "studied",
        "worked",
        "internship",
        "project",
    ),
    "baseline": (
        "example",
        "time when",
        "situation",
    ),
}

DEFAULT_INTENTS = (
    "establish_context",
    "establish_ownership",
    "applied_understanding",
)


def _tokens(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(part) > 2}


def competency_by_id(definition: dict[str, Any] | None, competency_id: str | None) -> dict[str, Any]:
    if not isinstance(definition, dict) or not competency_id:
        return {}
    for item in definition.get("competencies") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == competency_id:
            return item
    return {}


def ladder_steps(definition: dict[str, Any] | None, competency_id: str | None) -> list[dict[str, Any]]:
    if not isinstance(definition, dict) or not competency_id:
        return []
    for item in definition.get("question_ladders") or []:
        if isinstance(item, dict) and str(item.get("competency_id") or "") == competency_id:
            levels = item.get("levels") if isinstance(item.get("levels"), list) else []
            return [step for step in levels if isinstance(step, dict)]
    return []


def required_intents_for(
    definition: dict[str, Any] | None, competency_id: str | None
) -> list[str]:
    competency = competency_by_id(definition, competency_id)
    configured = [
        str(item).strip()
        for item in (competency.get("min_assessment_intents") or [])
        if str(item).strip()
    ]
    if configured:
        return configured
    steps = ladder_steps(definition, competency_id)
    from_ladder = [
        str(step.get("intent") or "").strip()
        for step in steps
        if str(step.get("intent") or "").strip()
    ]
    max_depth = int(competency.get("max_depth") or 4)
    if from_ladder:
        return from_ladder[: max(1, max_depth)]
    return list(DEFAULT_INTENTS[: max(1, min(max_depth, 3))])


def empty_coverage_entry(required: list[str]) -> dict[str, Any]:
    intents = [item for item in required if item]
    return {
        "status": "not_started",
        "required_intents": list(intents),
        "covered_intents": [],
        "missing_intents": list(intents),
        "evidence_ids": [],
    }


def init_coverage(definition: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    if not isinstance(definition, dict):
        return coverage
    for item in definition.get("competencies") or []:
        if not isinstance(item, dict):
            continue
        competency_id = str(item.get("id") or "").strip()
        if not competency_id:
            continue
        coverage[competency_id] = empty_coverage_entry(
            required_intents_for(definition, competency_id)
        )
    return coverage


def _intent_matched(text: str, intent: str) -> bool:
    lowered = (text or "").lower()
    for marker in INTENT_KEYWORDS.get(intent, ()):
        if marker in lowered:
            return True
    slug = intent.replace("_", " ")
    return slug in lowered


def classify_live_answer(
    text: str | None,
    *,
    required_intents: list[str],
    evidence_expected: list[str] | None = None,
    min_words: int = 3,
) -> tuple[str, str, list[str]]:
    """Return (usability, quality, newly_covered_intents)."""
    usability = classify_answer_usability(text, min_words=min_words)
    cleaned = _WS.sub(" ", (text or "").strip())
    if usability == "silence":
        return usability, "unusable", []
    if usability == "too_short":
        return usability, "unclear", []
    if usability == "explicit_unknown":
        return usability, "unsupported", []
    if usability != "usable":
        return usability, "unusable", []

    covered = [intent for intent in required_intents if _intent_matched(cleaned, intent)]
    expected = [item.strip() for item in (evidence_expected or []) if item and item.strip()]
    expected_hits = 0
    blob_tokens = _tokens(cleaned)
    for item in expected:
        needles = _tokens(item)
        if item.lower() in cleaned.lower() or (needles and needles & blob_tokens):
            expected_hits += 1

    if not covered and expected and expected_hits == 0 and len(cleaned.split()) >= 8:
        return "off_topic", "off_topic", []
    if len(covered) >= max(1, (len(required_intents) + 1) // 2) and expected_hits >= 1:
        quality = "sufficient"
    elif covered or expected_hits:
        quality = "partial"
    else:
        quality = "unclear"
    return "usable", quality, covered


def apply_coverage(
    coverage: dict[str, dict[str, Any]],
    *,
    competency_id: str | None,
    covered_intents: list[str],
    evidence_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not competency_id or competency_id not in coverage:
        return coverage
    entry = dict(coverage[competency_id])
    required = list(entry.get("required_intents") or [])
    already = list(entry.get("covered_intents") or [])
    for intent in covered_intents:
        if intent in required and intent not in already:
            already.append(intent)
    missing = [intent for intent in required if intent not in already]
    evidence_ids = list(entry.get("evidence_ids") or [])
    if evidence_id and evidence_id not in evidence_ids:
        evidence_ids.append(evidence_id)
    if not already:
        status = "not_started"
    elif missing:
        status = "partial"
    else:
        status = "complete"
    if already and not missing and not evidence_ids:
        status = "insufficient_evidence"
    coverage[competency_id] = {
        "status": status,
        "required_intents": required,
        "covered_intents": already,
        "missing_intents": missing,
        "evidence_ids": evidence_ids,
    }
    return coverage


def first_incomplete_competency(
    coverage: dict[str, dict[str, Any]],
    competency_ids: list[str],
) -> str | None:
    for competency_id in competency_ids:
        entry = coverage.get(competency_id) or {}
        if entry.get("missing_intents"):
            return competency_id
    return None
