"""Schema-constrained LLM completions with a fast no-op when extract is disabled."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("backend-api.brain.llm")


def llm_extract_enabled() -> bool:
    flag = (os.getenv("INTERVIEW_LLM_EXTRACT") or "auto").strip().lower()
    if flag in {"0", "false", "off", "heuristic"}:
        return False
    if flag in {"1", "true", "on", "llm"}:
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    provider = (os.getenv("LLM_PROVIDER") or "self_hosted").strip().lower()
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    return bool(api_key) or provider in {"openai", "openai_api", "api"}


async def complete_structured_json(
    *,
    schema_name: str,
    schema: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any] | None:
    if not llm_extract_enabled():
        return None
    llm_url = os.getenv("LLM_SERVICE_URL", "http://localhost:11434/v1").rstrip("/")
    timeout_s = float(os.getenv("LLM_EXTRACT_TIMEOUT_SECONDS", "20"))
    connect_s = float(os.getenv("HTTP_CONNECT_TIMEOUT_SECONDS", "5"))
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    provider = (os.getenv("LLM_PROVIDER") or "self_hosted").strip().lower()
    use_openai = provider in {"openai", "openai_api", "api"} or "api.openai.com" in llm_url
    model = os.getenv("LLM_MODEL_NAME", "qwen3:4b-instruct-2507-q8_0")
    if use_openai and (":" in model or model.lower().startswith("qwen")):
        model = os.getenv("LLM_EXTRACT_MODEL_NAME", "gpt-4o-mini")

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if use_openai:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
        payload["messages"][0]["content"] += " Reply with JSON only."
    else:
        payload["format"] = schema

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=connect_s)
        ) as client:
            resp = await client.post(
                f"{llm_url}/chat/completions",
                json=payload,
                headers=headers or None,
            )
            resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as exc:
        logger.warning(
            "structured_llm_failed",
            extra={
                "event": "structured_llm_failed",
                "schema_name": schema_name,
                "error_type": type(exc).__name__,
            },
        )
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
