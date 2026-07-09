"""build_envelope_distribution — per-envelope income distribution (Alokasi donut toggle)."""
import unittest
from decimal import Decimal

from app.services.advisor.allocation import build_envelope_distribution


class EnvelopeDistributionTests(unittest.TestCase):
    def test_filters_sorts_and_computes_pct(self):
        rows = [
            ("Dapur", "🍳", Decimal("4200000")),
            ("Transfer keluar", "📤", Decimal("-500000")),   # net negatif -> drop
            ("Tabungan", "🐷", Decimal("3100000")),
            ("Kosong", "📭", Decimal("0")),                  # nol -> drop
        ]
        out = build_envelope_distribution(rows, Decimal("16600000"))
        self.assertEqual([d["name"] for d in out], ["Dapur", "Tabungan"])
        self.assertEqual(out[0], {"name": "Dapur", "emoji": "🍳", "amount": 4200000.0, "pct": 25})
        self.assertEqual(out[1]["pct"], 19)

    def test_zero_income_pct_zero(self):
        out = build_envelope_distribution([("Dapur", "🍳", Decimal("100000"))], Decimal("0"))
        self.assertEqual(out[0]["pct"], 0)
        self.assertEqual(out[0]["amount"], 100000.0)

    def test_empty_rows(self):
        self.assertEqual(build_envelope_distribution([], Decimal("1000000")), [])


if __name__ == "__main__":
    unittest.main()
