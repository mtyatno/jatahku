"""Response API menandai penyesuaian (untuk badge UI).

Run: python -m unittest app.tests.test_adjustment_flags -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

from app.models.models import TransactionSource
from app.tests.fakes import FakeResult, db_with

HID, USER_ID = uuid.uuid4(), uuid.uuid4()
USER = SimpleNamespace(id=USER_ID, payday_day=1, timezone=None)
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)


def txn(balance_check_id):
    return SimpleNamespace(
        id=uuid.uuid4(), envelope_id=uuid.uuid4(), user_id=USER_ID, amount=D("5000"),
        description="x", source=TransactionSource.webapp, transaction_date=date(2026, 9, 30),
        created_at=NOW, is_deleted=False, is_private=False, balance_check_id=balance_check_id,
    )


class AdjustmentFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_transactions_flags_adjustments(self):
        from app.api.routes.transactions import list_transactions
        db = db_with(FakeResult(HID), FakeResult(rows=[txn(uuid.uuid4()), txn(None)]))
        out = await list_transactions(envelope_id=None, start_date=None, end_date=None,
                                      limit=20, offset=0, user=USER, db=db)
        self.assertEqual([t.is_adjustment for t in out], [True, False])

    def test_present_transaction_flags_adjustment(self):
        from app.services.visibility import present_transaction
        self.assertTrue(present_transaction(USER_ID, txn(uuid.uuid4()))["is_adjustment"])
        self.assertFalse(present_transaction(USER_ID, txn(None))["is_adjustment"])

    async def test_list_incomes_flags_adjustment(self):
        from app.api.routes.incomes import list_incomes
        inc = SimpleNamespace(id=uuid.uuid4(), amount=D("200000"), description="Penyesuaian saldo",
                              income_date=date(2026, 9, 30), created_at=NOW, balance_check_id=uuid.uuid4())
        db = db_with(FakeResult(HID), FakeResult(rows=[inc]), FakeResult(rows=[]))
        out = await list_incomes(period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), user=USER, db=db)
        self.assertTrue(out[0]["is_adjustment"])


if __name__ == "__main__":
    unittest.main()
