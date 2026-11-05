"""Laporan berkala tahap 2, Task 4: API kirim tautan verifikasi email, halaman konfirmasinya (GET), dan tombol
"Verifikasi email" (POST; Ruling F-4).

HTTP httpx + SQLite in-memory; token akses dan token verifikasi asli, `get_current_user` asli; hanya `get_db` dan
pengirim SMTP yang dipalsukan. Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_verifikasi_email_api -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import calendar
import html
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import event, select, update

from app.api.routes import auth as auth_route, verifikasi_email as rute
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, create_purpose_token, create_refresh_token
from app.models.models import HouseholdMember, Report, User
from app.services import email_service, verifikasi_email as ve
from app.tests.test_verifikasi_email import HAS_AIOSQLITE, TERVERIFIKASI, DasarVerifikasi


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
        """GET tautan di email (yang juga dibuka pemindai tautan)."""
        return await self.klien2.get("/auth/verifikasi-email", params={"token": token}, follow_redirects=False)

    async def konfirmasi(self, token, **kw):
        """POST tombol "Verifikasi email" di halaman konfirmasi."""
        return await self.klien2.post("/auth/verifikasi-email", params={"token": token}, follow_redirects=False, **kw)

    async def laporan_dilewati(self, user, hari=2, alasan="belum_verifikasi", bulan=10):
        """Laporan bulanan `user` (periode bulan `bulan` 2026; satu laporan per bulan per user) yang terbit `hari` hari
        lalu dan `dilewati` karena `alasan`."""
        async with self.Session() as db:
            r = Report(
                user_id=user.id, jenis="bulanan", periode_mulai=date(2026, bulan, 1),
                periode_akhir=date(2026, bulan, calendar.monthrange(2026, bulan)[1]),
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


class TautanVerifikasiTests(ApiVerifikasiDasar):
    """Ruling F-4: tautan di email membuka GET, yang hanya menampilkan halaman konfirmasi dan tidak pernah menulis
    (pemindai tautan di layanan email membuka GET); tombol "Verifikasi email" mengirim POST ke alamat yang sama, dan
    hanya POST yang memverifikasi. Pola berhenti berlangganan (`test_laporan_api.SaklarEmailTests`)."""

    def token(self, user):
        return parse_qs(urlparse(ve.tautan_verifikasi(user)).query)["token"][0]

    async def dengan_tulisan(self, permintaan):
        """(jawaban, SQL tulis): setiap INSERT/UPDATE/DELETE yang dijalankan database selama `permintaan`."""
        tulis = []

        def catat(_conn, _cursor, statement, *_args):
            if statement.lstrip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"):
                tulis.append(statement)
        event.listen(self.engine.sync_engine, "before_cursor_execute", catat)
        try:
            return await permintaan, tulis
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", catat)

    def token_tidak_sah(self) -> dict:
        uid = str(self.baru.id)
        return {
            "kedaluwarsa": create_purpose_token(uid, ve.TUJUAN_VERIFIKASI, berlaku=timedelta(seconds=-5),
                                                email="baru@example.com"),
            "tujuan lain": create_purpose_token(uid, "berhenti_email_laporan", berlaku=None),
            "access": create_access_token(uid),
            "refresh": create_refresh_token(uid),
            "user tidak ada": create_purpose_token("00000000-0000-0000-0000-000000000001", ve.TUJUAN_VERIFIKASI,
                                                   berlaku=timedelta(hours=1), email="x@example.com"),
            "kosong": "",
            "acak": "bukan-token",
        }

    async def ganti_email(self, user, email):
        async with self.Session() as db:
            u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
            u.email = email
            await db.commit()

    async def hapus_user(self, user):
        async with self.Session() as db:
            await db.execute(HouseholdMember.__table__.delete().where(HouseholdMember.user_id == user.id))
            await db.execute(User.__table__.delete().where(User.id == user.id))
            await db.commit()

    async def baris_laporan(self, rid):
        async with self.Session() as db:
            r = await db.get(Report, rid)
            return r.email_status, r.email_alasan, r.email_percobaan, r.email_terakhir_at

    def aksi_formulir(self, halaman: str) -> str:
        return html.unescape(re.search(r'<form method="post" action="([^"]*)">', halaman).group(1))

    # --- GET: halaman konfirmasi; tidak pernah menulis -------------------------------------------------------------

    async def test_get_menampilkan_konfirmasi_tanpa_menulis(self):
        async with self.Session() as db:
            oneil = await self.buat(db, "Oneil", "o'neil@example.com", terverifikasi=False)
            await db.commit()
        rid = await self.laporan_dilewati(oneil, hari=2)
        token = self.token(oneil)
        r, tulis = await self.dengan_tulisan(self.buka(token))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertIn("<h1>Verifikasi email kamu</h1>", r.text)
        self.assertIn("<p>Klik tombol di bawah untuk memverifikasi o&#x27;neil@example.com sebagai alamat penerima "
                      "laporan Jatahku.</p>", r.text)
        self.assertNotIn("o'neil@example.com", r.text)   # alamat hanya tampil ter-escape
        self.assertEqual(self.aksi_formulir(r.text), f"/auth/verifikasi-email?token={quote(token, safe='')}")
        self.assertIn('<button type="submit">Verifikasi email</button>', r.text)
        self.assertEqual(tulis, [])
        self.assertIsNone((await self.baca(oneil.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_get_token_tidak_berlaku_303_tanpa_menulis(self):
        rid = await self.laporan_dilewati(self.baru)
        for nama, token in self.token_tidak_sah().items():
            with self.subTest(nama=nama):
                r, tulis = await self.dengan_tulisan(self.buka(token))
                self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("tidak_berlaku")))
                self.assertEqual(r.headers["cache-control"], "no-store")
                self.assertEqual(tulis, [])
        r = await self.klien2.get("/auth/verifikasi-email", follow_redirects=False)   # tanpa parameter token
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("tidak_berlaku")))
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_get_user_terhapus_303_tanpa_menulis(self):
        token = self.token(self.baru)
        await self.hapus_user(self.baru)
        r, tulis = await self.dengan_tulisan(self.buka(token))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("tidak_berlaku")))
        self.assertEqual(tulis, [])

    async def test_get_email_berganti_303_berubah_tanpa_menulis(self):
        token = self.token(self.baru)
        await self.ganti_email(self.baru, "lain@example.com")
        rid = await self.laporan_dilewati(self.baru)
        r, tulis = await self.dengan_tulisan(self.buka(token))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berubah")))
        self.assertEqual(tulis, [])
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_get_sudah_terverifikasi_303_berhasil_tanpa_menulis(self):
        rid = await self.laporan_dilewati(self.ani)
        r, tulis = await self.dengan_tulisan(self.buka(self.token(self.ani)))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(tulis, [])
        self.assertEqual((await self.baca(self.ani.id)).email_verified_at.replace(tzinfo=None),
                         TERVERIFIKASI.replace(tzinfo=None))
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    # --- POST: tombol "Verifikasi email" ---------------------------------------------------------------------------

    async def test_post_memverifikasi_dan_menghidupkan_lagi_7_hari(self):
        dua_hari = await self.laporan_dilewati(self.baru, hari=2)
        tanpa_email = await self.laporan_dilewati(self.baru, hari=6, alasan="tanpa_email", bulan=9)
        tua = await self.laporan_dilewati(self.baru, hari=30, bulan=8)
        dimatikan = await self.laporan_dilewati(self.baru, hari=2, alasan="dimatikan", bulan=7)
        orang_lain = await self.laporan_dilewati(self.tanpa, hari=2)
        r, tulis = await self.dengan_tulisan(self.konfirmasi(
            self.token(self.baru), content="apa=saja",   # badan tidak dibaca
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertTrue(tulis)   # pembanding untuk tes GET: perekam memang menangkap tulisan
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(dua_hari), ("menunggu", None))
        self.assertEqual(await self.status_laporan(tanpa_email), ("menunggu", None))
        self.assertEqual(await self.status_laporan(tua), ("dilewati", "belum_verifikasi"))
        self.assertEqual(await self.status_laporan(dimatikan), ("dilewati", "dimatikan"))
        self.assertEqual(await self.status_laporan(orang_lain), ("dilewati", "belum_verifikasi"))

    async def test_post_token_tidak_berlaku_303_tanpa_menulis(self):
        rid = await self.laporan_dilewati(self.baru)
        for nama, token in self.token_tidak_sah().items():
            with self.subTest(nama=nama):
                r, tulis = await self.dengan_tulisan(self.konfirmasi(token))
                self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("tidak_berlaku")))
                self.assertEqual(tulis, [])
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_post_user_terhapus_303_tanpa_menulis(self):
        token = self.token(self.baru)
        await self.hapus_user(self.baru)
        r, tulis = await self.dengan_tulisan(self.konfirmasi(token))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("tidak_berlaku")))
        self.assertEqual(tulis, [])

    async def test_post_email_berganti_303_berubah_tanpa_menulis(self):
        token = self.token(self.baru)
        await self.ganti_email(self.baru, "lain@example.com")
        rid = await self.laporan_dilewati(self.baru)
        r, tulis = await self.dengan_tulisan(self.konfirmasi(token))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berubah")))
        self.assertEqual(tulis, [])
        self.assertIsNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("dilewati", "belum_verifikasi"))

    async def test_post_dua_kali_tetap_berhasil_tanpa_efek_tambahan(self):
        rid = await self.laporan_dilewati(self.baru)
        token = self.token(self.baru)
        r = await self.konfirmasi(token)
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        waktu = (await self.baca(self.baru.id)).email_verified_at
        self.assertIsNotNone(waktu)
        # Antrean sempat mengklaim laporan yang dihidupkan lagi sebelum tombol ditekan lagi.
        async with self.Session() as db:
            await db.execute(update(Report).where(Report.id == rid).values(
                email_status="mengirim", email_percobaan=1, email_terakhir_at=datetime.now(timezone.utc)))
            await db.commit()
        sebelum = await self.baris_laporan(rid)
        r = await self.konfirmasi(token)
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertEqual((await self.baca(self.baru.id)).email_verified_at, waktu)
        self.assertEqual(await self.baris_laporan(rid), sebelum)

    async def test_email_beda_huruf_tetap_bisa_diverifikasi(self):
        token = self.token(self.baru)
        await self.ganti_email(self.baru, " Baru@Example.COM ")
        r = await self.buka(token)
        self.assertEqual(r.status_code, 200, r.text)   # alamat yang sama: halaman konfirmasi, bukan `berubah`
        r = await self.konfirmasi(token)
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)

    async def test_tombol_halaman_mengikuti_action(self):
        rid = await self.laporan_dilewati(self.baru)
        r = await self.buka(self.token(self.baru))
        r = await self.klien2.post(self.aksi_formulir(r.text), content="", follow_redirects=False,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)
        self.assertEqual(await self.status_laporan(rid), ("menunggu", None))
        # Tautan yang sama dibuka lagi: langsung ke Pengaturan dengan `berhasil`, tanpa halaman.
        r = await self.buka(self.token(self.baru))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))

    async def test_batas_30_per_menit_ember_get_dan_post_terpisah(self):
        batas = auth_route.limiter._route_limits
        for nama, scope in (("halaman_verifikasi_email", "verifikasi_email_get"),
                            ("konfirmasi_verifikasi_email", "verifikasi_email_post")):
            with self.subTest(nama=nama):
                self.assertEqual([(str(b.limit), b.scope) for b in batas[f"{rute.__name__}.{nama}"]],
                                 [("30 per 1 minute", scope)])
        auth_route.limiter.reset()
        auth_route.limiter.enabled = True
        kode = [(await self.buka("x")).status_code for _ in range(31)]
        self.assertEqual(kode, [303] * 30 + [429])
        # Ember GET habis (mis. pemindai tautan): tombol tetap memverifikasi, dengan ember 30/menit sendiri.
        r = await self.konfirmasi(self.token(self.baru))
        self.assertEqual((r.status_code, r.headers["location"]), (303, _lokasi("berhasil")))
        self.assertIsNotNone((await self.baca(self.baru.id)).email_verified_at)
        kode = [(await self.konfirmasi("x")).status_code for _ in range(30)]
        self.assertEqual(kode, [303] * 29 + [429])


class PemasanganTautanTests(unittest.TestCase):
    def test_get_dan_post_terpasang_dan_terdokumentasi(self):
        from app.main import app
        jalur = app.openapi()["paths"]["/auth/verifikasi-email"]
        get, post = jalur["get"], jalur["post"]
        self.assertEqual((get["tags"], post["tags"]), (["laporan"], ["laporan"]))
        self.assertIn("text/html", get["responses"]["200"]["content"])
        self.assertLessEqual({"200", "303", "429"}, set(get["responses"]))
        self.assertLessEqual({"303", "429"}, set(post["responses"]))
        self.assertNotIn("200", post["responses"])        # POST selalu mengalihkan ke Pengaturan
        self.assertNotIn("content", post["responses"]["303"])   # pengalihan tanpa badan
        self.assertNotIn("requestBody", post)             # badan tidak dibaca


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
