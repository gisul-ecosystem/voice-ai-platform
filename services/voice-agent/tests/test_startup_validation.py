import pytest

from products.interviewer import worker


REQUIRED = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "VOICE_AGENT_SERVICE_TOKEN",
)


def test_development_skips_production_validation(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)

    worker.validate_startup_configuration()


def test_production_rejects_missing_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="LIVEKIT_API_KEY"):
        worker.validate_startup_configuration()


def test_production_validates_provider_factories(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in REQUIRED:
        monkeypatch.setenv(name, "configured")
    called: list[str] = []
    monkeypatch.setattr(worker, "get_llm_client", lambda: called.append("llm"))
    monkeypatch.setattr(worker, "get_stt_client", lambda: called.append("stt"))
    monkeypatch.setattr(worker, "get_tts_client", lambda: called.append("tts"))

    worker.validate_startup_configuration()

    assert called == ["llm", "stt", "tts"]


def test_production_rejects_devkey_livekit_credentials(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in REQUIRED:
        monkeypatch.setenv(name, "configured")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setattr(worker, "get_llm_client", lambda: None)
    monkeypatch.setattr(worker, "get_stt_client", lambda: None)
    monkeypatch.setattr(worker, "get_tts_client", lambda: None)

    with pytest.raises(RuntimeError, match="LIVEKIT_API_KEY must not be"):
        worker.validate_startup_configuration()
