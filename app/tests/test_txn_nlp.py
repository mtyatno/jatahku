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

    def test_qris_merchant_words(self):
        # Kata yang sering muncul di nama merchant QRIS (Kotak Struk).
        for text, expected in [("SOTO LAMONGAN CAK DI", "makan"), ("martabak 77", "makan"), ("SEBLAK TETEH", "makan"),
                               ("SPBU 34.401", "transport"), ("Pertamina Sudirman", "transport"),
                               ("Shell Super", "transport"), ("Bengkel Maju Jaya", "transport"),
                               ("Apotek Sehat", "kesehatan"), ("apotik kimia", "kesehatan"),
                               ("Klinik Pratama", "kesehatan"), ("KIMIA FARMA 123", "kesehatan"), ("K24 Dago", "kesehatan")]:
            self.assertEqual(guess_envelope_name(text), expected, text)

    def test_warung_is_not_food(self):
        self.assertIsNone(guess_envelope_name("Warung Kelontong Bu Siti"))


if __name__ == "__main__":
    unittest.main()
