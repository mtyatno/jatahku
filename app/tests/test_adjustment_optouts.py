"""Penyesuaian cocokkan saldo TIDAK boleh memengaruhi limit & pengingat.

Run: python -m unittest app.tests.test_adjustment_optouts -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from app.tests.fakes import FakeResult, db_with, sql

NOT_ADJ_TXN = "transactions.balance_check_id IS NULL"
NOT_ADJ_INC = "incomes.balance_check_id IS NULL"


class FlowOptOutTests(unittest.IsolatedAsyncioTestCase):
    async def test_basic_txn_limit_ignores_adjustments(self):
        from app.services.plan_limits import check_transaction_limit
        db = db_with(FakeResult(0))
        ok, _ = await check_transaction_limit(SimpleNamespace(id=uuid.uuid4(), plan="basic"), db)
        self.assertTrue(ok)
        self.assertIn(NOT_ADJ_TXN, sql(db.execute.call_args.args[0]))

    def test_daily_limit_ignores_adjustments(self):
        from app.services.behavior import spent_today_query
        self.assertIn(NOT_ADJ_TXN, sql(spent_today_query(uuid.uuid4(), uuid.uuid4(), date(2026, 9, 30))))

    async def test_payday_reminder_ignores_adjustment_income(self):
        from app.services.payday_reminder import _has_allocated_this_period
        db = db_with(FakeResult(uuid.uuid4()), FakeResult(0))
        got = await _has_allocated_this_period(
            SimpleNamespace(id=uuid.uuid4()), date(2026, 9, 1), date(2026, 9, 30), db)
        self.assertFalse(got)
        self.assertIn(NOT_ADJ_INC, sql(db.execute.call_args_list[1].args[0]))


if __name__ == "__main__":
    unittest.main()
