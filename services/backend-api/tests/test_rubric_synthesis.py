"""Tests for the Rubric Synthesis Engine (Spec §4.3)."""
from __future__ import annotations

import pytest

from brain.rubric_synthesis import (
    compute_rubric_cache_key,
    synthesize_rubric_async,
)
from db.mongo import MemoryDatabase, set_fallback_mode


@pytest.fixture(autouse=True)
def memory_db(monkeypatch):
    set_fallback_mode(True)
    db = MemoryDatabase()
    monkeypatch.setattr("db.mongo.get_db", lambda: db)
    monkeypatch.setattr("db.brain.get_db", lambda: db)
    yield db
    set_fallback_mode(False)


@pytest.mark.asyncio
async def test_rubric_cache_key_deterministic() -> None:
    k1 = compute_rubric_cache_key(
        jd_text="Enterprise SaaS Account Executive...",
        role="Enterprise Sales Executive",
        seniority="senior",
    )
    k2 = compute_rubric_cache_key(
        jd_text="  enterprise saas account executive...  ",
        role="Enterprise Sales Executive",
        seniority="senior",
    )
    assert k1 == k2
    assert len(k1) == 64


@pytest.mark.asyncio
async def test_sales_role_synthesizes_meddic_rubric_and_anchors() -> None:
    """Enterprise sales synthesizes MEDDIC lens with weak/strong level anchors."""
    rubric = await synthesize_rubric_async(
        role="Enterprise Sales Executive",
        seniority="senior",
        job_description=(
            "Looking for an Enterprise AE to manage complex $100k+ ARR deals, "
            "navigate buying committees, and handle procurement objections."
        ),
        target_duration_minutes=45,
    )
    assert rubric["evaluation_lens"] in {"MEDDIC", "BANT"}
    comps = rubric["competencies"]
    assert len(comps) >= 2
    # Verify level anchors are concrete plain language
    first = comps[0]
    assert "level_anchors" in first
    assert "weak" in first["level_anchors"]
    assert "strong" in first["level_anchors"]
    assert len(first["level_anchors"]["weak"]) > 10
    assert len(first["level_anchors"]["strong"]) > 10
    assert len(first["required_skills"]) >= 2
    assert len(first["allowed_intents"]) >= 2


@pytest.mark.asyncio
async def test_generic_role_synthesizes_star_rubric() -> None:
    """Non-sales role synthesizes structured STAR competency framework."""
    rubric = await synthesize_rubric_async(
        role="Operations Project Manager",
        seniority="mid",
        job_description="Manage logistics workflows and cross-functional handoffs.",
        target_duration_minutes=30,
    )
    assert rubric["evaluation_lens"] == "STAR"
    assert len(rubric["competencies"]) >= 2
    for comp in rubric["competencies"]:
        assert comp["level_anchors"]["weak"]
        assert comp["level_anchors"]["strong"]
        assert len(comp["allowed_intents"]) >= 1
