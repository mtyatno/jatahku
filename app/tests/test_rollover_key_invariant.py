"""Invariant behind get_previous_rollover (app/services/rollover.py).

get_previous_rollover derives the *previous* snapshot's key from the current
period's (year, month) using plain calendar arithmetic (month - 1). That is
only valid if consecutive budget periods always start in consecutive calendar
months. This test locks that invariant against the period model — if the period
model ever changes so the invariant breaks (e.g. sub-monthly periods), the
arithmetic in get_previous_rollover becomes wrong and this test will catch it.

Run from repo root:  python -m unittest app.tests.test_rollover_key_invariant
"""
import unittest
from datetime import date, timedelta

from app.core.period import get_budget_period, get_previous_period

PAYDAYS = [1, 15, 28, 29, 30, 31]


def _naive_prev_key(year, month):
    """Exactly what get_previous_rollover computes."""
    if month == 1:
        return (year - 1, 12)
    return (year, month - 1)


def _iter(year_from, year_to):
    d = date(year_from, 1, 1)
    end = date(year_to, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)


class TestRolloverKeyInvariant(unittest.TestCase):
    def test_naive_prev_key_matches_get_previous_period(self):
        for payday in PAYDAYS:
            for today in _iter(2024, 2026):
                period_start, _ = get_budget_period(payday, today)
                prev_start, _ = get_previous_period(payday, today)
                self.assertEqual(
                    (prev_start.year, prev_start.month),
                    _naive_prev_key(period_start.year, period_start.month),
                    f"payday={payday} today={today}: previous snapshot key "
                    f"({prev_start.year},{prev_start.month}) != month-1 of "
                    f"period_start ({period_start.year},{period_start.month})",
                )

    def test_consecutive_periods_start_in_consecutive_months(self):
        """The structural reason the arithmetic is valid."""
        for payday in PAYDAYS:
            for today in _iter(2024, 2026):
                start, end = get_budget_period(payday, today)
                next_start, _ = get_budget_period(payday, end + timedelta(days=1))
                expected_month = 1 if start.month == 12 else start.month + 1
                self.assertEqual(
                    next_start.month, expected_month,
                    f"payday={payday}: period starting {start} -> next starts "
                    f"{next_start}, not in the following calendar month",
                )


if __name__ == "__main__":
    unittest.main()
