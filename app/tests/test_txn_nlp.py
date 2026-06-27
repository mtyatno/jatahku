"""Tests for pure helpers in app/services/txn_nlp.py.

Run from repo root:  python -m unittest app.tests.test_txn_nlp
"""
import unittest

from app.services.txn_nlp import extract_keywords, guess_envelope_name


class TestExtractKeywords(unittest.TestCase):
    def test_drops_short_words_stopwords_and_punctuation(self):
        kws = extract_keywords("beli kopi di starbucks!")
        # 'beli' and 'di' are stopwords; punctuation stripped
        self.assertIn("kopi", kws)
        self.assertIn("starbucks", kws)
        self.assertNotIn("di", kws)
        self.assertNotIn("beli", kws)

    def test_appends_full_phrase(self):
        kws = extract_keywords("nasi padang")
        self.assertIn("nasi", kws)
        self.assertIn("padang", kws)
        self.assertIn("nasi padang", kws)


class TestGuessEnvelopeName(unittest.TestCase):
    def test_food_keyword(self):
        self.assertEqual(guess_envelope_name("kopi pagi"), "makan")

    def test_transport_keyword(self):
        self.assertEqual(guess_envelope_name("gojek ke kantor"), "transport")

    def test_no_match_returns_none(self):
        self.assertIsNone(guess_envelope_name("xyzzy qwerty"))


if __name__ == "__main__":
    unittest.main()
