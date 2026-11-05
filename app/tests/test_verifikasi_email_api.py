"""Laporan berkala tahap 2, Task 4: API kirim dan buka tautan verifikasi email.

HTTP httpx + SQLite in-memory; token akses dan token verifikasi asli, `get_current_user` asli; hanya `get_db` dan
pengirim SMTP yang dipalsukan. Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_verifikasi_email_api -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from app.api.routes import auth as auth_route, verifikasi_email as rute
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, create_purpose_token, create_refresh_token
from app.models.models import Report, User
from app.services import email_service, verifikasi_email as ve
from app.tests.test_verifikasi_email import HAS_AIOSQLITE, DasarVerifikasi


def _lokasi(hasil: str) -> str:
    return f"{get_settings().APP_URL}/settings?email_verifikasi={hasil}#laporan"


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class ApiVerifikasiDasar(DasarVerifikasi):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.Session() as db:
            self.tanpa = await self.buat(db, "Tanpa", None)
            self.baru = await self.buat(db, "Baru", "baru@example.com", terverifikasi=False)
            await db.commit()
        app = FastAPI()
        app.state.limiter = auth_route.limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(rute.user_router, prefix="/user")
        app.include_router(rute.auth_router, prefix="/auth")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.klien2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.klien2.aclose)
        self.addCleanup(auth_route.limiter.reset)

    async def kirim(self, user, headers=None):
        return await self.klien2.post("/user/email/verifikasi", headers=headers or self.masuk(user))

    async def buka(self, token):
        return await self.klien2.get("/auth/verifikasi-email", params={"token": token}, follow_redirects=False)

    async def laporan_dilewati(self, user, hari=2, alasan="belum_verifikasi"):
        async with self.Session() as db:
            r = Report(
                user_id=user.id, jenis="bulanan", periode_mulai=date(2026, 10, 1), periode_akhir=date(2026, 10, 31),
                payday_day=1, data={}, terbit_at=datetime.now(timezone.utc) - timedelta(days=hari),
                email_status="dilewati", email_alasan=alasan,
            )
            db.add(r)
            await db.commit()
            return r.id

    async def status_laporan(self, rid):
        async with self.Session() as db:
            r = (await db.execute(select(Report).where(Report.id == rid))).scalar_one()
            return r.email_status, r.email_alasan


class KirimTautanTests(ApiVerifikasiDasar):
    async def test_kirim_tautan(self):
        with patch.object(email_service, "send_verifikasi_email", return_value=True) as kirim:
            r = await self.kirim(self.baru)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"status": "terkirim"})
        kirim.assert_called_once()
        ke, subjek, html, teks = kirim.call_args.args
        self.assertEqual(ke, "baru@example.com")
        self.assertEqual(subjek, "Verifikasi email Jatahku kamu")
        tautan = next(w for w in teks.split() if "/auth/verifikasi-email?token=" in w)
        token = parse_qs(urlparse(tautan).query)["token"][0]
        self.assertEqual(ve.baca_token_verifikasi(token), (self.baru.id, "baru@example.com"))

    async def test_sudah_terverifikasi_409(self):
        with patch.object(email_service, "send_verifikasi_email", return_value=True) as kirim:
            r = await self.kirim(self.ani)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["kode"], "sudah_terverifikasi")
        self.assertIn("detail", r.json())
        kirim.assert_not_called()

    async def test_tanpa_email_422(self):
        with patch.object(email_service, "send_verifikasi_email", return_value=True) as kirim:
            r = await self.kirim(self.tanpa)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["kode"], "tanpa_email")
        kirim.assert_not_called()

    async def test_smtp_gagal_502(self):
        with patch.object(email_service, "send_verifikasi_email", return_value=False):
            r = await self.kirim(self.baru)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["kode"], "gagal_kirim")
        self.assertIn("detail", r.json())

    async def test_tanpa_token_ditolak(self):
        r = await self.klien2.post("/user/email/verifikasi")
        self.assertIn(r.status_code, (401, 403))

    async def test_batas_tiga_per_jam(self):
        auth_route.limiter.reset()
        auth_route.limiter.enabled = True
        token = create_access_token(str(self.baru.id))
        varian = [
            {"Authorization": f"Bearer {token}"}, {"Authorization": f"bearer {token}"},
            {"Authorization": f"BEARER {token}!!!!"}, {"Authorization": f"Bearer {token}"},
        ]
        with patch.object(email_service, "send_verifikasi_email", return_value=True):
            kode = [(await self.kirim(self.baru, headers=h)).status_code for h in varian]
        self.assertEqual(kode, [200, 200, 200, 429])


class BukaTautanTests(ApiVerifikasiDasar):
    def token(self, user):
        return parse_qs(urlparse(ve.tautan_verifikasi(user)).query)["token"][0]

    async def test_buka_tautan_berhasil(self):
        rid = await self.laporan_dilewati(self.baru, hari=2)
        r = await self.buka(self.token(self.baru))
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], _lokasi("berhasil"))
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("menunggu", None))

    async def test_laporan_lama_tidak_dihidupkan(self):
        rid = await self.laporan_dilewati(self.baru, hari=30)
        await self.buka(self.token(self.baru))
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_sudah_terverifikasi_tetap_berhasil(self):
        r = await self.buka(self.token(self.ani))
        self.assertEqual(r.headers["location"], _lokasi("berhasil"))
        self.assertEqual((await self.baca(self.ani.id)).email_verified_at.replace(tzinfo=None),
                         datetime(2026, 10, 5, 3, 0))

    async def test_tautan_kedaluwarsa_dan_type_lain(self):
        kedaluwarsa = create_purpose_token(str(self.baru.id), ve.TUJUAN_VERIFIKASI, timedelta(seconds=-5),
                                           email="baru@example.com")
        lain = create_purpose_token(str(self.baru.id), "berhenti_email_laporan", timedelta(hours=1),
                                    email="baru@example.com")
        akses = create_access_token(str(self.baru.id))
        refresh = create_refresh_token(str(self.baru.id))
        hantu = create_purpose_token("00000000-0000-0000-0000-000000000001", ve.TUJUAN_VERIFIKASI,
                                     timedelta(hours=1), email="x@example.com")
        rid = await self.laporan_dilewati(self.baru)
        for t in (kedaluwarsa, lain, akses, refresh, hantu, "", "bukan-token"):
            r = await self.buka(t)
            self.assertEqual(r.status_code, 303)
            self.assertEqual(r.headers["location"], _lokasi("tidak_berlaku"), t[:20])
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_email_berganti_sesudah_kirim(self):
        token = self.token(self.baru)
        async with self.Session() as db:
            u = (await db.execute(select(User).where(User.id == self.baru.id))).scalar_one()
            u.email = "lain@example.com"
            await db.commit()
        rid = await self.laporan_dilewati(self.baru)
        r = await self.buka(token)
        self.assertEqual(r.headers["location"], _lokasi("berubah"))
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_email_beda_huruf_tetap_berhasil(self):
        token = self.token(self.baru)
        async with self.Session() as db:
            u = (await db.execute(select(User).where(User.id == self.baru.id))).scalar_one()
            u.email = " Baru@Example.COM "
            await db.commit()
        r = await self.buka(token)
        self.assertEqual(r.headers["location"], _lokasi("berhasil"))
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)

    async def test_batas_buka_tautan(self):
        auth_route.limiter.reset()
        auth_route.limiter.enabled = True
        kode = [(await self.buka("x")).status_code for _ in range(31)]
        self.assertEqual(kode[:30], [303] * 30)
        self.assertEqual(kode[30], 429)


class LogTanpaAlamatTests(unittest.TestCase):
    ALAMAT = "rahasia.alamat@example.com"

    def _jalankan(self, deliver):
        with patch.object(email_service, "_deliver", deliver), self.assertLogs("jatahku.email", level="DEBUG") as cm:
            hasil = email_service.send_verifikasi_email(self.ALAMAT, "S", "<p>h</p>", "t")
        return hasil, "\n".join(cm.output)

    def test_sukses_tanpa_alamat_di_log(self):
        msg = MagicMock()
        hasil, log = self._jalankan(msg)
        self.assertTrue(hasil)
        self.assertNotIn(self.ALAMAT, log)
        pesan = msg.call_args.args[1]
        self.assertNotIn("List-Unsubscribe", pesan.keys())
        for kepala in ("From", "To", "Subject", "Date", "Message-ID"):
            self.assertIn(kepala, pesan.keys())

    def test_gagal_tanpa_alamat_di_log(self):
        hasil, log = self._jalankan(MagicMock(side_effect=RuntimeError(f"550 {self.ALAMAT} ditolak")))
        self.assertFalse(hasil)
        self.assertNotIn(self.ALAMAT, log)
        self.assertIn("RuntimeError", log)


if __name__ == "__main__":
    unittest.main()
