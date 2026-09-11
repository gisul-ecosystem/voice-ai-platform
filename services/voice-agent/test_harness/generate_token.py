"""Mint a LiveKit participant token and ensure the room has Stage 1 metadata.

aaptor_agent.py reads ctx.room.metadata JSON keys job_description and resume_text
(falling back to JOB_DESCRIPTION / RESUME_TEXT in .env).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
from livekit import api

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_JD = (
    "Backend engineer (Python). 4+ years. FastAPI, distributed systems, "
    "ownership of production services. Comfortable with async I/O and LAN/HTTP "
    "service boundaries."
)
DEFAULT_RESUME = (
    "Priya N. 5 years backend. Led a monolith-to-services migration. "
    "Python, FastAPI, PostgreSQL, Redis. Mentored two juniors. "
    "On-call for a payments API."
)

SAMPLE_JD_PATH = Path(__file__).with_name("sample_jd.txt")
SAMPLE_RESUME_PATH = Path(__file__).with_name("sample_resume.txt")


def _agent_name() -> str:
    return os.getenv("LIVEKIT_AGENT_NAME", "aaptor")


def _ws_url() -> str:
    return (
        os.getenv("LIVEKIT_URL")
        or os.getenv("LIVEKIT_WS_URL")
        or os.getenv("LIVEKIT_SERVER_URL")
        or ""
    ).rstrip("/")


def _http_url(ws_url: str) -> str:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :]
    return ws_url


def _read_text(path: Path | None, fallback: str) -> str:
    if path is None:
        return fallback
    return path.read_text(encoding="utf-8").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a LiveKit test-participant token")
    parser.add_argument("--room", default="", help="Room name (default: aaptor-test-<id>)")
    parser.add_argument("--identity", default="test-candidate")
    parser.add_argument("--name", default="Test Candidate")
    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=max(int(os.getenv("LIVEKIT_TOKEN_TTL_MINUTES", "2")), 30),
        help="Token TTL. Default is max(LIVEKIT_TOKEN_TTL_MINUTES, 30) so a test call is not 2 minutes.",
    )
    parser.add_argument("--job-description", default=os.getenv("JOB_DESCRIPTION", "").strip())
    parser.add_argument("--resume-text", default=os.getenv("RESUME_TEXT", "").strip())
    parser.add_argument("--job-file", type=Path, default=None)
    parser.add_argument("--resume-file", type=Path, default=None)
    parser.add_argument(
        "--skip-create-room",
        action="store_true",
        help="Only mint a token; do not create/update the room via the LiveKit API.",
    )
    return parser.parse_args()


async def _ensure_room(
    ws_url: str,
    api_key: str,
    api_secret: str,
    room_name: str,
    metadata: str,
    max_participants: int,
) -> None:
    lk = api.LiveKitAPI(_http_url(ws_url), api_key, api_secret)
    try:
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    metadata=metadata,
                    max_participants=max_participants,
                    agents=[api.RoomAgentDispatch(agent_name=_agent_name())],
                )
            )
        except api.TwirpError:
            await lk.room.update_room_metadata(
                api.UpdateRoomMetadataRequest(room=room_name, metadata=metadata)
            )
    finally:
        await lk.aclose()


def _build_token(
    *,
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
    name: str,
    ttl_minutes: int,
) -> str:
    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=_agent_name())])
        )
        .to_jwt()
    )


async def main() -> int:
    args = _parse_args()
    ws_url = _ws_url()
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    if not ws_url or not api_key or not api_secret:
        print(
            "LIVEKIT_URL (or LIVEKIT_WS_URL) / LIVEKIT_API_KEY / LIVEKIT_API_SECRET "
            "must be set in services/voice-agent/.env",
            file=sys.stderr,
        )
        return 1

    jd = args.job_description
    resume = args.resume_text
    if args.job_file:
        jd = _read_text(args.job_file, jd)
    if args.resume_file:
        resume = _read_text(args.resume_file, resume)
    if not jd:
        jd = _read_text(SAMPLE_JD_PATH if SAMPLE_JD_PATH.exists() else None, DEFAULT_JD)
    if not resume:
        resume = _read_text(
            SAMPLE_RESUME_PATH if SAMPLE_RESUME_PATH.exists() else None, DEFAULT_RESUME
        )

    metadata = json.dumps({"job_description": jd, "resume_text": resume})
    room_name = args.room or f"aaptor-test-{uuid.uuid4().hex[:8]}"
    max_participants = int(os.getenv("LIVEKIT_ROOM_CAPACITY", "5"))

    if not args.skip_create_room:
        await _ensure_room(ws_url, api_key, api_secret, room_name, metadata, max_participants)

    token = _build_token(
        api_key=api_key,
        api_secret=api_secret,
        room_name=room_name,
        identity=args.identity,
        name=args.name,
        ttl_minutes=args.ttl_minutes,
    )
    join_qs = urlencode({"url": ws_url, "token": token}, quote_via=quote)
    join_url = f"http://127.0.0.1:8765/index.html?{join_qs}"
    open_path = Path(__file__).with_name("open.html")
    open_path.write_text(
        '<!DOCTYPE html><meta charset="utf-8" />'
        f'<meta http-equiv="refresh" content="0;url=index.html?{join_qs}" />'
        "<p>Redirecting to the test room… "
        f'<a href="index.html?{join_qs}">open index.html</a></p>\n',
        encoding="utf-8",
    )

    print(f"LIVEKIT_URL={ws_url}")
    print(f"ROOM={room_name}")
    print(f"TTL_MINUTES={args.ttl_minutes}")
    print(f"TOKEN={token}")
    print()
    print("Stage 1 room metadata keys: job_description, resume_text")
    print(f"  job_description chars: {len(jd)}")
    print(f"  resume_text chars: {len(resume)}")
    print()
    print("Open the harness (http.server must be running in this folder):")
    print("  python -m http.server 8765")
    print("  http://127.0.0.1:8765/open.html")
    print("Or paste LIVEKIT_URL + TOKEN into http://127.0.0.1:8765/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
