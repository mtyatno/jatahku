"""API verifikasi email penerima laporan berkala (tahap 2, Task 4; Ruling F-4).

Dua router, keduanya dipasang di main.py: `user_router` di `/user` (`POST /user/email/verifikasi`: kirim tautan) dan
`auth_router` di `/auth` (`/auth/verifikasi-email?token=`, tanpa login: `GET` = tautan di email, menampilkan halaman
konfirmasi; `POST` = tombol "Verifikasi email" di halaman itu). Semua endpoint baru, jadi API hanya bertambah.

Yang dijaga di sini (tes: app/tests/test_verifikasi_email_api.py):
- Tautan hanya dikirim ke alamat akun pemanggil sendiri, dengan token bertujuan 24 jam (services/verifikasi_email.py).
  Kiriman lewat `email_service.send_verifikasi_email` di thread: lognya tanpa alamat. Log di sini hanya teks tetap
  dan id user; tidak pernah alamat, token, atau tautan.
- `GET` tidak pernah menulis apa pun: pemindai tautan di layanan email membuka GET (pola berhenti berlangganan). Hanya
  `POST` yang memverifikasi. Halaman konfirmasi hanya tampil bila tautannya masih bisa memverifikasi; selainnya kedua
  metode langsung 303 ke Pengaturan dengan hasilnya.
- Yang diverifikasi alamat yang ada DI TOKEN: bila alamat akun sudah berganti sejak tautan dikirim hasilnya `berubah`
  dan tidak ada yang ditulis. Token salah, kedaluwarsa, bertujuan lain, atau user sudah tidak ada: sama,
  `tidak_berlaku` (tanpa membedakan, agar tidak membocorkan keberadaan akun).
- Berhasil juga menghidupkan lagi laporan 7 hari terakhir yang dilewati karena email belum terverifikasi.
- Batas: kirim 3/jam per user (`kunci_per_user`); `GET` dan `POST` tautan masing-masing 30/menit per IP dalam ember
  terpisah, jadi pemindai yang menghabiskan jatah GET tidak memblokir tombol.
"""
import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    """303 ke Pengaturan dengan hasilnya; alamat tujuan tidak memuat token. Jawaban ini (alamat asalnya bertoken) tidak
    disimpan cache. `Referrer-Policy` dari SecurityHeadersMiddleware (`strict-origin-when-cross-origin`): perujuk yang
    sampai ke Pengaturan (origin lain) paling banyak origin API, tanpa path dan query bertoken."""
    url = f"{get_settings().APP_URL}/settings?email_verifikasi={quote(hasil)}#laporan"
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})


async def _baca_tautan(db: AsyncSession, token: str) -> tuple[str | None, User | None, str | None]:
    """(hasil, user, email di token). `hasil` None bila tautan masih bisa memverifikasi `user`; selainnya
    `tidak_berlaku` (token tidak sah atau user sudah tidak ada) atau `berubah` (alamat akun berganti sejak tautan
    dikirim), tanpa user dan email. Hanya membaca."""
    terbaca = ve.baca_token_verifikasi(token)
    if terbaca is None:
        return HASIL_TIDAK_BERLAKU, None, None
    user_id, email = terbaca
    user = await db.get(User, user_id)
    if user is None:
        return HASIL_TIDAK_BERLAKU, None, None
    if not ve.sama_email(user.email, email):
        return HASIL_BERUBAH, None, None
    return None, user, email


_TERLALU_SERING = {"description": "Lebih dari 30 permintaan per menit."}


@auth_router.get(
    "/verifikasi-email",
    response_class=HTMLResponse,
    responses={
        200: {"description": 'Halaman konfirmasi "Verifikasi email kamu"; tombol "Verifikasi email" mengirim POST ke '
                             "alamat yang sama. Tidak mengubah apa pun."},
        303: {"description": "Tanpa halaman, dialihkan ke `/settings?email_verifikasi=<hasil>#laporan`: "
                             "`tidak_berlaku` (token tidak sah atau akun tidak ada), `berubah` (alamat akun berganti "
                             "sejak tautan dikirim), atau `berhasil` (alamat ini sudah terverifikasi). Tidak mengubah "
                             "apa pun."},
        429: _TERLALU_SERING,
    },
)
@limiter.shared_limit("30/minute", scope="verifikasi_email_get")   # ember GET dan POST terpisah (satu URL)
async def halaman_verifikasi_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Tautan di email. Tidak pernah menulis apa pun (pemindai tautan di layanan email membuka GET): halaman konfirmasi
    (200) bila tautannya masih bisa memverifikasi; selainnya 303 ke Pengaturan."""
    hasil, user, email = await _baca_tautan(db, token)
    if hasil is not None:
        return _balik(hasil)
    if user.email_verified_at is not None:   # alamat yang sama sudah terverifikasi: tidak ada yang perlu ditekan
        return _balik(HASIL_BERHASIL)
    return HTMLResponse(surel.halaman_konfirmasi_verifikasi(token, email), headers={"Cache-Control": "no-store"})


@auth_router.post(
    "/verifikasi-email",
    status_code=303,
    response_class=RedirectResponse,
    responses={
        303: {"description": "Dialihkan ke `/settings?email_verifikasi=berhasil|tidak_berlaku|berubah#laporan`; "
                             "`berhasil` = alamat di token terverifikasi (juga bila sudah sebelumnya)."},
        429: _TERLALU_SERING,
    },
)
@limiter.shared_limit("30/minute", scope="verifikasi_email_post")
async def konfirmasi_verifikasi_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Tombol "Verifikasi email" di halaman konfirmasi (badan tidak dibaca). Memverifikasi alamat di token, menghidupkan
    lagi laporan yang dilewati karena email belum terverifikasi, lalu 303 ke Pengaturan. Aman diulang: yang sudah
    terverifikasi tetap `berhasil` dan waktunya tidak berubah."""
    hasil, user, _email = await _baca_tautan(db, token)
    if hasil is not None:
        return _balik(hasil)
    ve.tandai_terverifikasi(user)
    await antrean_email.hidupkan_lagi(
        db, user.id, (antrean_email.ALASAN_BELUM_VERIFIKASI, antrean_email.ALASAN_TANPA_EMAIL),
    )
    await db.commit()
    return _balik(HASIL_BERHASIL)
