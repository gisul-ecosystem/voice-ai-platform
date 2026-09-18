"""Durable Mongo persistence for interview brain records (layer 3)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from db.mongo import get_db
from models.brain import (
    InterviewAnswerRecord,
    InterviewBrainState,
    InterviewEvidenceRecord,
    InterviewQuestionRecord,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_brain_indexes() -> None:
    db = get_db()
    await db.interview_questions.create_index(
        [("session_id", 1), ("question_id", 1)], unique=True
    )
    await db.interview_questions.create_index([("session_id", 1), ("asked_at", 1)])
    await db.interview_answers.create_index(
        [("session_id", 1), ("answer_id", 1)], unique=True
    )
    await db.interview_answers.create_index(
        [("session_id", 1), ("question_id", 1)], unique=True
    )
    await db.interview_evidence.create_index(
        [("session_id", 1), ("evidence_id", 1)], unique=True
    )
    await db.interview_evidence.create_index(
        [("session_id", 1), ("competency_id", 1)]
    )
    await db.interview_brain_snapshots.create_index(
        [("session_id", 1), ("state_version", 1)], unique=True
    )
    await db.interview_brain_snapshots.create_index(
        [("session_id", 1), ("updated_at", -1)]
    )


async def upsert_question(record: InterviewQuestionRecord) -> str:
    db = get_db()
    document = record.model_dump(mode="python")
    existing = await db.interview_questions.find_one(
        {"session_id": record.session_id, "question_id": record.question_id}
    )
    if existing:
        comparable = ("text", "intent", "depth", "competency_id", "status")
        if all(existing.get(key) == document.get(key) for key in comparable):
            return "duplicate"
        return "conflict"
    try:
        await db.interview_questions.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def upsert_answer(record: InterviewAnswerRecord) -> str:
    db = get_db()
    document = record.model_dump(mode="python")
    existing = await db.interview_answers.find_one(
        {"session_id": record.session_id, "answer_id": record.answer_id}
    )
    if existing:
        comparable = ("question_id", "final_transcript", "usable", "usability")
        if all(existing.get(key) == document.get(key) for key in comparable):
            return "duplicate"
        return "conflict"
    by_question = await db.interview_answers.find_one(
        {"session_id": record.session_id, "question_id": record.question_id}
    )
    if by_question and by_question.get("answer_id") != record.answer_id:
        return "conflict"
    try:
        await db.interview_answers.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def upsert_evidence(record: InterviewEvidenceRecord) -> str:
    db = get_db()
    document = record.model_dump(mode="python")
    existing = await db.interview_evidence.find_one(
        {"session_id": record.session_id, "evidence_id": record.evidence_id}
    )
    if existing:
        comparable = ("competency_id", "claim", "strength", "question_id")
        if all(existing.get(key) == document.get(key) for key in comparable):
            return "duplicate"
        return "conflict"
    try:
        await db.interview_evidence.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def save_durable_snapshot(state: InterviewBrainState) -> str:
    """Append-only versioned snapshot in Mongo (source of truth)."""
    db = get_db()
    existing = await db.interview_brain_snapshots.find_one(
        {
            "session_id": state.session_id,
            "state_version": state.state_version,
        }
    )
    if existing:
        if existing.get("active_question_id") == state.active_question_id:
            return "duplicate"
        return "conflict"
    document = state.model_dump(mode="python")
    document["updated_at"] = utc_now()
    try:
        await db.interview_brain_snapshots.insert_one(document)
    except DuplicateKeyError:
        existing = await db.interview_brain_snapshots.find_one(
            {
                "session_id": state.session_id,
                "state_version": state.state_version,
            }
        )
        if existing and existing.get("active_question_id") == state.active_question_id:
            return "duplicate"
        return "conflict"
    return "created"


async def latest_durable_snapshot(session_id: str) -> dict[str, Any] | None:
    docs = (
        await get_db()
        .interview_brain_snapshots.find({"session_id": session_id})
        .sort("state_version", -1)
        .to_list(length=1)
    )
    return docs[0] if docs else None


async def list_session_questions(session_id: str) -> list[dict[str, Any]]:
    return (
        await get_db()
        .interview_questions.find({"session_id": session_id})
        .sort("asked_at", 1)
        .to_list(length=1_000)
    )


async def list_session_answers(session_id: str) -> list[dict[str, Any]]:
    return (
        await get_db()
        .interview_answers.find({"session_id": session_id})
        .to_list(length=1_000)
    )


async def list_session_evidence(session_id: str) -> list[dict[str, Any]]:
    return (
        await get_db()
        .interview_evidence.find({"session_id": session_id})
        .to_list(length=2_000)
    )
