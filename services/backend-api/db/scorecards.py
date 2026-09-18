"""Persist interview scorecards."""
from __future__ import annotations

from typing import Any

from pymongo.errors import DuplicateKeyError

from db.mongo import get_db
from models.brain import InterviewScorecard


async def ensure_scorecard_indexes() -> None:
    db = get_db()
    await db.interview_scorecards.create_index("session_id", unique=True)
    await db.interview_scorecards.create_index([("created_at", -1)])
    await db.interview_scorecards.create_index("definition_id")


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
