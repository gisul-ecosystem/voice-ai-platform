"""Tests for immutable interview definition persistence."""
from __future__ import annotations

import pytest

from brain.definition_service import publish_and_store
from db import definitions, interviews, mongo
from models.schemas import InterviewSetupConfig


@pytest.fixture(autouse=True)
def _memory_mongo(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "")
    mongo.set_fallback_mode(True)
    yield
    mongo.set_fallback_mode(False)


def _setup() -> InterviewSetupConfig:
    return InterviewSetupConfig(
        title="Backend interview",
        role="Backend Engineer",
        seniority="mid",
        difficulty="applied",
        durationMinutes=30,
        language="English",
        competencies=["Problem solving", "Python"],
        maxProbesPerPhase=2,
        monitoringEnabled=True,
        recordingEnabled=False,
    )


@pytest.mark.asyncio
async def test_publish_and_store_persists_immutable_definition() -> None:
    published = await publish_and_store(
        job_description="Build APIs with Python and own production incidents.",
        interview_setup=_setup(),
        timezone="Asia/Kolkata",
        published_by="test@example.com",
    )
    assert published.definition_id.startswith("idef_")
    stored = await definitions.get_definition_model(published.definition_id)
    assert stored is not None
    assert stored.version == 1
    assert stored.status == "published"
    assert stored.competencies


@pytest.mark.asyncio
async def test_publish_and_store_blocks_incomplete_setup() -> None:
    with pytest.raises(ValueError, match="job description is incomplete"):
        await publish_and_store(
            job_description="too short",
            interview_setup=_setup(),
            timezone="Asia/Kolkata",
            published_by="test@example.com",
        )
    with pytest.raises(ValueError, match="creator competencies are required"):
        await publish_and_store(
            job_description="Build APIs with Python and own production incidents.",
            interview_setup=_setup().model_copy(update={"competencies": ["  ", ""]}),
            timezone="Asia/Kolkata",
            published_by="test@example.com",
        )


@pytest.mark.asyncio
async def test_list_definitions_returns_newest_first() -> None:
    first = await publish_and_store(
        job_description="Build APIs with Python and own production incidents.",
        interview_setup=_setup(),
        timezone="Asia/Kolkata",
        published_by="test@example.com",
    )
    second_setup = _setup().model_copy(update={"title": "Second interview"})
    second = await publish_and_store(
        job_description="Ship reliable backend services with strong ownership.",
        interview_setup=second_setup,
        timezone="Asia/Kolkata",
        published_by="test@example.com",
    )
    listed = await definitions.list_definitions(limit=10)
    ids = [row["definition_id"] for row in listed]
    assert second.definition_id in ids
    assert first.definition_id in ids
    assert ids.index(second.definition_id) < ids.index(first.definition_id)

    created = await interviews.create_context(
        "Build APIs",
        "Python experience",
        _setup().model_dump(mode="python"),
        definition_id="idef_context_attach_01",
    )
    stored = await interviews.get_context(created["context_id"])
    assert stored is not None
    assert stored["definition_id"] == "idef_context_attach_01"
