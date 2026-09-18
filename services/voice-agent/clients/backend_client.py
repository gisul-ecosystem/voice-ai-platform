"""HTTP client for backend-api (Laptop 4). Stage 1 plan + Racko mock tools."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import (
    BACKEND_API_URL,
    BACKEND_TIMEOUT_SECONDS,
    VOICE_AGENT_SERVICE_TOKEN,
)

logger = logging.getLogger("voice-agent.backend")


def _service_headers() -> dict[str, str] | None:
    if not VOICE_AGENT_SERVICE_TOKEN:
        return None
    return {"Authorization": f"Bearer {VOICE_AGENT_SERVICE_TOKEN}"}


async def fetch_account_status(account_id: str) -> dict:
    started = time.perf_counter()
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/tools/account/{account_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    payload = resp.json()
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "tool_account",
            "latency_ms": latency_ms,
            "account_id": account_id,
        },
    )
    return payload


async def fetch_order_status(order_id: str) -> dict:
    started = time.perf_counter()
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/tools/order/{order_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    payload = resp.json()
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "tool_order",
            "latency_ms": latency_ms,
            "order_id": order_id,
        },
    )
    return payload


async def fetch_invoice_status(invoice_id: str) -> dict:
    started = time.perf_counter()
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/tools/invoice/{invoice_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    payload = resp.json()
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "tool_invoice",
            "latency_ms": latency_ms,
            "invoice_id": invoice_id,
        },
    )
    return payload


async def fetch_interview_plan(
    job_description: str,
    resume_text: str,
    interview_setup: dict | None = None,
) -> dict:
    started = time.perf_counter()
    resp = await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/interviews/plan",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json={
            "job_description": job_description,
            "resume_text": resume_text,
            "interview_setup": interview_setup,
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    outline = resp.json()
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "interview_plan",
            "latency_ms": latency_ms,
            "phase_count": len(outline.get("phases") or []),
        },
    )
    return outline


async def fetch_interview_context(context_id: str) -> dict:
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/interview-contexts/{context_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
    )
    return resp.json()


async def fetch_interview_definition(definition_id: str) -> dict:
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/interview-brain/definitions/{definition_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
    )
    return resp.json()


async def report_session_status(
    session_id: str,
    status: str,
    *,
    reason: str | None = None,
) -> None:
    payload = {"status": status}
    if reason:
        payload["reason"] = reason
    await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/status",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json=payload,
        retry_safe=True,
    )


async def fetch_session_state(session_id: str) -> dict:
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
    )
    return resp.json()


async def fetch_brain_state(session_id: str) -> dict:
    resp = await request(
        "backend-api",
        "GET",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/brain",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
    )
    return resp.json()


async def put_brain_state(session_id: str, state: dict) -> dict:
    resp = await request(
        "backend-api",
        "PUT",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/brain",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json=state,
        retry_safe=True,
    )
    return resp.json()


async def record_brain_question(
    session_id: str,
    *,
    question_id: str,
    text: str,
    intent: str = "live_question",
    depth: int = 1,
    competency_id: str | None = None,
    status: str = "spoken",
    source_claim_ids: list[str] | None = None,
    prompt_version: str | None = None,
    definition_id: str | None = None,
    policy_action: str | None = None,
    validator_ok: bool | None = None,
    validator_reasons: list[str] | None = None,
    raw_model_output: str | None = None,
) -> None:
    payload: dict = {
        "question_id": question_id,
        "session_id": session_id,
        "intent": intent,
        "depth": depth,
        "text": text,
        "status": status,
    }
    if competency_id:
        payload["competency_id"] = competency_id
    if source_claim_ids:
        payload["source_claim_ids"] = list(source_claim_ids)
    if prompt_version:
        payload["prompt_version"] = prompt_version
    if definition_id:
        payload["definition_id"] = definition_id
    if policy_action:
        payload["policy_action"] = policy_action
    if validator_ok is not None:
        payload["validator_ok"] = validator_ok
    if validator_reasons:
        payload["validator_reasons"] = list(validator_reasons)[:20]
    if raw_model_output:
        payload["raw_model_output"] = raw_model_output[:2000]
    await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/brain/questions",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json=payload,
        retry_safe=True,
    )


async def record_brain_answer(
    session_id: str,
    *,
    answer_id: str,
    question_id: str,
    turn_ids: list[str],
    final_transcript: str,
    usable: bool = True,
    usability: str = "usable",
) -> None:
    await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/brain/answers",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json={
            "answer_id": answer_id,
            "question_id": question_id,
            "session_id": session_id,
            "turn_ids": turn_ids,
            "final_transcript": final_transcript,
            "usable": usable,
            "usability": usability,
            "status": "answered",
        },
        retry_safe=True,
    )


async def record_session_turn(
    session_id: str,
    *,
    turn_id: str,
    speaker: str,
    text: str,
    phase_index: int,
    sequence_number: int,
) -> None:
    await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/internal/interview-sessions/{session_id}/turns",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        headers=_service_headers(),
        json={
            "turn_id": turn_id,
            "speaker": speaker,
            "text": text,
            "phase_index": phase_index,
            "sequence_number": sequence_number,
            "is_final": True,
        },
        retry_safe=True,
    )
