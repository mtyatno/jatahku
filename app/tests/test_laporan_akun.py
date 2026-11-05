"""Laporan berkala tahap 1, Task 8: laporan dan pengaturan laporan ikut hapus akun dan gabung akun
(spec 2026-11-01-laporan-berkala-design, bagian 8 dan 10).

FK `reports.user_id` dan `report_settings.user_id` CASCADE, `reports.household_id` SET NULL, jadi di Postgres
hapus user dan hapus household tidak gagal tanpa kode tambahan. Yang tetap butuh kode eksplisit:
- hapus akun: baris tingkat-user dihapus eksplisit (pola `account_deletion`), tidak bergantung pada aksi FK;
  household yang ikut terhapus melepas `household_id` laporan mantan anggota secara eksplisit;
- gabung akun: laporan dan pengaturan sumber DIPINDAH ke target (CASCADE membuangnya saat akun sumber dihapus),
  dan `household_id` yang menunjuk household yang dibuang ikut ke yang dipertahankan (SET NULL melepasnya).

Ruling R15: laporan beku penerima lain memuat nama (`pencatat`) dan teks catatan anggota yang menghapus akun. Baris
seperti itu membawa `pencatat_id`; hapus akun menulis ulang PERSIS baris yang `pencatat_id`-nya akun itu menjadi
"Mantan anggota" (sama dengan catatan hidupnya), dan gabung akun mengalihkan `pencatat_id` sumber ke target. Tes murni
penulis ulang (`PencatatLaporanTests`) tanpa DB; sisanya di SQLite seperti di atas.

Semuanya dicoba di SQLite sungguhan dengan FK menyala, jadi aksi CASCADE/SET NULL nyata (pola
`test_account_deletion.py`). Varian "tanpa aksi FK" mematikan FK supaya hanya kode eksplisit yang bekerja.
Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_laporan_akun -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import importlib.util
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import event, func, select
from sqlalchemy.orm import configure_mappers

from app.core.database import Base
from app.models.models import (
    JENIS_BULANAN, Allocation, BalanceCheck, Envelope, Household, HouseholdMember, HouseholdRole, Income,
    MonthlySnapshot, Report, ReportSettings, Transaction, User,
)
from app.services import account_deletion
from app.services.account_deletion import (
    ANON_INCOME_DESC, ANON_TXN_DESC, FORMER_MEMBER_ID, FORMER_MEMBER_NAME,
)
from app.services.laporan import pencatat
from app.services.laporan.muat import muat_bahan
from app.services.laporan.susun import susun_bulanan
from app.services.merge import merge_users
from app.services.visibility import PRIVATE_PLACEHOLDER
from app.tests.test_laporan_susun import ID_ANI, ID_BUDI, UANG, bahan, d, txn

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
UTC = timezone.utc
OKT1, OKT31 = date(2026, 10, 1), date(2026, 10, 31)
MANTAN = str(FORMER_MEMBER_ID)
PENGGANTI = dict(id_pengganti=MANTAN, nama_pengganti=FORMER_MEMBER_NAME, teks_pengeluaran=ANON_TXN_DESC,
                 teks_pemasukan=ANON_INCOME_DESC)


def uang_per_jalur(nilai, jalur="data") -> dict:
    """{jalur: teks uang} untuk setiap nominal di `nilai`. Menurut jalur, bukan urutan: JSONB PostgreSQL menyimpan kunci
    kamus dalam urutannya sendiri, jadi daftar nominal menurut urutan kunci berbeda antara SQLite dan PostgreSQL."""
    if isinstance(nilai, dict):
        return {j: u for k, v in nilai.items() for j, u in uang_per_jalur(v, f"{jalur}.{k}").items()}
    if isinstance(nilai, list):
        return {j: u for i, v in enumerate(nilai) for j, u in uang_per_jalur(v, f"{jalur}[{i}]").items()}
    return {jalur: nilai} if isinstance(nilai, str) and UANG.match(nilai) else {}


def baris_mutasi(hari, keterangan, jumlah, oleh, oleh_id, *, arah="keluar", amplop="Kebutuhan", penyesuaian=False):
    """Satu baris `mutasi` seperti yang dibekukan `susun_bulanan` (Oktober 2026)."""
    return {"tanggal": f"2026-10-{hari:02d}", "arah": arah, "amplop": amplop, "keterangan": keterangan,
            "jumlah": jumlah, "pencatat": oleh, "pencatat_id": oleh_id, "penyesuaian": penyesuaian}


def baris_terbesar(hari, keterangan, jumlah, oleh, oleh_id):
    return {"tanggal": f"2026-10-{hari:02d}", "amplop": "Kebutuhan", "keterangan": keterangan, "jumlah": jumlah,
            "pencatat": oleh, "pencatat_id": oleh_id}


def baris_terbayar(hari, nama, jumlah, oleh_id):
    return {"tanggal": f"2026-10-{hari:02d}", "nama": nama, "amplop": "Kebutuhan", "jumlah": jumlah,
            "pencatat_id": oleh_id}


class PencatatLaporanTests(unittest.TestCase):
    """Penulis ulang murni (`pencatat.anonimkan_data`, `pencatat.alihkan_data`) atas `data` v1 dari penyusun."""

    def data_campur(self):
        """Laporan Ani: catatan Ani dan Budi di mutasi dan terbesar, tagihan keduanya, dan transaksi privat Budi."""
        return susun_bulanan(bahan(transaksi=[
            txn(id="a1", tanggal=d(2), jumlah=Decimal(150_000), keterangan="Belanja bulanan"),
            txn(id="b1", tanggal=d(3), jumlah=Decimal(90_000), keterangan="Makan siang", pencatat="Budi",
                milik_penerima=False),
            txn(id="b2", tanggal=d(4), jumlah=Decimal(55_000), keterangan="🔄 Spotify", pencatat="Budi",
                milik_penerima=False, tagihan=True),
            txn(id="b3", tanggal=d(5), jumlah=Decimal(45_000), keterangan=PRIVATE_PLACEHOLDER, pencatat="Budi",
                milik_penerima=False),
            txn(id="b4", tanggal=d(6), jumlah=Decimal(7_000), keterangan="Selisih", pencatat="Budi",
                milik_penerima=False, penyesuaian=True),
            txn(id="a2", tanggal=d(12), jumlah=Decimal(54_000), keterangan="🔄 Netflix", tagihan=True),
        ]))

    def test_anonimkan_persis_baris_pencatat_itu(self):
        data = self.data_campur()
        asli = copy.deepcopy(data)

        baru = pencatat.anonimkan_data(data, ID_BUDI, **PENGGANTI)

        self.assertEqual(data, asli)  # masukan tidak diubah: hasilnya objek baru
        self.assertEqual([(m["keterangan"], m["pencatat"], m["pencatat_id"]) for m in baru["mutasi"]
                          if m["arah"] == "keluar"], [
            ("Belanja bulanan", "Ani", ID_ANI),
            (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN),
            (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN),
            (PRIVATE_PLACEHOLDER, FORMER_MEMBER_NAME, MANTAN),  # privat tetap privat, seperti aplikasi menampilkannya
            (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN),         # penyesuaian saldo juga
            ("🔄 Netflix", "Ani", ID_ANI),
        ])
        self.assertEqual([(t["keterangan"], t["pencatat"], t["pencatat_id"]) for t in baru["terbesar"]], [
            ("Belanja bulanan", "Ani", ID_ANI), (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN),
            (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN), ("🔄 Netflix", "Ani", ID_ANI),
            (PRIVATE_PLACEHOLDER, FORMER_MEMBER_NAME, MANTAN),
        ])
        # Tagihan: nama langganan dari keterangan pembayarnya ikut dianonimkan (catatan hidupnya kehilangan penanda).
        self.assertEqual([(t["nama"], t["pencatat_id"]) for t in baru["langganan"]["terbayar"]],
                         [(ANON_TXN_DESC, MANTAN), ("Netflix", ID_ANI)])
        # Selain baris itu tidak ada yang berubah; nominal di mana pun tetap.
        for kunci in set(asli) - {"mutasi", "terbesar", "langganan"}:
            self.assertEqual(baru[kunci], asli[kunci], kunci)
        self.assertEqual(baru["langganan"]["jatuh_tempo"], asli["langganan"]["jatuh_tempo"])
        self.assertEqual(uang_per_jalur(baru), uang_per_jalur(asli))
        self.assertEqual([m["jumlah"] for m in baru["mutasi"]], [m["jumlah"] for m in asli["mutasi"]])

    def test_baris_masuk_memakai_teks_pemasukan(self):
        # Baris masuk adalah pemasukan penerima sendiri, jadi di laporan anggota lain tidak pernah cocok. Bila cocok
        # (laporan yang dipindah gabung akun), teksnya teks pemasukan mantan anggota, sama dengan pemasukan hidupnya.
        baru = pencatat.anonimkan_data(self.data_campur(), ID_ANI, **PENGGANTI)
        masuk = [m for m in baru["mutasi"] if m["arah"] == "masuk"]
        self.assertTrue(masuk)
        for m in masuk:
            self.assertEqual((m["keterangan"], m["pencatat"], m["pencatat_id"]),
                             (ANON_INCOME_DESC, FORMER_MEMBER_NAME, MANTAN))

    def test_tanpa_baris_pencatat_itu_tidak_ada_perubahan(self):
        data = self.data_campur()
        for user_id in ("8f0e0d0c-0000-4000-8000-000000000999", ID_ANI.upper(), ""):
            with self.subTest(user_id=user_id):
                self.assertIsNone(pencatat.anonimkan_data(data, user_id, **PENGGANTI))
                self.assertIsNone(pencatat.alihkan_data(data, user_id, "x"))
        # Laporan tanpa `pencatat_id` sama sekali (mis. data lain di tes) juga dibiarkan.
        self.assertIsNone(pencatat.anonimkan_data({"versi": 1, "judul": "Laporan"}, ID_ANI, **PENGGANTI))

    def test_alihkan_hanya_id_nama_dan_teks_tetap(self):
        data = self.data_campur()
        asli = copy.deepcopy(data)
        target = "9e9e9e9e-0000-4000-8000-0000000000aa"

        baru = pencatat.alihkan_data(data, ID_BUDI, target)

        self.assertEqual(data, asli)
        self.assertEqual({(m["pencatat"], m["pencatat_id"]) for m in baru["mutasi"]},
                         {("Ani", ID_ANI), ("Budi", target)})
        self.assertEqual([t["pencatat_id"] for t in baru["langganan"]["terbayar"]], [target, ID_ANI])

        # Selain `pencatat_id` baris Budi, tidak ada yang berubah.
        def tanpa_id(nilai):
            if isinstance(nilai, dict):
                return {k: tanpa_id(v) for k, v in nilai.items() if k != "pencatat_id"}
            if isinstance(nilai, list):
                return [tanpa_id(v) for v in nilai]
            return nilai

        self.assertEqual(tanpa_id(baru), tanpa_id(asli))


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

    # ── R15: catatan anggota yang menghapus akun di laporan beku anggota lain ──
    async def rumah_bertiga(self):
        """Rumah "Rumah Kita" (gajian 1): Ani (pemilik), Budi, Citra; amplop bersama Kebutuhan dengan snapshot Oktober
        2026 (alokasi 2.000.000 dari gaji Budi, terpakai 784.000 = jumlah transaksi di bawah). Transaksi Oktober:

            Ani    3 Okt  Bensin           300.000
            Ani    6 Okt  🔄 Netflix         54.000   tagihan tombol Bayar
            Ani    9 Okt  Obat              45.000   privat
            Ani   12 Okt  Selisih dompet    10.000   penyesuaian cocokkan saldo
            Budi   4 Okt  Belanja          120.000
            Citra  5 Okt  Sepatu           200.000
            Citra  7 Okt  🔄 Spotify         55.000   tagihan tombol Bayar

        Mengembalikan (ani, budi, citra, rumah)."""
        ani, hh = await self.add_user("Ani", email="ani@contoh.test")
        budi, _ = await self.add_user("Budi", email="budi@contoh.test", household=hh, role=HouseholdRole.member)
        citra, _ = await self.add_user("Citra", email="citra@contoh.test", household=hh, role=HouseholdRole.member)
        async with self.Session() as db:
            rumah = await db.get(Household, hh)
            rumah.name, rumah.payday_day = "Rumah Kita", 1
            env = Envelope(household_id=hh, name="Kebutuhan", emoji="🍜", is_rollover=True,
                           created_at=datetime(2026, 1, 1, tzinfo=UTC))
            cek = BalanceCheck(household_id=hh, user_id=ani, actual_amount=Decimal(0), app_amount=Decimal(0),
                               gap=Decimal(0))
            db.add_all([env, cek])
            await db.flush()
            gaji = Income(household_id=hh, user_id=budi, amount=Decimal(2_000_000), description="Gaji Budi",
                          income_date=OKT1)
            db.add(gaji)
            db.add(Allocation(income=gaji, envelope_id=env.id, amount=Decimal(2_000_000)))
            for oleh, jumlah, ket, hari, lain in [
                (ani, 300_000, "Bensin", 3, {}),
                (ani, 54_000, "🔄 Netflix", 6, {}),
                (ani, 45_000, "Obat", 9, {"is_private": True}),
                (ani, 10_000, "Selisih dompet", 12, {"balance_check_id": cek.id}),
                (budi, 120_000, "Belanja", 4, {}),
                (citra, 200_000, "Sepatu", 5, {}),
                (citra, 55_000, "🔄 Spotify", 7, {}),
            ]:
                db.add(Transaction(envelope_id=env.id, user_id=oleh, amount=Decimal(jumlah), description=ket,
                                   transaction_date=date(2026, 10, hari), **lain))
            db.add(MonthlySnapshot(envelope_id=env.id, year=2026, month=10, opening_balance=Decimal(2_000_000),
                                   closing_balance=Decimal(1_216_000), rollover_amount=Decimal(1_216_000),
                                   allocated_amount=Decimal(2_000_000), spent_amount=Decimal(784_000)))
            await db.commit()
        return ani, budi, citra, hh

    async def susun_dari_db(self, user_id, household_id) -> dict:
        """`data` laporan Oktober 2026 `user_id` dari isi database saat ini (pemuat dan penyusun sungguhan)."""
        async with self.Session() as db:
            user, rumah = await db.get(User, user_id), await db.get(Household, household_id)
            return susun_bulanan(await muat_bahan(db, user, rumah, OKT1, OKT31, 1, date(2026, 11, 1)))

    async def bekukan(self, user_id, household_id):
        """Terbitkan laporan Oktober 2026 `user_id` dari isi database saat ini. Mengembalikan (id, data)."""
        data = await self.susun_dari_db(user_id, household_id)
        async with self.Session() as db:
            r = Report(user_id=user_id, household_id=household_id, jenis=JENIS_BULANAN, periode_mulai=OKT1,
                       periode_akhir=OKT31, payday_day=1, data=data)
            db.add(r)
            await db.commit()
            return r.id, data

    async def data_laporan(self, report_id) -> dict:
        return (await self.get(Report, report_id)).data

    async def semua_data_laporan(self) -> str:
        async with self.Session() as db:
            return json.dumps([r for r in (await db.execute(select(Report.data))).scalars()], ensure_ascii=False)

    async def test_hapus_akun_menganonimkan_catatannya_di_laporan_beku_anggota_lain(self):
        ani, budi, citra, hh = await self.rumah_bertiga()
        r_budi, budi_sebelum = await self.bekukan(budi, hh)
        r_citra, citra_sebelum = await self.bekukan(citra, hh)
        await self.bekukan(ani, hh)
        dewi, hh_dewi = await self.add_user("Dewi", email="dewi@contoh.test")
        r_dewi = await self.add_report(dewi, hh_dewi, SEP, tanda="dewi")
        a, b, c = str(ani), str(budi), str(citra)
        # Prasyarat: laporan Budi memuat nama, id, dan teks catatan Ani (privatnya tersamar sejak terbit).
        self.assertIn(baris_mutasi(3, "Bensin", "300000.00", "Ani", a), budi_sebelum["mutasi"])
        self.assertIn(baris_mutasi(9, PRIVATE_PLACEHOLDER, "45000.00", "Ani", a), budi_sebelum["mutasi"])
        self.assertIn(baris_terbayar(6, "Netflix", "54000.00", a), budi_sebelum["langganan"]["terbayar"])

        await self.hapus(ani)

        budi_sesudah = await self.data_laporan(r_budi)
        self.assertEqual(budi_sesudah["mutasi"], [
            baris_mutasi(1, "Gaji Budi", "2000000.00", "Budi", b, arah="masuk", amplop=None),
            baris_mutasi(3, ANON_TXN_DESC, "300000.00", FORMER_MEMBER_NAME, MANTAN),
            baris_mutasi(4, "Belanja", "120000.00", "Budi", b),
            baris_mutasi(5, "Sepatu", "200000.00", "Citra", c),
            baris_mutasi(6, ANON_TXN_DESC, "54000.00", FORMER_MEMBER_NAME, MANTAN),
            baris_mutasi(7, "🔄 Spotify", "55000.00", "Citra", c),
            baris_mutasi(9, PRIVATE_PLACEHOLDER, "45000.00", FORMER_MEMBER_NAME, MANTAN),
            baris_mutasi(12, ANON_TXN_DESC, "10000.00", FORMER_MEMBER_NAME, MANTAN, penyesuaian=True),
        ])
        self.assertEqual(budi_sesudah["terbesar"], [
            baris_terbesar(3, ANON_TXN_DESC, "300000.00", FORMER_MEMBER_NAME, MANTAN),
            baris_terbesar(5, "Sepatu", "200000.00", "Citra", c),
            baris_terbesar(4, "Belanja", "120000.00", "Budi", b),
            baris_terbesar(7, "🔄 Spotify", "55000.00", "Citra", c),
            baris_terbesar(6, ANON_TXN_DESC, "54000.00", FORMER_MEMBER_NAME, MANTAN),
        ])
        self.assertEqual(budi_sesudah["langganan"]["terbayar"], [
            baris_terbayar(6, ANON_TXN_DESC, "54000.00", MANTAN),
            baris_terbayar(7, "Spotify", "55000.00", c),
        ])
        # Sama persis dengan laporan yang disusun ulang dari catatan hidup sesudah hapus akun, kecuali tagihan Ani:
        # catatan hidupnya kehilangan penanda tombol Bayar, jadi susunan baru tidak lagi mengenalinya sebagai tagihan;
        # laporan beku tetap memuat barisnya (nominal tidak berubah), hanya namanya yang dianonimkan.
        segar = await self.susun_dari_db(budi, hh)
        self.assertEqual({k: v for k, v in budi_sesudah.items() if k != "langganan"},
                         {k: v for k, v in segar.items() if k != "langganan"})
        self.assertEqual(budi_sesudah["langganan"]["jatuh_tempo"], segar["langganan"]["jatuh_tempo"])
        self.assertEqual(segar["langganan"]["terbayar"], [baris_terbayar(7, "Spotify", "55000.00", c)])
        # Nominal di mana pun tetap, dan nama serta teks Ani tidak tersisa.
        self.assertEqual(uang_per_jalur(budi_sesudah), uang_per_jalur(budi_sebelum))
        teks_budi = json.dumps(budi_sesudah, ensure_ascii=False)
        for jejak in ("Ani", a, "Bensin", "Netflix", "Selisih dompet"):
            self.assertNotIn(jejak, teks_budi)

        # Laporan Citra juga, hanya baris Ani; baris Budi dan Citra di sana utuh.
        citra_sesudah = await self.data_laporan(r_citra)
        self.assertEqual({k: v for k, v in citra_sesudah.items() if k != "langganan"},
                         {k: v for k, v in (await self.susun_dari_db(citra, hh)).items() if k != "langganan"})
        for baris_lama, baris_baru in zip(citra_sebelum["mutasi"], citra_sesudah["mutasi"]):
            if baris_lama["pencatat_id"] != a:
                self.assertEqual(baris_baru, baris_lama)
        self.assertEqual(uang_per_jalur(citra_sesudah), uang_per_jalur(citra_sebelum))

        # Laporan Ani sendiri ikut terhapus; laporan rumah lain tidak tersentuh; id Ani tak tersisa di laporan mana pun.
        self.assertEqual(await self.count(Report, Report.user_id == ani), 0)
        self.assertEqual(await self.reports_of(dewi), {(JENIS_BULANAN, SEP): (r_dewi, hh_dewi, "dewi")})
        self.assertNotIn(a, await self.semua_data_laporan())

    async def test_hapus_akun_menganonimkan_laporan_mantan_anggota_walau_rumahnya_ikut_terhapus(self):
        # Budi dulu serumah dengan Ani (laporannya memuat catatan Ani), kini pindah. Ani sendirian lalu menghapus akun:
        # rumahnya terhapus beserta semua transaksinya, jadi tidak ada catatan hidup yang dianonimkan, tetapi laporan
        # beku Budi tetap ditulis ulang.
        ani, hh = await self.add_user("Ani", email="ani@contoh.test")
        budi, hh_budi = await self.add_user("Budi", email="budi@contoh.test")
        a, b = str(ani), str(budi)
        data = susun_bulanan(bahan(penerima_nama="Budi", penerima_id=b, rumah_nama="Rumah Lama", transaksi=[
            txn(id="a1", tanggal=d(2), jumlah=Decimal(150_000), keterangan="Bensin", pencatat="Ani", pencatat_id=a,
                milik_penerima=False),
            txn(id="b1", tanggal=d(3), jumlah=Decimal(90_000), keterangan="Makan siang", pencatat="Budi",
                pencatat_id=b),
            txn(id="a2", tanggal=d(12), jumlah=Decimal(54_000), keterangan="🔄 Netflix", pencatat="Ani",
                pencatat_id=a, milik_penerima=False, tagihan=True),
        ]))
        async with self.Session() as db:
            lama = Report(user_id=budi, household_id=hh, jenis=JENIS_BULANAN, periode_mulai=OKT1, periode_akhir=OKT31,
                          payday_day=1, data=data)
            db.add(lama)
            await db.commit()

        await self.hapus(ani)

        self.assertIsNone(await self.get(Household, hh))
        laporan = await self.get(Report, lama.id)
        self.assertIsNone(laporan.household_id)
        keluar = [(m["keterangan"], m["pencatat"], m["pencatat_id"]) for m in laporan.data["mutasi"]
                  if m["arah"] == "keluar"]
        self.assertEqual(keluar, [(ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN), ("Makan siang", "Budi", b),
                                  (ANON_TXN_DESC, FORMER_MEMBER_NAME, MANTAN)])
        self.assertEqual([t["nama"] for t in laporan.data["langganan"]["terbayar"]], [ANON_TXN_DESC])
        self.assertEqual(uang_per_jalur(laporan.data), uang_per_jalur(data))
        self.assertNotIn(a, json.dumps(laporan.data))
        self.assertIsNotNone(await self.get(Household, hh_budi))

    async def test_penulis_ulang_menerima_id_dalam_bentuk_apa_pun_dan_melewati_laporan_miliknya(self):
        # `pencatat_id` dibekukan sebagai `str(uuid)`; id yang datang sebagai teks berhuruf besar atau UUID tetap cocok.
        # Laporan milik akun yang dihapus sendiri tidak ditulis ulang (ikut terhapus bersama akunnya).
        ani, hh = await self.add_user("Ani", email="ani@contoh.test")
        budi, _ = await self.add_user("Budi", email="budi@contoh.test", household=hh, role=HouseholdRole.member)
        a, b = str(ani), str(budi)

        def data_untuk(penerima, penerima_id):
            return susun_bulanan(bahan(penerima_nama=penerima, penerima_id=penerima_id, transaksi=[
                txn(id="a1", keterangan="Bensin", pencatat="Ani", pencatat_id=a, milik_penerima=penerima_id == a),
            ]))

        async with self.Session() as db:
            milik_budi, milik_ani = (
                Report(user_id=pemilik, household_id=hh, jenis=JENIS_BULANAN, periode_mulai=OKT1,
                       periode_akhir=OKT31, payday_day=1, data=isi)
                for pemilik, isi in ((budi, data_untuk("Budi", b)), (ani, data_untuk("Ani", a)))
            )
            db.add_all([milik_budi, milik_ani])
            await db.commit()

        async with self.Session() as db:
            self.assertEqual(await pencatat.anonimkan_pencatat(db, a.upper(), **PENGGANTI), 1)
            await db.commit()

        self.assertEqual([(m["pencatat"], m["keterangan"]) for m in (await self.data_laporan(milik_budi.id))["mutasi"]
                          if m["arah"] == "keluar"], [(FORMER_MEMBER_NAME, ANON_TXN_DESC)])
        self.assertIn(a, json.dumps(await self.data_laporan(milik_ani.id)))  # milik Ani sendiri tidak disentuh
        async with self.Session() as db:
            self.assertEqual(await pencatat.alihkan_pencatat(db, FORMER_MEMBER_ID, budi), 1)
            await db.commit()
        self.assertEqual({m["pencatat_id"] for m in (await self.data_laporan(milik_budi.id))["mutasi"]}, {b})

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

    async def test_gabung_mengalihkan_pencatat_id_sumber_lalu_hapus_target_menganonimkannya(self):
        # Ruling R15: catatan sumber yang beku di laporan Budi menunjuk akun yang akan dihapus gabung akun. `pencatat_id`
        # dialihkan ke target (nama dan teks tetap seperti saat terbit), supaya hapus akun target kelak ikut
        # menganonimkan baris yang dicatat sumber.
        sumber, hh = await self.add_user("Bot", telegram_id="777")
        budi, _ = await self.add_user("Budi", email="budi@contoh.test", household=hh, role=HouseholdRole.member)
        target, _ = await self.add_user("Web", email="web@contoh.test")
        s, b, t = str(sumber), str(budi), str(target)

        def catatan(penerima):
            return [
                txn(id="s1", tanggal=d(2), jumlah=Decimal(150_000), keterangan="Bensin", pencatat="Bot",
                    pencatat_id=s, milik_penerima=penerima == s),
                txn(id="b1", tanggal=d(3), jumlah=Decimal(90_000), keterangan="Makan siang", pencatat="Budi",
                    pencatat_id=b, milik_penerima=penerima == b),
                txn(id="s2", tanggal=d(12), jumlah=Decimal(54_000), keterangan="🔄 Netflix", pencatat="Bot",
                    pencatat_id=s, milik_penerima=penerima == s, tagihan=True),
            ]

        data_budi = susun_bulanan(bahan(penerima_nama="Budi", penerima_id=b, rumah_nama="Rumah Bot",
                                        transaksi=catatan(b)))
        data_sumber = susun_bulanan(bahan(penerima_nama="Bot", penerima_id=s, rumah_nama="Rumah Bot",
                                          transaksi=catatan(s)))
        async with self.Session() as db:
            r_budi, r_sumber = (
                Report(user_id=pemilik, household_id=hh, jenis=JENIS_BULANAN, periode_mulai=OKT1, periode_akhir=OKT31,
                       payday_day=1, data=isi)
                for pemilik, isi in ((budi, data_budi), (sumber, data_sumber))
            )
            db.add_all([r_budi, r_sumber])
            await db.commit()

        await self.gabung(sumber, target, hh)

        budi_gabung = await self.data_laporan(r_budi.id)
        self.assertEqual([(m["pencatat"], m["pencatat_id"], m["keterangan"]) for m in budi_gabung["mutasi"]
                          if m["arah"] == "keluar"],
                         [("Bot", t, "Bensin"), ("Budi", b, "Makan siang"), ("Bot", t, "🔄 Netflix")])
        self.assertEqual([(x["nama"], x["pencatat_id"]) for x in budi_gabung["langganan"]["terbayar"]],
                         [("Netflix", t)])
        self.assertEqual(uang_per_jalur(budi_gabung), uang_per_jalur(data_budi))
        # Laporan sumber yang pindah ke target juga (baris masuk = pemasukan sumber); id sumber tak tersisa di mana pun.
        sumber_gabung = await self.data_laporan(r_sumber.id)
        self.assertEqual({(m["arah"], m["pencatat_id"]) for m in sumber_gabung["mutasi"]},
                         {("masuk", t), ("keluar", t), ("keluar", b)})
        self.assertNotIn(s, await self.semua_data_laporan())

        await self.hapus(target)

        budi_hapus = await self.data_laporan(r_budi.id)
        self.assertEqual([(m["pencatat"], m["pencatat_id"], m["keterangan"]) for m in budi_hapus["mutasi"]
                          if m["arah"] == "keluar"],
                         [(FORMER_MEMBER_NAME, MANTAN, ANON_TXN_DESC), ("Budi", b, "Makan siang"),
                          (FORMER_MEMBER_NAME, MANTAN, ANON_TXN_DESC)])
        self.assertEqual(uang_per_jalur(budi_hapus), uang_per_jalur(data_budi))
        self.assertIsNone(await self.get(Report, r_sumber.id))  # milik target kini, ikut terhapus bersamanya
        self.assertNotIn(t, await self.semua_data_laporan())

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
