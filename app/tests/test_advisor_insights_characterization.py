"""Characterization (golden) tests for compute_insight_cards.

These lock the current, pre-decomposition behavior of the card-computation
logic that used to live inline in build_advisor_insights (app/services/
advisor/core.py). Task 6 split build_advisor_insights into a thin async
loader (DB I/O) + this pure, synchronous compute_insight_cards(envelopes,
stats, period_info, goals_by_env, balances_by_env). Because it's pure, we can
drive it directly with synthetic fixtures — no DB, no event loop.

Tasks 7+ will move this logic into app/services/advisor/rules/*. These tests
must stay green (behavior-preserving) across that move; do not "fix" any
card logic here even if it looks odd — see docs/ai-advisor-review for the
list of known issues, tracked separately in Plan B2.

Run from repo root:  python -m unittest app.tests.test_advisor_insights_characterization
"""
import unittest
from datetime import date
from decimal import Decimal

from app.services.advisor.core import compute_insight_cards
from app.tests.advisor_fixtures import (
    build_stats,
    make_envelope,
    make_goal,
    make_period_info,
    make_period_row,
)


class NormalSafeScenarioTests(unittest.TestCase):
    """Spend well within pace, no goals, no reserve pressure -> no cards."""

    def test_no_danger_cards_when_spend_is_on_pace(self):
        envelope = make_envelope(id="env-m", name="Makan", emoji="🍔", purpose="expense")
        stats = build_stats((
            "env-m",
            [make_period_row(allocated=Decimal("1000000"), spent=Decimal("300000"))],
        ))
        period_info = make_period_info(days_used=10, days_total=30, days_remaining=20)

        result = compute_insight_cards([envelope], stats, period_info, {}, {})

        self.assertEqual(result["cards"], [])
        self.assertEqual(result["dashboard_cards"], [])
        self.assertIn("period_start", result)
        self.assertIn("period_end", result)


class EnvDepletionScenarioTests(unittest.TestCase):
    """One envelope burning far faster than pace triggers env_depletion;
    a healthy second envelope keeps the aggregate below the global
    overspend threshold, isolating the per-envelope signal."""

    def test_fast_burning_envelope_triggers_depletion_only(self):
        fast = make_envelope(id="env-a", name="Hiburan", emoji="🎮", purpose="expense")
        healthy = make_envelope(id="env-b", name="Belanja", emoji="🛒", purpose="expense")
        stats = build_stats(
            ("env-a", [make_period_row(allocated=Decimal("500000"), spent=Decimal("400000"))]),
            ("env-b", [make_period_row(allocated=Decimal("5000000"), spent=Decimal("100000"))]),
        )
        period_info = make_period_info(days_used=10, days_total=30, days_remaining=20)

        result = compute_insight_cards([fast, healthy], stats, period_info, {}, {})

        self.assertEqual(len(result["cards"]), 1)
        card = result["cards"][0]
        self.assertEqual(card["type"], "env_depletion")
        self.assertEqual(card["severity"], "danger")  # shortage 700k > 20% of 500k available
        self.assertIn("Hiburan", card["title"])
        self.assertIn("80%", card["title"])
        self.assertIn("Proyeksi habis", card["body"])
        self.assertEqual(result["dashboard_cards"], result["cards"][:3])


class BudgetOverspendScenarioTests(unittest.TestCase):
    """Aggregate expense spend outpaces the period -> budget_overspend fires.
    This also exercises the env_depletion "warning" (not "danger") branch,
    since shortage == exactly 20% of available here."""

    def test_overspend_and_boundary_warning_depletion(self):
        envelope = make_envelope(id="env-d", name="Rumah Tangga", emoji="🏠", purpose="expense")
        stats = build_stats((
            "env-d",
            [make_period_row(allocated=Decimal("2000000"), spent=Decimal("1200000"))],
        ))
        period_info = make_period_info(days_used=15, days_total=30, days_remaining=15)

        result = compute_insight_cards([envelope], stats, period_info, {}, {})

        self.assertEqual(len(result["cards"]), 2)
        # Sorted by severity: danger before warning.
        overspend, depletion = result["cards"]
        self.assertEqual(overspend["type"], "budget_overspend")
        self.assertEqual(overspend["severity"], "danger")
        self.assertIn("jebol", overspend["title"])
        self.assertIn("Proyeksi overspend", overspend["body"])

        self.assertEqual(depletion["type"], "env_depletion")
        self.assertEqual(depletion["severity"], "warning")  # boundary: shortage == 20% exactly
        self.assertIn("Rumah Tangga", depletion["title"])


class GoalsScenarioTests(unittest.TestCase):
    """A saving envelope + a sinking_fund envelope, both with goals, produce
    one consolidated goal_progress card covering both."""

    def test_saving_and_sinking_fund_consolidate_into_one_card(self):
        saving_env = make_envelope(id="env-s", name="Tabungan", emoji="💰", purpose="saving")
        sinking_env = make_envelope(id="env-k", name="Servis Mobil", emoji="🚗", purpose="sinking_fund")

        stats = build_stats(
            (
                "env-s",
                [
                    make_period_row(allocated=Decimal("500000"), spent=Decimal("0")),  # history
                    make_period_row(allocated=Decimal("500000"), spent=Decimal("0")),  # current
                ],
            ),
            (
                "env-k",
                [make_period_row(allocated=Decimal("200000"), spent=Decimal("0"))],
            ),
        )
        period_info = make_period_info(days_used=10, days_total=30, days_remaining=20)

        goals_by_env = {
            "env-s": make_goal(name="Dana Darurat", target_amount=Decimal("6000000"), target_date=None),
            "env-k": make_goal(
                name="Servis Besar",
                target_amount=Decimal("3000000"),
                # Anchored to "today" at fixture-build time so months_remaining
                # resolves to exactly 12 regardless of which day the suite runs
                # (formula only diffs year*12+month, ignoring day-of-month).
                target_date=date.today().replace(year=date.today().year + 1),
            ),
        }
        balances_by_env = {
            "env-s": Decimal("1000000"),
            "env-k": Decimal("600000"),
        }

        result = compute_insight_cards(
            [saving_env, sinking_env], stats, period_info, goals_by_env, balances_by_env
        )

        self.assertEqual(len(result["cards"]), 1)
        card = result["cards"][0]
        self.assertEqual(card["type"], "goal_progress")
        self.assertEqual(card["severity"], "info")  # sinking fund is on-track, not under-funded
        self.assertIn("Target menabung", card["title"])
        self.assertIn("Dana Darurat", card["body"])
        self.assertIn("16%", card["body"])  # 1,000,000 / 6,000,000
        self.assertIn("estimasi 10 bulan", card["body"])  # (6,000,000-1,000,000)/500,000
        self.assertIn("Servis Besar", card["body"])
        self.assertIn("on track", card["body"])
        self.assertIn("1 tahun", card["body"])  # _fmt_months(12) == "1 tahun"


if __name__ == "__main__":
    unittest.main()
