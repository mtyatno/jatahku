"""Kata sandi laporan terenkripsi Fernet (laporan berkala tahap 1, Task 1; spec bagian 4 dan 8).

`rahasia` membaca REPORT_SECRET_KEY lewat `get_settings()` saat dipanggil, bukan saat impor, jadi
tes cukup menambal `rahasia.get_settings`. Dua jenis kegagalan sengaja berbeda: kunci tidak ada atau
tidak valid -> `KunciLaporanTidakAda` (route: 503); token tersimpan tidak terbaca -> `ValueError`
(route: 409, diperlakukan seperti belum diatur).
Run: python -m unittest app.tests.test_laporan_rahasia -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.services.laporan import rahasia
from app.services.laporan.rahasia import (
    KunciLaporanTidakAda, check_configured, dekripsi, enkripsi, kunci_tersedia,
)

PERINGATAN = "REPORT_SECRET_KEY kosong atau tidak valid: kata sandi dan PDF laporan nonaktif"


def _kunci() -> str:
    return Fernet.generate_key().decode()


def _pakai(kunci: str | None):
    """Tambal pembacaan setelan: rahasia hanya boleh membaca kunci lewat get_settings()."""
    return patch.object(rahasia, "get_settings", return_value=SimpleNamespace(REPORT_SECRET_KEY=kunci))


# Kunci yang bukan kunci Fernet (32 byte base64 url-safe).
KUNCI_TIDAK_VALID = {
    "teks biasa": "bukan-kunci",
    "spasi saja": "   ",
    "base64 valid tapi 16 byte": base64.urlsafe_b64encode(b"0123456789abcdef").decode(),
    "32 karakter mentah": "0123456789abcdef0123456789abcdef",
    "bukan ASCII": "kunci-é-rahasia",
}


class RoundtripTests(unittest.TestCase):
    def test_roundtrip(self):
        with _pakai(_kunci()):
            token = enkripsi("rahasia-é1")
            self.assertEqual(dekripsi(token), "rahasia-é1")
        self.assertNotIn("rahasia", token)

    def test_token_is_ascii_text_fit_for_a_text_column(self):
        with _pakai(_kunci()):
            token = enkripsi("rahasia-é1")
        self.assertIsInstance(token, str)
        self.assertTrue(token.isascii())

    def test_boundary_lengths_and_non_latin_text(self):
        # Kata sandi laporan 6-64 karakter (spec bagian 4); isinya bebas, termasuk emoji dan spasi.
        sandi = ["abcdef", "x" * 64, "kata sandi dengan spasi", "sandi-😀-日本語", "é" * 64]
        with _pakai(_kunci()):
            for s in sandi:
                with self.subTest(s[:12]):
                    self.assertEqual(dekripsi(enkripsi(s)), s)

    def test_same_password_gives_different_tokens(self):
        # Fernet memakai IV acak: dua token untuk kata sandi sama tidak boleh identik.
        with _pakai(_kunci()):
            a, b = enkripsi("rahasia-é1"), enkripsi("rahasia-é1")
            self.assertNotEqual(a, b)
            self.assertEqual(dekripsi(a), dekripsi(b))

    def test_key_is_read_per_call_not_at_import(self):
        kunci_a, kunci_b = _kunci(), _kunci()
        with _pakai(kunci_a):
            token_a = enkripsi("sandi-a")
        with _pakai(kunci_b):
            token_b = enkripsi("sandi-b")
            self.assertEqual(dekripsi(token_b), "sandi-b")
        with _pakai(kunci_a):
            self.assertEqual(dekripsi(token_a), "sandi-a")

    def test_module_holds_no_key(self):
        self.assertFalse(hasattr(rahasia, "REPORT_SECRET_KEY"))


class MissingKeyTests(unittest.TestCase):
    def test_missing_key(self):
        # "" = bawaan Settings (kunci tidak diisi di .env); None hanya dari setelan tiruan, tapi tetap "tidak ada".
        for kosong in ("", None):
            with self.subTest(repr(kosong)), _pakai(kosong):
                self.assertFalse(kunci_tersedia())
                with self.assertRaises(KunciLaporanTidakAda):
                    enkripsi("rahasia-é1")
                with self.assertRaises(KunciLaporanTidakAda):
                    dekripsi("token-apa-saja")

    def test_error_is_a_runtime_error_and_not_a_value_error(self):
        # Pemanggil membedakan 503 (kunci) dari 409 (token tak terbaca) lewat ValueError.
        self.assertTrue(issubclass(KunciLaporanTidakAda, RuntimeError))
        self.assertFalse(issubclass(KunciLaporanTidakAda, ValueError))

    def test_invalid_key(self):
        with _pakai("bukan-kunci"):
            self.assertFalse(kunci_tersedia())

    def test_invalid_key_variants_are_all_unavailable(self):
        for nama, kunci in KUNCI_TIDAK_VALID.items():
            with self.subTest(nama), _pakai(kunci):
                self.assertFalse(kunci_tersedia())
                with self.assertRaises(KunciLaporanTidakAda):
                    enkripsi("rahasia-é1")

    def test_invalid_key_is_never_reported_as_unreadable_token(self):
        # Fernet sendiri melempar ValueError untuk kunci buruk; itu tidak boleh bocor sebagai 409.
        with _pakai(_kunci()):
            token = enkripsi("rahasia-é1")
        for nama, kunci in KUNCI_TIDAK_VALID.items():
            with self.subTest(nama), _pakai(kunci):
                with self.assertRaises(KunciLaporanTidakAda) as ctx:
                    dekripsi(token)
                self.assertNotIsInstance(ctx.exception, ValueError)

    def test_valid_key_is_available(self):
        with _pakai(_kunci()):
            self.assertTrue(kunci_tersedia())

    def test_key_error_message_never_contains_the_key(self):
        for kunci in KUNCI_TIDAK_VALID.values():
            with self.subTest(kunci), _pakai(kunci):
                with self.assertRaises(KunciLaporanTidakAda) as ctx:
                    enkripsi("rahasia-é1")
                if kunci.strip():
                    self.assertNotIn(kunci, str(ctx.exception))


class UnreadableTokenTests(unittest.TestCase):
    def test_token_from_other_key_is_value_error(self):
        with _pakai(_kunci()):
            token = enkripsi("rahasia-é1")
        with _pakai(_kunci()):
            with self.assertRaises(ValueError) as ctx:
                dekripsi(token)
        self.assertNotIsInstance(ctx.exception, KunciLaporanTidakAda)

    def test_garbage_tokens_are_value_errors(self):
        sampah = {
            "teks biasa": "bukan-token",
            "kosong": "",
            "bukan ASCII": "tokén-é",
            "base64 tapi bukan Fernet": base64.urlsafe_b64encode(b"x" * 64).decode(),
        }
        with _pakai(_kunci()):
            for nama, token in sampah.items():
                with self.subTest(nama):
                    with self.assertRaises(ValueError) as ctx:
                        dekripsi(token)
                    self.assertNotIsInstance(ctx.exception, KunciLaporanTidakAda)

    def test_truncated_and_tampered_tokens_are_value_errors(self):
        with _pakai(_kunci()):
            token = enkripsi("rahasia-é1")
            tengah = len(token) // 2
            diubah = token[:tengah] + ("A" if token[tengah] != "A" else "B") + token[tengah + 1:]
            for nama, buruk in {"terpotong": token[:-8], "diubah": diubah}.items():
                with self.subTest(nama):
                    with self.assertRaises(ValueError):
                        dekripsi(buruk)

    def test_every_unreadable_cause_gives_the_same_plain_value_error(self):
        # Satu jenis galat dan satu pesan untuk semua penyebab. Galat codec (token bukan ASCII, isi bukan
        # UTF-8) tidak boleh lolos apa adanya: pesannya memuat karakter/byte dari data yang dibuka.
        kunci, lain = _kunci(), _kunci()
        with _pakai(kunci):
            token = enkripsi("rahasia-é1")
        bukan_utf8 = Fernet(kunci.encode()).encrypt(b"\xff\xfe-sandi").decode()
        kasus = [
            ("kunci lain", token, lain),
            ("teks biasa", "bukan-token", kunci),
            ("kosong", "", kunci),
            ("bukan ASCII", "tokén-é", kunci),
            ("isi bukan UTF-8", bukan_utf8, kunci),
        ]
        pesan = set()
        for nama, isi, kunci_pakai in kasus:
            with self.subTest(nama), _pakai(kunci_pakai):
                with self.assertRaises(ValueError) as ctx:
                    dekripsi(isi)
                self.assertIs(type(ctx.exception), ValueError)
                pesan.add(str(ctx.exception))
        self.assertEqual(len(pesan), 1, pesan)

    def test_unreadable_token_error_leaks_neither_password_token_nor_key(self):
        kunci_lama, kunci_baru = _kunci(), _kunci()
        with _pakai(kunci_lama):
            token = enkripsi("rahasia-é1")
        with _pakai(kunci_baru):
            with self.assertRaises(ValueError) as ctx:
                dekripsi(token)
        pesan = str(ctx.exception)
        for terlarang in ("rahasia-é1", token, kunci_lama, kunci_baru):
            self.assertNotIn(terlarang, pesan)


class CheckConfiguredTests(unittest.TestCase):
    def test_check_configured_warns_without_secret(self):
        with _pakai(""), self.assertLogs("jatahku.laporan", level="WARNING") as logs:
            self.assertFalse(check_configured())
        self.assertEqual([r.getMessage() for r in logs.records], [PERINGATAN])
        self.assertEqual([r.levelname for r in logs.records], ["WARNING"])

    def test_check_configured_warns_for_invalid_key_without_echoing_it(self):
        for nama, kunci in KUNCI_TIDAK_VALID.items():
            with self.subTest(nama):
                with _pakai(kunci), self.assertLogs("jatahku.laporan", level="WARNING") as logs:
                    self.assertFalse(check_configured())
                self.assertEqual([r.getMessage() for r in logs.records], [PERINGATAN])
                if kunci.strip():
                    self.assertNotIn(kunci, "\n".join(logs.output))

    def test_check_configured_is_silent_with_valid_key(self):
        kunci = _kunci()
        with _pakai(kunci), self.assertNoLogs("jatahku.laporan", level="DEBUG"):
            self.assertTrue(check_configured())

    def test_password_and_key_are_never_logged(self):
        kunci = _kunci()
        with _pakai(kunci), self.assertNoLogs("jatahku.laporan", level="DEBUG"):
            token = enkripsi("rahasia-é1")
            self.assertEqual(dekripsi(token), "rahasia-é1")
            self.assertTrue(kunci_tersedia())

    def test_logger_name(self):
        self.assertEqual(rahasia.logger.name, "jatahku.laporan")


class SettingsTests(unittest.TestCase):
    def test_report_secret_key_has_no_default(self):
        from app.core.config import Settings
        self.assertIn("REPORT_SECRET_KEY", Settings.model_fields)
        self.assertEqual(Settings.model_fields["REPORT_SECRET_KEY"].default, "")


if __name__ == "__main__":
    unittest.main()
