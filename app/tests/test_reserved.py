import unittest
from datetime import date
from decimal import Decimal
from app.services.reserved import recurring_monthly_reserve

PE = date(2026, 7, 31)


class ReservedTests(unittest.TestCase):
    def test_monthly_due_counts_full(self):
        self.assertEqual(recurring_monthly_reserve("monthly", Decimal("1600000"), date(2026, 7, 6), PE), Decimal("1600000"))

    def test_monthly_paid_counts_zero(self):
        self.assertEqual(recurring_monthly_reserve("monthly", Decimal("1600000"), date(2026, 8, 6), PE), Decimal("0"))

    def test_yearly_is_amount_over_12(self):
        self.assertEqual(recurring_monthly_reserve("yearly", Decimal("1200000"), date(2027, 1, 1), PE), Decimal("100000"))

    def test_weekly_is_52_over_12(self):
        self.assertEqual(recurring_monthly_reserve("weekly", Decimal("120000"), date(2026, 7, 9), PE), Decimal("120000") * Decimal("52") / Decimal("12"))


if __name__ == "__main__":
    unittest.main()
