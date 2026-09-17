from __future__ import annotations

import pytest

from clients.llm.openai_compat import openai_sse_content_deltas
from products.interviewer.flow import InterviewFlow, SpokenQuestionStream, parse_stage2


class FakeStreamingLlm:
    def __init__(self, *chunks: str) -> None:
        self.chunks = list(chunks)
        self.messages: list[list[dict]] = []

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


def test_spoken_question_stream_skips_decision_line() -> None:
    parser = SpokenQuestionStream()
    assert parser.push("DECISION: probe") == ""
    assert parser.push("\n\nCould you") == "Could you"
    assert parser.push(" walk me through that?") == " walk me through that?"
    assert parser.decision == "probe"
    assert parser.finish() == ""


def test_spoken_question_stream_falls_back_without_decision() -> None:
    parser = SpokenQuestionStream()
    parser.push("Just a spoken question?")
    assert parser.finish() == "Just a spoken question?"
    _, parsed = parse_stage2("Just a spoken question?")
    assert parsed == "Just a spoken question?"


def test_openai_sse_content_deltas() -> None:
    assert openai_sse_content_deltas("data: [DONE]") == []
    assert openai_sse_content_deltas(
        'data: {"choices":[{"delta":{"content":"Hello"}}]}'
    ) == ["Hello"]
    assert openai_sse_content_deltas("event: ping") == []


@pytest.mark.asyncio
async def test_generate_next_question_stream_yields_after_decision() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "What was the result of that launch?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        llm,
    )
    chunks = [
        chunk
        async for chunk in flow.generate_next_question_stream("I led the rollout.")
    ]
    assert "".join(chunks) == "What was the result of that launch?"
    assert flow.candidate_turns == ["I led the rollout."]
    assert flow.probe_count == 1
