from __future__ import annotations

import json

import pytest

from products.interviewer.flow import InterviewFlow


class FakeStreamingLlm:
    def __init__(self, *payloads: str) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        self.calls += 1
        payload = self.payloads.pop(0) if self.payloads else self.payloads[-1]
        # Emit in small chunks so a naive implementation would speak mid-question.
        for index in range(0, len(payload), 12):
            yield payload[index : index + 12]

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.calls += 1
        return self.payloads.pop(0) if self.payloads else "{}"


def _payload(question: str) -> str:
    return json.dumps(
        {
            "question": question,
            "competency_id": "dsa",
            "intent": "applied_understanding",
            "depth": 2,
        }
    )


def _definition() -> dict:
    return {
        "definition_id": "idef_gate_01",
        "prompt_version": "interviewer-system-v2",
        "competencies": [
            {
                "id": "dsa",
                "name": "Algorithms",
                "definition": "Designs and analyses algorithms.",
                "evidence_expected": ["approach", "complexity"],
                "max_depth": 4,
                "max_probes": 4,
            }
        ],
    }


def _flow(llm, *, asked: list[str] | None = None) -> InterviewFlow:
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        job_description="Backend engineer working on algorithms and data structures.",
        interviewer_turns=asked if asked is not None else ["q1", "q2"],
        candidate_turns=["intro", "background"],
    )
    flow.phase_index = next(
        index
        for index, phase in enumerate(flow.phases)
        if phase.get("competency_id") == "dsa"
    )
    return flow


async def _collect(flow: InterviewFlow, turn: str) -> str:
    parts: list[str] = []
    async for chunk in flow.generate_next_question_stream(turn):
        parts.append(chunk)
    return "".join(parts)


@pytest.mark.asyncio
async def test_question_is_not_spoken_in_fragments() -> None:
    llm = FakeStreamingLlm(_payload("Which data structure did you pick, and why that one?"))
    flow = _flow(llm)

    chunks: list[str] = []
    async for chunk in flow.generate_next_question_stream("I built a scheduler."):
        chunks.append(chunk)

    # The whole question arrives as one piece, after validation - never token by token.
    assert chunks == ["Which data structure did you pick, and why that one?"]


@pytest.mark.asyncio
async def test_duplicate_question_is_blocked_before_speech() -> None:
    repeat = "Which data structure did you pick, and why that one?"
    # First call repeats an earlier question; the repair retry returns a fresh one.
    llm = FakeStreamingLlm(
        _payload(repeat),
        _payload("What was the space cost of that approach at peak load?"),
    )
    flow = _flow(llm, asked=[repeat])

    spoken = await _collect(flow, "I built a scheduler.")

    assert spoken != repeat, "a duplicate question reached the candidate"
    assert spoken == "What was the space cost of that approach at peak load?"
    assert llm.calls == 2, "the repair retry did not run"


@pytest.mark.asyncio
async def test_leading_question_is_blocked_before_speech() -> None:
    leading = "So you used a hash map there, right?"
    llm = FakeStreamingLlm(
        _payload(leading),
        _payload("How did you handle collisions in that lookup?"),
    )
    flow = _flow(llm)

    spoken = await _collect(flow, "I built a scheduler.")

    assert spoken != leading
    assert spoken == "How did you handle collisions in that lookup?"


@pytest.mark.asyncio
async def test_clean_question_is_spoken_without_a_retry() -> None:
    llm = FakeStreamingLlm(_payload("What did that lookup cost at ten times the load?"))
    flow = _flow(llm)

    spoken = await _collect(flow, "I built a scheduler.")

    assert spoken == "What did that lookup cost at ten times the load?"
    assert llm.calls == 1, "a valid question must not trigger a second LLM call"
