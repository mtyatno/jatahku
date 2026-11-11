"""Worker email laporan, Task 3: keadaan antrean dan alarm (`app/services/laporan/pantau_email.py`; spec
2026-11-11-worker-email-laporan bagian 6). SQLite berkas per tes (pola `test_laporan_antrean_email`); Redis dan
Telegram dipalsukan, tidak pernah menghubungi jaringan.
Run: python -m unittest app.tests.test_laporan_pantau_email -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import event
from sqlalchemy.orm import configure_mappers

from app.core.database import Base
from app.models.models import AppSetting, Report, ReportSettings, User
from app.services.laporan import antrean_email, pantau_email, worker_email

configure_mappers()

UTC = timezone.utc
MENIT = timedelta(minutes=1)
JAM = timedelta(hours=1)
HARI = timedelta(days=1)
T0 = datetime(2026, 11, 5, 12, 30, tzinfo=UTC)
KUNCI_GAGAL = "alarm_email_laporan:email_gagal"


class RedisPalsu:
    def __init__(self, nilai=None, galat=None):
        self.nilai, self.galat = nilai, galat

    async def get(self, kunci):
        assert kunci == worker_email.KUNCI_HIDUP
        if self.galat:
            raise self.galat
        return self.nilai


def tanda(waktu: datetime, sebagai_bytes: bool = True):
    teks = waktu.isoformat()
    return teks.encode() if sebagai_bytes else teks


def pengaturan(smtp_host="localhost"):
    return SimpleNamespace(SMTP_HOST=smtp_host, EMAIL_LAPORAN_PER_DETIK="3")


class PantauTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(folder) / 'pantau.db'}", poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)

        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.enterContext(patch.object(pantau_email, "get_settings", return_value=pengaturan()))
        self.nomor = 0

    # ------------------------------------------------------------------ bahan

    async def user(self, email=None, *, terverifikasi=True, email_on=None) -> uuid.UUID:
        self.nomor += 1
        async with self.Session() as db:
            u = User(name="U", email=email or f"u{self.nomor}@contoh.id")
            if terverifikasi:
                u.email_verified_at = T0 - 30 * HARI
            db.add(u)
            await db.flush()
            if email_on is not None:
                db.add(ReportSettings(user_id=u.id, kata_sandi_enc=None, email_on=email_on, kuartalan_on=True,
                                      tahunan_on=True))
            await db.commit()
            return u.id

    async def laporan(self, user_id, *, status, terbit=None, terakhir=None, terkirim=None):
        self.nomor += 1
        async with self.Session() as db:
            db.add(Report(
                user_id=user_id, household_id=None, jenis="bulanan", periode_mulai=datetime(2020, 1, 1).date() + self.nomor * HARI,
                periode_akhir=datetime(2020, 1, 1).date(), payday_day=1, data={}, terbit_at=terbit or T0 - 5 * MENIT,
                email_status=status, email_terakhir_at=terakhir, email_terkirim_at=terkirim,
            ))
            await db.commit()

    async def catat_alarm(self, kode, waktu):
        async with self.Session() as db:
            db.add(AppSetting(key=f"alarm_email_laporan:{kode}", value=waktu.isoformat()))
            await db.commit()

    async def baca_alarm(self, kode):
        async with self.Session() as db:
            baris = await db.get(AppSetting, f"alarm_email_laporan:{kode}")
            return None if baris is None else baris.value

    async def keadaan(self, redis=None, sekarang=T0) -> dict:
        async with self.Session() as db:
            return await pantau_email.keadaan_email(db, redis, sekarang)

    async def berlaku(self, redis=None, sekarang=T0) -> list[str]:
        async with self.Session() as db:
            k = await pantau_email.keadaan_email(db, redis, sekarang)
            return await pantau_email.alarm_berlaku(db, k, sekarang)

    async def periksa(self, kirim, redis=None, sekarang=T0, api_menyala=None) -> list[str]:
        async with self.Session() as db:
            return await pantau_email.periksa_alarm(db, redis, sekarang, kirim=kirim, api_menyala=api_menyala)

    # ------------------------------------------------------------------ keadaan

    async def test_keadaan_menghitung(self):
        a = await self.user()
        await self.user(email_on=None)                       # tanpa baris pengaturan: dihitung
        await self.user(email_on=False)                      # mati
        await self.user(terverifikasi=False)
        await self.user("deleted_abc@contoh.id")
        await self.user("banned_abc@contoh.id")
        await self.laporan(a, status="menunggu", terbit=T0 - 90 * MENIT)
        await self.laporan(a, status="menunggu", terbit=T0 - 400 * MENIT)
        await self.laporan(a, status="mengirim")
        for selisih in (1 * MENIT, 5 * JAM, 23 * JAM + 59 * MENIT):
            await self.laporan(a, status="terkirim", terkirim=T0 - selisih)
        await self.laporan(a, status="terkirim", terkirim=T0 - 24 * JAM - 1 * MENIT)
        await self.laporan(a, status="gagal", terakhir=T0 - 7 * HARI + 1 * MENIT)
        await self.laporan(a, status="gagal", terakhir=T0 - 7 * HARI - 1 * MENIT)
        await self.laporan(a, status="dilewati")
        k = await self.keadaan()
        self.assertEqual(
            {x: k[x] for x in ("menunggu", "tertua_menit", "mengirim", "terkirim_24_jam", "gagal_7_hari", "penerima")},
            {"menunggu": 2, "tertua_menit": 400, "mengirim": 1, "terkirim_24_jam": 3, "gagal_7_hari": 1,
             "penerima": 2},
        )
        self.assertEqual(
            set(k), {"worker_hidup", "worker_terakhir", "menunggu", "tertua_menit", "mengirim", "terkirim_24_jam",
                     "gagal_7_hari", "penerima", "ambang_penerima", "smtp_lokal", "laju_per_detik"})
        self.assertEqual((k["ambang_penerima"], k["smtp_lokal"], k["laju_per_detik"]), (300, True, 3.0))

    async def test_tanpa_menunggu_tertua_none(self):
        k = await self.keadaan()
        self.assertEqual((k["menunggu"], k["tertua_menit"], k["penerima"]), (0, None, 0))

    async def test_smtp_lokal(self):
        for host, lokal in (("localhost", True), ("  LocalHost ", True), ("127.0.0.1", True), ("::1", True),
                            ("smtp.contoh.id", False), ("", False)):
            with patch.object(pantau_email, "get_settings", return_value=pengaturan(host)):
                self.assertEqual((await self.keadaan())["smtp_lokal"], lokal, host)

    async def test_worker_hidup_dari_tanda(self):
        k = await self.keadaan(RedisPalsu(tanda(T0 - 5 * MENIT)))
        self.assertEqual((k["worker_hidup"], k["worker_terakhir"]), (True, (T0 - 5 * MENIT).isoformat()))
        k = await self.keadaan(RedisPalsu(tanda(T0 - 10 * MENIT)))       # tepat di batas: masih hidup
        self.assertTrue(k["worker_hidup"])
        k = await self.keadaan(RedisPalsu(tanda(T0 - 10 * MENIT - timedelta(seconds=1))))
        self.assertFalse(k["worker_hidup"])
        k = await self.keadaan(RedisPalsu(tanda(T0 - 11 * MENIT, sebagai_bytes=False)))   # str (klien decode)
        self.assertEqual((k["worker_hidup"], k["worker_terakhir"]), (False, (T0 - 11 * MENIT).isoformat()))
        for redis in (RedisPalsu(None), RedisPalsu(galat=ConnectionError("x")), None, RedisPalsu(b"bukan waktu")):
            k = await self.keadaan(redis)
            self.assertEqual((k["worker_hidup"], k["worker_terakhir"]), (False, None))

    # ------------------------------------------------------------------ alarm

    async def test_alarm_per_syarat(self):
        hidup = RedisPalsu(tanda(T0 - MENIT))
        self.assertEqual(await self.berlaku(hidup), [])
        self.assertEqual(await self.berlaku(None), ["worker_mati"])

        # pindah_penyedia: 300 penerima + SMTP lokal; 299 tidak; SMTP lain tidak.
        async with self.Session() as db:
            for i in range(299):
                db.add(User(name="U", email=f"p{i}@contoh.id"))
            await db.flush()
            await db.execute(User.__table__.update().values(email_verified_at=T0 - HARI))
            await db.commit()
        self.assertEqual(await self.berlaku(hidup), [])
        await self.user()
        self.assertEqual(await self.berlaku(hidup), ["pindah_penyedia"])
        with patch.object(pantau_email, "get_settings", return_value=pengaturan("smtp.contoh.id")):
            self.assertEqual(await self.berlaku(hidup), [])

        # antrean_tersendat: > 360 menit.
        u = await self.user(terverifikasi=False)
        await self.laporan(u, status="menunggu", terbit=T0 - 360 * MENIT)
        self.assertNotIn("antrean_tersendat", await self.berlaku(hidup))
        await self.laporan(u, status="menunggu", terbit=T0 - 361 * MENIT)
        self.assertIn("antrean_tersendat", await self.berlaku(hidup))

        # email_gagal: gagal baru (dalam 24 jam bila belum pernah dikirim).
        self.assertNotIn("email_gagal", await self.berlaku(hidup))
        await self.laporan(u, status="gagal", terakhir=T0 - 24 * JAM - MENIT)
        self.assertNotIn("email_gagal", await self.berlaku(hidup))
        await self.laporan(u, status="gagal", terakhir=T0 - 24 * JAM + MENIT)
        self.assertIn("email_gagal", await self.berlaku(hidup))

    async def test_email_gagal_hanya_yang_baru(self):
        u = await self.user()
        hidup = RedisPalsu(tanda(T0 - MENIT))
        await self.laporan(u, status="gagal", terakhir=T0 - 3 * JAM)
        await self.catat_alarm("email_gagal", T0 - 2 * JAM)
        self.assertNotIn("email_gagal", await self.berlaku(hidup))   # gagal sebelum alarm terakhir
        await self.laporan(u, status="gagal", terakhir=T0 - 1 * JAM)
        self.assertIn("email_gagal", await self.berlaku(hidup))
        # Alarm terakhir 3 hari lalu: batasnya alarm itu, bukan 24 jam.
        await self.catat_alarm_ulang("email_gagal", T0 - 3 * HARI)
        self.assertIn("email_gagal", await self.berlaku(hidup))

    async def catat_alarm_ulang(self, kode, waktu):
        async with self.Session() as db:
            (await db.get(AppSetting, f"alarm_email_laporan:{kode}")).value = waktu.isoformat()
            await db.commit()

    async def test_batas_ulang_dan_pencatatan(self):
        kirim = AsyncMock(return_value=True)
        self.assertEqual(await self.periksa(kirim), ["worker_mati"])
        self.assertEqual(kirim.await_count, 1)
        self.assertEqual(await self.baca_alarm("worker_mati"), T0.isoformat())
        # Jam berikutnya: tidak dikirim lagi; 23 jam 59 menit juga belum.
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + JAM), [])
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + 24 * JAM - MENIT), [])
        self.assertEqual(kirim.await_count, 1)
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + 24 * JAM), ["worker_mati"])
        self.assertEqual(kirim.await_count, 2)
        self.assertEqual(await self.baca_alarm("worker_mati"), (T0 + 24 * JAM).isoformat())

    async def test_pindah_penyedia_ulang_30_hari(self):
        async with self.Session() as db:
            for i in range(300):
                db.add(User(name="U", email=f"q{i}@contoh.id"))
            await db.flush()
            await db.execute(User.__table__.update().values(email_verified_at=T0 - HARI))
            await db.commit()
        hidup = RedisPalsu(tanda(T0 - MENIT))
        kirim = AsyncMock(return_value=True)
        self.assertEqual(await self.periksa(kirim, hidup), ["pindah_penyedia"])
        def hidup_pada(waktu):
            return RedisPalsu(tanda(waktu - MENIT))
        waktu = T0 + 30 * HARI - MENIT
        self.assertEqual(await self.periksa(kirim, hidup_pada(waktu), sekarang=waktu), [])
        waktu = T0 + 30 * HARI
        self.assertEqual(await self.periksa(kirim, hidup_pada(waktu), sekarang=waktu), ["pindah_penyedia"])

    async def test_kirim_gagal_tidak_dicatat_dan_dicoba_lagi(self):
        kirim = AsyncMock(return_value=False)
        self.assertEqual(await self.periksa(kirim), [])
        self.assertIsNone(await self.baca_alarm("worker_mati"))
        kirim = AsyncMock(side_effect=RuntimeError("putus"))
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + JAM), [])
        self.assertIsNone(await self.baca_alarm("worker_mati"))
        kirim = AsyncMock(return_value=True)
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + 2 * JAM), ["worker_mati"])
        self.assertEqual(await self.baca_alarm("worker_mati"), (T0 + 2 * JAM).isoformat())

    async def test_masa_tenang_worker_mati(self):
        kirim = AsyncMock(return_value=True)
        self.assertEqual(await self.periksa(kirim, api_menyala=T0 - 5 * MENIT), [])
        self.assertEqual(await self.periksa(kirim, api_menyala=T0 - 15 * MENIT + timedelta(seconds=1)), [])
        self.assertEqual(kirim.await_count, 0)
        self.assertEqual(await self.periksa(kirim, api_menyala=T0 - 16 * MENIT), ["worker_mati"])
        # Tanpa waktu menyala: tidak ada masa tenang. Naive dianggap UTC.
        self.assertEqual(await self.periksa(kirim, sekarang=T0 + 2 * HARI, api_menyala=None), ["worker_mati"])
        self.assertEqual(
            await self.periksa(kirim, sekarang=T0 + 4 * HARI, api_menyala=(T0 + 4 * HARI - 5 * MENIT).replace(tzinfo=None)),
            [])

    async def test_alarm_lain_tetap_terkirim_saat_masa_tenang(self):
        u = await self.user()
        await self.laporan(u, status="menunggu", terbit=T0 - 400 * MENIT)
        kirim = AsyncMock(return_value=True)
        self.assertEqual(await self.periksa(kirim, api_menyala=T0 - MENIT), ["antrean_tersendat"])

    # ------------------------------------------------------------------ pesan

    def test_pesan_tanpa_alamat(self):
        k = {"penerima": 312, "menunggu": 7, "tertua_menit": 400, "gagal_7_hari": 2,
             "worker_terakhir": datetime(2026, 11, 5, 17, 5, tzinfo=UTC).isoformat()}
        for kode in pantau_email.ULANG:
            self.assertNotIn("@", pantau_email.pesan_alarm(kode, k))
        p = pantau_email.pesan_alarm("pindah_penyedia", k)
        self.assertIn("312", p)
        self.assertIn("AGENTS.md", p)
        self.assertEqual(
            p, "📬 Penerima email laporan sudah 312. Saatnya pindah ke penyedia email transaksional — langkahnya di "
               "AGENTS.md bagian 'Pindah penyedia email'.")
        self.assertEqual(
            pantau_email.pesan_alarm("worker_mati", k),
            "⚠️ Worker email laporan tidak memberi tanda hidup sejak 00:05 WIB. Cek: sudo systemctl status jatahku-worker")
        self.assertEqual(
            pantau_email.pesan_alarm("worker_mati", {**k, "worker_terakhir": None}),
            "⚠️ Worker email laporan tidak memberi tanda hidup. Cek: sudo systemctl status jatahku-worker")
        self.assertEqual(
            pantau_email.pesan_alarm("antrean_tersendat", k),
            "⚠️ Antrean email laporan tersendat: 7 menunggu, tertua 6 jam. Cek: sudo journalctl -u jatahku-worker -n 50")
        self.assertEqual(
            pantau_email.pesan_alarm("email_gagal", k),
            '⚠️ Ada email laporan yang gagal dikirim (2 dalam 7 hari). Periksa SMTP, lalu ikuti "kirim ulang email" '
            "di docs/laporan-berkala.md.")

    def test_konstanta(self):
        self.assertEqual(
            (pantau_email.AMBANG_PENERIMA, pantau_email.BATAS_HIDUP, pantau_email.BATAS_TERSENDAT_MENIT,
             pantau_email.MASA_TENANG, pantau_email.API_MENYALA, antrean_email.AWALAN_AKUN_NONAKTIF),
            (300, timedelta(minutes=10), 360, timedelta(minutes=15), None, ("deleted_", "banned_")))
        self.assertEqual(pantau_email.ULANG, {"pindah_penyedia": 30 * HARI, "worker_mati": 24 * JAM,
                                              "antrean_tersendat": 24 * JAM, "email_gagal": 24 * JAM})


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    def tambal(self, token="tok", admin="42"):
        return patch.object(pantau_email, "get_settings",
                            return_value=SimpleNamespace(TELEGRAM_BOT_TOKEN=token, ADMIN_TELEGRAM_ID=admin))

    async def test_terkirim_tanpa_parse_mode(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with self.tambal(), patch("telegram.Bot", return_value=bot) as kelas:
            self.assertTrue(await pantau_email.kirim_telegram_admin("halo"))
        kelas.assert_called_once_with(token="tok")
        bot.send_message.assert_awaited_once_with(chat_id=42, text="halo")

    async def test_kosong_atau_galat_false_tanpa_isi_pesan(self):
        with self.tambal(token=""), patch("telegram.Bot") as kelas:
            self.assertFalse(await pantau_email.kirim_telegram_admin("rahasia-isi"))
            kelas.assert_not_called()
        with self.tambal(admin=""), patch("telegram.Bot") as kelas:
            self.assertFalse(await pantau_email.kirim_telegram_admin("rahasia-isi"))
            kelas.assert_not_called()
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("rahasia-isi putus"))
        with self.tambal(), patch("telegram.Bot", return_value=bot), self.assertLogs("jatahku.laporan", "WARNING") as log:
            self.assertFalse(await pantau_email.kirim_telegram_admin("rahasia-isi"))
        self.assertNotIn("rahasia-isi", "\n".join(log.output))


if __name__ == "__main__":
    unittest.main()
