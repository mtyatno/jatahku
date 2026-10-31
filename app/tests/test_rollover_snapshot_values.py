"""Siklus household, Task 3: nilai snapshot murni (`snapshot_values`), alokasi/pengeluaran ikut tersimpan di
`MonthlySnapshot`, dan `recompute_household` (riwayat satu household dihitung ulang oldest-first dengan force).

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


if __name__ == "__main__":
    unittest.main()
