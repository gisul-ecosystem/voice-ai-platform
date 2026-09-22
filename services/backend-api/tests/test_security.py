from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from security.auth import verify_service_token
from security.invitations import issue_invitation, verify_invitation


def test_service_auth_is_required_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "expected-secret")
    with pytest.raises(HTTPException) as missing:
        verify_service_token(None, "bff")
    assert missing.value.status_code == 401

    verify_service_token("Bearer expected-secret", "bff")


def test_production_fails_closed_without_service_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("VOICE_AGENT_SERVICE_TOKEN", raising=False)
    with pytest.raises(HTTPException) as unconfigured:
        verify_service_token(None, "worker")
    assert unconfigured.value.status_code == 503


def test_invitation_is_signed_and_expiring(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_INVITATION_SECRET", "x" * 32)
    token = issue_invitation(
        interview_id="interview-1",
        context_id="ctx_1234567890123456",
        candidate_id="candidate-1",
        expires_at=int(time.time()) + 60,
    )
    payload = verify_invitation(token)
    assert payload["context_id"] == "ctx_1234567890123456"

    with pytest.raises(HTTPException):
        verify_invitation(token + "tampered")


def test_expired_invitation_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("INTERVIEW_INVITATION_SECRET", "x" * 32)
    token = issue_invitation(
        interview_id="interview-1",
        context_id="ctx_1234567890123456",
        candidate_id="candidate-1",
        expires_at=int(time.time()) - 1,
    )
    with pytest.raises(HTTPException) as expired:
        verify_invitation(token)
    assert expired.value.status_code == 401
