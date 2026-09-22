from __future__ import annotations

from types import SimpleNamespace

from voice_platform.chat import is_usable_candidate_turn, last_text


def test_last_text_reads_latest_matching_role() -> None:
    context = SimpleNamespace(
        items=[
            SimpleNamespace(role="user", text_content="first"),
            SimpleNamespace(role="assistant", text_content="answer"),
            SimpleNamespace(role="user", text_content="latest"),
        ]
    )
    assert last_text(context) == "latest"


def test_last_text_joins_string_content_parts() -> None:
    context = SimpleNamespace(
        items=[
            SimpleNamespace(
                role="user",
                text_content=None,
                content=["hello", {"type": "image"}, "world"],
            )
        ]
    )
    assert last_text(context) == "hello world"


def test_usable_candidate_turn_rejects_echo_and_collapsed_stt() -> None:
    assert is_usable_candidate_turn("Hello", min_words=1)
    assert not is_usable_candidate_turn("Hello")
    assert not is_usable_candidate_turn("Thank you.")
    assert not is_usable_candidate_turn("So,")
    assert not is_usable_candidate_turn("That's " * 20)
    assert not is_usable_candidate_turn(
        "Could you walk me through your background?",
        last_agent_text="Could you walk me through your background?",
    )
    assert not is_usable_candidate_turn(
        "Thanks for joining. I'm your interviewer",
        last_agent_text=(
            "Thanks for joining. I'm your interviewer for the Backend Engineer "
            "conversation. To get started, please introduce yourself."
        ),
    )
