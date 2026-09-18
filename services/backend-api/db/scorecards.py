"""Persist interview scorecards."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from db.mongo import get_db
from models.brain import InterviewScorecard, ScorecardReviewEvent


async def ensure_scorecard_indexes() -> None:
    db = get_db()
    await db.interview_scorecards.create_index("session_id", unique=True)
    await db.interview_scorecards.create_index([("created_at", -1)])
    await db.interview_scorecards.create_index("definition_id")
    await db.interview_review_events.create_index(
        [("session_id", 1), ("created_at", -1)]
    )
    await db.interview_review_events.create_index("review_id", unique=True)


async def save_scorecard(scorecard: InterviewScorecard) -> str:
    db = get_db()
    document = scorecard.model_dump(mode="python")
    document["_id"] = scorecard.session_id
    existing = await db.interview_scorecards.find_one({"session_id": scorecard.session_id})
    if existing:
        # Immutable AI scorecard; human overrides go to review events later.
        return "duplicate"
    try:
        await db.interview_scorecards.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def get_scorecard(session_id: str) -> dict[str, Any] | None:
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    return await get_db().interview_scorecards.find_one(
        {"$or": [{"_id": session_id}, {"session_id": session_id}]}
    )


async def save_review_event(event: ScorecardReviewEvent) -> str:
    db = get_db()
    document = event.model_dump(mode="python")
    document["_id"] = event.review_id
    try:
        await db.interview_review_events.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def latest_review(session_id: str) -> dict[str, Any] | None:
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    cursor = get_db().interview_review_events.find({"session_id": session_id})
    rows = await cursor.sort("created_at", -1).to_list(1)
    return rows[0] if rows else None


async def apply_review_stamp(
    session_id: str,
    *,
    status: str,
    reviewer_id: str,
    override_reason: str | None,
    reviewed_at: datetime,
) -> None:
    await get_db().interview_scorecards.update_one(
        {"session_id": session_id},
        {
            "$set": {
                "human_review_status": status,
                "reviewer_id": reviewer_id,
                "override_reason": override_reason,
                "reviewed_at": reviewed_at,
            }
        },
    )


async def get_scorecard_with_review(session_id: str) -> dict[str, Any] | None:
    stored = await get_scorecard(session_id)
    if stored is None:
        return None
    payload = dict(stored)
    payload.pop("_id", None)
    review = await latest_review(session_id)
    if review:
        overlay = dict(review)
        overlay.pop("_id", None)
        payload["latest_review"] = overlay
        payload["human_review_status"] = overlay.get(
            "status", payload.get("human_review_status")
        )
        payload["reviewer_id"] = overlay.get("reviewer_id")
        payload["override_reason"] = overlay.get("override_reason")
        payload["reviewed_at"] = overlay.get("created_at")
    return payload
