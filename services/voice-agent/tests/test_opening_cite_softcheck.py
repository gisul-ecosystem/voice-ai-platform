"""Soft-check: LLM opening without claim cite is replaced."""
from __future__ import annotations

import pytest

from products.interviewer.flow import InterviewFlow


@pytest.mark.asyncio
async def test_opening_without_claim_cite_is_replaced() -> None:
    class GenericLlm:
        async def generate_reply(self, messages, **_kwargs):
            return (
                '{"question": "Thanks for joining. Please introduce yourself.",'
                ' "competency_id": "", "intent": "opening", "depth": 1,'
                ' "source_claim_ids": []}'
            )

    flow = InterviewFlow(
        {"phases": [{"name": "opening", "topics": [], "duration_minutes": 2}]},
        GenericLlm(),
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
                            "example_question": "Tell me about a recent problem.",
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
    assert "FastAPI billing retries" in question
    # Soft-weave keeps the model's greeting and cites the claim; it does not
    # hard-replace with the role+claim template.
    assert "introduce yourself" in question.lower()
    assert question != "Thanks for joining. Please introduce yourself."
