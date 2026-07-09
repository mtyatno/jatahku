import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace


class MonthlyTrendTests(unittest.IsolatedAsyncioTestCase):
    async def test_monthly_trend_returns_6_periods(self):
        # Regression: 35ced24 referenced period_start/period_end (out of scope)
        # instead of loop vars p_start/p_end -> NameError -> 500 on every call,
        # leaving the Analytics page stuck on "Loading...".
        from app.api.routes.analytics import monthly_trend

        user = SimpleNamespace(id="u1", payday_day=27)
        db = MagicMock()
        hid_res = MagicMock()
        hid_res.scalar_one_or_none = MagicMock(return_value="h1")
        scalar_res = MagicMock()
        scalar_res.scalar = MagicMock(return_value=Decimal("100000"))
        income_res = MagicMock()
        income_res.all = MagicMock(return_value=[(Decimal("500000"),), (Decimal("-200000"),)])
        # 1st execute -> hid; then 3 per period (spent + allocated + income) x 6 periods
        db.execute = AsyncMock(side_effect=[hid_res] + [scalar_res, scalar_res, income_res] * 6)

        out = await monthly_trend(user=user, db=db)

        self.assertEqual(len(out), 6)
        for row in out:
            self.assertEqual(row["spent"], 100000.0)
            self.assertEqual(row["allocated"], 100000.0)
            self.assertEqual(row["income"], 500000.0)  # hanya amount > 0 (transfer diabaikan)
            self.assertIn("month", row)


if __name__ == "__main__":
    unittest.main()
