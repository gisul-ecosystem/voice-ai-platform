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
STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "http://localhost:5552").rstrip("/")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://localhost:5553").rstrip("/")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:5554").rstrip("/")
VOICE_AGENT_SERVICE_TOKEN = (os.getenv("VOICE_AGENT_SERVICE_TOKEN") or "").strip()
CONTEXT_ENGINE_URL = os.getenv("CONTEXT_ENGINE_URL", "http://localhost:5555").rstrip("/")

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3:4b-instruct-2507-q8_0")
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart")

# Optional provider names and keys. Unset = today's self-hosted URL path.
# Not listed in .env.example so existing deployments keep the same defaults.
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "self_hosted").strip() or "self_hosted"
STT_PROVIDER = (os.getenv("STT_PROVIDER") or "self_hosted").strip() or "self_hosted"
TTS_PROVIDER = (os.getenv("TTS_PROVIDER") or "self_hosted").strip() or "self_hosted"
LLM_API_KEY = (os.getenv("LLM_API_KEY") or "").strip()
STT_API_KEY = (os.getenv("STT_API_KEY") or "").strip()
TTS_API_KEY = (os.getenv("TTS_API_KEY") or "").strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ELEVENLABS_API_KEY = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
ELEVENLABS_BASE_URL = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1").rstrip("/")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip()
SARVAM_API_KEY = (os.getenv("SARVAM_API_KEY") or "").strip()
SARVAM_STT_BASE_URL = (
    os.getenv("SARVAM_STT_BASE_URL") or "https://api.sarvam.ai"
).strip().rstrip("/")
SARVAM_STT_MODEL = (os.getenv("SARVAM_STT_MODEL") or "saaras:v3").strip() or "saaras:v3"
SARVAM_STT_MODE = (os.getenv("SARVAM_STT_MODE") or "transcribe").strip() or "transcribe"
SARVAM_STT_LANGUAGE = (os.getenv("SARVAM_STT_LANGUAGE") or "unknown").strip() or "unknown"
SARVAM_STT_STREAM_TYPE = (os.getenv("SARVAM_STT_STREAM_TYPE") or "fast").strip() or "fast"

LLM_TIMEOUT_SECONDS = _float("LLM_TIMEOUT_SECONDS", 30)
STT_TIMEOUT_SECONDS = _float("STT_TIMEOUT_SECONDS", 30)
TTS_TIMEOUT_SECONDS = _float("TTS_TIMEOUT_SECONDS", 30)
BACKEND_TIMEOUT_SECONDS = _float("BACKEND_TIMEOUT_SECONDS", 60)
CONTEXT_ENGINE_TIMEOUT_SECONDS = _float("CONTEXT_ENGINE_TIMEOUT_SECONDS", 10)
HTTP_CONNECT_TIMEOUT_SECONDS = _float("HTTP_CONNECT_TIMEOUT_SECONDS", 5)
# Total attempts including the first try. 2–3 is the intended range.
HTTP_RETRY_ATTEMPTS = max(1, min(_int("HTTP_RETRY_ATTEMPTS", 3), 5))
