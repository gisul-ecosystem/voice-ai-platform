"""Hot interview-brain snapshots (layer 2).

Production/staging: Redis keyed by session_id (fail-closed when REDIS_URL is set).
Development/tests: in-process memory fallback when Redis is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("backend-api.brain.redis")

_KEY_PREFIX = "interview:brain:"
_DEFAULT_TTL_SECONDS = 6 * 60 * 60

_memory_lock = threading.Lock()
_memory_store: dict[str, tuple[float, str]] = {}
_redis_client = None
_redis_init_attempted = False


def brain_key(session_id: str) -> str:
    session_id = (session_id or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    return f"{_KEY_PREFIX}{session_id}"


def snapshot_ttl_seconds() -> int:
    return max(300, int(os.getenv("INTERVIEW_BRAIN_REDIS_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))))


def _app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def _redis_required() -> bool:
    """Staging/production must use Redis when REDIS_URL is configured."""
    if not (os.getenv("REDIS_URL") or "").strip():
        return False
    return _app_env() in {"production", "staging", "prod"}


def _reset_redis_client() -> None:
    global _redis_client, _redis_init_attempted
    _redis_client = None
    _redis_init_attempted = False


def _get_redis():
    global _redis_client, _redis_init_attempted
    if _redis_client is not None:
        return _redis_client
    if _redis_init_attempted:
        return None
    _redis_init_attempted = True
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        _redis_client = client
        logger.info("brain_redis_connected", extra={"event": "brain_redis_connected"})
        return _redis_client
    except Exception:
        logger.warning(
            "brain_redis_unavailable",
            extra={"event": "brain_redis_unavailable"},
            exc_info=True,
        )
        return None


def reset_redis_for_tests() -> None:
    """Test helper: clear clients and memory store."""
    with _memory_lock:
        _memory_store.clear()
    _reset_redis_client()


def _memory_put(key: str, payload: str, ttl_seconds: int) -> None:
    expires_at = time.time() + ttl_seconds
    with _memory_lock:
        _memory_store[key] = (expires_at, payload)


def _memory_get(key: str) -> str | None:
    now = time.time()
    with _memory_lock:
        item = _memory_store.get(key)
        if item is None:
            return None
        expires_at, payload = item
        if expires_at < now:
            _memory_store.pop(key, None)
            return None
        return payload


def put_hot_snapshot(session_id: str, state: dict[str, Any]) -> str:
    """Write hot snapshot. Returns backend used: redis|memory."""
    key = brain_key(session_id)
    if state.get("session_id") and state["session_id"] != session_id:
        raise ValueError("state.session_id must match path session_id")
    payload = json.dumps(state, default=str)
    ttl = snapshot_ttl_seconds()
    client = _get_redis()
    if client is not None:
        try:
            client.set(key, payload, ex=ttl)
            return "redis"
        except Exception:
            logger.warning(
                "brain_redis_write_failed",
                extra={"event": "brain_redis_write_failed", "session_id": session_id},
                exc_info=True,
            )
            # Allow a later request to reconnect after a transient outage.
            _reset_redis_client()
    if _redis_required():
        raise RuntimeError(
            "Redis hot brain is required in production/staging; refusing memory fallback"
        )
    _memory_put(key, payload, ttl)
    return "memory"


def get_hot_snapshot(session_id: str) -> dict[str, Any] | None:
    key = brain_key(session_id)
    client = _get_redis()
    raw: str | None = None
    if client is not None:
        try:
            raw = client.get(key)
        except Exception:
            logger.warning(
                "brain_redis_read_failed",
                extra={"event": "brain_redis_read_failed", "session_id": session_id},
                exc_info=True,
            )
            _reset_redis_client()
            raw = None
    if raw is None:
        raw = _memory_get(key)
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("session_id") != session_id:
        # Hard isolation guard: never return another session's payload.
        return None
    return data


def delete_hot_snapshot(session_id: str) -> None:
    key = brain_key(session_id)
    client = _get_redis()
    if client is not None:
        try:
            client.delete(key)
        except Exception:
            logger.warning(
                "brain_redis_delete_failed",
                extra={"event": "brain_redis_delete_failed", "session_id": session_id},
                exc_info=True,
            )
            _reset_redis_client()
    with _memory_lock:
        _memory_store.pop(key, None)
