"""Echo / unusable STT must not land in the durable transcript."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from products.interviewer.agent import AaptorAgent


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

    assert chunks == []
    assert recorded == []
