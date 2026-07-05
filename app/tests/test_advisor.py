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
    build_allocation_distribution,
    _fmt_rp,
    _period_index,
    _sum_by_period,
    _count_by_period,
)


class TestPeriodBucketing(unittest.TestCase):
    PERIODS = [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 31)),
    ]

    def test_period_index_inclusive_boundaries(self):
        self.assertEqual(_period_index(date(2026, 1, 1), self.PERIODS), 0)
        self.assertEqual(_period_index(date(2026, 1, 31), self.PERIODS), 0)
        self.assertEqual(_period_index(date(2026, 2, 15), self.PERIODS), 1)
        self.assertEqual(_period_index(date(2026, 3, 31), self.PERIODS), 2)
        self.assertIsNone(_period_index(date(2025, 12, 31), self.PERIODS))
        self.assertIsNone(_period_index(date(2026, 4, 1), self.PERIODS))

    def test_sum_by_period_buckets_amounts(self):
        rows = [
            (date(2026, 1, 5), Decimal("10000")),
            (date(2026, 1, 20), Decimal("5000")),
            (date(2026, 2, 2), Decimal("7000")),
            (date(2025, 12, 9), Decimal("99999")),  # out of range — ignored
        ]
        self.assertEqual(
            _sum_by_period(rows, self.PERIODS),
            [Decimal("15000"), Decimal("7000"), Decimal("0")],
        )

    def test_count_by_period(self):
        dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 3, 1), date(2026, 4, 9)]
        self.assertEqual(_count_by_period(dates, self.PERIODS), [2, 0, 1])


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


class TestAllocationDistribution(unittest.TestCase):
    def test_groups_and_percentages(self):
        rows = [
            ("Kebutuhan", Decimal("4800000")),
            ("Tabungan", Decimal("3000000")),
            ("Sinking Fund", Decimal("2400000")),
            ("Lifestyle", Decimal("1200000")),
            ("Kebutuhan", Decimal("600000")),  # digabung ke Kebutuhan
        ]
        out = build_allocation_distribution(rows, Decimal("12000000"))
        cats = {d["category"]: d for d in out["distribution"]}
        self.assertEqual(cats["Kebutuhan"]["amount"], 5400000.0)
        self.assertEqual(cats["Kebutuhan"]["pct"], 45)
        self.assertEqual(out["distribution"][0]["category"], "Kebutuhan")  # desc sort
        self.assertEqual(out["allocated_pct"], 100)
        self.assertEqual(out["saving_amount"], 5400000.0)  # Tabungan + Sinking Fund
        self.assertEqual(out["saving_pct"], 45)

    def test_drops_nonpositive_and_handles_zero_income(self):
        rows = [("Kebutuhan", Decimal("500000")), ("Lainnya", Decimal("-100000"))]
        out = build_allocation_distribution(rows, Decimal("500000"))
        self.assertEqual([d["category"] for d in out["distribution"]], ["Kebutuhan"])
        self.assertEqual(out["allocated_pct"], 100)
        zero = build_allocation_distribution([], Decimal("0"))
        self.assertEqual(zero["distribution"], [])
        self.assertEqual(zero["allocated_pct"], 0)
        self.assertEqual(zero["saving_pct"], 0)


class SelectVisibleSamplesTests(unittest.TestCase):
    def test_excludes_other_members_private_descriptions(self):
        from types import SimpleNamespace
        from uuid import uuid4
        from app.services.advisor import select_visible_samples

        me, other = uuid4(), uuid4()
        txns = [
            SimpleNamespace(user_id=other, is_private=True, description="terapi rahasia"),
            SimpleNamespace(user_id=other, is_private=False, description="netflix keluarga"),
            SimpleNamespace(user_id=me, is_private=True, description="kado istri"),
            SimpleNamespace(user_id=me, is_private=False, description="netflix keluarga"),
        ]
        samples = select_visible_samples(me, txns)
        self.assertNotIn("terapi rahasia", samples)
        self.assertIn("netflix keluarga", samples)
        self.assertIn("kado istri", samples)  # milik sendiri boleh
        self.assertEqual(samples.count("netflix keluarga"), 1)  # dedup

    def test_all_private_returns_empty(self):
        from types import SimpleNamespace
        from uuid import uuid4
        from app.services.advisor import select_visible_samples

        me, other = uuid4(), uuid4()
        txns = [SimpleNamespace(user_id=other, is_private=True, description="x")]
        self.assertEqual(select_visible_samples(me, txns), [])


class SinkingFundIdNoRawTokensTests(unittest.TestCase):
    def test_id_uses_stable_hash_not_raw_normalized_tokens(self):
        import hashlib
        from app.services.advisor import _sinking_group_id

        normalized = "terapi psikolog rahasia"
        env_id = "abc-123"
        got = _sinking_group_id(env_id, normalized)
        # id tidak boleh memuat token kata deskripsi
        self.assertNotIn("terapi", got)
        self.assertNotIn("psikolog", got)
        self.assertNotIn("rahasia", got)
        # stabil & deterministik
        self.assertEqual(got, _sinking_group_id(env_id, normalized))
        # format sfa:{env}:{hash8}
        expected_hash = hashlib.sha256(normalized.encode()).hexdigest()[:8]
        self.assertEqual(got, f"sfa:{env_id}:{expected_hash}")
        # grup berbeda → id berbeda
        self.assertNotEqual(got, _sinking_group_id(env_id, "netflix keluarga"))


if __name__ == "__main__":
    unittest.main()
