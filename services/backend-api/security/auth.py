"""Service authentication for BFF and worker-only endpoints."""
from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def _expected_token(audience: str) -> str:
    env_name = (
        "VOICE_AGENT_SERVICE_TOKEN"
        if audience == "worker"
        else "BACKEND_SERVICE_TOKEN"
    )
    return (os.getenv(env_name) or "").strip()


def verify_service_token(authorization: str | None, audience: str) -> None:
    expected = _expected_token(audience)
    environment = (os.getenv("APP_ENV") or "development").strip().lower()
    if not expected:
        if environment in {"production", "staging"}:
            raise HTTPException(
                status_code=503,
                detail=f"{audience} service authentication is not configured",
            )
        return

    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service credentials")


async def require_bff_service(
    authorization: str | None = Header(default=None),
) -> None:
    verify_service_token(authorization, "bff")


async def require_worker_service(
    authorization: str | None = Header(default=None),
) -> None:
    verify_service_token(authorization, "worker")


async def require_bff_or_worker_service(
    authorization: str | None = Header(default=None),
) -> None:
    """Accept either BFF or worker service token."""
    try:
        verify_service_token(authorization, "bff")
        return
    except HTTPException as bff_error:
        if bff_error.status_code == 503:
            raise
    try:
        verify_service_token(authorization, "worker")
    except HTTPException as worker_error:
        if worker_error.status_code == 503:
            raise
        raise HTTPException(status_code=401, detail="Invalid service credentials") from worker_error
