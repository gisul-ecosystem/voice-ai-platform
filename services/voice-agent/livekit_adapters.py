"""
LiveKit STT / LLM / TTS plugins wrapping the laptop HTTP clients.

AgentSession (livekit-agents 1.x) is the successor to VoicePipelineAgent and
takes the same kind of plugin instances: stt=, llm=, tts=.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import uuid
import wave

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
except ImportError:  # websockets < 13
    from websockets import connect as websocket_connect

    _WEBSOCKET_HEADERS_ARG = "extra_headers"

from clients.errors import ServiceUnavailableError
from clients.llm import get_llm_client
from clients.stt import get_stt_client
from clients.stt.sarvam import SarvamStt, parse_realtime_message
from clients.tts import get_tts_client

logger = logging.getLogger("voice-agent.stt")

TTS_SAMPLE_RATE = 24000
TTS_NUM_CHANNELS = 1
_STT_SAMPLE_RATE = 16000
_STT_CHUNK_BYTES = _STT_SAMPLE_RATE // 20 * 2  # 50 ms of 16-bit mono
# Brief patience after speech_end before committing to the LLM — a corrected
# Sarvam transcript arriving just after speech_end is worth the small delay.
_SARVAM_FINAL_GRACE_SECONDS = 0.2
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _to_api_error(exc: Exception) -> APIConnectionError:
    err = APIConnectionError(str(exc))
    err.__cause__ = exc
    return err


class LaptopSTT(stt.STT):
    """Streaming STT when the client supports it; otherwise buffered recognize()."""

    def __init__(self, client=None) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._client = client or get_stt_client()

    @property
    def model(self) -> str:
        return getattr(self._client, "model", None) or "nemotron-http"

    @property
    def provider(self) -> str:
        return type(self._client).__name__

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return _LaptopRecognizeStream(
            stt=self,
            conn_options=conn_options,
            language=language,
        )

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


class _LaptopRecognizeStream(stt.RecognizeStream):
    def __init__(
        self,
        *,
        stt: LaptopSTT,
        conn_options: APIConnectOptions,
        language: NotGivenOr[str],
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=_STT_SAMPLE_RATE)
        self._language = language

    async def _run(self) -> None:
        if isinstance(self._stt._client, SarvamStt):
            await self._run_sarvam()
        else:
            await self._run_buffered()

    def _lang(self) -> str:
        if self._language is NOT_GIVEN or not self._language:
            return "en"
        return str(self._language)

    async def _run_buffered(self) -> None:
        frames: list[rtc.AudioFrame] = []
        speaking = False

        async def emit_final() -> None:
            nonlocal frames, speaking
            if not frames:
                return
            event = await self._stt._recognize_impl(
                frames, language=self._language, conn_options=self._conn_options
            )
            if not speaking:
                self._event_ch.send_nowait(
                    stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                )
                speaking = True
            self._event_ch.send_nowait(event)
            self._event_ch.send_nowait(
                stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
            )
            speaking = False
            frames = []

        async for ev in self._input_ch:
            if isinstance(ev, rtc.AudioFrame):
                frames.append(ev)
            else:
                await emit_final()
        await emit_final()

    async def _run_sarvam(self) -> None:
        client: SarvamStt = self._stt._client
        url = client.realtime_ws_url(sample_rate=_STT_SAMPLE_RATE)
        headers = {
            "api-subscription-key": client.subscription_key,
            "API-SUBSCRIPTION-KEY": client.subscription_key,
        }
        speaking = False
        closing = False
        last_text = ""

        def _emit_interim(text: str) -> None:
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                    alternatives=[stt.SpeechData(text=text, language=self._lang())],
                )
            )

        def _emit_final(text: str) -> None:
            logger.info(
                "stt_transcript",
                extra={
                    "event": "stt_transcript",
                    "stage": "stt",
                    "provider": self._stt.provider,
                    "model": self._stt.model,
                    "output_chars": len(text),
                    "streaming": True,
                },
            )
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[stt.SpeechData(text=text, language=self._lang())],
                )
            )

        def _end_speech() -> None:
            nonlocal speaking, last_text
            if speaking:
                self._event_ch.send_nowait(
                    stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                )
                speaking = False
            last_text = ""

        pending_final_task: asyncio.Task | None = None

        def _cancel_pending_final() -> None:
            nonlocal pending_final_task
            if pending_final_task is not None and not pending_final_task.done():
                pending_final_task.cancel()
            pending_final_task = None

        async def _finalize_after_grace() -> None:
            nonlocal pending_final_task
            try:
                await asyncio.sleep(_SARVAM_FINAL_GRACE_SECONDS)
            except asyncio.CancelledError:
                return
            pending_final_task = None
            text_to_send = last_text
            if text_to_send:
                _emit_final(text_to_send)
            _end_speech()

        def _schedule_final() -> None:
            # Wait briefly for a possible corrected transcript.final instead of
            # committing the first guess immediately — small latency is worth
            # not sending a wrong transcript to the LLM.
            nonlocal pending_final_task
            _cancel_pending_final()
            pending_final_task = asyncio.create_task(_finalize_after_grace())

        def emit_transcript(kind: str, text: str) -> None:
            """Map Sarvam events to LiveKit STT events.

            Sarvam "fast" mode often emits growing transcript.final frames for one
            utterance. Commit only on speech_end or a repeated stable final.
            """
            nonlocal speaking, last_text
            text = (text or "").strip()
            if kind == "speech_start" or (text and not speaking):
                if not speaking:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                    speaking = True
                if kind == "speech_start":
                    return
            if kind == "partial" and text:
                last_text = text
                _emit_interim(text)
                if pending_final_task is not None:
                    # Speech resumed before the grace window elapsed; more is coming.
                    _cancel_pending_final()
                return
            if kind == "final" and text:
                # Identical final twice → utterance settled; otherwise keep interim.
                if speaking and text == last_text:
                    _cancel_pending_final()
                    _emit_final(text)
                    _end_speech()
                    return
                last_text = text
                _emit_interim(text)
                # Sarvam may omit speech_end. Every final therefore gets a short
                # debounce window so a correction can replace it before commit.
                _schedule_final()
                return
            if kind == "speech_end":
                if text:
                    last_text = text
                _schedule_final()

        try:
            connect_options = {_WEBSOCKET_HEADERS_ARG: headers}
            async with websocket_connect(url, **connect_options) as ws:

                async def send_task() -> None:
                    nonlocal closing
                    buf = bytearray()
                    try:
                        async for ev in self._input_ch:
                            if isinstance(ev, rtc.AudioFrame):
                                buf.extend(ev.data.tobytes())
                                while len(buf) >= _STT_CHUNK_BYTES:
                                    chunk = bytes(buf[:_STT_CHUNK_BYTES])
                                    del buf[:_STT_CHUNK_BYTES]
                                    await ws.send(
                                        json.dumps(
                                            {
                                                "event": "audio_input",
                                                "audio": base64.b64encode(chunk).decode(
                                                    "ascii"
                                                ),
                                            }
                                        )
                                    )
                            else:
                                if buf:
                                    await ws.send(
                                        json.dumps(
                                            {
                                                "event": "audio_input",
                                                "audio": base64.b64encode(bytes(buf)).decode(
                                                    "ascii"
                                                ),
                                            }
                                        )
                                    )
                                    buf.clear()
                                await ws.send(json.dumps({"event": "flush"}))
                        if buf:
                            await ws.send(
                                json.dumps(
                                    {
                                        "event": "audio_input",
                                        "audio": base64.b64encode(bytes(buf)).decode(
                                            "ascii"
                                        ),
                                    }
                                )
                            )
                    finally:
                        closing = True
                        try:
                            await ws.send(json.dumps({"event": "end"}))
                        except Exception:
                            pass

                async def recv_task() -> None:
                    async for raw in ws:
                        if not isinstance(raw, str):
                            continue
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        kind, text = parse_realtime_message(payload)
                        if kind == "other":
                            if payload.get("event") == "error":
                                raise APIConnectionError(
                                    f"Sarvam realtime error: {payload}"
                                )
                            continue
                        emit_transcript(kind, text)
                        if payload.get("event") == "session.end":
                            return

                sender = asyncio.create_task(send_task())
                receiver = asyncio.create_task(recv_task())
                try:
                    await asyncio.wait(
                        {sender, receiver},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if receiver.done() and receiver.exception():
                        raise receiver.exception()
                    await sender
                    if not receiver.done():
                        await asyncio.wait_for(receiver, timeout=2.0)
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    _cancel_pending_final()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
        except APIConnectionError:
            raise
        except (WebSocketException, OSError, Exception) as exc:
            if closing:
                return
            raise _to_api_error(exc) from exc


class LaptopTTS(tts.TTS):
    """Streaming TTS when the client can chunk PCM; otherwise full synthesize()."""

    def __init__(self, client=None) -> None:
        super().__init__(
            # Streaming keeps one continuous audio segment per reply. With this
            # off, livekit-agents wraps us in a sentence-splitting adapter that
            # issues a separate blocking HTTP synthesis per sentence, which is
            # heard as gaps and stutter mid-answer.
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
        )
        self._client = client or get_tts_client()

    @property
    def model(self) -> str:
        return (
            getattr(self._client, "model_id", None)
            or getattr(self._client, "model", None)
            or "tts-http"
        )

    @property
    def provider(self) -> str:
        return type(self._client).__name__

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _LaptopChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _LaptopSynthesizeStream(tts=self, conn_options=conn_options)


class _LaptopChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        try:
            audio_bytes = await self._tts._client.synthesize(self.input_text)
        except ServiceUnavailableError as exc:
            raise _to_api_error(exc) from exc

        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
            mime_type="audio/pcm",
        )
        pcm = _to_pcm(audio_bytes)
        if pcm:
            output_emitter.push(pcm)
        output_emitter.flush()


class _LaptopSynthesizeStream(tts.SynthesizeStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = str(uuid.uuid4())
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=TTS_NUM_CHANNELS,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=request_id)
        buffer = ""

        async def emit_text(text: str) -> None:
            spoken = (text or "").strip()
            if not spoken:
                return
            self._mark_started()
            stream = getattr(self._tts._client, "stream_synthesize", None)
            try:
                if stream is not None:
                    async for chunk in stream(spoken):
                        pcm = _to_pcm(chunk)
                        if pcm:
                            output_emitter.push(pcm)
                else:
                    audio_bytes = await self._tts._client.synthesize(spoken)
                    output_emitter.push(_to_pcm(audio_bytes))
            except ServiceUnavailableError as exc:
                raise _to_api_error(exc) from exc

        async for data in self._input_ch:
            if isinstance(data, self._FlushSentinel):
                await emit_text(buffer)
                buffer = ""
                continue
            buffer += data
            pieces = _SENTENCE_SPLIT.split(buffer)
            if len(pieces) > 1:
                buffer = pieces[-1]
                await emit_text(" ".join(pieces[:-1]))
        await emit_text(buffer)
        output_emitter.end_segment()
        output_emitter.flush()


def _to_pcm(audio_bytes: bytes) -> bytes:
    """LiveKit's emitter expects raw PCM; unwrap WAV if the TTS client returned one."""
    if not audio_bytes.startswith(b"RIFF"):
        return audio_bytes
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        return wav_file.readframes(wav_file.getnframes())


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
        stream = getattr(self._llm._client, "generate_reply_stream", None) or getattr(
            self._llm._client, "stream_reply", None
        )
        try:
            if stream is not None:
                chunk_id = str(uuid.uuid4())
                first = True
                async for delta in stream(messages):
                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=chunk_id,
                            delta=llm.ChoiceDelta(
                                role="assistant" if first else None,
                                content=delta,
                            ),
                        )
                    )
                    first = False
                return
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
