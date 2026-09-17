import pytest

import main


REQUIRED = (
    "MONGO_URL",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "BACKEND_SERVICE_TOKEN",
    "VOICE_AGENT_SERVICE_TOKEN",
    "INTERVIEW_INVITATION_SECRET",
    "OPENAI_API_KEY",
)


def test_development_allows_missing_production_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)

    main.validate_startup_configuration()


def test_production_rejects_missing_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="BACKEND_SERVICE_TOKEN"):
        main.validate_startup_configuration()


def test_production_accepts_complete_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    for name in REQUIRED:
        monkeypatch.setenv(name, "configured")

    main.validate_startup_configuration()
