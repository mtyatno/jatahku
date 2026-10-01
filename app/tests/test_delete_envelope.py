"""Hapus amplop: sisa sebenarnya (alokasi + rollover − terpakai, termasuk minus)
dipindah ke Tabungan; transaksi TIDAK dipindah; ditolak bila masih ada langganan aktif.

Run: python -m unittest app.tests.test_delete_envelope -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.routes import envelopes as route
from app.models.models import Allocation, Income
from app.tests.fakes import FakeResult, executed_sql

HID, USER_ID, ENV_ID, TAB_ID = (uuid.uuid4() for _ in range(4))
USER = SimpleNamespace(id=USER_ID, payday_day=1)


def make_db(active_subs=0):
    env = SimpleNamespace(id=ENV_ID, name="Makan", is_active=True)
    tab = SimpleNamespace(id=TAB_ID, name="Tabungan")
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        FakeResult(HID),          # household id
        FakeResult(env),          # amplop yang dihapus
        FakeResult(active_subs),  # jumlah langganan aktif
        FakeResult(tab),          # Tabungan
        FakeResult(),             # cadangan bila ada statement lain
    ])
    added = []
    db.add = MagicMock(side_effect=added.append)

    async def flush():
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=flush)
    db.commit = AsyncMock()
    db.added = added
    db.env = env
    return db


def summary_rows(remaining):
    return [
        {"id": ENV_ID, "remaining": D(remaining)},
        {"id": TAB_ID, "remaining": D("5000000")},
    ]


class DeleteEnvelopeTests(unittest.IsolatedAsyncioTestCase):
    async def run_delete(self, db, remaining):
        with patch.object(route, "compute_envelope_summaries",
                          new=AsyncMock(return_value=summary_rows(remaining))):
            await route.delete_envelope(ENV_ID, user=USER, db=db)

    def allocations(self, db):
        return {a.envelope_id: a.amount for a in db.added if isinstance(a, Allocation)}

    async def test_moves_full_remaining_including_rollover(self):
        db = make_db()
        await self.run_delete(db, "900000")  # alokasi 1jt + rollover 200rb − terpakai 300rb
        self.assertEqual(self.allocations(db), {ENV_ID: D("-900000"), TAB_ID: D("900000")})
        income = next(o for o in db.added if isinstance(o, Income))
        self.assertEqual(income.amount, D("0"))  # transfer internal, bukan pemasukan
        self.assertFalse(db.env.is_active)
        db.commit.assert_awaited_once()

    async def test_overspent_envelope_moves_deficit_to_tabungan(self):
        db = make_db()
        await self.run_delete(db, "-50000")
        self.assertEqual(self.allocations(db), {ENV_ID: D("50000"), TAB_ID: D("-50000")})
        self.assertFalse(db.env.is_active)

    async def test_zero_remaining_makes_no_transfer(self):
        db = make_db()
        await self.run_delete(db, "0")
        self.assertEqual(db.added, [])
        self.assertFalse(db.env.is_active)

    async def test_transactions_are_not_moved(self):
        db = make_db()
        await self.run_delete(db, "900000")
        self.assertFalse(any(s.startswith("UPDATE transactions") for s in executed_sql(db)))

    async def test_active_subscriptions_block_delete(self):
        db = make_db(active_subs=2)
        with self.assertRaises(HTTPException) as ctx:
            await self.run_delete(db, "900000")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("2 langganan aktif", ctx.exception.detail)
        self.assertEqual(db.added, [])
        self.assertTrue(db.env.is_active)
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
