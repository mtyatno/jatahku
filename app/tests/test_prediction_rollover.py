"""Bebas di Analytics harus ikut menghitung rollover periode lalu, sama seperti Sisa bebas.

Run: python -m unittest app.tests.test_prediction_rollover -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.tests.fakes import FakeResult, db_with

USER = SimpleNamespace(id=uuid.uuid4(), payday_day=27)
PS, PE = date(2026, 9, 27), date(2026, 10, 26)
BILL = SimpleNamespace(frequency=SimpleNamespace(value="monthly"),
                       amount=D("2090000"), next_run=date(2026, 10, 6))


class PredictionRolloverTests(unittest.IsolatedAsyncioTestCase):
    async def test_period_funded_only_by_rollover(self):
        # Periode tanpa pemasukan: semua dana dari rollover periode lalu.
        from app.api.routes.analytics import spending_prediction
        eid = uuid.uuid4()
        db = db_with(
            FakeResult(uuid.uuid4()),        # household id
            FakeResult(D("0")),              # alokasi periode ini
            FakeResult(D("5095174")),        # terpakai
            FakeResult(D("11290000")),       # rollover dari periode lalu
            FakeResult([eid]),               # amplop expense
            FakeResult([BILL]),              # langganan amplop itu
            FakeResult([]),                  # transaksi amplop itu (tak ada yang cocok)
        )
        out = await spending_prediction(period_start=PS, period_end=PE, user=USER, db=db)
        self.assertEqual(out["total_rollover"], 11290000.0)
        self.assertEqual(out["total_available"], 11290000.0)
        self.assertAlmostEqual(out["remaining"], 11290000 - 5095174)
        self.assertAlmostEqual(out["free"], 11290000 - 5095174 - 2090000)


if __name__ == "__main__":
    unittest.main()
