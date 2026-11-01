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

from app.services.kotak_struk import kerangka, merchants
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
# Kata nama orang karangan yang tercetak di daftar sapuan (kebenaran dasar, bukan hasil pembaca): tidak satu pun boleh muncul
# sebagai teks polos di kerangka. "DANA" sengaja tidak: nama yang juga nama penyedia (batas yang diketahui, docstring).
SWEEP_PERSON_WORDS = ("budi", "santoso", "siti", "aminah", "andi", "pratama", "rina", "hartono", "wulandari")
ID_WORDS = re.compile(r"(?<![a-z])(?:rek|rekening|no|nomor|ref|referensi|npwp|nmid|id|va|virtual|kode|pos|hp|terminal|"
                      r"pan|rrn|akun|pelanggan)(?![a-z])", re.IGNORECASE)
MONEY_WORDS = {"nominal", "jumlah", "total", "bayar", "dibayar", "pembayaran", "biaya", "admin", "harga", "subtotal",
               "amount", "tagihan", "saldo", "terpakai", "fee", "layanan", "diskon", "potongan", "promo", "voucher",
               "pajak", "ppn", "tax", "discount", "tips", "tip", "ongkir", "donasi", "debit", "paid", "payment"}
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


def well_formed_amount(amount: int, line: str, label: str | None) -> bool:
    """Nominal benar-benar tercetak sebagai uang di barisnya (pemeriksa independen dari regex kerangka): ribuan bertitik
    tanpa nol di depan, berawalan Rp/IDR, atau angka polos di bawah label uang."""
    dotted, commas = f"{amount:,}".replace(",", "."), f"{amount:,}"
    end = r"(?:[.,]\d\d)?(?![\d]|[.,]\d)"
    if re.search(r"(?<![\d.,])" + re.escape(dotted) + end, line):
        return True
    if re.search(r"(?i)(?:rp|idr)\.?\s*(?:" + "|".join(map(re.escape, (dotted, commas, str(amount)))) + ")" + end, line):
        return True
    return bool(label and set(label.split()) & MONEY_WORDS
                and re.search(r"(?<![\d.,])" + str(amount) + r"(?![\d]|[.,]\d)", line))


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
        # Batas tepat: 40 karakter boleh, 41 tidak.
        at_max, over = "pembayaran transaksi pembayaran subtotal", "pembayaran transaksi pembayaran recipient"
        self.assertEqual((len(at_max), len(over)), (LAYOUT_LABEL_MAX, LAYOUT_LABEL_MAX + 1))
        self.assertEqual(safe_label(at_max, forbidden_words=set()), at_max)
        self.assertIsNone(safe_label(over, forbidden_words=set()))

    def test_label_words_cover_known_labels(self):
        for name, labels in GENERIC_LABELS.items():
            for label in labels:
                with self.subTest(label=label):
                    self.assertIsNotNone(safe_label(label, forbidden_words=set()))
        for word in ("jumlah", "kirim", "uang", "ditransfer", "tanggal", "waktu", "selesai", "merchant", "ke", "dari"):
            self.assertIn(word, LABEL_WORDS)


class RuleKeyTests(unittest.TestCase):
    def test_tahap_1_has_only_profile_keys(self):
        # Review L1 I-1: baris teratas bukti tak dikenal bisa nama orang/merchant; tanpa kunci `logo:` sampai M2.
        self.assertIs(kerangka.LOGO_KEYS, False)
        self.assertEqual(rule_key(["GoPay", "Rp10.000"], GOPAY, forbidden_words=set()), "gopay")
        for lines in (["KilatPay", "Pembayaran Berhasil", "Rp10.000"], ["09:41", "Siti Aminah", "Kirim Uang Berhasil"],
                      ["10:57 LTE", "Wahyu Nugroho", "Rp50.000"], ["Bambang", "Pembayaran Berhasil"]):
            with self.subTest(lines=lines):
                self.assertIsNone(rule_key(lines, None, forbidden_words=set()))
        for lines in (["09:41", "Siti Aminah", "Kirim Uang Berhasil", "Nominal Rp50.000"],
                      ["RIZKY PRATAMA", "Bukti Transfer", "Total Rp150.000"], ["KilatPay", "Total Rp150.000"]):
            with self.subTest(lines=lines):
                self.assertIsNone(build_layout(lines, transfer_doc(doc_type="tidak_dikenali", issuer=None), Secrets(),
                                               user_name=None))

    @patch.object(kerangka, "LOGO_KEYS", True)
    def test_logo_key_for_unknown_app_and_none_for_status_bar_or_name(self):
        """Logika kunci logo untuk M2 (saklar `LOGO_KEYS`)."""
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

    @patch.object(kerangka, "LOGO_KEYS", True)
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
                 "RRN  …K2NW", "Rekening 0123****4567", "Ke xxxx1234", "Total Rp25.000", "Saldo ****1235",
                 "Debit …4822"]
        lay = build_layout(lines, transfer_doc(issuer="jago"), Secrets(), user_name=None)
        self.assertEqual([(e["i"], e.get("amount")) for e in lay["lines"]], [(1, 25000), (9, 25000)])
        for tail in ("4821", "7342", "2096", "4567", "1234", "1235", "4822"):
            self.assertNotIn(tail, json.dumps(lay))

    def test_logo_key_only_for_unknown_documents(self):
        # Tahap 1: tanpa profil aplikasi tidak ada kerangka sama sekali. Dengan `LOGO_KEYS` (M2): kunci logo hanya untuk
        # tidak_dikenali (QRIS/transfer tanpa profil sering diawali nama merchant, spec §2), dan baris logonya sendiri
        # tidak menjadi entri.
        lines = ["KilatPay", "Kopi Susu 1 25.000", "Total Rp25.000", "Bayar QRIS"]
        for doc_type in ("qris", "transfer", "tidak_dikenali"):
            self.assertIsNone(build_layout(lines, transfer_doc(doc_type=doc_type, issuer=None), Secrets(), user_name=None))
        with patch.object(kerangka, "LOGO_KEYS", True):
            self.assertIsNone(build_layout(lines, transfer_doc(doc_type="qris", issuer=None), Secrets(), user_name=None))
            lay = build_layout(lines, transfer_doc(doc_type="tidak_dikenali", issuer=None), Secrets(), user_name=None)
        self.assertEqual(lay["key"], "logo:kilatpay")
        self.assertEqual([e["i"] for e in lay["lines"]], [1, 2])   # baris logo (0) bukan entri nama

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
        lines = ["GoPay", "Transfer ke BUDI Berhasil", "Top Up Saldo", "Nominal Rp10.000", "Pembayaran Berhasil"]
        lay = build_layout(lines, transfer_doc(name=None), Secrets(), user_name=None)
        titles = {e["i"]: e["words"] for e in lay["lines"] if e["kind"] == "judul"}
        self.assertEqual(titles, {1: ["transfer", "ke", "berhasil"], 2: ["top", "up", "saldo"]})

    def test_title_is_capped_at_six_words(self):
        lay = build_layout(["GoPay", "Pembayaran Top Up Saldo Dana Masuk Transaksi Berhasil"], transfer_doc(),
                           Secrets(), user_name=None)
        self.assertEqual(lay["lines"], [{"i": 1, "label": None, "kind": "judul",
                                         "words": ["pembayaran", "top", "up", "saldo", "dana", "masuk"]}])

    def test_identifier_numbers_are_never_amounts(self):
        # Review L1 I-2/M-2: nomor rekening/NPWP/VA/HP/referensi/pelanggan dan kode pos tidak pernah menjadi `amount`.
        cases = {
            "rekening bertitik di bawah label": ["Rekening Tujuan", "012.345.678.9"],
            "rekening bertitik sebaris": ["No. Rekening 123.456.789.012"],
            "npwp": ["NPWP 01.234.567.8-901.000"],
            "va bertitik": ["Virtual Account 8808.1234.5678"],
            "rekening terbelah": ["Rekening", "0123 4567", "890"],
            "rekening terbelah pendek": ["Rekening", "1234", "5678"],
            "hp bertitik": ["Pulsa 0812.345.678"],
            "hp terbelah": ["No HP 0812 345", "6789"],
            "pelanggan bertitik": ["ID Pelanggan 5.123.456"],
            "referensi pendek": ["No. Ref 12345"],
            "referensi di bawah label": ["ID Transaksi", "1.234"],
            "kode pos": ["Bekasi 17520"],
            "alamat": ["Jl. Merdeka 1.234"],
            "angka polos tanpa label uang": ["Info transaksi pending/gagal: 14017"],
            "telepon bertitik berawalan nol tanpa label": ["021.234.567"],
            "kelompok janggal tanpa label": ["5.123.4567"],
        }
        for name, extra in cases.items():
            with self.subTest(name):
                lay = build_layout(["GoPay", *extra, "Total Rp150.000"], transfer_doc(), Secrets(), user_name=None)
                self.assertEqual([(e["label"], e["amount"]) for e in lay["lines"] if e["kind"] == "nominal"],
                                 [("total", 150000)])

    def test_money_shapes_still_read(self):
        lines = ["GoPay", "Total 25000", "Biaya Admin 2500", "Rp 25.000,00", "IDR 15000", "Jumlah", "45000", "RP  16.000",
                 "Nominal 1.500.000", "Rp 50,000"]
        lay = build_layout(lines, transfer_doc(), Secrets(), user_name=None)
        self.assertEqual([(e["i"], e["label"], e["amount"]) for e in lay["lines"]],
                         [(1, "total", 25000), (2, "biaya admin", 2500), (3, None, 25000), (4, None, 15000),
                          (6, "jumlah", 45000), (7, None, 16000), (8, "nominal", 1500000), (9, None, 50000)])

    def test_dashed_date_is_kept(self):
        lay = build_layout(["GoPay", "Tanggal 31-10-2026 10:40", "Waktu 31.10.2026"], transfer_doc(), Secrets(),
                           user_name=None)
        self.assertEqual([(e["kind"], e["label"], e["date"]) for e in lay["lines"]],
                         [("tanggal", "tanggal", "2026-10-31"), ("tanggal", "waktu", "2026-10-31")])

    def test_name_hash_uses_the_normalised_name(self):
        lay = build_layout(["GoPay", "Ditransfer ke M. Andi Saputra", "Penerima: Budi S."], transfer_doc(), Secrets(),
                           user_name=None)
        self.assertEqual([e["h"] for e in lay["lines"]], [hmac_hex("m andi saputra"), hmac_hex("budi s")])

    def test_short_secret_value_drops_its_line(self):
        lay = build_layout(["GoPay", "Total Rp50.000 (A1B2C)", "Biaya Rp2.500"], transfer_doc(),
                           Secrets(ref_values=["A1B2C"]), user_name=None)
        self.assertEqual([e["i"] for e in lay["lines"]], [2])

    def test_label_above_with_digits_is_not_a_label(self):
        lay = build_layout(["GoPay", "Biaya 2", "Rp5.000"], transfer_doc(), Secrets(), user_name=None)
        self.assertEqual([(e["i"], e["label"]) for e in lay["lines"]], [(2, None)])


class NameFilterTests(unittest.TestCase):
    """Review L1 I-3: setiap sumber nama (pihak lawan dokumen, pengirim, merchant berlabel, user) menyaring label, label
    baris di atas, dan judul; tiap tes hanya lolos lewat satu sumber itu. Kata nama yang dipakai di sini sengaja juga
    kata kosakata ("Admin", "Total", "Tujuan"), karena hanya kata seperti itu yang bisa masuk label."""

    def setUp(self):
        patcher = patch.object(merchants, "_warned_no_key", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def labels(self, lay):
        return [e["label"] for e in lay["lines"] if e["kind"] == "nominal"]

    def test_counterparty_name_filters_inline_and_above_labels(self):
        lines = ["GoPay", "Kirim ke Dana Rp50.000", "Biaya Admin", "Rp2.500"]
        self.assertEqual(self.labels(build_layout(lines, transfer_doc(name="Budi"), Secrets(), user_name=None)),
                         ["kirim ke dana", "biaya admin"])   # pembanding: tanpa nama itu labelnya utuh
        lay = build_layout(lines, transfer_doc(name="Dana Admin Pratama"), Secrets(), user_name=None)
        self.assertEqual(self.labels(lay), [None, None])
        self.assertNotIn("dana", json.dumps(lay).lower())

    def test_sender_name_filters_labels(self):
        lines = ["GoPay", "Pengirim", "Rudi Admin", "Biaya Admin Rp2.500"]
        self.assertEqual(pc.read_sender_name(lines, GOPAY), "Rudi Admin")
        lay = build_layout(lines, transfer_doc(name="Budi"), Secrets(), user_name=None)
        self.assertEqual(self.labels(lay), [None])

    def test_labelled_merchant_name_filters_labels(self):
        lines = ["GoPay", "Nama Merchant", "WARUNG TOTAL JAYA", "Total Rp15.000"]
        lay = build_layout(lines, transfer_doc(name=None), Secrets(), user_name=None)
        self.assertEqual(self.labels(lay), [None])

    def test_user_name_filters_labels_and_titles(self):
        lines = ["GoPay", "Transfer Tujuan Berhasil", "Tujuan Rp15.000"]
        lay = build_layout(lines, transfer_doc(name=None), Secrets(), user_name=None)
        self.assertEqual((self.labels(lay), lay["lines"][0]["words"]), (["tujuan"], ["transfer", "tujuan", "berhasil"]))
        lay = build_layout(lines, transfer_doc(name=None), Secrets(), user_name="Tujuan Wibowo")
        self.assertEqual((self.labels(lay), lay["lines"][0]["words"]), ([None], ["transfer", "berhasil"]))


class PublicReaderNamesTests(unittest.TestCase):
    def test_reader_helpers_used_by_kerangka_are_public(self):
        # Review L1 M-4: kerangka memakai nama publik; pembaca boleh mengganti nama privatnya asal alias ini tetap ada.
        from app.services.kotak_struk.readers import labels, transfer
        self.assertEqual(pc.classify_status("Transaksi Gagal"), pc.GAGAL)
        self.assertTrue(pc.STATUS_TITLE.search("Pembayaran Berhasil"))
        self.assertTrue(transfer.TOP_UP.search("Top Up GoPay") and transfer.INCOMING.search("Dana Masuk"))
        self.assertEqual(labels.find_date("Tanggal 31 Okt 2026")[2:], (2026, 10, 31))
        src = Path(kerangka.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?:pc|transfer_reader|labels)\._[a-z_A-Z]+|import _")

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
                    # Setiap nominal tercetak sebagai uang di barisnya, tidak di bawah/di samping label nomor.
                    for e in lay["lines"]:
                        if e["kind"] == "nominal":
                            line = clean[e["i"]]
                            self.assertTrue(well_formed_amount(e["amount"], line, e["label"]), (line, e))
                            above = clean[e["i"] - 1] if e["i"] else ""
                            self.assertFalse(ID_WORDS.search(line.split(re.search(r"\d", line).group(0))[0]), line)
                            if not e["label"] and not re.search(r"\d", above):
                                self.assertFalse(ID_WORDS.search(above), (above, line))
                    names = [doc.counterparty.name, pc.read_sender_name(clean, detect_issuer(clean)),
                             case.get("user_name")]
                    name_words = {w for n in names for w in normalize_name(n).split()} | set(SWEEP_PERSON_WORDS)
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
        text = json.dumps(SWEEP).lower()
        self.assertTrue(all(w in text for w in SWEEP_PERSON_WORDS))   # nama-nama itu memang tercetak di sapuan


if __name__ == "__main__":
    unittest.main()
