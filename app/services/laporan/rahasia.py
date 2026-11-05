"""Kata sandi laporan terenkripsi (laporan berkala, spec 2026-11-01-laporan-berkala-design, bagian 4).

Kata sandi PDF laporan disimpan di `report_settings.kata_sandi_enc` sebagai token Fernet. Kuncinya,
`REPORT_SECRET_KEY` (app/core/config.py), hanya dari /opt/jatahku/.env dan dibaca lewat
`get_settings()` setiap kali dipakai, tidak saat impor. Kunci, kata sandi, dan token tidak pernah
masuk log atau pesan galat.

Dua kegagalan sengaja berbeda supaya pemanggil bisa menjawab dengan benar:
- kunci kosong atau bukan kunci Fernet -> `KunciLaporanTidakAda` (server belum siap; route 503);
- token tersimpan tidak terbaca (kunci diganti, data rusak) -> `ValueError` (diperlakukan seperti
  kata sandi belum diatur; route 409).
"""
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger("jatahku.laporan")


class KunciLaporanTidakAda(RuntimeError):
    """REPORT_SECRET_KEY kosong atau bukan kunci Fernet yang valid."""


def _fernet() -> Fernet:
    kunci = get_settings().REPORT_SECRET_KEY
    if not kunci:
        raise KunciLaporanTidakAda("REPORT_SECRET_KEY kosong")
    try:
        return Fernet(kunci)
    except ValueError:  # bukan base64 url-safe 32 byte (termasuk karakter non-ASCII)
        raise KunciLaporanTidakAda("REPORT_SECRET_KEY bukan kunci Fernet yang valid") from None


def kunci_tersedia() -> bool:
    """True bila kata sandi laporan bisa dienkripsi dan didekripsi di server ini."""
    try:
        _fernet()
    except KunciLaporanTidakAda:
        return False
    return True


def enkripsi(kata_sandi: str) -> str:
    """Kata sandi -> token Fernet (teks ASCII, muat di kolom Text). Dua pemanggilan dengan kata sandi
    sama menghasilkan token berbeda. Tanpa kunci valid: `KunciLaporanTidakAda`."""
    return _fernet().encrypt(kata_sandi.encode("utf-8")).decode("ascii")


def dekripsi(token: str) -> str:
    """Token Fernet -> kata sandi. Tanpa kunci valid: `KunciLaporanTidakAda`. Token yang tidak bisa
    dibaca dengan kunci sekarang (kunci lain, terpotong, diubah, bukan token): `ValueError`."""
    fernet = _fernet()
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):  # UnicodeError (token bukan ASCII, isi bukan UTF-8) termasuk ValueError
        raise ValueError("token kata sandi laporan tidak terbaca") from None


def check_configured() -> bool:
    """Dipanggil saat startup (app/main.py): tanpa kunci yang valid, kata sandi dan PDF laporan ditolak
    di API, jadi peringatkan sekali di log (pola `email_service.check_configured`)."""
    if kunci_tersedia():
        return True
    logger.warning("REPORT_SECRET_KEY kosong atau tidak valid: kata sandi dan PDF laporan nonaktif")
    return False
