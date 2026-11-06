"""Laporan berkala tahap 1, Task 5: job penerbitan tiap jam (`laporan_job`, `terbitkan_household`) dan notifikasi
(`kirim_notifikasi_laporan`); spec 2026-11-01-laporan-berkala-design bagian 3 dan 6d, Ruling R4.

Unit tanpa Postgres: setiap sesi `AsyncSessionLocal` job memakai satu `db` tiruan (`db_with`) yang mengembalikan hasil
kueri berurutan; urutan kueri persiapan satu household ada di `skrip_rumah`. IO di sekeliling diganti di tempat namanya
terikat di `app/services/laporan/job.py`: `current_payday`, `create_monthly_snapshots` (refresh snapshot, Ruling R4),
`muat_bahan`, `kirim_notifikasi_laporan`; `advisor_cache.invalidate` dan `notification_service.kirim` lewat modulnya.
`member_rows`, `ada_aktivitas`, dan `susun_bulanan` asli, dengan `BahanLaporan` sungguhan. Setiap tiruan mencatat ke
`self.kejadian`: urutan langkah beserta household yang kuncinya sedang dipegang. Kunci household terikat ke event loop
tempat ia pertama kali diperebutkan, jadi setiap tes memakai id household baru.

`UjungKeUjungTests` menjalankan job di SQLite dengan `current_payday`, refresh snapshot, pemuat, `kirim`, dan antrean
email yang asli (`AsyncSessionLocal` diganti di setiap modul yang mengikatnya; hanya pengirim SMTP yang dipalsukan);
fixture-nya dijelaskan di kelas itu.

Tahap 2, Task 3: status email diisi saat terbit (`antrean_email.status_awal`, pengaturan semua calon dalam satu kueri)
dan `laporan_job` menjalankan `proses_antrean_email` sesudah sapu notifikasi, di luar kunci household. Antreannya
sendiri diuji di `test_laporan_antrean_email`; di tes unit job ia diganti tiruan yang mencatat kejadian "email".
Run: python -m unittest app.tests.test_laporan_job -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import inspect
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers

from app.core.database import Base
from app.models.models import (
    Allocation, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, Income, MonthlySnapshot,
    Notification, NotificationType, Report, ReportSettings, Transaction, User,
)
from app.services import email_service, household_cycle, notification_service, rollover
from app.services import scheduler as scheduler_mod
from app.services.advisor import advisor_cache
from app.services.laporan import antrean_email, job
from app.services.laporan.muat import muat_bahan
from app.services.laporan.susun import AmplopPeriode, BahanLaporan, TransaksiPeriode, susun_bulanan
from app.tests.fakes import FakeResult, db_with, fixed_date, sql

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
KIRIM_LAPORAN_ASLI = email_service.send_laporan_email   # tanda tangan untuk membaca argumen pengirim tiruan

D = Decimal
UTC = timezone.utc
PS, PE = date(2026, 10, 1), date(2026, 10, 31)  # periode yang baru tutup untuk gajian tanggal 1
HARI_TERBIT = date(2026, 11, 1)
PESAN = "Lihat bagaimana periode kemarin berjalan."
TANPA_ERROR = {"processed": 2, "snapshots_created": 2, "errors": []}
KOSONG = {"terkirim": 0, "gagal": 0, "dilewati": 0, "dicoba_lagi": 0}  # antrean email tanpa kiriman
TERVERIFIKASI = datetime(2026, 10, 2, tzinfo=UTC)
_OTOMATIS = object()


def okt(n: int) -> date:
    return date(2026, 10, n)


def norm(teks: str) -> str:
    """SQL hasil compile berisi newline antar klausa; rapatkan supaya assert tidak bergantung pada tata letak."""
    return " ".join(teks.split())


def params(stmt) -> dict:
    return stmt.compile(dialect=postgresql.dialect()).params


def orang(nama: str, *, email=_OTOMATIS, dibuat: datetime = datetime(2026, 1, 5, 8, tzinfo=UTC)) -> User:
    """User seperti yang dimuat dari tabel `users` (objek ORM transien; kolom yang dibaca job dan pemuat terisi)."""
    return User(id=uuid.uuid4(), name=nama, email=f"{nama.lower()}@contoh.id" if email is _OTOMATIS else email,
                created_at=dibuat, timezone="Asia/Jakarta", payday_day=1)


def rumah_tangga(nama: str = "Rumah Ani", payday: int = 1) -> Household:
    return Household(id=uuid.uuid4(), name=nama, type=HouseholdType.RUMAH_TANGGA, payday_day=payday)


def bahan_laporan(nama: str, *, aktif: bool = True) -> BahanLaporan:
    """Bahan sah terkecil untuk `susun_bulanan`: satu amplop bersama. Aktif = alokasi 500.000 dan satu transaksi
    100.000; tidak aktif = tanpa alokasi dan tanpa transaksi (`ada_aktivitas` False)."""
    alokasi = D(500_000) if aktif else D(0)
    terpakai = D(100_000) if aktif else D(0)
    amplop = AmplopPeriode(
        id="amp-1", nama="Kebutuhan", emoji="🍜", pribadi=False, tujuan="expense", awal=alokasi, alokasi=alokasi,
        terpakai=terpakai, akhir=alokasi - terpakai, rollover=alokasi - terpakai, ditutup=False,
        alokasi_per_hari={PS: alokasi} if aktif else {}, terpakai_lalu=[None, None, None],
    )
    id_penerima = f"id-{nama.lower()}"
    transaksi = [TransaksiPeriode(
        id="trx-1", amplop_id="amp-1", tanggal=okt(5), jumlah=terpakai, keterangan="Belanja", pencatat=nama,
        pencatat_id=id_penerima, milik_penerima=True, penyesuaian=False, tagihan=False,
    )] if aktif else []
    return BahanLaporan(
        penerima_nama=nama, penerima_id=id_penerima, rumah_nama="Rumah Ani", periode_mulai=PS, periode_akhir=PE,
        payday=1,
        angka_per=HARI_TERBIT, amplop=[amplop], transaksi=transaksi, pemasukan=[], tagihan_berikut=[], target=[],
        streak_saat_ini=0, terpakai_lalu_total=[None, None, None],
    )


def skrip_rumah(rumah: Household, anggota: list[User], *, snapshot=True, sudah=(), beraktivitas=True,
                pengaturan=()) -> list:
    """Hasil kueri `terbitkan_household` untuk satu household, berurutan. Sesi persiapan: prasyarat snapshot periode,
    anggota (`member_rows`), `User` anggota, id user yang sudah punya laporan periode itu, aktivitas household di
    jendela, household. Sesi pembangunan: baris `report_settings` para calon (`pengaturan`, bawaan tidak ada). Langkah
    yang tidak tercapai (job berhenti lebih awal) tidak memakai hasilnya."""
    return [
        FakeResult(value=uuid.uuid4() if snapshot else None),
        FakeResult(rows=[(HouseholdRole.member, datetime(2026, 1, 5, tzinfo=UTC), u.id, u.name, 1) for u in anggota]),
        FakeResult(rows=list(anggota)),
        FakeResult(rows=list(sudah)),
        FakeResult(value=beraktivitas),
        FakeResult(value=rumah),
        FakeResult(rows=list(pengaturan)),
    ]


class FakeSession:
    """Pengganti `AsyncSessionLocal()`: `async with` menghasilkan `db` tiruan yang sama untuk setiap sesi."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class PenerimaLayakTests(unittest.TestCase):
    def test_penerima_tidak_layak(self):
        wib = timezone(timedelta(hours=7))
        kasus = [
            # (keterangan, email, created_at, layak)
            ("email biasa, akun lama", "ani@contoh.id", datetime(2026, 1, 5, tzinfo=UTC), True),
            ("tanpa email (hanya Telegram)", None, datetime(2026, 1, 5, tzinfo=UTC), True),
            ("akun terhapus", "deleted_1a2b3c@contoh.id", datetime(2026, 1, 5, tzinfo=UTC), False),
            ("akun diblokir", "banned_1a2b3c@contoh.id", datetime(2026, 1, 5, tzinfo=UTC), False),
            ("awalan hanya dihitung di depan", "ani.deleted_@contoh.id", datetime(2026, 1, 5, tzinfo=UTC), True),
            ("dibuat di hari terakhir periode", "ani@contoh.id", datetime(2026, 10, 31, 23, 59, tzinfo=UTC), True),
            # 1 Nov 06.00 WIB = 31 Okt 23.00 UTC: tanggal server (UTC) masih di dalam periode.
            ("dibuat 1 Nov 06.00 WIB", "ani@contoh.id", datetime(2026, 11, 1, 6, tzinfo=wib), True),
            ("dibuat setelah periode berakhir", "ani@contoh.id", datetime(2026, 11, 1, tzinfo=UTC), False),
            ("tanpa zona (SQLite), setelah periode", "ani@contoh.id", datetime(2026, 11, 1, 0, 30), False),
            ("tanpa zona (SQLite), di dalam periode", "ani@contoh.id", datetime(2026, 10, 31, 23, 30), True),
        ]
        for keterangan, email, dibuat, layak in kasus:
            with self.subTest(keterangan):
                self.assertIs(job.penerima_layak(orang("Ani", email=email, dibuat=dibuat), PE), layak)


class JobTestCase(unittest.IsolatedAsyncioTestCase):
    """Dasar tes unit job. Semua IO tiruan dan tidak pernah menunda, jadi satu-satunya yang bisa membuat job menunggu
    adalah kunci household. Antrean email (`proses_antrean_email`) tiruan: mencatat kejadian "email" dan menjawab
    `KOSONG` kecuali tes mengganti `self.antrean`."""

    def pasang(self, hasil, *, rumah, payday=1, refresh=None, bahan=None):
        """`hasil`: hasil kueri berurutan untuk semua sesi job. `rumah`: id household yang kuncinya dicatat.
        `payday`: tanggal gajian yang dibaca di dalam kunci (None = household sudah dihapus). `refresh`: hasil
        `create_monthly_snapshots` (bawaan tanpa error). `bahan`: {user id: BahanLaporan atau Exception yang
        dilempar}; bawaannya bahan aktif atas nama user. Boleh dipanggil lagi di tes yang sama (run berikutnya)."""
        self.rumah = list(rumah)
        self.kejadian: list[tuple[str, frozenset]] = []
        self.pernyataan: list = []
        antrian = iter(hasil)

        async def execute(stmt):
            self.catat("sql")
            self.pernyataan.append(stmt)
            return next(antrian)

        async def current_payday(household_id):
            self.catat("payday")
            return payday

        async def create(period_start, period_end, **kwargs):
            self.catat("refresh")
            return dict(refresh or TANPA_ERROR)

        async def invalidate(household_id):
            self.catat("invalidate")

        async def muat(db, user, household, period_start, period_end, payday_day, angka_per):
            self.catat(f"muat {user.name}")
            isi = (bahan or {}).get(user.id) or bahan_laporan(user.name)
            if isinstance(isi, Exception):
                raise isi
            return isi

        async def notifikasi(report_id):
            self.catat("notifikasi")

        async def sapu(today, kecuali=frozenset()):
            self.catat("sapu")
            return 0

        async def antrean(*args, **kwargs):
            self.catat("email")
            return dict(KOSONG)

        self.db = db_with()
        self.db.execute = AsyncMock(side_effect=execute)
        self.db.commit = AsyncMock(side_effect=lambda: self.catat("commit"))
        self.current_payday = AsyncMock(side_effect=current_payday)
        self.refresh = AsyncMock(side_effect=create)
        self.invalidate = AsyncMock(side_effect=invalidate)
        self.muat = AsyncMock(side_effect=muat)
        self.notifikasi = AsyncMock(side_effect=notifikasi)
        self.sapu = AsyncMock(side_effect=sapu)
        self.antrean = AsyncMock(side_effect=antrean)
        self.enterContext(patch.object(job, "AsyncSessionLocal", lambda: FakeSession(self.db)))
        self.enterContext(patch.object(job, "current_payday", self.current_payday))
        self.enterContext(patch.object(job, "create_monthly_snapshots", self.refresh))
        self.enterContext(patch.object(advisor_cache, "invalidate", self.invalidate))
        self.enterContext(patch.object(job, "muat_bahan", self.muat))
        self.enterContext(patch.object(job, "kirim_notifikasi_laporan", self.notifikasi))
        self.enterContext(patch.object(job, "kirim_notifikasi_tertunda", self.sapu))
        self.enterContext(patch.object(job, "proses_antrean_email", self.antrean))

    def catat(self, nama: str):
        terkunci = frozenset(h for h in self.rumah if household_cycle.household_lock(h).locked())
        self.kejadian.append((nama, terkunci))

    def urutan(self) -> list[str]:
        return [nama for nama, _ in self.kejadian]

    def laporan_baru(self) -> list:
        return [c.args[0] for c in self.db.add.call_args_list]

    async def giliran(self):
        """Beri task job giliran berjalan sampai ia selesai atau tertahan (kunci)."""
        for _ in range(10):
            await asyncio.sleep(0)


class TerbitkanHouseholdTests(JobTestCase):
    async def test_terbit_satu_per_anggota_dan_idempoten(self):
        rumah, ani, budi = rumah_tangga(), orang("Ani"), orang("Budi")
        self.pasang(skrip_rumah(rumah, [ani, budi]), rumah=[rumah.id])

        ids = await job.terbitkan_household(rumah.id, HARI_TERBIT)

        laporan = self.laporan_baru()
        self.assertEqual([type(r) for r in laporan], [Report, Report])
        self.assertEqual(ids, [r.id for r in laporan])
        self.assertEqual(len({i for i in ids if i is not None}), 2)
        for r, user in zip(laporan, (ani, budi)):
            with self.subTest(user.name):
                self.assertEqual(
                    (r.user_id, r.household_id, r.jenis, r.periode_mulai, r.periode_akhir, r.payday_day),
                    (user.id, rumah.id, "bulanan", PS, PE, 1),
                )
                self.assertEqual(r.data, susun_bulanan(bahan_laporan(user.name)))  # data dari bahan anggota itu
                self.assertEqual((r.data["judul"], r.data["penerima"]["nama"], r.data["ringkasan"]["terpakai"]),
                                 ("Laporan Oktober 2026", user.name, "100000.00"))
                # Tahap 2: status email diisi saat terbit; email keduanya belum terverifikasi.
                self.assertEqual((r.email_status, r.email_alasan), ("dilewati", "belum_verifikasi"))
                self.assertIsNone(r.notified_at)   # diisi setelah notifikasi terkirim, di luar kunci
        self.assertEqual(self.muat.await_args_list, [
            call(self.db, ani, rumah, PS, PE, 1, HARI_TERBIT),
            call(self.db, budi, rumah, PS, PE, 1, HARI_TERBIT),
        ])
        self.db.commit.assert_awaited_once()  # satu commit untuk semua anggota household

        # Jam berikutnya: keduanya sudah punya laporan bulanan periode ini.
        self.pasang(skrip_rumah(rumah, [ani, budi], sudah=[ani.id, budi.id]), rumah=[rumah.id])

        self.assertEqual(await job.terbitkan_household(rumah.id, HARI_TERBIT), [])

        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()
        self.muat.assert_not_awaited()
        self.refresh.assert_not_awaited()  # tidak ada yang dibangun: buku besar tidak ditulis ulang tiap jam
        sudah_ada = self.pernyataan[3]
        teks = norm(sql(sudah_ada))
        for bagian in ("FROM reports", "reports.user_id IN", "reports.jenis = ", "reports.periode_mulai = "):
            self.assertIn(bagian, teks)
        self.assertEqual(sorted(params(sudah_ada).values(), key=str),
                         sorted([[ani.id, budi.id], "bulanan", PS], key=str))

    async def test_terbit_mengisi_status_email(self):
        # Tahap 2 (spec 6c): saat terbit `email_status` = `menunggu`, atau `dilewati` dengan alasannya. Pengaturan semua
        # calon dibaca dalam SATU kueri; tanpa baris = bawaan (email_on). Laporan yang tidak dibangun (tanpa aktivitas)
        # tentu tanpa status.
        rumah = rumah_tangga()
        ani, budi, citra, dewi, eko, fajar = (
            orang("Ani"), orang("Budi"), orang("Citra", email=None), orang("Dewi"), orang("Eko"), orang("Fajar"),
        )
        for u in (ani, dewi, eko, fajar):
            u.email_verified_at = TERVERIFIKASI   # sesudah email: event model mengosongkannya saat email diisi
        pengaturan = [
            ReportSettings(user_id=dewi.id, kata_sandi_enc=None, email_on=False, kuartalan_on=True, tahunan_on=True),
            ReportSettings(user_id=eko.id, kata_sandi_enc="token-tersimpan", email_on=True, kuartalan_on=True,
                           tahunan_on=True),
        ]
        anggota = [ani, budi, citra, dewi, eko, fajar]
        self.pasang(skrip_rumah(rumah, anggota, pengaturan=pengaturan), rumah=[rumah.id],
                    bahan={fajar.id: bahan_laporan("Fajar", aktif=False)})

        ids = await job.terbitkan_household(rumah.id, HARI_TERBIT)

        self.assertEqual(len(ids), 5)
        self.assertEqual({r.user_id: (r.email_status, r.email_alasan) for r in self.laporan_baru()}, {
            ani.id: ("menunggu", None),               # terverifikasi, tanpa baris pengaturan
            budi.id: ("dilewati", "belum_verifikasi"),
            citra.id: ("dilewati", "tanpa_email"),   # hanya Telegram
            dewi.id: ("dilewati", "dimatikan"),
            eko.id: ("menunggu", None),               # baris pengaturan dengan email_on
        })
        [kueri] = [s for s in self.pernyataan if "report_settings" in norm(sql(s))]
        self.assertIn("FROM report_settings WHERE report_settings.user_id IN", norm(sql(kueri)))
        self.assertEqual(list(params(kueri).values()), [[u.id for u in anggota]])
        self.assertEqual(len(self.pernyataan), 7)   # 6 kueri persiapan + 1 untuk pengaturan semua calon

    async def test_jendela_tujuh_hari(self):
        kasus = [
            # (gajian, hari job, terbit?, periode yang baru tutup)
            (1, date(2026, 11, 7), True, (PS, PE)),                         # 7 hari setelah 31 Okt
            (1, date(2026, 11, 8), False, (PS, PE)),                        # 8 hari
            (25, date(2026, 10, 31), True, (date(2026, 9, 25), okt(24))),   # 7 hari setelah 24 Okt
            (25, date(2026, 11, 1), False, (date(2026, 9, 25), okt(24))),   # 8 hari
        ]
        for payday, hari, terbit, (ps, pe) in kasus:
            with self.subTest(payday=payday, hari=hari):
                rumah, ani = rumah_tangga(payday=payday), orang("Ani")
                self.pasang(skrip_rumah(rumah, [ani]), rumah=[rumah.id], payday=payday)

                ids = await job.terbitkan_household(rumah.id, hari)

                self.current_payday.assert_awaited_once_with(rumah.id)
                if terbit:
                    self.assertEqual(len(ids), 1)
                    # Prasyarat memakai kunci snapshot periode itu: (tahun, bulan) AWAL periode, bukan akhirnya.
                    self.assertLessEqual({rumah.id, ps.year, ps.month}, set(params(self.pernyataan[0]).values()))
                    self.refresh.assert_awaited_once_with(ps, pe, force=True, household_ids=[rumah.id])
                    self.assertEqual(self.muat.await_args.args[3:], (ps, pe, payday, hari))  # angka per hari terbit
                    [laporan] = self.laporan_baru()
                    self.assertEqual((laporan.periode_mulai, laporan.periode_akhir, laporan.payday_day),
                                     (ps, pe, payday))
                else:
                    self.assertEqual(ids, [])
                    self.db.execute.assert_not_awaited()  # berhenti sebelum kueri apa pun
                    self.refresh.assert_not_awaited()

    async def test_tanpa_snapshot_tidak_terbit_lalu_terbit(self):
        rumah, ani = rumah_tangga(), orang("Ani")
        # 00.30 hari gajian: job snapshot harian belum memproses periode household ini.
        self.pasang(skrip_rumah(rumah, [ani], snapshot=False), rumah=[rumah.id])

        self.assertEqual(await job.terbitkan_household(rumah.id, HARI_TERBIT), [])

        self.assertEqual(self.urutan(), ["payday", "sql"])  # berhenti setelah prasyarat, sebelum membaca anggota
        self.refresh.assert_not_awaited()  # refresh tidak boleh memenuhi prasyaratnya sendiri
        self.db.add.assert_not_called()
        [prasyarat] = self.pernyataan
        teks = norm(sql(prasyarat))
        for bagian in ("FROM monthly_snapshots JOIN envelopes ON envelopes.id = monthly_snapshots.envelope_id",
                       "envelopes.household_id = ", "monthly_snapshots.year = ", "monthly_snapshots.month = "):
            self.assertIn(bagian, teks)
        self.assertLessEqual({rumah.id, 2026, 10}, set(params(prasyarat).values()))

        # Jam berikutnya snapshot periode itu sudah ada: terbit. Prasyarat dibaca sebelum refresh.
        self.pasang(skrip_rumah(rumah, [ani]), rumah=[rumah.id])

        self.assertEqual(len(await job.terbitkan_household(rumah.id, HARI_TERBIT)), 1)
        self.assertIn("monthly_snapshots", norm(sql(self.pernyataan[0])))
        self.assertLess(self.urutan().index("sql"), self.urutan().index("refresh"))

    async def test_snapshot_belum_ada_di_hari_terakhir_jendela_dicatat_warning(self):
        # Ruling R16: snapshot yang belum ada ditunda tiap jam dengan log DEBUG. Di hari terakhir jendela, household yang
        # beraktivitas di periode itu tidak akan pernah mendapat laporannya bila snapshot tak dibuat hari itu: WARNING,
        # supaya `journalctl -u jatahku | grep -i laporan` menangkapnya. Tanpa angka atau isi laporan di pesannya.
        hari_terakhir = PE + timedelta(days=job.JENDELA_TERBIT_HARI)
        rumah = rumah_tangga()
        self.pasang([FakeResult(value=None), FakeResult(value=True)], rumah=[rumah.id])

        with self.assertLogs("jatahku.laporan", "WARNING") as logs:
            self.assertEqual(await job.terbitkan_household(rumah.id, hari_terakhir), [])

        [catatan] = logs.records
        self.assertEqual(catatan.levelname, "WARNING")
        pesan = catatan.getMessage()
        for bagian in (str(rumah.id), "2026-10-01", "2026-10-31", "laporan"):
            self.assertIn(bagian, pesan)
        self.refresh.assert_not_awaited()
        self.db.add.assert_not_called()
        [prasyarat, aktivitas] = self.pernyataan
        self.assertIn("monthly_snapshots", norm(sql(prasyarat)))
        self.assertIn("FROM transactions", norm(sql(aktivitas)))  # aktivitas periode itu, sama dengan gerbang R9
        self.assertLessEqual({rumah.id, PS, PE}, set(params(aktivitas).values()))

    async def test_snapshot_belum_ada_sebelum_hari_terakhir_atau_tanpa_aktivitas_hanya_debug(self):
        kasus = [
            # (nama, hari job, hasil kueri berurutan, jumlah kueri)
            ("hari terbit", HARI_TERBIT, [FakeResult(value=None)], 1),
            ("hari keenam", PE + timedelta(days=6), [FakeResult(value=None)], 1),
            ("hari terakhir tanpa aktivitas", PE + timedelta(days=7), [FakeResult(value=None), FakeResult(value=False)],
             2),
        ]
        for nama, hari, hasil, jumlah_kueri in kasus:
            with self.subTest(nama):
                rumah = rumah_tangga()
                self.pasang(hasil, rumah=[rumah.id])

                with self.assertLogs("jatahku.laporan", "DEBUG") as logs:
                    self.assertEqual(await job.terbitkan_household(rumah.id, hari), [])

                self.assertEqual([r.levelname for r in logs.records], ["DEBUG"])
                self.assertIn(str(rumah.id), logs.records[0].getMessage())
                self.assertEqual(len(self.pernyataan), jumlah_kueri)
                self.refresh.assert_not_awaited()

    async def test_tanpa_aktivitas_dilewati(self):
        rumah, ani, budi = rumah_tangga(), orang("Ani"), orang("Budi")
        tanpa_aktivitas = {budi.id: bahan_laporan("Budi", aktif=False)}
        self.pasang(skrip_rumah(rumah, [ani, budi]), rumah=[rumah.id], bahan=tanpa_aktivitas)

        ids = await job.terbitkan_household(rumah.id, HARI_TERBIT)

        [laporan] = self.laporan_baru()
        self.assertEqual((laporan.user_id, ids), (ani.id, [laporan.id]))
        self.assertEqual(self.muat.await_count, 2)  # Budi dimuat, tetapi lingkupnya tanpa alokasi dan transaksi

        # Tak satu anggota pun beraktivitas: tidak ada laporan kosong dan tidak ada commit.
        semua_kosong = {u.id: bahan_laporan(u.name, aktif=False) for u in (ani, budi)}
        self.pasang(skrip_rumah(rumah, [ani, budi]), rumah=[rumah.id], bahan=semua_kosong)

        self.assertEqual(await job.terbitkan_household(rumah.id, HARI_TERBIT), [])
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_rumah_tanpa_aktivitas_tidak_menulis_ulang_buku_besar(self):
        # Household tanpa transaksi maupun alokasi di jendela (mis. akun yang tidak dipakai lagi): tak satu anggota pun
        # bisa lolos `ada_aktivitas`, jadi job berhenti sebelum refresh. Tanpa ini buku besarnya ditulis ulang tiap jam
        # selama 7 hari, karena anggotanya tetap belum punya laporan.
        rumah, ani = rumah_tangga(), orang("Ani")
        self.pasang(skrip_rumah(rumah, [ani], beraktivitas=False), rumah=[rumah.id])

        self.assertEqual(await job.terbitkan_household(rumah.id, HARI_TERBIT), [])

        self.refresh.assert_not_awaited()
        self.invalidate.assert_not_awaited()
        self.muat.assert_not_awaited()
        aktivitas = self.pernyataan[4]
        teks = norm(sql(aktivitas))
        for bagian in ("FROM transactions", "transactions.is_deleted = false", "transactions.transaction_date >= ",
                       "transactions.transaction_date <= ", "FROM allocations JOIN incomes", "incomes.income_date >= ",
                       "incomes.income_date <= ", "envelopes.household_id = "):
            self.assertIn(bagian, teks)
        self.assertNotIn("is_active", teks)  # amplop yang sudah ditutup juga dihitung
        self.assertNotIn("owner_id", teks)   # bersama maupun pribadi anggota mana pun
        self.assertLessEqual({rumah.id, PS, PE}, set(params(aktivitas).values()))

    async def test_penerima_tidak_layak_tidak_dibangun(self):
        rumah = rumah_tangga()
        ani = orang("Ani")
        baru = orang("Baru", dibuat=datetime(2026, 11, 1, 0, 10, tzinfo=UTC))  # akun dibuat setelah periode berakhir
        hapus = orang("Hapus", email="deleted_9f8e@contoh.id")
        blokir = orang("Blokir", email="banned_9f8e@contoh.id")
        self.pasang(skrip_rumah(rumah, [ani, baru, hapus, blokir]), rumah=[rumah.id])

        ids = await job.terbitkan_household(rumah.id, HARI_TERBIT)

        self.assertEqual([c.args[1] for c in self.muat.await_args_list], [ani])
        [laporan] = self.laporan_baru()
        self.assertEqual((laporan.user_id, ids), (ani.id, [laporan.id]))
        self.assertIn([ani.id], params(self.pernyataan[3]).values())  # laporan lama hanya dicari untuk yang layak

        # Tak satu anggota pun layak: berhenti sebelum refresh.
        self.pasang(skrip_rumah(rumah, [baru, hapus]), rumah=[rumah.id])

        self.assertEqual(await job.terbitkan_household(rumah.id, HARI_TERBIT), [])
        self.refresh.assert_not_awaited()
        self.muat.assert_not_awaited()

    async def test_refresh_paksa_dalam_kunci_sebelum_muat(self):
        # Ruling R4: snapshot periode yang baru tutup dibekukan job snapshot 07.05 WIB, sedangkan mutasi dibaca dari
        # transaksi hidup; refresh paksa household itu sebelum anggota mana pun dimuat menjaga Σ mutasi = terpakai.
        rumah, ani, budi = rumah_tangga(), orang("Ani"), orang("Budi")
        self.pasang(skrip_rumah(rumah, [ani, budi]), rumah=[rumah.id])

        await job.terbitkan_household(rumah.id, HARI_TERBIT)

        self.refresh.assert_awaited_once_with(PS, PE, force=True, household_ids=[rumah.id])
        self.invalidate.assert_awaited_once_with(rumah.id)
        di_dalam = frozenset({rumah.id})
        self.assertEqual(self.kejadian[-7:], [
            ("sql", di_dalam),  # household (persiapan terakhir)
            ("refresh", di_dalam), ("invalidate", di_dalam),
            ("sql", di_dalam),  # pengaturan laporan para calon (status email)
            ("muat Ani", di_dalam), ("muat Budi", di_dalam), ("commit", di_dalam),
        ])

    async def test_household_hilang_dilewati(self):
        # Household dihapus (merge, penghapusan akun) setelah dipilih: dilewati dengan peringatan, kunci dilepas.
        hid = uuid.uuid4()
        self.pasang([], rumah=[hid], payday=None)

        with self.assertLogs("jatahku.laporan", "WARNING") as logs:
            self.assertEqual(await job.terbitkan_household(hid, HARI_TERBIT), [])

        self.db.execute.assert_not_awaited()
        self.refresh.assert_not_awaited()
        self.assertIn(str(hid), logs.records[0].getMessage())
        self.assertFalse(household_cycle.household_lock(hid).locked())


class LaporanJobTests(JobTestCase):
    async def test_ruang_usaha_tidak_diproses(self):
        self.pasang([FakeResult(rows=[])], rumah=[])

        self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})

        [pilih] = self.pernyataan
        teks = norm(sql(pilih))
        self.assertIn("households.type = ", teks)
        self.assertIn("households.id IN (SELECT household_members.household_id FROM household_members)", teks)
        self.assertEqual(list(params(pilih).values()), [HouseholdType.RUMAH_TANGGA])
        self.current_payday.assert_not_awaited()

    async def test_kunci_household_dipegang_saat_membangun(self):
        rumah, ani, budi = rumah_tangga(), orang("Ani"), orang("Budi")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani, budi])], rumah=[rumah.id])
        kunci = household_cycle.household_lock(rumah.id)

        async with kunci:  # mis. recompute riwayat atau job snapshot household ini sedang berjalan
            tugas = asyncio.create_task(job.laporan_job(HARI_TERBIT))
            await self.giliran()
            self.assertFalse(tugas.done())
            self.assertEqual(self.urutan(), ["sql"])  # baru memilih household; tanggal gajian belum dibaca

        self.assertEqual(await asyncio.wait_for(tugas, timeout=1), {"terbit": 2, "gagal": 0, "email": KOSONG})
        di_dalam, di_luar = frozenset({rumah.id}), frozenset()
        self.assertEqual(self.kejadian[1:], [
            ("payday", di_dalam),
            *[("sql", di_dalam)] * 6,  # prasyarat, anggota, user, laporan lama, aktivitas, household
            ("refresh", di_dalam), ("invalidate", di_dalam),
            ("sql", di_dalam),         # pengaturan laporan para calon (status email)
            ("muat Ani", di_dalam), ("muat Budi", di_dalam), ("commit", di_dalam),
            ("notifikasi", di_luar), ("notifikasi", di_luar),  # setelah kunci dilepas
            ("sapu", di_luar),                                  # notifikasi yang tertinggal, setelah semua household
            ("email", di_luar),                                 # antrean email, paling akhir
        ])
        self.assertEqual(self.notifikasi.await_args_list, [call(r.id) for r in self.laporan_baru()])
        self.assertFalse(kunci.locked())

    async def test_gagal_satu_household_tidak_menghentikan_lain(self):
        rumah1, rumah2 = rumah_tangga("Rumah Ani"), rumah_tangga("Rumah Budi")
        ani, budi = orang("Ani"), orang("Budi")
        self.pasang(
            [FakeResult(rows=[rumah1.id, rumah2.id]), *skrip_rumah(rumah1, [ani]), *skrip_rumah(rumah2, [budi])],
            rumah=[rumah1.id, rumah2.id], bahan={ani.id: RuntimeError("boom")},
        )

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            hasil = await job.laporan_job(HARI_TERBIT)

        self.assertEqual(hasil, {"terbit": 1, "gagal": 1, "email": KOSONG})
        [laporan] = self.laporan_baru()
        self.assertEqual((laporan.user_id, laporan.household_id), (budi.id, rumah2.id))
        self.db.commit.assert_awaited_once()  # household pertama tidak menyimpan apa pun
        self.notifikasi.assert_awaited_once_with(laporan.id)
        [catatan] = logs.records
        self.assertIn(str(rumah1.id), catatan.getMessage())
        self.assertIsNotNone(catatan.exc_info)  # logger.exception: traceback ikut dicatat
        self.assertFalse(household_cycle.household_lock(rumah1.id).locked())

    async def test_refresh_gagal_tidak_terbit(self):
        # `create_monthly_snapshots` menelan error per amplop: laporan tidak boleh beku tanpa belanja satu amplop.
        rumah, ani = rumah_tangga(), orang("Ani")
        gagal = {"processed": 2, "snapshots_created": 1, "errors": ["Makan: boom"]}
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id], refresh=gagal)

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            hasil = await job.laporan_job(HARI_TERBIT)

        self.assertEqual(hasil, {"terbit": 0, "gagal": 1, "email": KOSONG})
        self.muat.assert_not_awaited()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()
        self.notifikasi.assert_not_awaited()
        [catatan] = logs.records
        self.assertEqual(catatan.levelname, "ERROR")
        self.assertIn(str(rumah.id), catatan.getMessage())
        self.assertIn("Makan: boom", catatan.getMessage())
        self.invalidate.assert_awaited_once_with(rumah.id)  # refresh sudah menulis sebagian: cache tetap dibuang
        self.assertFalse(household_cycle.household_lock(rumah.id).locked())

        # Jam berikutnya refresh berhasil: laporan terbit.
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id])

        self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 1, "gagal": 0, "email": KOSONG})

    async def test_notifikasi_gagal_tidak_membatalkan_terbit(self):
        rumah, ani, budi = rumah_tangga(), orang("Ani"), orang("Budi")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani, budi])], rumah=[rumah.id])
        self.notifikasi.side_effect = [RuntimeError("lonceng mati"), None]

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            hasil = await job.laporan_job(HARI_TERBIT)

        self.assertEqual(hasil, {"terbit": 2, "gagal": 0, "email": KOSONG})
        pertama, kedua = [r.id for r in self.laporan_baru()]
        self.assertEqual(self.notifikasi.await_args_list, [call(pertama), call(kedua)])
        [catatan] = logs.records
        self.assertIn(str(pertama), catatan.getMessage())

    async def test_sapu_notifikasi_setelah_semua_household_tanpa_mengulang_yang_baru_dicoba(self):
        # Ruling R16: notifikasi yang tertinggal (galat DB, restart di antara commit laporan dan kirim) disusulkan oleh
        # sapu di akhir setiap jalan. Laporan yang sudah dicoba di jalan ini (berhasil atau gagal) tidak dicoba dua kali
        # dalam jam yang sama; household yang gagal tidak menghentikan sapu.
        rumah1, rumah2 = rumah_tangga("Rumah Ani"), rumah_tangga("Rumah Citra")
        ani, budi, citra = orang("Ani"), orang("Budi"), orang("Citra")
        self.pasang(
            [FakeResult(rows=[rumah1.id, rumah2.id]), *skrip_rumah(rumah1, [ani, budi]), *skrip_rumah(rumah2, [citra])],
            rumah=[rumah1.id, rumah2.id], bahan={citra.id: RuntimeError("boom")},
        )
        self.notifikasi.side_effect = [RuntimeError("lonceng mati"), None]

        with self.assertLogs("jatahku.laporan", "ERROR"):
            hasil = await job.laporan_job(HARI_TERBIT)

        self.assertEqual(hasil, {"terbit": 2, "gagal": 1, "email": KOSONG})
        dicoba = frozenset(r.id for r in self.laporan_baru())
        self.assertEqual(len(dicoba), 2)
        self.sapu.assert_awaited_once_with(HARI_TERBIT, kecuali=dicoba)
        self.assertEqual(self.urutan()[-2:], ["sapu", "email"])

    async def test_sapu_yang_gagal_hanya_dicatat(self):
        self.pasang([FakeResult(rows=[])], rumah=[])
        self.sapu.side_effect = RuntimeError("koneksi putus")

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})

        [catatan] = logs.records
        self.assertIn("sapu notifikasi", catatan.getMessage())
        self.assertIsNotNone(catatan.exc_info)
        self.antrean.assert_awaited_once_with()   # sapu yang gagal tidak menghentikan antrean email

    async def test_tanpa_tanggal_memakai_tanggal_server(self):
        # Scheduler memanggil `laporan_job()` tanpa argumen: tanggal server hari itu.
        rumah, ani = rumah_tangga(), orang("Ani")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id])
        self.enterContext(patch.object(job, "date", fixed_date(date(2026, 11, 7))))

        self.assertEqual(await job.laporan_job(), {"terbit": 1, "gagal": 0, "email": KOSONG})

        self.assertEqual(self.muat.await_args.args[3:], (PS, PE, 1, date(2026, 11, 7)))

    async def test_laporan_job_menjalankan_antrean(self):
        # Tahap 2: sesudah sapu notifikasi, di luar kunci household, job menjalankan antrean email tanpa argumen
        # (`sekarang` = waktu server) dan mencatat satu baris INFO ringkasan berisi angka saja. Hasilnya ikut di
        # kembalian job di bawah "email".
        rumah, ani = rumah_tangga(), orang("Ani")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id])
        email = {"terkirim": 2, "gagal": 1, "dilewati": 3, "dicoba_lagi": 4}
        self.antrean.side_effect = None
        self.antrean.return_value = email

        with self.assertLogs("jatahku.laporan", "INFO") as logs:
            hasil = await job.laporan_job(HARI_TERBIT)

        self.assertEqual(hasil, {"terbit": 1, "gagal": 0, "email": email})
        self.antrean.assert_awaited_once_with()
        ringkasan = [c.getMessage() for c in logs.records if c.getMessage().startswith("email laporan:")]
        self.assertEqual(ringkasan, ["email laporan: 2 terkirim, 1 gagal, 3 dilewati, 4 dicoba lagi"])
        self.assertEqual([c.levelname for c in logs.records if c.getMessage() in ringkasan], ["INFO"])

    async def test_antrean_tanpa_kiriman_tidak_mencatat_ringkasan(self):
        # Seperti sapu notifikasi: tiap jam tanpa kiriman tidak menambah baris log.
        rumah, ani = rumah_tangga(), orang("Ani")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id])

        with self.assertLogs("jatahku.laporan", "INFO") as logs:   # "1 laporan terbit"
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 1, "gagal": 0, "email": KOSONG})

        self.assertEqual([c.getMessage() for c in logs.records if c.getMessage().startswith("email laporan:")], [])

    async def test_antrean_yang_gagal_hanya_dicatat(self):
        # Galat di luar satu laporan (mis. database putus saat memilih antrean) tidak menggagalkan job; laporannya
        # tetap di antrean untuk jam berikutnya.
        rumah, ani = rumah_tangga(), orang("Ani")
        self.pasang([FakeResult(rows=[rumah.id]), *skrip_rumah(rumah, [ani])], rumah=[rumah.id])
        self.antrean.side_effect = RuntimeError("koneksi putus")

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 1, "gagal": 0, "email": KOSONG})

        [catatan] = logs.records
        self.assertIn("antrean email", catatan.getMessage())
        self.assertIsNotNone(catatan.exc_info)


class NotifikasiTests(unittest.IsolatedAsyncioTestCase):
    RID = uuid.UUID("5b0d7c1e-3f4a-4b6c-9d8e-7f6a5b4c3d2e")

    def test_teks_notifikasi(self):
        self.assertEqual(job.notifikasi_laporan("Laporan Oktober 2026", self.RID, "https://jatahku.com"), (
            "Laporan Oktober 2026 siap",
            PESAN,
            f"/laporan/{self.RID}",
            "<b>Laporan Oktober 2026 siap</b>\nLihat bagaimana periode kemarin berjalan.\n"
            f'<a href="https://jatahku.com/laporan/{self.RID}">Buka laporan</a>',
        ))

    def pasang(self, report, user, *, kirim=None, diklaim=1, commit_gagal=None):
        """Satu sesi tiruan: kueri laporan, kueri user, lalu UPDATE klaim `notified_at` yang mengenai `diklaim` baris.
        `kirim` = pengganti `notification_service.kirim` (Telegram) atau galat yang dilemparnya; `commit_gagal` = galat
        yang dilempar commit."""
        self.kejadian, self.pernyataan, self.ditambah = [], [], []
        antrian = iter([FakeResult(value=report), FakeResult(value=user), SimpleNamespace(rowcount=diklaim)])

        async def execute(stmt):
            self.kejadian.append("sql")
            self.pernyataan.append(stmt)
            return next(antrian)

        def tambah(objek):
            self.kejadian.append("add")
            self.ditambah.append(objek)

        async def commit():
            self.kejadian.append("commit")
            if commit_gagal is not None:
                raise commit_gagal

        async def kirim_tercatat(*args, **kwargs):
            self.kejadian.append("kirim")
            return {"telegram"}

        self.db = db_with()
        self.db.execute = AsyncMock(side_effect=execute)
        self.db.add = MagicMock(side_effect=tambah)
        self.db.commit = AsyncMock(side_effect=commit)
        self.db.rollback = AsyncMock(side_effect=lambda: self.kejadian.append("rollback"))
        self.kirim = AsyncMock(side_effect=kirim or kirim_tercatat)
        self.enterContext(patch.object(job, "AsyncSessionLocal", lambda: FakeSession(self.db)))
        self.enterContext(patch.object(notification_service, "kirim", self.kirim))
        self.enterContext(patch.object(job, "get_settings", lambda: SimpleNamespace(APP_URL="https://contoh.test")))

    def laporan(self, *, judul="Laporan 25 Sep – 24 Okt 2026", notified_at=None):
        uid = uuid.uuid4()
        report = Report(id=self.RID, user_id=uid, household_id=uuid.uuid4(), jenis="bulanan",
                        periode_mulai=date(2026, 9, 25), periode_akhir=okt(24), payday_day=25,
                        data={"judul": judul}, notified_at=notified_at)
        return report, User(id=uid, name="Ani", email="ani@contoh.id", telegram_id="12345")

    async def test_lonceng_dan_notified_at_satu_transaksi_lalu_telegram(self):
        # Ruling R16: lonceng dan `notified_at` di-commit bersama, didahului klaim bersyarat `notified_at IS NULL`, jadi
        # mengulang tidak pernah membuat lonceng kedua; Telegram menyusul sekali setelah commit.
        report, user = self.laporan()
        self.pasang(report, user)

        self.assertIs(await job.kirim_notifikasi_laporan(self.RID), True)

        self.assertEqual(self.kejadian, ["sql", "sql", "sql", "add", "commit", "kirim"])
        klaim = self.pernyataan[2]
        teks = norm(sql(klaim))
        self.assertTrue(teks.startswith("UPDATE reports SET notified_at="), teks)
        self.assertIn("reports.id = ", teks)
        self.assertIn("reports.notified_at IS NULL", teks)
        nilai = params(klaim)
        self.assertEqual(nilai["id_1"], self.RID)
        self.assertLess(abs(datetime.now(UTC) - nilai["notified_at"]), timedelta(minutes=1))
        [lonceng] = self.ditambah
        self.assertIsInstance(lonceng, Notification)
        self.assertEqual((lonceng.user_id, lonceng.type, lonceng.title, lonceng.message, lonceng.link),
                         (user.id, NotificationType.system, "Laporan 25 Sep – 24 Okt 2026 siap", PESAN,
                          f"/laporan/{self.RID}"))
        self.kirim.assert_awaited_once_with(
            user, NotificationType.system, "Laporan 25 Sep – 24 Okt 2026 siap", PESAN,
            link=f"/laporan/{self.RID}",
            telegram_html="<b>Laporan 25 Sep – 24 Okt 2026 siap</b>\nLihat bagaimana periode kemarin berjalan.\n"
                          f'<a href="https://contoh.test/laporan/{self.RID}">Buka laporan</a>',
            permukaan=("telegram",),
        )

        # Judul di-escape di teks Telegram (parse mode HTML); lonceng menyimpannya apa adanya.
        report, user = self.laporan(judul="Laporan <Rumah & Toko>")
        self.pasang(report, user)

        await job.kirim_notifikasi_laporan(self.RID)

        self.assertEqual(self.ditambah[0].title, "Laporan <Rumah & Toko> siap")
        argumen, kata_kunci = self.kirim.await_args
        self.assertEqual(argumen[2], "Laporan <Rumah & Toko> siap")
        self.assertTrue(kata_kunci["telegram_html"].startswith("<b>Laporan &lt;Rumah &amp; Toko&gt; siap</b>\n"),
                        kata_kunci["telegram_html"])

    async def test_telegram_gagal_tidak_membatalkan_lonceng(self):
        # Telegram best-effort: lonceng dan `notified_at` sudah tersimpan, jadi galatnya hanya dicatat dan tidak membuat
        # sapu mengirim ulang tiap jam selama tujuh hari.
        report, user = self.laporan()
        self.pasang(report, user, kirim=RuntimeError("Forbidden: bot was blocked by the user"))

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertIs(await job.kirim_notifikasi_laporan(self.RID), True)

        self.assertEqual(self.kejadian, ["sql", "sql", "sql", "add", "commit"])
        self.assertIn(str(self.RID), logs.records[0].getMessage())

    async def test_galat_database_tidak_menyimpan_apa_pun_dan_diteruskan(self):
        # Commit gagal: lonceng dan `notified_at` sama-sama batal, galat diteruskan (sapu berikutnya mencoba lagi), dan
        # Telegram tidak dikirim tanpa lonceng.
        report, user = self.laporan()
        self.pasang(report, user, commit_gagal=RuntimeError("koneksi putus"))

        with self.assertRaises(RuntimeError):
            await job.kirim_notifikasi_laporan(self.RID)

        self.assertEqual(self.kejadian, ["sql", "sql", "sql", "add", "commit"])
        self.kirim.assert_not_awaited()

    async def test_klaim_kalah_tidak_membuat_lonceng(self):
        # Proses lain (mis. jalan manual) memberi tahu laporan ini di antara baca dan klaim: UPDATE bersyarat tidak
        # mengenai baris, jadi tidak ada lonceng kedua dan tidak ada Telegram.
        report, user = self.laporan()
        self.pasang(report, user, diklaim=0)

        self.assertIs(await job.kirim_notifikasi_laporan(self.RID), False)

        self.assertEqual(self.kejadian, ["sql", "sql", "sql", "rollback"])
        self.db.commit.assert_not_awaited()
        self.kirim.assert_not_awaited()

    async def test_tidak_dikirim_ulang_atau_untuk_laporan_yang_hilang(self):
        report, user = self.laporan(notified_at=datetime(2026, 11, 1, 0, 31, tzinfo=UTC))
        self.pasang(report, user)
        self.assertIs(await job.kirim_notifikasi_laporan(self.RID), False)
        self.kirim.assert_not_awaited()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()

        self.pasang(None, None)  # laporan terhapus (akun dihapus) sebelum notifikasinya dikirim
        self.assertIs(await job.kirim_notifikasi_laporan(self.RID), False)
        self.kirim.assert_not_awaited()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()


class SapuNotifikasiTests(unittest.IsolatedAsyncioTestCase):
    """`kirim_notifikasi_tertunda` (Ruling R16): laporan yang belum diberi tahu dan terbit dalam jendela tujuh hari."""

    async def test_memilih_yang_belum_diberi_tahu_dalam_jendela_dan_melewati_kecuali(self):
        a, b, c, e = (uuid.uuid4() for _ in range(4))
        db = db_with(FakeResult(rows=[a, b, c, e]))
        hasil = {a: True, c: RuntimeError("koneksi putus"), e: False}  # e: diberi tahu proses lain lebih dulu

        async def kirim(report_id):
            isi = hasil[report_id]
            if isinstance(isi, Exception):
                raise isi
            return isi

        kirim_mock = AsyncMock(side_effect=kirim)
        with patch.object(job, "AsyncSessionLocal", lambda: FakeSession(db)), \
                patch.object(job, "kirim_notifikasi_laporan", kirim_mock), \
                self.assertLogs("jatahku.laporan", "INFO") as logs:
            terkirim = await job.kirim_notifikasi_tertunda(HARI_TERBIT, kecuali=frozenset({b}))

        self.assertEqual(terkirim, 1)
        self.assertEqual(kirim_mock.await_args_list, [call(a), call(c), call(e)])  # b sudah dicoba di jalan ini
        [pilih] = [c_.args[0] for c_ in db.execute.call_args_list]
        teks = norm(sql(pilih))
        for bagian in ("SELECT reports.id FROM reports", "reports.notified_at IS NULL", "reports.terbit_at >= ",
                       "ORDER BY reports.terbit_at"):
            self.assertIn(bagian, teks)
        # Jendela: terbit paling awal pukul 00.00 UTC tujuh hari sebelum hari job.
        self.assertIn(datetime(2026, 10, 25, tzinfo=UTC), params(pilih).values())
        tingkat = {(r.levelname, str(c) in r.getMessage()) for r in logs.records}
        self.assertIn(("ERROR", True), tingkat)  # galat satu laporan dicatat, yang lain tetap dicoba


class RegistrasiTests(unittest.TestCase):
    def test_registrasi_scheduler(self):
        fake = MagicMock()
        with patch.object(scheduler_mod, "scheduler", fake):
            scheduler_mod.start_scheduler()
        calls = [c for c in fake.add_job.call_args_list if c.args and c.args[0] is job.laporan_job]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs, {"trigger": "cron", "minute": 30, "id": "laporan",
                                           "replace_existing": True, "max_instances": 1})
        # Job yang sudah ada tetap terdaftar.
        terdaftar = {c.kwargs.get("id") for c in fake.add_job.call_args_list}
        self.assertLessEqual({"payday_snapshot", "user_summaries", "recurring_transactions", "kotak_maintenance"},
                             terdaftar)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class UjungKeUjungTests(unittest.IsolatedAsyncioTestCase):
    """Satu jam job di hari gajian 1 Nov 2026, di SQLite. Rumah (semua gajian tanggal 1):

        H  Rumah Ani     rumah_tangga  Ani (pemilik), Budi, Citra (akun dibuat 1 Nov)   -> laporan Ani dan Budi
        W  Warung Ani    usaha         Ani, Dewi (hanya anggota warung)                -> tidak diproses
        K  Rumah Eko     rumah_tangga  Eko; aktivitas Oktober, snapshot Oktober belum ada -> tidak terbit
        F  Rumah Fajar   rumah_tangga  Fajar; aktivitas hanya September                 -> tidak terbit, tanpa refresh

    Amplop H: Kebutuhan (bersama, rollover September 100.000), Jajan Ani (pribadi Ani), Hobi Budi (pribadi Budi).
    Snapshot Oktober H, W, dan F dibuat job snapshot harian sungguhan (tanpa force); sesudahnya Ani mencatat listrik
    75.000 bertanggal 20 Okt ke Kebutuhan, jadi snapshot Kebutuhan basi (terpakai 150.000, seharusnya 225.000).
    """

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
        for modul in (job, rollover, household_cycle, notification_service, antrean_email):  # yang mengikat namanya
            self.enterContext(patch.object(modul, "AsyncSessionLocal", self.Session))
        self.invalidate = AsyncMock()
        self.enterContext(patch.object(advisor_cache, "invalidate", self.invalidate))  # tanpa Redis
        self.pengirim = MagicMock(return_value=True)   # tanpa SMTP; antrean email selebihnya asli
        self.enterContext(patch.object(email_service, "send_laporan_email", self.pengirim))
        async with self.Session() as db:
            await self._isi(db)
            await db.commit()

    async def _isi(self, db):
        def user(nama, dibuat):
            u = User(name=nama, email=f"{nama.lower()}@contoh.id", created_at=dibuat)
            db.add(u)
            return u

        ani = user("Ani", datetime(2026, 1, 5, tzinfo=UTC))
        budi = user("Budi", datetime(2026, 3, 1, tzinfo=UTC))
        citra = user("Citra", datetime(2026, 11, 1, 0, 10, tzinfo=UTC))
        dewi = user("Dewi", datetime(2026, 2, 1, tzinfo=UTC))
        eko = user("Eko", datetime(2026, 2, 1, tzinfo=UTC))
        fajar = user("Fajar", datetime(2026, 2, 1, tzinfo=UTC))
        h = Household(name="Rumah Ani", payday_day=1)
        w = Household(name="Warung Ani", type=HouseholdType.USAHA, payday_day=1)
        k = Household(name="Rumah Eko", payday_day=1)
        f = Household(name="Rumah Fajar", payday_day=1)
        db.add_all([h, w, k, f])
        await db.flush()
        for anggota, rumah, peran in [(ani, h, HouseholdRole.owner), (budi, h, HouseholdRole.member),
                                      (citra, h, HouseholdRole.member), (ani, w, HouseholdRole.owner),
                                      (dewi, w, HouseholdRole.member), (eko, k, HouseholdRole.owner),
                                      (fajar, f, HouseholdRole.owner)]:
            db.add(HouseholdMember(user_id=anggota.id, household_id=rumah.id, role=peran))

        def amplop(rumah, nama, hari, pemilik=None):
            # `created_at` berbeda per amplop: pemuat mengurutkan baris menurut waktu amplop dibuat.
            env = Envelope(household_id=rumah.id, name=nama, emoji="", owner_id=pemilik and pemilik.id,
                           is_rollover=True, created_at=datetime(2026, 1, hari, tzinfo=UTC))
            db.add(env)
            return env

        s, pa, pb = amplop(h, "Kebutuhan", 5), amplop(h, "Jajan Ani", 6, ani), amplop(h, "Hobi Budi", 7, budi)
        modal, belanja_eko, dapur = amplop(w, "Modal", 8), amplop(k, "Belanja Eko", 9), amplop(f, "Dapur Fajar", 10)
        await db.flush()
        db.add(MonthlySnapshot(envelope_id=s.id, year=2026, month=9, opening_balance=D(400_000),
                               closing_balance=D(100_000), rollover_amount=D(100_000), allocated_amount=D(400_000),
                               spent_amount=D(300_000)))

        def masuk(rumah, oleh, jumlah, ket, tanggal, alokasi):
            inc = Income(household_id=rumah.id, user_id=oleh.id, amount=D(jumlah), description=ket,
                         income_date=tanggal)
            db.add(inc)
            for env, nilai in alokasi:
                db.add(Allocation(income=inc, envelope_id=env.id, amount=D(nilai)))

        masuk(h, ani, 3_000_000, "Gaji Ani", okt(1), [(s, 2_000_000), (pa, 500_000)])
        masuk(h, budi, 1_000_000, "Gaji Budi", okt(2), [(pb, 300_000)])
        masuk(w, dewi, 800_000, "Penjualan", okt(3), [(modal, 800_000)])
        masuk(k, eko, 500_000, "Gaji Eko", okt(1), [(belanja_eko, 500_000)])
        masuk(f, fajar, 200_000, "Gaji September", date(2026, 9, 1), [(dapur, 200_000)])

        def keluar(env, oleh, jumlah, ket, tanggal):
            db.add(Transaction(envelope_id=env.id, user_id=oleh.id, amount=D(jumlah), description=ket,
                               transaction_date=tanggal))

        keluar(s, ani, 100_000, "Belanja bulanan", okt(5))
        keluar(s, budi, 50_000, "Makan", okt(10))
        keluar(pa, ani, 20_000, "Kopi", okt(12))
        keluar(pb, budi, 30_000, "Senar", okt(15))
        keluar(modal, dewi, 200_000, "Bahan baku", okt(8))
        keluar(belanja_eko, eko, 40_000, "Sayur", okt(9))
        keluar(dapur, fajar, 60_000, "Beras", date(2026, 9, 20))
        await db.flush()
        self.ANI, self.BUDI, self.H, self.W, self.F = ani.id, budi.id, h.id, w.id, f.id
        self.S, self.BELANJA_EKO = s.id, belanja_eko.id

    async def snapshot_okt(self, env_id):
        async with self.Session() as db:
            return (await db.execute(select(MonthlySnapshot).where(
                MonthlySnapshot.envelope_id == env_id, MonthlySnapshot.year == 2026, MonthlySnapshot.month == 10,
            ))).scalar_one_or_none()

    async def id_snapshot_okt(self, household_id) -> set:
        async with self.Session() as db:
            return set((await db.execute(
                select(MonthlySnapshot.id).join(Envelope, Envelope.id == MonthlySnapshot.envelope_id).where(
                    Envelope.household_id == household_id, MonthlySnapshot.year == 2026, MonthlySnapshot.month == 10,
                )
            )).scalars().all())

    async def semua(self, model) -> list:
        async with self.Session() as db:
            return (await db.execute(select(model))).scalars().all()

    async def test_ujung_ke_ujung_sqlite(self):
        # 00.05 hari gajian: job snapshot harian (tanpa force) membekukan Oktober untuk H, W, dan F; K belum.
        await rollover.create_monthly_snapshots(PS, PE, household_ids=[self.H, self.W, self.F])
        self.assertEqual((await self.snapshot_okt(self.S)).spent_amount, D(150_000))
        # 00.20: Ani mencatat tagihan listrik 20 Okt yang terlupa, bertanggal mundur ke periode yang sudah dibekukan.
        async with self.Session() as db:
            db.add(Transaction(envelope_id=self.S, user_id=self.ANI, amount=D(75_000), description="Listrik",
                               transaction_date=okt(20), created_at=datetime(2026, 11, 1, 0, 20, tzinfo=UTC)))
            await db.commit()
        snapshot_w, snapshot_f = await self.id_snapshot_okt(self.W), await self.id_snapshot_okt(self.F)

        self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 2, "gagal": 0, "email": KOSONG})

        laporan = {r.user_id: r for r in await self.semua(Report)}
        self.assertEqual(set(laporan), {self.ANI, self.BUDI})  # bukan Citra, Dewi (warung), Eko, Fajar
        for r in laporan.values():
            self.assertEqual((r.household_id, r.jenis, r.periode_mulai, r.periode_akhir, r.payday_day),
                             (self.H, "bulanan", PS, PE, 1))
            self.assertEqual(r.data["judul"], "Laporan Oktober 2026")
            self.assertEqual(r.data["angka_per"], "2026-11-01")
            self.assertEqual((r.email_status, r.email_alasan), ("dilewati", "belum_verifikasi"))
            self.assertIsNotNone(r.notified_at)
        self.pengirim.assert_not_called()

        # Transaksi bertanggal mundur ada di mutasi DAN di terpakai: refresh menyegarkan snapshot sebelum dimuat.
        ani = laporan[self.ANI].data
        baris = {a["nama"]: a for a in ani["amplop"]}
        self.assertEqual(list(baris), ["Kebutuhan", "Jajan Ani"])
        self.assertEqual(
            {k: baris["Kebutuhan"][k] for k in ("awal", "alokasi", "terpakai", "akhir")},
            {"awal": "2100000.00", "alokasi": "2000000.00", "terpakai": "225000.00", "akhir": "1875000.00"},
        )
        keluar_kebutuhan = [m for m in ani["mutasi"] if m["arah"] == "keluar" and m["amplop"] == "Kebutuhan"]
        self.assertIn({"tanggal": "2026-10-20", "arah": "keluar", "amplop": "Kebutuhan", "keterangan": "Listrik",
                       "jumlah": "75000.00", "pencatat": "Ani", "pencatat_id": str(self.ANI), "penyesuaian": False},
                      keluar_kebutuhan)
        self.assertEqual(sum(D(m["jumlah"]) for m in keluar_kebutuhan), D("225000.00"))
        self.assertEqual((ani["ringkasan"]["pemasukan"], ani["ringkasan"]["terpakai"]), ("3000000.00", "245000.00"))
        self.assertEqual([a["terpakai"] for a in laporan[self.BUDI].data["amplop"]], ["225000.00", "30000.00"])
        disegarkan = await self.snapshot_okt(self.S)
        self.assertEqual((disegarkan.spent_amount, disegarkan.closing_balance), (D(225_000), D(1_875_000)))
        self.invalidate.assert_awaited_once_with(self.H)

        # Yang dibekukan = susun_bulanan(muat_bahan(...)) atas data sesudah job, per penerima.
        async with self.Session() as db:
            rumah = await db.get(Household, self.H)
            for uid in (self.ANI, self.BUDI):
                penerima = await db.get(User, uid)
                self.assertEqual(laporan[uid].data,
                                 susun_bulanan(await muat_bahan(db, penerima, rumah, PS, PE, 1, HARI_TERBIT)))

        notifikasi = {n.user_id: n for n in await self.semua(Notification)}
        self.assertEqual(set(notifikasi), {self.ANI, self.BUDI})
        for uid, n in notifikasi.items():
            self.assertEqual((n.type, n.title, n.message, n.link),
                             (NotificationType.system, "Laporan Oktober 2026 siap", PESAN,
                              f"/laporan/{laporan[uid].id}"))

        # K tanpa snapshot Oktober: refresh tidak dijalankan, jadi tidak membuatkan snapshot yang jadi prasyaratnya.
        self.assertIsNone(await self.snapshot_okt(self.BELANJA_EKO))
        # Warung dan rumah tanpa aktivitas: buku besarnya tidak ditulis ulang.
        self.assertEqual(await self.id_snapshot_okt(self.W), snapshot_w)
        self.assertEqual(await self.id_snapshot_okt(self.F), snapshot_f)

        # Jam berikutnya: tidak ada laporan atau notifikasi baru, dan buku besar H tidak ditulis ulang.
        snapshot_h = await self.id_snapshot_okt(self.H)
        self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})
        self.assertEqual(len(await self.semua(Report)), 2)
        self.assertEqual(len(await self.semua(Notification)), 2)
        self.assertEqual(await self.id_snapshot_okt(self.H), snapshot_h)

    async def test_notifikasi_yang_gagal_disusulkan_tepat_sekali(self):
        # Ruling R16: notifikasi pertama gagal sebelum apa pun tersimpan (galat DB, atau restart di antara commit laporan
        # dan kirim). Laporannya tetap terbit dengan `notified_at` NULL; jam berikutnya sapu menyusulkan tepat satu
        # lonceng, dan jalan-jalan sesudahnya tidak menambah apa pun.
        await rollover.create_monthly_snapshots(PS, PE, household_ids=[self.H, self.W, self.F])
        asli = job.kirim_notifikasi_laporan
        panggilan = []

        async def gagal_sekali(report_id):
            panggilan.append(report_id)
            if len(panggilan) == 1:
                raise RuntimeError("koneksi putus")
            return await asli(report_id)

        with patch.object(job, "kirim_notifikasi_laporan", gagal_sekali), self.assertLogs("jatahku.laporan", "ERROR"):
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 2, "gagal": 0, "email": KOSONG})

        laporan = {r.id: r for r in await self.semua(Report)}
        self.assertEqual([i for i, r in laporan.items() if r.notified_at is None], [panggilan[0]])
        self.assertEqual(len(await self.semua(Notification)), 1)
        self.assertEqual(len(panggilan), 2)  # yang gagal tidak dicoba lagi oleh sapu di jam yang sama

        for _ in range(3):
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})

        notifikasi = await self.semua(Notification)
        self.assertEqual(sorted(n.link for n in notifikasi), sorted(f"/laporan/{i}" for i in laporan))  # satu per laporan
        self.assertTrue(all(r.notified_at is not None for r in await self.semua(Report)))

    async def test_telegram_gagal_tidak_dikirim_ulang_tiap_jam(self):
        # Telegram best-effort: bot diblokir user (galat permanen). Lonceng dan `notified_at` sudah tersimpan sebelum
        # Telegram, jadi sapu tidak mengirim ulang tiap jam selama tujuh hari.
        await rollover.create_monthly_snapshots(PS, PE, household_ids=[self.H, self.W, self.F])
        async with self.Session() as db:
            await db.execute(update(User).where(User.id == self.ANI).values(telegram_id="5550001"))
            await db.commit()
        bot = MagicMock()
        bot.return_value.send_message = AsyncMock(side_effect=RuntimeError("Forbidden: bot was blocked by the user"))
        self.enterContext(patch.object(notification_service, "Bot", bot))
        self.enterContext(patch.object(notification_service, "settings", SimpleNamespace(TELEGRAM_BOT_TOKEN="tes")))

        with self.assertLogs("jatahku.notify", "ERROR"):
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 2, "gagal": 0, "email": KOSONG})
        for _ in range(3):
            self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})

        bot.return_value.send_message.assert_awaited_once()  # hanya Ani yang tertaut; sekali, walau gagal
        self.assertEqual(bot.return_value.send_message.await_args.kwargs["chat_id"], 5550001)
        self.assertEqual(len(await self.semua(Notification)), 2)
        self.assertTrue(all(r.notified_at is not None for r in await self.semua(Report)))

    async def test_laporan_job_menjalankan_antrean_sqlite(self):
        # Tahap 2 ujung ke ujung: Ani terverifikasi, Budi belum. Laporan Ani terbit `menunggu` dan terkirim di jalan
        # yang sama (antrean sesudah sapu); laporan Budi terbit `dilewati`/`belum_verifikasi` dan tidak pernah dikirim.
        # Jam berikutnya tidak ada kiriman kedua.
        await rollover.create_monthly_snapshots(PS, PE, household_ids=[self.H, self.W, self.F])
        async with self.Session() as db:
            (await db.get(User, self.ANI)).email_verified_at = TERVERIFIKASI
            await db.commit()

        self.assertEqual(await job.laporan_job(HARI_TERBIT),
                         {"terbit": 2, "gagal": 0, "email": {**KOSONG, "terkirim": 1}})

        laporan = {r.user_id: r for r in await self.semua(Report)}
        ani, budi = laporan[self.ANI], laporan[self.BUDI]
        self.assertEqual((ani.email_status, ani.email_alasan, ani.email_percobaan), ("terkirim", None, 1))  # klaim = 1
        self.assertIsNotNone(ani.email_terkirim_at)
        self.assertEqual((budi.email_status, budi.email_alasan, budi.email_terkirim_at),
                         ("dilewati", "belum_verifikasi", None))
        self.pengirim.assert_called_once()
        kiriman = inspect.signature(KIRIM_LAPORAN_ASLI).bind(*self.pengirim.call_args.args,
                                                             **self.pengirim.call_args.kwargs)
        kiriman.apply_defaults()
        self.assertEqual(
            {k: kiriman.arguments[k] for k in ("to_email", "subject", "pdf_bytes", "filename")},
            {"to_email": "ani@contoh.id", "subject": "Laporan Oktober 2026 · Jatahku", "pdf_bytes": None,
             "filename": None},   # kata sandi belum diatur: tanpa lampiran
        )

        self.assertEqual(await job.laporan_job(HARI_TERBIT), {"terbit": 0, "gagal": 0, "email": KOSONG})
        self.pengirim.assert_called_once()

    async def test_sapu_hanya_laporan_yang_terbit_dalam_tujuh_hari(self):
        async with self.Session() as db:
            for mulai, terbit in [
                (date(2026, 7, 1), datetime(2026, 10, 24, 23, 59, tzinfo=UTC)),  # sebelum jendela: dibiarkan
                (date(2026, 8, 1), datetime(2026, 10, 25, 0, 0, tzinfo=UTC)),    # tepat di awal jendela
                (date(2026, 9, 1), datetime(2026, 10, 31, 1, 0, tzinfo=UTC)),
            ]:
                db.add(Report(user_id=self.ANI, household_id=self.H, jenis="bulanan", periode_mulai=mulai,
                              periode_akhir=mulai + timedelta(days=29), payday_day=1, data={"judul": "Laporan lama"},
                              terbit_at=terbit))
            await db.commit()

        self.assertEqual(await job.kirim_notifikasi_tertunda(HARI_TERBIT), 2)
        self.assertEqual(await job.kirim_notifikasi_tertunda(HARI_TERBIT), 0)

        laporan = {r.periode_mulai: r for r in await self.semua(Report)}
        self.assertIsNone(laporan[date(2026, 7, 1)].notified_at)
        self.assertIsNotNone(laporan[date(2026, 8, 1)].notified_at)
        self.assertIsNotNone(laporan[date(2026, 9, 1)].notified_at)
        self.assertEqual(sorted(n.link for n in await self.semua(Notification)),
                         sorted(f"/laporan/{laporan[m].id}" for m in (date(2026, 8, 1), date(2026, 9, 1))))


if __name__ == "__main__":
    unittest.main()
