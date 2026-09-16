"""Mint a LiveKit participant token and ensure the room has Stage 1 metadata.

aaptor_agent.py reads ctx.room.metadata JSON keys job_description and resume_text
(falling back to JOB_DESCRIPTION / RESUME_TEXT in .env). Optional inference
overrides: llm_provider, llm_api_key, stt_provider, stt_api_key, tts_provider,
tts_api_key. Omitted means the worker uses .env defaults. API keys are never printed.
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


def _optional_meta(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def build_room_metadata(
    *,
    job_description: str,
    resume_text: str,
    llm_provider: str | None = None,
    llm_api_key: str | None = None,
    stt_provider: str | None = None,
    stt_api_key: str | None = None,
    tts_provider: str | None = None,
    tts_api_key: str | None = None,
) -> dict:
    """Room JSON the agent reads. Omitted inference fields mean server .env defaults."""
    metadata = {"job_description": job_description, "resume_text": resume_text}
    extras = {
        "llm_provider": _optional_meta(llm_provider),
        "llm_api_key": _optional_meta(llm_api_key),
        "stt_provider": _optional_meta(stt_provider),
        "stt_api_key": _optional_meta(stt_api_key),
        "tts_provider": _optional_meta(tts_provider),
        "tts_api_key": _optional_meta(tts_api_key),
    }
    for key, value in extras.items():
        if value is not None:
            metadata[key] = value
    return metadata


def _log_safe_inference(metadata: dict) -> dict:
    # Client-provided keys must never land in log files or observability tooling.
    return {
        "llm_provider": metadata.get("llm_provider"),
        "stt_provider": metadata.get("stt_provider"),
        "tts_provider": metadata.get("tts_provider"),
        "llm_api_key_set": bool(metadata.get("llm_api_key")),
        "stt_api_key_set": bool(metadata.get("stt_api_key")),
        "tts_api_key_set": bool(metadata.get("tts_api_key")),
    }


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
    parser.add_argument("--room", default="", help="Room name (default: <agent>-test-<id>)")
    parser.add_argument(
        "--agent-name",
        default="aaptor",
        help="Named LiveKit worker to dispatch (aaptor or racko). Default aaptor.",
    )
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
    parser.add_argument("--llm-provider", default=None)
    parser.add_argument("--llm-api-key", default=None)
    parser.add_argument("--stt-provider", default=None)
    parser.add_argument("--stt-api-key", default=None)
    parser.add_argument("--tts-provider", default=None)
    parser.add_argument("--tts-api-key", default=None)
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
    agent_name: str,
) -> None:
    lk = api.LiveKitAPI(_http_url(ws_url), api_key, api_secret)
    try:
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    metadata=metadata,
                    max_participants=max_participants,
                    agents=[api.RoomAgentDispatch(agent_name=agent_name)],
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
    agent_name: str,
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
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=agent_name)])
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

    metadata = json.dumps(
        build_room_metadata(
            job_description=jd,
            resume_text=resume,
            llm_provider=args.llm_provider,
            llm_api_key=args.llm_api_key,
            stt_provider=args.stt_provider,
            stt_api_key=args.stt_api_key,
            tts_provider=args.tts_provider,
            tts_api_key=args.tts_api_key,
        )
    )
    agent_name = (args.agent_name or "aaptor").strip() or "aaptor"
    room_name = args.room or f"{agent_name}-test-{uuid.uuid4().hex[:8]}"
    max_participants = int(os.getenv("LIVEKIT_ROOM_CAPACITY", "5"))

    if not args.skip_create_room:
        await _ensure_room(
            ws_url,
            api_key,
            api_secret,
            room_name,
            metadata,
            max_participants,
            agent_name,
        )

    token = _build_token(
        api_key=api_key,
        api_secret=api_secret,
        room_name=room_name,
        identity=args.identity,
        name=args.name,
        ttl_minutes=args.ttl_minutes,
        agent_name=agent_name,
    )

    print(f"LIVEKIT_URL={ws_url}")
    print(f"ROOM={room_name}")
    print(f"AGENT_NAME={agent_name}")
    print(f"TTL_MINUTES={args.ttl_minutes}")
    print(f"TOKEN={token}")
    print()
    print("Stage 1 room metadata keys: job_description, resume_text")
    print(f"  job_description chars: {len(jd)}")
    print(f"  resume_text chars: {len(resume)}")
    inferred = _log_safe_inference(json.loads(metadata))
    print("Inference overrides (omitted = server .env defaults):")
    print(f"  llm_provider={inferred['llm_provider']}")
    print(f"  stt_provider={inferred['stt_provider']}")
    print(f"  tts_provider={inferred['tts_provider']}")
    print(f"  llm_api_key_set={inferred['llm_api_key_set']}")
    print(f"  stt_api_key_set={inferred['stt_api_key_set']}")
    print(f"  tts_api_key_set={inferred['tts_api_key_set']}")
    print()
    print("The integrated browser harness creates its own room and token through backend-api.")
    print("For the normal test flow, open http://127.0.0.1:8765/index.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
