"""Penyesuaian dikecualikan dari laporan 'kapan/item apa' & event pemasukan.

Run: python -m unittest app.tests.test_adjustment_reporting -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.tests.fakes import FakeResult, db_with, sql, executed_sql

NOT_ADJ_TXN = "transactions.balance_check_id IS NULL"
NOT_ADJ_INC = "incomes.balance_check_id IS NULL"
HID, USER_ID = uuid.uuid4(), uuid.uuid4()
USER = SimpleNamespace(id=USER_ID, payday_day=1, timezone=None)
PS, PE = date(2026, 9, 1), date(2026, 9, 30)


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def db_first_then(first, rest):
    """db.execute: hasil pertama `first`, selanjutnya selalu `rest()`."""
    calls = iter([first])
    db = MagicMock()
    db.execute = AsyncMock(side_effect=lambda *a, **k: next(calls, None) or rest())
    return db


class SummaryTests(unittest.TestCase):
    def test_daily_today_list_excludes_adjustments_keeps_privacy_filter(self):
        from app.services.summary import _today_txns_query
        q = sql(_today_txns_query(HID, USER_ID, date(2026, 9, 30)))
        self.assertIn(NOT_ADJ_TXN, q)
        self.assertIn("envelopes.owner_id IS NULL", q)

    def test_weekly_section_excludes_adjustments(self):
        from app.services.summary import _week_txns_query
        self.assertIn(NOT_ADJ_TXN, sql(_week_txns_query(HID, date(2026, 9, 23), date(2026, 9, 30))))


class AnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_spending_chart(self):
        from app.api.routes.analytics import daily_spending
        db = db_with(FakeResult(HID), FakeResult(rows=[]))
        await daily_spending(period_start=PS, period_end=PE, user=USER, db=db)
        self.assertIn(NOT_ADJ_TXN, sql(db.execute.call_args_list[1].args[0]))

    async def test_weekly_pattern(self):
        from app.api.routes.analytics import weekly_pattern
        db = db_with(FakeResult(HID), FakeResult(rows=[]))
        await weekly_pattern(periods=3, user=USER, db=db)
        self.assertIn(NOT_ADJ_TXN, sql(db.execute.call_args_list[1].args[0]))

    async def test_income_totals(self):
        from app.api.routes.analytics import _income_totals
        db = db_with(FakeResult(rows=[]))
        await _income_totals(HID, USER, PS, PE, db)
        self.assertIn(NOT_ADJ_INC, sql(db.execute.call_args.args[0]))

    async def test_net_alloc_by_category(self):
        from app.api.routes.analytics import _net_alloc_by_category
        db = db_with(FakeResult(rows=[]))
        await _net_alloc_by_category(HID, USER, PS, PE, db)
        self.assertIn(NOT_ADJ_INC, sql(db.execute.call_args.args[0]))

    async def test_monthly_trend_allocations(self):
        from app.api.routes.analytics import monthly_trend
        db = db_first_then(FakeResult(HID), lambda: FakeResult(0, rows=[]))
        await monthly_trend(user=USER, db=db)
        alloc_sqls = [s for s in executed_sql(db) if "FROM allocations" in s]
        self.assertEqual(len(alloc_sqls), 6)
        for s in alloc_sqls:
            self.assertIn(NOT_ADJ_INC, s)


class PublicStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_stats_spending_excludes_adjustments(self):
        from app.api.routes.health import public_stats
        db = MagicMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: FakeResult(0))
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db)):
            await public_stats()
        txn_sqls = [s for s in executed_sql(db) if "FROM transactions" in s]
        self.assertEqual(len(txn_sqls), 3)
        for s in txn_sqls:
            self.assertIn(NOT_ADJ_TXN, s)


if __name__ == "__main__":
    unittest.main()
