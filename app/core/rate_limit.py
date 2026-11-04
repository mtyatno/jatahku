"""Kunci batas frekuensi (`key_func` slowapi) per user, dipakai `/transactions/transcribe` dan `/bot/chat/*`.

Kunci lama (`transactions.transcribe_key_func`, `bot_chat.chat_key_func`) = sha256 dari teks header Authorization.
Teks itu bukan identitas: satu user mendapat ember baru kapan saja dengan menulis ulang headernya, tanpa mengubah siapa
dia: huruf besar-kecil skema (`HTTPBearer` menerima "bearer" dan "BEARER"), karakter di ujung token yang diabaikan
PyJWT (`<token>!!!!` tetap lolos verifikasi), atau login ulang (sesi dan token baru). Di sini kuncinya user yang
terautentikasi: klaim `sub` dari access token yang sah, jadi semua bentuk itu jatuh ke satu ember.

Header diurai persis seperti `HTTPBearer` (`get_authorization_scheme_param`, skema tak peka huruf) dan diverifikasi
persis seperti `get_current_user` (`decode_token`: tanda tangan, kedaluwarsa, dan harus access token). Token yang tidak
sah (tanda tangan salah, kedaluwarsa, refresh token, tanpa `sub`) tidak pernah menentukan ember siapa pun, dan tidak
bisa dipakai untuk mengaku sebagai user lain: kuncinya jatuh ke alamat IP. Di FastAPI `get_current_user` selesai lebih
dulu daripada pemeriksaan batas (yang membungkus fungsi route), jadi pada route yang memakainya token di sini sudah
terbukti sah; verifikasi ulang membuat fungsi ini benar juga bila urutan itu berubah.

Token tidak pernah dicatat ke log dan tidak menjadi bagian kunci.
"""
from fastapi import Request
from fastapi.security.utils import get_authorization_scheme_param
from slowapi.util import get_remote_address

from app.core.security import decode_token


def kunci_per_user(request: Request) -> str:
    """`user:<sub>` bila header membawa access token yang sah dengan `sub`; selainnya alamat IP klien
    (`get_remote_address`, tidak pernah kosong: slowapi melewatkan batas yang kuncinya kosong)."""
    skema, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if skema.lower() == "bearer" and token:
        payload = decode_token(token)
        if payload is not None and payload.get("type") == "access":
            sub = payload.get("sub")
            if isinstance(sub, str) and sub:
                return f"user:{sub}"
    return get_remote_address(request)
