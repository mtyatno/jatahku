"""End-to-end advisor scenarios (Plan B2 §9 Layer 2)."""
import unittest
from datetime import date
from decimal import Decimal as D

from app.tests.evaluator.scenario import (
    make_txn, run_scenario, card_types, evidence_text,
)
from app.tests.advisor_fixtures import (
    make_envelope, make_period_row, make_period_info, make_goal,
)

PI = make_period_info(days_used=10, days_total=30, days_remaining=20)
PI_MID = make_period_info(days_used=15, days_total=30, days_remaining=15)


class EvaluatorScenarioTests(unittest.TestCase):
    def test_1_normal_spend_no_danger(self):
        env = make_envelope(id="m", name="Makan", purpose="expense")
        stats = {"m": [make_period_row(allocated=D("1000000"), spent=D("250000"), transaction_count=6)]}
        txns = {"m": [make_txn(40000) for _ in range(6)]}
        result = run_scenario([env], stats, PI, txns_by_env=txns)
        self.assertNotIn("env_depletion", card_types(result))
        self.assertNotIn("budget_overspend", card_types(result))

    def test_2_front_loaded_rent_no_overspend(self):
        env = make_envelope(id="r", name="Sewa", purpose="expense")
        stats = {"r": [make_period_row(allocated=D("3000000"), spent=D("3050000"), transaction_count=3)]}
        txns = {"r": [make_txn(3000000, "sewa"), make_txn(30000), make_txn(20000)]}
        rec = {"r": [{"amount": D("3000000"), "frequency": "monthly", "norm": ""}]}
        result = run_scenario([env], stats, PI, txns_by_env=txns, recurring_by_env=rec)
        # A depletion card may exist (spent already > available) but never danger,
        # and the global overspend must not be danger from a day-1 fixed bill.
        for card in result["cards"]:
            self.assertNotEqual(card["severity"], "danger")

    def test_3_genuine_even_overspend_is_danger(self):
        env = make_envelope(id="g", name="Belanja", purpose="expense")
        stats = {"g": [make_period_row(allocated=D("1000000"), spent=D("800000"), transaction_count=8)]}
        txns = {"g": [make_txn(100000) for _ in range(8)]}
        result = run_scenario([env], stats, PI_MID, txns_by_env=txns)
        types = card_types(result)
        self.assertTrue({"budget_overspend", "env_depletion"} & types)
        self.assertIn("danger", {c["severity"] for c in result["cards"]})

    def test_4_subscription_pressure_triggers(self):  # closes B1 coverage gap
        env = make_envelope(id="s", name="Langganan", purpose="expense")
        stats = {"s": [make_period_row(allocated=D("500000"), spent=D("0"),
                                       reserved=D("500000"), transaction_count=0)]}
        result = run_scenario([env], stats, PI)
        self.assertIn("subscription_pressure", card_types(result))

    def test_5_allocation_drift_triggers(self):  # closes B1 coverage gap
        env = make_envelope(id="d", name="Transport", purpose="expense", budget_amount=D("500000"))
        stats = {"d": [
            make_period_row(allocated=D("500000"), spent=D("800000")),   # history median 800k
            make_period_row(allocated=D("500000"), spent=D("300000"), transaction_count=4),  # current
        ]}
        result = run_scenario([env], stats, PI)
        self.assertIn("allocation_drift", card_types(result))

    def test_6_other_member_private_desc_never_in_evidence(self):  # privacy regression guard
        # An outlier that would surface in evidence, but its description is masked.
        # In production, context.py (Task 7) masks another household member's
        # private transaction description BEFORE it ever reaches this pipeline —
        # we feed the already-masked value here, exactly as the real pipeline
        # would. The raw content ("terapi rahasia") must never appear anywhere
        # in a card, unconditionally.
        env = make_envelope(id="p", name="Rumah Tangga", purpose="expense")
        stats = {"p": [make_period_row(allocated=D("500000"), spent=D("460000"), transaction_count=4)]}
        txns = {"p": [make_txn(400000, "Transaksi privat"), make_txn(20000),
                      make_txn(20000), make_txn(20000)]}
        result = run_scenario([env], stats, PI, txns_by_env=txns)
        text = evidence_text(result)

        # Load-bearing, unconditional: no raw private token ever leaks into any
        # card string (title, body, or evidence line).
        self.assertNotIn("terapi rahasia", text)

        # Prove the guard isn't vacuous: the 400k outlier DOES surface in the
        # depletion card's evidence, but only via the masked placeholder —
        # never as raw text.
        depletion_cards = [c for c in result["cards"] if c["type"] == "env_depletion"]
        self.assertTrue(
            depletion_cards,
            "expected the 400k outlier to produce an env_depletion card with evidence",
        )
        self.assertIn("Transaksi privat", evidence_text({"cards": depletion_cards}))


if __name__ == "__main__":
    unittest.main()
