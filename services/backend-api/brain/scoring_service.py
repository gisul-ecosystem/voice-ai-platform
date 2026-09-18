"""Build and persist scorecards after interview completion."""
from __future__ import annotations

import logging
from typing import Any

from brain.scoring import build_scorecard_bundle, build_transcript_document
from db import brain as brain_db
from db import definitions, interviews, scorecards

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
            answers.append(
                {
                    "answer_id": f"a_synth_{turn.get('turn_id')}",
                    "question_id": pending_question["question_id"],
                    "session_id": session_id,
                    "turn_ids": [str(turn.get("turn_id"))],
                    "usable": len(text.split()) >= 3,
                    "usability": "usable" if len(text.split()) >= 3 else "too_short",
                    "final_transcript": text,
                    "status": "answered",
                }
            )
            pending_question = None
    return questions, answers
