"""Executable proof of the live-quality matrix: same role, two levels, thin answers, time-up."""
from __future__ import annotations

import time

import pytest

from products.interviewer.coverage import init_coverage
from products.interviewer.flow import CLOSING_MESSAGE, InterviewFlow
from products.interviewer.policy import CLOSE_INTERVIEW, PolicyState, decide_next_action
from products.interviewer.worker import (
    InterviewPlanUnavailableError,
    resolve_live_outline,
)


class FakeLlm:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict]] = []

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.messages.append(messages)
        return self.replies.pop(0)


def _published_backend_role() -> dict:
    return {
        "definition_id": "idef_live_quality_be_01",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
        },
        "non_answer_policy": {
            "clarify_after": 1,
            "rephrase_after": 2,
            "change_topic_after": 3,
        },
        "job_intelligence": {
            "role": {"title": "Backend Engineer", "target_level": "mid"},
            "raw_job_description": "Own Python services, incidents, and API reliability.",
        },
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
        ],
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "definition": "Identifies and resolves backend problems",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": [
                    "context of the work",
                    "personal contribution",
                    "approach or method",
                ],
            }
        ],
        "question_ladders": [
            {
                "competency_id": "problem_solving",
                "levels": [
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "objective": "Clarify personal contribution",
                        "example_question": "What part of that did you personally handle?",
                    }
                ],
            }
        ],
    }


def _flow_for_profile(profile_type: str, job_target_level: str, llm: FakeLlm) -> InterviewFlow:
    return InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_published_backend_role(),
        job_description="Own Python services, incidents, and API reliability.",
        resume_text="Python backend work.",
        candidate_profile={
            "job_target_level": job_target_level,
            "experience_summary": {"profile_type": profile_type},
            "claims": [
                {
                    "claim_id": "claim_project_1",
                    "type": "project",
                    "value": "Billing retries service",
                }
            ],
        },
    )


def test_same_role_same_required_intents_across_experience_levels() -> None:
    definition = _published_backend_role()
    junior = init_coverage(definition)
    senior = init_coverage(definition)
    assert junior["problem_solving"]["required_intents"] == senior["problem_solving"]["required_intents"]
    assert "establish_ownership" in junior["problem_solving"]["required_intents"]
    assert "applied_understanding" in junior["problem_solving"]["required_intents"]


@pytest.mark.asyncio
async def test_junior_profile_does_not_drop_the_published_bar() -> None:
    llm = FakeLlm(
        '{"question": "What part of the billing retries did you personally handle?",'
        ' "competency_id": "problem_solving", "intent": "establish_ownership",'
        ' "depth": 2, "source_claim_ids": ["claim_project_1"]}'
    )
    flow = _flow_for_profile("final_year_student", "junior", llm)
    flow.interviewer_turns = ["Thanks for joining. Please introduce yourself."]
    flow.candidate_turns = ["I am a student who interned on a billing service."]
    await flow.generate_next_question("We used Python and it mostly worked.")
    prompt = llm.messages[0][0]["content"]
    assert "never drop required intents" in prompt.lower()
    required = flow.coverage["problem_solving"]["required_intents"]
    assert "establish_ownership" in required
    assert "applied_understanding" in required


@pytest.mark.asyncio
async def test_job_true_opening_names_the_published_role_when_llm_fails() -> None:
    class FailingLlm:
        async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
            raise RuntimeError("provider unavailable")

    flow = InterviewFlow(
        {"phases": []},
        FailingLlm(),
        interview_definition=_published_backend_role(),
        job_description="Own Python services.",
    )
    question = await flow.generate_next_question(None)
    assert "Backend Engineer" in question
    assert "introduce yourself" in question.lower()


def test_thin_answers_do_not_cover_required_intents() -> None:
    definition = _published_backend_role()
    coverage = init_coverage(definition)
    assert coverage["problem_solving"]["covered_intents"] == []
    assert coverage["problem_solving"]["missing_intents"]
    from products.interviewer.coverage import classify_live_answer

    usability, quality, covered = classify_live_answer(
        "I don't know.",
        required_intents=coverage["problem_solving"]["required_intents"],
        evidence_expected=["context of the work"],
    )
    assert usability in {"explicit_unknown", "too_short", "needs_clarification"}
    assert covered == []


def test_time_up_closes_the_same_role_cleanly() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=12,
            candidate_turn_count=12,
            phase_name="Problem solving",
            competency_id="problem_solving",
            elapsed_seconds=35 * 60,
            hard_end_seconds=35 * 60,
        )
    )
    assert decision.action == CLOSE_INTERVIEW
    assert decision.forced_flow_decision == "close"


@pytest.mark.asyncio
async def test_flow_closes_with_closing_message_when_hard_end_elapsed() -> None:
    llm = FakeLlm("should not run")
    flow = _flow_for_profile("junior", "mid", llm)
    flow.started_at = time.monotonic() - (35 * 60) - 1
    question = await flow.generate_next_question("I owned the retries and reduced timeout errors.")
    assert question == CLOSING_MESSAGE
    assert flow.completed is True
    assert llm.messages == []


def test_published_definition_never_falls_back_to_generic_outline() -> None:
    outline, source = resolve_live_outline(
        interview_definition=_published_backend_role(),
        definition_id="idef_live_quality_be_01",
        app_env="production",
    )
    assert source == "published_definition"
    assert outline is not None
    names = [phase["name"] for phase in outline["phases"]]
    assert "Problem solving" in names
    assert names[0] == "opening"


def test_bound_definition_failure_does_not_become_generic() -> None:
    with pytest.raises(InterviewPlanUnavailableError, match="published_definition_required"):
        resolve_live_outline(
            interview_definition=None,
            definition_id="idef_missing",
            app_env="development",
        )
    with pytest.raises(InterviewPlanUnavailableError, match="published_definition_required"):
        resolve_live_outline(
            interview_definition=None,
            definition_id=None,
            app_env="staging",
        )
