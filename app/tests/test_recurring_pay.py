import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace


class PayAdvancesAndRecordsTests(unittest.IsolatedAsyncioTestCase):
    async def test_pay_creates_txn_and_advances_next_run(self):
        from app.api.routes.recurring import pay_recurring, PayRequest
        rec = SimpleNamespace(
            id="r1", envelope_id="e1", amount=Decimal("110000"),
            description="Server", frequency=MagicMock(), next_run=date(2026, 7, 3),
        )
        # frequency.value monthly path handled by _next_date; patch _next_date via monkeypatch below
        user = SimpleNamespace(id="u1")
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        # first execute → hid; second → (rec join envelope)
        hid_res = MagicMock(); hid_res.scalar_one_or_none = MagicMock(return_value="h1")
        rec_res = MagicMock(); rec_res.scalar_one_or_none = MagicMock(return_value=rec)
        db.execute = AsyncMock(side_effect=[hid_res, rec_res])

        import app.api.routes.recurring as mod
        orig = mod._next_date
        mod._next_date = lambda cur, freq: date(2026, 8, 3)
        try:
            out = await pay_recurring("r1", PayRequest(amount=None), user=user, db=db)
        finally:
            mod._next_date = orig

        self.assertEqual(rec.next_run, date(2026, 8, 3))
        self.assertEqual(out["prev_next_run"], date(2026, 7, 3))
        self.assertEqual(out["next_run"], date(2026, 8, 3))
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        self.assertEqual(added.amount, Decimal("110000"))

    async def test_pay_custom_amount(self):
        from app.api.routes.recurring import pay_recurring, PayRequest
        rec = SimpleNamespace(id="r1", envelope_id="e1", amount=Decimal("110000"),
                              description="Listrik", frequency=MagicMock(), next_run=date(2026, 7, 3))
        user = SimpleNamespace(id="u1")
        db = MagicMock(); db.add = MagicMock(); db.commit = AsyncMock(); db.refresh = AsyncMock()
        hid_res = MagicMock(); hid_res.scalar_one_or_none = MagicMock(return_value="h1")
        rec_res = MagicMock(); rec_res.scalar_one_or_none = MagicMock(return_value=rec)
        db.execute = AsyncMock(side_effect=[hid_res, rec_res])
        import app.api.routes.recurring as mod
        orig = mod._next_date; mod._next_date = lambda cur, freq: date(2026, 8, 3)
        try:
            await pay_recurring("r1", PayRequest(amount=Decimal("250000")), user=user, db=db)
        finally:
            mod._next_date = orig
        self.assertEqual(db.add.call_args[0][0].amount, Decimal("250000"))


class MarkPaidTests(unittest.IsolatedAsyncioTestCase):
    """POST /recurring/{id}/mark-paid (AI Advisor S4, DAT-06): next_run maju, tanpa transaksi."""

    def _db(self, rec):
        db = MagicMock(); db.add = MagicMock(); db.commit = AsyncMock()
        hid_res = MagicMock(); hid_res.scalar_one_or_none = MagicMock(return_value="h1")
        rec_res = MagicMock(); rec_res.scalar_one_or_none = MagicMock(return_value=rec)
        db.execute = AsyncMock(side_effect=[hid_res, rec_res])
        return db

    async def test_mark_paid_advances_without_txn(self):
        from app.api.routes.recurring import mark_recurring_paid
        from app.models.models import RecurringFrequency
        today = date.today()
        rec = SimpleNamespace(id="r1", envelope_id="e1", amount=Decimal("110000"), description="Listrik",
                              frequency=RecurringFrequency.monthly, next_run=today)
        db = self._db(rec)
        out = await mark_recurring_paid("r1", user=SimpleNamespace(id="u1", payday_day=1), db=db)
        self.assertEqual(out["prev_next_run"], today)
        self.assertGreater(rec.next_run, today)
        self.assertEqual(out["next_run"], rec.next_run)
        db.add.assert_not_called()
        db.commit.assert_awaited_once()

    async def test_mark_paid_next_period_rejected(self):
        from fastapi import HTTPException
        from app.api.routes.recurring import mark_recurring_paid
        from app.models.models import RecurringFrequency
        nanti = date(date.today().year + 1, 1, 15)
        rec = SimpleNamespace(id="r1", envelope_id="e1", amount=Decimal("110000"), description="Listrik",
                              frequency=RecurringFrequency.monthly, next_run=nanti)
        db = self._db(rec)
        with self.assertRaises(HTTPException) as cm:
            await mark_recurring_paid("r1", user=SimpleNamespace(id="u1", payday_day=1), db=db)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(rec.next_run, nanti)
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
