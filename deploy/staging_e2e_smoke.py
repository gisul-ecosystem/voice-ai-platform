#!/usr/bin/env python3
"""Staging end-to-end interviewer smoke (no browser mic required).

Creates context + invitation + LiveKit session, waits for the agent to join,
then verifies greeting TTS / turn persistence from backend + worker logs.
Secrets are read from /etc/voice-ai-platform and never printed.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from livekit import rtc


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def required(env: dict[str, str], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing {key}")
    return value


async def main() -> int:
    # Prefer process env (container); fall back to VM secret files.
    frontend: dict[str, str] = {}
    backend_env: dict[str, str] = {}
    frontend_path = Path("/etc/voice-ai-platform/frontend.env")
    backend_path = Path("/etc/voice-ai-platform/backend-api.env")
    if frontend_path.exists():
        frontend = load_env(frontend_path)
    if backend_path.exists():
        backend_env = load_env(backend_path)

    token = (
        os.getenv("BACKEND_SERVICE_TOKEN")
        or frontend.get("BACKEND_SERVICE_TOKEN")
        or ""
    ).strip()
    worker_token = (
        os.getenv("VOICE_AGENT_SERVICE_TOKEN")
        or backend_env.get("VOICE_AGENT_SERVICE_TOKEN")
        or ""
    ).strip()
    if not token:
        raise RuntimeError("missing BACKEND_SERVICE_TOKEN")
    if not worker_token:
        raise RuntimeError("missing VOICE_AGENT_SERVICE_TOKEN")

    backend = (os.getenv("STAGING_BACKEND_URL") or "http://127.0.0.1:5554").rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    worker_headers = {"Authorization": f"Bearer {worker_token}"}
    candidate = f"e2e_{uuid.uuid4().hex[:10]}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Prefer an existing published definition if one exists.
        definition_id = None
        defs = await client.get(
            f"{backend}/interview-brain/definitions",
            headers=headers,
            params={"limit": 5},
        )
        if defs.status_code == 200:
            items = defs.json() if isinstance(defs.json(), list) else defs.json().get("items") or []
            for item in items:
                if isinstance(item, dict) and item.get("definition_id"):
                    definition_id = item["definition_id"]
                    break
        print(f"definition_id={definition_id or '(none)'}")

        ctx_body = {
            "job_description": (
                "AI Engineer / backend role using Python, FastAPI, Redis, and React. "
                "Own APIs, debugging, and deployment."
            ),
            "resume_text": (
                "Ujwal — backend engineer. Built FastAPI microservices, async Python, "
                "Redis queues, and React dashboards."
            ),
        }
        if definition_id:
            ctx_body["definition_id"] = definition_id

        ctx = await client.post(
            f"{backend}/interview-contexts",
            headers=headers,
            json=ctx_body,
        )
        ctx.raise_for_status()
        context_id = ctx.json()["context_id"]
        print(f"context_id={context_id}")

        inv = await client.post(
            f"{backend}/interview-contexts/{context_id}/invitations",
            headers=headers,
            json={"candidate_id": candidate, "ttl_minutes": 20},
        )
        inv.raise_for_status()
        invitation = inv.json()["invitation_token"]
        print(f"invitation_ok len={len(invitation)}")

        sess = await client.post(
            f"{backend}/sessions/token",
            headers=headers,
            json={
                "product_id": "interviewer",
                "name": "E2E Candidate",
                "invitation_token": invitation,
            },
        )
        sess.raise_for_status()
        session = sess.json()
        session_id = session.get("session_id") or ""
        room_name = session.get("room") or session.get("room_name") or ""
        print(f"session_id={session_id}")
        print(f"room={room_name}")
        print(f"livekit_url={session.get('livekit_url')}")

    room = rtc.Room()
    agent_joined = asyncio.Event()
    agent_identity = ""

    @room.on("participant_connected")
    def _on_participant(participant: rtc.RemoteParticipant) -> None:
        nonlocal agent_identity
        if participant.identity != "E2E Candidate":
            agent_identity = participant.identity
            agent_joined.set()

    await room.connect(session["livekit_url"], session["token"])
    if room.remote_participants:
        for p in room.remote_participants.values():
            if p.identity != "E2E Candidate":
                agent_identity = p.identity
                agent_joined.set()
                break
    await asyncio.wait_for(agent_joined.wait(), timeout=45)
    print(f"agent_joined identity={agent_identity}")

    # Give the worker time to finish TTS preflight + greeting.
    await asyncio.sleep(25)

    # Inspect worker logs for this room/session.
    logs = subprocess.check_output(
        [
            "docker",
            "logs",
            "--since=3m",
            "voice-ai-platform-voice-agent-1",
        ],
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    interesting = [
        line
        for line in logs.splitlines()
        if any(
            token in line
            for token in (
                session_id,
                room_name,
                "tts_preflight_ok",
                "tts_preflight_failed",
                "opening_say_failed",
                "opening_stream_failed",
                "session_start",
                "stage2_question",
                "ERROR",
            )
        )
    ]
    joined = any("session_start" in line and room_name and room_name in line for line in interesting) or any(
        "session_start" in line for line in interesting[-40:]
    )
    tts_ok = any("tts_preflight_ok" in line for line in interesting)
    tts_fail = any("tts_preflight_failed" in line for line in interesting)
    opening_fail = any(
        token in line for line in interesting for token in ("opening_say_failed", "opening_stream_failed")
    )
    stage2 = any("stage2_question" in line for line in interesting)

    print(f"log_session_start={joined}")
    print(f"log_tts_preflight_ok={tts_ok}")
    print(f"log_tts_preflight_failed={tts_fail}")
    print(f"log_opening_failed={opening_fail}")
    print(f"log_stage2_question={stage2}")

    # Backend turn persistence
    turns_count = 0
    agent_turns = 0
    if session_id:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Internal status / turns endpoints vary; try common ones.
            for path in (
                f"/internal/interview-sessions/{session_id}",
                f"/internal/interview-sessions/{session_id}/status",
            ):
                resp = await client.get(f"{backend}{path}", headers=worker_headers)
                print(f"get {path} -> {resp.status_code}")
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, dict):
                        print("session_keys=", sorted(payload.keys())[:20])
                        turns = payload.get("turns") or payload.get("recent_turns") or []
                        if isinstance(turns, list):
                            turns_count = len(turns)
                            agent_turns = sum(
                                1
                                for t in turns
                                if isinstance(t, dict) and str(t.get("speaker") or "").lower() in {"agent", "interviewer"}
                            )
                    break

    await room.disconnect()

    ok = joined and tts_ok and not tts_fail and not opening_fail and stage2
    print(f"turns_count={turns_count} agent_turns={agent_turns}")
    print("RESULT=" + ("PASS" if ok else "FAIL"))
    if not ok:
        print("--- recent matching logs ---")
        for line in interesting[-30:]:
            print(line[:500])
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"RESULT=FAIL error={type(exc).__name__}: {exc}")
        raise
