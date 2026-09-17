"""Durable interview context, lifecycle, and turn persistence."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from db.mongo import get_db


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_indexes() -> None:
    db = get_db()
    await db.interview_contexts.create_index("expires_at", expireAfterSeconds=0)
    await db.interview_sessions.create_index(
        "retention_expires_at", expireAfterSeconds=0
    )
    await db.interview_sessions.create_index(
        [("candidate_id", 1), ("created_at", -1)]
    )
    await db.interview_sessions.create_index("correlation_id", unique=True)
    await db.interview_sessions.create_index(
        [("invitation_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={
            "invitation_id": {"$type": "string"},
            "idempotency_key": {"$type": "string"},
        },
    )
    await db.scorecard_jobs.create_index("session_id", unique=True)
    await db.interview_invitations.create_index("expires_at", expireAfterSeconds=0)
    await db.interview_turns.create_index(
        [("session_id", 1), ("turn_id", 1)], unique=True
    )
    await db.interview_turns.create_index(
        [("session_id", 1), ("sequence_number", 1)], unique=True
    )
    await db.scheduled_interviews.create_index(
        [("source_product_id", 1), ("external_interview_id", 1)],
        unique=True,
        sparse=True,
    )
    await db.scheduled_interviews.create_index("invitation_id", unique=True)
    await db.scheduled_interviews.create_index(
        [("starts_at", 1), ("status", 1)]
    )


async def create_context(
    job_description: str,
    resume_text: str,
    interview_setup: dict[str, Any] | None = None,
    *,
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
        "created_at": now,
        "expires_at": expires_at,
    }
    await get_db().interview_contexts.insert_one(document)
    return {"context_id": context_id, "expires_at": expires_at}


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


async def consume_invitation(invitation_id: str) -> bool:
    now = utc_now()
    result = await get_db().interview_invitations.update_one(
        {
            "_id": invitation_id,
            "used_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"used_at": now}},
    )
    return bool(result.modified_count)


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
    await get_db().scheduled_interviews.insert_one(document)


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
    await get_db().interview_sessions.insert_one(
        {
            "_id": session_id,
            "product_id": product_id,
            "context_id": context_id,
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
        return (
            "duplicate"
            if all(existing.get(key) == turn.get(key) for key in comparable)
            else "conflict"
        )
    await db.interview_turns.insert_one({**turn, "session_id": session_id})
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


async def enqueue_scorecard(session_id: str) -> None:
    now = utc_now()
    await get_db().scorecard_jobs.update_one(
        {"session_id": session_id},
        {
            "$setOnInsert": {
                "session_id": session_id,
                "status": "pending",
                "created_at": now,
            }
        },
        upsert=True,
    )
