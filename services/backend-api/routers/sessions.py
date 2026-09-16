"""Create a LiveKit room and dispatch a registered voice product.

The browser sends a public product ID. Worker names, provider policy, and all
credentials are resolved server-side. Legacy callers may still pass agent_name
and provider names, but never raw provider credentials.
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
from products.registry import ProductProfile, resolve_product

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


def _room_metadata(req: CreateSessionRequest, product: ProductProfile) -> dict:
    metadata: dict = {
        "product_id": product.product_id,
        "provider_policy_id": product.provider_policy_id,
        **product.provider_selection(),
    }
    jd = _optional(req.job_description)
    resume = _optional(req.resume_text)
    if jd:
        metadata["job_description"] = jd
    if resume:
        metadata["resume_text"] = resume
    extras = {
        "llm_provider": _optional(req.llm_provider),
        "stt_provider": _optional(req.stt_provider),
        "tts_provider": _optional(req.tts_provider),
    }
    for key, value in extras.items():
        if value is not None:
            metadata[key] = value
    return metadata


def _log_safe_inference(metadata: dict) -> dict:
    return {
        "provider_policy_id": metadata.get("provider_policy_id"),
        "llm_provider": metadata.get("llm_provider"),
        "stt_provider": metadata.get("stt_provider"),
        "tts_provider": metadata.get("tts_provider"),
    }


@router.post("/token", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    try:
        product = resolve_product(req.product_id, req.agent_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ws_url = _ws_url()
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    if not ws_url or not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail="LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET must be set",
        )

    room_name = _optional(req.room) or f"session-{uuid.uuid4().hex[:8]}"
    agent_name = product.agent_name
    ttl = req.ttl_minutes or max(int(os.getenv("LIVEKIT_TOKEN_TTL_MINUTES", "2")), 30)
    max_participants = int(os.getenv("LIVEKIT_ROOM_CAPACITY", "5"))
    metadata = _room_metadata(req, product)
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
            "product_id": product.product_id,
            "agent_name": agent_name,
            **safe,
        },
    )
    return CreateSessionResponse(
        room=room_name,
        token=token,
        livekit_url=ws_url,
        product_id=product.product_id,
        llm_provider=safe["llm_provider"],
        stt_provider=safe["stt_provider"],
        tts_provider=safe["tts_provider"],
    )
