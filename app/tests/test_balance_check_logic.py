"""Logika murni cocokkan saldo.

Run: python -m unittest app.tests.test_balance_check_logic -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from decimal import Decimal as D

from app.services.balance_check import (
    Candidate, classify_gap, suggest_distribution, validate_lines,
)


def C(eid, weight="0", budget="0"):
    return Candidate(eid, D(weight), D(budget))


class ClassifyGapTests(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(classify_gap(D("-1")), "unrecorded_expense")
        self.assertEqual(classify_gap(D("0")), "match")
        self.assertEqual(classify_gap(D("5")), "surplus")


class SuggestDistributionTests(unittest.TestCase):
    def test_proportional_exact(self):
        out = suggest_distribution(D("340000"), [C("a", "600000"), C("b", "300000"), C("c", "100000")])
        self.assertEqual(out, [D("204000"), D("102000"), D("34000")])

    def test_rounding_remainder_goes_to_heaviest_then_earliest(self):
        self.assertEqual(
            suggest_distribution(D("100000"), [C("a", "1"), C("b", "1"), C("c", "1")]),
            [D("34000"), D("33000"), D("33000")],
        )
        self.assertEqual(
            suggest_distribution(D("100500"), [C("a", "1"), C("b", "3")]),
            [D("25000"), D("75500")],
        )

    def test_falls_back_to_budget_when_no_recent_spending(self):
        out = suggest_distribution(D("40000"), [C("a", "0", "300000"), C("b", "0", "100000")])
        self.assertEqual(out, [D("30000"), D("10000")])

    def test_total_below_unit_goes_to_heaviest(self):
        self.assertEqual(suggest_distribution(D("500"), [C("a", "100"), C("b", "900")]), [D("0"), D("500")])

    def test_no_candidates(self):
        self.assertEqual(suggest_distribution(D("100000"), []), [])

    def test_all_zero_weights_and_budgets(self):
        self.assertEqual(suggest_distribution(D("100000"), [C("a"), C("b")]), [D("0"), D("0")])

    def test_non_positive_total(self):
        self.assertEqual(suggest_distribution(D("0"), [C("a", "5")]), [D("0")])
        self.assertEqual(suggest_distribution(D("-5"), [C("a", "5")]), [D("0")])

    def test_negative_weight_ignored(self):
        self.assertEqual(suggest_distribution(D("20000"), [C("a", "-50000"), C("b", "100000")]), [D("0"), D("20000")])

    def test_sum_always_equals_total_and_non_negative(self):
        weight_sets = [["1"], ["5", "5"], ["3", "7", "11"], ["100000", "1", "0"]]
        for total in ["1", "999", "1000", "12345", "340000", "1999999"]:
            for ws in weight_sets:
                out = suggest_distribution(D(total), [C(str(i), w) for i, w in enumerate(ws)])
                self.assertEqual(sum(out), D(total), (total, ws))
                self.assertTrue(all(x >= 0 for x in out), (total, ws))


SPENDABLE = {"m", "t"}
ALL = {"m", "t", "tab"}


class ValidateLinesTests(unittest.TestCase):
    def v(self, gap, lines):
        return validate_lines(D(gap), [(e, D(a)) for e, a in lines], SPENDABLE, ALL)

    def test_match(self):
        self.assertIsNone(self.v("0", []))
        self.assertIn("cocok", self.v("0", [("m", "1000")]))

    def test_unrecorded_valid(self):
        self.assertIsNone(self.v("-340000", [("m", "227000"), ("t", "113000")]))

    def test_unrecorded_wrong_total(self):
        self.assertEqual(self.v("-340000", [("m", "200000")]), "Total pembagian harus Rp340.000")

    def test_unrecorded_saving_envelope_rejected(self):
        self.assertIn("tidak valid", self.v("-340000", [("tab", "340000")]))

    def test_unrecorded_zero_amount_rejected(self):
        self.assertIn("lebih dari 0", self.v("-340000", [("m", "340000"), ("t", "0")]))

    def test_duplicate_envelope_rejected(self):
        self.assertIn("sekali", self.v("-340000", [("m", "170000"), ("m", "170000")]))

    def test_empty_lines_rejected(self):
        self.assertIn("belum diisi", self.v("-340000", []))

    def test_surplus_valid(self):
        self.assertIsNone(self.v("200000", [("tab", "200000")]))

    def test_surplus_multiple_lines_rejected(self):
        self.assertIn("satu amplop", self.v("200000", [("tab", "100000"), ("m", "100000")]))

    def test_surplus_unknown_envelope_rejected(self):
        self.assertIn("tidak valid", self.v("200000", [("x", "200000")]))

    def test_surplus_wrong_amount(self):
        self.assertEqual(self.v("200000", [("tab", "150000")]), "Nominal harus Rp200.000")

    def test_accepts_uuid_ids(self):
        eid = uuid.uuid4()
        self.assertIsNone(validate_lines(D("-1000"), [(eid, D("1000"))], {str(eid)}, {str(eid)}))


if __name__ == "__main__":
    unittest.main()
