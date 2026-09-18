"""Evidence-linked scorecard generation (advisory; always requires human review).

Numeric ratings are only emitted when answers overlap expected evidence and
meet min_evidence_per_competency. Heuristic fallback never invents a low
score from English ownership idioms.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from brain.quality import compute_quality_metrics
from models.brain import (
    CompetencyScore,
    EvidenceStrength,
    InterviewEvidenceRecord,
    InterviewScorecard,
    ScorecardQualityMetrics,
    utc_now,
)

_RESULT_MARKERS = (
    "result",
    "outcome",
    "impact",
    "improved",
    "reduced",
    "increased",
    "metric",
    "latency",
    "revenue",
    "saved",
)
_TRADEOFF_MARKERS = (
    "tradeoff",
    "trade-off",
    "alternative",
    "instead",
    "would change",
    "next time",
    "because",
)

_INTENT_FOLLOWUPS = {
    "establish_context": "Ask for a concrete work situation related to {name}.",
    "establish_ownership": "Ask what the candidate personally handled for {name}.",
    "applied_understanding": "Ask how the candidate approached the {name} work.",
    "problem_or_complexity": "Ask what was difficult about the {name} work.",
    "tradeoff_or_transfer": "Ask what they would change about the {name} work and why.",
}


def _tokens(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(part) > 2}


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _strength_for_answer(text: str, expected: list[str]) -> EvidenceStrength:
    cleaned = (text or "").strip()
    if len(cleaned.split()) < 8:
        return "weak"
    hits = 0
    blob = cleaned.lower()
    for item in expected:
        needle = (item or "").strip().lower()
        if not needle:
            continue
        if needle in blob or any(token in _tokens(cleaned) for token in _tokens(needle)):
            hits += 1
    has_result = _contains_any(cleaned, _RESULT_MARKERS)
    has_tradeoff = _contains_any(cleaned, _TRADEOFF_MARKERS)
    words = len(cleaned.split())
    if hits >= 2 and has_result and has_tradeoff:
        return "strong"
    if hits >= 2 and words >= 12 and has_result:
        return "sufficient"
    if hits >= 1 and words >= 8:
        return "partial"
    return "weak"


def _rating_from_strength(
    strength: EvidenceStrength,
    *,
    evidence_count: int,
    min_evidence: int = 1,
) -> tuple[int | None, str]:
    if evidence_count <= 0:
        return None, "not_assessed"
    if evidence_count < max(1, min_evidence) or strength in {"none", "weak", "contradictory"}:
        return None, "insufficient_evidence"
    mapping = {
        "partial": 3,
        "sufficient": 4,
        "strong": 5,
    }
    rating = mapping.get(strength)
    if rating is None:
        return None, "insufficient_evidence"
    return rating, "scored"


def _anchor_for_rating(competency: dict[str, Any], rating: int | None) -> str | None:
    if rating is None:
        return None
    rubric = competency.get("rubric") if isinstance(competency.get("rubric"), list) else []
    for item in rubric:
        if isinstance(item, dict) and int(item.get("rating") or 0) == rating:
            return str(item.get("description") or "")[:500] or None
    # Prefer nearest lower anchor.
    candidates = sorted(
        (
            int(item.get("rating") or 0),
            str(item.get("description") or ""),
        )
        for item in rubric
        if isinstance(item, dict) and item.get("rating") is not None
    )
    chosen = None
    for value, description in candidates:
        if value <= rating:
            chosen = description
    return (chosen or None) and chosen[:500]


def _recommendation(
    scores: list[CompetencyScore],
    *,
    weights: dict[str, float] | None = None,
    importance: dict[str, str] | None = None,
) -> str:
    if not scores:
        return "human_decision_required"
    weight_map = weights or {}
    importance_map = importance or {}
    scored = [item for item in scores if item.rating is not None]
    if not scored:
        return "insufficient_evidence"

    def _weight_for(item: CompetencyScore) -> float:
        value = weight_map.get(item.competency_id)
        if value is None:
            return 1.0
        return max(0.0, float(value))

    scored_weight = sum(_weight_for(item) for item in scored)
    total_weight = sum(_weight_for(item) for item in scores) or 1.0
    if scored_weight < (total_weight * 0.5):
        return "insufficient_evidence"
    high_missing = any(
        importance_map.get(item.competency_id, "high") == "high"
        and item.outcome in {"not_assessed", "insufficient_evidence"}
        for item in scores
    )
    average = sum((item.rating or 0) * _weight_for(item) for item in scored) / max(
        scored_weight, 0.01
    )
    if high_missing and average < 4.5:
        if average >= 3.2:
            return "mixed_evidence"
        return "human_decision_required"
    if average >= 4.5:
        return "strong_evidence"
    if average >= 3.2:
        return "meets_expectations"
    if average >= 2.5:
        return "mixed_evidence"
    return "human_decision_required"


def _next_human_questions(
    *,
    name: str,
    missing_evidence: list[str],
    missing_intents: list[str],
) -> list[str]:
    questions: list[str] = []
    for intent in missing_intents[:3]:
        template = _INTENT_FOLLOWUPS.get(intent)
        if template:
            questions.append(template.format(name=name.lower())[:400])
    for item in missing_evidence[:2]:
        questions.append(
            f"Ask for a concrete example that shows {item.lower()} for {name.lower()}."
        )
    return questions[:4]


def build_transcript_document(
    *,
    session_id: str,
    turns: list[dict[str, Any]],
    questions: list[dict[str, Any]] | None = None,
    answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(
        [dict(turn) for turn in turns if isinstance(turn, dict)],
        key=lambda item: (
            int(item.get("sequence_number") or 0),
            str(item.get("created_at") or ""),
        ),
    )
    spoken = [
        {
            "turn_id": item.get("turn_id"),
            "speaker": item.get("speaker"),
            "text": item.get("text"),
            "phase_index": item.get("phase_index"),
            "sequence_number": item.get("sequence_number"),
            "created_at": item.get("created_at"),
            "is_final": item.get("is_final", True),
        }
        for item in ordered
        if str(item.get("text") or "").strip()
    ]
    char_count = sum(len(str(item.get("text") or "")) for item in spoken)
    return {
        "session_id": session_id,
        "turn_count": len(spoken),
        "candidate_turn_count": sum(
            1 for item in spoken if item.get("speaker") == "candidate"
        ),
        "agent_turn_count": sum(1 for item in spoken if item.get("speaker") == "agent"),
        "character_count": char_count,
        "turns": spoken,
        "questions": questions or [],
        "answers": answers or [],
    }


def build_scorecard_bundle(
    *,
    session_id: str,
    definition: dict[str, Any],
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    turns: list[dict[str, Any]] | None = None,
    coverage: dict[str, Any] | None = None,
) -> tuple[InterviewScorecard, list[InterviewEvidenceRecord]]:
    definition_id = str(definition.get("definition_id") or "").strip()
    if not definition_id:
        raise ValueError("definition_id is required for scoring")
    competencies = [
        item
        for item in (definition.get("competencies") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not competencies:
        raise ValueError("definition has no competencies to score")
    scoring_policy = definition.get("scoring_policy") if isinstance(definition.get("scoring_policy"), dict) else {}
    min_evidence = int(scoring_policy.get("min_evidence_per_competency") or 1)

    answers_by_question = {
        str(item.get("question_id")): item
        for item in answers
        if isinstance(item, dict) and item.get("question_id")
    }
    questions_by_competency: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        if not isinstance(question, dict):
            continue
        competency_id = str(question.get("competency_id") or "").strip()
        if not competency_id:
            continue
        questions_by_competency.setdefault(competency_id, []).append(question)

    # Fallback: attribute unmatched usable answers round-robin by keyword overlap.
    orphan_answers = [
        item
        for item in answers
        if isinstance(item, dict)
        and item.get("usable", True)
        and str(item.get("final_transcript") or "").strip()
        and str(item.get("question_id") or "") not in {
            str(q.get("question_id"))
            for values in questions_by_competency.values()
            for q in values
        }
    ]

    evidence_records: list[InterviewEvidenceRecord] = []
    scores: list[CompetencyScore] = []
    followups: list[str] = []
    weights: dict[str, float] = {}
    importance: dict[str, str] = {}

    for competency in competencies:
        competency_id = str(competency["id"])
        name = str(competency.get("name") or competency_id)
        weights[competency_id] = float(competency.get("weight") or 0) or 1.0
        importance[competency_id] = str(competency.get("importance") or "high")
        expected = [
            str(item).strip()
            for item in (competency.get("evidence_expected") or [])
            if str(item).strip()
        ]
        required_intents = [
            str(item).strip()
            for item in (competency.get("min_assessment_intents") or [])
            if str(item).strip()
        ]
        related_questions = list(questions_by_competency.get(competency_id) or [])
        related_answers: list[dict[str, Any]] = []
        for question in related_questions:
            answer = answers_by_question.get(str(question.get("question_id")))
            if answer and answer.get("usable", True):
                related_answers.append(answer)

        if not related_answers and orphan_answers:
            # Keyword attribution once.
            remaining = []
            for answer in orphan_answers:
                text = str(answer.get("final_transcript") or "")
                if any(
                    needle.lower() in text.lower()
                    for needle in expected + [str(competency.get("name") or "")]
                    if needle
                ):
                    related_answers.append(answer)
                else:
                    remaining.append(answer)
            orphan_answers = remaining

        competency_evidence_ids: list[str] = []
        best_strength: EvidenceStrength = "none"
        missing = list(expected)
        excerpts: list[str] = []
        for answer in related_answers:
            text = str(answer.get("final_transcript") or "").strip()
            if not text:
                continue
            strength = _strength_for_answer(text, expected)
            rank = {
                "none": 0,
                "weak": 1,
                "partial": 2,
                "sufficient": 3,
                "strong": 4,
                "contradictory": 1,
            }
            if rank.get(strength, 0) > rank.get(best_strength, 0):
                best_strength = strength
            for item in list(missing):
                if item.lower() in text.lower() or any(
                    token in _tokens(text) for token in _tokens(item)
                ):
                    missing.remove(item)
            evidence_id = f"ev_{uuid.uuid4().hex[:16]}"
            turn_ids = [
                str(value)
                for value in (answer.get("turn_ids") or [])
                if str(value).strip()
            ]
            if not turn_ids:
                # Fall back to any candidate turns containing the answer text.
                for turn in turns or []:
                    if (
                        isinstance(turn, dict)
                        and turn.get("speaker") == "candidate"
                        and text[:40] in str(turn.get("text") or "")
                    ):
                        turn_ids.append(str(turn.get("turn_id")))
                        break
            if not turn_ids:
                turn_ids = [f"turn_synthetic_{uuid.uuid4().hex[:10]}"]
            evidence_records.append(
                InterviewEvidenceRecord(
                    evidence_id=evidence_id,
                    session_id=session_id,
                    competency_id=competency_id,
                    question_id=str(answer.get("question_id") or "") or None,
                    turn_ids=turn_ids[:50],
                    claim=text[:2000],
                    strength=strength,
                    missing_details=missing[:20],
                    confidence=0.55
                    if strength == "weak"
                    else 0.7
                    if strength == "partial"
                    else 0.82
                    if strength == "sufficient"
                    else 0.9
                    if strength == "strong"
                    else 0.4,
                )
            )
            competency_evidence_ids.append(evidence_id)
            if len(excerpts) < 3:
                excerpts.append(text[:240])

        asked_intents = {
            str(item.get("intent") or "").strip()
            for item in related_questions
            if str(item.get("intent") or "").strip()
        }
        coverage_row = (coverage or {}).get(competency_id) if isinstance(coverage, dict) else None
        covered_intents = set()
        if isinstance(coverage_row, dict):
            covered_intents = {
                str(item).strip()
                for item in (coverage_row.get("covered_intents") or [])
                if str(item).strip()
            }
        missing_intents = [
            intent
            for intent in required_intents
            if intent not in asked_intents and intent not in covered_intents
        ]

        rating, outcome = _rating_from_strength(
            best_strength,
            evidence_count=len(competency_evidence_ids),
            min_evidence=min_evidence,
        )
        scores.append(
            CompetencyScore(
                competency_id=competency_id,
                rating=rating,
                outcome=outcome,  # type: ignore[arg-type]
                anchor=_anchor_for_rating(competency, rating),
                evidence_ids=competency_evidence_ids,
                contradictory_evidence_ids=[],
                missing_evidence=missing[:20],
                missing_intents=missing_intents[:20],
                excerpts=excerpts[:8],
                confidence=(
                    0.0
                    if outcome != "scored"
                    else max(
                        (item.confidence for item in evidence_records if item.evidence_id in competency_evidence_ids),
                        default=0.5,
                    )
                ),
                review_required=True,
            )
        )
        followups.extend(
            _next_human_questions(
                name=name,
                missing_evidence=missing,
                missing_intents=missing_intents,
            )
        )

    quality_metrics: ScorecardQualityMetrics = compute_quality_metrics(
        questions=questions,
        answers=answers,
        coverage=coverage,
        competency_outcomes=[item.outcome for item in scores],
        validator_results=[
            item.get("validator_ok")
            for item in questions
            if isinstance(item, dict) and "validator_ok" in item
        ],
    )
    scorecard = InterviewScorecard(
        session_id=session_id,
        definition_id=definition_id,
        competencies=scores,
        overall_recommendation=_recommendation(
            scores, weights=weights, importance=importance
        ),  # type: ignore[arg-type]
        human_review_status="pending",
        created_at=utc_now(),
        next_human_questions=list(dict.fromkeys(followups))[:12],
        quality_metrics=quality_metrics,
    )
    return scorecard, evidence_records
