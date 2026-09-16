"""OpenAI-compatible /v1/chat/completions (Ollama, vLLM, OpenAI API)."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from clients.http_util import make_timeout, request, stream_request
from clients.settings import LLM_MODEL_NAME, LLM_SERVICE_URL, LLM_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.llm")


class OpenAICompatLlm:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = LLM_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def generate_reply(
        self, messages: list[dict], *, extra_body: dict | None = None
    ) -> str:
        payload: dict = {"model": self.model, "messages": messages}
        if extra_body:
            payload.update(extra_body)

        started = time.perf_counter()
        resp = await request(
            "llm",
            "POST",
            f"{self.base_url}/chat/completions",
            timeout=make_timeout(self._timeout_seconds),
            api_key=self._api_key or None,
            json=payload,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        text = resp.json()["choices"][0]["message"]["content"]
        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "llm",
                "latency_ms": latency_ms,
                "model": self.model,
                "message_count": len(messages),
                "output_chars": len(text or ""),
            },
        )
        return text

    async def stream_reply(
        self,
        messages: list[dict],
        *,
        extra_body: dict | None = None,
    ) -> AsyncIterator[str]:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if extra_body:
            payload.update(extra_body)
        async with stream_request(
            "llm",
            "POST",
            f"{self.base_url}/chat/completions",
            timeout=make_timeout(self._timeout_seconds),
            api_key=self._api_key or None,
            json=payload,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                    content = chunk["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    continue
                if content:
                    yield str(content)


def default_self_hosted_llm(*, api_key: str = "") -> OpenAICompatLlm:
    return OpenAICompatLlm(
        base_url=LLM_SERVICE_URL,
        model=LLM_MODEL_NAME,
        api_key=api_key,
    )
