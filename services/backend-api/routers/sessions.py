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

from fastapi import APIRouter, Depends, HTTPException
from livekit import api

from db import interviews
from models.schemas import CreateSessionRequest, CreateSessionResponse
from observability import get_correlation_id
from products.registry import ProductProfile, resolve_product
from security.auth import require_bff_service
from security.invitations import verify_invitation
from security.rate_limit import require_capacity

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


def _room_metadata(
    *,
    product: ProductProfile,
    session_id: str,
    context_id: str | None,
    definition_id: str | None,
    correlation_id: str,
) -> dict:
    metadata: dict = {
        "product_id": product.product_id,
        "provider_policy_id": product.provider_policy_id,
        "session_id": session_id,
        "correlation_id": correlation_id,
        **product.provider_selection(),
    }
    if context_id:
        metadata["context_id"] = context_id
    if definition_id:
        metadata["definition_id"] = definition_id
    return metadata


def _log_safe_inference(metadata: dict) -> dict:
    return {
        "provider_policy_id": metadata.get("provider_policy_id"),
        "llm_provider": metadata.get("llm_provider"),
        "stt_provider": metadata.get("stt_provider"),
        "tts_provider": metadata.get("tts_provider"),
    }


@router.post(
    "/token",
    response_model=CreateSessionResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    try:
        product = resolve_product(req.product_id, None)
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

    invitation = (
        verify_invitation(req.invitation_token) if req.invitation_token else None
    )
    environment = (os.getenv("APP_ENV") or "development").strip().lower()
    if environment in {"production", "staging"} and invitation is None:
        raise HTTPException(status_code=401, detail="Interview invitation is required")

    context_id = req.context_id
    invitation_id: str | None = None
    existing_session: dict | None = None
    reservation_id: str | None = None
    if invitation:
        invited_context = invitation["context_id"]
        if context_id and context_id != invited_context:
            raise HTTPException(status_code=403, detail="Interview context mismatch")
        invitation_id = invitation["jti"]
        scheduled = await interviews.get_scheduled_interview_by_invitation(
            invitation_id
        )
        if scheduled:
            if not req.idempotency_key:
                raise HTTPException(
                    status_code=422,
                    detail="idempotency_key is required for scheduled interviews",
                )
            allowed = await interviews.validate_join_window(invitation_id)
            if allowed is None:
                raise HTTPException(
                    status_code=403,
                    detail="Interview is outside its join window or consent is incomplete",
                )
            existing_session = await interviews.get_session_for_join(
                invitation_id, req.idempotency_key
            )
        if existing_session is None:
            reservation_id = f"ses_{uuid.uuid4().hex}"
            if not await interviews.reserve_invitation(
                invitation_id, reservation_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Interview invitation was already used or expired",
                )
        context_id = invited_context
        candidate_id = invitation["candidate_id"]
    else:
        candidate_id = f"candidate_{uuid.uuid4().hex[:16]}"

    if product.product_id == "interviewer" and not context_id:
        raise HTTPException(status_code=422, detail="Interview context is required")

    definition_id = None
    if context_id:
        context = await interviews.get_context(context_id)
        if context:
            raw_definition_id = context.get("definition_id")
            if isinstance(raw_definition_id, str) and raw_definition_id.strip():
                definition_id = raw_definition_id.strip()

    room_name = (
        str(existing_session["room"])
        if existing_session
        else f"interview-{uuid.uuid4().hex}"
    )
    agent_name = product.agent_name
    ttl = max(5, min(int(os.getenv("LIVEKIT_TOKEN_TTL_MINUTES", "45")), 60))
    max_participants = max(2, min(int(os.getenv("LIVEKIT_ROOM_CAPACITY", "2")), 3))
    expires_at = interviews.utc_now() + timedelta(minutes=ttl)
    correlation_id = get_correlation_id()
    if existing_session:
        session_id = str(existing_session["_id"])
    else:
        try:
            session_id = await interviews.create_live_session(
                product_id=product.product_id,
                context_id=context_id,
                candidate_id=candidate_id,
                room=room_name,
                correlation_id=correlation_id,
                expires_at=expires_at,
                session_id=reservation_id,
                invitation_id=invitation_id,
                idempotency_key=req.idempotency_key,
            )
        except Exception as exc:
            if invitation_id and reservation_id:
                await interviews.release_invitation(invitation_id, reservation_id)
            raise HTTPException(
                status_code=503,
                detail="Interview session persistence is temporarily unavailable",
            ) from exc
    metadata = _room_metadata(
        product=product,
        session_id=session_id,
        context_id=context_id,
        definition_id=definition_id,
        correlation_id=correlation_id,
    )
    metadata_json = json.dumps(metadata)

    lk = api.LiveKitAPI(_http_url(ws_url), api_key, api_secret)
    try:
        try:
            if existing_session is None:
                # Single dispatch path only. Creating the room with
                # RoomAgentDispatch *and* calling create_dispatch (and/or putting
                # agents on the participant token) can start two workers in one
                # room — the candidate hears the opening twice.
                await lk.room.create_room(
                    api.CreateRoomRequest(
                        name=room_name,
                        metadata=metadata_json,
                        max_participants=max_participants,
                    )
                )
                dispatch = await lk.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        room=room_name,
                        agent_name=agent_name,
                        metadata=metadata_json,
                    )
                )
                logger.info(
                    "livekit_agent_dispatched",
                    extra={
                        "event": "livekit_agent_dispatched",
                        "room": room_name,
                        "agent_name": agent_name,
                        "session_id": session_id,
                        "dispatch_id": getattr(dispatch, "id", None),
                        "correlation_id": correlation_id,
                    },
                )
                if (
                    invitation_id
                    and reservation_id
                    and not await interviews.commit_invitation(
                        invitation_id, reservation_id
                    )
                ):
                    try:
                        await lk.room.delete_room(
                            api.DeleteRoomRequest(room=room_name)
                        )
                    except Exception:
                        logger.exception(
                            "livekit_room_cleanup_failed",
                            extra={
                                "event": "livekit_room_cleanup_failed",
                                "room": room_name,
                                "session_id": session_id,
                            },
                        )
                    await interviews.release_invitation(
                        invitation_id, reservation_id
                    )
                    await interviews.transition_session(
                        session_id,
                        expected=("joining",),
                        status="failed",
                        reason="invitation_commit_failed",
                    )
                    raise HTTPException(
                        status_code=409,
                        detail="Interview invitation could not be committed",
                    )
        except api.TwirpError as exc:
            if existing_session is None:
                try:
                    await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
                except Exception:
                    logger.warning(
                        "livekit_room_cleanup_skipped",
                        extra={
                            "event": "livekit_room_cleanup_skipped",
                            "room": room_name,
                            "session_id": session_id,
                        },
                    )
            if invitation_id and reservation_id:
                await interviews.release_invitation(invitation_id, reservation_id)
            await interviews.transition_session(
                session_id,
                expected=("joining",),
                status="failed",
                reason=f"livekit_{exc.code}",
            )
            logger.error(
                "livekit_room_create_failed",
                extra={
                    "event": "livekit_room_create_failed",
                    "room": room_name,
                    "error_code": exc.code,
                    "status": exc.status,
                    "correlation_id": correlation_id,
                },
            )
            raise HTTPException(
                status_code=502,
                detail=f"LiveKit could not create the interview room ({exc.code})",
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            if existing_session is None:
                try:
                    await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
                except Exception:
                    logger.exception(
                        "livekit_room_cleanup_failed",
                        extra={
                            "event": "livekit_room_cleanup_failed",
                            "room": room_name,
                            "session_id": session_id,
                        },
                    )
            if invitation_id and reservation_id:
                await interviews.release_invitation(invitation_id, reservation_id)
            await interviews.transition_session(
                session_id,
                expected=("joining",),
                status="failed",
                reason="livekit_transport_error",
            )
            raise HTTPException(
                status_code=502,
                detail="LiveKit could not prepare the interview room",
            ) from exc
    finally:
        await lk.aclose()

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(candidate_id)
        .with_name(req.name)
        .with_ttl(timedelta(minutes=ttl))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
            )
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
            "session_id": session_id,
            "correlation_id": correlation_id,
            **safe,
        },
    )
    return CreateSessionResponse(
        room=room_name,
        token=token,
        livekit_url=ws_url,
        product_id=product.product_id,
        session_id=session_id,
        expires_at=expires_at,
    )
