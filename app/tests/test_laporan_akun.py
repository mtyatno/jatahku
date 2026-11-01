"""Laporan berkala tahap 1, Task 8: laporan dan pengaturan laporan ikut hapus akun dan gabung akun
(spec 2026-11-01-laporan-berkala-design, bagian 8 dan 10).

FK `reports.user_id` dan `report_settings.user_id` CASCADE, `reports.household_id` SET NULL, jadi di Postgres
hapus user dan hapus household tidak gagal tanpa kode tambahan. Yang tetap butuh kode eksplisit:
- hapus akun: baris tingkat-user dihapus eksplisit (pola `account_deletion`), tidak bergantung pada aksi FK;
  household yang ikut terhapus melepas `household_id` laporan mantan anggota secara eksplisit;
- gabung akun: laporan dan pengaturan sumber DIPINDAH ke target (CASCADE membuangnya saat akun sumber dihapus),
  dan `household_id` yang menunjuk household yang dibuang ikut ke yang dipertahankan (SET NULL melepasnya).

Semuanya dicoba di SQLite sungguhan dengan FK menyala, jadi aksi CASCADE/SET NULL nyata (pola
`test_account_deletion.py`). Varian "tanpa aksi FK" mematikan FK supaya hanya kode eksplisit yang bekerja.
Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_laporan_akun -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event, func, select
from sqlalchemy.orm import configure_mappers

from app.core.database import Base
from app.models.models import (
    JENIS_BULANAN, Envelope, Household, HouseholdMember, HouseholdRole, Report, ReportSettings, Transaction, User,
)
from app.services import account_deletion
from app.services.account_deletion import FORMER_MEMBER_ID
from app.services.merge import merge_users

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

# Bukan token Fernet sungguhan: tidak pernah didekripsi di sini, hanya dibandingkan antar-akun.
TOKEN_SUMBER = "token-palsu-sumber"
TOKEN_TARGET = "token-palsu-target"
TOKEN_SARI = "token-palsu-sari"
TOKEN_BUDI = "token-palsu-budi"
TOKEN_ANDI = "token-palsu-andi"

AGU, SEP, OKT = date(2026, 8, 25), date(2026, 9, 25), date(2026, 10, 25)
KUARTALAN = "kuartalan"


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class LaporanAkunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)  # juga bila setUp gagal (aiosqlite menggantung)

        # Postgres menegakkan FK dan aksinya (CASCADE, SET NULL); tanpa ini SQLite meloloskan semuanya.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    # ── helper ────────────────────────────────────────────────────────────
    async def add_user(self, name, *, email=None, telegram_id=None, household=None, role=HouseholdRole.owner):
        """User + rumah sendiri (atau gabung `household`). Mengembalikan (user_id, household_id)."""
        async with self.Session() as db:
            u = User(name=name, email=email, telegram_id=telegram_id)
            db.add(u)
            await db.flush()
            if household is None:
                hh = Household(name=f"Rumah {name}")
                db.add(hh)
                await db.flush()
                household = hh.id
            db.add(HouseholdMember(user_id=u.id, household_id=household, role=role))
            await db.commit()
            return u.id, household

    async def add_report(self, user_id, household_id, mulai, *, jenis=JENIS_BULANAN, tanda):
        """Laporan terbit; `tanda` (di `data`) menunjukkan laporan siapa/yang mana, untuk dibandingkan sesudahnya."""
        async with self.Session() as db:
            r = Report(user_id=user_id, household_id=household_id, jenis=jenis, periode_mulai=mulai,
                       periode_akhir=mulai + timedelta(days=29), payday_day=mulai.day,
                       data={"versi": 1, "judul": f"Laporan {mulai.isoformat()}", "tanda": tanda})
            db.add(r)
            await db.commit()
            return r.id

    async def add_settings(self, user_id, token, **kw):
        async with self.Session() as db:
            db.add(ReportSettings(user_id=user_id, kata_sandi_enc=token, **kw))
            await db.commit()

    async def reports_of(self, user_id):
        """{(jenis, awal periode): (id, household_id, tanda)} laporan milik user."""
        async with self.Session() as db:
            rows = (await db.execute(select(Report).where(Report.user_id == user_id))).scalars().all()
        return {(r.jenis, r.periode_mulai): (r.id, r.household_id, r.data["tanda"]) for r in rows}

    async def settings_of(self, user_id):
        """(token, email_on, kuartalan_on, tahunan_on) pengaturan laporan user, None bila tidak punya."""
        async with self.Session() as db:
            s = await db.get(ReportSettings, user_id)
        return None if s is None else (s.kata_sandi_enc, s.email_on, s.kuartalan_on, s.tahunan_on)

    async def count(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    async def get(self, model, pk):
        async with self.Session() as db:
            return await db.get(model, pk)

    async def foreign_keys(self, on: bool):
        """FK di koneksi StaticPool (satu-satunya koneksi) dinyalakan/dimatikan. Dengan FK menyala, CASCADE/SET NULL
        ikut membereskan baris laporan, jadi hanya varian tanpa FK yang membuktikan kode eksplisitnya."""
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
            self.assertEqual((await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar(), int(on))

    async def hapus(self, user_id):
        async with self.Session() as db:
            await account_deletion.delete_account(db, await db.get(User, user_id))

    async def pasangan(self, n=""):
        """Akun bot (sumber, ber-Telegram) dan akun web (target), masing-masing dengan rumahnya sendiri.
        Mengembalikan (sumber, rumah sumber, target, rumah target)."""
        sumber, hh_sumber = await self.add_user(f"Bot{n}", telegram_id=f"777{n}")
        target, hh_target = await self.add_user(f"Web{n}", email=f"web{n}@contoh.test")
        return sumber, hh_sumber, target, hh_target

    async def gabung(self, sumber, target, keep):
        async with self.Session() as db:
            hasil = await merge_users(sumber, target, keep, db)
        self.assertEqual(hasil.get("status"), "merged", hasil)
        self.assertIsNone(await self.get(User, sumber))
        return hasil

    # ── hapus akun ────────────────────────────────────────────────────────
    async def skenario_hapus_akun(self, *, fk):
        sari, hh_sari = await self.add_user("Sari", email="sari@contoh.test")
        budi, hh_budi = await self.add_user("Budi", email="budi@contoh.test")
        await self.add_report(sari, hh_sari, AGU, tanda="sari-agu")
        await self.add_report(sari, hh_sari, SEP, tanda="sari-sep")
        r_budi = await self.add_report(budi, hh_budi, SEP, tanda="budi")
        await self.add_settings(sari, TOKEN_SARI, email_on=False)
        await self.add_settings(budi, TOKEN_BUDI)
        await self.foreign_keys(fk)

        await self.hapus(sari)

        self.assertIsNone(await self.get(User, sari))
        self.assertEqual(await self.count(Report, Report.user_id == sari), 0)
        self.assertEqual(await self.count(ReportSettings, ReportSettings.user_id == sari), 0)
        # User lain tidak tersentuh: laporan, rumah, dan pengaturannya utuh.
        self.assertEqual(await self.reports_of(budi), {(JENIS_BULANAN, SEP): (r_budi, hh_budi, "budi")})
        self.assertEqual(await self.settings_of(budi), (TOKEN_BUDI, True, True, True))
        self.assertEqual(await self.count(Report), 1)
        self.assertEqual(await self.count(ReportSettings), 1)

    async def test_hapus_akun_menghapus_laporan_dan_pengaturan(self):
        await self.skenario_hapus_akun(fk=True)

    async def test_hapus_akun_menghapus_laporan_dan_pengaturan_tanpa_aksi_fk(self):
        # CASCADE tidak jalan: hanya daftar hapus eksplisit di delete_account yang membuang barisnya.
        await self.skenario_hapus_akun(fk=False)

    async def skenario_mantan_anggota(self, *, fk):
        sari, hh = await self.add_user("Sari", email="sari@contoh.test")        # satu-satunya anggota rumah
        budi, hh_budi = await self.add_user("Budi", email="budi@contoh.test")   # dulu anggota rumah Sari, kini pindah
        await self.add_report(sari, hh, SEP, tanda="sari")
        r_lama = await self.add_report(budi, hh, AGU, tanda="budi-lama")        # terbit saat Budi di rumah Sari
        r_baru = await self.add_report(budi, hh_budi, SEP, tanda="budi-baru")
        await self.add_settings(budi, TOKEN_BUDI)
        await self.foreign_keys(fk)

        await self.hapus(sari)

        self.assertIsNone(await self.get(Household, hh))
        # Laporan mantan anggota tetap ada, utuh, hanya tautan ke rumah yang sudah dihapus yang dilepas.
        self.assertEqual(await self.reports_of(budi), {
            (JENIS_BULANAN, AGU): (r_lama, None, "budi-lama"),
            (JENIS_BULANAN, SEP): (r_baru, hh_budi, "budi-baru"),
        })
        self.assertEqual(await self.settings_of(budi), (TOKEN_BUDI, True, True, True))
        self.assertEqual(await self.count(Report, Report.user_id == sari), 0)
        self.assertIsNotNone(await self.get(Household, hh_budi))

    async def test_hapus_household_menyisakan_laporan_mantan_anggota_dengan_household_null(self):
        await self.skenario_mantan_anggota(fk=True)

    async def test_hapus_household_menyisakan_laporan_mantan_anggota_dengan_household_null_tanpa_aksi_fk(self):
        # SET NULL tidak jalan: tanpa pelepasan eksplisit di _delete_household laporan Budi menunjuk rumah yang
        # sudah tidak ada.
        await self.skenario_mantan_anggota(fk=False)

    async def test_hapus_anggota_household_bersama_hanya_membuang_laporan_miliknya(self):
        # Rumah masih punya anggota lain, jadi tidak dihapus: laporan Andi tetap menunjuk rumahnya, dan
        # laporan/pengaturan Sari dibuang (bukan dipindah ke "Mantan anggota").
        andi, hh = await self.add_user("Andi", email="andi@contoh.test")
        sari, _ = await self.add_user("Sari", email="sari@contoh.test", household=hh, role=HouseholdRole.member)
        async with self.Session() as db:
            dapur = Envelope(household_id=hh, name="Dapur")
            db.add(dapur)
            await db.flush()
            db.add(Transaction(envelope_id=dapur.id, user_id=sari, amount=Decimal("75000"), description="sayur pasar"))
            await db.commit()
        r_andi = await self.add_report(andi, hh, SEP, tanda="andi")
        await self.add_report(sari, hh, SEP, tanda="sari")
        await self.add_settings(andi, TOKEN_ANDI)
        await self.add_settings(sari, TOKEN_SARI)

        await self.hapus(sari)

        self.assertIsNotNone(await self.get(Household, hh))
        # Jalur "Mantan anggota" benar-benar jalan (catatan di amplop bersama dianonimkan), laporan tidak ikut.
        self.assertEqual(await self.count(Transaction, Transaction.user_id == FORMER_MEMBER_ID), 1)
        self.assertEqual(await self.count(Report, Report.user_id.in_([sari, FORMER_MEMBER_ID])), 0)
        self.assertEqual(await self.count(ReportSettings, ReportSettings.user_id.in_([sari, FORMER_MEMBER_ID])), 0)
        self.assertEqual(await self.reports_of(andi), {(JENIS_BULANAN, SEP): (r_andi, hh, "andi")})
        self.assertEqual(await self.settings_of(andi), (TOKEN_ANDI, True, True, True))

    # ── gabung akun ───────────────────────────────────────────────────────
    async def test_gabung_memindahkan_laporan(self):
        # Rumah target dipertahankan, rumah sumber dibuang: laporan sumber pindah ke target (id yang sama, bukan
        # salinan) dan yang menunjuk rumah sumber ikut ke rumah target. Tanpa pemindahan eksplisit, CASCADE
        # membuangnya bersama akun sumber; tanpa pengalihan eksplisit, SET NULL melepas tautannya.
        sumber, hh_s, target, hh_t = await self.pasangan()
        s_agu = await self.add_report(sumber, hh_s, AGU, tanda="sumber-agu")
        s_sep = await self.add_report(sumber, hh_s, SEP, tanda="sumber-sep")
        t_okt = await self.add_report(target, hh_t, OKT, tanda="target-okt")

        await self.gabung(sumber, target, hh_t)

        self.assertIsNone(await self.get(Household, hh_s))
        self.assertEqual(await self.reports_of(target), {
            (JENIS_BULANAN, AGU): (s_agu, hh_t, "sumber-agu"),
            (JENIS_BULANAN, SEP): (s_sep, hh_t, "sumber-sep"),
            (JENIS_BULANAN, OKT): (t_okt, hh_t, "target-okt"),
        })
        self.assertEqual(await self.count(Report), 3)

    async def test_gabung_memindahkan_laporan_saat_rumah_sumber_dipertahankan(self):
        # Kebalikannya: rumah sumber dipertahankan, rumah target dibuang. Laporan target sendiri yang menunjuk
        # rumah target ikut ke rumah sumber; laporan sumber yang sudah di rumah yang dipertahankan tidak berubah.
        sumber, hh_s, target, hh_t = await self.pasangan()
        s_agu = await self.add_report(sumber, hh_s, AGU, tanda="sumber-agu")
        t_sep = await self.add_report(target, hh_t, SEP, tanda="target-sep")

        await self.gabung(sumber, target, hh_s)

        self.assertIsNone(await self.get(Household, hh_t))
        self.assertIsNotNone(await self.get(Household, hh_s))
        self.assertEqual(await self.reports_of(target), {
            (JENIS_BULANAN, AGU): (s_agu, hh_s, "sumber-agu"),
            (JENIS_BULANAN, SEP): (t_sep, hh_s, "target-sep"),
        })

    async def test_gabung_di_household_yang_sama_tidak_mengubah_household_laporan(self):
        # Kedua akun anggota rumah yang sama: tidak ada rumah yang dibuang, jadi tautan laporan tidak berubah.
        sumber, hh = await self.add_user("Bot", telegram_id="777")
        target, _ = await self.add_user("Web", email="web@contoh.test", household=hh, role=HouseholdRole.member)
        s_agu = await self.add_report(sumber, hh, AGU, tanda="sumber-agu")
        t_sep = await self.add_report(target, hh, SEP, tanda="target-sep")

        await self.gabung(sumber, target, hh)

        self.assertIsNotNone(await self.get(Household, hh))
        self.assertEqual(await self.reports_of(target), {
            (JENIS_BULANAN, AGU): (s_agu, hh, "sumber-agu"),
            (JENIS_BULANAN, SEP): (t_sep, hh, "target-sep"),
        })

    async def test_gabung_laporan_anggota_lain_di_household_yang_dibuang_ikut_dialihkan(self):
        # Seperti amplop, pemasukan, dan cocokkan saldo di langkah 4 gabung akun, laporan yang menunjuk rumah yang
        # dibuang pindah seluruhnya ke rumah yang dipertahankan, bukan hanya milik kedua akun yang digabung.
        # Pemiliknya tidak berubah (laporan itu tetap milik anggota tersebut).
        sumber, hh_s, target, hh_t = await self.pasangan()
        lain, _ = await self.add_user("Lain", email="lain@contoh.test", household=hh_s, role=HouseholdRole.member)
        r_lain = await self.add_report(lain, hh_s, SEP, tanda="lain")

        await self.gabung(sumber, target, hh_t)

        self.assertEqual(await self.reports_of(lain), {(JENIS_BULANAN, SEP): (r_lain, hh_t, "lain")})
        self.assertEqual(await self.count(Report, Report.user_id == target), 0)

    async def test_gabung_laporan_bentrok_milik_sumber_dihapus(self):
        # Kunci unik laporan: (user, jenis, awal periode). Laporan sumber yang bentrok dengan milik target
        # dibuang dan milik target tidak disentuh; selebihnya (periode lain, atau jenis lain di tanggal yang sama)
        # pindah. Tanpa penghapusan eksplisit, pemindahan melanggar kunci unik dan seluruh gabung akun gagal.
        sumber, hh_s, target, hh_t = await self.pasangan()
        s_agu = await self.add_report(sumber, hh_s, AGU, tanda="sumber-agu")
        s_sep = await self.add_report(sumber, hh_s, SEP, tanda="sumber-sep")
        s_kuartal = await self.add_report(sumber, hh_s, SEP, jenis=KUARTALAN, tanda="sumber-kuartal")
        t_sep = await self.add_report(target, hh_t, SEP, tanda="target-sep")
        t_okt = await self.add_report(target, hh_t, OKT, tanda="target-okt")

        await self.gabung(sumber, target, hh_t)

        self.assertIsNone(await self.get(Report, s_sep))
        self.assertEqual(await self.reports_of(target), {
            (JENIS_BULANAN, AGU): (s_agu, hh_t, "sumber-agu"),
            (JENIS_BULANAN, SEP): (t_sep, hh_t, "target-sep"),       # milik target utuh: id dan isinya
            (JENIS_BULANAN, OKT): (t_okt, hh_t, "target-okt"),
            (KUARTALAN, SEP): (s_kuartal, hh_t, "sumber-kuartal"),   # jenis lain tidak bentrok
        })
        self.assertEqual(await self.count(Report), 4)

    async def test_gabung_pengaturan(self):
        # Target belum punya pengaturan laporan: milik sumber (kata sandi PDF dan saklarnya) pindah ke target.
        # Tanpa pemindahan eksplisit, CASCADE membuangnya bersama akun sumber.
        sumber, _, target, hh_t = await self.pasangan()
        await self.add_settings(sumber, TOKEN_SUMBER, email_on=False, kuartalan_on=False)

        await self.gabung(sumber, target, hh_t)

        self.assertEqual(await self.settings_of(target), (TOKEN_SUMBER, False, False, True))
        self.assertEqual(await self.count(ReportSettings), 1)

    async def test_gabung_pengaturan_milik_sumber_dihapus_bila_target_sudah_punya(self):
        # Satu baris per user (user_id kunci utama): milik target menang dan tidak berubah sedikit pun.
        # Tanpa penghapusan eksplisit, pemindahan melanggar kunci utama dan seluruh gabung akun gagal.
        sumber, _, target, hh_t = await self.pasangan()
        await self.add_settings(sumber, TOKEN_SUMBER, email_on=False, kuartalan_on=False)
        await self.add_settings(target, TOKEN_TARGET, tahunan_on=False)

        await self.gabung(sumber, target, hh_t)

        self.assertEqual(await self.settings_of(target), (TOKEN_TARGET, True, True, False))
        self.assertEqual(await self.count(ReportSettings), 1)

    async def test_gabung_tanpa_pengaturan_sumber_tidak_mengubah_milik_target(self):
        sumber, _, target, hh_t = await self.pasangan()
        await self.add_settings(target, TOKEN_TARGET)

        await self.gabung(sumber, target, hh_t)

        self.assertEqual(await self.settings_of(target), (TOKEN_TARGET, True, True, True))
        self.assertEqual(await self.count(ReportSettings), 1)


if __name__ == "__main__":
    unittest.main()
