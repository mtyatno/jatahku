"""Verifikasi email penerima laporan berkala (tahap 2). Tidak ada alamat email atau token di log."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.models.models import email_normal

TUJUAN_VERIFIKASI = "verifikasi_email"
BERLAKU_VERIFIKASI = timedelta(hours=24)


def sama_email(a: str | None, b: str | None) -> bool:
    """Dua alamat sama setelah strip + huruf kecil. None atau kosong di salah satu sisi → False."""
    na, nb = email_normal(a), email_normal(b)
    return bool(na) and bool(nb) and na == nb


def tandai_terverifikasi(user, sekarang: datetime | None = None) -> None:
    """Isi `email_verified_at` bila masih NULL. Panggil SESUDAH email user diisi."""
    if user.email_verified_at is None:
        user.email_verified_at = sekarang or datetime.now(timezone.utc)


def tautan_verifikasi(user) -> str:
    token = create_purpose_token(
        str(user.id), TUJUAN_VERIFIKASI, BERLAKU_VERIFIKASI, email=email_normal(user.email),
    )
    return f"{get_settings().API_URL}/auth/verifikasi-email?token={token}"


def baca_token_verifikasi(token: str) -> tuple[UUID, str] | None:
    """(id user, email huruf kecil) dari token verifikasi yang sah, selainnya None."""
    payload = decode_purpose_token(token, TUJUAN_VERIFIKASI)
    if payload is None or "exp" not in payload:
        return None
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        return None
    try:
        return UUID(payload["sub"]), email
    except ValueError:
        return None
