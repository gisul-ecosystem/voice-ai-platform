from __future__ import annotations

from types import SimpleNamespace

from voice_platform.chat import last_text


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
