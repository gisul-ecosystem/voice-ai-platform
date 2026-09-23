"""PBI-B1/B2: claim-aware opening and project ranking."""
from __future__ import annotations

import pytest

from products.interviewer.flow import (
    InterviewFlow,
    build_candidate_profile,
    rank_projects_by_competency_gap,
)


def test_rank_projects_prefers_jd_overlap_over_unrelated() -> None:
    claims = [
        {"claim_id": "c1", "type": "project", "value": "Built a React dashboard"},
        {"claim_id": "c2", "type": "project", "value": "Owned FastAPI billing retries in Python"},
        {"claim_id": "c3", "type": "skill", "value": "Cooking"},
    ]
    ranked = rank_projects_by_competency_gap(
        claims,
        competencies=["Problem solving", "Python", "FastAPI"],
        job_description="Backend engineer with Python and FastAPI ownership.",
    )
    assert ranked[0]["claim_id"] == "c2"
    assert [item["claim_id"] for item in ranked][:2] == ["c2", "c1"]


def test_build_candidate_profile_ranks_existing_claims() -> None:
    profile = build_candidate_profile(
        resume_text="",
        interview_setup={"competencies": ["Python", "FastAPI"], "seniority": "mid"},
        existing={
            "experience_summary": {"profile_type": "junior"},
            "claims": [
                {"claim_id": "a", "type": "project", "value": "Marketing blog"},
                {"claim_id": "b", "type": "project", "value": "Python FastAPI payments API"},
            ],
        },
    )
    assert profile["claims"][0]["claim_id"] == "b"
    assert profile["job_target_level"] == "mid"


@pytest.mark.asyncio
async def test_fallback_opening_cites_one_resume_claim() -> None:
    class Boom:
        async def generate_reply(self, messages, **_kwargs):
            raise RuntimeError("down")

    flow = InterviewFlow(
        {"phases": [{"name": "opening", "topics": [], "duration_minutes": 2}]},
        Boom(),
        interview_definition={
            "competencies": [
                {
                    "id": "problem_solving",
                    "name": "Problem solving",
                    "importance": "high",
                    "max_depth": 3,
                    "required_intents": ["establish_context"],
                    "evidence_expected": ["context"],
                }
            ],
            "question_ladders": [
                {
                    "competency_id": "problem_solving",
                    "steps": [
                        {
                            "intent": "establish_context",
                            "objective": "context",
                            "example_question": "Tell me about a recent problem you solved.",
                        }
                    ],
                }
            ],
            "job_intelligence": {
                "role": {"title": "Backend Engineer", "target_level": "mid", "domain": "software"}
            },
            "time_policy": {
                "duration_minutes": 30,
                "soft_end_minutes": 27,
                "target_end_minutes": 30,
                "hard_end_minutes": 35,
                "allow_final_addition": True,
            },
            "non_answer_policy": {
                "clarify_after": 1,
                "rephrase_after": 2,
                "change_topic_after": 3,
                "confirm_continue_after": 4,
            },
        },
        job_description="Own Python FastAPI services.",
        candidate_profile={
            "experience_summary": {"profile_type": "junior"},
            "claims": [
                {
                    "claim_id": "claim_1",
                    "type": "project",
                    "value": "Owned FastAPI billing retries",
                }
            ],
        },
    )
    question = await flow.generate_next_question(None)
    assert "Backend Engineer" in question
    assert "introduce yourself" in question.lower()
    assert "Aaptor" in question
    assert "FastAPI billing retries" not in question


def test_same_jd_different_experience_keeps_job_bar() -> None:
    definition = {
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "importance": "high",
                "max_depth": 3,
                "required_intents": ["establish_context", "establish_ownership"],
                "evidence_expected": ["context"],
            }
        ],
        "job_intelligence": {"role": {"title": "Backend Engineer", "target_level": "mid"}},
    }
    student = build_candidate_profile(
        definition=definition,
        interview_setup={"seniority": "mid"},
        existing={
            "experience_summary": {"profile_type": "final_year_student"},
            "claims": [{"claim_id": "c1", "type": "project", "value": "College library app"}],
        },
    )
    senior = build_candidate_profile(
        definition=definition,
        interview_setup={"seniority": "mid"},
        existing={
            "experience_summary": {"profile_type": "senior"},
            "claims": [{"claim_id": "c2", "type": "project", "value": "Payments platform"}],
        },
    )
    assert student["job_target_level"] == "mid"
    assert senior["job_target_level"] == "mid"
    assert student["experience_summary"]["profile_type"] == "final_year_student"
    assert senior["experience_summary"]["profile_type"] == "senior"
