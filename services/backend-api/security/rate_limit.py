"""Bounded in-process admission control; production gateways add global limits."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

_WINDOW_SECONDS = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


async def require_capacity(request: Request) -> None:
    limit = max(1, int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120")))
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    with _lock:
        values = _hits[key]
        while values and values[0] <= cutoff:
            values.popleft()
        if len(values) >= limit:
            raise HTTPException(status_code=429, detail="Request rate limit exceeded")
        values.append(now)
