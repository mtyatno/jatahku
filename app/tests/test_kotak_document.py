import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest import mock
from datetime import datetime, timezone, timedelta
from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar, Ref
from app.services.kotak_struk import merchants as M

WIB = timezone(timedelta(hours=7))

def qris(name="SITI AMINAH", city="BANDUNG"):
    return DokumenBayar(doc_type="qris", method="qris", status="berhasil", flow="keluar",
                        paid_at=datetime(2026, 10, 26, 8, 12, tzinfo=WIB),
                        counterparty=Counterparty(name=name, city=city), amounts=Amounts(total=25000),
                        refs=[Ref("rrn", "…8812")])

class DocumentTests(unittest.TestCase):
    def test_json_roundtrip_and_unknown_fields_ignored(self):
        d = qris().to_json()
        self.assertEqual(d["paid_at"], "2026-10-26T08:12:00+07:00")
        d["future_field"] = 1
        back = DokumenBayar.from_json(d)
        self.assertEqual((back.counterparty.name, back.amounts.total, back.refs[0].masked), ("SITI AMINAH", 25000, "…8812"))

class MerchantKeyTests(unittest.TestCase):
    def test_nmid_beats_name(self):
        self.assertEqual(M.counterparty_key(Counterparty("SITI"), nmid="id1024358806544"), "nmid:ID1024358806544")

    def test_name_and_city_normalized(self):
        self.assertEqual(M.counterparty_key(Counterparty("Siti  Aminah.", "Bandung")), "nama:siti aminah|bandung")

    def test_full_account_uses_hmac_never_raw_digits(self):
        k = M.counterparty_key(Counterparty("BUDI"), account_number="0123 0100 1234 567", bank_code="BRI")
        self.assertTrue(k.startswith("rek:")); self.assertNotIn("1234567", k)
        self.assertEqual(k, M.counterparty_key(Counterparty("BUDI S"), account_number="012301001234567", bank_code="BRI"))

    def test_masked_account_falls_back_to_name_and_bank(self):
        self.assertEqual(M.counterparty_key(Counterparty("BUDI", bank="BRI"), account_number="****4567"), "nama:budi|bri")

    def test_no_name_no_key(self):
        self.assertIsNone(M.counterparty_key(Counterparty(None)))

class DescriptionTests(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(M.display_name("SITI AMINAH"), "Siti Aminah")
        self.assertEqual(M.display_name("SPBU PERTAMINA 34.401"), "SPBU Pertamina 34.401")
        self.assertEqual(M.display_name("Kopi Kenangan"), "Kopi Kenangan")

    def test_compose(self):
        self.assertEqual(M.compose_description(qris(), display="Siti Aminah", note=None), "Siti Aminah (QRIS)")
        self.assertEqual(M.compose_description(qris(), display="Siti Aminah", note="bakso 2, es teh"), "bakso 2, es teh (Siti Aminah)")
        t = DokumenBayar(doc_type="transfer", counterparty=Counterparty("BUDI SANTOSO"))
        self.assertEqual(M.compose_description(t, display="Budi Santoso", note=None), "Transfer ke Budi Santoso")

    def test_learnable_text_drops_merchant_names(self):
        self.assertEqual(M.learnable_text("bakso 2, es teh (Siti Aminah)", ["SITI AMINAH", "Warung Bu Siti"]), "bakso 2, es teh")
        self.assertEqual(M.learnable_text("Siti Aminah (QRIS)", ["SITI AMINAH"]), "")
        self.assertEqual(M.learnable_text("Transfer ke Budi Santoso", ["BUDI SANTOSO"]), "")

    def test_mask_digits(self):
        self.assertEqual(M.mask_digits("612345678812"), "…8812")
        self.assertEqual(M.mask_digits("0123 0100 1234 567"), "…4567")


def _settings(key, secret="test-secret"):
    return mock.patch.object(M, "get_settings", return_value=SimpleNamespace(KOTAK_HMAC_KEY=key, JWT_SECRET=secret))


class HmacTests(unittest.TestCase):
    def setUp(self):
        M._warned_no_key = False

    def test_configured_key_is_used(self):
        with _settings("kunci-rahasia"), self.assertNoLogs(M.log, "WARNING"):
            got = M.hmac_hex("612345678812")
        self.assertEqual(got, hmac.new(b"kunci-rahasia", b"612345678812", hashlib.sha256).hexdigest())

    def test_empty_key_derives_from_jwt_secret_and_warns_once(self):
        derived = hashlib.sha256(b"kotak:jwt-x").digest()
        with _settings("", "jwt-x"), self.assertLogs(M.log, "WARNING") as logs:
            first = M.hmac_hex("abc")
            second = M.hmac_hex("abc")
        self.assertEqual(first, second)
        self.assertEqual(first, hmac.new(derived, b"abc", hashlib.sha256).hexdigest())
        self.assertNotEqual(first, hmac.new(b"", b"abc", hashlib.sha256).hexdigest())
        self.assertEqual(len(logs.records), 1)


class EdgeCaseTests(unittest.TestCase):
    def test_partially_masked_account_is_not_hashed(self):
        k = M.counterparty_key(Counterparty("BUDI", bank="BRI"), account_number="0123****4567", bank_code="BRI")
        self.assertEqual(k, "nama:budi|bri")

    def test_short_account_falls_back_to_name(self):
        self.assertEqual(M.counterparty_key(Counterparty("BUDI"), account_number="1234567"), "nama:budi|")

    def test_city_preferred_over_bank_and_key_capped_at_80(self):
        self.assertEqual(M.counterparty_key(Counterparty("Toko A", "Solo", bank="BCA")), "nama:toko a|solo")
        k = M.counterparty_key(Counterparty("x" * 200, "Solo"))
        self.assertEqual(len(k), 80)
        self.assertTrue(k.startswith("nama:xxx"))

    def test_normalize_name_drops_punctuation(self):
        self.assertEqual(M.normalize_name("  P.T. Maju-Jaya, CV!  "), "pt majujaya cv")
        self.assertEqual(M.normalize_name(None), "")

    def test_display_name_edge_cases(self):
        self.assertEqual(M.display_name(None), "")
        self.assertEqual(M.display_name("  PT  MAJU JAYA  "), "PT Maju Jaya")
        self.assertEqual(M.display_name("warung bu siti"), "warung bu siti")
        self.assertEqual(M.display_name("TB. BANGUNAN RS-1"), "TB. Bangunan RS-1")

    def test_compose_without_name(self):
        self.assertEqual(M.compose_description(qris(), display=None, note=None), "Pembayaran QRIS")
        self.assertEqual(M.compose_description(qris(), display=None, note="bakso"), "bakso")
        t = DokumenBayar(doc_type="transfer")
        self.assertEqual(M.compose_description(t, display=None, note=None), "Transfer")
        other = DokumenBayar(doc_type="tagihan")
        self.assertEqual(M.compose_description(other, display=None, note=None), "Bukti bayar")
        self.assertEqual(M.compose_description(other, display="PLN", note=None), "PLN")
        self.assertEqual(M.compose_description(other, display="PLN", note="token"), "token (PLN)")

    def test_compose_caps_at_500_and_keeps_merchant_name(self):
        out = M.compose_description(qris(), display="Siti Aminah", note="a" * 600)
        self.assertEqual(len(out), 500)
        self.assertTrue(out.endswith(" (Siti Aminah)"))
        self.assertEqual(len(M.compose_description(qris(), display=None, note="b" * 600)), 500)

    def test_learnable_text_edge_cases(self):
        # nama dicocokkan utuh sebagai kata: "Bu" tidak merusak "bubur"; nama terpanjang dihapus dulu
        self.assertEqual(M.learnable_text("bubur ayam (Bu)", ["Bu"]), "bubur ayam")
        self.assertEqual(M.learnable_text("es teh (Siti Aminah)", ["Siti", "Siti Aminah", "", None]), "es teh")
        self.assertEqual(M.learnable_text("bayar kopi", []), "bayar kopi")

    def test_mask_digits_edge_cases(self):
        self.assertEqual(M.mask_digits("12-34-56", keep=2), "…56")
        self.assertEqual(M.mask_digits("1234", keep=0), "…")
        self.assertEqual(M.mask_digits("abc"), "")

    def test_from_json_tolerates_missing_and_unknown_nested(self):
        back = DokumenBayar.from_json({"doc_type": "transfer", "counterparty": {"name": "BUDI", "zzz": 1},
                                       "amounts": None, "lines": [{"kind": "fee", "name": "Biaya", "amount": 2500, "x": 1}],
                                       "paid_at": None})
        self.assertEqual((back.counterparty.name, back.amounts.total, back.paid_at), ("BUDI", None, None))
        self.assertEqual((back.lines[0].kind, back.lines[0].amount, back.lines[0].flag), ("fee", 2500, "ok"))
        self.assertEqual(DokumenBayar.from_json(back.to_json()), back)


class ReviewFixTests(unittest.TestCase):
    def test_nameless_fallback_descriptions_teach_nothing(self):
        other = DokumenBayar(doc_type="tagihan")
        t = DokumenBayar(doc_type="transfer")
        for doc in (qris(), t, other):
            desc = M.compose_description(doc, display=None, note=None)
            self.assertEqual(M.learnable_text(desc, []), "", desc)
            self.assertEqual(M.learnable_text(desc.upper(), []), "", desc)
            self.assertEqual(M.learnable_text(desc.lower(), []), "", desc)

    def test_fallback_strip_is_exact_user_words_survive(self):
        self.assertEqual(M.learnable_text("transfer arisan", []), "transfer arisan")
        self.assertEqual(M.learnable_text("bukti bayar kos", []), "bukti bayar kos")
        self.assertEqual(M.learnable_text("pembayaran qris bakso", []), "pembayaran qris bakso")

    def test_dot_or_dash_masked_account_is_not_hashed(self):
        for masked in ("0123 .... 4567", "0123-----4567", "0123 - 4567 8901", "0123....4567", "0123 **** 4567"):
            k = M.counterparty_key(Counterparty("BUDI", bank="BRI"), account_number=masked, bank_code="BRI")
            self.assertEqual(k, "nama:budi|bri", masked)

    def test_single_separators_between_digit_groups_still_hashed(self):
        full = M.counterparty_key(Counterparty("BUDI"), account_number="012301001234567", bank_code="BRI")
        for ok in ("0123 0100 1234 567", "0123-0100-1234-567", "0123.0100.1234.567", "  0123   0100 1234 567 "):
            self.assertEqual(M.counterparty_key(Counterparty("BUDI"), account_number=ok, bank_code="BRI"), full, ok)
