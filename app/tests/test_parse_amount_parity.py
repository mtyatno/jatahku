"""Parser nominal bot harus membaca teks persis seperti parser web.

Kasus uji BERSAMA ada di frontend/src/lib/parseAmount.cases.json, dijalankan
juga oleh frontend/src/lib/parseAmount.test.js (node --test).

Run: python -m unittest app.tests.test_parse_amount_parity -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import pathlib
import unittest
from decimal import Decimal as D

from app.bot.handlers import parse_amount, parse_subscription
from app.bot.nlp_cmd import correction_amount, parse_multi_expense

CASES = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/parseAmount.cases.json").read_text())


class SharedCasesTests(unittest.TestCase):
    def test_multi_expense_matches_web(self):
        for c in CASES["multi"]:
            with self.subTest(input=c["input"]):
                got = parse_multi_expense(c["input"])
                self.assertEqual(got and [[int(a), d] for a, d in got], c["expect"])

    def test_amount_matches_web(self):
        for c in CASES["amount"]:
            with self.subTest(input=c["input"]):
                got = parse_amount(c["input"])
                self.assertEqual(got and [int(got[0]), got[1]], c["expect"])


class BotOnlyTests(unittest.TestCase):
    def test_correction_picks_new_amount(self):
        self.assertEqual(correction_amount("harusnya 25k bukan 30k"), D("25000"))
        self.assertEqual(correction_amount("salah ketik 30k jadi 25k"), D("25000"))
        self.assertEqual(correction_amount("ralat 30k"), D("30000"))
        self.assertEqual(correction_amount("tadi salah harusnya 2 juta"), D("2000000"))
        self.assertIsNone(correction_amount("batalin yang tadi"))

    def test_subscription_still_cleans_frequency_words(self):
        self.assertEqual(parse_subscription("netflix 54k tiap bulan"), (D("54000"), "netflix", "monthly", 1))
        self.assertEqual(parse_subscription("sewa server 250k tiap bulan")[:2], (D("250000"), "server"))
        amount, desc, freq, months = parse_subscription("tiap 2 bulan 300k netflix")
        self.assertEqual((amount, desc, freq, months), (D("300000"), "netflix", "2monthly", 2))


if __name__ == "__main__":
    unittest.main()
