"""Opt-in session admission load harness using pre-issued single-use invitations."""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import httpx


async def main() -> None:
    backend = (os.getenv("STAGING_BACKEND_URL") or "").rstrip("/")
    token = (os.getenv("BACKEND_SERVICE_TOKEN") or "").strip()
    invitations_path = os.getenv("LOAD_INVITATIONS_FILE")
    if not backend or not token or not invitations_path:
        raise RuntimeError(
            "STAGING_BACKEND_URL, BACKEND_SERVICE_TOKEN and "
            "LOAD_INVITATIONS_FILE are required"
        )
    invitations = json.loads(Path(invitations_path).read_text(encoding="utf-8"))
    if not isinstance(invitations, list) or not invitations:
        raise RuntimeError("LOAD_INVITATIONS_FILE must contain a JSON token array")
    concurrency = max(1, int(os.getenv("LOAD_CONCURRENCY", "5")))
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures: list[int] = []

    async with httpx.AsyncClient(timeout=30) as client:
        async def create(index: int, invitation: str) -> None:
            async with semaphore:
                started = time.perf_counter()
                response = await client.post(
                    f"{backend}/sessions/token",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "product_id": "interviewer",
                        "name": f"Load Candidate {index}",
                        "invitation_token": invitation,
                    },
                )
                latencies.append((time.perf_counter() - started) * 1000)
                if response.status_code != 200:
                    failures.append(response.status_code)

        await asyncio.gather(
            *(create(index, value) for index, value in enumerate(invitations))
        )

    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(
        json.dumps(
            {
                "requests": len(invitations),
                "failures": len(failures),
                "mean_ms": round(statistics.mean(latencies), 1),
                "p95_ms": round(p95, 1),
                "statuses": failures,
            }
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
