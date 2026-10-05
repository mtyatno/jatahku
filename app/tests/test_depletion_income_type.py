"""env_depletion per income type: daily and weekly earners only need an envelope
to last until the next income, not until the period ends.

Numbers mirror the MSBT Project daily-income account on 5 Oct (period to 31 Oct):
Makan di Jalan has Rp45.400, Rp30.000 spent over 5 days (Rp6.000/day)."""
import unittest
from decimal import Decimal as D

from app.services.advisor.rules import compute_insight_cards
from app.tests.advisor_fixtures import build_stats, make_envelope, make_period_info, make_period_row


def depletion_cards(available, spent, income_type=None, days_remaining=26):
    env = make_envelope(id="env-makan", name="Makan di Jalan", emoji="🍜", purpose="expense")
    stats = build_stats(("env-makan", [make_period_row(allocated=D(available), spent=D(spent))]))
    period = make_period_info(days_used=5, days_total=31, days_remaining=days_remaining)
    result = compute_insight_cards([env], stats, period, {}, {}, income_type=income_type)
    return [c for c in result["cards"] if c["type"] == "env_depletion"]


class MonthlyEarnerTests(unittest.TestCase):
    def test_period_horizon_floored_to_rp100(self):
        # 15.400 ÷ 26 days = 592 -> Rp500, never a non-Rp100 amount
        (card,) = depletion_cards(45400, 30000)
        self.assertEqual(card["detail"]["safe_daily"], 500)
        self.assertIn("maksimal Rp500/hari", card["title"])
        self.assertIn("sebelum periode selesai", card["body"])
        self.assertIsNone(card["detail"]["horizon_days"])

    def test_unknown_income_type_is_monthly(self):
        self.assertEqual(len(depletion_cards(45400, 30000, income_type="irregular")), 1)


class DailyEarnerTests(unittest.TestCase):
    def test_no_card_when_envelope_lasts_until_tomorrow(self):
        # Rp15.400 left covers today's usual Rp6.000
        self.assertEqual(depletion_cards(45400, 30000, income_type="daily"), [])

    def test_card_when_today_would_empty_it(self):
        (card,) = depletion_cards(35000, 30000, income_type="daily")
        self.assertEqual(card["detail"]["safe_daily"], 5000)
        self.assertEqual(card["detail"]["horizon_days"], 1)
        self.assertIn("maksimal Rp5.000 hari ini", card["title"])
        self.assertIn("besok", card["body"])
        self.assertNotIn("periode", card["body"])

    def test_empty_envelope_still_flagged(self):
        (card,) = depletion_cards(30000, 32000, income_type="daily")
        self.assertIn("dana sudah habis", card["title"])
        self.assertEqual(card["detail"]["days_early"], 0)


class WeeklyEarnerTests(unittest.TestCase):
    def test_seven_day_horizon(self):
        # Rp6.000/day for 7 days needs Rp42.000; 15.400 ÷ 7 = 2.200
        (card,) = depletion_cards(45400, 30000, income_type="weekly")
        self.assertEqual(card["detail"]["safe_daily"], 2200)
        self.assertEqual(card["detail"]["horizon_days"], 7)
        self.assertIn("7 hari lagi", card["body"])

    def test_horizon_capped_by_period_end(self):
        (card,) = depletion_cards(45400, 30000, income_type="weekly", days_remaining=3)
        self.assertEqual(card["detail"]["horizon_days"], 3)
        self.assertEqual(card["detail"]["safe_daily"], 5100)

    def test_no_card_when_week_is_covered(self):
        self.assertEqual(depletion_cards(80000, 30000, income_type="weekly"), [])


if __name__ == "__main__":
    unittest.main()
