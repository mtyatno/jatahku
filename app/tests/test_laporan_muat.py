"""Pemuat bahan laporan berkala (tahap 1, Task 4; spec bagian 2c-2d) dan filter pemasukan bersama.

`muat_bahan` satu-satunya pembaca DB isi laporan, jadi diuji di SQLite sungguhan (pola `test_account_deletion.py`).
Rumah H "Rumah Ani": Ani (pemilik, penerima utama) dan Budi (anggota); jendela 1-31 Okt 2026 (gajian 1). Amplop dan
nasibnya di laporan Ani:

    S   Kebutuhan     bersama, aktif, snapshot Jul-Okt                                  -> baris
    PA  Tabungan Ani  pribadi Ani, saving, snapshot Okt dengan alokasi/terpakai NULL     -> baris, dua angka dihitung
    PB  Hobi Budi     pribadi Budi, snapshot Jul-Okt                                    -> tak pernah terlihat Ani
    C   Liburan       bersama, ditutup, tanpa snapshot Okt, hanya transaksi di jendela   -> baris ditutup
    D   Arisan        bersama, ditutup, snapshot Sep, di Okt hanya transaksi terhapus    -> bukan baris; Sep ikut total
    E   Lama          bersama, ditutup, transaksi Agustus saja                          -> bukan baris
    F   Pulsa         bersama, ditutup, tanpa snapshot Okt, hanya alokasi (sisa dipindah) -> baris ditutup
    CB  Kado Budi     pribadi Budi, ditutup, transaksi dan alokasi di jendela            -> tak pernah terlihat Ani
    N   Baru          bersama, aktif, dibuat 1 Nov, transaksi bertanggal 30 Okt, tanpa snapshot -> bukan baris
    K   Kas kecil     bersama, aktif, dibuat Jan, tanpa snapshot (mis. refresh gagal), transaksi Okt -> bukan baris
    U   Modal         ruang usaha Ani (household lain), snapshot dan transaksi Okt      -> tidak ikut

Snapshot Oktober konsisten dengan transaksi dan alokasinya (diturunkan tangan di `_isi`), jadi tes konsistensi
(akhir = awal - terpakai, jumlah alokasi harian = alokasi, jumlah transaksi = terpakai) bermakna. Harapan ditulis
sebagai literal, tidak dihitung dengan fungsi yang diuji.
Run: python -m unittest app.tests.test_laporan_muat -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import unittest
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers

from app.api.routes import analytics
from app.core.database import Base
from app.models.models import (
    Allocation, BalanceCheck, Envelope, Goal, Household, HouseholdMember, HouseholdRole, HouseholdType, Income,
    IncomeKind, MonthlySnapshot, PurposeType, RecurringTransaction, Transaction, User, UserStreak,
)
from app.services.laporan import muat
from app.services.laporan.muat import muat_bahan
from app.services.laporan.susun import AmplopPeriode, TagihanBerikut, TargetTabungan, TransaksiPeriode, susun_bulanan
from app.services.pemasukan import filter_pemasukan_user
from app.services.streak import user_today
from app.tests.fakes import FakeResult, db_with

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

D = Decimal
PS, PE = date(2026, 10, 1), date(2026, 10, 31)
ANGKA_PER = date(2026, 11, 1)
PRIVAT = "Transaksi privat"
UTC = timezone.utc


def okt(n: int) -> date:
    return date(2026, 10, n)


def pukul(tanggal: date, jam: int = 12) -> datetime:
    return datetime.combine(tanggal, time(jam), tzinfo=UTC)


# --- filter pemasukan bersama (tanpa DB) -------------------------------------------------------------------------

HID, UID = uuid.UUID("11111111-1111-4111-8111-111111111111"), uuid.UUID("22222222-2222-4222-8222-222222222222")
PS9, PE9 = date(2026, 9, 1), date(2026, 9, 30)


def _income_totals_sebelum_task_4():
    """Kueri `analytics._income_totals` sebelum Task 4, disalin apa adanya (pembanding SQL)."""
    return select(Income.amount).where(
        Income.household_id == HID,
        Income.user_id == UID,
        Income.income_date >= PS9,
        Income.income_date <= PE9,
        Income.balance_check_id.is_(None),
    )


def _kompilasi(stmt) -> tuple[str, dict]:
    c = stmt.compile(dialect=postgresql.dialect())
    return str(c), c.params


class FilterPemasukanTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_pemasukan_sama_dengan_income_totals(self):
        sebelum = _kompilasi(_income_totals_sebelum_task_4())
        bersama = select(Income.amount).where(*filter_pemasukan_user(HID, UID, PS9, PE9))
        self.assertEqual(_kompilasi(bersama), sebelum)

        db = db_with(FakeResult(rows=[(D(500),), (D(0),), (D(250),)]))
        hasil = await analytics._income_totals(HID, SimpleNamespace(id=UID), PS9, PE9, db)
        self.assertEqual(hasil, (D(750), 2, 1))  # perilaku tetap: satu kueri, nominal 0 = transfer
        self.assertEqual(db.execute.call_count, 1)
        self.assertEqual(_kompilasi(db.execute.call_args.args[0]), sebelum)

    async def test_income_totals_memakai_filter_bersama(self):
        panggilan = []

        def filter_dicatat(*argumen):
            panggilan.append(argumen)
            return filter_pemasukan_user(*argumen)

        db = db_with(FakeResult(rows=[]))
        with patch.object(analytics, "filter_pemasukan_user", filter_dicatat):
            await analytics._income_totals(HID, SimpleNamespace(id=UID), PS9, PE9, db)
        self.assertEqual(panggilan, [(HID, UID, PS9, PE9)])


# --- pemuat (SQLite) ----------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class MuatBahanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)  # juga bila setUp gagal (aiosqlite menggantung)

        # Postgres menegakkan FK; tanpa ini SQLite meloloskan baris yatim.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        # Tanggal lokal hari ini: streak dibaca seperti aplikasi membacanya (catatan terakhir hari ini = masih hidup).
        self.hari_ini = user_today("Asia/Jakarta")
        async with self.Session() as db:
            await self._isi(db)
            await db.commit()

    async def _isi(self, db):
        """Data bersama semua tes. Angka snapshot Oktober (diturunkan tangan, konsisten dengan baris di bawah):

        S:  alokasi 2.000.000 (1 Okt) + 500.000 (2 Okt, gaji Budi) + 50.000 (2 Okt, sisa Pulsa) + 300.000 (15 Okt)
            + 25.000 (20 Okt, penyesuaian) = 2.875.000; awal = 2.875.000 + rollover Sep 600.000 = 3.475.000;
            terpakai 100+50+35+54+20+30+45+15+40+25 ribu = 414.000; akhir = dibawa = 3.061.000.
        PA: alokasi 1.000.000 (1 Okt) + 40.000 (22 Okt, top-up) = 1.040.000; awal = 1.040.000 + 300.000 = 1.340.000;
            terpakai 200.000 + 15.000 = 215.000; akhir = dibawa = 1.125.000 (kolom alokasi/terpakai snapshot NULL).
        PB: alokasi 500.000 + 6.000 (sisa Kado Budi) = 506.000 = awal; terpakai 300.000; akhir = dibawa = 206.000.
        C:  rollover Sep 200.000, tanpa alokasi, terpakai 150.000 -> awal 200.000, akhir = dibawa 50.000.
        F:  rollover Sep 50.000, sisa -50.000 dipindah ke S 2 Okt, tanpa belanja -> awal 0, akhir 0.
        CB: rollover Sep 56.000, sisa -6.000 dipindah ke PB 6 Okt, terpakai 50.000 -> awal 50.000, akhir 0.
        """
        a = User(name="Ani", email="ani@contoh.id")
        b = User(name="Budi", email="budi@contoh.id")
        db.add_all([a, b])
        await db.flush()
        h = Household(name="Rumah Ani", payday_day=1)
        h2 = Household(name="Usaha Ani", type=HouseholdType.USAHA, payday_day=1)
        db.add_all([h, h2])
        await db.flush()
        db.add_all([
            HouseholdMember(user_id=a.id, household_id=h.id, role=HouseholdRole.owner),
            HouseholdMember(user_id=b.id, household_id=h.id, role=HouseholdRole.member),
            HouseholdMember(user_id=a.id, household_id=h2.id, role=HouseholdRole.owner),
        ])
        cek = BalanceCheck(household_id=h.id, user_id=a.id, actual_amount=D(0), app_amount=D(0), gap=D(0))
        db.add(cek)

        def amplop(nama, emoji, dibuat, pemilik=None, aktif=True, tujuan="expense", rumah=h):
            env = Envelope(household_id=rumah.id, name=nama, emoji=emoji, owner_id=pemilik, is_active=aktif,
                           is_rollover=True, purpose=tujuan, created_at=datetime(*dibuat, tzinfo=UTC))
            db.add(env)
            return env

        s = amplop("Kebutuhan", "🍜", (2026, 1, 1))
        pa = amplop("Tabungan Ani", "🐷", (2026, 1, 2), pemilik=a.id, tujuan="saving")
        pb = amplop("Hobi Budi", "🎸", (2026, 1, 3), pemilik=b.id)
        c = amplop("Liburan", "🧳", (2026, 1, 4), aktif=False)
        d = amplop("Arisan", "🤝", (2026, 1, 5), aktif=False)
        e = amplop("Lama", "📦", (2026, 1, 6), aktif=False)
        f = amplop("Pulsa", "📱", (2026, 1, 7), aktif=False)
        cb = amplop("Kado Budi", "🎁", (2026, 1, 8), pemilik=b.id, aktif=False)
        n = amplop("Baru", "🆕", (2026, 11, 1))
        k = amplop("Kas kecil", "💵", (2026, 1, 10))
        u = amplop("Modal", "💼", (2026, 1, 9), rumah=h2)
        await db.flush()

        def snapshot(env, tahun, bulan, awal, akhir, dibawa, alokasi, terpakai):
            db.add(MonthlySnapshot(
                envelope_id=env.id, year=tahun, month=bulan, opening_balance=D(awal), closing_balance=D(akhir),
                rollover_amount=D(dibawa), allocated_amount=None if alokasi is None else D(alokasi),
                spent_amount=None if terpakai is None else D(terpakai),
            ))

        snapshot(s, 2026, 7, 1_000_000, 700_000, 700_000, 1_000_000, 300_000)
        snapshot(s, 2026, 8, 900_000, 500_000, 500_000, 200_000, 400_000)
        snapshot(s, 2026, 9, 1_100_000, 600_000, 600_000, 600_000, 500_000)
        snapshot(s, 2026, 10, 3_475_000, 3_061_000, 3_061_000, 2_875_000, 414_000)
        snapshot(pa, 2026, 6, 0, 0, 0, None, None)
        snapshot(pa, 2026, 8, 300_000, 220_000, 220_000, 300_000, 80_000)
        snapshot(pa, 2026, 9, 300_000, 300_000, 300_000, None, None)
        snapshot(pa, 2026, 10, 1_340_000, 1_125_000, 1_125_000, None, None)
        for bulan in (7, 8, 9):
            snapshot(pb, 2026, bulan, 1_000_000, 0, 0, 1_000_000, 1_000_000)
        snapshot(pb, 2026, 10, 506_000, 206_000, 206_000, 506_000, 300_000)
        snapshot(c, 2026, 9, 260_000, 200_000, 200_000, 260_000, 60_000)
        snapshot(d, 2026, 9, 70_000, 0, 0, 70_000, 70_000)
        snapshot(f, 2026, 9, 100_000, 50_000, 50_000, 100_000, 50_000)
        snapshot(cb, 2026, 9, 500_000, 56_000, 56_000, 500_000, 444_000)
        snapshot(u, 2026, 9, 800_000, 23_000, 23_000, 800_000, 777_000)
        snapshot(u, 2026, 10, 2_523_000, 1_523_000, 1_523_000, 2_500_000, 1_000_000)

        def masuk(oleh, jumlah, ket, tanggal, alokasi=(), rumah=h, jenis=IncomeKind.PEMASUKAN, cek_id=None):
            inc = Income(household_id=rumah.id, user_id=oleh.id, amount=D(jumlah), description=ket,
                         income_date=tanggal, kind=jenis, balance_check_id=cek_id, created_at=pukul(tanggal))
            db.add(inc)
            for env, nilai in alokasi:
                db.add(Allocation(income=inc, envelope_id=env.id, amount=D(nilai)))

        masuk(a, 5_000_000, "Gaji Oktober", okt(1), [(s, 2_000_000), (pa, 1_000_000)])
        masuk(b, 3_000_000, "Gaji Budi", okt(2), [(s, 500_000), (pb, 500_000)])
        masuk(a, 0, "Refund: hapus amplop Pulsa", okt(2), [(f, -50_000), (s, 50_000)], jenis=IncomeKind.TRANSFER)
        masuk(b, 0, "Refund: hapus amplop Kado Budi", okt(6), [(cb, -6_000), (pb, 6_000)],
              jenis=IncomeKind.TRANSFER)
        masuk(a, 300_000, "Bonus", okt(15), [(s, 300_000)])
        masuk(a, 25_000, "Penyesuaian saldo", okt(20), [(s, 25_000)], jenis=IncomeKind.PENYESUAIAN, cek_id=cek.id)
        masuk(a, 40_000, "Top-up dompet", okt(22), [(pa, 40_000)], jenis=IncomeKind.TOPUP)
        masuk(a, 999_000, "Gaji September", date(2026, 9, 30), [(s, 100_000)])
        masuk(a, 888_000, "Gaji November", date(2026, 11, 1), [(s, 200_000)])
        masuk(a, 77_000, "Jual barang", okt(31))
        masuk(a, 2_500_000, "Penjualan", okt(10), [(u, 2_500_000)], rumah=h2)

        trx = {}

        def keluar(kode, env, oleh, tanggal, jumlah, ket, privat=False, hapus=False, cek_id=None, dicatat=None):
            trx[kode] = Transaction(
                envelope_id=env.id, user_id=oleh.id, amount=D(jumlah), description=ket, transaction_date=tanggal,
                is_private=privat, is_deleted=hapus, balance_check_id=cek_id, created_at=dicatat or pukul(tanggal),
            )
            db.add(trx[kode])

        keluar("t1", s, a, okt(1), 100_000, "Belanja bulanan", dicatat=pukul(okt(5), 9))  # dicatat mundur
        keluar("t2", s, b, okt(3), 50_000, "Makan siang")
        keluar("t17", c, a, okt(3), 150_000, "Tiket kereta", dicatat=pukul(okt(3), 8))
        keluar("t3", s, b, okt(4), 35_000, "Hadiah untuk Ani", privat=True)
        keluar("t4", s, a, okt(6), 54_000, "🔄 Netflix")
        keluar("t5", s, b, okt(7), 20_000, "🔄 Spotify")
        keluar("t6", s, b, okt(8), 30_000, "🔄 Rahasia", privat=True)
        keluar("t7", s, a, okt(9), 45_000, "Obat", privat=True)
        keluar("t8", s, a, okt(10), 15_000, "Bayar 🔄 parkir")
        keluar("t14", pa, a, okt(12), 200_000, "Servis laptop", privat=True)
        keluar("t13", s, a, okt(12), 99_000, "Dihapus", hapus=True)
        keluar("t15", pa, a, okt(14), 15_000, "🔄 iCloud", privat=True)
        keluar("t9", s, a, okt(20), 40_000, "Penyesuaian saldo", cek_id=cek.id)
        keluar("t10", s, a, okt(31), 25_000, "Makan malam")
        keluar("t11", s, a, date(2026, 9, 30), 11_000, "Kemarin")
        keluar("t12", s, a, date(2026, 11, 1), 12_000, "Besok")
        keluar("t16", pb, b, okt(5), 300_000, "Senar gitar")
        keluar("t18", d, a, okt(11), 66_000, "Arisan batal", hapus=True)
        keluar("t19", e, a, date(2026, 8, 15), 10_000, "Lama sekali")
        keluar("t20", n, a, okt(30), 30_000, "Cat tembok", dicatat=pukul(date(2026, 11, 1)))
        keluar("t23", k, a, okt(18), 7_000, "Fotokopi")
        keluar("t21", cb, b, okt(6), 50_000, "Kado ulang tahun Ani", privat=True)
        keluar("t22", u, a, okt(10), 1_000_000, "Bahan baku")

        def tagihan(env, ket, jumlah, jatuh_tempo, aktif=True):
            db.add(RecurringTransaction(envelope_id=env.id, description=ket, amount=D(jumlah), next_run=jatuh_tempo,
                                        is_active=aktif))

        tagihan(s, "Internet", 350_000, date(2026, 11, 5))
        tagihan(s, "Air", 100_000, date(2026, 11, 30))
        tagihan(s, "Listrik", 200_000, okt(31))
        tagihan(s, "Asuransi", 500_000, date(2026, 12, 1))
        tagihan(s, "Gym", 150_000, date(2026, 11, 10), aktif=False)
        tagihan(pa, "iCloud", 15_000, date(2026, 11, 14))
        tagihan(pb, "Spotify Budi", 55_000, date(2026, 11, 7))
        tagihan(n, "Iuran RT", 25_000, date(2026, 11, 10))
        tagihan(u, "Sewa lapak", 100_000, date(2026, 11, 3))

        for env, nama, target, hari in [(pa, "Laptop baru", 5_000_000, 1), (pb, "Gitar listrik", 3_000_000, 2),
                                        (n, "Renovasi", 10_000_000, 3), (c, "Tiket pesawat", 1_000_000, 4)]:
            db.add(Goal(envelope_id=env.id, name=nama, target_amount=D(target),
                        created_at=datetime(2026, 2, hari, tzinfo=UTC)))
        db.add(UserStreak(user_id=a.id, current_streak=5, longest_streak=9, total_logged_days=40,
                          last_log_date=self.hari_ini))
        await db.flush()

        self.A, self.B, self.H, self.H2 = a.id, b.id, h.id, h2.id
        self.S, self.PA, self.PB, self.C, self.D, self.E, self.F, self.CB, self.N, self.U = (
            s.id, pa.id, pb.id, c.id, d.id, e.id, f.id, cb.id, n.id, u.id)
        self.t = {kode: str(t.id) for kode, t in trx.items()}

    async def muat(self, siapa="a", ps=PS, pe=PE, payday=1, rumah=None):
        async with self.Session() as db:
            user = await db.get(User, self.A if siapa == "a" else self.B)
            household = await db.get(Household, rumah or self.H)
            return await muat_bahan(db, user, household, ps, pe, payday, ANGKA_PER)

    async def ubah_snapshot(self, env_id, tahun, bulan, **nilai):
        async with self.Session() as db:
            await db.execute(update(MonthlySnapshot).where(
                MonthlySnapshot.envelope_id == env_id, MonthlySnapshot.year == tahun, MonthlySnapshot.month == bulan,
            ).values(**nilai))
            await db.commit()

    # --- lingkup dan privasi ----------------------------------------------------------------------------------

    async def test_lingkup_tanpa_amplop_pribadi_anggota_lain(self):
        bahan = await self.muat("a")
        self.assertEqual({a.id for a in bahan.amplop}, {str(self.S), str(self.PA), str(self.C), str(self.F)})
        # Urut menurut waktu amplop dibuat, seperti daftar amplop di aplikasi.
        self.assertEqual([a.nama for a in bahan.amplop], ["Kebutuhan", "Tabungan Ani", "Liburan", "Pulsa"])
        self.assertEqual((bahan.penerima_nama, bahan.rumah_nama, bahan.periode_mulai, bahan.periode_akhir,
                          bahan.payday, bahan.angka_per), ("Ani", "Rumah Ani", PS, PE, 1, ANGKA_PER))
        self.assertEqual(bahan.penerima_id, str(self.A))  # teks, seperti `pencatat_id` (Ruling R15)

    async def test_lingkup_anggota_lain_memakai_amplop_pribadinya_sendiri(self):
        bahan = await self.muat("b")
        self.assertEqual([a.id for a in bahan.amplop],
                         [str(self.S), str(self.PB), str(self.C), str(self.F), str(self.CB)])
        baris = {a.id: a for a in bahan.amplop}
        cb = baris[str(self.CB)]
        # Amplop pribadi yang ditutup tetap baris bagi pemiliknya: snapshot_values(56.000, -6.000, 50.000, rollover).
        self.assertEqual((cb.pribadi, cb.ditutup, cb.awal, cb.alokasi, cb.terpakai, cb.akhir, cb.rollover),
                         (True, True, D(50_000), D(-6_000), D(50_000), D(0), D(0)))
        self.assertEqual((bahan.penerima_nama, bahan.penerima_id, bahan.rumah_nama), ("Budi", str(self.B), "Rumah Ani"))

    async def test_amplop_yang_dibuat_setelah_periode_tidak_ikut(self):
        """Ruling R8: refresh paksa snapshot sebelum laporan dibangun (Task 5) memberi snapshot nol pada amplop yang
        dibuat sesudah periode tutup. Amplop yang tanggal UTC `created_at`-nya sesudah akhir periode tidak jadi baris,
        jadi transaksi, tagihan, dan targetnya juga tidak ikut; yang dibuat pada hari terakhir periode tetap baris."""
        async with self.Session() as db:
            # 23.30 UTC = 1 Nov 06.30 WIB, tetapi tanggal UTC-nya 31 Okt: masih di dalam periode.
            akhir_okt = Envelope(household_id=self.H, name="Akhir Oktober", emoji="🌙",
                                 created_at=datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
            telat = Envelope(household_id=self.H, name="Dibuat lalu ditutup", emoji="🗑", is_active=False,
                             created_at=datetime(2026, 11, 2, tzinfo=UTC))
            db.add_all([akhir_okt, telat])
            await db.flush()
            for env_id in (self.N, akhir_okt.id):  # snapshot nol seperti hasil refresh paksa
                db.add(MonthlySnapshot(envelope_id=env_id, year=2026, month=10, opening_balance=D(0),
                                       closing_balance=D(0), rollover_amount=D(0), allocated_amount=D(0),
                                       spent_amount=D(0)))
            # Amplop ditutup tanpa snapshot, dibuat 2 Nov, dengan transaksi bertanggal mundur di jendela.
            db.add(Transaction(envelope_id=telat.id, user_id=self.A, amount=D(5_000), description="Mundur",
                               transaction_date=okt(15), created_at=pukul(date(2026, 11, 2))))
            await db.commit()
        bahan = await self.muat("a")
        self.assertEqual([a.nama for a in bahan.amplop],
                         ["Kebutuhan", "Tabungan Ani", "Liburan", "Pulsa", "Akhir Oktober"])
        # N (dibuat 1 Nov): transaksi 30 Okt, tagihan "Iuran RT", dan target "Renovasi" tidak ikut.
        self.assertNotIn(str(self.N), {t.amplop_id for t in bahan.transaksi})
        self.assertNotIn("Iuran RT", [b.nama for b in bahan.tagihan_berikut])
        self.assertNotIn("Renovasi", [g.nama for g in bahan.target])
        self.assertNotIn("Mundur", [t.keterangan for t in bahan.transaksi])
        self.periksa_konsisten(bahan)
        susun_bulanan(bahan)

    async def test_deskripsi_privat_anggota_lain_tersamar(self):
        ani = {t.id: t for t in (await self.muat("a")).transaksi}
        self.assertEqual(ani[self.t["t3"]].keterangan, PRIVAT)        # privat Budi di amplop bersama
        self.assertEqual(ani[self.t["t6"]].keterangan, PRIVAT)
        self.assertEqual((ani[self.t["t3"]].jumlah, ani[self.t["t3"]].pencatat), (D(35_000), "Budi"))  # tetap terlihat
        self.assertEqual(ani[self.t["t7"]].keterangan, "Obat")        # privat Ani sendiri terbaca
        self.assertEqual(ani[self.t["t14"]].keterangan, "Servis laptop")
        self.assertEqual(ani[self.t["t2"]].keterangan, "Makan siang")  # milik Budi, tidak privat
        budi = {t.id: t for t in (await self.muat("b")).transaksi}
        self.assertEqual(budi[self.t["t7"]].keterangan, PRIVAT)
        self.assertEqual(budi[self.t["t3"]].keterangan, "Hadiah untuk Ani")
        self.assertEqual(budi[self.t["t21"]].keterangan, "Kado ulang tahun Ani")

    async def test_tidak_ada_jejak_data_pribadi_anggota_lain_atau_ruang_lain(self):
        ani = repr(await self.muat("a"))
        for rahasia in ("Hadiah untuk Ani", "Rahasia", "Kado ulang tahun Ani", "Senar gitar", "Hobi Budi",
                        "Kado Budi", "Spotify Budi", "Gitar listrik", "Gaji Budi", str(self.PB), str(self.CB),
                        "Modal", "Bahan baku", "Penjualan", "Sewa lapak", str(self.U)):
            with self.subTest(penerima="Ani", rahasia=rahasia):
                self.assertNotIn(rahasia, ani)
        budi = repr(await self.muat("b"))
        for rahasia in ("Obat", "Servis laptop", "iCloud", "Tabungan Ani", "Laptop baru", "Gaji Oktober", "Bonus",
                        "Top-up dompet", "Jual barang", str(self.PA)):
            with self.subTest(penerima="Budi", rahasia=rahasia):
                self.assertNotIn(rahasia, budi)

    # --- angka amplop -------------------------------------------------------------------------------------------

    async def test_baris_amplop_lengkap(self):
        bahan = await self.muat("a")
        self.assertEqual(bahan.amplop, [
            AmplopPeriode(
                id=str(self.S), nama="Kebutuhan", emoji="🍜", pribadi=False, tujuan="expense",
                awal=D(3_475_000), alokasi=D(2_875_000), terpakai=D(414_000), akhir=D(3_061_000),
                rollover=D(3_061_000), ditutup=False,
                alokasi_per_hari={okt(1): D(2_000_000), okt(2): D(550_000), okt(15): D(300_000), okt(20): D(25_000)},
                terpakai_lalu=[D(300_000), D(400_000), D(500_000)],
            ),
            AmplopPeriode(
                id=str(self.PA), nama="Tabungan Ani", emoji="🐷", pribadi=True, tujuan="saving",
                awal=D(1_340_000), alokasi=D(1_040_000), terpakai=D(215_000), akhir=D(1_125_000),
                rollover=D(1_125_000), ditutup=False, alokasi_per_hari={okt(1): D(1_000_000), okt(22): D(40_000)},
                terpakai_lalu=[None, D(80_000), None],
            ),
            AmplopPeriode(
                id=str(self.C), nama="Liburan", emoji="🧳", pribadi=False, tujuan="expense",
                awal=D(200_000), alokasi=D(0), terpakai=D(150_000), akhir=D(50_000), rollover=D(50_000),
                ditutup=True, alokasi_per_hari={}, terpakai_lalu=[None, None, D(60_000)],
            ),
            AmplopPeriode(
                id=str(self.F), nama="Pulsa", emoji="📱", pribadi=False, tujuan="expense",
                awal=D(0), alokasi=D(-50_000), terpakai=D(0), akhir=D(0), rollover=D(0),
                ditutup=True, alokasi_per_hari={okt(2): D(-50_000)}, terpakai_lalu=[None, None, D(50_000)],
            ),
        ])

    async def test_tipe_nilai_sesuai_kontrak_penyusun(self):
        """`uang()` menolak int dan float, `tujuan` harus teks mentah (str), tanggal `date` (bukan datetime)."""
        bahan = await self.muat("a")
        uang = [x for a in bahan.amplop for x in (a.awal, a.alokasi, a.terpakai, a.akhir, a.rollover)]
        uang += [x for a in bahan.amplop for x in a.alokasi_per_hari.values()]
        uang += [x for a in bahan.amplop for x in a.terpakai_lalu if x is not None]
        uang += [t.jumlah for t in bahan.transaksi] + [p.jumlah for p in bahan.pemasukan]
        uang += [b.jumlah for b in bahan.tagihan_berikut] + [g.target for g in bahan.target]
        uang += [x for x in bahan.terpakai_lalu_total if x is not None]
        self.assertTrue(uang)
        for x in uang:
            self.assertIs(type(x), Decimal, x)
        tanggal = [h for a in bahan.amplop for h in a.alokasi_per_hari] + [t.tanggal for t in bahan.transaksi]
        tanggal += [p.tanggal for p in bahan.pemasukan] + [b.tanggal for b in bahan.tagihan_berikut]
        for x in tanggal:
            self.assertIs(type(x), date, x)
        for a in bahan.amplop:
            self.assertIs(type(a.tujuan), str)
            self.assertIs(type(a.emoji), str)
        self.assertIs(type(bahan.streak_saat_ini), int)

    async def test_tujuan_enum_menjadi_teks_mentah(self):
        async with self.Session() as db:
            env = await db.get(Envelope, self.S)
            env.purpose = PurposeType.sinking_fund  # objek di sesi memegang enum, bukan teks
            user, household = await db.get(User, self.A), await db.get(Household, self.H)
            bahan = await muat_bahan(db, user, household, PS, PE, 1, ANGKA_PER)
        self.assertEqual(bahan.amplop[0].tujuan, "sinking_fund")
        self.assertIs(type(bahan.amplop[0].tujuan), str)

    async def test_angka_amplop_dari_snapshot_bukan_dihitung_ulang(self):
        await self.ubah_snapshot(self.S, 2026, 10, opening_balance=D(1), closing_balance=D(2), rollover_amount=D(3),
                                 allocated_amount=D(4), spent_amount=D(5))
        s = (await self.muat("a")).amplop[0]
        self.assertEqual((s.awal, s.akhir, s.rollover, s.alokasi, s.terpakai), (D(1), D(2), D(3), D(4), D(5)))

    async def test_kolom_snapshot_null_dihitung_dari_transaksi_dan_alokasi(self):
        pa = (await self.muat("a")).amplop[1]
        self.assertEqual((pa.alokasi, pa.terpakai), (D(1_040_000), D(215_000)))           # NULL -> dihitung
        self.assertEqual((pa.awal, pa.akhir, pa.rollover), (D(1_340_000), D(1_125_000), D(1_125_000)))  # snapshot
        for ubah, harap in [
            (dict(allocated_amount=None, spent_amount=D(7)), (D(2_875_000), D(7))),
            (dict(allocated_amount=D(9), spent_amount=None), (D(9), D(414_000))),
        ]:
            with self.subTest(ubah=ubah):
                await self.ubah_snapshot(self.S, 2026, 10, **ubah)
                s = (await self.muat("a")).amplop[0]
                self.assertEqual((s.alokasi, s.terpakai), harap)

    async def test_amplop_ditutup_dihitung_seperti_snapshot(self):
        baris = {a.id: a for a in (await self.muat("a")).amplop}
        c, f = baris[str(self.C)], baris[str(self.F)]
        # snapshot_values(rollover Sep 200.000, alokasi 0, terpakai 150.000, is_rollover=True)
        self.assertEqual((c.awal, c.alokasi, c.terpakai, c.akhir, c.rollover, c.ditutup),
                         (D(200_000), D(0), D(150_000), D(50_000), D(50_000), True))
        # snapshot_values(rollover Sep 50.000, alokasi -50.000, terpakai 0, is_rollover=True)
        self.assertEqual((f.awal, f.alokasi, f.terpakai, f.akhir, f.rollover, f.ditutup),
                         (D(0), D(-50_000), D(0), D(0), D(0), True))

    async def test_amplop_nonaktif_yang_punya_snapshot_tetap_baris_biasa(self):
        """Snapshot hanya ditulis untuk amplop yang aktif saat periode tutup; amplop yang dihapus sesudahnya tetap
        baris dengan angka snapshot, bukan baris "ditutup di tengah periode"."""
        async with self.Session() as db:
            await db.execute(update(Envelope).where(Envelope.id == self.S).values(is_active=False))
            await db.commit()
        await self.ubah_snapshot(self.S, 2026, 10, closing_balance=D(11))
        s = (await self.muat("a")).amplop[0]
        self.assertEqual((s.id, s.ditutup, s.akhir), (str(self.S), False, D(11)))

    async def test_terpakai_lalu_urut_terlama_dulu(self):
        ani = await self.muat("a")
        self.assertEqual({a.id: a.terpakai_lalu for a in ani.amplop}, {
            str(self.S): [D(300_000), D(400_000), D(500_000)],   # Jul, Agu, Sep
            str(self.PA): [None, D(80_000), None],                # Jul tanpa snapshot; Sep terpakai NULL
            str(self.C): [None, None, D(60_000)],
            str(self.F): [None, None, D(50_000)],
        })
        # Semua amplop lingkup yang punya angka: D (bukan baris) ikut; PB, CB (Budi) dan U (ruang usaha) tidak.
        self.assertEqual(ani.terpakai_lalu_total, [D(300_000), D(480_000), D(680_000)])
        budi = await self.muat("b")
        self.assertEqual(budi.terpakai_lalu_total, [D(1_300_000), D(1_400_000), D(2_124_000)])
        juli = await self.muat("a", ps=date(2026, 7, 1), pe=date(2026, 7, 31))
        self.assertEqual([(a.id, a.terpakai_lalu) for a in juli.amplop], [(str(self.S), [None, None, None])])
        # Apr-Jun tanpa angka; snapshot Jun PA ada tetapi terpakainya NULL: tidak dikenal, bukan nol.
        self.assertEqual(juli.terpakai_lalu_total, [None, None, None])

    # --- transaksi ------------------------------------------------------------------------------------------------

    async def test_transaksi_hanya_jendela_amplop_baris_urut_tanggal(self):
        t = self.t

        id_user = {"Ani": str(self.A), "Budi": str(self.B)}

        def baris(kode, amplop, tanggal, jumlah, ket, pencatat="Ani", milik=True, penyesuaian=False, tagihan=False):
            return TransaksiPeriode(id=t[kode], amplop_id=str(amplop), tanggal=tanggal, jumlah=D(jumlah),
                                    keterangan=ket, pencatat=pencatat, pencatat_id=id_user[pencatat],
                                    milik_penerima=milik, penyesuaian=penyesuaian, tagihan=tagihan)

        self.assertEqual((await self.muat("a")).transaksi, [
            baris("t1", self.S, okt(1), 100_000, "Belanja bulanan"),
            baris("t17", self.C, okt(3), 150_000, "Tiket kereta"),            # dicatat 08.00, sebelum t2
            baris("t2", self.S, okt(3), 50_000, "Makan siang", "Budi", False),
            baris("t3", self.S, okt(4), 35_000, PRIVAT, "Budi", False),
            baris("t4", self.S, okt(6), 54_000, "🔄 Netflix", tagihan=True),
            baris("t5", self.S, okt(7), 20_000, "🔄 Spotify", "Budi", False, tagihan=True),
            baris("t6", self.S, okt(8), 30_000, PRIVAT, "Budi", False),
            baris("t7", self.S, okt(9), 45_000, "Obat"),
            baris("t8", self.S, okt(10), 15_000, "Bayar 🔄 parkir"),
            baris("t14", self.PA, okt(12), 200_000, "Servis laptop"),
            baris("t15", self.PA, okt(14), 15_000, "🔄 iCloud", tagihan=True),
            baris("t9", self.S, okt(20), 40_000, "Penyesuaian saldo", penyesuaian=True),
            baris("t10", self.S, okt(31), 25_000, "Makan malam"),
        ])

    async def test_pencatat_id_dari_user_transaksi_juga_mantan_anggota(self):
        # Ruling R15: id pencatat = `transactions.user_id` apa adanya (teks), bukan ditebak dari nama (nama tidak unik).
        # Catatan yang sudah dianonimkan hapus akun membawa id "Mantan anggota", sama dengan namanya.
        from app.services.account_deletion import FORMER_MEMBER_ID, FORMER_MEMBER_NAME
        async with self.Session() as db:
            db.add(User(id=FORMER_MEMBER_ID, name=FORMER_MEMBER_NAME, email="deleted_mantan-anggota@jatahku.com"))
            db.add(Transaction(envelope_id=self.S, user_id=FORMER_MEMBER_ID, amount=D(1_000),
                               description="Transaksi mantan anggota", transaction_date=okt(16)))
            await db.commit()
            pencatat = dict((await db.execute(select(Transaction.id, Transaction.user_id))).all())
        ani = (await self.muat("a")).transaksi
        self.assertEqual({t.id: t.pencatat_id for t in ani}, {t.id: str(pencatat[uuid.UUID(t.id)]) for t in ani})
        mantan = [t for t in ani if t.pencatat == FORMER_MEMBER_NAME]
        self.assertEqual([t.pencatat_id for t in mantan], [str(FORMER_MEMBER_ID)])
        self.assertEqual({type(t.pencatat_id) for t in ani}, {str})

    async def test_penanda_tagihan_dan_penyesuaian(self):
        ani = (await self.muat("a")).transaksi
        self.assertEqual({t.id for t in ani if t.tagihan}, {self.t["t4"], self.t["t5"], self.t["t15"]})
        self.assertEqual({t.id for t in ani if t.penyesuaian}, {self.t["t9"]})
        # Keterangan privat Budi berawalan penanda: bagi Ani bukan tagihan (awalan itu tidak boleh bocor) ...
        self.assertNotIn(self.t["t6"], {t.id for t in ani if t.tagihan})
        # ... bagi Budi sendiri tagihan.
        budi = (await self.muat("b")).transaksi
        self.assertEqual({t.id for t in budi if t.tagihan}, {self.t["t4"], self.t["t5"], self.t["t6"]})

    # --- pemasukan -----------------------------------------------------------------------------------------------

    async def test_pemasukan_hanya_milik_penerima_tanpa_penyesuaian_dan_transfer(self):
        bahan = await self.muat("a")
        self.assertEqual([(p.tanggal, p.jumlah, p.keterangan) for p in bahan.pemasukan], [
            (okt(1), D(5_000_000), "Gaji Oktober"),
            (okt(15), D(300_000), "Bonus"),
            (okt(22), D(40_000), "Top-up dompet"),
            (okt(31), D(77_000), "Jual barang"),
        ])
        budi = await self.muat("b")
        self.assertEqual([(p.tanggal, p.keterangan) for p in budi.pemasukan], [(okt(2), "Gaji Budi")])

    async def test_pemasukan_sama_dengan_total_analitik(self):
        bahan = await self.muat("a")
        async with self.Session() as db:
            total, jumlah, transfer = await analytics._income_totals(self.H, SimpleNamespace(id=self.A), PS, PE, db)
        self.assertEqual((total, jumlah, transfer), (D(5_417_000), 4, 1))
        self.assertEqual((sum((p.jumlah for p in bahan.pemasukan), D(0)), len(bahan.pemasukan)), (total, jumlah))

    async def test_pemasukan_memakai_filter_bersama(self):
        panggilan = []

        def ke_ruang_usaha(household_id, user_id, ps, pe):
            panggilan.append((household_id, user_id, ps, pe))
            return filter_pemasukan_user(self.H2, user_id, ps, pe)

        with patch.object(muat, "filter_pemasukan_user", ke_ruang_usaha):
            bahan = await self.muat("a")
        self.assertEqual(panggilan, [(self.H, self.A, PS, PE)])
        self.assertEqual([p.keterangan for p in bahan.pemasukan], ["Penjualan"])

    # --- tagihan, target, streak -----------------------------------------------------------------------------

    async def test_tagihan_berikut_hanya_periode_berikutnya(self):
        self.assertEqual((await self.muat("a")).tagihan_berikut, [
            TagihanBerikut(date(2026, 11, 5), "Internet", str(self.S), D(350_000)),
            TagihanBerikut(date(2026, 11, 14), "iCloud", str(self.PA), D(15_000)),
            TagihanBerikut(date(2026, 11, 30), "Air", str(self.S), D(100_000)),
        ])
        self.assertEqual((await self.muat("b")).tagihan_berikut, [
            TagihanBerikut(date(2026, 11, 5), "Internet", str(self.S), D(350_000)),
            TagihanBerikut(date(2026, 11, 7), "Spotify Budi", str(self.PB), D(55_000)),
            TagihanBerikut(date(2026, 11, 30), "Air", str(self.S), D(100_000)),
        ])

        # Gajian 31: jendela 31 Jan - 27 Feb 2027, periode berikutnya 28 Feb - 30 Mar 2027.
        async with self.Session() as db:
            db.add(MonthlySnapshot(envelope_id=self.S, year=2027, month=1, opening_balance=D(0),
                                   closing_balance=D(0), rollover_amount=D(0), allocated_amount=D(0),
                                   spent_amount=D(0)))
            for ket, jatuh_tempo in [("Sebelum", date(2027, 2, 27)), ("Awal", date(2027, 2, 28)),
                                     ("Akhir", date(2027, 3, 30)), ("Sesudah", date(2027, 3, 31))]:
                db.add(RecurringTransaction(envelope_id=self.S, description=ket, amount=D(10_000),
                                            next_run=jatuh_tempo))
            await db.commit()
        bahan = await self.muat("a", ps=date(2027, 1, 31), pe=date(2027, 2, 27), payday=31)
        self.assertEqual([(b.tanggal, b.nama) for b in bahan.tagihan_berikut],
                         [(date(2027, 2, 28), "Awal"), (date(2027, 3, 30), "Akhir")])

    async def test_target_dan_streak(self):
        ani = await self.muat("a")
        self.assertEqual(ani.target, [TargetTabungan("Laptop baru", str(self.PA), D(5_000_000)),
                                      TargetTabungan("Tiket pesawat", str(self.C), D(1_000_000))])
        self.assertEqual(ani.streak_saat_ini, 5)
        budi = await self.muat("b")
        self.assertEqual(budi.target, [TargetTabungan("Gitar listrik", str(self.PB), D(3_000_000)),
                                       TargetTabungan("Tiket pesawat", str(self.C), D(1_000_000))])
        self.assertEqual(budi.streak_saat_ini, 0)  # tanpa baris user_streaks

    async def test_streak_yang_sudah_putus_nol_seperti_di_aplikasi(self):
        async with self.Session() as db:
            await db.execute(update(UserStreak).where(UserStreak.user_id == self.A)
                             .values(last_log_date=self.hari_ini - timedelta(days=3)))
            await db.commit()
        self.assertEqual((await self.muat("a")).streak_saat_ini, 0)

    # --- jendela, kosong, konsistensi, penyusun -----------------------------------------------------------

    async def test_jendela_harus_satu_periode_gajian(self):
        for ps, pe, payday in [(okt(2), PE, 1), (PS, okt(30), 1), (PS, PE, 25)]:
            with self.subTest(ps=ps, pe=pe, payday=payday), self.assertRaises(ValueError):
                await self.muat("a", ps=ps, pe=pe, payday=payday)
        # Sah walau tanggal awalnya bukan tanggal gajian (gajian 31 di Februari): gajian tetap dari parameter.
        bahan = await self.muat("a", ps=date(2027, 2, 28), pe=date(2027, 3, 30), payday=31)
        self.assertEqual((bahan.periode_mulai, bahan.periode_akhir, bahan.payday),
                         (date(2027, 2, 28), date(2027, 3, 30), 31))

    async def test_rumah_tanpa_amplop_memberi_bahan_kosong(self):
        async with self.Session() as db:
            kosong = Household(name="Rumah Kosong", payday_day=1)
            db.add(kosong)
            await db.commit()
        bahan = await self.muat("a", rumah=kosong.id)
        self.assertEqual((bahan.amplop, bahan.transaksi, bahan.pemasukan, bahan.tagihan_berikut, bahan.target),
                         ([], [], [], [], []))
        self.assertEqual(bahan.terpakai_lalu_total, [None, None, None])
        self.assertEqual(bahan.rumah_nama, "Rumah Kosong")
        susun_bulanan(bahan)  # bahan kosong pun memenuhi syarat penyusun

    def periksa_konsisten(self, bahan):
        """Sifat bahan yang dijanjikan pemuat untuk snapshot yang konsisten dengan transaksinya (keputusan 5)."""
        baris = {a.id for a in bahan.amplop}
        for t in bahan.transaksi:
            self.assertTrue(PS <= t.tanggal <= PE, t)
            self.assertIn(t.amplop_id, baris)
        for a in bahan.amplop:
            with self.subTest(penerima=bahan.penerima_nama, amplop=a.nama):
                self.assertEqual(a.akhir, a.awal - a.terpakai)
                self.assertTrue(all(PS <= hari <= PE for hari in a.alokasi_per_hari))
                self.assertEqual(sum(a.alokasi_per_hari.values(), D(0)), a.alokasi)
                self.assertEqual(sum((t.jumlah for t in bahan.transaksi if t.amplop_id == a.id), D(0)), a.terpakai)
        for i in range(3):
            nilai = [a.terpakai_lalu[i] for a in bahan.amplop if a.terpakai_lalu[i] is not None]
            if bahan.terpakai_lalu_total[i] is None:
                self.assertEqual(nilai, [])
            else:
                self.assertLessEqual(sum(nilai, D(0)), bahan.terpakai_lalu_total[i])

    async def test_bahan_konsisten_dengan_snapshot(self):
        ani = await self.muat("a")
        self.periksa_konsisten(ani)
        self.periksa_konsisten(await self.muat("b"))
        # September: baris 500.000 + 60.000 + 50.000 = 610.000 < total 680.000 (D ditutup tanpa baris, 70.000).
        self.assertEqual(sum((a.terpakai_lalu[2] for a in ani.amplop if a.terpakai_lalu[2] is not None), D(0)),
                         D(610_000))
        self.assertEqual(ani.terpakai_lalu_total[2], D(680_000))

    async def test_bahan_bisa_disusun_dan_diserialkan(self):
        data = json.loads(json.dumps(susun_bulanan(await self.muat("a")), ensure_ascii=False))
        self.assertEqual([a["id"] for a in data["amplop"]], [str(self.S), str(self.PA), str(self.C), str(self.F)])
        self.assertEqual([a["ditutup"] for a in data["amplop"]], [False, False, True, True])
        self.assertEqual(data["ringkasan"]["pemasukan"], "5417000.00")
        self.assertEqual(data["ringkasan"]["terpakai"], "779000.00")
        self.assertEqual(data["banding"]["terpakai_lalu"], "680000.00")
        self.assertEqual([b["nama"] for b in data["langganan"]["terbayar"]], ["Netflix", "Spotify", "iCloud"])
        self.assertEqual([b["nama"] for b in data["langganan"]["jatuh_tempo"]], ["Internet", "iCloud", "Air"])
        self.assertEqual([g["nama"] for g in data["sorotan"]["target"]], ["Laptop baru", "Tiket pesawat"])
        for a in data["amplop"]:
            keluar = sum((D(m["jumlah"]) for m in data["mutasi"] if m["arah"] == "keluar" and m["amplop"] == a["nama"]),
                         D(0))
            self.assertEqual(keluar, D(a["terpakai"]), a["nama"])
        self.assertNotIn("Rahasia", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
