"""Shared httpx + tenacity helper for laptop-to-laptop HTTP calls."""
from __future__ import annotations

import logging
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from clients.errors import ServiceUnavailableError
from clients.settings import HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_RETRY_ATTEMPTS

logger = logging.getLogger("voice-agent.http")


def make_timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=HTTP_CONNECT_TIMEOUT_SECONDS)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response is not None and exc.response.status_code >= 500
    return False


async def request(
    service: str,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout,
    api_key: str | None = None,
    headers: dict | None = None,
    **kwargs,
) -> httpx.Response:
    """POST/GET with exponential backoff. Raises ServiceUnavailableError, never raw httpx errors.

    api_key is sent as Authorization: Bearer … and is never written to logs.
    Client-provided keys must never land in log files or observability tooling.
    """
    req_headers = dict(headers or {})
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"

    def _log_retry(retry_state) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        wait_s = getattr(getattr(retry_state, "next_action", None), "sleep", None)
        logger.warning(
            "http_retry",
            extra={
                "event": "http_retry",
                "remote_service": service,
                "url": url,
                "method": method,
                "attempt": retry_state.attempt_number,
                "wait_s": wait_s,
                "error_type": type(exc).__name__ if exc else None,
                "has_api_key": bool(api_key),
            },
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(HTTP_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_log_retry,
    )
    async def _once() -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=req_headers or None,
                **kwargs,
            )
            resp.raise_for_status()
            return resp

    started = time.perf_counter()
    try:
        resp = await _once()
    except httpx.HTTPError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.error(
            "service_unavailable",
            extra={
                "event": "service_unavailable",
                "remote_service": service,
                "url": url,
                "method": method,
                "latency_ms": latency_ms,
                "error_type": type(exc).__name__,
            },
        )
        raise ServiceUnavailableError(service, f"{type(exc).__name__}: {exc}", url=url) from exc

    return resp
