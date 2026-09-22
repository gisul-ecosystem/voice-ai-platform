"""Durable interview context, lifecycle, and turn persistence."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError, OperationFailure

from db.mongo import get_db

SCHEDULE_EXTERNAL_INDEX = "uniq_scheduled_source_external_v2"
LEGACY_SCHEDULE_EXTERNAL_INDEX = "source_product_id_1_external_interview_id_1"
SCHEDULE_EXTERNAL_KEYS = [
    ("source_product_id", 1),
    ("external_interview_id", 1),
]
SCHEDULE_EXTERNAL_FILTER = {"external_interview_id": {"$type": "string"}}
SESSION_CORRELATION_INDEX = "correlation_id_1"


class ExternalInterviewConflictError(Exception):
    """A product reused an external interview identifier."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _scheduled_external_index_matches(index: dict[str, Any]) -> bool:
    key = index.get("key") or {}
    return (
        list(key.items()) == SCHEDULE_EXTERNAL_KEYS
        and index.get("unique") is True
        and index.get("partialFilterExpression") == SCHEDULE_EXTERNAL_FILTER
    )


async def _drop_index_if_present(collection: Any, name: str) -> None:
    try:
        await collection.drop_index(name)
    except OperationFailure as exc:
        if exc.code not in {26, 27}:  # NamespaceNotFound, IndexNotFound
            raise


async def ensure_scheduled_external_index(collection: Any) -> None:
    try:
        indexes = {item["name"]: item async for item in collection.list_indexes()}
    except OperationFailure as exc:
        # MongoDB reports NamespaceNotFound before a collection's first index.
        if exc.code != 26:
            raise
        indexes = {}

    if LEGACY_SCHEDULE_EXTERNAL_INDEX in indexes:
        await _drop_index_if_present(collection, LEGACY_SCHEDULE_EXTERNAL_INDEX)

    current = indexes.get(SCHEDULE_EXTERNAL_INDEX)
    if current is not None and not _scheduled_external_index_matches(current):
        await _drop_index_if_present(collection, SCHEDULE_EXTERNAL_INDEX)
        current = None

    if current is None:
        await collection.create_index(
            SCHEDULE_EXTERNAL_KEYS,
            name=SCHEDULE_EXTERNAL_INDEX,
            unique=True,
            partialFilterExpression=SCHEDULE_EXTERNAL_FILTER,
        )


async def ensure_session_correlation_index(collection: Any) -> None:
    try:
        indexes = {item["name"]: item async for item in collection.list_indexes()}
    except OperationFailure as exc:
        if exc.code != 26:
            raise
        indexes = {}

    current = indexes.get(SESSION_CORRELATION_INDEX)
    if current is not None and current.get("unique") is True:
        await _drop_index_if_present(collection, SESSION_CORRELATION_INDEX)
        current = None
    if current is None:
        await collection.create_index(
            "correlation_id",
            name=SESSION_CORRELATION_INDEX,
        )


async def ensure_indexes() -> None:
    db = get_db()
    await db.interview_contexts.create_index("expires_at", expireAfterSeconds=0)
    from db.candidates import ensure_candidate_indexes
    await ensure_candidate_indexes()
    await db.interview_sessions.create_index(
        "retention_expires_at", expireAfterSeconds=0
    )
    await db.interview_sessions.create_index(
        [("candidate_id", 1), ("created_at", -1)]
    )
    await ensure_session_correlation_index(db.interview_sessions)
    await db.interview_sessions.create_index(
        [("invitation_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={
            "invitation_id": {"$type": "string"},
            "idempotency_key": {"$type": "string"},
        },
    )
    await db.interview_invitations.create_index("expires_at", expireAfterSeconds=0)
    await db.interview_turns.create_index(
        [("session_id", 1), ("turn_id", 1)], unique=True
    )
    await db.interview_turns.create_index(
        [("session_id", 1), ("sequence_number", 1)], unique=True
    )
    await ensure_scheduled_external_index(db.scheduled_interviews)
    await db.scheduled_interviews.create_index("invitation_id", unique=True)
    await db.scheduled_interviews.create_index(
        [("starts_at", 1), ("status", 1)]
    )
    from db.brain import ensure_brain_indexes
    from db.definitions import ensure_definition_indexes
    from db.scorecards import ensure_scorecard_indexes

    await ensure_brain_indexes()
    await ensure_definition_indexes()
    await ensure_scorecard_indexes()


async def create_context(
    job_description: str,
    resume_text: str,
    interview_setup: dict[str, Any] | None = None,
    *,
    definition_id: str | None = None,
    candidate_profile: dict[str, Any] | None = None,
    expires_at_override: datetime | None = None,
) -> dict[str, Any]:
    now = utc_now()
    expires_at = expires_at_override or (
        now
        + timedelta(
            hours=max(1, int(os.getenv("INTERVIEW_CONTEXT_TTL_HOURS", "24")))
        )
    )
    context_id = f"ctx_{uuid.uuid4().hex}"
    document = {
        "_id": context_id,
        "job_description": job_description,
        "resume_text": resume_text,
        "interview_setup": interview_setup,
        "definition_id": (definition_id or "").strip() or None,
        "candidate_profile": candidate_profile,
        "created_at": now,
        "expires_at": expires_at,
    }
    await get_db().interview_contexts.insert_one(document)
    return {
        "context_id": context_id,
        "expires_at": expires_at,
        "definition_id": document["definition_id"],
    }


async def attach_definition_to_context(
    context_id: str, definition_id: str
) -> bool:
    result = await get_db().interview_contexts.update_one(
        {"_id": context_id},
        {"$set": {"definition_id": definition_id.strip()}},
    )
    return result.modified_count > 0 or result.matched_count > 0


async def get_context(context_id: str) -> dict[str, Any] | None:
    return await get_db().interview_contexts.find_one(
        {"_id": context_id, "expires_at": {"$gt": utc_now()}}
    )


async def store_invitation(
    *,
    invitation_id: str,
    context_id: str,
    candidate_id: str,
    expires_at: datetime,
) -> None:
    await get_db().interview_invitations.insert_one(
        {
            "_id": invitation_id,
            "context_id": context_id,
            "candidate_id": candidate_id,
            "expires_at": expires_at,
            "used_at": None,
        }
    )


async def reserve_invitation(invitation_id: str, reservation_id: str) -> bool:
    now = utc_now()
    result = await get_db().interview_invitations.update_one(
        {
            "_id": invitation_id,
            "used_at": None,
            "expires_at": {"$gt": now},
            "$or": [
                {"reservation_id": None},
                {"reservation_id": {"$exists": False}},
                {"reservation_id": reservation_id},
                {"reservation_expires_at": {"$lte": now}},
            ],
        },
        {
            "$set": {
                "reservation_id": reservation_id,
                "reservation_expires_at": now + timedelta(minutes=2),
            }
        },
    )
    return bool(result.modified_count or result.matched_count)


async def commit_invitation(invitation_id: str, reservation_id: str) -> bool:
    result = await get_db().interview_invitations.update_one(
        {
            "_id": invitation_id,
            "reservation_id": reservation_id,
            "used_at": None,
        },
        {
            "$set": {"used_at": utc_now()},
            "$unset": {"reservation_id": "", "reservation_expires_at": ""},
        },
    )
    return bool(result.modified_count)


async def release_invitation(invitation_id: str, reservation_id: str) -> None:
    await get_db().interview_invitations.update_one(
        {
            "_id": invitation_id,
            "reservation_id": reservation_id,
            "used_at": None,
        },
        {"$unset": {"reservation_id": "", "reservation_expires_at": ""}},
    )


async def create_scheduled_interview(document: dict[str, Any]) -> None:
    try:
        await get_db().scheduled_interviews.insert_one(document)
    except DuplicateKeyError as exc:
        key_pattern = (exc.details or {}).get("keyPattern") or {}
        if set(key_pattern) == {"source_product_id", "external_interview_id"}:
            raise ExternalInterviewConflictError from exc
        raise


async def rollback_schedule_artifacts(
    *, context_id: str, invitation_id: str
) -> None:
    db = get_db()
    await db.interview_contexts.delete_one({"_id": context_id})
    await db.interview_invitations.delete_one({"_id": invitation_id})


async def get_scheduled_interview_by_invitation(
    invitation_id: str,
) -> dict[str, Any] | None:
    return await get_db().scheduled_interviews.find_one(
        {"invitation_id": invitation_id}
    )


async def record_candidate_consent(
    invitation_id: str,
    consent: dict[str, Any],
) -> bool:
    result = await get_db().scheduled_interviews.update_one(
        {
            "invitation_id": invitation_id,
            "status": "scheduled",
        },
        {
            "$set": {
                "consent": consent,
                "updated_at": utc_now(),
            }
        },
    )
    return bool(result.modified_count)


async def validate_join_window(invitation_id: str) -> dict[str, Any] | None:
    now = utc_now()
    return await get_db().scheduled_interviews.find_one(
        {
            "invitation_id": invitation_id,
            "status": "scheduled",
            "join_not_before": {"$lte": now},
            "join_closes_at": {"$gte": now},
            "consent.ai_interview": True,
            "consent.transcription": True,
        }
    )


async def create_live_session(
    *,
    product_id: str,
    context_id: str | None,
    candidate_id: str,
    room: str,
    correlation_id: str,
    expires_at: datetime,
    session_id: str | None = None,
    invitation_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    session_id = session_id or f"ses_{uuid.uuid4().hex}"
    now = utc_now()
    definition_id = None
    if context_id:
        context = await get_context(context_id)
        if context:
            definition_id = context.get("definition_id")
    await get_db().interview_sessions.insert_one(
        {
            "_id": session_id,
            "product_id": product_id,
            "context_id": context_id,
            "definition_id": definition_id,
            "candidate_id": candidate_id,
            "room": room,
            "correlation_id": correlation_id,
            "status": "joining",
            "created_at": now,
            "updated_at": now,
            "room_token_expires_at": expires_at,
            "retention_expires_at": now + timedelta(
                days=max(1, int(os.getenv("INTERVIEW_RETENTION_DAYS", "365")))
            ),
            "invitation_id": invitation_id,
            "idempotency_key": idempotency_key,
            "events": [
                {"type": "session_created", "at": now, "status": "joining"}
            ],
        }
    )
    return session_id


async def transition_session(
    session_id: str,
    *,
    expected: tuple[str, ...],
    status: str,
    reason: str | None = None,
) -> bool:
    now = utc_now()
    event = {"type": "status_changed", "at": now, "status": status}
    if reason:
        event["reason"] = reason
    result = await get_db().interview_sessions.update_one(
        {"_id": session_id, "status": {"$in": list(expected)}},
        {
            "$set": {"status": status, "updated_at": now},
            "$push": {"events": event},
        },
    )
    return bool(result.modified_count)


async def append_turn(session_id: str, turn: dict[str, Any]) -> str:
    db = get_db()
    if await db.interview_sessions.find_one({"_id": session_id}, {"_id": 1}) is None:
        return "missing"
    existing = await db.interview_turns.find_one(
        {"session_id": session_id, "turn_id": turn["turn_id"]}
    )
    comparable = ("speaker", "text", "phase_index", "sequence_number", "is_final")
    if existing:
        if not all(existing.get(key) == turn.get(key) for key in comparable):
            return "conflict"
        # Same turn re-posted to attach the LLM verdict that was not yet known
        # on the first write.
        evaluation = turn.get("answer_evaluation")
        if evaluation and not existing.get("answer_evaluation"):
            await db.interview_turns.update_one(
                {"session_id": session_id, "turn_id": turn["turn_id"]},
                {"$set": {"answer_evaluation": evaluation}},
            )
        return "duplicate"
    try:
        await db.interview_turns.insert_one({**turn, "session_id": session_id})
    except DuplicateKeyError:
        existing = await db.interview_turns.find_one(
            {"session_id": session_id, "turn_id": turn["turn_id"]}
        )
        if existing and all(
            existing.get(key) == turn.get(key) for key in comparable
        ):
            return "duplicate"
        return "conflict"
    await db.interview_sessions.update_one(
        {"_id": session_id}, {"$set": {"updated_at": utc_now()}}
    )
    return "created"


async def get_session(session_id: str) -> dict[str, Any] | None:
    db = get_db()
    session = await db.interview_sessions.find_one({"_id": session_id})
    if session is not None:
        session["turns"] = await db.interview_turns.find(
            {"session_id": session_id}
        ).sort("sequence_number", 1).to_list(length=10_000)
    return session


async def get_session_for_join(
    invitation_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    return await get_db().interview_sessions.find_one(
        {
            "invitation_id": invitation_id,
            "idempotency_key": idempotency_key,
            "status": {"$in": ["joining", "live"]},
        }
    )
