"""Unit tests for advisor reserve/projection helpers (Plan B2 §6a, §6d)."""
import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.advisor.context import _monthly_reserve, load_advisor_context
from app.services.advisor.sinking import _frequency_monthly_reserve
from app.services.advisor.rules._base import AdvisorContext
from app.services.advisor.rules import compute_insight_cards
from app.services.advisor.rules.subscription import evaluate_subscription
from app.services.advisor.rules.overspend import evaluate_overspend
from app.services.advisor.projection import project_envelope
from app.services.advisor.rules.depletion import evaluate_depletion
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


class ContextShapeTests(unittest.TestCase):
    def test_no_household_returns_empty_txn_maps(self):
        # _get_household_id returns None -> early return must still carry the new keys.
        from types import SimpleNamespace
        user = SimpleNamespace(id="u1", payday_day=1)

        class _DB:
            async def execute(self, *a, **k):
                class _R:
                    def scalar_one_or_none(self_inner): return None
                return _R()

        ctx = asyncio.run(load_advisor_context(user, _DB()))
        self.assertEqual(ctx.get("current_txns_by_env", "MISSING"), {})
        self.assertEqual(ctx.get("recurring_by_env", "MISSING"), {})


class ComputeInsightCardsOptionalArgsTests(unittest.TestCase):
    def test_accepts_txn_maps_without_error(self):
        env = make_envelope(id="e1", name="Makan", purpose="expense")
        stats = {"e1": [make_period_row(allocated=_D("1000000"), spent=_D("100000"), transaction_count=2)]}
        # Passing the new optional maps must be accepted and not change a low-spend result.
        result = compute_insight_cards(
            [env], stats, make_period_info(days_used=10, days_total=30, days_remaining=20),
            {}, {}, txns_by_env={"e1": []}, recurring_by_env={"e1": []},
        )
        self.assertEqual(result["cards"], [])

    def test_context_defaults_are_empty_dicts(self):
        ctx = AdvisorContext(envelopes=[], stats={}, period_info=make_period_info(),
                             goals_by_env={}, balances_by_env={})
        self.assertEqual(ctx.txns_by_env, {})
        self.assertEqual(ctx.recurring_by_env, {})


def _txn(amount, desc="beli", d=None):
    from datetime import date
    return SimpleNamespace(amount=_D(str(amount)), description=desc, transaction_date=d or date(2026, 1, 5))


class ProjectEnvelopeTests(unittest.TestCase):
    def test_aggregate_only_matches_old_formula(self):
        # No txns -> variable == total; new == old == (spent/days_used)*days_total.
        out = project_envelope(_D("300000"), 3, _D("1000000"), 10, 30, 20)
        self.assertEqual(out["projected"], _D("300000") / 10 * 30)
        self.assertFalse(out["severity_capped"])  # aggregate-only never caps

    def test_recurring_excluded_from_rate(self):
        # 500k rent matches a 500k monthly recurring; only the 100k variable counts.
        txns = [_txn(500000), _txn(60000), _txn(40000)]
        out = project_envelope(_D("600000"), 3, _D("1000000"), 10, 30, 20,
                               txns=txns, recurring_amounts=[_D("500000")])
        # variable_total = 100k; rate = 10k/day; projected = 600k + 10k*20 = 800k
        self.assertEqual(out["projected"], _D("800000"))
        self.assertEqual(out["variable_count"], 2)

    def test_outlier_excluded_and_reported(self):
        # 400k outlier: > 2x median(of [400k,20k,20k,20k]=20k) AND > 30% of 500k available.
        txns = [_txn(400000, "beli tv"), _txn(20000), _txn(20000), _txn(20000)]
        out = project_envelope(_D("460000"), 4, _D("500000"), 10, 30, 20, txns=txns)
        self.assertEqual(out["variable_count"], 3)
        self.assertEqual(len(out["outliers"]), 1)
        self.assertEqual(out["outliers"][0].description, "beli tv")

    def test_thin_variable_sample_caps_severity(self):
        # < 5 variable txns with per-txn data -> severity_capped True.
        txns = [_txn(50000), _txn(50000)]
        out = project_envelope(_D("100000"), 2, _D("500000"), 10, 30, 20, txns=txns)
        self.assertTrue(out["severity_capped"])

    def test_enough_variable_sample_not_capped(self):
        txns = [_txn(50000) for _ in range(6)]
        out = project_envelope(_D("300000"), 6, _D("500000"), 10, 30, 20, txns=txns)
        self.assertFalse(out["severity_capped"])


class DepletionProjectionTests(unittest.TestCase):
    def test_front_loaded_rent_does_not_trigger_danger(self):
        # Rent 3M paid day 1 in a 3M-available envelope, matched to a recurring;
        # tiny variable spend after -> no depletion card.
        env = make_envelope(id="r1", name="Sewa", purpose="expense")
        stats = {"r1": [make_period_row(allocated=_D("3000000"), spent=_D("3050000"), transaction_count=3)]}
        txns = [_txn(3000000, "sewa"), _txn(30000), _txn(20000)]
        ctx = AdvisorContext(
            envelopes=[env], stats=stats,
            period_info=make_period_info(days_used=10, days_total=30, days_remaining=20),
            goals_by_env={}, balances_by_env={},
            txns_by_env={"r1": txns}, recurring_by_env={"r1": [{"amount": _D("3000000"), "frequency": "monthly", "norm": ""}]},
        )
        # available 3M, spent 3.05M already > available -> but projection variable
        # is only 50k; the rule still may flag because spent>available. Guard: the
        # card, if any, must NOT be danger (capped: 2 variable txns < 5).
        cards = evaluate_depletion(ctx)
        for card in cards:
            self.assertNotEqual(card["severity"], "danger")

    def test_genuine_even_burn_stays_danger(self):
        env = make_envelope(id="g1", name="Hiburan", purpose="expense")
        stats = {"g1": [make_period_row(allocated=_D("500000"), spent=_D("400000"), transaction_count=8)]}
        txns = [_txn(50000) for _ in range(8)]
        ctx = AdvisorContext(
            envelopes=[env], stats=stats,
            period_info=make_period_info(days_used=10, days_total=30, days_remaining=20),
            goals_by_env={}, balances_by_env={},
            txns_by_env={"g1": txns}, recurring_by_env={},
        )
        cards = evaluate_depletion(ctx)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["severity"], "danger")


if __name__ == "__main__":
    unittest.main()
