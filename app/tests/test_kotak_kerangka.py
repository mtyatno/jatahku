"""Kerangka tata letak bukti bayar (spec 2026-11-01 §3a, §8; pre-flight K1, G1, G2, G4): label tersamar, jenis nilai,
nominal/tanggal, HMAC nama, tanpa nomor dan tanpa nama polos.
Run: python -m unittest app.tests.test_kotak_kerangka -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import re
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from app.services.kotak_struk import merchants
from app.services.kotak_struk.config import LAYOUT_LABEL_MAX, LAYOUT_MAX_LINES
from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.kerangka import LABEL_WORDS, build_layout, rule_key, safe_label
from app.services.kotak_struk.merchants import hmac_hex, normalize_name
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import ParseContext, Secrets
from app.services.kotak_struk.readers.profiles import GENERIC_LABELS, PROFILES, detect_issuer
from app.services.kotak_struk.registry import read_document

SWEEP = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "sweep_lines.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 1)
GOPAY = next(p for p in PROFILES if p.key == "gopay")
TRANSFER_LINES = ["GoPay", "Transfer Berhasil", "Ditransfer ke", "BUDI SANTOSO", "Mandiri 1234567890",
                  "Jumlah Kirim Uang", "Rp10.000", "Tanggal 31 Okt 2026", "No. Ref 123456789012"]


def transfer_doc(name=None, total=None, doc_type="transfer", issuer="gopay"):
    return DokumenBayar(doc_type=doc_type, issuer=issuer, counterparty=Counterparty(name=name),
                        amounts=Amounts(total=total))


def kinds(layout):
    return {(e["kind"], e.get("label")) for e in layout["lines"]}


def plain_texts(layout) -> list[str]:
    """Semua teks polos di kerangka: label, kata judul, dan kata logo kunci (kunci profil adalah konstanta kode)."""
    out = [e["label"] for e in layout["lines"] if e.get("label")]
    out += [w for e in layout["lines"] for w in e.get("words") or []]
    if layout["key"].startswith("logo:"):
        out.append(layout["key"][len("logo:"):])
    return out


def without_values(layout) -> str:
    """JSON kerangka tanpa nilai yang memang boleh berupa angka panjang: nominal (Rp150.000 = 6 digit), tanggal, HMAC."""
    return json.dumps({**layout, "lines": [{k: v for k, v in e.items() if k not in ("amount", "date", "h")}
                                           for e in layout["lines"]]})


class SafeLabelTests(unittest.TestCase):
    def test_label_is_normalised(self):
        self.assertEqual(safe_label("  Jumlah   Kirim Uang : ", forbidden_words=set()), "jumlah kirim uang")
        self.assertEqual(safe_label("Total Bayar", forbidden_words=set()), "total bayar")
        self.assertEqual(safe_label("Waktu Selesai:", forbidden_words=set()), "waktu selesai")

    def test_digits_become_hash(self):
        self.assertEqual(safe_label("Biaya 2", forbidden_words=set()), "biaya #")

    def test_label_with_name_or_unknown_word_is_dropped(self):
        self.assertIsNone(safe_label("Transfer ke BUDI SANTOSO", forbidden_words={"budi", "santoso"}))
        self.assertIsNone(safe_label("Transfer ke BUDI", forbidden_words=set()))   # kata di luar LABEL_WORDS
        self.assertIsNone(safe_label("Kirim ke", forbidden_words={"kirim"}))        # kata nama user/pihak lawan
        self.assertIsNone(safe_label("pending/gagal", forbidden_words=set()))
        lay = build_layout(["GoPay", "Transfer ke BUDI SANTOSO Rp10.000"], transfer_doc(name="BUDI SANTOSO"),
                           Secrets(), user_name=None)
        self.assertEqual([(e["kind"], e["label"], e["amount"]) for e in lay["lines"]], [("nominal", None, 10000)])
        self.assertNotIn("budi", json.dumps(lay).lower())

    def test_empty_long_or_wordy_label_is_dropped(self):
        for text in (None, "", "  :  ", "#", "12"):
            with self.subTest(text=text):
                self.assertIsNone(safe_label(text, forbidden_words=set()))
        self.assertIsNone(safe_label("jumlah total bayar biaya admin layanan", forbidden_words=set()))   # 6 kata
        long = "pembayaran " * 4 + "transaksi"
        self.assertGreater(len(long), LAYOUT_LABEL_MAX)
        self.assertIsNone(safe_label(long, forbidden_words=set()))

    def test_label_words_cover_known_labels(self):
        for name, labels in GENERIC_LABELS.items():
            for label in labels:
                with self.subTest(label=label):
                    self.assertIsNotNone(safe_label(label, forbidden_words=set()))
        for word in ("jumlah", "kirim", "uang", "ditransfer", "tanggal", "waktu", "selesai", "merchant", "ke", "dari"):
            self.assertIn(word, LABEL_WORDS)


class RuleKeyTests(unittest.TestCase):
    def test_logo_key_for_unknown_app_and_none_for_status_bar_or_name(self):
        self.assertEqual(rule_key(["GoPay", "Rp10.000"], GOPAY, forbidden_words=set()), "gopay")
        self.assertEqual(rule_key(["KilatPay", "Pembayaran Berhasil", "Rp10.000"], None, forbidden_words=set()),
                         "logo:kilatpay")
        # Bilah status (jam, panah) dilewati.
        self.assertEqual(rule_key(["10:57", "↑", "KilatPay", "Rp10.000"], None, forbidden_words=set()), "logo:kilatpay")
        self.assertIsNone(rule_key(["10:57", "Transfer Berhasil", "Nominal Rp10.000"], None, forbidden_words=set()))
        # Nama pihak lawan/user tidak pernah jadi kunci.
        self.assertIsNone(rule_key(["BUDI SANTOSO", "Transfer Berhasil", "Rp10.000"], None,
                                   forbidden_words={"budi", "santoso"}))
        # Label, kata status, kata LABEL_WORDS, QRIS, kata pendek, angka: bukan logo.
        for first in ("Penerima", "Berhasil", "Transfer", "QRIS", "Ok", "A1B2", "Bayar Sekarang Juga"):
            with self.subTest(first=first):
                self.assertIsNone(rule_key([first, "Rp10.000"], None, forbidden_words=set()))
        # Logo baru di bawah judul/baris teks lain bukan logo (baris teks di atasnya bisa nama orang).
        self.assertIsNone(rule_key(["Transfer Berhasil", "KILATPAY", "Rp10.000"], None, forbidden_words=set()))

    def test_logo_key_is_lower_case_and_short(self):
        self.assertEqual(rule_key(["Kilat Pay", "Rp10.000"], None, forbidden_words=set()), "logo:kilat pay")
        self.assertIsNone(rule_key(["Abcdefghijklmnopqrstu Vwxyzabcdefghijklmnop", "Rp1.000"], None,
                                   forbidden_words=set()))


class BuildLayoutTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_layout_shape_for_transfer(self):
        lay = build_layout(TRANSFER_LINES, transfer_doc(name="BUDI SANTOSO", total=10000),
                           Secrets(ref_values=["123456789012"], account_number="1234567890"), user_name="Andi Pratama")
        self.assertEqual((lay["v"], lay["key"]), (1, "gopay"))
        self.assertIn(("nominal", "jumlah kirim uang"), kinds(lay))
        self.assertIn(("tanggal", "tanggal"), kinds(lay))
        self.assertIn(("nama", "ditransfer ke"), kinds(lay))
        self.assertIn(("judul", None), kinds(lay))
        by_i = {e["i"]: e for e in lay["lines"]}
        self.assertEqual(by_i[6], {"i": 6, "label": "jumlah kirim uang", "kind": "nominal", "amount": 10000})
        self.assertEqual(by_i[7], {"i": 7, "label": "tanggal", "kind": "tanggal", "date": "2026-10-31"})
        self.assertEqual(by_i[3], {"i": 3, "label": "ditransfer ke", "kind": "nama", "h": hmac_hex("budi santoso")})
        self.assertEqual(by_i[1], {"i": 1, "label": None, "kind": "judul", "words": ["transfer", "berhasil"]})
        # Baris rekening dan referensi tidak masuk sama sekali; label tanpa nilai bukan entri.
        self.assertFalse({2, 4, 5, 8} & set(by_i))
        self.assertEqual([e["i"] for e in lay["lines"]], sorted(by_i))
        self.assertNotRegex(without_values(lay), r"\d{6,}")
        for word in ("budi", "santoso", "andi", "pratama", "mandiri"):
            self.assertNotIn(word, json.dumps(lay).lower())

    def test_long_digit_line_is_dropped_even_without_secrets(self):
        lines = ["DANA", "Kirim Uang Berhasil", "Ke SITI 0812 3456 7890", "Nominal Rp50.000", "Total Rp1.500.000"]
        lay = build_layout(lines, transfer_doc(name="SITI", issuer="dana"), Secrets(), user_name=None)
        self.assertEqual([e["i"] for e in lay["lines"]], [3, 4])
        self.assertEqual(lay["lines"][1]["amount"], 1500000)

    def test_masked_number_lines_are_dropped(self):
        # Ekor rekening/PAN/referensi tersamar bukan nominal: "…4821" tidak boleh tersimpan sebagai amount 4821.
        lines = ["Jago Syariah", "Rp25.000", "Sumber Dana", "…4821", "Bank Mandiri-…7342", "Terminal  *********2096",
                 "RRN  …K2NW", "Rekening 0123****4567", "Ke xxxx1234", "Total Rp25.000"]
        lay = build_layout(lines, transfer_doc(issuer="jago"), Secrets(), user_name=None)
        self.assertEqual([(e["i"], e.get("amount")) for e in lay["lines"]], [(1, 25000), (9, 25000)])
        for tail in ("4821", "7342", "2096", "4567", "1234"):
            self.assertNotIn(tail, json.dumps(lay))

    def test_logo_key_only_for_unknown_documents(self):
        # QRIS/transfer tanpa profil aplikasi sering diawali nama merchant: tidak dipakai sebagai kunci (spec §2).
        lines = ["KOPI NUSANTARA", "Kopi Susu 1 25.000", "Total Rp25.000", "Bayar QRIS"]
        self.assertIsNone(build_layout(lines, transfer_doc(doc_type="qris", issuer=None), Secrets(), user_name=None))
        lay = build_layout(lines, transfer_doc(doc_type="tidak_dikenali", issuer=None), Secrets(), user_name=None)
        self.assertEqual(lay["key"], "logo:kopi nusantara")

    def test_value_on_its_own_line_takes_the_label_above_only_when_it_is_a_label(self):
        lines = ["GoPay", "Total Bayar", "Rp12.500", "BUDI", "Rp1.000", "Tanggal & waktu transaksi",
                 "29 Okt 2026, 19:15 WIB"]
        lay = build_layout(lines, transfer_doc(name="BUDI"), Secrets(), user_name=None)
        by_i = {e["i"]: e for e in lay["lines"]}
        self.assertEqual(by_i[2]["label"], "total bayar")
        self.assertIsNone(by_i[4]["label"])              # baris di atasnya nama, bukan label
        self.assertEqual(by_i[6]["label"], "tanggal & waktu transaksi")
        self.assertEqual(by_i[6]["date"], "2026-10-29")

    def test_inline_name_after_label_or_colon(self):
        lines = ["GoPay", "Ditransfer ke Budi Hartono", "Nama Merchant: WARUNG BAKSO PAK DI", "Ke SITI"]
        lay = build_layout(lines, transfer_doc(name="Budi Hartono"), Secrets(), user_name=None)
        got = [(e["i"], e["kind"], e["label"], e["h"]) for e in lay["lines"]]
        self.assertEqual(got, [(1, "nama", "ditransfer ke", hmac_hex("budi hartono")),
                               (2, "nama", "nama merchant", hmac_hex(normalize_name("WARUNG BAKSO PAK DI"))),
                               (3, "nama", "ke", hmac_hex("siti"))])

    def test_title_words_hold_no_name_and_only_in_the_header(self):
        lines = ["KilatPay", "Transfer ke BUDI Berhasil", "Top Up Saldo", "Nominal Rp10.000", "Pembayaran Berhasil"]
        lay = build_layout(lines, transfer_doc(name=None, doc_type="tidak_dikenali", issuer=None), Secrets(),
                           user_name=None)
        titles = {e["i"]: e["words"] for e in lay["lines"] if e["kind"] == "judul"}
        self.assertEqual(titles, {1: ["transfer", "ke", "berhasil"], 2: ["top", "up", "saldo"]})
        self.assertEqual(lay["key"], "logo:kilatpay")

    def test_store_receipt_has_no_layout(self):
        doc = DokumenBayar(doc_type="struk_belanja", counterparty=Counterparty(name="ALFAMART"))
        self.assertIsNone(build_layout(["ALFAMART", "ROTI 1 15.000", "Total Belanja 15.000"], doc, Secrets(),
                                       user_name=None))
        # Juga bila barisnya memuat nama aplikasi yang dikenal (kunci profil ada): struk belanja tidak pernah.
        lines = ["INDOMARET", "TOP UP GOPAY 100.000", "ADMIN 2.000", "TOTAL 102.000", "TUNAI 102.000"]
        self.assertIsNotNone(detect_issuer(lines))
        for issuer in (None, "gopay"):
            doc = DokumenBayar(doc_type="struk_belanja", issuer=issuer, counterparty=Counterparty(name="INDOMARET"))
            self.assertIsNone(build_layout(lines, doc, Secrets(), user_name=None))

    def test_no_key_no_layout(self):
        doc = transfer_doc(name="BUDI SANTOSO", issuer=None)
        self.assertIsNone(build_layout(["Transfer Berhasil", "Penerima", "BUDI SANTOSO", "Nominal Rp150.000"], doc,
                                       Secrets(), user_name=None))

    def test_entries_are_capped(self):
        lines = ["GoPay"] + [f"Biaya Rp{i + 1}.000" for i in range(LAYOUT_MAX_LINES + 20)]
        lay = build_layout(lines, transfer_doc(), Secrets(), user_name=None)
        self.assertEqual(len(lay["lines"]), LAYOUT_MAX_LINES)
        self.assertEqual(lay["lines"][-1]["i"], LAYOUT_MAX_LINES)


class LayoutPrivacyTests(unittest.IsolatedAsyncioTestCase):
    """Review Focus 3: semua daftar sapuan bertanda proof/probe (dan sisanya), kedua posisi saklar."""

    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_layout_holds_no_pii(self):
        cases = [c for c in SWEEP if {"proof", "probe"} & set(c["tags"])]
        self.assertGreater(len(cases), 150)
        built = 0
        for case in SWEEP:
            for enabled in (False, True):
                text = TextDoc(lines=list(case["lines"]), kind=KIND_IMAGE)
                res = await read_document(text, ParseContext(today=TODAY, user_name=case.get("user_name")),
                                          proofs_enabled=enabled)
                doc, secrets = res.parsed.doc, res.parsed.secrets
                lay = build_layout(case["lines"], doc, secrets, user_name=case.get("user_name"))
                if lay is None:
                    continue
                built += 1
                with self.subTest(id=case["id"], on=enabled):
                    self.assertNotRegex(without_values(lay), r"\d{6,}")
                    clean = pc.clean_lines(case["lines"])
                    names = [doc.counterparty.name, pc.read_sender_name(clean, detect_issuer(clean)),
                             case.get("user_name")]
                    name_words = {w for n in names for w in normalize_name(n).split()}
                    for t in plain_texts(lay):
                        self.assertFalse(set(re.findall(r"[a-z]+", t.lower())) & name_words, t)
                    for e in lay["lines"]:
                        if e.get("label"):
                            words = [w.strip(".,:;()'&/-") for w in e["label"].split()]
                            self.assertTrue(all(not w or set(w) <= set("#.,") or w in LABEL_WORDS for w in words),
                                            e["label"])
                        if e["kind"] == "nama":
                            self.assertRegex(e["h"], r"^[0-9a-f]{64}$")
                        self.assertLessEqual(set(e), {"i", "label", "kind", "amount", "date", "h", "words"})
                    # Teks polos tanpa digit sama sekali (digit label menjadi "#"), jadi nomor apa pun tidak bisa
                    # tersimpan di sana; angka hanya di nominal, tanggal, dan indeks baris.
                    for t in plain_texts(lay):
                        self.assertNotRegex(t, r"\d", t)
        self.assertGreater(built, 20)   # sapuan benar-benar menghasilkan kerangka


if __name__ == "__main__":
    unittest.main()
