"""HTTP client for backend-api (Laptop 4). Stage 1 plan + Racko mock tools."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import BACKEND_API_URL, BACKEND_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.backend")


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


async def fetch_interview_plan(job_description: str, resume_text: str) -> dict:
    started = time.perf_counter()
    resp = await request(
        "backend-api",
        "POST",
        f"{BACKEND_API_URL}/interviews/plan",
        timeout=make_timeout(BACKEND_TIMEOUT_SECONDS),
        json={"job_description": job_description, "resume_text": resume_text},
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
