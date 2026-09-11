"""
LiveKit STT / LLM / TTS plugins wrapping the laptop HTTP clients.

AgentSession (livekit-agents 1.x) is the successor to VoicePipelineAgent and
takes the same kind of plugin instances: stt=, llm=, tts=.
"""
from __future__ import annotations

import uuid

from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    llm,
    stt,
    tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer

from clients.errors import ServiceUnavailableError
from clients.llm_client import generate_reply
from clients.settings import LLM_MODEL_NAME
from clients.stt_client import transcribe
from clients.tts_client import synthesize

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1


def _to_api_error(exc: Exception) -> APIConnectionError:
    err = APIConnectionError(str(exc))
    err.__cause__ = exc
    return err


class LaptopSTT(stt.STT):
    """Non-streaming STT that POSTs a WAV buffer to Laptop 2."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )

    @property
    def model(self) -> str:
        return "nemotron-http"

    @property
    def provider(self) -> str:
        return "laptop-stt"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        wav_bytes = rtc.combine_audio_frames(buffer).to_wav_bytes()
        try:
            text = await transcribe(wav_bytes)
        except ServiceUnavailableError as exc:
            raise _to_api_error(exc) from exc

        lang = "en" if language is NOT_GIVEN or not language else str(language)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=text or "", language=str(lang or "en"))],
        )


class LaptopTTS(tts.TTS):
    """Non-streaming TTS that POSTs text to Laptop 3 (Kokoro, WAV @ 24 kHz)."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
        )

    @property
    def model(self) -> str:
        return "kokoro-http"

    @property
    def provider(self) -> str:
        return "laptop-tts"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _LaptopChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _LaptopChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        try:
            audio_bytes = await synthesize(self.input_text)
        except ServiceUnavailableError as exc:
            raise _to_api_error(exc) from exc

        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
            mime_type="audio/wav",
        )
        output_emitter.push(audio_bytes)
        output_emitter.flush()


class LaptopLLM(llm.LLM):
    """OpenAI-compatible chat completions via Laptop 1 (Ollama / vLLM)."""

    @property
    def model(self) -> str:
        return LLM_MODEL_NAME

    @property
    def provider(self) -> str:
        return "laptop-llm"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs=NOT_GIVEN,
    ) -> llm.LLMStream:
        return _LaptopLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class _LaptopLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        messages = chat_ctx_to_messages(self._chat_ctx)
        try:
            text = await generate_reply(messages)
        except ServiceUnavailableError as exc:
            raise _to_api_error(exc) from exc

        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=str(uuid.uuid4()),
                delta=llm.ChoiceDelta(role="assistant", content=text),
            )
        )


def chat_ctx_to_messages(chat_ctx: llm.ChatContext) -> list[dict]:
    messages: list[dict] = []
    for item in chat_ctx.items:
        role = getattr(item, "role", None)
        if role not in ("system", "user", "assistant", "developer"):
            continue
        text = getattr(item, "text_content", None)
        if not text:
            content = getattr(item, "content", None)
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(part for part in content if isinstance(part, str))
        if text:
            openai_role = "system" if role == "developer" else role
            messages.append({"role": openai_role, "content": text})
    return messages
