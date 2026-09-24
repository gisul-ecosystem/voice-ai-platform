"""PBI-B3: non-answer ladder, time grace, closing, anti-trivia."""
from __future__ import annotations

import time

import pytest

from products.interviewer.flow import CLOSING_MESSAGE, InterviewFlow
from products.interviewer.policy import (
    CLARIFY_CURRENT_ANSWER,
    CLOSE_INTERVIEW,
    MOVE_TO_NEXT_COMPETENCY,
    OFFER_FINAL_ADDITION,
    PolicyState,
    decide_next_action,
    non_answer_bounds_from_definition,
)
from products.interviewer.validator import (
    GeneratedQuestion,
    validate_generated_question,
)


def _definition() -> dict:
    return {
        "definition_id": "idef_b3",
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
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 2,
                "required_intents": ["establish_context", "establish_ownership"],
                "evidence_expected": ["context", "action"],
            },
            {
                "id": "communication",
                "name": "Communication",
                "importance": "medium",
                "max_depth": 2,
                "max_probes": 2,
                "required_intents": ["establish_context"],
                "evidence_expected": ["clarity"],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "problem_solving",
                "steps": [
                    {
                        "intent": "establish_context",
                        "objective": "context",
                        "example_question": "What problem were you solving?",
                    },
                    {
                        "intent": "establish_ownership",
                        "objective": "ownership",
                        "example_question": "What part did you own?",
                    },
                ],
            },
            {
                "competency_id": "communication",
                "steps": [
                    {
                        "intent": "establish_context",
                        "objective": "context",
                        "example_question": "How did you explain that to others?",
                    }
                ],
            },
        ],
        "job_intelligence": {
            "role": {"title": "Backend Engineer", "target_level": "mid", "domain": "software"}
        },
    }


def test_confirm_continue_after_maps_to_close_after() -> None:
    bounds = non_answer_bounds_from_definition(_definition())
    assert bounds["clarify_after"] == 1
    assert bounds["rephrase_after"] == 2
    assert bounds["change_topic_after"] == 3
    assert bounds["close_after"] == 4


def test_non_answer_ladder_clarify_rephrase_change_close() -> None:
    base = dict(
        interviewer_turn_count=5,
        candidate_turn_count=5,
        phase_name="Problem solving",
        competency_id="problem_solving",
        has_uncovered_competencies=True,
        clarify_after=1,
        rephrase_after=2,
        change_topic_after=3,
        close_after=4,
    )
    clarify = decide_next_action(PolicyState(**base, consecutive_unusable=1))
    assert clarify.action == CLARIFY_CURRENT_ANSWER
    assert clarify.intent == "clarify"

    rephrase = decide_next_action(PolicyState(**base, consecutive_unusable=2))
    assert rephrase.action == CLARIFY_CURRENT_ANSWER
    assert rephrase.intent == "rephrase"

    change = decide_next_action(PolicyState(**base, consecutive_unusable=3))
    assert change.action == MOVE_TO_NEXT_COMPETENCY
    assert change.forced_flow_decision == "advance"

    # Early close blocked: still has topics → advance instead of closing.
    early_close = decide_next_action(
        PolicyState(
            **base,
            consecutive_unusable=4,
            elapsed_seconds=120,
            target_end_seconds=1800,
            min_elapsed_before_close_seconds=720,
            min_candidate_turns_before_close=8,
        )
    )
    assert early_close.action == MOVE_TO_NEXT_COMPETENCY

    closed = decide_next_action(
        PolicyState(
            **{**base, "has_uncovered_competencies": False},
            consecutive_unusable=4,
            elapsed_seconds=900,
            target_end_seconds=1800,
            min_elapsed_before_close_seconds=720,
            min_candidate_turns_before_close=8,
        )
    )
    assert closed.action == CLOSE_INTERVIEW
    assert closed.forced_flow_decision == "close"


def test_soft_end_grace_offers_final_then_target_closes() -> None:
    soft = decide_next_action(
        PolicyState(
            interviewer_turn_count=10,
            candidate_turn_count=10,
            phase_name="Communication",
            competency_id="communication",
            at_last_competency=True,
            elapsed_seconds=27 * 60,
            soft_end_seconds=27 * 60,
            target_end_seconds=30 * 60,
            hard_end_seconds=35 * 60,
        )
    )
    assert soft.action == OFFER_FINAL_ADDITION
    assert soft.intent == "final_addition"

    target = decide_next_action(
        PolicyState(
            interviewer_turn_count=11,
            candidate_turn_count=11,
            phase_name="Communication",
            competency_id="communication",
            at_last_competency=True,
            elapsed_seconds=30 * 60,
            soft_end_seconds=27 * 60,
            target_end_seconds=30 * 60,
            hard_end_seconds=35 * 60,
        )
    )
    assert target.action == CLOSE_INTERVIEW
    assert "target" in target.reason


def test_soft_end_advances_remaining_competencies_without_deeper_probes() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=8,
            candidate_turn_count=8,
            phase_name="Problem solving",
            competency_id="problem_solving",
            probe_count=1,
            max_probes=3,
            max_depth=4,
            missing_intents=["establish_ownership"],
            at_last_competency=False,
            has_uncovered_competencies=True,
            elapsed_seconds=27 * 60,
            soft_end_seconds=27 * 60,
            target_end_seconds=30 * 60,
            hard_end_seconds=35 * 60,
        )
    )
    assert decision.action == MOVE_TO_NEXT_COMPETENCY
    assert decision.current_depth <= 2


@pytest.mark.asyncio
async def test_four_unusable_answers_close_with_closing_message() -> None:
    import time

    class Scripted:
        async def generate_reply(self, messages, **_kwargs):
            return (
                '{"question": "Could you share one concrete example?",'
                ' "competency_id": "problem_solving", "intent": "establish_context",'
                ' "depth": 1, "source_claim_ids": []}'
            )

    flow = InterviewFlow(
        {"phases": []},
        Scripted(),
        interview_definition=_definition(),
        job_description="Own Python FastAPI services.",
        candidate_profile={
            "experience_summary": {"profile_type": "junior"},
            "claims": [{"claim_id": "c1", "type": "project", "value": "Billing API"}],
        },
    )
    # Opening
    await flow.generate_next_question(None)
    # Intro usable enough to proceed onto resume projects.
    await flow.generate_next_question(
        "I am a backend engineer who worked on APIs and services in Python."
    )
    # Exercise non-answer close on the last competency so change-topic can wrap up.
    competency_indexes = [
        index
        for index, phase in enumerate(flow.phases)
        if phase.get("competency_id")
    ]
    flow.phase_index = competency_indexes[-1]
    flow.probe_count = 0
    flow.usable_exchanges_on_competency = 0
    # Satisfy min interview length so controlled close is allowed.
    flow.started_at = time.monotonic() - 900
    for _ in range(3):
        await flow.generate_next_question("Yeah.")
    question = await flow.generate_next_question("Yeah.")
    assert question == CLOSING_MESSAGE
    assert flow.completed is True


@pytest.mark.asyncio
async def test_completed_path_always_returns_closing_message() -> None:
    class Boom:
        async def generate_reply(self, messages, **_kwargs):
            raise RuntimeError("down")

    flow = InterviewFlow(
        {"phases": []},
        Boom(),
        interview_definition=_definition(),
    )
    flow.completed = True
    assert await flow.generate_next_question("anything") == CLOSING_MESSAGE


def test_anti_trivia_rejects_acronym_drill() -> None:
    generated = GeneratedQuestion(
        question="What does API stand for?",
        competency_id="problem_solving",
        intent="establish_context",
        depth=1,
    )
    result = validate_generated_question(
        generated,
        definition=_definition(),
        policy_competency_id="problem_solving",
        policy_intent="establish_context",
        policy_depth=1,
        max_depth=3,
        recent_questions=[],
        allowed_probes=[],
        job_description="Own FastAPI services.",
        resume_text="Built billing APIs.",
    )
    assert result.ok is False
    assert "non_job_trivia" in result.reasons


def test_anti_trivia_allows_applied_job_question() -> None:
    generated = GeneratedQuestion(
        question="In your billing API work, how did you handle retries under load?",
        competency_id="problem_solving",
        intent="establish_context",
        depth=1,
    )
    result = validate_generated_question(
        generated,
        definition=_definition(),
        policy_competency_id="problem_solving",
        policy_intent="establish_context",
        policy_depth=1,
        max_depth=3,
        recent_questions=[],
        allowed_probes=[],
        job_description="Own FastAPI billing services with retries.",
        resume_text="Owned billing API retries.",
    )
    assert "non_job_trivia" not in result.reasons
