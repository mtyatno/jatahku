"""Unit tests for advisor confidence model (Plan B2 §6b)."""
import unittest
from decimal import Decimal

from app.services.advisor.confidence import assess_confidence


class ConfidenceTierTests(unittest.TestCase):
    def test_high_needs_four_periods_and_tight_spread(self):
        out = assess_confidence([Decimal("1000000")] * 4)
        self.assertEqual(out["level"], "high")
        self.assertTrue(out["reasons"])

    def test_wide_spread_is_not_high(self):
        # 4 periods but max/median spread >= 50%
        out = assess_confidence([Decimal("1000000"), Decimal("1000000"),
                                 Decimal("1000000"), Decimal("2000000")])
        self.assertEqual(out["level"], "medium")

    def test_two_periods_is_medium(self):
        out = assess_confidence([Decimal("500000"), Decimal("600000")])
        self.assertEqual(out["level"], "medium")

    def test_one_period_is_low(self):
        self.assertEqual(assess_confidence([Decimal("500000")])["level"], "low")

    def test_empty_or_zero_median_is_low(self):
        self.assertEqual(assess_confidence([])["level"], "low")
        self.assertEqual(assess_confidence([Decimal("0"), Decimal("0")])["level"], "low")


if __name__ == "__main__":
    unittest.main()
