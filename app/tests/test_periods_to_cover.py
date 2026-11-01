"""Tests for periods_to_cover (app/core/period.py): berapa periode tertutup yang harus dihitung ulang supaya recompute
mencakup seluruh riwayat household, dari periode SEBELUM periode yang memuat aktivitas pertama sampai periode tertutup
terbaru.

Run from repo root:  python -m unittest app.tests.test_periods_to_cover -v
"""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app.core import period
from app.core.period import get_budget_period, get_closed_periods, get_period_for_month, periods_to_cover
from app.tests.fakes import fixed_date

PAYDAYS = (1, 15, 25, 29, 30, 31)
TODAY = date(2026, 11, 10)


class PeriodsToCoverTests(unittest.TestCase):
    def test_first_day_in_the_open_period_is_one(self):
        # Hanya periode tertutup terbaru: periode SEBELUM periode yang memuat hari pertama.
        for payday in PAYDAYS:
            with self.subTest(payday=payday):
                open_start, _ = get_budget_period(payday, TODAY)
                self.assertEqual(periods_to_cover(payday, open_start, TODAY), 1)
                self.assertEqual(periods_to_cover(payday, TODAY, TODAY), 1)

    def test_first_day_in_the_newest_closed_period_is_two(self):
        for payday in PAYDAYS:
            with self.subTest(payday=payday):
                ((start, end),) = get_closed_periods(payday, TODAY, 1)
                self.assertEqual(periods_to_cover(payday, start, TODAY), 2)
                self.assertEqual(periods_to_cover(payday, end, TODAY), 2)

    def test_oldest_period_covered_is_the_one_before_the_first_day(self):
        # Untuk setiap tanggal gajian dan setiap hari pertama dalam dua tahun terakhir: periode tertua yang dihitung
        # ulang berakhir tepat sehari sebelum periode yang memuat hari pertama dimulai, dan semuanya tertutup.
        for payday in PAYDAYS:
            first = date(2024, 11, 1)
            while first <= TODAY:
                with self.subTest(payday=payday, first=first):
                    closed = get_closed_periods(payday, TODAY, periods_to_cover(payday, first, TODAY))
                    first_start, _ = get_budget_period(payday, first)
                    self.assertEqual(closed[0][1] + timedelta(days=1), first_start)
                    self.assertLess(closed[-1][1], TODAY)
                first += timedelta(days=1)

    def test_across_a_year_boundary(self):
        # Hari pertama 15 Nov 2025, hari ini 10 Jan 2026, tanggal 1: Okt 2025 (periode sebelumnya), Nov, Des.
        self.assertEqual(periods_to_cover(1, date(2025, 11, 15), date(2026, 1, 10)), 3)
        self.assertEqual(
            get_closed_periods(1, date(2026, 1, 10), 3)[0], (date(2025, 10, 1), date(2025, 10, 31))
        )
        # Tanggal 25: hari pertama 30 Des 2025 (periode 25 Des–24 Jan), hari ini 10 Mar 2026 (periode 25 Feb–24 Mar):
        # 25 Nov–24 Des (sebelumnya), 25 Des–24 Jan, 25 Jan–24 Feb.
        self.assertEqual(periods_to_cover(25, date(2025, 12, 30), date(2026, 3, 10)), 3)

    def test_around_february(self):
        # Tanggal 31 dijepit ke 28 Feb: periode 28 Feb–30 Mar 2026 memuat hari pertama, hari ini dalam 31 Mar–29 Apr.
        self.assertEqual(periods_to_cover(31, date(2026, 2, 28), date(2026, 4, 15)), 2)
        self.assertEqual(periods_to_cover(31, date(2026, 3, 30), date(2026, 4, 15)), 2)
        # Tanggal 30 di tahun kabisat: periode 29 Feb–29 Mar 2028, hari ini dalam 30 Mar–29 Apr.
        self.assertEqual(periods_to_cover(30, date(2028, 2, 29), date(2028, 3, 30)), 2)
        # Tanggal 29: hari pertama 28 Feb 2026 (periode 28 Feb–28 Mar), hari ini 29 Mar (periode baru) dan 28 Mar.
        self.assertEqual(periods_to_cover(29, date(2026, 2, 28), date(2026, 3, 29)), 2)
        self.assertEqual(periods_to_cover(29, date(2026, 2, 28), date(2026, 3, 28)), 1)

    def test_payday_moving_earlier_covers_the_old_window_holding_the_first_data(self):
        # Gajian lama 25, baru 1, data pertama 5 Mar 2026. Di bawah tanggal 25 kunci 2026-02 berjendela 25 Feb–24 Mar,
        # jadi snapshot lamanya memuat 5 Mar. Di bawah tanggal 1 data pertama ada di periode Maret; tanpa periode
        # sebelumnya (Februari) kunci 2026-02 lama itu tetap ada dan rollover-nya terhitung dua kali di Maret.
        first = date(2026, 3, 5)
        old_start, old_end = get_period_for_month(25, 2026, 2)
        self.assertTrue(old_start <= first <= old_end)
        covered = get_closed_periods(1, TODAY, periods_to_cover(1, first, TODAY))
        self.assertEqual(covered[0], (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(len(covered), 9)  # Feb–Okt 2026

    def test_first_day_after_today_is_zero(self):
        self.assertEqual(periods_to_cover(1, date(2026, 12, 3), TODAY), 0)
        self.assertEqual(periods_to_cover(1, date(2027, 5, 3), TODAY), 0)

    def test_today_defaults_to_date_today(self):
        with patch.object(period, "date", fixed_date(date(2026, 3, 15))):
            self.assertEqual(periods_to_cover(1, date(2026, 1, 20)), 3)  # Des 2025, Jan, Feb


if __name__ == "__main__":
    unittest.main()
