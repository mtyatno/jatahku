"""Unit tests for advisor reserve/projection helpers (Plan B2 §6a, §6d)."""
import unittest
from decimal import Decimal

from app.services.advisor.context import _monthly_reserve
from app.services.advisor.sinking import _frequency_monthly_reserve
from app.services.advisor.rules._base import AdvisorContext
from app.services.advisor.rules.subscription import evaluate_subscription
from app.services.advisor.rules.overspend import evaluate_overspend
from app.tests.advisor_fixtures import make_envelope, make_period_row, make_period_info


_D = Decimal


def _ctx(envelopes, stats, period_info=None, goals=None, balances=None):
    return AdvisorContext(
        envelopes=envelopes,
        stats=stats,
        period_info=period_info or make_period_info(),
        goals_by_env=goals or {},
        balances_by_env=balances or {},
    )


class WeeklyReserveTests(unittest.TestCase):
    def test_context_weekly_reserve_uses_4_33_weeks(self):
        # 100000/week * 52 / 12 = 433333.33...
        got = _monthly_reserve(Decimal("100000"), "weekly")
        self.assertEqual(got, Decimal("100000") * Decimal("52") / 12)

    def test_context_monthly_and_yearly_unchanged(self):
        self.assertEqual(_monthly_reserve(Decimal("120000"), "monthly"), Decimal("120000"))
        self.assertEqual(_monthly_reserve(Decimal("1200000"), "yearly"), Decimal("100000"))

    def test_sinking_weekly_reserve_uses_4_33_weeks(self):
        got = _frequency_monthly_reserve(Decimal("100000"), "weekly")
        self.assertEqual(got, Decimal("100000") * Decimal("52") / 12)

    def test_sinking_other_frequencies_unchanged(self):
        self.assertEqual(_frequency_monthly_reserve(Decimal("300000"), "quarterly"), Decimal("100000"))
        self.assertEqual(_frequency_monthly_reserve(Decimal("1200000"), "yearly"), Decimal("100000"))
        self.assertEqual(_frequency_monthly_reserve(Decimal("600000"), "semiannual"), Decimal("100000"))


class SubscriptionExpenseOnlyTests(unittest.TestCase):
    def _pressured_row(self):
        # available 500k, spent 0, reserved 500k -> free 0 < 25% of reserved
        return make_period_row(allocated=_D("500000"), spent=_D("0"), reserved=_D("500000"))

    def test_expense_envelope_triggers(self):
        env = make_envelope(id="e1", name="Langganan", purpose="expense")
        ctx = _ctx([env], {"e1": [self._pressured_row()]})
        cards = evaluate_subscription(ctx)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "subscription_pressure")

    def test_saving_envelope_does_not_trigger(self):
        env = make_envelope(id="e2", name="Dana Pensiun", purpose="saving")
        ctx = _ctx([env], {"e2": [self._pressured_row()]})
        self.assertEqual(evaluate_subscription(ctx), [])


class OverspendExpenseOnlyReserveTests(unittest.TestCase):
    def test_evidence_reserve_excludes_saving_envelope_reserve(self):
        # expense env overspends; a saving env carries a big reserve that must
        # NOT appear in the overspend evidence "Reserve rutin" line.
        exp = make_envelope(id="ex", name="Belanja", purpose="expense")
        sav = make_envelope(id="sv", name="Tabungan", purpose="saving")
        stats = {
            "ex": [make_period_row(allocated=_D("1000000"), spent=_D("900000"),
                                   transaction_count=8, reserved=_D("50000"))],
            "sv": [make_period_row(allocated=_D("2000000"), spent=_D("0"),
                                   reserved=_D("999000"))],
        }
        ctx = _ctx([exp, sav], stats, period_info=make_period_info(days_used=15, days_total=30, days_remaining=15))
        cards = evaluate_overspend(ctx)
        self.assertEqual(len(cards), 1)
        evidence = " ".join(cards[0]["evidence"])
        self.assertIn("50.000", evidence)       # expense-only reserved
        self.assertNotIn("999.000", evidence)    # saving reserve excluded
        self.assertNotIn("1.049.000", evidence)  # not the all-envelope sum


if __name__ == "__main__":
    unittest.main()
