"""Immutable published interview definition storage."""
from __future__ import annotations

from typing import Any

from pymongo.errors import DuplicateKeyError

from db.mongo import get_db
from models.brain import InterviewDefinitionVersion


async def ensure_definition_indexes() -> None:
    db = get_db()
    await db.interview_definitions.create_index("definition_id", unique=True)
    await db.interview_definitions.create_index(
        [("template_id", 1), ("version", 1)], unique=True
    )
    await db.interview_definitions.create_index([("published_at", -1)])


async def save_definition(definition: InterviewDefinitionVersion) -> str:
    """Insert an immutable published definition. Returns created|duplicate."""
    db = get_db()
    document = definition.model_dump(mode="python")
    document["_id"] = definition.definition_id
    existing = await db.interview_definitions.find_one(
        {"definition_id": definition.definition_id}
    )
    if existing:
        return "duplicate"
    try:
        await db.interview_definitions.insert_one(document)
    except DuplicateKeyError:
        return "duplicate"
    return "created"


async def get_definition(definition_id: str) -> dict[str, Any] | None:
    definition_id = (definition_id or "").strip()
    if not definition_id:
        return None
    return await get_db().interview_definitions.find_one(
        {"$or": [{"_id": definition_id}, {"definition_id": definition_id}]}
    )


async def get_definition_model(
    definition_id: str,
) -> InterviewDefinitionVersion | None:
    stored = await get_definition(definition_id)
    if stored is None:
        return None
    payload = dict(stored)
    payload.pop("_id", None)
    return InterviewDefinitionVersion.model_validate(payload)


async def list_definitions(*, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent published definitions, newest first."""
    capped = max(1, min(int(limit), 100))
    cursor = get_db().interview_definitions.find({})
    docs = await cursor.sort("published_at", -1).to_list(capped)
    rows: list[dict[str, Any]] = []
    for doc in docs:
        payload = dict(doc)
        payload.pop("_id", None)
        rows.append(payload)
    return rows
