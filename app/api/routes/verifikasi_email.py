"""API verifikasi email penerima laporan berkala (tahap 2, Task 4).

Dua router, keduanya dipasang di main.py: `user_router` di `/user` (`POST /user/email/verifikasi`: kirim tautan) dan
`auth_router` di `/auth` (`GET /auth/verifikasi-email?token=`: buka tautan dari email, tanpa login). Semua endpoint
baru, jadi API hanya bertambah.

Yang dijaga di sini (tes: app/tests/test_verifikasi_email_api.py):
- Tautan hanya dikirim ke alamat akun pemanggil sendiri, dengan token bertujuan 24 jam (services/verifikasi_email.py).
  Kiriman lewat `email_service.send_verifikasi_email` di thread: lognya tanpa alamat. Log di sini hanya teks tetap
  dan id user; tidak pernah alamat, token, atau tautan.
- Membuka tautan memverifikasi alamat yang ada DI TOKEN: bila alamat akun sudah berganti sejak tautan dikirim hasilnya
  `berubah` dan tidak ada yang ditulis. Token salah, kedaluwarsa, bertujuan lain, atau user sudah tidak ada: sama,
  `tidak_berlaku` (tanpa membedakan, agar tidak membocorkan keberadaan akun).
- Berhasil juga menghidupkan lagi laporan 7 hari terakhir yang dilewati karena email belum terverifikasi.
- Batas: kirim 3/jam per user (`kunci_per_user`), buka tautan 30/menit per IP.
"""
import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.routes.auth import limiter
from app.api.routes.laporan import GalatKode
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import kunci_per_user
from app.models.models import User
from app.services import email_service, verifikasi_email as ve
from app.services.laporan import antrean_email, surel

logger = logging.getLogger("jatahku.verifikasi_email")

user_router = APIRouter()
auth_router = APIRouter()

HASIL_BERHASIL = "berhasil"
HASIL_TIDAK_BERLAKU = "tidak_berlaku"
HASIL_BERUBAH = "berubah"
MSG_SUDAH = "Email sudah terverifikasi."
MSG_TANPA_EMAIL = "Belum ada email di akun ini."
MSG_GAGAL_KIRIM = "Tautan verifikasi gagal dikirim. Coba lagi nanti."


class StatusKirim(BaseModel):
    status: str


@user_router.post(
    "/email/verifikasi",
    response_model=StatusKirim,
    responses={
        409: {"model": GalatKode, "description": "Email sudah terverifikasi (kode `sudah_terverifikasi`)."},
        422: {"model": GalatKode, "description": "Akun belum punya email (kode `tanpa_email`)."},
        429: {"description": "Lebih dari 3 permintaan per jam."},
        502: {"model": GalatKode, "description": "Email gagal dikirim (kode `gagal_kirim`)."},
    },
)
@limiter.limit("3/hour", key_func=kunci_per_user)
async def kirim_tautan_verifikasi(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not (user.email or "").strip():
        return JSONResponse({"detail": MSG_TANPA_EMAIL, "kode": "tanpa_email"}, status_code=422)
    if user.email_verified_at is not None:
        return JSONResponse({"detail": MSG_SUDAH, "kode": "sudah_terverifikasi"}, status_code=409)
    user_id, nama, email = user.id, user.name, user.email
    tautan = ve.tautan_verifikasi(user)
    subjek, html, teks = surel.isi_email_verifikasi(nama, email, tautan)
    await db.close()   # koneksi dilepas selama kiriman SMTP
    terkirim = await asyncio.to_thread(email_service.send_verifikasi_email, email, subjek, html, teks)
    if not terkirim:
        logger.error("Tautan verifikasi email user %s gagal dikirim", user_id)
        return JSONResponse({"detail": MSG_GAGAL_KIRIM, "kode": "gagal_kirim"}, status_code=502)
    return StatusKirim(status="terkirim")


def _balik(hasil: str) -> RedirectResponse:
    url = f"{get_settings().APP_URL}/settings?email_verifikasi={quote(hasil)}#laporan"
    # Alamat ini tidak memuat token; header tambahan menjaga agar halaman tujuan tidak pernah membawa tautan asal.
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@auth_router.get(
    "/verifikasi-email",
    status_code=303,
    responses={303: {"description": "Dialihkan ke `/settings?email_verifikasi=berhasil|tidak_berlaku|berubah#laporan`."},
              429: {"description": "Lebih dari 30 permintaan per menit."}},
)
@limiter.limit("30/minute")
async def buka_tautan_verifikasi(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    terbaca = ve.baca_token_verifikasi(token)
    if terbaca is None:
        return _balik(HASIL_TIDAK_BERLAKU)
    user_id, email = terbaca
    user = await db.get(User, user_id)
    if user is None:
        return _balik(HASIL_TIDAK_BERLAKU)
    if not ve.sama_email(user.email, email):
        return _balik(HASIL_BERUBAH)
    ve.tandai_terverifikasi(user)
    await antrean_email.hidupkan_lagi(
        db, user.id, (antrean_email.ALASAN_BELUM_VERIFIKASI, antrean_email.ALASAN_TANPA_EMAIL),
    )
    await db.commit()
    return _balik(HASIL_BERHASIL)
