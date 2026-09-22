"""Build and persist scorecards after interview completion."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from brain.quality import compute_quality_metrics
from brain.scoring import build_scorecard_bundle, build_transcript_document
from db import brain as brain_db
from db import definitions, interviews, scorecards
from models.brain import ScorecardReviewEvent, ScorecardReviewRequest, utc_now

logger = logging.getLogger("backend-api.brain.scoring")


async def resolve_definition_for_session(session_id: str) -> dict[str, Any] | None:
    session = await interviews.get_session(session_id)
    if session is None:
        return None
    definition_id = session.get("definition_id")
    if not definition_id and session.get("context_id"):
        context = await interviews.get_context(str(session["context_id"]))
        if context:
            definition_id = context.get("definition_id")
    if not definition_id:
        snapshot = await brain_db.latest_durable_snapshot(session_id)
        if snapshot:
            definition_id = snapshot.get("definition_id")
    if not definition_id:
        return None
    stored = await definitions.get_definition(str(definition_id))
    if stored is None:
        return None
    payload = dict(stored)
    payload.pop("_id", None)
    return payload


async def get_full_transcript(session_id: str) -> dict[str, Any] | None:
    session = await interviews.get_session(session_id)
    if session is None:
        return None
    questions = await brain_db.list_session_questions(session_id)
    answers = await brain_db.list_session_answers(session_id)
    return build_transcript_document(
        session_id=session_id,
        turns=list(session.get("turns") or []),
        questions=questions,
        answers=answers,
    )


async def generate_and_store_scorecard(session_id: str) -> dict[str, Any] | None:
    existing = await scorecards.get_scorecard(session_id)
    if existing is not None:
        payload = dict(existing)
        payload.pop("_id", None)
        return payload

    definition = await resolve_definition_for_session(session_id)
    if definition is None:
        logger.warning(
            "scorecard_skipped_no_definition",
            extra={"event": "scorecard_skipped_no_definition", "session_id": session_id},
        )
        return None

    session = await interviews.get_session(session_id)
    if session is None:
        return None
    questions = await brain_db.list_session_questions(session_id)
    answers = await brain_db.list_session_answers(session_id)
    turns = list(session.get("turns") or [])
    snapshot = await brain_db.latest_durable_snapshot(session_id)
    coverage = snapshot.get("coverage") if isinstance(snapshot, dict) else None

    # If brain Q/A empty, synthesize from transcript turns so scoring still runs.
    if not questions and not answers and turns:
        questions, answers = _synthesize_qa_from_turns(session_id, turns)

    try:
        scorecard, evidence = build_scorecard_bundle(
            session_id=session_id,
            definition=definition,
            questions=questions,
            answers=answers,
            turns=turns,
            coverage=coverage if isinstance(coverage, dict) else None,
        )
    except ValueError as exc:
        logger.warning(
            "scorecard_build_failed",
            extra={
                "event": "scorecard_build_failed",
                "session_id": session_id,
                "error": str(exc),
            },
        )
        return None

    for record in evidence:
        await brain_db.upsert_evidence(record)
    await scorecards.save_scorecard(scorecard)
    logger.info(
        "scorecard_created",
        extra={
            "event": "scorecard_created",
            "session_id": session_id,
            "definition_id": scorecard.definition_id,
            "competency_count": len(scorecard.competencies),
            "recommendation": scorecard.overall_recommendation,
        },
    )
    return scorecard.model_dump(mode="python")


async def apply_scorecard_review(
    session_id: str,
    request: ScorecardReviewRequest,
) -> dict[str, Any]:
    stored = await scorecards.get_scorecard(session_id)
    if stored is None:
        raise ValueError("scorecard_not_found")
    event = ScorecardReviewEvent(
        review_id=f"rev_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        status=request.status,
        reviewer_id=request.reviewer_id,
        override_reason=request.override_reason,
        competency_overrides=list(request.competency_overrides),
        created_at=utc_now(),
    )
    await scorecards.save_review_event(event)
    await scorecards.apply_review_stamp(
        session_id,
        status=request.status,
        reviewer_id=request.reviewer_id,
        override_reason=request.override_reason,
        reviewed_at=event.created_at,
    )
    payload = await scorecards.get_scorecard_with_review(session_id)
    if payload is None:
        raise ValueError("scorecard_not_found")
    logger.info(
        "scorecard_reviewed",
        extra={
            "event": "scorecard_reviewed",
            "session_id": session_id,
            "status": request.status,
        },
    )
    return payload


async def get_session_quality_metrics(session_id: str) -> dict[str, Any] | None:
    session = await interviews.get_session(session_id)
    if session is None:
        return None
    questions = await brain_db.list_session_questions(session_id)
    answers = await brain_db.list_session_answers(session_id)
    snapshot = await brain_db.latest_durable_snapshot(session_id)
    coverage = snapshot.get("coverage") if isinstance(snapshot, dict) else None
    stored = await scorecards.get_scorecard(session_id)
    outcomes: list[str] = []
    if stored and isinstance(stored.get("competencies"), list):
        outcomes = [
            str(item.get("outcome") or "")
            for item in stored["competencies"]
            if isinstance(item, dict)
        ]
    metrics = compute_quality_metrics(
        questions=questions,
        answers=answers,
        coverage=coverage if isinstance(coverage, dict) else None,
        competency_outcomes=outcomes,
        validator_results=[
            item.get("validator_ok")
            for item in questions
            if isinstance(item, dict) and "validator_ok" in item
        ],
    )
    return metrics.model_dump(mode="python")


def _synthesize_qa_from_turns(
    session_id: str, turns: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    pending_question: dict[str, Any] | None = None
    for turn in sorted(
        turns,
        key=lambda item: int(item.get("sequence_number") or 0),
    ):
        speaker = turn.get("speaker")
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if speaker == "agent":
            pending_question = {
                "question_id": f"q_synth_{turn.get('turn_id')}",
                "session_id": session_id,
                "competency_id": None,
                "intent": "live_question",
                "depth": 1,
                "text": text,
                "status": "spoken",
            }
            questions.append(pending_question)
        elif speaker == "candidate" and pending_question is not None:
            evaluation = turn.get("answer_evaluation")
            evaluation = evaluation if isinstance(evaluation, dict) else None
            # Prefer the LLM's own read of the answer; word count is only a
            # last resort when no verdict was persisted with the turn.
            if evaluation is not None:
                usable = str(
                    evaluation.get("technical_substance") or ""
                ).strip().lower() not in {"", "not_applicable"}
            else:
                usable = len(text.split()) >= 3
            answers.append(
                {
                    "answer_id": f"a_synth_{turn.get('turn_id')}",
                    "question_id": pending_question["question_id"],
                    "session_id": session_id,
                    "turn_ids": [str(turn.get("turn_id"))],
                    "usable": usable,
                    "usability": "usable" if usable else "too_short",
                    "final_transcript": text,
                    "answer_evaluation": evaluation,
                    "status": "answered",
                }
            )
            pending_question = None
    return questions, answers
