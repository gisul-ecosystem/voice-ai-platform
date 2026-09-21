"""Candidate records and resume persistence for admin-managed interviews."""
from __future__ import annotations

from typing import Any

from db.mongo import get_db


async def ensure_candidate_indexes() -> None:
    collection = get_db().candidates
    await collection.create_index("email")
    await collection.create_index([("created_at", -1)])


async def create_candidate(
    *, candidate_id: str, name: str, email: str, created_by: str
) -> dict[str, Any]:
    from db.interviews import utc_now

    document = {
        "_id": candidate_id,
        "candidate_id": candidate_id,
        "name": name.strip(),
        "email": email.strip().lower(),
        "resume_text": None,
        "candidate_profile": None,
        "resume_filename": None,
        "resume_content_type": None,
        "created_by": created_by.strip(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await get_db().candidates.insert_one(document)
    return document


async def get_candidate(candidate_id: str) -> dict[str, Any] | None:
    return await get_db().candidates.find_one(
        {"$or": [{"_id": candidate_id}, {"candidate_id": candidate_id}]}
    )


async def attach_resume(
    candidate_id: str,
    *,
    resume_text: str,
    candidate_profile: dict[str, Any],
    filename: str,
    content_type: str,
) -> bool:
    from db.interviews import utc_now

    result = await get_db().candidates.update_one(
        {"candidate_id": candidate_id},
        {
            "$set": {
                "resume_text": resume_text,
                "candidate_profile": candidate_profile,
                "resume_filename": filename,
                "resume_content_type": content_type,
                "updated_at": utc_now(),
            }
        },
    )
    return bool(result.matched_count)
