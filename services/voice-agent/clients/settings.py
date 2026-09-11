"""Env-backed settings for the voice-agent HTTP clients."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _livekit_url() -> str:
    return (
        os.getenv("LIVEKIT_URL")
        or os.getenv("LIVEKIT_WS_URL")
        or os.getenv("LIVEKIT_SERVER_URL")
        or ""
    ).rstrip("/")


# livekit-agents CLI/SDK reads LIVEKIT_URL. Accept WS/SERVER aliases from .env.
LIVEKIT_URL = _livekit_url()
if LIVEKIT_URL and not os.getenv("LIVEKIT_URL"):
    os.environ["LIVEKIT_URL"] = LIVEKIT_URL

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LIVEKIT_TOKEN_TTL_MINUTES = _int("LIVEKIT_TOKEN_TTL_MINUTES", 2)
LIVEKIT_ROOM_CAPACITY = _int("LIVEKIT_ROOM_CAPACITY", 5)

LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://localhost:11434/v1").rstrip("/")
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "http://localhost:8001").rstrip("/")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://localhost:8002").rstrip("/")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000").rstrip("/")

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3:4b-instruct-2507-q8_0")
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart")

LLM_TIMEOUT_SECONDS = _float("LLM_TIMEOUT_SECONDS", 30)
STT_TIMEOUT_SECONDS = _float("STT_TIMEOUT_SECONDS", 30)
TTS_TIMEOUT_SECONDS = _float("TTS_TIMEOUT_SECONDS", 30)
BACKEND_TIMEOUT_SECONDS = _float("BACKEND_TIMEOUT_SECONDS", 60)
HTTP_CONNECT_TIMEOUT_SECONDS = _float("HTTP_CONNECT_TIMEOUT_SECONDS", 5)
# Total attempts including the first try. 2–3 is the intended range.
HTTP_RETRY_ATTEMPTS = max(1, min(_int("HTTP_RETRY_ATTEMPTS", 3), 5))
