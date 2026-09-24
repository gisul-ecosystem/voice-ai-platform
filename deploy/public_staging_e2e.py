#!/usr/bin/env python3
"""Public staging E2E via template invite path (no VM secrets)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from livekit import rtc

BASE = "https://interviewer-dev.gisul.ai"


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0, follow_redirects=True) as client:
        health = await client.get("/api/health")
        print(f"health={health.status_code}")
        health.raise_for_status()

        defs = await client.get("/api/admin/definitions")
        print(f"definitions={defs.status_code}")
        defs.raise_for_status()
        items = defs.json().get("items") or []
        if not items:
            raise RuntimeError("no published definitions on staging")
        definition = items[0]
        definition_id = definition["definition_id"]
        print(f"definition_id={definition_id}")

        email = f"e2e_{uuid.uuid4().hex[:10]}@example.com"
        cand = await client.post(
            "/api/admin/candidates",
            json={"name": "E2E Candidate", "email": email},
        )
        print(f"candidate={cand.status_code}")
        if cand.status_code >= 400:
            print(cand.text[:400])
            cand.raise_for_status()
        candidate_id = cand.json().get("candidate_id") or cand.json().get("id")
        print(f"candidate_id={candidate_id}")

        resume_bytes = (
            b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
            b"E2E Candidate resume. Backend engineer. FastAPI, Redis, React."
        )
        upload = await client.post(
            f"/api/admin/candidates/{candidate_id}/resume",
            files={"file": ("e2e_resume.pdf", resume_bytes, "application/pdf")},
        )
        print(f"resume_upload={upload.status_code}")
        if upload.status_code >= 400:
            print(upload.text[:400])
            # Fall back to a plain text CV if PDF validation is strict.
            upload = await client.post(
                f"/api/admin/candidates/{candidate_id}/resume",
                files={
                    "file": (
                        "e2e_resume.txt",
                        (
                            "E2E Candidate\nBackend engineer\n"
                            "FastAPI microservices, async Python, Redis, React\n"
                        ).encode(),
                        "text/plain",
                    )
                },
            )
            print(f"resume_upload_txt={upload.status_code}")
            if upload.status_code >= 400:
                print(upload.text[:400])
                upload.raise_for_status()

        starts = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        competencies = definition.get("competencies") or ["Role expertise", "Problem solving"]
        if isinstance(competencies, list):
            competencies = [str(c) for c in competencies if str(c).strip()][:6]
        schedule = await client.post(
            "/api/interviews",
            json={
                "candidateId": candidate_id,
                "definitionId": definition_id,
                "candidateName": "E2E Candidate",
                "candidateEmail": email,
                "startsAt": starts,
                "joinEarlyMinutes": 0,
                "lateGraceMinutes": 43200,
                "timezone": "UTC",
                "jobDescription": definition.get("job_description")
                or "Python backend engineer role.",
                "resumeText": (
                    "E2E Candidate — backend engineer. Built FastAPI services, "
                    "async Python, Redis queues, and React dashboards."
                ),
                "interviewSetup": {
                    "title": definition.get("title") or "E2E Interview",
                    "role": definition.get("role") or "Engineer",
                    "seniority": definition.get("seniority") or "mid",
                    "difficulty": "applied",
                    "durationMinutes": int(definition.get("duration_minutes") or 15),
                    "language": "English",
                    "competencies": competencies or ["Role expertise"],
                    "maxProbesPerPhase": 1,
                    "monitoringEnabled": False,
                    "recordingEnabled": False,
                },
            },
        )
        print(f"schedule={schedule.status_code}")
        if schedule.status_code >= 400:
            print(schedule.text[:500])
            schedule.raise_for_status()
        invite = schedule.json()
        token = invite["invitationToken"]
        interview_id = invite.get("interviewId")
        print(f"interview_id={interview_id}")
        print(f"candidate_path={invite.get('candidatePath')}")

        # Consent preview (best-effort)
        preview = await client.post(
            "/api/invitations",
            json={"invitationToken": token},
        )
        print(f"invite_preview={preview.status_code}")
        consent = await client.post(
            "/api/invitations",
            json={
                "invitationToken": token,
                "consent": {
                    "ai_interview": True,
                    "transcription": True,
                    "monitoring": False,
                    "recording": False,
                },
            },
        )
        print(f"invite_consent={consent.status_code}")

        sess = await client.post(
            "/api/sessions",
            json={
                "productId": "interviewer",
                "participantName": "E2E Candidate",
                "invitationToken": token,
                "idempotencyKey": f"e2e-{uuid.uuid4().hex}",
            },
        )
        print(f"session={sess.status_code}")
        if sess.status_code >= 400:
            print(sess.text[:500])
            sess.raise_for_status()
        session = sess.json()
        session_id = session.get("sessionId") or ""
        livekit_url = session["livekitUrl"]
        lk_token = session["token"]
        print(f"session_id={session_id}")
        print(f"livekit_url={livekit_url}")

    room = rtc.Room()
    agent_joined = asyncio.Event()
    agent_spoke = asyncio.Event()
    agent_identity = ""
    audio_frames = 0

    @room.on("participant_connected")
    def _on_participant(participant: rtc.RemoteParticipant) -> None:
        nonlocal agent_identity
        if participant.identity != "E2E Candidate":
            agent_identity = participant.identity
            agent_joined.set()

    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity != "E2E Candidate":
            agent_spoke.set()

            async def _count() -> None:
                nonlocal audio_frames
                stream = rtc.AudioStream(track)
                async for _event in stream:
                    audio_frames += 1
                    if audio_frames >= 8:
                        break

            asyncio.create_task(_count())

    await room.connect(livekit_url, lk_token)
    if room.remote_participants:
        for p in room.remote_participants.values():
            if p.identity != "E2E Candidate":
                agent_identity = p.identity
                agent_joined.set()
                break
    await asyncio.wait_for(agent_joined.wait(), timeout=45)
    print(f"agent_joined identity={agent_identity}")

    try:
        await asyncio.wait_for(agent_spoke.wait(), timeout=45)
        print("agent_audio_track=yes")
    except asyncio.TimeoutError:
        print("agent_audio_track=no")

    await asyncio.sleep(25)
    print(f"audio_frames_sampled={audio_frames}")

    transcript_ok = False
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0, follow_redirects=True) as client:
        if session_id:
            for path in (
                f"/api/sessions/{session_id}/transcript",
                f"/api/sessions/{session_id}/status",
            ):
                resp = await client.get(path)
                print(f"get {path} -> {resp.status_code}")
                if resp.status_code == 200:
                    payload = resp.json()
                    preview = json.dumps(payload)[:500]
                    print(f"payload_preview={preview}")
                    blob = json.dumps(payload).lower()
                    if any(
                        k in blob
                        for k in (
                            "hello",
                            "welcome",
                            "interview",
                            "tell me",
                            "agent",
                            "turn",
                            "question",
                        )
                    ):
                        transcript_ok = True

    await room.disconnect()
    ok = bool(agent_identity) and (agent_spoke.is_set() or audio_frames > 0 or transcript_ok)
    print(f"RESULT={'PASS' if ok else 'FAIL'}")
    print(
        json.dumps(
            {
                "session_id": session_id,
                "interview_id": interview_id,
                "definition_id": definition_id,
                "agent_identity": agent_identity,
                "audio": agent_spoke.is_set(),
                "audio_frames": audio_frames,
                "transcript_ok": transcript_ok,
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"RESULT=FAIL error={type(exc).__name__}: {exc}")
        raise
