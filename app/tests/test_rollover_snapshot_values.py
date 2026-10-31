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
        # Setelah periode tertutup dibangun ulang, recompute_household membuka sesi sendiri untuk SATU DELETE
        # (snapshot periode berjalan dan sesudahnya). Tiap tes mendapat db tiruan yang hanya menerima kueri itu.
        self.db = db_with(FakeResult(None))
        self.enterContext(patch.object(rollover, "AsyncSessionLocal", new=lambda: FakeSession(self.db)))

    def _deletes(self):
        """Statement yang dieksekusi di sesi tiruan; tepat satu, yaitu DELETE-nya."""
        statements = [c.args[0] for c in self.db.execute.await_args_list]
        self.assertEqual(len(statements), 1, "harus ada tepat satu DELETE setelah periode tertutup dibangun ulang")
        return statements[0]

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

    async def test_recompute_household_deletes_after_the_rebuilds_and_commits(self):
        events = []

        async def rebuild(period_start, period_end, **kwargs):
            events.append(("rebuild", period_start))
            return {"processed": 0, "snapshots_created": 0, "errors": []}

        async def execute(statement):
            events.append(("delete",))
            return FakeResult(None)

        async def commit():
            events.append(("commit",))

        self.db.execute = AsyncMock(side_effect=execute)
        self.db.commit = AsyncMock(side_effect=commit)
        with patch.object(rollover, "create_monthly_snapshots", new=rebuild):
            await rollover.recompute_household(uuid.uuid4(), 25, 2, today=date(2026, 11, 10))
        self.assertEqual(
            events,
            [("rebuild", date(2026, 8, 25)), ("rebuild", date(2026, 9, 25)), ("delete",), ("commit",)],
        )

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


if __name__ == "__main__":
    unittest.main()
