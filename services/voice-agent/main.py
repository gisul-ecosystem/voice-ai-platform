"""
Laptop 4 -- voice agent
Round-trip smoke test: STT -> LLM -> TTS, no LiveKit yet.
Confirms all three laptop nodes are reachable and working together
before wiring into LiveKit's VoicePipelineAgent (AgentSession in 1.x).
Run the live interview worker with: python aaptor_agent.py start
"""
import asyncio
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from logging_config import configure_logging  # noqa: E402

configure_logging()

from clients.errors import ServiceUnavailableError  # noqa: E402
from clients.llm_client import generate_reply  # noqa: E402
from clients.tts_client import synthesize  # noqa: E402

logger = logging.getLogger("voice-agent.smoke")


async def main():
    # Placeholder candidate turn -- replace with real STT output once
    # you have a mic capture loop or a LiveKit room wired up.
    candidate_text = "I led a team migrating our monolith to microservices."

    try:
        reply = await generate_reply(
            [
                {
                    "role": "system",
                    "content": "You are an AI interviewer. Ask one relevant follow-up question.",
                },
                {"role": "user", "content": candidate_text},
            ]
        )
    except ServiceUnavailableError:
        logger.exception("smoke_llm_failed", extra={"event": "smoke_llm_failed", "stage": "llm"})
        raise

    logger.info(
        "smoke_llm_reply",
        extra={"event": "smoke_llm_reply", "stage": "llm", "output_chars": len(reply)},
    )

    try:
        audio = await synthesize(reply)
    except ServiceUnavailableError:
        logger.exception("smoke_tts_failed", extra={"event": "smoke_tts_failed", "stage": "tts"})
        raise

    with open("reply.wav", "wb") as f:
        f.write(audio)
    logger.info(
        "smoke_round_trip_complete",
        extra={"event": "smoke_round_trip_complete", "audio_bytes": len(audio)},
    )


if __name__ == "__main__":
    asyncio.run(main())
