"""Test safe_daily calculation for different income types.

Run: python -m unittest app.tests.test_income_type_safe_daily -v
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


class IncomeTypeSafeDailyTests(unittest.IsolatedAsyncioTestCase):
    """Test that safe_daily is calculated differently per income_type."""

    async def test_monthly_earner_safe_daily(self):
        """Monthly earner: safe_daily = free / days_left"""
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(
            id=uuid.uuid4(),
            payday_day=1,
            income_type='monthly'
        )
        period_start = date(2026, 10, 1)
        period_end = date(2026, 10, 31)

        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D("80000")),             # total_allocated
            FakeResult(D("20000")),             # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )

        out = await spending_prediction(
            period_start=period_start,
            period_end=period_end,
            user=user,
            db=db
        )

        # free = 80000 - 20000 = 60000
        # days_left = 26 (assuming today is around Oct 5)
        # safe_daily = 60000 / 26 ≈ 2307
        self.assertEqual(out["total_allocated"], 80000)
        self.assertEqual(out["total_spent"], 20000)
        self.assertEqual(out["free"], 60000)
        self.assertGreater(out["safe_daily"], 0)
        # For monthly, safe_daily should be free / days_left
        # With 26 days left: 60000 / 26 ≈ 2307
        self.assertAlmostEqual(out["safe_daily"], 2307, delta=100)

    async def test_daily_earner_safe_daily(self):
        """Daily earner: safe_daily = free / 1"""
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(
            id=uuid.uuid4(),
            payday_day=1,
            income_type='daily'
        )
        period_start = date(2026, 10, 1)
        period_end = date(2026, 10, 31)

        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D("80000")),             # total_allocated
            FakeResult(D("20000")),             # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )

        out = await spending_prediction(
            period_start=period_start,
            period_end=period_end,
            user=user,
            db=db
        )

        # free = 80000 - 20000 = 60000
        # safe_daily = 60000 / 1 = 60000
        self.assertEqual(out["total_allocated"], 80000)
        self.assertEqual(out["total_spent"], 20000)
        self.assertEqual(out["free"], 60000)
        # For daily earner, safe_daily should be free / 1
        self.assertAlmostEqual(out["safe_daily"], 60000, delta=1)

    async def test_weekly_earner_safe_daily(self):
        """Weekly earner: safe_daily = free / 7"""
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(
            id=uuid.uuid4(),
            payday_day=1,
            income_type='weekly'
        )
        period_start = date(2026, 10, 1)
        period_end = date(2026, 10, 31)

        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D("80000")),             # total_allocated
            FakeResult(D("20000")),             # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )

        out = await spending_prediction(
            period_start=period_start,
            period_end=period_end,
            user=user,
            db=db
        )

        # free = 80000 - 20000 = 60000
        # safe_daily = 60000 / 7 ≈ 8571
        self.assertEqual(out["total_allocated"], 80000)
        self.assertEqual(out["total_spent"], 20000)
        self.assertEqual(out["free"], 60000)
        # For weekly earner, safe_daily should be free / 7
        self.assertAlmostEqual(out["safe_daily"], 8571, delta=10)

    async def test_irregular_earner_safe_daily(self):
        """Irregular earner: safe_daily = free / days_left (like monthly)"""
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(
            id=uuid.uuid4(),
            payday_day=1,
            income_type='irregular'
        )
        period_start = date(2026, 10, 1)
        period_end = date(2026, 10, 31)

        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D("80000")),             # total_allocated
            FakeResult(D("20000")),             # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )

        out = await spending_prediction(
            period_start=period_start,
            period_end=period_end,
            user=user,
            db=db
        )

        # free = 80000 - 20000 = 60000
        # days_left = 26
        # safe_daily = 60000 / 26 ≈ 2307 (like monthly)
        self.assertEqual(out["total_allocated"], 80000)
        self.assertEqual(out["total_spent"], 20000)
        self.assertEqual(out["free"], 60000)
        # For irregular earner, safe_daily should be free / days_left
        self.assertAlmostEqual(out["safe_daily"], 2307, delta=100)

    async def test_null_income_type_defaults_to_monthly(self):
        """Null income_type should default to monthly logic"""
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(
            id=uuid.uuid4(),
            payday_day=1,
            income_type=None  # NULL in database
        )
        period_start = date(2026, 10, 1)
        period_end = date(2026, 10, 31)

        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D("80000")),             # total_allocated
            FakeResult(D("20000")),             # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )

        out = await spending_prediction(
            period_start=period_start,
            period_end=period_end,
            user=user,
            db=db
        )

        # Should behave like monthly: free / days_left
        self.assertEqual(out["free"], 60000)
        self.assertAlmostEqual(out["safe_daily"], 2307, delta=100)


if __name__ == "__main__":
    unittest.main()
