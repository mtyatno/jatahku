"""Tests for budget-period calculations (app/core/period.py).

Run from repo root:  python -m unittest app.tests.test_period
"""
import unittest
from datetime import date, timedelta

from app.core.period import document_date_kind, get_budget_period, get_previous_period


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


class TestDocumentDateKind(unittest.TestCase):
    """Tanggal dokumen (struk/bukti) terhadap periode berjalan: bot hanya bertanya untuk "past" (Task H1)."""

    def kind(self, doc, payday, today):
        return document_date_kind(doc, payday_day=payday, today=today)

    def test_owner_payday_27_boundaries(self):
        today = date(2026, 10, 28)   # periode 27 Okt–26 Nov
        for doc, expected in [(date(2026, 10, 26), "past"), (date(2026, 10, 27), "current"),
                              (date(2026, 10, 28), "current"), (date(2026, 10, 29), "future"),
                              (date(2026, 9, 30), "past"), (date(2026, 11, 26), "future")]:
            with self.subTest(doc=doc):
                self.assertEqual(self.kind(doc, 27, today), expected)

    def test_payday_1_is_the_calendar_month(self):
        today = date(2026, 10, 28)
        self.assertEqual(self.kind(date(2026, 9, 30), 1, today), "past")
        self.assertEqual(self.kind(date(2026, 10, 1), 1, today), "current")
        self.assertEqual(self.kind(date(2026, 10, 28), 1, today), "current")
        first = date(2026, 11, 1)   # hari pertama periode: kemarin sudah periode lalu
        self.assertEqual(self.kind(date(2026, 10, 31), 1, first), "past")
        self.assertEqual(self.kind(first, 1, first), "current")

    def test_without_a_date(self):
        self.assertIsNone(self.kind(None, 27, date(2026, 10, 28)))

    def test_year_boundary(self):
        jan = date(2027, 1, 3)   # payday 27 → periode 27 Des 2026–26 Jan 2027
        self.assertEqual(self.kind(date(2026, 12, 27), 27, jan), "current")
        self.assertEqual(self.kind(date(2026, 12, 26), 27, jan), "past")
        self.assertEqual(self.kind(date(2027, 1, 4), 27, jan), "future")
        self.assertEqual(self.kind(date(2026, 12, 31), 1, date(2027, 1, 1)), "past")

    def test_capped_payday_in_a_short_month(self):
        today = date(2026, 3, 1)   # payday 31 → periode dimulai 28 Feb (Februari tanpa tanggal 31)
        self.assertEqual(self.kind(date(2026, 2, 28), 31, today), "current")
        self.assertEqual(self.kind(date(2026, 2, 27), 31, today), "past")


if __name__ == "__main__":
    unittest.main()
