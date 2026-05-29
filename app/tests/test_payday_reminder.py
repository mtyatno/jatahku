"""Tests for payday_reminder_day_index (app/core/period.py).

Run from repo root:  python -m unittest app.tests.test_payday_reminder
"""
import unittest
from datetime import date, timedelta

from app.core.period import payday_reminder_day_index, get_budget_period

PAYDAYS = [1, 15, 28, 29, 30, 31]


def _iter_year(year):
    d = date(year, 1, 1)
    while d <= date(year, 12, 31):
        yield d
        d += timedelta(days=1)


class TestPaydayReminderDayIndex(unittest.TestCase):
    def test_first_three_days_payday_1(self):
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 1)), 0)
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 2)), 1)
        self.assertEqual(payday_reminder_day_index(1, date(2026, 3, 3)), 2)
        self.assertIsNone(payday_reminder_day_index(1, date(2026, 3, 4)))
        self.assertIsNone(payday_reminder_day_index(1, date(2026, 3, 31)))

    def test_capped_payday_31_february(self):
        # payday 31 in Feb 2026 -> period starts Feb 28
        self.assertEqual(payday_reminder_day_index(31, date(2026, 2, 28)), 0)
        self.assertEqual(payday_reminder_day_index(31, date(2026, 3, 1)), 1)
        self.assertEqual(payday_reminder_day_index(31, date(2026, 3, 2)), 2)
        self.assertIsNone(payday_reminder_day_index(31, date(2026, 3, 3)))

    def test_property_matches_period_start(self):
        for payday in PAYDAYS:
            for today in _iter_year(2026):
                idx = payday_reminder_day_index(payday, today)
                start, _ = get_budget_period(payday, today)
                offset = (today - start).days
                if idx is None:
                    self.assertGreater(offset, 2,
                        f"payday={payday} today={today}: None but offset={offset}")
                else:
                    self.assertEqual(idx, offset)
                    self.assertTrue(0 <= idx <= 2)
                    self.assertEqual(today, start + timedelta(days=idx))


if __name__ == "__main__":
    unittest.main()
