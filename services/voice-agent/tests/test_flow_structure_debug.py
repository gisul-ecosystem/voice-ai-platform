"""Flow structure fixes: leading block, rewrite, dry follow-ups, JD/resume harness."""
from __future__ import annotations

from pathlib import Path

import pytest

from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import (
    MOVE_TO_NEXT_COMPETENCY,
    PolicyState,
    decide_next_action,
)
from products.interviewer.validator import (
    AnswerEvaluation,
    GeneratedQuestion,
    validate_generated_question,
)

HARNESS = Path(__file__).resolve().parents[1] / "test_harness"
SAMPLE_JD = (HARNESS / "sample_jd.txt").read_text(encoding="utf-8").strip()
SAMPLE_RESUME = (HARNESS / "sample_resume.txt").read_text(encoding="utf-8").strip()


def _backend_definition() -> dict:
    return {
        "definition_id": "idef_flow_debug",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {"duration_minutes": 30},
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
            "What would you change if you did it again?",
        ],
        "job_intelligence": {
            "role": {"title": "Backend Engineer", "target_level": "mid"},
        },
        "competencies": [
            {
                "id": "ownership",
                "name": "Service ownership",
                "importance": "high",
                "max_depth": 4,
                "max_probes": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": [
                    "production ownership",
                    "personal contribution",
                    "technical approach",
                ],
            },
            {
                "id": "reliability",
                "name": "Reliability",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 2,
                "min_assessment_intents": [
                    "establish_context",
                    "problem_or_complexity",
                ],
                "evidence_expected": ["incident handling", "failure mode"],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "ownership",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "objective": "Context of owned service",
                        "example_question": (
                            "Can you walk me through a production service you owned?"
                        ),
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "objective": "Personal ownership",
                        "example_question": (
                            "What part of that service were you personally responsible for?"
                        ),
                    },
                    {
                        "depth": 3,
                        "intent": "applied_understanding",
                        "objective": "How they built it",
                        "example_question": (
                            "How did you structure the FastAPI service boundaries?"
                        ),
                    },
                ],
            }
        ],
    }


def test_validator_rejects_leading_questions() -> None:
    generated = GeneratedQuestion(
        question="You must have owned the FastAPI service, right?",
        competency_id="ownership",
        intent="establish_ownership",
        depth=2,
    )
    result = validate_generated_question(
        generated,
        definition=_backend_definition(),
        policy_competency_id="ownership",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=4,
        recent_questions=[],
        allowed_probes=_backend_definition()["allowed_probes"],
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        recent_turns=["I owned a payments API on FastAPI."],
        hook_fact="payments API",
    )
    assert result.ok is False
    assert "leading_question" in result.reasons


def test_dry_followups_force_advance() -> None:
    decision = decide_next_action(
        PolicyState(
            candidate_turn_count=4,
            interviewer_turn_count=5,
            phase_index=2,
            probe_count=2,
            phase_name="Service ownership",
            competency_id="ownership",
            max_depth=4,
            max_probes=3,
            missing_intents=["establish_ownership"],
            has_uncovered_competencies=True,
            consecutive_dry_probes=2,
            dry_probe_limit=2,
        )
    )
    assert decision.action == MOVE_TO_NEXT_COMPETENCY
    assert "without new information" in decision.reason


class _ScriptedLlm:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def generate_reply(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        if not self.replies:
            return "{}"
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_rejected_question_is_rewritten_before_fallback() -> None:
    leading = (
        '{"question": "You must have owned the FastAPI payments API, right?", '
        '"competency_id": "ownership", "intent": "establish_ownership", "depth": 2}'
    )
    rewritten = (
        '{"question": "What part of the FastAPI payments API were you personally responsible for?", '
        '"competency_id": "ownership", "intent": "establish_ownership", "depth": 2, '
        '"answer_evaluation": {"technical_substance": "surface", '
        '"key_facts_stated": ["FastAPI payments API"]}}'
    )
    llm = _ScriptedLlm([leading, rewritten])
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_backend_definition(),
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        allow_legacy_flow=False,
    )
    # Move past opening/map into first competency baseline territory.
    flow.phase_index = next(
        index
        for index, phase in enumerate(flow.phases)
        if phase.get("competency_id") == "ownership"
    )
    flow.candidate_turns = [
        "Hi, I'm Priya.",
        "I have been a backend engineer for five years.",
    ]
    flow.interviewer_turns = [
        "Thanks for joining. Let's talk about your backend work.",
        "Tell me briefly about your recent experience.",
    ]
    flow.probe_count = 1
    flow.coverage["ownership"] = {
        "required_intents": [
            "establish_context",
            "establish_ownership",
            "applied_understanding",
        ],
        "covered_intents": ["establish_context"],
        "missing_intents": ["establish_ownership", "applied_understanding"],
    }
    question = await flow.generate_next_question(
        "I owned the FastAPI payments API migration."
    )
    assert "must have" not in question.lower()
    assert "right?" not in question.lower()
    assert "fastapi" in question.lower() or "personally" in question.lower()
    assert len(llm.calls) >= 2
    rewrite_blob = " ".join(
        str(item.get("content") or "") for item in llm.calls[1]
    ).lower()
    assert "rewrite" in rewrite_blob or "rejected" in rewrite_blob


@pytest.mark.asyncio
async def test_sample_jd_resume_flow_targets_missing_ownership_intent() -> None:
    """Debug harness: sample JD/resume drive structured follow-up intent."""
    good = (
        '{"question": "What part of the FastAPI payments service did you personally own?", '
        '"competency_id": "ownership", "intent": "establish_ownership", "depth": 2, '
        '"answer_evaluation": {"technical_substance": "surface", '
        '"key_facts_stated": ["FastAPI payments service"]}}'
    )
    llm = _ScriptedLlm([good, good])
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_backend_definition(),
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        allow_legacy_flow=False,
    )
    flow.phase_index = next(
        index
        for index, phase in enumerate(flow.phases)
        if phase.get("competency_id") == "ownership"
    )
    flow.candidate_turns = ["Hi.", "I have backend experience."]
    flow.interviewer_turns = ["Welcome.", "Tell me about your background."]
    flow.probe_count = 1
    flow.coverage["ownership"] = {
        "required_intents": [
            "establish_context",
            "establish_ownership",
            "applied_understanding",
        ],
        "covered_intents": ["establish_context"],
        "missing_intents": ["establish_ownership", "applied_understanding"],
    }
    decision = flow._current_policy_decision(pending_candidate_turn=True)
    assert decision is not None
    assert decision.intent == "establish_ownership"
    question = await flow.generate_next_question(
        "We migrated a monolith to FastAPI services around payments."
    )
    assert "?" in question
    assert question.count("?") == 1
    assert flow.last_question_competency_id == "ownership"
    assert flow.last_question_intent == "establish_ownership"


def test_remember_known_facts_increments_dry_probe_counter() -> None:
    flow = InterviewFlow(
        {"phases": []},
        object(),
        interview_definition=_backend_definition(),
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        allow_legacy_flow=False,
    )
    flow.probe_count = 1
    flow.policy_mode = True
    eval_empty = AnswerEvaluation(key_facts_stated=[])
    flow._remember_known_facts("ownership", eval_empty)
    assert flow.consecutive_dry_probes == 1
    flow._remember_known_facts("ownership", eval_empty)
    assert flow.consecutive_dry_probes == 2
    flow._remember_known_facts(
        "ownership",
        AnswerEvaluation(key_facts_stated=["Owned on-call for payments API"]),
    )
    assert flow.consecutive_dry_probes == 0
