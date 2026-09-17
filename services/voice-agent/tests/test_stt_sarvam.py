"""STT Sarvam client tests: mocked success, missing key, invalid key, optional live."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from clients.errors import ProviderConfigError, ServiceUnavailableError  # noqa: E402
from clients.stt import get_stt_client  # noqa: E402
from clients.stt.sarvam import SarvamStt, transcript_from_payload  # noqa: E402


def _json_response(status: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://api.sarvam.ai/speech-to-text")
    return httpx.Response(status, json=payload, request=request)


class TranscriptParseTests(unittest.TestCase):
    def test_prefers_transcript_field(self) -> None:
        self.assertEqual(
            transcript_from_payload({"transcript": "hello", "text": "ignored"}),
            "hello",
        )

    def test_falls_back_to_text(self) -> None:
        self.assertEqual(transcript_from_payload({"text": "hi"}), "hi")


class FactoryTests(unittest.TestCase):
    def test_missing_key_raises(self) -> None:
        with self.assertRaises(ProviderConfigError):
            get_stt_client("sarvam", "")

    def test_factory_builds_sarvam(self) -> None:
        client = get_stt_client("sarvam", "sk-test")
        self.assertIsInstance(client, SarvamStt)
        self.assertEqual(client.model, "saaras:v3")


class MockedTranscribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mocked_success(self) -> None:
        resp = _json_response(200, {"transcript": "namaste", "language_code": "hi-IN"})
        with patch("clients.stt.sarvam.request", new_callable=AsyncMock, return_value=resp):
            text = await SarvamStt(api_key="sk-test").transcribe(b"RIFF....")
        self.assertEqual(text, "namaste")

    async def test_uses_subscription_header_without_bearer_auth(self) -> None:
        resp = _json_response(200, {"transcript": "hello"})
        with patch(
            "clients.stt.sarvam.request",
            new_callable=AsyncMock,
            return_value=resp,
        ) as mocked:
            await SarvamStt(api_key="sk-test").transcribe(b"RIFF....")
        kwargs = mocked.await_args.kwargs
        self.assertEqual(kwargs["headers"], {"api-subscription-key": "sk-test"})
        self.assertNotIn("api_key", kwargs)

    async def test_retries_empty_unknown_language(self) -> None:
        empty = _json_response(200, {"transcript": "", "language_code": None})
        filled = _json_response(200, {"transcript": "hello", "language_code": "en-IN"})
        with patch(
            "clients.stt.sarvam.request",
            new_callable=AsyncMock,
            side_effect=[empty, filled],
        ) as mocked:
            text = await SarvamStt(api_key="sk-test").transcribe(b"RIFF....")
        self.assertEqual(text, "hello")
        self.assertEqual(mocked.await_count, 2)

    async def test_invalid_key_is_unavailable(self) -> None:
        request = httpx.Request("POST", "https://api.sarvam.ai/speech-to-text")
        error = httpx.HTTPStatusError(
            "Forbidden",
            request=request,
            response=httpx.Response(403, request=request),
        )
        with patch(
            "clients.stt.sarvam.request",
            new_callable=AsyncMock,
            side_effect=ServiceUnavailableError("stt", f"HTTPStatusError: {error}"),
        ):
            with self.assertRaises(ServiceUnavailableError):
                await SarvamStt(api_key="bad-key").transcribe(b"RIFF....")


@unittest.skipUnless(
    os.getenv("SARVAM_LIVE_TEST", "").strip() in {"1", "true", "yes"}
    and (os.getenv("STT_API_KEY") or os.getenv("SARVAM_API_KEY") or "").strip(),
    "Set SARVAM_LIVE_TEST=1 and STT_API_KEY (or SARVAM_API_KEY) to hit Sarvam.",
)
class LiveSarvamTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_rejects_invalid_key(self) -> None:
        client = SarvamStt(api_key="definitely-not-a-valid-key")
        with self.assertRaises(ServiceUnavailableError):
            await client.transcribe(b"not-a-wav")


if __name__ == "__main__":
    unittest.main()
