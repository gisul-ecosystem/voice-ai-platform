"""Tests for ElevenLabs TTS client and factory."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from clients.errors import ServiceUnavailableError
from clients.provider_util import normalize_provider
from clients.tts import ElevenLabsTts, get_tts_client


class TestElevenLabsTts(unittest.IsolatedAsyncioTestCase):
    async def test_elevenlabs_synthesize_mocked(self):
        """Mocked test: checks URL, parameters, headers, and audio wrapping."""
        tts = ElevenLabsTts(
            base_url="https://api.elevenlabs.io/v1",
            api_key="mock-key-123",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            model_id="eleven_flash_v2_5",
        )

        mock_pcm = b"\x00\x00" * 2400  # 0.1s of silence in 16-bit 24kHz PCM
        mock_resp = httpx.Response(200, content=mock_pcm)

        with patch("clients.tts.elevenlabs.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_resp
            audio = await tts.synthesize("Hello from ElevenLabs")

            mock_request.assert_called_once()
            _, kwargs = mock_request.call_args
            self.assertEqual(mock_request.call_args[0][0], "tts")
            self.assertEqual(mock_request.call_args[0][1], "POST")
            self.assertIn("text-to-speech/JBFqnCBsd6RMkjVDRZzb", mock_request.call_args[0][2])
            self.assertEqual(kwargs["headers"], {"xi-api-key": "mock-key-123"})
            self.assertEqual(
                kwargs["json"],
                {
                    "text": "Hello from ElevenLabs",
                    "model_id": "eleven_flash_v2_5",
                },
            )
            self.assertEqual(kwargs["params"], {"output_format": "pcm_24000"})

            # Verify output is a valid WAV container (starts with RIFF header)
            self.assertTrue(audio.startswith(b"RIFF"))
            self.assertGreater(len(audio), len(mock_pcm))

    async def test_elevenlabs_invalid_key_error(self):
        """Invalid key test: verifies graceful failure raising ServiceUnavailableError."""
        tts = ElevenLabsTts(
            base_url="https://api.elevenlabs.io/v1",
            api_key="invalid_key",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
        )

        with patch("clients.http_util.httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
            req = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb")
            mock_req.return_value = httpx.Response(401, text="Invalid API key", request=req)

            with self.assertRaises(ServiceUnavailableError):
                await tts.synthesize("Test failure")

    def test_provider_normalization_and_factory(self):
        """Tests provider resolver and TTS factory for ElevenLabs."""
        self.assertEqual(normalize_provider("elevenlabs", fallback="self_hosted"), "elevenlabs")
        self.assertEqual(normalize_provider("11labs", fallback="self_hosted"), "elevenlabs")
        self.assertEqual(normalize_provider("eleven_labs", fallback="self_hosted"), "elevenlabs")

        client = get_tts_client(
            provider_override="elevenlabs",
            api_key_override="override-key-456",
        )
        self.assertIsInstance(client, ElevenLabsTts)
        self.assertEqual(client._api_key, "override-key-456")
        self.assertEqual(client.voice_id, "JBFqnCBsd6RMkjVDRZzb")
        self.assertEqual(client.model_id, "eleven_flash_v2_5")

    @unittest.skipUnless(
        os.getenv("ELEVENLABS_LIVE_TEST", "").strip().lower()
        in {"1", "true", "yes"},
        "Set ELEVENLABS_LIVE_TEST=1 to call the paid ElevenLabs API.",
    )
    async def test_elevenlabs_live(self):
        """Live test against ElevenLabs API if TTS_API_KEY is configured."""
        api_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("TTS_API_KEY")
        if not api_key or not api_key.strip() or api_key.startswith("mock") or api_key.startswith("sk-proj-"):
            self.skipTest("No valid ElevenLabs API key configured in environment (found dummy or OpenAI key).")

        tts = ElevenLabsTts(api_key=api_key)
        try:
            audio = await tts.synthesize("Testing voice synthesis.")
            self.assertTrue(audio.startswith(b"RIFF"))
            self.assertGreater(len(audio), 1000)
        except ServiceUnavailableError as err:
            if "401" in str(err) or "Unauthorized" in str(err):
                self.skipTest(f"ElevenLabs key unauthorized (expired or invalid): {err}")
            else:
                self.fail(f"Live ElevenLabs call failed: {err}")


if __name__ == "__main__":
    unittest.main()
