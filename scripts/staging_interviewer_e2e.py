"""Opt-in staging smoke: context -> invitation -> room -> worker participant."""
from __future__ import annotations

import asyncio
import os
import uuid

import httpx
from livekit import rtc


def required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def main() -> None:
    backend = required("STAGING_BACKEND_URL").rstrip("/")
    service_token = required("BACKEND_SERVICE_TOKEN")
    headers = {"Authorization": f"Bearer {service_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        context_response = await client.post(
            f"{backend}/interview-contexts",
            headers=headers,
            json={
                "job_description": "Python backend engineer",
                "resume_text": "Built and operated asynchronous Python services.",
            },
        )
        context_response.raise_for_status()
        context_id = context_response.json()["context_id"]

        invitation_response = await client.post(
            f"{backend}/interview-contexts/{context_id}/invitations",
            headers=headers,
            json={
                "candidate_id": f"smoke_{uuid.uuid4().hex[:12]}",
                "ttl_minutes": 10,
            },
        )
        invitation_response.raise_for_status()
        invitation = invitation_response.json()["invitation_token"]

        session_response = await client.post(
            f"{backend}/sessions/token",
            headers=headers,
            json={
                "product_id": "interviewer",
                "name": "Staging Smoke",
                "invitation_token": invitation,
            },
        )
        session_response.raise_for_status()
        session = session_response.json()

    room = rtc.Room()
    agent_joined = asyncio.Event()

    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        if participant.identity != "Staging Smoke":
            agent_joined.set()

    try:
        await room.connect(session["livekit_url"], session["token"])
        if room.remote_participants:
            agent_joined.set()
        await asyncio.wait_for(agent_joined.wait(), timeout=30)
        print("Staging interviewer dispatch smoke passed")
    finally:
        await room.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
