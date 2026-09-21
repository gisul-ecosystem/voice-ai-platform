"""InterviewFlow policy-mode integration tests."""
from __future__ import annotations

import pytest

from products.interviewer.flow import InterviewFlow


class FakeLlm:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict]] = []

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.messages.append(messages)
        return self.replies.pop(0)


def _definition() -> dict:
    return {
        "definition_id": "idef_flow_policy_01",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
        },
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "max_depth": 3,
                "max_probes": 2,
                "evidence_expected": ["context", "ownership", "result"],
            },
            {
                "id": "communication",
                "name": "Communication",
                "max_depth": 3,
                "max_probes": 2,
                "evidence_expected": ["clarity"],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "problem_solving",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "example_question": "Which algorithm did you use for the problem, and why?",
                    },
                ],
            },
        ],
    }


def test_policy_prompt_contains_full_technical_reference_context() -> None:
    definition = _definition()
    definition["job_intelligence"] = {
        "role": {"title": "AI Engineer", "domain": "AI/ML", "target_level": "mid"},
        "knowledge": [{"text": "Model evaluation and overfitting"}],
        "skills": [{"text": "Python and machine learning"}],
        "tools": [{"text": "scikit-learn"}],
        "raw_job_description": "Use algorithms, data structures, and model evaluation.",
    }
    definition["question_ladders"].append(
        {
            "competency_id": "communication",
            "levels": [
                {
                    "depth": 1,
                    "intent": "establish_context",
                    "objective": "Assess technical communication",
                    "example_question": "How would you explain a model trade-off?",
                }
            ],
        }
    )
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=definition,
        job_description="Use algorithms, data structures, and model evaluation.",
        resume_text="Built a machine learning classifier in Python.",
        candidate_profile={"claims": [{"claim_id": "c1", "value": "Built a machine learning classifier"}]},
        initial_phase_index=2,
    )

    prompt, _ = flow._structured_system_prompt(
        "I built a machine learning classifier in Python.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )

    assert "machine learning" in prompt.lower()
    assert "data structures" in prompt.lower()
    assert "model evaluation" in prompt.lower()
    assert "technical communication" in prompt.lower()


@pytest.mark.asyncio
async def test_policy_mode_blocks_immediate_deep_dive_advance() -> None:
    llm = FakeLlm(
        "DECISION: advance\n\nJumping straight into system design tradeoffs?",
        "DECISION: advance\n\nJumping straight into system design tradeoffs?",
    )
    flow = InterviewFlow(
        {"phases": [{"name": "legacy", "duration_minutes": 10, "topics": ["x"], "source": "generic"}]},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["Thanks for joining. Please introduce yourself."],
        candidate_turns=[],
        initial_phase_index=1,
    )
    assert flow.policy_mode is True
    assert flow.phases[0]["name"] == "opening"

    question = await flow.generate_next_question(
        "I am a backend engineer who worked on payments."
    )
    prompt = llm.messages[0][0]["content"]
    assert "POLICY ENGINE" in prompt
    # candidate_map's forced advance is resolved before the prompt is built, so the
    # LLM sees the real next competency it is entering, not the phase it just left.
    assert "Problem solving" in prompt
    assert "problem_solving" in prompt
    # Forced probe — cannot honor LLM advance into deep dive.
    assert flow.phase_index == 2
    # The configured ladder question for this competency/intent is pinned verbatim.
    assert question == "Which algorithm did you use for the problem, and why?"


@pytest.mark.asyncio
async def test_policy_mode_uses_configured_competency_question() -> None:
    llm = FakeLlm(
        '{"question":"Tell me about your background.","competency_id":"problem_solving","intent":"establish_context","depth":1}'
    )
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )

    question = await flow.generate_next_question("I solved a graph problem.")

    assert question == "Which algorithm did you use for the problem, and why?"


@pytest.mark.asyncio
async def test_policy_mode_advances_after_probe_cap() -> None:
    llm = FakeLlm(
        "DECISION: probe\n\nWhat was difficult about that ownership?"
    )
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2", "q3"],
        candidate_turns=["a1", "a2", "a3"],
        initial_phase_index=2,
        initial_probe_count=2,
    )
    await flow.generate_next_question(
        "I owned retries and timeouts on the billing API."
    )
    assert flow.phase_index == 3


def test_candidate_map_moves_to_technical_baseline_after_one_turn() -> None:
    from products.interviewer.policy import PolicyState, decide_next_action

    decision = decide_next_action(
        PolicyState(
            candidate_turn_count=1,
            interviewer_turn_count=2,
            phase_name="candidate_map",
            has_uncovered_competencies=True,
            competency_id=None,
        )
    )

    assert decision.action == "ASK_BASELINE"
    assert decision.forced_flow_decision == "advance"


@pytest.mark.asyncio
async def test_policy_mode_opening_cites_resume_or_jd_materials() -> None:
    llm = FakeLlm(
        '{"question":"Welcome! I saw you worked on a machine learning classifier '
        '\u2014 could you introduce yourself and your background?","intent":"opening","depth":1}'
    )
    definition = _definition()
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=definition,
        candidate_profile={
            "claims": [{"claim_id": "c1", "value": "Built a machine learning classifier"}]
        },
        job_description="Looking for an engineer skilled in data structures and algorithms.",
        initial_phase_index=0,
    )

    await flow.generate_next_question(None)

    prompt = llm.messages[0][0]["content"]
    assert "cite exactly ONE concrete signal" in prompt
    assert "machine learning classifier" in prompt


@pytest.mark.asyncio
async def test_policy_mode_opening_falls_back_only_on_llm_failure() -> None:
    class FailingLlm:
        async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
            raise RuntimeError("provider unavailable")

    from products.interviewer.flow import FALLBACK_OPENING

    flow = InterviewFlow(
        {"phases": []},
        FailingLlm(),
        interview_definition=_definition(),
        candidate_profile={"claims": [{"claim_id": "c1", "value": "Built a classifier"}]},
        job_description="Data structures and algorithms role.",
        initial_phase_index=0,
    )

    question = await flow.generate_next_question(None)

    assert question == FALLBACK_OPENING

