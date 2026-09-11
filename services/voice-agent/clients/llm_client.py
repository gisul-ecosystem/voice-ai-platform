"""
LLM client -- talks to whatever is behind LLM_SERVICE_URL.
Ollama today (Laptop 1), vLLM later on a GPU server. Both speak the
OpenAI-compatible /v1/chat/completions shape, so this file doesn't
change when you swap backends -- only the .env URL and model name do.
"""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import LLM_MODEL_NAME, LLM_SERVICE_URL, LLM_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.llm")


async def generate_reply(messages: list[dict], *, extra_body: dict | None = None) -> str:
    payload: dict = {"model": LLM_MODEL_NAME, "messages": messages}
    if extra_body:
        payload.update(extra_body)

    started = time.perf_counter()
    resp = await request(
        "llm",
        "POST",
        f"{LLM_SERVICE_URL}/chat/completions",
        timeout=make_timeout(LLM_TIMEOUT_SECONDS),
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
            "model": LLM_MODEL_NAME,
            "message_count": len(messages),
            "output_chars": len(text or ""),
        },
    )
    return text
