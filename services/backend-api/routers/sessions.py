"""Create a LiveKit room + participant token, including optional inference overrides.

Omitted llm_provider / *_api_key fields mean the agent uses server .env defaults.
API keys are written only into room metadata for the worker; they are never logged.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from livekit import api

from models.schemas import CreateSessionRequest, CreateSessionResponse

logger = logging.getLogger("backend-api.sessions")

router = APIRouter(prefix="/sessions", tags=["sessions"])


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


def _optional(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _room_metadata(req: CreateSessionRequest) -> dict:
    metadata: dict = {}
    jd = _optional(req.job_description)
    resume = _optional(req.resume_text)
    if jd:
        metadata["job_description"] = jd
    if resume:
        metadata["resume_text"] = resume
    extras = {
        "llm_provider": _optional(req.llm_provider),
        "llm_api_key": _optional(req.llm_api_key),
        "stt_provider": _optional(req.stt_provider),
        "stt_api_key": _optional(req.stt_api_key),
        "tts_provider": _optional(req.tts_provider),
        "tts_api_key": _optional(req.tts_api_key),
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


@router.post("/token", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    ws_url = _ws_url()
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    if not ws_url or not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail="LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET must be set",
        )

    room_name = _optional(req.room) or f"session-{uuid.uuid4().hex[:8]}"
    agent_name = req.agent_name
    ttl = req.ttl_minutes or max(int(os.getenv("LIVEKIT_TOKEN_TTL_MINUTES", "2")), 30)
    max_participants = int(os.getenv("LIVEKIT_ROOM_CAPACITY", "5"))
    metadata = _room_metadata(req)
    metadata_json = json.dumps(metadata)

    lk = api.LiveKitAPI(_http_url(ws_url), api_key, api_secret)
    try:
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    metadata=metadata_json,
                    max_participants=max_participants,
                    agents=[api.RoomAgentDispatch(agent_name=agent_name)],
                )
            )
        except api.TwirpError as exc:
            if exc.code != "already_exists":
                logger.error(
                    "livekit_room_create_failed",
                    extra={
                        "event": "livekit_room_create_failed",
                        "room": room_name,
                        "error_code": exc.code,
                        "status": exc.status,
                    },
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"LiveKit could not create the interview room ({exc.code})",
                ) from exc
            await lk.room.update_room_metadata(
                api.UpdateRoomMetadataRequest(room=room_name, metadata=metadata_json)
            )
    finally:
        await lk.aclose()

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(req.identity)
        .with_name(req.name)
        .with_ttl(timedelta(minutes=ttl))
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

    safe = _log_safe_inference(metadata)
    logger.info(
        "session_created",
        extra={
            "event": "session_created",
            "room": room_name,
            "agent_name": agent_name,
            **safe,
        },
    )
    return CreateSessionResponse(
        room=room_name,
        token=token,
        livekit_url=ws_url,
        llm_provider=safe["llm_provider"],
        stt_provider=safe["stt_provider"],
        tts_provider=safe["tts_provider"],
        llm_api_key_set=safe["llm_api_key_set"],
        stt_api_key_set=safe["stt_api_key_set"],
        tts_api_key_set=safe["tts_api_key_set"],
    )
