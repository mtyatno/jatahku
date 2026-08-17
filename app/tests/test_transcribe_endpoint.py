"""Tests for _transcribe_request in app/api/routes/transactions.py.

Run from repo root:  python -m unittest app.tests.test_transcribe_endpoint -v
"""
import os
# app/core/database.py mengonstruksi Settings() saat import (butuh DATABASE_URL
# + JWT_SECRET dari /opt/jatahku/.env — tidak ada di mesin dev). Set env dummy
# SEBELUM import modul app.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.routes.transactions import _transcribe_request, MAX_AUDIO_BYTES
from app.services.transcription import TranscriptionError


class FakeAudio:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.content_type = content_type

    async def read(self):
        return self._data


class TestTranscribeRequest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_transcript_text(self):
        audio = FakeAudio(b"fake-audio", "audio/webm")
        with patch("app.api.routes.transactions.transcribe_audio",
                   new=AsyncMock(return_value="kopi 35 ribu")):
            text = await _transcribe_request(audio)
        self.assertEqual(text, "kopi 35 ribu")

    async def test_non_audio_content_type_415(self):
        audio = FakeAudio(b"x", "image/png")
        with self.assertRaises(HTTPException) as ctx:
            await _transcribe_request(audio)
        self.assertEqual(ctx.exception.status_code, 415)

    async def test_empty_audio_422(self):
        audio = FakeAudio(b"", "audio/webm")
        with self.assertRaises(HTTPException) as ctx:
            await _transcribe_request(audio)
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_oversize_413(self):
        audio = FakeAudio(b"x" * (MAX_AUDIO_BYTES + 1), "audio/webm")
        with self.assertRaises(HTTPException) as ctx:
            await _transcribe_request(audio)
        self.assertEqual(ctx.exception.status_code, 413)

    async def test_provider_error_502(self):
        audio = FakeAudio(b"fake-audio", "audio/webm")
        with patch("app.api.routes.transactions.transcribe_audio",
                   new=AsyncMock(side_effect=TranscriptionError("down"))):
            with self.assertRaises(HTTPException) as ctx:
                await _transcribe_request(audio)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_empty_transcript_422(self):
        audio = FakeAudio(b"fake-audio", "audio/webm")
        with patch("app.api.routes.transactions.transcribe_audio",
                   new=AsyncMock(return_value="")):
            with self.assertRaises(HTTPException) as ctx:
                await _transcribe_request(audio)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
