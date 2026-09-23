"""Tests for Deepgram TTS client and factory."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from clients.provider_util import normalize_provider
from clients.tts import DeepgramTts, ResilientTts, get_tts_client


class TestDeepgramTts(unittest.IsolatedAsyncioTestCase):
    async def test_deepgram_synthesize_mocked(self):
        tts = DeepgramTts(
            base_url="https://api.deepgram.com/v1",
            api_key="mock-key-123",
            model="aura-asteria-en",
        )

        mock_pcm = b"\x00\x00" * 2400
        mock_resp = httpx.Response(200, content=mock_pcm)

        with patch("clients.tts.deepgram.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_resp
            audio = await tts.synthesize("Hello from Deepgram")

            mock_request.assert_called_once()
            self.assertEqual(mock_request.call_args[0][0], "tts")
            self.assertEqual(mock_request.call_args[0][1], "POST")
            self.assertIn("/speak", mock_request.call_args[0][2])
            _, kwargs = mock_request.call_args
            self.assertEqual(kwargs["params"]["model"], "aura-asteria-en")
            self.assertEqual(kwargs["params"]["encoding"], "linear16")
            self.assertEqual(kwargs["params"]["sample_rate"], "24000")
            self.assertEqual(kwargs["headers"]["Authorization"], "Token mock-key-123")
            self.assertEqual(kwargs["json"], {"text": "Hello from Deepgram"})
            self.assertEqual(audio, mock_pcm)

    async def test_deepgram_stream_mocked(self):
        tts = DeepgramTts(
            base_url="https://api.deepgram.com/v1",
            api_key="mock-key-123",
            model="aura-asteria-en",
        )

        mock_chunks = [b"chunk1", b"chunk2"]

        class FakeStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def aiter_bytes(self, chunk_size=4096):
                for chunk in mock_chunks:
                    yield chunk

        with patch("clients.tts.deepgram.stream_request", return_value=FakeStream()):
            chunks = [chunk async for chunk in tts.stream_synthesize("Hello stream")]
            self.assertEqual(chunks, mock_chunks)

    def test_provider_resolver_and_factory(self):
        self.assertEqual(normalize_provider("deepgram", fallback="self_hosted"), "deepgram")
        self.assertEqual(normalize_provider("deep_gram", fallback="self_hosted"), "deepgram")

        tts_client = get_tts_client(
            provider_override="deepgram",
            api_key_override="mock-key-deepgram",
        )
        self.assertIsInstance(tts_client, ResilientTts)
        inner = tts_client._primary
        self.assertIsInstance(inner, DeepgramTts)
        self.assertEqual(inner.model, "aura-asteria-en")
