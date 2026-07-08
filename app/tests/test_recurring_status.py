import unittest
from datetime import date
from app.services.recurring_status import compute_recurring_status

TODAY = date(2026, 7, 8)
PERIOD_END = date(2026, 7, 31)


class RecurringStatusTests(unittest.TestCase):
    def test_monthly_overdue(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 3), "monthly", TODAY, PERIOD_END), "overdue")

    def test_monthly_due(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 20), "monthly", TODAY, PERIOD_END), "due")

    def test_monthly_paid_next_period(self):
        self.assertEqual(compute_recurring_status(date(2026, 8, 3), "monthly", TODAY, PERIOD_END), "paid")

    def test_yearly_upcoming(self):
        self.assertEqual(compute_recurring_status(date(2026, 12, 1), "yearly", TODAY, PERIOD_END), "upcoming")

    def test_yearly_overdue(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 1), "yearly", TODAY, PERIOD_END), "overdue")

    def test_weekly_upcoming_when_future(self):
        self.assertEqual(compute_recurring_status(date(2026, 7, 9), "weekly", TODAY, PERIOD_END), "upcoming")


if __name__ == "__main__":
    unittest.main()
