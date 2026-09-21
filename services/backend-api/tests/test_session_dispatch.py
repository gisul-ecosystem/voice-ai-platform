from __future__ import annotations

import json

import pytest
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


class FakeAgentDispatchService:
    def __init__(self) -> None:
        self.created = []

    async def create_dispatch(self, request):
        self.created.append(request)
        return type("FakeDispatch", (), {"id": "AD_test"})()


class FakeLiveKitApi:
    room_service = FakeRoomService()
    dispatch_service = FakeAgentDispatchService()

    def __init__(self, *_args) -> None:
        self.room = self.room_service
        self.agent_dispatch = self.dispatch_service

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_name", ["aaptor", "racko"])
async def test_session_dispatches_only_supported_workers(
    monkeypatch, agent_name: str
) -> None:
    FakeLiveKitApi.room_service = FakeRoomService()
    FakeLiveKitApi.dispatch_service = FakeAgentDispatchService()
    monkeypatch.setattr(sessions.api, "LiveKitAPI", FakeLiveKitApi)
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)
    monkeypatch.setattr(
        sessions.interviews,
        "create_live_session",
        _fake_create_live_session,
    )
    monkeypatch.setattr(
        sessions.interviews,
        "get_context",
        _fake_get_context,
    )

    request = CreateSessionRequest(
        name="Test Participant",
        product_id="interviewer" if agent_name == "aaptor" else "customer-support",
        context_id="ctx_1234567890123456" if agent_name == "aaptor" else None,
    )
    response = await sessions.create_session(request)

    created = FakeLiveKitApi.room_service.created[0]
    metadata = json.loads(created.metadata)
    dispatch = FakeLiveKitApi.dispatch_service.created[0]
    assert dispatch.agent_name == agent_name
    assert list(created.agents)[0].agent_name == agent_name
    assert response.room.startswith("interview-")
    assert response.token
    assert response.session_id == "ses_test"
    assert response.product_id == (
        "interviewer" if agent_name == "aaptor" else "customer-support"
    )
    assert "job_description" not in metadata
    assert "resume_text" not in metadata
    assert "session_id" in metadata


@pytest.mark.asyncio
async def test_session_metadata_includes_published_definition(monkeypatch) -> None:
    FakeLiveKitApi.room_service = FakeRoomService()
    FakeLiveKitApi.dispatch_service = FakeAgentDispatchService()
    monkeypatch.setattr(sessions.api, "LiveKitAPI", FakeLiveKitApi)
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)
    monkeypatch.setattr(sessions.interviews, "create_live_session", _fake_create_live_session)
    monkeypatch.setattr(
        sessions.interviews,
        "get_context",
        _fake_get_context_with_definition,
    )

    await sessions.create_session(
        CreateSessionRequest(
            name="Test Candidate",
            product_id="interviewer",
            context_id="ctx_1234567890123456",
        )
    )

    metadata = json.loads(FakeLiveKitApi.room_service.created[0].metadata)
    assert metadata["definition_id"] == "ai-engineer-junior-v1"


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
    FakeLiveKitApi.dispatch_service = FakeAgentDispatchService()
    monkeypatch.setattr(sessions.api, "LiveKitAPI", FakeLiveKitApi)
    monkeypatch.setattr(sessions, "_ws_url", lambda: "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 32)
    monkeypatch.setattr(
        sessions.interviews,
        "create_live_session",
        _fake_create_live_session,
    )
    monkeypatch.setattr(
        sessions.interviews,
        "get_context",
        _fake_get_context,
    )

    response = await sessions.create_session(
        CreateSessionRequest(
            product_id=product_id,
            name="Web User",
            context_id="ctx_1234567890123456"
            if product_id == "interviewer"
            else None,
        )
    )

    created = FakeLiveKitApi.room_service.created[0]
    metadata = json.loads(created.metadata)
    assert FakeLiveKitApi.dispatch_service.created[0].agent_name == agent_name
    assert list(created.agents)[0].agent_name == agent_name
    assert metadata["product_id"] == product_id
    assert "provider_policy_id" in metadata
    assert response.product_id == product_id


def test_livekit_agent_name_env_overrides_interviewer_worker(monkeypatch) -> None:
    from products.registry import resolve_product

    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "aaptor-staging")
    profile = resolve_product("interviewer", None)
    assert profile.agent_name == "aaptor-staging"
    # Legacy callers may still pass default worker name with product_id.
    assert resolve_product("interviewer", "aaptor").agent_name == "aaptor-staging"


def test_unknown_product_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(product_id="unknown")


def test_public_session_schema_rejects_provider_credentials() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(
            product_id="interviewer",
            llm_api_key="must-not-enter-public-session-contract",
        )


async def _fake_create_live_session(**_kwargs) -> str:
    return "ses_test"


async def _fake_get_context(_context_id: str) -> dict:
    return {}


async def _fake_get_context_with_definition(_context_id: str) -> dict:
    return {"definition_id": "ai-engineer-junior-v1"}
