from __future__ import annotations

import pytest

import aaptor_agent
import racko_agent


class FakeLlm:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict]] = []

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.messages.append(messages)
        return self.replies.pop(0)


def test_aaptor_stage2_parser_preserves_fallbacks() -> None:
    assert aaptor_agent._parse_stage2("DECISION: advance\n\nNext question?") == (
        "advance",
        "Next question?",
    )
    assert aaptor_agent._parse_stage2("") == (
        "probe",
        aaptor_agent.FALLBACK_OPENING,
    )


@pytest.mark.asyncio
async def test_aaptor_forces_advance_after_probe_limit() -> None:
    llm = FakeLlm(
        "DECISION: probe\n\nFirst probe?",
        "DECISION: probe\n\nSecond probe?",
        "DECISION: probe\n\nForced advance question?",
    )
    agent = aaptor_agent.AaptorAgent(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                },
                {
                    "name": "technical",
                    "duration_minutes": 10,
                    "topics": ["Python"],
                    "source": "jd",
                },
            ]
        },
        llm,
    )

    await agent.generate_next_question("Answer one")
    await agent.generate_next_question("Answer two")
    await agent.generate_next_question("Answer three")

    assert agent.phase_index == 1
    assert agent.probe_count == 0
    assert agent.candidate_turns == ["Answer one", "Answer two", "Answer three"]


def test_racko_parsers_and_id_extraction() -> None:
    assert racko_agent._parse_intent("INTENT: billing") == "billing"
    assert racko_agent._parse_intent("please get me a real person") == "escalation"
    assert racko_agent._parse_resolved("RESOLVED: no\n\nNeed more detail") == (
        False,
        "Need more detail",
    )
    assert racko_agent._extract_id("order ORD-12345", "order") == "ORD-12345"
    # The prefixed match is skipped for the wrong intent, then the same token is
    # accepted by the existing bare-ID fallback.
    assert racko_agent._extract_id("account ACC-12345", "order") == "ACC-12345"


@pytest.mark.asyncio
async def test_racko_escalates_after_unresolved_replies(monkeypatch) -> None:
    llm = FakeLlm(
        "INTENT: general",
        "RESOLVED: no\n\nCould you clarify?",
        "INTENT: general",
        "RESOLVED: no\n\nStill unclear.",
    )

    async def no_context(_query: str) -> list[str]:
        return []

    monkeypatch.setattr(racko_agent, "retrieve_context", no_context)
    agent = racko_agent.RackoAgent(llm, session_id="session-test")

    assert await agent.generate_reply_text("I need help") == "Could you clarify?"
    second = await agent.generate_reply_text("That did not solve it")

    assert second == racko_agent.ESCALATION_SPOKEN
    assert agent.escalated is True
