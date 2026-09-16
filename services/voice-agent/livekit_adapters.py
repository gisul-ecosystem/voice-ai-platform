"""
LiveKit STT / LLM / TTS plugins wrapping the laptop HTTP clients.

AgentSession (livekit-agents 1.x) is the successor to VoicePipelineAgent and
takes the same kind of plugin instances: stt=, llm=, tts=.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from urllib.parse import urlencode

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
from websockets.exceptions import WebSocketException

try:
    from websockets.asyncio.client import connect as websocket_connect

    _WEBSOCKET_HEADERS_ARG = "additional_headers"
except ImportError:  # websockets < 13, retained for existing developer environments
    from websockets import connect as websocket_connect

    _WEBSOCKET_HEADERS_ARG = "extra_headers"

from clients.errors import ServiceUnavailableError
from clients.llm import get_llm_client
from clients.stt import get_stt_client
from clients.tts import get_tts_client

logger = logging.getLogger("voice-agent.stt")

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1


def _to_api_error(exc: Exception) -> APIConnectionError:
    err = APIConnectionError(str(exc))
    err.__cause__ = exc
    return err


class LaptopSTT(stt.STT):
    """Provider-neutral STT with Sarvam realtime and batch fallback support."""

    def __init__(self, client=None) -> None:
        selected = client or get_stt_client()
        streaming = type(selected).__name__ == "SarvamStt"
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=streaming,
                interim_results=streaming,
            )
        )
        self._client = selected

    @property
    def model(self) -> str:
        return getattr(self._client, "model", None) or "nemotron-http"

    @property
    def provider(self) -> str:
        return type(self._client).__name__

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        wav_bytes = rtc.combine_audio_frames(buffer).to_wav_bytes()
        try:
            text = await self._client.transcribe(wav_bytes)
        except ServiceUnavailableError as exc:
            raise _to_api_error(exc) from exc

        lang = "en" if language is NOT_GIVEN or not language else str(language)
        transcript = text or ""
        logger.info(
            "stt_transcript",
            extra={
                "event": "stt_transcript",
                "stage": "stt",
                "provider": self.provider,
                "model": self.model,
                "output_chars": len(transcript),
            },
        )
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=text or "", language=str(lang or "en"))],
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        if not self.capabilities.streaming:
            return super().stream(language=language, conn_options=conn_options)
        return _SarvamRecognizeStream(
            stt_client=self,
            conn_options=conn_options,
        )


class _SarvamRecognizeStream(stt.RecognizeStream):
    def __init__(
        self,
        *,
        stt_client: LaptopSTT,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            stt=stt_client,
            conn_options=conn_options,
            sample_rate=16000,
        )
        self._client = stt_client._client

    async def _run(self) -> None:
        base_url = self._client.base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        query = urlencode(
            {
                "language_code": "auto",
                "model": "saaras:v3-realtime",
                "stream_type": "fast",
                "mode": self._client.mode,
                "endpointing": "vad",
                "encoding": "linear16",
                "sample_rate": 16000,
            }
        )
        url = f"{base_url}/speech-to-text-realtime/ws?{query}"
        try:
            connect_options = {
                _WEBSOCKET_HEADERS_ARG: {
                    "api-subscription-key": self._client.subscription_key
                }
            }
            async with websocket_connect(
                url,
                open_timeout=self._conn_options.timeout,
                **connect_options,
            ) as socket:
                async def send_audio() -> None:
                    async for item in self._input_ch:
                        if isinstance(item, stt.RecognizeStream._FlushSentinel):
                            continue
                        await socket.send(
                            json.dumps(
                                {
                                    "event": "audio_input",
                                    "audio": base64.b64encode(
                                        bytes(item.data)
                                    ).decode(),
                                }
                            )
                        )
                    await socket.send(json.dumps({"event": "end"}))

                async def receive_events() -> None:
                    async for raw in socket:
                        payload = json.loads(raw)
                        event = payload.get("event")
                        if event == "transcript.partial":
                            event_type = stt.SpeechEventType.INTERIM_TRANSCRIPT
                        elif event == "transcript.final":
                            event_type = stt.SpeechEventType.FINAL_TRANSCRIPT
                        elif event == "vad.speech_start":
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                            )
                            continue
                        elif event == "vad.speech_end":
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                            )
                            continue
                        elif event == "error":
                            raise APIConnectionError(
                                str(payload.get("message") or "Sarvam stream error")
                            )
                        elif event == "session.end":
                            return
                        else:
                            continue
                        text = str(payload.get("text") or "")
                        if text:
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(
                                    type=event_type,
                                    alternatives=[
                                        stt.SpeechData(
                                            text=text,
                                            language=str(
                                                payload.get("language") or "en-IN"
                                            ),
                                        )
                                    ],
                                )
                            )

                await asyncio.gather(send_audio(), receive_events())
        except (WebSocketException, OSError, json.JSONDecodeError) as exc:
            raise _to_api_error(exc) from exc


class LaptopTTS(tts.TTS):
    """Non-streaming TTS via the configured TTS provider (Kokoro HTTP or OpenAI)."""

    def __init__(self, client=None) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
        )
        self._client = client or get_tts_client()

    @property
    def model(self) -> str:
        return getattr(self._client, "model_id", None) or getattr(
            self._client, "model", None
        ) or "tts-http"

    @property
    def provider(self) -> str:
        return type(self._client).__name__

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _LaptopChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _LaptopChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        stream_synthesize = getattr(self._tts._client, "stream_synthesize", None)
        if callable(stream_synthesize):
            output_emitter.initialize(
                request_id=str(uuid.uuid4()),
                sample_rate=TTS_SAMPLE_RATE,
                num_channels=TTS_NUM_CHANNELS,
                mime_type="audio/pcm",
            )
            try:
                async for audio_chunk in stream_synthesize(self.input_text):
                    output_emitter.push(audio_chunk)
            except ServiceUnavailableError as exc:
                raise _to_api_error(exc) from exc
            output_emitter.flush()
            return

        try:
            audio_bytes = await self._tts._client.synthesize(self.input_text)
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
    """OpenAI-compatible chat completions (self-hosted Ollama/vLLM or OpenAI API)."""

    def __init__(self, client=None) -> None:
        super().__init__()
        self._client = client or get_llm_client()

    @property
    def model(self) -> str:
        return getattr(self._client, "model", "") or "llm-http"

    @property
    def provider(self) -> str:
        return type(self._client).__name__

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
        stream_reply = getattr(self._llm._client, "stream_reply", None)
        if callable(stream_reply):
            try:
                async for text in stream_reply(messages):
                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=str(uuid.uuid4()),
                            delta=llm.ChoiceDelta(
                                role="assistant",
                                content=text,
                            ),
                        )
                    )
            except ServiceUnavailableError as exc:
                raise _to_api_error(exc) from exc
            return

        try:
            text = await self._llm._client.generate_reply(messages)
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
