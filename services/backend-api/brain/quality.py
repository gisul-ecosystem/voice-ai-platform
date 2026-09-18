"""Session quality metrics that never include transcript or PII text."""
from __future__ import annotations

import re
from typing import Any

from models.brain import ScorecardQualityMetrics

_PUNCT = re.compile(r"[^a-z0-9]+")


def _fingerprint(text: str) -> str:
    cleaned = _PUNCT.sub(" ", (text or "").lower())
    return " ".join(cleaned.split())


def compute_quality_metrics(
    *,
    questions: list[dict[str, Any]] | None = None,
    answers: list[dict[str, Any]] | None = None,
    coverage: dict[str, Any] | None = None,
    competency_outcomes: list[str] | None = None,
    validator_results: list[bool | None] | None = None,
) -> ScorecardQualityMetrics:
    question_rows = [item for item in (questions or []) if isinstance(item, dict)]
    fingerprints = [_fingerprint(str(item.get("text") or "")) for item in question_rows]
    fingerprints = [item for item in fingerprints if item]
    unique = set(fingerprints)
    repeated_question_rate = 0.0
    if fingerprints:
        repeated_question_rate = round(
            max(0.0, (len(fingerprints) - len(unique)) / len(fingerprints)),
            4,
        )

    coverage_rows = [
        value
        for value in (coverage or {}).values()
        if isinstance(value, dict)
    ]
    complete = sum(1 for item in coverage_rows if item.get("status") == "complete")
    mandatory_coverage_pct = (
        round(100.0 * complete / len(coverage_rows), 2) if coverage_rows else 0.0
    )

    outcomes = [str(item or "") for item in (competency_outcomes or [])]
    not_assessed_rate = 0.0
    insufficient_evidence_rate = 0.0
    if outcomes:
        not_assessed_rate = round(
            sum(1 for item in outcomes if item == "not_assessed") / len(outcomes),
            4,
        )
        insufficient_evidence_rate = round(
            sum(1 for item in outcomes if item == "insufficient_evidence") / len(outcomes),
            4,
        )

    validator_failure_rate = 0.0
    checked = [item for item in (validator_results or []) if item is not None]
    if checked:
        validator_failure_rate = round(
            sum(1 for item in checked if item is False) / len(checked),
            4,
        )

    return ScorecardQualityMetrics(
        mandatory_coverage_pct=mandatory_coverage_pct,
        repeated_question_rate=repeated_question_rate,
        not_assessed_rate=not_assessed_rate,
        insufficient_evidence_rate=insufficient_evidence_rate,
        validator_failure_rate=validator_failure_rate,
        question_count=len(question_rows),
        answer_count=len([item for item in (answers or []) if isinstance(item, dict)]),
    )
