"""Unit tests for advisor reserve/projection helpers (Plan B2 §6a, §6d)."""
import unittest
from decimal import Decimal

from app.services.advisor.context import _monthly_reserve
from app.services.advisor.sinking import _frequency_monthly_reserve


class WeeklyReserveTests(unittest.TestCase):
    def test_context_weekly_reserve_uses_4_33_weeks(self):
        # 100000/week * 52 / 12 = 433333.33...
        got = _monthly_reserve(Decimal("100000"), "weekly")
        self.assertEqual(got, Decimal("100000") * Decimal("52") / 12)

    def test_context_monthly_and_yearly_unchanged(self):
        self.assertEqual(_monthly_reserve(Decimal("120000"), "monthly"), Decimal("120000"))
        self.assertEqual(_monthly_reserve(Decimal("1200000"), "yearly"), Decimal("100000"))

    def test_sinking_weekly_reserve_uses_4_33_weeks(self):
        got = _frequency_monthly_reserve(Decimal("100000"), "weekly")
        self.assertEqual(got, Decimal("100000") * Decimal("52") / 12)

    def test_sinking_other_frequencies_unchanged(self):
        self.assertEqual(_frequency_monthly_reserve(Decimal("300000"), "quarterly"), Decimal("100000"))
        self.assertEqual(_frequency_monthly_reserve(Decimal("1200000"), "yearly"), Decimal("100000"))
        self.assertEqual(_frequency_monthly_reserve(Decimal("600000"), "semiannual"), Decimal("100000"))


if __name__ == "__main__":
    unittest.main()
