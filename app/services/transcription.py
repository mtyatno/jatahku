"""Voice transcription service.

Entry point stabil: transcribe_audio(audio_bytes, content_type) -> str.
Provider dipilih via settings.WHISPER_PROVIDER ("groq" saat ini; "selfhosted"
untuk private whisper server nanti — tinggal tambah class + registry).

Konvensi marker: kode spesifik provider diberi komentar
`# WHISPER-PROVIDER:<name>`. Saat migrasi ke selfhosted, seluruh blok
ber-marker groq tidak dipakai lagi; kode tanpa marker tetap dipakai.
"""
import httpx

from app.core.config import get_settings


class TranscriptionError(Exception):
    """Kegagalan transkripsi (provider error/timeout). Endpoint memetakan ke 502."""


# WHISPER-PROVIDER:groq — seluruh class ini spesifik Groq, tidak dipakai saat selfhosted.
class GroqProvider:
    """Panggil Groq audio/transcriptions (OpenAI-compatible, multipart)."""

    _EXT_BY_MIME = {
        "audio/webm": "audio.webm",
        "audio/mp4": "audio.mp4",
        "audio/m4a": "audio.m4a",
        "audio/ogg": "audio.ogg",
        "audio/wav": "audio.wav",
    }

    def _filename(self, content_type: str) -> str:
        base = (content_type or "").split(";")[0].strip()
        return self._EXT_BY_MIME.get(base, "audio.webm")

    async def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        # Catatan: import httpx di level modul (bukan di sini) supaya patch
        # unittest "app.services.transcription.httpx" bisa resolve.
        settings = get_settings()
        files = {"file": (self._filename(content_type), audio_bytes, content_type)}
        data = {
            "model": settings.GROQ_WHISPER_MODEL,
            "language": "id",
            "response_format": "json",
        }
        headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    settings.GROQ_API_URL, files=files, data=data, headers=headers
                )
        except httpx.HTTPError as exc:  # timeout / koneksi gagal
            raise TranscriptionError(f"provider error: {exc}") from exc
        if res.status_code != 200:
            raise TranscriptionError(f"provider status {res.status_code}")
        return (res.json().get("text") or "").strip()


# Registry provider (tanpa marker — stable). Tambah "selfhosted":
# SelfHostedProvider saat private whisper server jadi.
PROVIDERS = {
    "groq": GroqProvider,
}


def _get_provider() -> GroqProvider:
    name = get_settings().WHISPER_PROVIDER
    if name not in PROVIDERS:
        raise TranscriptionError(f"provider tidak dikenal: {name}")
    return PROVIDERS[name]()


async def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
    """Entry point stabil (tanpa marker — dipakai semua provider)."""
    return await _get_provider().transcribe(audio_bytes, content_type)
