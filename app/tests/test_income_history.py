"""Tests for income history helpers. Run: python -m unittest app.tests.test_income_history"""
import unittest
from decimal import Decimal

from app.services.income_history import parse_transfer


class TestParseTransfer(unittest.TestCase):
    def test_parses_source_and_target(self):
        allocs = [
            {"envelope": "Transport", "emoji": "🚗", "amount": Decimal("-200000")},
            {"envelope": "Kebutuhan Rumah", "emoji": "🏠", "amount": Decimal("200000")},
        ]
        out = parse_transfer(allocs)
        self.assertEqual(out["from"], "Transport")
        self.assertEqual(out["from_emoji"], "🚗")
        self.assertEqual(out["to"], "Kebutuhan Rumah")
        self.assertEqual(out["to_emoji"], "🏠")
        self.assertEqual(out["amount"], "200000")

    def test_accepts_string_amounts_and_order_independent(self):
        allocs = [
            {"envelope": "Tujuan", "emoji": "", "amount": "150000"},
            {"envelope": "Sumber", "emoji": "", "amount": "-150000"},
        ]
        out = parse_transfer(allocs)
        self.assertEqual(out["from"], "Sumber")
        self.assertEqual(out["to"], "Tujuan")
        self.assertEqual(out["amount"], "150000")

    def test_returns_none_when_not_a_valid_pair(self):
        self.assertIsNone(parse_transfer([]))
        self.assertIsNone(parse_transfer([{"envelope": "A", "emoji": "", "amount": Decimal("100")}]))
        self.assertIsNone(parse_transfer([
            {"envelope": "A", "emoji": "", "amount": Decimal("100")},
            {"envelope": "B", "emoji": "", "amount": Decimal("100")},
        ]))
