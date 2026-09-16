from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.schemas import CreateSessionRequest
from routers import sessions


class FakeRoomService:
    def __init__(self) -> None:
        self.created = []

    async def create_room(self, request) -> None:
        self.created.append(request)

    async def update_room_metadata(self, request) -> None:
        raise AssertionError("unique test rooms must not need metadata updates")


class FakeLiveKitApi:
    room_service = FakeRoomService()

    def __init__(self, *_args) -> None:
        self.room = self.room_service

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", ["aaptor", "racko"])
async def test_session_dispatches_only_supported_workers(
    monkeypatch, agent_name: str
) -> None:
    FakeLiveKitApi.room_service = FakeRoomService()
    monkeypatch.setattr(sessions.api, "LiveKitAPI", FakeLiveKitApi)
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)

    request = CreateSessionRequest(
        identity=f"{agent_name}-participant",
        name="Test Participant",
        agent_name=agent_name,
        job_description="Python role" if agent_name == "aaptor" else None,
        resume_text="Python experience" if agent_name == "aaptor" else None,
    )
    response = await sessions.create_session(request)

    created = FakeLiveKitApi.room_service.created[0]
    metadata = json.loads(created.metadata)
    assert created.agents[0].agent_name == agent_name
    assert response.room.startswith("session-")
    assert response.token
    assert response.product_id == (
        "interviewer" if agent_name == "aaptor" else "customer-support"
    )
    if agent_name == "racko":
        assert "job_description" not in metadata
        assert "resume_text" not in metadata


def test_unknown_worker_is_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        CreateSessionRequest(agent_name="unknown")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_id", "agent_name"),
    [("interviewer", "aaptor"), ("customer-support", "racko")],
)
async def test_public_products_map_to_private_workers(
    monkeypatch, product_id: str, agent_name: str
) -> None:
    FakeLiveKitApi.room_service = FakeRoomService()
    monkeypatch.setattr(sessions.api, "LiveKitAPI", FakeLiveKitApi)
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)

    response = await sessions.create_session(
        CreateSessionRequest(product_id=product_id, identity="web-user", name="Web User")
    )

    created = FakeLiveKitApi.room_service.created[0]
    metadata = json.loads(created.metadata)
    assert created.agents[0].agent_name == agent_name
    assert metadata["product_id"] == product_id
    assert "provider_policy_id" in metadata
    assert response.product_id == product_id


@pytest.mark.asyncio
async def test_unknown_or_conflicting_product_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)

    with pytest.raises(HTTPException) as unknown:
        await sessions.create_session(CreateSessionRequest(product_id="unknown"))
    assert unknown.value.status_code == 422

    with pytest.raises(HTTPException) as conflict:
        await sessions.create_session(
            CreateSessionRequest(product_id="interviewer", agent_name="racko")
        )
    assert conflict.value.status_code == 422


def test_public_session_schema_rejects_provider_credentials() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(
            product_id="interviewer",
            llm_api_key="must-not-enter-public-session-contract",
        )
