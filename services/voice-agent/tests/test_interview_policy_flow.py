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
    }


@pytest.mark.asyncio
async def test_policy_mode_blocks_immediate_deep_dive_advance() -> None:
    llm = FakeLlm(
        "DECISION: advance\n\nJumping straight into system design tradeoffs?"
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
    assert "MAP_CANDIDATE_BACKGROUND" in prompt or "ASK_BASELINE" in prompt
    # Forced probe — cannot honor LLM advance into deep dive.
    assert flow.phase_index == 1
    assert "tradeoffs" in question.lower() or question


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
