"""Echo / unusable STT must not land in the durable transcript."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from products.interviewer.agent import CLARIFY_TURN, AaptorAgent


@pytest.fixture(autouse=True)
def _allow_legacy_interview_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_LEGACY_INTERVIEW_FLOW", "1")


class _FakeLlm:
    async def generate_reply(self, messages, **_kwargs) -> str:
        return "DECISION: probe\n\nShould not be used for echo."


@pytest.mark.asyncio
async def test_echo_stt_is_not_persisted_as_candidate_turn() -> None:
    recorded: list[dict] = []

    async def turn_sink(**turn) -> None:
        recorded.append(turn)

    agent = AaptorAgent(
        {
            "phases": [
                {
                    "name": "opening",
                    "duration_minutes": 2,
                    "topics": ["intro"],
                    "source": "generic",
                }
            ]
        },
        _FakeLlm(),
        turn_sink=turn_sink,
        initial_state={
            "candidate_turns": ["I already introduced myself briefly."],
            "interviewer_turns": ["Could you walk me through your background?"],
        },
    )
    agent._opened = True
    agent._last_agent_text = "Could you walk me through your background?"

    chat_ctx = SimpleNamespace(
        items=[
            SimpleNamespace(
                role="user",
                text_content="Could you walk me through your background?",
            )
        ]
    )

    chunks: list[str] = []
    async for chunk in agent.llm_node(chat_ctx, [], None):  # type: ignore[arg-type]
        chunks.append(chunk)

    assert "".join(chunks) == CLARIFY_TURN
    assert [item["speaker"] for item in recorded] == ["agent"]
    assert recorded[0]["text"] == CLARIFY_TURN


@pytest.mark.asyncio
async def test_short_fragments_are_joined_before_flow() -> None:
    recorded: list[dict] = []
    seen_turns: list[str | None] = []

    async def turn_sink(**turn) -> None:
        recorded.append(turn)

    agent = AaptorAgent(
        {
            "phases": [
                {
                    "name": "opening",
                    "duration_minutes": 2,
                    "topics": ["intro"],
                    "source": "generic",
                }
            ]
        },
        _FakeLlm(),
        turn_sink=turn_sink,
        initial_state={
            "candidate_turns": ["I already introduced myself briefly."],
            "interviewer_turns": ["What did you build on that project?"],
        },
    )
    agent._opened = True
    agent._last_agent_text = "What did you build on that project?"

    async def fake_stream(last_candidate_turn: str | None):
        seen_turns.append(last_candidate_turn)
        yield "What part of that did you personally handle?"

    agent.flow.generate_next_question_stream = fake_stream  # type: ignore[method-assign]

    # First short fragment — buffer only.
    first = SimpleNamespace(items=[SimpleNamespace(role="user", text_content="I built")])
    chunks: list[str] = []
    async for chunk in agent.llm_node(first, [], None):  # type: ignore[arg-type]
        chunks.append(chunk)
    assert "".join(chunks) == CLARIFY_TURN
    assert seen_turns == []
    assert all(item["speaker"] == "agent" for item in recorded)

    # Second fragment completes a usable joined answer.
    second = SimpleNamespace(
        items=[
            SimpleNamespace(
                role="user",
                text_content="the LiveKit proctoring pipeline for admins",
            )
        ]
    )
    chunks = []
    async for chunk in agent.llm_node(second, [], None):  # type: ignore[arg-type]
        chunks.append(chunk)
    assert "personally handle" in "".join(chunks)
    assert seen_turns == [
        "I built the LiveKit proctoring pipeline for admins",
    ]
    assert any(
        item["speaker"] == "candidate" and "LiveKit proctoring" in item["text"]
        for item in recorded
    )
