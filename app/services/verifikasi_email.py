"""Verifikasi email penerima laporan berkala (tahap 2). Tidak ada alamat email atau token di log.

Token verifikasi tidak memuat alamat. Badan JWT hanya base64url, dan token ada di URL (email, riwayat peramban, log
akses), jadi yang dibawa hanya sidik alamat: HMAC-SHA256 dari alamat yang dinormalkan (`models.email_normal`), dengan
kunci turunan `JWT_SECRET` dan pemisah domain `verifikasi-email/v1`. Tanpa kunci rahasia, alamat yang mudah ditebak bisa
dicocokkan dengan hash-nya, jadi hash biasa tidak cukup. Alamat yang ditampilkan dan diverifikasi selalu milik akun di
database; sidik hanya memastikan alamat itu masih sama dengan saat tautan dikirim.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.models.models import email_normal

TUJUAN_VERIFIKASI = "verifikasi_email"
BERLAKU_VERIFIKASI = timedelta(hours=24)
KLAIM_SIDIK = "eh"   # sidik alamat (hex). Token lama berklaim `email` tidak punya klaim ini → tidak berlaku.
_LABEL_KUNCI_SIDIK = b"verifikasi-email/v1"   # pemisah domain; versi baru = label baru (sidik lama tak lagi cocok)


def sama_email(a: str | None, b: str | None) -> bool:
    """Dua alamat sama setelah strip + huruf kecil. None atau kosong di salah satu sisi → False."""
    na, nb = email_normal(a), email_normal(b)
    return bool(na) and bool(nb) and na == nb


def _kunci_sidik() -> bytes:
    """Kunci HMAC sidik alamat, diturunkan dari `JWT_SECRET`; tidak pernah `JWT_SECRET` itu sendiri, jadi sidik tidak
    bisa dipakai sebagai tanda tangan apa pun yang lain. Mengganti `JWT_SECRET` membatalkan token ini (seperti semua
    token)."""
    return hmac.new(get_settings().JWT_SECRET.encode("utf-8"), _LABEL_KUNCI_SIDIK, hashlib.sha256).digest()


def sidik_email(email: str | None) -> str:
    """HMAC-SHA256 (hex, 64 karakter) dari alamat yang dinormalkan."""
    return hmac.new(_kunci_sidik(), email_normal(email).encode("utf-8"), hashlib.sha256).hexdigest()


def cocok_email(email: str | None, sidik) -> bool:
    """`sidik` (dari token) adalah sidik `email`. Alamat kosong atau sidik yang bukan teks tak kosong → False.
    Dibandingkan dalam waktu tetap."""
    if not email_normal(email) or not isinstance(sidik, str) or not sidik:
        return False
    return hmac.compare_digest(sidik_email(email).encode("ascii"), sidik.encode("utf-8", "replace"))


def tandai_terverifikasi(user, sekarang: datetime | None = None) -> None:
    """Isi `email_verified_at` bila masih NULL. Panggil SESUDAH email user diisi."""
    if user.email_verified_at is None:
        user.email_verified_at = sekarang or datetime.now(timezone.utc)


def tautan_verifikasi(user) -> str:
    token = create_purpose_token(
        str(user.id), TUJUAN_VERIFIKASI, berlaku=BERLAKU_VERIFIKASI, **{KLAIM_SIDIK: sidik_email(user.email)},
    )
    return f"{get_settings().API_URL}/auth/verifikasi-email?token={token}"


def baca_token_verifikasi(token: str) -> tuple[UUID, str] | None:
    """(id user, sidik alamat) dari token verifikasi yang sah, selainnya None. Cocokkan sidik dengan alamat akun lewat
    `cocok_email`."""
    payload = decode_purpose_token(token, TUJUAN_VERIFIKASI)
    if payload is None or "exp" not in payload:
        return None
    sidik = payload.get(KLAIM_SIDIK)
    if not isinstance(sidik, str) or not sidik:
        return None
    try:
        return UUID(payload["sub"]), sidik
    except ValueError:
        return None
