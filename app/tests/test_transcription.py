"""Tests for app/services/transcription.py.

Run from repo root:  python -m unittest app.tests.test_transcription -v
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import httpx

from app.services.transcription import (
    transcribe_audio, TranscriptionError, PROVIDERS, GroqProvider,
)

# Settings() butuh DATABASE_URL/JWT_SECRET dari /opt/jatahku/.env (VPS-only),
# jadi test patch get_settings dengan nilai default di bawah.
FAKE_SETTINGS = SimpleNamespace(
    WHISPER_PROVIDER="groq",
    GROQ_API_KEY="test-key",
    GROQ_WHISPER_MODEL="whisper-large-v3-turbo",
    GROQ_API_URL="https://api.groq.com/openai/v1/audio/transcriptions",
)


def _fake_response(status_code, payload):
    # MagicMock (bukan AsyncMock): service memanggil res.json() secara sync.
    res = MagicMock()
    res.status_code = status_code
    res.json.return_value = payload
    return res


def _patch_client(response_or_side_effect):
    """Patch httpx.AsyncClient; return the post-mock untuk inspeksi."""
    client = AsyncMock()
    post = AsyncMock(return_value=response_or_side_effect)
    client.__aenter__.return_value.post = post
    return patch("app.services.transcription.httpx.AsyncClient", return_value=client), post


class TestTranscribeAudio(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._settings_patch = patch("app.services.transcription.get_settings",
                                     return_value=FAKE_SETTINGS)
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()

    async def test_success_returns_trimmed_text(self):
        p, _ = _patch_client(_fake_response(200, {"text": "  kopi 35 ribu  "}))
        with p:
            text = await transcribe_audio(b"fake-audio", "audio/webm")
        self.assertEqual(text, "kopi 35 ribu")

    async def test_non_200_raises_transcription_error(self):
        p, _ = _patch_client(_fake_response(401, {"error": {}}))
        with p:
            with self.assertRaises(TranscriptionError):
                await transcribe_audio(b"fake-audio", "audio/webm")

    async def test_timeout_raises_transcription_error(self):
        client = AsyncMock()
        client.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.TimeoutException("timeout"))
        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            with self.assertRaises(TranscriptionError):
                await transcribe_audio(b"fake-audio", "audio/webm")

    async def test_empty_text_returns_empty_string(self):
        p, _ = _patch_client(_fake_response(200, {"text": ""}))
        with p:
            text = await transcribe_audio(b"fake-audio", "audio/webm")
        self.assertEqual(text, "")

    async def test_malformed_200_body_raises_transcription_error(self):
        fake = MagicMock()
        fake.status_code = 200
        fake.json.side_effect = ValueError("bad json")
        client = AsyncMock()
        client.__aenter__.return_value.post = AsyncMock(return_value=fake)
        with patch("app.services.transcription.httpx.AsyncClient", return_value=client):
            with self.assertRaises(TranscriptionError):
                await transcribe_audio(b"fake-audio", "audio/webm")

    async def test_multipart_filename_maps_webm(self):
        p, post = _patch_client(_fake_response(200, {"text": "ok"}))
        with p:
            await transcribe_audio(b"fake-audio", "audio/webm;codecs=opus")
        kwargs = post.call_args.kwargs
        name, _, _ = kwargs["files"]["file"]
        self.assertEqual(name, "audio.webm")

    async def test_multipart_filename_maps_mp4(self):
        p, post = _patch_client(_fake_response(200, {"text": "ok"}))
        with p:
            await transcribe_audio(b"fake-audio", "audio/mp4")
        kwargs = post.call_args.kwargs
        name, _, _ = kwargs["files"]["file"]
        self.assertEqual(name, "audio.mp4")

    async def test_unknown_provider_raises(self):
        with patch("app.services.transcription.get_settings",
                   return_value=SimpleNamespace(WHISPER_PROVIDER="nope")):
            with self.assertRaises(TranscriptionError):
                await transcribe_audio(b"fake-audio", "audio/webm")


class TestProviderRegistry(unittest.TestCase):
    def test_groq_is_registered(self):
        self.assertIs(PROVIDERS["groq"], GroqProvider)


if __name__ == "__main__":
    unittest.main()
