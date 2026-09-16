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
    await db.interview_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.interview_sessions.create_index(
        [("candidate_id", 1), ("created_at", -1)]
    )
    await db.interview_sessions.create_index("correlation_id", unique=True)
    await db.scorecard_jobs.create_index("session_id", unique=True)
    await db.interview_invitations.create_index("expires_at", expireAfterSeconds=0)


async def create_context(job_description: str, resume_text: str) -> dict[str, Any]:
    now = utc_now()
    expires_at = now + timedelta(
        hours=max(1, int(os.getenv("INTERVIEW_CONTEXT_TTL_HOURS", "24")))
    )
    context_id = f"ctx_{uuid.uuid4().hex}"
    document = {
        "_id": context_id,
        "job_description": job_description,
        "resume_text": resume_text,
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


async def create_live_session(
    *,
    product_id: str,
    context_id: str | None,
    candidate_id: str,
    room: str,
    correlation_id: str,
    expires_at: datetime,
) -> str:
    session_id = f"ses_{uuid.uuid4().hex}"
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
            "expires_at": expires_at,
            "turns": [],
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


async def append_turn(session_id: str, turn: dict[str, Any]) -> None:
    await get_db().interview_sessions.update_one(
        {"_id": session_id},
        {
            "$push": {"turns": turn},
            "$set": {"updated_at": utc_now()},
        },
    )


async def get_session(session_id: str) -> dict[str, Any] | None:
    return await get_db().interview_sessions.find_one({"_id": session_id})


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
