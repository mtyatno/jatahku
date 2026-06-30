"""Tests for deterministic advisor helpers (app/services/advisor.py).

Run from repo root:  python -m unittest app.tests.test_advisor
"""
import unittest
from datetime import date
from decimal import Decimal

from app.services.advisor import (
    allocate_income_to_targets,
    detect_interval,
    normalize_description,
    _fmt_rp,
)


class TestFmtRp(unittest.TestCase):
    def test_indonesian_dot_grouping(self):
        self.assertEqual(_fmt_rp(Decimal("1520000")), "1.520.000")
        self.assertEqual(_fmt_rp(Decimal("970000")), "970.000")
        self.assertEqual(_fmt_rp(0), "0")
        self.assertEqual(_fmt_rp(Decimal("999.6")), "1.000")


class TestNormalizeDescription(unittest.TestCase):
    def test_removes_amount_tokens_and_fillers(self):
        self.assertEqual(
            normalize_description("Aku bayar Rp186.000 Netflix Premium dong"),
            "netflix premium",
        )
        self.assertEqual(
            normalize_description("35k kopi kenangan tadi"),
            "kopi kenangan",
        )

    def test_keeps_meaningful_subscription_terms(self):
        self.assertEqual(
            normalize_description("perpanjang domain jatahku.com 220rb tahunan"),
            "perpanjang domain jatahku com tahunan",
        )


class TestDetectInterval(unittest.TestCase):
    def test_detects_monthly_interval(self):
        result = detect_interval([
            date(2026, 1, 15),
            date(2026, 2, 14),
            date(2026, 3, 16),
            date(2026, 4, 15),
        ])
        self.assertEqual(result["frequency"], "monthly")
        self.assertEqual(result["confidence"], "high")

    def test_detects_weekly_interval(self):
        result = detect_interval([
            date(2026, 1, 1),
            date(2026, 1, 8),
            date(2026, 1, 15),
            date(2026, 1, 22),
        ])
        self.assertEqual(result["frequency"], "weekly")
        self.assertEqual(result["confidence"], "high")

    def test_sparse_explicit_yearly_is_low_confidence(self):
        result = detect_interval(
            [date(2025, 6, 10)],
            normalized_text="hosting tahunan renewal",
        )
        self.assertEqual(result["frequency"], "yearly")
        self.assertEqual(result["confidence"], "low")

    def test_inconsistent_dates_need_review(self):
        result = detect_interval([
            date(2026, 1, 1),
            date(2026, 1, 9),
            date(2026, 2, 20),
            date(2026, 4, 1),
        ])
        self.assertEqual(result["frequency"], "unknown")
        self.assertEqual(result["confidence"], "low")


class TestAllocateIncomeToTargets(unittest.TestCase):
    def test_obligations_are_filled_before_discretionary_targets(self):
        envelopes = [
            {
                "id": "tagihan",
                "name": "Tagihan",
                "minimum": Decimal("1000000"),
                "target": Decimal("1200000"),
                "priority": 10,
            },
            {
                "id": "hiburan",
                "name": "Hiburan",
                "minimum": Decimal("0"),
                "target": Decimal("800000"),
                "priority": 30,
            },
        ]

        result = allocate_income_to_targets(Decimal("1200000"), envelopes)
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(by_id["tagihan"]["recommended_amount"], Decimal("1000000"))
        self.assertEqual(by_id["hiburan"]["recommended_amount"], Decimal("200000"))
        self.assertEqual(result["unallocated"], Decimal("0"))

    def test_insufficient_income_returns_warning(self):
        envelopes = [
            {
                "id": "tagihan",
                "name": "Tagihan",
                "minimum": Decimal("1000000"),
                "target": Decimal("1000000"),
                "priority": 10,
            }
        ]

        result = allocate_income_to_targets(Decimal("600000"), envelopes)

        self.assertEqual(result["items"][0]["recommended_amount"], Decimal("600000"))
        self.assertGreater(len(result["warnings"]), 0)

    def test_leftover_goes_to_tabungan_when_present(self):
        envelopes = [
            {
                "id": "makan",
                "name": "Makan",
                "minimum": Decimal("0"),
                "target": Decimal("1000000"),
                "priority": 20,
            },
            {
                "id": "tabungan",
                "name": "Tabungan",
                "minimum": Decimal("0"),
                "target": Decimal("0"),
                "priority": 90,
            },
        ]

        result = allocate_income_to_targets(Decimal("1500000"), envelopes)
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(by_id["makan"]["recommended_amount"], Decimal("1000000"))
        self.assertEqual(by_id["tabungan"]["recommended_amount"], Decimal("500000"))
        self.assertEqual(result["unallocated"], Decimal("0"))

    def test_leftover_goes_to_saving_purpose_even_if_not_named_tabungan(self):
        envelopes = [
            {"id": "makan", "name": "Makan", "minimum": Decimal("0"), "target": Decimal("1000000"), "priority": 20, "purpose": "expense"},
            {"id": "pensiun", "name": "Dana Pensiun", "minimum": Decimal("0"), "target": Decimal("0"), "priority": 90, "purpose": "saving"},
        ]
        result = allocate_income_to_targets(Decimal("1500000"), envelopes)
        by_id = {item["id"]: item for item in result["items"]}
        self.assertEqual(by_id["makan"]["recommended_amount"], Decimal("1000000"))
        self.assertEqual(by_id["pensiun"]["recommended_amount"], Decimal("500000"))
        self.assertEqual(result["unallocated"], Decimal("0"))

    def test_locked_envelopes_are_not_used_as_sources(self):
        envelopes = [
            {
                "id": "gadget",
                "name": "Gadget",
                "minimum": Decimal("0"),
                "target": Decimal("500000"),
                "priority": 40,
                "is_locked": True,
            },
            {
                "id": "tabungan",
                "name": "Tabungan",
                "minimum": Decimal("0"),
                "target": Decimal("0"),
                "priority": 90,
            },
        ]

        result = allocate_income_to_targets(Decimal("800000"), envelopes)
        by_id = {item["id"]: item for item in result["items"]}

        self.assertEqual(by_id["gadget"]["recommended_amount"], Decimal("0"))
        self.assertEqual(by_id["tabungan"]["recommended_amount"], Decimal("800000"))


if __name__ == "__main__":
    unittest.main()
