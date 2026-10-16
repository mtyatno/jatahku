import unittest
from datetime import date
from types import SimpleNamespace
from app.services.recurring_status import compute_recurring_status, take_paid_in_period

TODAY = date(2026, 7, 8)
PERIOD_END = date(2026, 7, 31)


class RecurringStatusTests(unittest.TestCase):
    def test_monthly_overdue(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 3), "monthly", TODAY, PERIOD_END), "overdue")

    def test_monthly_due(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 20), "monthly", TODAY, PERIOD_END), "due")

    def test_monthly_paid_next_period(self):
        self.assertEqual(compute_recurring_status(date(2026, 8, 3), "monthly", TODAY, PERIOD_END,
                                                  paid_in_period=True), "paid")

    def test_monthly_new_next_period_is_not_paid(self):
        # Langganan baru dengan jatuh tempo pertama di periode depan: belum dibayar apa pun.
        self.assertEqual(compute_recurring_status(date(2026, 8, 3), "monthly", TODAY, PERIOD_END), "upcoming")

    def test_yearly_upcoming(self):
        self.assertEqual(compute_recurring_status(date(2026, 12, 1), "yearly", TODAY, PERIOD_END), "upcoming")

    def test_yearly_overdue(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 1), "yearly", TODAY, PERIOD_END), "overdue")

    def test_weekly_upcoming_when_future(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 9), "weekly", TODAY, PERIOD_END), "upcoming")



PERIOD_START = date(2026, 7, 1)


def _rec(rid, next_run, desc="Netflix", env="e1", freq="monthly"):
    return SimpleNamespace(id=rid, envelope_id=env, description=desc, next_run=next_run,
                           frequency=SimpleNamespace(value=freq))


class TakePaidInPeriodTests(unittest.TestCase):
    def test_paid_via_bayar_this_period(self):
        pools = {"e1": [(54000, "🔄 Netflix")]}
        paid = take_paid_in_period([_rec(1, date(2026, 8, 5))], pools, PERIOD_START, PERIOD_END)
        self.assertEqual(paid, {1: 54000})
        self.assertEqual(pools["e1"], [])

    def test_new_subscription_without_payment_not_paid(self):
        paid = take_paid_in_period([_rec(1, date(2026, 8, 5))], {}, PERIOD_START, PERIOD_END)
        self.assertEqual(paid, {})

    def test_paid_early_for_next_period_bill(self):
        # Jatuh tempo 5 Agt (periode depan) dibayar lebih awal di Juli → next_run maju ke 5 Sep.
        pools = {"e1": [(295000, "🔄 VPS")]}
        paid = take_paid_in_period([_rec(1, date(2026, 9, 5), desc="VPS")], pools, PERIOD_START, PERIOD_END)
        self.assertEqual(paid, {1: 295000})

    def test_new_next_period_with_other_payment_not_paid(self):
        pools = {"e1": [(54000, "🔄 Spotify")]}
        paid = take_paid_in_period([_rec(1, date(2026, 8, 5))], pools, PERIOD_START, PERIOD_END)
        self.assertEqual(paid, {})

    def test_one_payment_marks_one_subscription(self):
        pools = {"e1": [(54000, "🔄 Netflix")]}
        recs = [_rec(1, date(2026, 8, 5)), _rec(2, date(2026, 8, 9))]
        paid = take_paid_in_period(recs, pools, PERIOD_START, PERIOD_END)
        self.assertEqual(list(paid), [1])


if __name__ == "__main__":
    unittest.main()
