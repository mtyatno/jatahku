import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from app.services.reserved import recurring_monthly_reserve, reserve_for_recs

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


def rec(freq, amount, next_run):
    return SimpleNamespace(frequency=SimpleNamespace(value=freq), amount=Decimal(amount), next_run=next_run)


class ReserveForRecsTests(unittest.TestCase):
    def test_due_bill_with_matching_payment_is_not_reserved(self):
        self.assertEqual(reserve_for_recs([rec("monthly", "1600000", date(2026, 7, 6))], [Decimal("1600000")], PE), Decimal("0"))

    def test_due_bill_without_matching_payment_stays_reserved(self):
        self.assertEqual(reserve_for_recs([rec("monthly", "1600000", date(2026, 7, 6))], [Decimal("50000")], PE), Decimal("1600000"))

    def test_one_payment_settles_only_one_bill(self):
        recs = [rec("monthly", "100000", date(2026, 7, 6)), rec("monthly", "100000", date(2026, 7, 20))]
        self.assertEqual(reserve_for_recs(recs, [Decimal("100000")], PE), Decimal("100000"))

    def test_yearly_is_not_matched_against_payments(self):
        self.assertEqual(reserve_for_recs([rec("yearly", "1200000", date(2027, 1, 1))], [Decimal("100000")], PE), Decimal("100000"))


if __name__ == "__main__":
    unittest.main()
