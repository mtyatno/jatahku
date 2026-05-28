"""Tests for get_closed_periods (app/core/period.py).

Underpins the self-healing snapshot catch-up: the scheduler must be able to
enumerate every CLOSED budget period (oldest first) so missed snapshots can be
backfilled in dependency order.

Run from repo root:  python -m unittest app.tests.test_closed_periods
"""
import unittest
from datetime import date, timedelta

from app.core.period import (
    get_budget_period,
    get_previous_period,
    get_closed_periods,
)

PAYDAYS = [1, 15, 29, 30, 31]


class TestGetClosedPeriods(unittest.TestCase):
    def test_returns_requested_count_oldest_first(self):
        periods = get_closed_periods(1, date(2026, 5, 15), max_periods=3)
        self.assertEqual(
            periods,
            [
                (date(2026, 2, 1), date(2026, 2, 28)),
                (date(2026, 3, 1), date(2026, 3, 31)),
                (date(2026, 4, 1), date(2026, 4, 30)),
            ],
        )

    def test_none_of_them_contains_today(self):
        for payday in PAYDAYS:
            today = date(2026, 6, 10)
            for start, end in get_closed_periods(payday, today, max_periods=6):
                self.assertLess(
                    end, today,
                    f"payday={payday}: closed period {start}..{end} reaches today {today}",
                )

    def test_periods_are_contiguous_oldest_first(self):
        for payday in PAYDAYS:
            periods = get_closed_periods(payday, date(2026, 7, 3), max_periods=6)
            for (s, e), (ns, ne) in zip(periods, periods[1:]):
                self.assertLess(s, ns, f"payday={payday}: not oldest-first")
                self.assertEqual(
                    ns, e + timedelta(days=1),
                    f"payday={payday}: gap between {e} and {ns}",
                )

    def test_newest_closed_period_is_the_previous_period(self):
        for payday in PAYDAYS:
            today = date(2026, 4, 20)
            periods = get_closed_periods(payday, today, max_periods=4)
            self.assertEqual(
                periods[-1], get_previous_period(payday, today),
                f"payday={payday}: newest closed != get_previous_period",
            )

    def test_newest_closed_period_ends_day_before_current_period(self):
        for payday in PAYDAYS:
            today = date(2026, 9, 14)
            current_start, _ = get_budget_period(payday, today)
            periods = get_closed_periods(payday, today, max_periods=2)
            self.assertEqual(periods[-1][1], current_start - timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
