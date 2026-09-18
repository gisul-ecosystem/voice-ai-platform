"""Unit tests for Milestone 1 JD/resume extractors."""
from __future__ import annotations

import pytest

from brain.extractors import (
    extract_candidate_profile,
    extract_job_intelligence,
    normalize_document_text,
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


def test_normalize_collapses_whitespace() -> None:
    assert normalize_document_text("a \t b\n\n\nc") == "a b\n\nc"


def test_jd_extractor_separates_mandatory_and_preferred() -> None:
    result = extract_job_intelligence(SAMPLE_JD)
    assert result.role.title.lower().startswith("senior backend")
    assert result.role.target_level == "senior"
    assert any("fastapi" in item.text.lower() for item in result.responsibilities)
    assert any("python" in item.text.lower() for item in result.mandatory_requirements)
    assert any("kafka" in item.text.lower() for item in result.preferred_requirements)
    assert any(item.text.lower() == "python" for item in result.skills) or any(
        "python" in item.text.lower() for item in result.skills
    )
    assert all(item.provenance.source == "jd" for item in result.mandatory_requirements)
    assert result.approved is False
    assert result.extraction_version == "jd-extractor-v1"


def test_jd_extractor_rejects_empty() -> None:
    with pytest.raises(ValueError):
        extract_job_intelligence("   ")


def test_resume_extractor_builds_claims_with_provenance() -> None:
    profile = extract_candidate_profile(SAMPLE_RESUME)
    assert any("billing" in item.text.lower() for item in profile.professional_experience)
    assert any("inventory" in item.text.lower() for item in profile.projects)
    assert profile.claims
    assert all(claim.provenance.source == "resume" for claim in profile.claims)
    assert profile.experience_summary.professional_months >= 24
    assert profile.experience_summary.internship_months >= 6
    assert profile.confirmed is False
    assert profile.extraction_version == "resume-extractor-v1"


def test_resume_extractor_rejects_empty() -> None:
    with pytest.raises(ValueError):
        extract_candidate_profile("")
