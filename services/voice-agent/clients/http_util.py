"""Pooled, bounded HTTP transport shared by provider and service clients."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx

from clients.errors import ServiceUnavailableError
from clients.settings import HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_RETRY_ATTEMPTS

logger = logging.getLogger("voice-agent.http")
_CLIENTS: dict[int, httpx.AsyncClient] = {}


def make_timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=HTTP_CONNECT_TIMEOUT_SECONDS)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response is not None and (
            exc.response.status_code == 429 or exc.response.status_code >= 500
        )
    return False


def _client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    client = _CLIENTS.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient()
        _CLIENTS[loop_id] = client
    return client


async def close_http_client() -> None:
    clients = list(_CLIENTS.values())
    _CLIENTS.clear()
    for client in clients:
        if not client.is_closed:
            await client.aclose()


@asynccontextmanager
async def stream_request(
    service: str,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout,
    api_key: str | None = None,
    headers: dict | None = None,
    **kwargs,
) -> AsyncIterator[httpx.Response]:
    """Open a non-retried streaming response using the shared connection pool."""
    req_headers = dict(headers or {})
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with _client().stream(
            method,
            url,
            headers=req_headers or None,
            timeout=timeout,
            **kwargs,
        ) as response:
            response.raise_for_status()
            yield response
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError(
            service,
            f"{type(exc).__name__}: {exc}",
            url=url,
        ) from exc


def _retry_delay(exc: BaseException, attempt: int) -> float:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        raw = exc.response.headers.get("Retry-After")
        try:
            if raw is not None:
                return min(max(float(raw), 0.0), 30.0)
        except ValueError:
            pass
    ceiling = min(0.5 * (2 ** max(attempt - 1, 0)), 4.0)
    return random.uniform(0.0, ceiling)


async def request(
    service: str,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout,
    api_key: str | None = None,
    headers: dict | None = None,
    retry_safe: bool | None = None,
    **kwargs,
) -> httpx.Response:
    """Pooled request with bounded safe retries and secret-aware logging.

    api_key is sent as Authorization: Bearer … and is never written to logs.
    Paid/mutating POST operations are not retried unless a caller explicitly
    supplies an idempotency strategy and opts in with ``retry_safe=True``.
    """
    req_headers = dict(headers or {})
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    may_retry = method.upper() in {"GET", "HEAD", "OPTIONS"} if retry_safe is None else retry_safe

    started = time.perf_counter()
    try:
        for attempt in range(1, HTTP_RETRY_ATTEMPTS + 1):
            try:
                resp = await _client().request(
                    method,
                    url,
                    headers=req_headers or None,
                    timeout=timeout,
                    **kwargs,
                )
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                if not may_retry or not _is_retryable(exc) or attempt >= HTTP_RETRY_ATTEMPTS:
                    raise
                wait_s = _retry_delay(exc, attempt)
                logger.warning(
                    "http_retry",
                    extra={
                        "event": "http_retry",
                        "remote_service": service,
                        "url": url,
                        "method": method,
                        "attempt": attempt,
                        "wait_s": round(wait_s, 3),
                        "error_type": type(exc).__name__,
                        "has_api_key": bool(api_key),
                    },
                )
                await asyncio.sleep(wait_s)
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

    raise AssertionError("unreachable")
