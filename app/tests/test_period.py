"""Tests for budget-period calculations (app/core/period.py).

Run from repo root:  python -m unittest app.tests.test_period
"""
import unittest
from datetime import date, timedelta

from app.core.period import get_budget_period, get_previous_period


# Days-per-month edge cases + a regular payday + start-of-month
PAYDAYS = [1, 15, 28, 29, 30, 31]


def _iter_year(year):
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)


class TestTodayWithinPeriod(unittest.TestCase):
    """Bug 1: get_budget_period must return a period that CONTAINS today,
    for every payday_day and every calendar day (incl. Feb + 30-day months)."""

    def test_today_always_within_period(self):
        for year in (2024, 2026):  # leap + non-leap
            for payday in PAYDAYS:
                for today in _iter_year(year):
                    start, end = get_budget_period(payday, today)
                    self.assertLessEqual(
                        start, today,
                        f"payday={payday} today={today}: start {start} > today",
                    )
                    self.assertLessEqual(
                        today, end,
                        f"payday={payday} today={today}: today > end {end}",
                    )


class TestPeriodsTile(unittest.TestCase):
    """Periods must tile the timeline: no gaps, no overlaps."""

    def test_next_period_starts_day_after_previous_ends(self):
        for payday in PAYDAYS:
            for today in _iter_year(2026):
                _, end = get_budget_period(payday, today)
                next_start, _ = get_budget_period(payday, end + timedelta(days=1))
                self.assertEqual(
                    next_start, end + timedelta(days=1),
                    f"payday={payday} today={today}: gap/overlap "
                    f"(period ends {end}, next starts {next_start})",
                )

    def test_previous_period_aligns(self):
        for payday in PAYDAYS:
            for today in _iter_year(2026):
                start, _ = get_budget_period(payday, today)
                _, prev_end = get_budget_period(payday, start - timedelta(days=1))
                self.assertEqual(
                    prev_end, start - timedelta(days=1),
                    f"payday={payday} today={today}: prev period end {prev_end} "
                    f"!= day before start {start - timedelta(days=1)}",
                )


class TestCalendarMonthCompatibility(unittest.TestCase):
    """payday_day=1 must behave exactly like a calendar month."""

    def test_payday_1_is_calendar_month(self):
        self.assertEqual(
            get_budget_period(1, date(2026, 3, 15)),
            (date(2026, 3, 1), date(2026, 3, 31)),
        )
        self.assertEqual(
            get_budget_period(1, date(2026, 2, 28)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )
        self.assertEqual(
            get_budget_period(1, date(2024, 2, 15)),  # leap
            (date(2024, 2, 1), date(2024, 2, 29)),
        )


class TestDocstringExamples(unittest.TestCase):
    """The examples documented in get_budget_period must hold."""

    def test_payday_29_examples(self):
        self.assertEqual(
            get_budget_period(29, date(2026, 3, 29)),
            (date(2026, 3, 29), date(2026, 4, 28)),
        )
        self.assertEqual(
            get_budget_period(29, date(2026, 4, 15)),
            (date(2026, 3, 29), date(2026, 4, 28)),
        )


class TestGapDaysRegression(unittest.TestCase):
    """Specific days that were previously orphaned (today outside any period)."""

    def test_known_gap_days(self):
        cases = [
            (31, date(2026, 4, 30)),
            (31, date(2026, 2, 28)),
            (30, date(2026, 2, 28)),
            (29, date(2026, 2, 28)),
            (31, date(2026, 6, 30)),
            (31, date(2024, 2, 29)),  # leap-year boundary
        ]
        for payday, today in cases:
            start, end = get_budget_period(payday, today)
            self.assertTrue(
                start <= today <= end,
                f"payday={payday} today={today}: orphaned (period {start}..{end})",
            )


if __name__ == "__main__":
    unittest.main()
