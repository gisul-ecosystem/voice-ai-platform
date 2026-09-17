from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from clients.llm.openai_compat import OpenAICompatLlm


@pytest.mark.asyncio
async def test_openai_chat_completion_contract() -> None:
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
    )
    response = httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": "Next question?"}}]},
    )
    client = OpenAICompatLlm(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="test-key",
    )
    with patch(
        "clients.llm.openai_compat.request",
        new_callable=AsyncMock,
        return_value=response,
    ) as mocked:
        text = await client.generate_reply([{"role": "user", "content": "Hi"}])

    assert text == "Next question?"
    kwargs = mocked.await_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["json"]["model"] == "gpt-4o-mini"
