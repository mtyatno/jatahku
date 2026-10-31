"""Tests for get_period_for_month (app/core/period.py) and its use by export._resolve_period.

Run from repo root:  python -m unittest app.tests.test_period_for_month -v
"""
import unittest
from datetime import date
from types import SimpleNamespace

from app.api.routes.export import _resolve_period
from app.core.period import get_period_for_month


class PeriodForMonthTests(unittest.TestCase):
    def test_payday_1_is_calendar_month(self):
        self.assertEqual(get_period_for_month(1, 2026, 2), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_payday_25(self):
        self.assertEqual(get_period_for_month(25, 2026, 1), (date(2026, 1, 25), date(2026, 2, 24)))

    def test_payday_31_across_february_2026(self):
        self.assertEqual(get_period_for_month(31, 2026, 1), (date(2026, 1, 31), date(2026, 2, 27)))
        self.assertEqual(get_period_for_month(31, 2026, 2), (date(2026, 2, 28), date(2026, 3, 30)))
        self.assertEqual(get_period_for_month(31, 2026, 3), (date(2026, 3, 31), date(2026, 4, 29)))

    def test_leap_year(self):
        self.assertEqual(get_period_for_month(30, 2028, 2), (date(2028, 2, 29), date(2028, 3, 29)))

    def test_december_rolls_into_next_year(self):
        self.assertEqual(get_period_for_month(25, 2026, 12), (date(2026, 12, 25), date(2027, 1, 24)))

    def test_export_resolve_period_uses_same_windows(self):
        for p in (1, 15, 25, 28, 29, 30, 31):
            for y in (2026, 2028):
                for m in range(1, 13):
                    user = SimpleNamespace(id=None, payday_day=p)
                    self.assertEqual(_resolve_period(user, year=y, month=m), get_period_for_month(p, y, m))


if __name__ == "__main__":
    unittest.main()
