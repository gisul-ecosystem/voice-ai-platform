"""LLM extract falls back to heuristic extractors when the model is unavailable."""
from __future__ import annotations

import pytest

from brain.extractors import extract_job_intelligence
from brain.llm_extract import (
    extract_candidate_profile_async,
    extract_job_intelligence_async,
)

SAMPLE_JD = """
Senior Backend Engineer

Responsibilities
- Design and operate FastAPI services
- Own on-call for billing APIs

Requirements
- 4+ years Python experience
- Strong MongoDB skills

Preferred
- Kafka experience

Skills
- Python, FastAPI, Redis

Tools
- Docker
- Kubernetes
"""

SAMPLE_RESUME = """
Alex Candidate

Experience
- Backend Engineer at Acme, 2021-2024
- Built billing APIs in Python

Internships
- Software Intern at Beta, 2020-2021

Projects
- Inventory Manager: stock tracking on AWS
- Payments Gateway checkout service

Skills
Python, FastAPI, MongoDB, Redis

Education
- B.S. Computer Science, 2020
"""


@pytest.mark.asyncio
async def test_async_extract_falls_back_to_heuristic(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_LLM_EXTRACT", "0")
    job = await extract_job_intelligence_async(SAMPLE_JD)
    heuristic = extract_job_intelligence(SAMPLE_JD)
    assert job.approved is False
    assert job.extraction_version == "jd-extractor-v1"
    assert [item.text for item in job.skills] == [item.text for item in heuristic.skills]


@pytest.mark.asyncio
async def test_async_extract_uses_heuristic_when_llm_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_LLM_EXTRACT", "1")

    async def fake_complete(**_kwargs):
        return None

    monkeypatch.setattr(
        "brain.llm_extract.complete_structured_json",
        fake_complete,
    )
    job = await extract_job_intelligence_async(SAMPLE_JD)
    assert job.approved is False
    assert any("python" in item.text.lower() for item in job.mandatory_requirements)


@pytest.mark.asyncio
async def test_llm_items_must_be_grounded_in_the_document(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_LLM_EXTRACT", "1")

    async def fake_complete(**_kwargs):
        return {
            "title": "Senior Backend Engineer",
            "target_level": "senior",
            "domain": "",
            "responsibilities": ["Invent a secret quantum compiler"],
            "mandatory_requirements": ["4+ years Python experience"],
            "preferred_requirements": [],
            "knowledge": [],
            "skills": ["Python"],
            "tools": [],
            "work_scenarios": [],
            "expected_outcomes": [],
        }

    monkeypatch.setattr(
        "brain.llm_extract.complete_structured_json",
        fake_complete,
    )
    job = await extract_job_intelligence_async(SAMPLE_JD)
    assert job.extraction_version == "jd-extractor-v2"
    assert all("quantum" not in item.text.lower() for item in job.responsibilities)
    assert any("python" in item.text.lower() for item in job.mandatory_requirements)


@pytest.mark.asyncio
async def test_resume_extract_async_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_LLM_EXTRACT", "1")

    async def fake_complete(**_kwargs):
        return None

    monkeypatch.setattr(
        "brain.llm_extract.complete_structured_json",
        fake_complete,
    )
    profile = await extract_candidate_profile_async(SAMPLE_RESUME)
    assert profile.confirmed is False
    assert profile.extraction_version == "resume-extractor-v1"
    assert profile.claims
