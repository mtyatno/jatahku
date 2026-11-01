"""Siklus household, Task 3: nilai snapshot murni (`snapshot_values`), alokasi/pengeluaran ikut tersimpan di
`MonthlySnapshot`, dan `recompute_household` (riwayat satu household dihitung ulang oldest-first dengan force, lalu
snapshot periode berjalan dan sesudahnya dibuang karena snapshot hanya boleh ada untuk periode tertutup).

Run: python -m unittest app.tests.test_rollover_snapshot_values -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import itertools
import unittest
import uuid
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from sqlalchemy.dialects import postgresql

from app.core.period import get_closed_periods
from app.services import rollover
from app.tests.fakes import FakeResult, db_with, fixed_date


class FakeSession:
    """Pengganti `AsyncSessionLocal()`: `async with` menghasilkan db mock."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def compiled(statement) -> tuple[str, dict]:
    """Statement → (SQL Postgres dengan spasi dirapatkan, parameter): untuk assert klausa DELETE dan batas kuncinya.
    (`fakes.sql` hanya mengembalikan teks; batas kunci ada di parameternya.)"""
    result = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(result).split()), result.params


class SnapshotValuesTests(unittest.TestCase):
    def test_identity_opening_minus_allocated_is_rollover_in(self):
        for prev, alloc, spent, is_rollover in itertools.product(
            (D(0), D(150000), D(-50000)), (D(0), D(500000)), (D(0), D(400000), D(700000)), (True, False)
        ):
            with self.subTest(prev=prev, alloc=alloc, spent=spent, is_rollover=is_rollover):
                v = rollover.snapshot_values(prev, alloc, spent, is_rollover)
                self.assertEqual(v.opening - v.allocated, prev)
                self.assertEqual(v.closing, v.opening - v.spent)
                # allocated/spent adalah angka yang disimpan ke MonthlySnapshot: harus persis masukan.
                self.assertEqual((v.allocated, v.spent), (alloc, spent))

    def test_rollover_carries_closing(self):
        v = rollover.snapshot_values(D(100000), D(500000), D(400000), True)
        self.assertEqual(v.closing, D(200000))
        self.assertEqual(v.rollover, D(200000))

    def test_non_rollover_resets_surplus(self):
        v = rollover.snapshot_values(D(100000), D(500000), D(400000), False)
        self.assertEqual(v.closing, D(200000))
        self.assertEqual(v.rollover, D(0))

    def test_non_rollover_resets_deficit(self):
        v = rollover.snapshot_values(D(0), D(500000), D(700000), False)
        self.assertEqual(v.closing, D(-200000))
        self.assertEqual(v.rollover, D(0))


class CreateMonthlySnapshotsTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_monthly_snapshots_stores_allocated_and_spent(self):
        household = SimpleNamespace(id=uuid.uuid4())
        env = SimpleNamespace(id=uuid.uuid4(), name="Makan", is_rollover=True)
        db = db_with(
            FakeResult(rows=[household]),  # rumah tangga
            FakeResult(rows=[env]),        # amplop aktif
            FakeResult(None),              # snapshot periode ini belum ada
            FakeResult(D(100000)),         # rollover periode sebelumnya
            FakeResult(D(400000)),         # terpakai
            FakeResult(D(500000)),         # dialokasikan
        )
        with patch.object(rollover, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            result = await rollover.create_monthly_snapshots(date(2026, 9, 25), date(2026, 10, 24))

        # create_monthly_snapshots menelan exception ke results["errors"]; pastikan snapshot memang terbentuk.
        self.assertEqual(result, {"processed": 1, "snapshots_created": 1, "errors": []})
        self.assertEqual(db.add.call_count, 1)
        snap = db.add.call_args.args[0]
        self.assertEqual(snap.allocated_amount, D(500000))
        self.assertEqual(snap.spent_amount, D(400000))
        self.assertEqual(snap.opening_balance, D(600000))
        self.assertEqual(snap.closing_balance, D(200000))
        self.assertEqual(snap.rollover_amount, D(200000))


class RecomputeHouseholdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # recompute_household membuka sesi sendiri untuk `first_activity_date` (di-patch: bawaannya None = tanpa
        # aktivitas, jadi `periods` pemanggil berlaku apa adanya) dan satu lagi untuk SATU DELETE (snapshot periode
        # berjalan dan sesudahnya), sebelum periode tertutup dibangun ulang. Tiap tes mendapat db tiruan yang hanya
        # menerima DELETE itu.
        self.db = db_with(FakeResult(None))
        self.first_activity = AsyncMock(return_value=None)
        self.enterContext(patch.object(rollover, "AsyncSessionLocal", new=lambda: FakeSession(self.db)))
        self.enterContext(patch.object(rollover, "first_activity_date", new=self.first_activity))

    def _deletes(self):
        """Statement yang dieksekusi di sesi tiruan; tepat satu, yaitu DELETE-nya."""
        statements = [c.args[0] for c in self.db.execute.await_args_list]
        self.assertEqual(len(statements), 1, "harus ada tepat satu DELETE kunci periode berjalan")
        return statements[0]

    async def _windows(self, *, first, payday, periods, today):
        """Jendela yang dibangun ulang `recompute_household(hid, payday, periods, today)` bila aktivitas pertama
        household `first`, oldest-first; sekaligus memeriksa bahwa nilai kembalinya satu entri per jendela itu."""
        self.first_activity.return_value = first
        fake = AsyncMock(return_value={"processed": 0, "snapshots_created": 0, "errors": []})
        hid = uuid.uuid4()
        with patch.object(rollover, "create_monthly_snapshots", new=fake):
            out = await rollover.recompute_household(hid, payday, periods, today=today)
        self.first_activity.assert_awaited_once_with(self.db, hid)
        windows = [(c.args[0], c.args[1]) for c in fake.await_args_list]
        self.assertTrue(all(c.kwargs == {"force": True, "household_ids": [hid]} for c in fake.await_args_list))
        self.assertEqual([r["period"] for r in out], [f"{s} → {e}" for s, e in windows])
        return windows

    async def test_recompute_household_extends_periods_back_to_the_first_activity(self):
        # Ruling R18: `periods` dari pemanggil hanya batas bawah. Aktivitas pertama 5 Mar 2025 (periode 25 Feb–24 Mar
        # menurut tanggal 25): 21 periode tertutup, mulai dari periode SEBELUMNYA (25 Jan–24 Feb 2025), bukan 12.
        with self.assertNoLogs("jatahku.rollover", "WARNING"):
            windows = await self._windows(first=date(2025, 3, 5), payday=25, periods=12, today=date(2026, 11, 10))
        self.assertEqual(len(windows), 21)
        self.assertEqual(windows, get_closed_periods(25, date(2026, 11, 10), 21))  # oldest-first, berurutan
        self.assertEqual(windows[0], (date(2025, 1, 25), date(2025, 2, 24)))
        self.assertEqual(windows[-1], (date(2026, 9, 25), date(2026, 10, 24)))

    async def test_recompute_household_keeps_the_callers_minimum_when_history_is_shorter(self):
        # Aktivitas pertama 1 Sep 2026: tiga periode sudah cukup, tetapi pemanggil meminta 12.
        windows = await self._windows(first=date(2026, 9, 1), payday=1, periods=12, today=date(2026, 11, 10))
        self.assertEqual(windows, get_closed_periods(1, date(2026, 11, 10), 12))
        self.assertEqual(windows[0], (date(2025, 11, 1), date(2025, 11, 30)))

    async def test_recompute_household_without_activity_uses_the_callers_periods(self):
        windows = await self._windows(first=None, payday=1, periods=3, today=date(2026, 11, 10))
        self.assertEqual(windows, [
            (date(2026, 8, 1), date(2026, 8, 31)),
            (date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        ])

    async def test_recompute_household_caps_the_extension_with_a_warning(self):
        # Riwayat sejak Jan 2010 = 203 periode; dibatasi MAX_RECOMPUTE_PERIODS (120), yang terbaru tetap tercakup.
        self.assertEqual(rollover.MAX_RECOMPUTE_PERIODS, 120)
        with self.assertLogs("jatahku.rollover", "WARNING") as logs:
            windows = await self._windows(first=date(2010, 1, 1), payday=1, periods=12, today=date(2026, 11, 10))
        self.assertEqual(len(windows), 120)
        self.assertEqual(windows[0], (date(2016, 11, 1), date(2016, 11, 30)))
        self.assertEqual(windows[-1], (date(2026, 10, 1), date(2026, 10, 31)))
        (record,) = logs.records
        self.assertEqual(record.levelname, "WARNING")
        for part in ("203", "120"):
            self.assertIn(part, record.getMessage())

    async def test_recompute_household_oldest_first_force_single_household(self):
        hid = uuid.uuid4()
        fake = AsyncMock(return_value={"processed": 1, "snapshots_created": 1, "errors": []})
        with patch.object(rollover, "create_monthly_snapshots", new=fake):
            out = await rollover.recompute_household(hid, 25, 3, today=date(2026, 10, 31))

        self.assertEqual(fake.await_args_list, [
            call(date(2026, 7, 25), date(2026, 8, 24), force=True, household_ids=[hid]),
            call(date(2026, 8, 25), date(2026, 9, 24), force=True, household_ids=[hid]),
            call(date(2026, 9, 25), date(2026, 10, 24), force=True, household_ids=[hid]),
        ])
        self.assertEqual(
            [r["period"] for r in out],
            ["2026-07-25 → 2026-08-24", "2026-08-25 → 2026-09-24", "2026-09-25 → 2026-10-24"],
        )
        # Bentuk sama dengan respons endpoint recompute hari ini: {"period": ..., **hasil create_monthly_snapshots}.
        self.assertEqual(
            out[0],
            {"period": "2026-07-25 → 2026-08-24", "processed": 1, "snapshots_created": 1, "errors": []},
        )

    async def _periods_with_clock_at_2026_03_15(self, **kwargs):
        """Periode yang dihitung ulang (payday 1, 2 periode) saat `date.today()` di rollover dipalsukan ke 2026-03-15,
        jauh dari jam asli, supaya hasilnya tidak lulus kebetulan."""
        fake = AsyncMock(return_value={"processed": 0, "snapshots_created": 0, "errors": []})
        with patch.object(rollover, "create_monthly_snapshots", new=fake), \
             patch.object(rollover, "date", fixed_date(date(2026, 3, 15))):
            out = await rollover.recompute_household(uuid.uuid4(), 1, 2, **kwargs)
        return [r["period"] for r in out]

    async def test_recompute_household_today_defaults_to_date_today(self):
        # Jalur produksi: pemanggil tidak memberi `today`.
        self.assertEqual(
            await self._periods_with_clock_at_2026_03_15(),
            ["2026-01-01 → 2026-01-31", "2026-02-01 → 2026-02-28"],
        )

    async def test_recompute_household_explicit_today_wins_over_clock(self):
        self.assertEqual(
            await self._periods_with_clock_at_2026_03_15(today=date(2026, 6, 20)),
            ["2026-04-01 → 2026-04-30", "2026-05-01 → 2026-05-31"],
        )

    async def test_recompute_household_deletes_open_period_snapshots_when_payday_moves_later(self):
        """Payday 1 → 25 pada 10 Nov 2026. Job 1 Nov menulis kunci (2026, 10) = 1–31 Okt. Di bawah payday 25 kunci itu
        adalah periode berjalan 25 Okt–24 Nov, yang masih terbuka, tetapi snapshot-nya berisi jendela lama; job tidak
        menimpa kunci yang sudah ada, jadi rollover yang salah itu terbawa selamanya ke periode berikutnya. Maka
        recompute membangun ulang periode tertutup lalu membuang snapshot household ini pada kunci >= (2026, 10)."""
        hid = uuid.uuid4()
        fake = AsyncMock(return_value={"processed": 1, "snapshots_created": 1, "errors": []})
        with patch.object(rollover, "create_monthly_snapshots", new=fake):
            out = await rollover.recompute_household(hid, 25, 12, today=date(2026, 11, 10))

        # Persis 12 periode tertutup menurut payday 25, oldest-first, yang terakhir berakhir 24 Okt 2026.
        closed = [
            (date(2025, 10, 25), date(2025, 11, 24)),
            (date(2025, 11, 25), date(2025, 12, 24)),
            (date(2025, 12, 25), date(2026, 1, 24)),
            (date(2026, 1, 25), date(2026, 2, 24)),
            (date(2026, 2, 25), date(2026, 3, 24)),
            (date(2026, 3, 25), date(2026, 4, 24)),
            (date(2026, 4, 25), date(2026, 5, 24)),
            (date(2026, 5, 25), date(2026, 6, 24)),
            (date(2026, 6, 25), date(2026, 7, 24)),
            (date(2026, 7, 25), date(2026, 8, 24)),
            (date(2026, 8, 25), date(2026, 9, 24)),
            (date(2026, 9, 25), date(2026, 10, 24)),
        ]
        self.assertEqual(
            fake.await_args_list, [call(s, e, force=True, household_ids=[hid]) for s, e in closed]
        )
        self.assertEqual([r["period"] for r in out], [f"{s} → {e}" for s, e in closed])  # nilai kembali tak berubah

        text, params = compiled(self._deletes())
        self.assertEqual(text, (
            "DELETE FROM monthly_snapshots WHERE monthly_snapshots.envelope_id IN "
            "(SELECT envelopes.id FROM envelopes WHERE envelopes.household_id = %(household_id_1)s::UUID) "
            "AND (monthly_snapshots.year > %(year_1)s OR "
            "monthly_snapshots.year = %(year_2)s AND monthly_snapshots.month >= %(month_1)s)"
        ))
        # Household ini saja, kunci (tahun, bulan) >= (2026, 10): awal periode berjalan 25 Okt.
        self.assertEqual(params, {"household_id_1": hid, "year_1": 2026, "year_2": 2026, "month_1": 10})
        self.db.commit.assert_awaited_once()

    async def test_recompute_household_deletes_and_commits_before_the_rebuilds(self):
        # Ruling R20 (mengubah R8): kunci periode berjalan dibuang dan di-commit SEBELUM periode tertutup dibangun
        # ulang. Kuncinya tidak pernah beririsan (setiap kunci tertutup < kunci periode berjalan), jadi urutan ini tidak
        # mengubah angka; tetapi rebuild yang gagal di tengah jalan tidak boleh lagi meninggalkan kunci periode berjalan
        # basi, yang tidak pernah ditimpa job. Aktivitas pertama dibaca paling awal (menentukan jumlah periode).
        events = []

        async def first_activity(db, household_id):
            events.append(("first",))
            return None

        async def rebuild(period_start, period_end, **kwargs):
            events.append(("rebuild", period_start))
            return {"processed": 0, "snapshots_created": 0, "errors": []}

        async def execute(statement):
            events.append(("delete",))
            return FakeResult(None)

        async def commit():
            events.append(("commit",))

        self.first_activity.side_effect = first_activity
        self.db.execute = AsyncMock(side_effect=execute)
        self.db.commit = AsyncMock(side_effect=commit)
        with patch.object(rollover, "create_monthly_snapshots", new=rebuild):
            await rollover.recompute_household(uuid.uuid4(), 25, 2, today=date(2026, 11, 10))
        self.assertEqual(
            events,
            [("first",), ("delete",), ("commit",), ("rebuild", date(2026, 8, 25)), ("rebuild", date(2026, 9, 25))],
        )

    async def test_recompute_household_failed_rebuild_leaves_no_open_period_key(self):
        # Rebuild melempar di periode pertama: DELETE kunci periode berjalan sudah di-commit lebih dulu.
        hid = uuid.uuid4()
        failing = AsyncMock(side_effect=RuntimeError("db mati"))
        with patch.object(rollover, "create_monthly_snapshots", new=failing), \
             self.assertRaisesRegex(RuntimeError, "db mati"):
            await rollover.recompute_household(hid, 25, 12, today=date(2026, 11, 10))
        _, params = compiled(self._deletes())
        self.assertEqual(params, {"household_id_1": hid, "year_1": 2026, "year_2": 2026, "month_1": 10})
        self.db.commit.assert_awaited_once()
        failing.assert_awaited_once()

    async def test_recompute_household_delete_boundary_is_the_open_period_start_key(self):
        # Kunci periode berjalan = (tahun, bulan) AWAL periode, bukan bulan `today`.
        cases = [
            (25, date(2026, 11, 10), (2026, 10)),  # sebelum gajian bulan ini: periode mulai bulan lalu
            (25, date(2026, 11, 25), (2026, 11)),  # tepat hari gajian: periode baru mulai hari ini
            (1, date(2026, 11, 10), (2026, 11)),   # payday 1 = bulan kalender
            (25, date(2027, 1, 10), (2026, 12)),   # lintas tahun: Des 2026, bukan Jan 2027
            (31, date(2027, 3, 1), (2027, 2)),     # payday 31 dijepit ke 28 Feb 2027, jadi periode mulai Februari
        ]
        for payday, today, (year, month) in cases:
            with self.subTest(payday=payday, today=today):
                db = db_with(FakeResult(None))
                with patch.object(rollover, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                     patch.object(rollover, "create_monthly_snapshots",
                                  new=AsyncMock(return_value={"processed": 0, "snapshots_created": 0, "errors": []})):
                    await rollover.recompute_household(uuid.uuid4(), payday, 1, today=today)
                (statement,) = [c.args[0] for c in db.execute.await_args_list]
                _, params = compiled(statement)
                self.assertEqual((params["year_1"], params["year_2"], params["month_1"]), (year, year, month))


class FirstActivityDateTests(unittest.IsolatedAsyncioTestCase):
    """`first_activity_date`: tanggal aktivitas paling awal household (transaksi, atau pemasukan yang dialokasikan ke
    amplopnya), batas mundur recompute. Dua kueri MIN lewat amplop household itu, tanpa filter `is_active` maupun
    `is_deleted`: amplop nonaktif dan transaksi terhapus hanya memperlebar rentangnya (snapshot lama bisa masih
    memuatnya)."""

    async def test_first_activity_date_takes_the_earlier_of_both_minimums(self):
        hid = uuid.uuid4()
        cases = [
            (date(2026, 3, 5), date(2026, 2, 27), date(2026, 2, 27)),  # pemasukan lebih dulu
            (date(2026, 1, 9), date(2026, 2, 27), date(2026, 1, 9)),   # transaksi lebih dulu
            (date(2026, 3, 5), None, date(2026, 3, 5)),                # hanya transaksi
            (None, date(2026, 2, 27), date(2026, 2, 27)),              # hanya pemasukan teralokasi
            (None, None, None),                                        # tanpa aktivitas
        ]
        for first_txn, first_income, expected in cases:
            with self.subTest(first_txn=first_txn, first_income=first_income):
                db = db_with(FakeResult(first_txn), FakeResult(first_income))
                self.assertEqual(await rollover.first_activity_date(db, hid), expected)
                self.assertEqual(db.execute.await_count, 2)

    async def test_first_activity_date_statements_follow_the_households_envelopes(self):
        hid = uuid.uuid4()
        db = db_with(FakeResult(None), FakeResult(None))
        await rollover.first_activity_date(db, hid)
        (txn_sql, txn_params), (income_sql, income_params) = [
            compiled(c.args[0]) for c in db.execute.await_args_list
        ]
        self.assertTrue(txn_sql.startswith("SELECT min(transactions.transaction_date)"), txn_sql)
        self.assertIn("FROM transactions JOIN envelopes ON envelopes.id = transactions.envelope_id", txn_sql)
        self.assertTrue(income_sql.startswith("SELECT min(incomes.income_date)"), income_sql)
        self.assertIn(
            "FROM incomes JOIN allocations ON allocations.income_id = incomes.id "
            "JOIN envelopes ON envelopes.id = allocations.envelope_id",
            income_sql,
        )
        for statement, params in ((txn_sql, txn_params), (income_sql, income_params)):
            self.assertTrue(statement.endswith("WHERE envelopes.household_id = %(household_id_1)s::UUID"), statement)
            self.assertEqual(params, {"household_id_1": hid})  # household ini saja
            self.assertNotIn("is_active", statement)
            self.assertNotIn("is_deleted", statement)


if __name__ == "__main__":
    unittest.main()
