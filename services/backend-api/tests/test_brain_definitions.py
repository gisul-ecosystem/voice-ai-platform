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
async def test_create_context_stores_definition_id() -> None:
    created = await interviews.create_context(
        "Build APIs",
        "Python experience",
        _setup().model_dump(mode="python"),
        definition_id="idef_context_attach_01",
    )
    stored = await interviews.get_context(created["context_id"])
    assert stored is not None
    assert stored["definition_id"] == "idef_context_attach_01"
