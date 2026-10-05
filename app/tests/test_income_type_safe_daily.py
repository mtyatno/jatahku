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
from unittest.mock import patch

from app.tests.fakes import FakeResult, db_with

OCT = (date(2026, 10, 1), date(2026, 10, 31))


class _Oct5(date):
    """spending_prediction reads date.today(); pin it so days_left is always 26."""
    @classmethod
    def today(cls):
        return date(2026, 10, 5)


class IncomeTypeSafeDailyTests(unittest.IsolatedAsyncioTestCase):
    """Test that safe_daily is calculated differently per income_type."""

    def setUp(self):
        patcher = patch("app.api.routes.analytics.date", _Oct5)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def predict(self, income_type, allocated="80000", spent="20000", period=OCT, payday_day=1):
        from app.api.routes.analytics import spending_prediction

        user = SimpleNamespace(id=uuid.uuid4(), payday_day=payday_day, income_type=income_type)
        db = db_with(
            FakeResult(uuid.uuid4()),           # household_id
            FakeResult(D(allocated)),           # total_allocated
            FakeResult(D(spent)),               # total_spent
            FakeResult(D("0")),                 # total_rollover
            FakeResult([uuid.uuid4()]),         # env_ids
            FakeResult([]),                     # reserved (no bills)
        )
        return await spending_prediction(period_start=period[0], period_end=period[1], user=user, db=db)

    def assertSafe(self, out, safe_daily, safe_days, income_type):
        self.assertEqual((out["safe_daily"], out["safe_days"], out["income_type"]),
                         (safe_daily, safe_days, income_type))

    async def test_monthly_earner_safe_daily(self):
        """Monthly earner: safe_daily = free / days_left, unchanged from main."""
        out = await self.predict("monthly")
        self.assertEqual(out["total_allocated"], 80000)
        self.assertEqual(out["total_spent"], 20000)
        self.assertEqual(out["free"], 60000)
        self.assertEqual(out["days_left"], 26)
        self.assertSafe(out, 2308, 26, "monthly")  # 60000 / 26

    async def test_daily_earner_safe_daily(self):
        """Daily earner: free must last until tomorrow's income, free / 1."""
        out = await self.predict("daily")
        self.assertEqual(out["free"], 60000)
        self.assertSafe(out, 60000, 1, "daily")

    async def test_weekly_earner_safe_daily(self):
        """Weekly earner: safe_daily = free / 7"""
        out = await self.predict("weekly")
        self.assertSafe(out, 8571, 7, "weekly")

    async def test_irregular_earner_safe_daily(self):
        """Irregular earner: safe_daily = free / days_left (like monthly)"""
        out = await self.predict("irregular")
        self.assertSafe(out, 2308, 26, "irregular")

    async def test_null_income_type_defaults_to_monthly(self):
        """Null income_type should default to monthly logic"""
        out = await self.predict(None)
        self.assertSafe(out, 2308, 26, "monthly")

    async def test_unknown_income_type_defaults_to_monthly(self):
        out = await self.predict("fortnightly")
        self.assertSafe(out, 2308, 26, "monthly")

    async def test_daily_overspent_returns_negative_free(self):
        """Daily earner below zero: safe_daily 0 and a negative free (the card warns on it)."""
        out = await self.predict("daily", allocated="50000", spent="65000")
        self.assertEqual(out["free"], -15000)
        self.assertSafe(out, 0, 1, "daily")

    async def test_past_period_matches_main_for_every_type(self):
        """Closed period (Sep, today 5 Oct): days_left 0, so safe_daily 0 as on main."""
        for income_type in ("daily", "weekly", "monthly", "irregular", None):
            with self.subTest(income_type=income_type):
                out = await self.predict(income_type, period=(date(2026, 9, 1), date(2026, 9, 30)))
                self.assertEqual(out["free"], 60000)
                self.assertEqual((out["days_left"], out["safe_daily"], out["safe_days"]), (0, 0, 0))

    async def test_last_day_of_current_period_is_not_past(self):
        """Period ending today (payday 6): daily still covers today, monthly stays 0 as on main."""
        period = (date(2026, 9, 6), date(2026, 10, 5))
        daily = await self.predict("daily", period=period, payday_day=6)
        monthly = await self.predict("monthly", period=period, payday_day=6)
        self.assertEqual(daily["days_left"], 0)
        self.assertSafe(daily, 60000, 1, "daily")
        self.assertSafe(monthly, 0, 0, "monthly")


if __name__ == "__main__":
    unittest.main()
