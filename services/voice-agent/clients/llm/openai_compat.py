"""OpenAI-compatible /v1/chat/completions (Ollama, vLLM, OpenAI API)."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from clients.http_util import make_timeout, request, stream_request
from clients.settings import LLM_MODEL_NAME, LLM_SERVICE_URL, LLM_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.llm")


def openai_sse_content_deltas(line: str) -> list[str]:
    """Extract assistant text deltas from one SSE `data:` line."""
    text = (line or "").strip()
    if not text.startswith("data:"):
        return []
    data = text[5:].strip()
    if not data or data == "[DONE]":
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []
    deltas: list[str] = []
    for choice in payload.get("choices") or []:
        content = (choice.get("delta") or {}).get("content")
        if isinstance(content, str) and content:
            deltas.append(content)
    return deltas


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

    async def generate_reply_stream(
        self, messages: list[dict], *, extra_body: dict | None = None
    ) -> AsyncIterator[str]:
        payload: dict = {"model": self.model, "messages": messages, "stream": True}
        if extra_body:
            payload.update(extra_body)
            payload["stream"] = True

        url = f"{self.base_url}/chat/completions"
        started = time.perf_counter()
        first_ms: float | None = None
        chars = 0
        async with stream_request(
            "llm",
            "POST",
            url,
            timeout=make_timeout(self._timeout_seconds),
            api_key=self._api_key or None,
            json=payload,
        ) as resp:
            async for line in resp.aiter_lines():
                for delta in openai_sse_content_deltas(line):
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - started) * 1000, 1)
                    chars += len(delta)
                    yield delta

        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "ttfb_ms": first_ms,
                "model": self.model,
                "message_count": len(messages),
                "output_chars": chars,
                "streaming": True,
            },
        )

    async def stream_reply(
        self,
        messages: list[dict],
        *,
        extra_body: dict | None = None,
    ) -> AsyncIterator[str]:
        async for delta in self.generate_reply_stream(messages, extra_body=extra_body):
            yield delta


def default_self_hosted_llm(*, api_key: str = "") -> OpenAICompatLlm:
    return OpenAICompatLlm(
        base_url=LLM_SERVICE_URL,
        model=LLM_MODEL_NAME,
        api_key=api_key,
    )
