"""
LLM client -- talks to whatever is behind LLM_SERVICE_URL.
Ollama today (Laptop 1), vLLM later on a GPU server. Both speak the
OpenAI-compatible /v1/chat/completions shape, so this file doesn't
change when you swap backends -- only the .env URL and model name do.

Per-session provider/key overrides: clients.llm.get_llm_client(...)
"""
from __future__ import annotations

from clients.llm import get_llm_client


async def generate_reply(messages: list[dict], *, extra_body: dict | None = None) -> str:
    return await get_llm_client().generate_reply(messages, extra_body=extra_body)
