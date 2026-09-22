from __future__ import annotations

from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from db import interviews


class FakeCollection:
    def __init__(self, indexes: list[dict[str, Any]]) -> None:
        self.indexes = indexes
        self.dropped: list[str] = []
        self.created: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []

    def list_indexes(self):
        async def iterate():
            for index in self.indexes:
                yield index

        return iterate()

    async def drop_index(self, name: str) -> None:
        self.dropped.append(name)

    async def create_index(self, keys, **options) -> str:
        self.created.append((keys, options))
        return options["name"]


@pytest.mark.asyncio
async def test_legacy_sparse_external_id_index_is_migrated() -> None:
    collection = FakeCollection(
        [
            {
                "name": interviews.LEGACY_SCHEDULE_EXTERNAL_INDEX,
                "key": {
                    "source_product_id": 1,
                    "external_interview_id": 1,
                },
                "unique": True,
                "sparse": True,
            }
        ]
    )

    await interviews.ensure_scheduled_external_index(collection)

    assert collection.dropped == [interviews.LEGACY_SCHEDULE_EXTERNAL_INDEX]
    assert collection.created == [
        (
            interviews.SCHEDULE_EXTERNAL_KEYS,
            {
                "name": interviews.SCHEDULE_EXTERNAL_INDEX,
                "unique": True,
                "partialFilterExpression": interviews.SCHEDULE_EXTERNAL_FILTER,
            },
        )
    ]


@pytest.mark.asyncio
async def test_correct_external_id_index_is_left_unchanged() -> None:
    collection = FakeCollection(
        [
            {
                "name": interviews.SCHEDULE_EXTERNAL_INDEX,
                "key": dict(interviews.SCHEDULE_EXTERNAL_KEYS),
                "unique": True,
                "partialFilterExpression": interviews.SCHEDULE_EXTERNAL_FILTER,
            }
        ]
    )

    await interviews.ensure_scheduled_external_index(collection)

    assert collection.dropped == []
    assert collection.created == []


@pytest.mark.asyncio
async def test_correlation_index_is_migrated_from_unique_to_non_unique() -> None:
    collection = FakeCollection(
        [
            {
                "name": interviews.SESSION_CORRELATION_INDEX,
                "key": {"correlation_id": 1},
                "unique": True,
            }
        ]
    )

    await interviews.ensure_session_correlation_index(collection)

    assert collection.dropped == [interviews.SESSION_CORRELATION_INDEX]
    assert collection.created == [
        (
            "correlation_id",
            {"name": interviews.SESSION_CORRELATION_INDEX},
        )
    ]


@pytest.mark.asyncio
async def test_external_id_duplicate_is_translated(monkeypatch) -> None:
    class ScheduledInterviews:
        async def insert_one(self, _document):
            raise DuplicateKeyError(
                "duplicate",
                11000,
                {
                    "keyPattern": {
                        "source_product_id": 1,
                        "external_interview_id": 1,
                    }
                },
            )

    class Database:
        scheduled_interviews = ScheduledInterviews()

    monkeypatch.setattr(interviews, "get_db", lambda: Database())

    with pytest.raises(interviews.ExternalInterviewConflictError):
        await interviews.create_scheduled_interview(
            {
                "source_product_id": "aaptor",
                "external_interview_id": "interview-123",
            }
        )
