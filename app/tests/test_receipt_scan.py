"""Tests scan struk: parser, susun baris OCR, belajar dari koreksi, kuota, plafon LLM.

Run from repo root:  python -m unittest app.tests.test_receipt_scan -v
(Tidak butuh rapidocr/Redis/Postgres — semua di-fake.)
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.services.receipt_parser import (
    amounts_in, merchant_key, normalize_line, parse_receipt,
)
from app.services.receipt_ocr import OcrResult, build_lines
from app.services import receipt_llm, receipt_scan
from app.tests.fakes import FakeResult, db_with

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())


class TestParserRealReceipts(unittest.TestCase):
    """4 struk Indomaret asli (dipegang, kusut, bayangan, buram) — semua harus benar."""

    def test_all_fixtures_total_date_merchant(self):
        for rec in FIXTURES["receipts"]:
            with self.subTest(rec["id"]):
                p = parse_receipt(rec["lines"], today=date(2026, 10, 15), max_age_days=4000)
                self.assertEqual(p.total, rec["expect"]["total"])
                self.assertEqual(p.date.isoformat(), rec["expect"]["date"])
                self.assertEqual(p.merchant, rec["expect"]["merchant"])
                self.assertEqual(p.confidence, "tinggi", p.evidence)

    def test_old_receipt_date_rejected_by_default(self):
        rec = FIXTURES["receipts"][3]  # 2019
        p = parse_receipt(rec["lines"], today=date(2026, 10, 15))
        self.assertIsNone(p.date)
        self.assertEqual(p.total, 9200)


class TestParserRules(unittest.TestCase):
    TODAY = date(2026, 10, 14)

    def parse(self, text, **kw):
        return parse_receipt(text.strip().splitlines(), today=self.TODAY, **kw)

    def test_ocr_typos_fixed(self):
        self.assertEqual(normalize_line("T0TAL 5O.4OO"), "TOTAL 50.400")
        self.assertIn("TUNAI", normalize_line("TUNAL 50.000"))
        self.assertIn("KEMBALI", normalize_line("KEHBALI 40.800"))

    def test_amount_formats(self):
        self.assertEqual(amounts_in("TOTAL Rp 35.000,00"), [35000])
        self.assertEqual(amounts_in("TOTAL 35,000"), [35000])
        self.assertEqual(amounts_in("ROTI 1 15500"), [15500])
        self.assertEqual(amounts_in("24.05.25-09:11/3.0.27/THTV-363626"), [])
        self.assertEqual(amounts_in("HP 081295158435"), [])

    def test_qris_non_tunai_crosscheck(self):
        p = self.parse("""ALFAMART
14-10-2026 08:15
Total Belanja 45.400
Non Tunai (QRIS) 45.400""")
        self.assertEqual((p.total, p.confidence), (45400, "tinggi"))

    def test_grand_total_beats_subtotal(self):
        p = self.parse("""WARUNG NASI AMPERA
Tgl: 13 Okt 2026
Subtotal 40.000
PB1 10% 4.000
Grand Total Rp 44.000
Cash Rp 50.000
Kembalian Rp 6.000""")
        self.assertEqual((p.total, p.confidence), (44000, "tinggi"))
        self.assertEqual(p.date, date(2026, 10, 13))
        self.assertEqual(p.merchant, "Warung Nasi Ampera")

    def test_no_keyword_low_confidence(self):
        p = self.parse("TOKO SUMBER REJEKI\ngula 1kg 18000\n45500")
        self.assertEqual((p.total, p.confidence), (45500, "rendah"))

    def test_nothing_readable(self):
        p = self.parse("blurry\n???")
        self.assertIsNone(p.total)
        self.assertEqual(p.confidence, "gagal")

    def test_learned_profile_label_wins(self):
        text = """TOKO MAJU
JML BYR 77.000
SUBTOTAL 70.000"""
        self.assertEqual(self.parse(text).confidence, "rendah")
        p = self.parse(text, merchant_profiles={"TOKOMAJU": ["JML BYR"]})
        self.assertEqual(p.total, 77000)

    def test_subtotal_not_taken_when_total_incl_tax(self):
        p = self.parse("RESTO A\nSUB TOTAL 100.000\nPAJAK 10% 10.000\nTOTAL (INCL. TAX) 115.500")
        self.assertEqual(p.total, 115500)

    def test_masked_card_number_never_a_total(self):
        p = self.parse("TOKO B\nNO KARTU 5264 82** **** 1234\nKARTU: 4567 **** **** 8899\nDEBIT BCA 140.500")
        self.assertEqual(p.total, 140500)

    def test_cash_without_change_is_low_confidence(self):
        p = self.parse("WARKOP\nKOPI 18.000\nTUNAI 50.000")
        self.assertEqual(p.confidence, "rendah")

    def test_total_contradicting_payment_is_low_confidence(self):
        p = self.parse("TOKO C\nTOTAL 60.000\nTUNAI 150.000\nKEMBALI 9.500")
        self.assertEqual(p.confidence, "rendah")

    def test_fuzzy_fix_does_not_rename_merchant_or_items(self):
        p = self.parse("TUNAS JAYA\nBERAS 5KG 75.000\nTOTAL 75.000")
        self.assertEqual(p.merchant, "Tunas Jaya")
        p = self.parse("TOKO X\nTUNAS JAYA 12.000\nTOTAL 12.000\nTUNAL 20.000\nKEHBALI 8.000")
        self.assertEqual((p.total, p.confidence), (12000, "tinggi"))

    def test_learned_label_cannot_override_payment_confirmed_total(self):
        text = "INDOMARET\nINDOMIE GORENG 3.500\nTOTAL 50.000\nTUNAI 50.000"
        p = self.parse(text, merchant_profiles={"INDOMARET": ["INDOMIE GORENG"]})
        self.assertEqual((p.total, p.confidence), (50000, "tinggi"))

    def test_learned_merchant_alias(self):
        p = self.parse("1NDOMAREI\nTOTAL 9.000", merchant_aliases={"1NDOMAREI": "Indomaret"})
        self.assertEqual(p.merchant, "Indomaret")


class TestReceiptItems(unittest.TestCase):
    """Rincian barang: Σ barang − diskon + pajak harus = total struk."""
    TODAY = date(2026, 10, 14)

    def parse(self, text, **kw):
        return parse_receipt(text.strip().splitlines(), today=self.TODAY, **kw)

    def test_real_receipts_items_reconcile(self):
        expected_items = {"s1": 8, "s2": 5, "s3": 4, "s4": 2}
        for rec in FIXTURES["receipts"]:
            with self.subTest(rec["id"]):
                p = parse_receipt(rec["lines"], today=date(2026, 10, 15), max_age_days=4000)
                self.assertEqual(p.reconciliation.status, "cocok", [(i.name, i.amount) for i in p.items])
                self.assertEqual(len(p.items), expected_items[rec["id"]])
                self.assertEqual(p.reconciliation.diff, 0)

    def test_inline_voucher_attaches_to_item_above(self):
        p = parse_receipt(FIXTURES["receipts"][0]["lines"], today=date(2026, 10, 15), max_age_days=4000)
        by_name = {i.name: i for i in p.items}
        self.assertEqual(by_name["SOKLN SOFTR ROSY 720"].discount, 3000)
        self.assertEqual(by_name["YC SS BKR SAPI KEJU"].discount, 5000)
        self.assertEqual(p.reconciliation.items_total, 149500)

    def test_global_vouchers_after_subtotal(self):
        p = parse_receipt(FIXTURES["receipts"][2]["lines"], today=date(2026, 10, 15), max_age_days=4000)
        self.assertEqual(sorted(a.amount for a in p.adjustments if a.kind == "discount"), [5900, 22900])

    def test_garbled_line_total_uses_unit_price(self):
        p = parse_receipt(FIXTURES["receipts"][3]["lines"], today=date(2026, 10, 15), max_age_days=4000)
        roti = p.items[1]
        self.assertEqual((roti.amount, roti.flag), (4500, "auto"))
        self.assertIn("40", roti.note)

    def test_merged_qty_and_price(self):
        p = parse_receipt(FIXTURES["receipts"][0]["lines"], today=date(2026, 10, 15), max_age_days=4000)
        choco = next(i for i in p.items if i.name.startswith("CHOCOLITO"))
        self.assertEqual((choco.qty, choco.unit_price, choco.amount), (1.0, 6000, 6000))

    def test_pack_count_kept_in_name(self):
        self.assertIn("20S", normalize_line("CAMEL ACT.P MINT 20S 29300 29.300"))

    def test_tax_line_counts_as_charge(self):
        p = self.parse("""WARUNG NASI AMPERA
Tgl: 13 Okt 2026
Nasi Putih 2 x 6.000 12.000
Es Teh 2 x 5.000 10.000
Subtotal 22.000
PB1 10% 2.200
Grand Total Rp 24.200""")
        self.assertEqual(p.reconciliation.status, "cocok")
        self.assertEqual(p.reconciliation.charges, 2200)
        self.assertEqual(p.items[0].qty, 2.0)

    def test_two_line_item(self):
        p = self.parse("""TOKO A
14/10/2026
INDOMIE GORENG SPECIAL
2 X 3.500 7.000
TOTAL 7.000""")
        self.assertEqual(len(p.items), 1)
        self.assertEqual((p.items[0].name, p.items[0].amount, p.items[0].qty), ("INDOMIE GORENG SPECIAL", 7000, 2.0))

    def test_misread_subtotal_fixed_by_unit_price(self):
        p = self.parse("""INDOMARET
14.10.26-10:00/1/A/01
SCORA GENTLE CLEAN75 1 37900 37,800
AQUA 600ML 2 3800 7,600
TOTAL : 45,500
TUNAI : 50,000
KEMBALI : 4,500""")
        self.assertEqual(p.reconciliation.status, "cocok")
        self.assertEqual((p.items[0].amount, p.items[0].flag), (37900, "auto"))

    def test_misread_digit_without_unit_price_is_suggested(self):
        p = self.parse("""INDOMARET
14.10.26-10:00/1/A/01
SCORA GENTLE CLEAN75 37,800
TOTAL : 37,900
TUNAI : 40,000
KEMBALI : 2,100""")
        it = p.items[0]
        self.assertEqual((it.flag, it.suggestion, it.amount), ("cek", 37900, 37800))
        self.assertEqual(p.reconciliation.diff, 100)
        self.assertEqual(p.confidence, "tinggi")  # total tetap terbukti oleh pembayaran

    def test_missing_item_reported(self):
        p = self.parse("""INDOMARET
14.10.26-10:00/1/A/01
SCORA GENTLE CLEAN75 1 37900 37,900
TOTAL : 45,500
TUNAI : 50,000
KEMBALI : 4,500""")
        self.assertEqual(p.reconciliation.diff, 7600)
        self.assertIn("belum masuk rincian", p.reconciliation.note)

    def test_duplicate_flags_only_second_copy(self):
        p = self.parse("""INDOMARET
14.10.26-10:00/1/A/01
SCORA GENTLE CLEAN75 1 37900 37,900
AQUA 600ML 2 3800 7,600
AQUA 600ML 2 3800 7,600
TOTAL : 45,500
TUNAI : 50,000
KEMBALI : 4,500""")
        self.assertEqual([i.flag for i in p.items], ["ok", "ok", "cek"])
        self.assertEqual(p.items[2].suggestion, 0)

    def test_items_upgrade_confidence(self):
        p = self.parse("""TOKO MAJU
14/10/2026
GULA 1KG 1 18.000 18.000
MINYAK 2L 1 38.000 38.000
TOTAL 56.000""")
        self.assertEqual((p.total, p.confidence), (56000, "tinggi"))
        self.assertTrue(any("cocok" in e for e in p.evidence))

    def test_no_total_line_uses_items(self):
        p = self.parse("WARUNG BU TINI\nNASI RAMES 15.000\nES JERUK 5.000")
        self.assertEqual((p.total, p.confidence), (20000, "rendah"))

    def test_grocery_name_not_turned_into_keyword(self):
        p = self.parse("PASAR SEGAR\nBAYAM 7.500\nWORTEL 1KG 12.000\nTOTAL 19.500")
        self.assertEqual([i.name for i in p.items], ["BAYAM", "WORTEL 1KG"])

    def test_address_postal_code_is_not_an_item(self):
        p = self.parse("TOKO A\nKEC. CIKARANG UTARA, KAB. BEKASI, 17534\nROTI 9.000\nTOTAL 9.000")
        self.assertEqual([i.name for i in p.items], ["ROTI"])


class TestReceiptItemsReviewCases(unittest.TestCase):
    """Kasus dari review independen (rincian barang)."""
    TODAY = date(2026, 10, 14)

    def parse(self, text):
        return parse_receipt(text.strip().splitlines(), today=self.TODAY)

    def test_subtotal_before_tax_resolves_to_paid_amount(self):
        p = self.parse("RESTO\n14/10/2026\nNasi 2 x 6.000 12.000\nEs Teh 2 x 5.000 10.000\n"
                       "Subtotal 22.000\nPB1 10% 2.200\nTunai 50.000\nKembali 25.800")
        self.assertEqual((p.total, p.confidence, p.confidence_source), (24200, "tinggi", "payment"))

    def test_tax_after_total_line_resolves_to_card_amount(self):
        p = self.parse("RESTO\n14/10/2026\nSteak 1 60.000 60.000\nTOTAL 60.000\nSERVICE 5% 3.000\n"
                       "PB1 10% 6.300\nDEBIT BCA 69.300")
        self.assertEqual((p.total, p.confidence), (69300, "tinggi"))
        self.assertEqual(p.reconciliation.charges, 9300)

    def test_items_never_upgrade_a_total_the_payment_contradicts(self):
        p = self.parse("TOKO\n14/10/2026\nGULA 1 20.000 20.000\nTOTAL 20.000\nDEBIT BCA 35.000")
        self.assertEqual(p.reconciliation.status, "cocok")
        self.assertEqual(p.confidence, "rendah")

    def test_items_never_upgrade_a_subtotal_line(self):
        p = self.parse("TOKO\n14/10/2026\nGULA 1 20.000 20.000\nHARGA JUAL 20.000")
        self.assertNotEqual(p.confidence, "tinggi")

    def test_unlabelled_total_line_not_counted_as_item(self):
        p = self.parse("TOKO\n14/10/2026\nGULA 20.000\nMINYAK 30.000\nBAYAR 50.000")
        self.assertEqual(p.total, 50000)
        self.assertEqual([i.name for i in p.items], ["GULA", "MINYAK"])

    def test_two_line_item_guess(self):
        p = self.parse("TOKO\nINDOMIE GORENG SPECIAL\n2 X 3.500 7.000\nAQUA 600ML 3.000")
        self.assertEqual((p.total, p.confidence_source), (10000, "items_sum"))
        self.assertTrue(all(i.flag == "ok" for i in p.items))

    def test_total_discount_summary_not_double_counted(self):
        p = self.parse("ALFAMART\n14-10-2026\nROTI 1 25.000 25.000\nDisc. (5.000)\nSUSU 1 25.000 25.000\n"
                       "Total Disc. (5.000)\nTotal Belanja 45.000\nTunai 50.000\nKembali 5.000")
        self.assertEqual(p.reconciliation.status, "cocok")

    def test_absurd_number_is_ignored(self):
        p = self.parse("TOKO\nBARANG 10.000.000.000.000\nTOTAL 9.000")
        self.assertEqual(p.total, 9000)

    def test_no_auto_fix_against_guessed_total(self):
        p = self.parse("TOKO\nSUSU 2 5.000 15.000\nROTI 5.000")
        susu = p.items[0]
        self.assertEqual((susu.amount, susu.flag), (15000, "cek"))  # ditandai, tidak diubah

    def test_keywords_inside_item_names(self):
        p = self.parse("TOKO\n14/10/2026\nSENSODYNE TOTAL CARE 1 25000 25.000\nCASHEW 1 30000 30.000\n"
                       "KARTU UCAPAN 1 5000 5.000\nPAKET PROMO 1 10000 10.000\nTOTAL 70.000\nTUNAI 70.000")
        self.assertEqual(len(p.items), 4)
        self.assertEqual((p.total, p.confidence, p.confidence_source), (70000, "tinggi", "payment"))


class TestBuildLines(unittest.TestCase):
    @staticmethod
    def box(x0, y0, x1, y1):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    def test_curved_receipt_pairs_label_with_value(self):
        # Kolom label & nilai bergeser 12px (struk melengkung) — tetap berpasangan.
        boxes = [
            self.box(10, 100, 80, 120), self.box(200, 112, 280, 132),   # TUNAI 150,000
            self.box(10, 125, 90, 145), self.box(200, 137, 280, 157),   # KEMBALI 9,500
        ]
        lines = build_lines(boxes, ["TUNAI", "150,000", "KEMBALI", "9,500"])
        self.assertEqual(lines, ["TUNAI  150,000", "KEMBALI  9,500"])

    def test_left_to_right_order(self):
        lines = build_lines([self.box(300, 0, 350, 20), self.box(0, 2, 100, 22)], ["9,200", "TOTAL:"])
        self.assertEqual(lines, ["TOTAL:  9,200"])


def _blank_png(width, height):
    """PNG polos 1-bit: file kecil (KB) tapi resolusi besar — pola bom dekompresi."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("1", (width, height)).save(buf, format="PNG")
    return buf.getvalue()


class TestImageGuard(unittest.TestCase):
    def test_decompression_bomb_rejected_before_decode(self):
        from app.services.receipt_ocr import OcrFailed, check_dimensions
        bomb = _blank_png(8000, 8000)  # 64 MP
        self.assertLess(len(bomb), 100_000)
        with self.assertRaises(OcrFailed):
            check_dimensions(bomb)
        check_dimensions(_blank_png(4000, 3000))  # foto HP 12 MP lolos

    def test_garbage_bytes_rejected(self):
        from app.services.receipt_ocr import OcrFailed, check_dimensions
        with self.assertRaises(OcrFailed):
            check_dimensions(b"bukan gambar")


class TestLearning(unittest.TestCase):
    def test_label_for_corrected_amount_skips_payment_lines(self):
        lines = ["ROTI 9.200", "JML BYR 9.200", "TUNAI 9.200", "NON TUNAI 9.200"]
        self.assertEqual(receipt_scan.find_label_for_amount(lines, 9200), "JML BYR")

    def test_merchant_key(self):
        self.assertEqual(merchant_key("Mr. DIY"), "MRDIY")
        self.assertIsNone(merchant_key(None))


def _user(plan="basic"):
    return SimpleNamespace(id=uuid4(), plan=plan)


class TestScanFlow(unittest.IsolatedAsyncioTestCase):
    async def test_basic_quota_exceeded(self):
        db = db_with(FakeResult(15))
        db.rollback = AsyncMock()
        with self.assertRaises(receipt_scan.ScanQuotaExceeded):
            await receipt_scan.scan_receipt(_user(), b"img", "image/jpeg", db, ocr=AsyncMock(), llm=AsyncMock())

    async def test_pro_unlimited_and_result_shape(self):
        lines = FIXTURES["receipts"][1]["lines"]
        db = db_with(FakeResult(500), FakeResult(rows=[]), FakeResult(rows=[]))
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        llm = AsyncMock()
        out = await receipt_scan.scan_receipt(
            _user("pro"), b"img", "image/jpeg", db,
            ocr=AsyncMock(return_value=OcrResult(lines=lines, score=0.9, seconds=1.0)), llm=llm,
        )
        self.assertEqual(out["total"], 51000)
        self.assertEqual(out["engine"], "rapidocr")
        self.assertEqual(len(out["items"]), 5)
        self.assertEqual(out["reconciliation"]["status"], "cocok")
        self.assertEqual(out["items"][1]["discount"], 4800)  # voucher KOBE melekat ke barangnya
        json.dumps(out)  # bisa diserialisasi untuk respons API
        self.assertIsNone(out["quota"]["limit"])
        llm.assert_not_awaited()  # keyakinan tinggi → LLM tidak dipanggil
        saved = db.add.call_args[0][0]
        self.assertEqual(saved.parsed_total, Decimal(51000))

    async def test_low_confidence_uses_llm_fallback(self):
        db = db_with(FakeResult(0), FakeResult(rows=[]), FakeResult(rows=[]))
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        out = await receipt_scan.scan_receipt(
            _user(), b"img", "image/jpeg", db,
            ocr=AsyncMock(return_value=OcrResult(lines=["buram"], score=0.2, seconds=1.0)), llm=llm,
        )
        self.assertEqual((out["engine"], out["total"], out["merchant"]), ("llm", 12000, "Toko A"))
        self.assertEqual(out["quota"], {"limit": 15, "used": 1, "remaining": 14})
        db.rollback.assert_not_awaited()  # rollback meng-expire `user` → MissingGreenlet (bug prod 15 Okt)
        db.commit.assert_awaited()  # koneksi DB dilepas sebelum OCR lewat commit

    async def test_llm_crash_keeps_ocr_result(self):
        db = db_with(FakeResult(0), FakeResult(rows=[]), FakeResult(rows=[]))
        db.refresh = AsyncMock(); db.rollback = AsyncMock()
        out = await receipt_scan.scan_receipt(
            _user(), b"img", "image/jpeg", db,
            ocr=AsyncMock(return_value=OcrResult(lines=["TOKO", "45.500"], score=0.5, seconds=1.0)),
            llm=AsyncMock(side_effect=RuntimeError("redis mati")),
        )
        self.assertEqual((out["engine"], out["total"]), ("rapidocr", 45500))

    @staticmethod
    def _feedback_db(scan):
        db = MagicMock()
        db.get = AsyncMock(return_value=scan)
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=FakeResult(1))
        nested = MagicMock()
        nested.__aenter__ = AsyncMock(return_value=None)
        nested.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested)
        return db

    @staticmethod
    def _scan(user, lines, parsed_total=70000, confidence="rendah", label="SUBTOTAL"):
        return SimpleNamespace(
            user_id=user.id, outcome=None, engine="rapidocr", merchant="Toko Maju", parsed_total=Decimal(parsed_total),
            confidence=confidence, total_label=label, ocr_lines=json.dumps(lines),
            feedback_at=None, final_total=None, final_date=None, final_merchant=None,
        )

    @staticmethod
    def _inserted(db, table):
        from sqlalchemy.dialects import postgresql
        out = []
        for call in db.execute.call_args_list:
            stmt = call.args[0]
            if getattr(getattr(stmt, "table", None), "name", None) == table:
                out.append(stmt.compile(dialect=postgresql.dialect()).params)
        return out

    async def test_feedback_correction_learns_label_when_payment_confirms(self):
        user = _user()
        scan = self._scan(user, ["TOKO MAJU", "SUBTOTAL 70.000", "JML BYR 77.000", "TUNAI 100.000", "KEMBALI 23.000"])
        db = self._feedback_db(scan)
        await receipt_scan.apply_feedback(user, uuid4(), db, saved=True, total=77000, merchant="Toko Maju")
        self.assertEqual(scan.outcome, "corrected")
        votes = self._inserted(db, "receipt_learn_votes")
        self.assertEqual((votes[0]["kind"], votes[0]["key"], votes[0]["value"]), ("label", "TOKOMAJU", "JML BYR"))
        self.assertEqual(votes[0]["user_id"], user.id)
        self.assertTrue(self._inserted(db, "receipt_total_labels"))
        self.assertIsNone(scan.ocr_lines)

    async def test_partial_item_correction_is_not_learned(self):
        user = _user()
        # User hanya mencatat satu item (3.500) — tidak cocok pembayaran 50.000.
        scan = self._scan(user, ["INDOMARET", "INDOMIE GORENG 3.500", "TOTAL 50.000", "TUNAI 50.000"],
                          parsed_total=50000, confidence="tinggi", label="TOTAL")
        db = self._feedback_db(scan)
        await receipt_scan.apply_feedback(user, uuid4(), db, saved=True, total=3500, merchant="Toko Maju")
        self.assertEqual(scan.outcome, "corrected")
        self.assertEqual(self._inserted(db, "receipt_learn_votes"), [])

    async def test_accepted_total_without_payment_proof_is_not_learned(self):
        user = _user()
        # "tinggi" karena rincian cocok, tapi tidak ada baris pembayaran.
        scan = self._scan(user, ["TOKO MAJU", "GULA 20.000", "JML BYR 20.000"],
                          parsed_total=20000, confidence="tinggi", label="JML BYR")
        db = self._feedback_db(scan)
        await receipt_scan.apply_feedback(user, uuid4(), db, saved=True, total=20000, merchant="Toko Maju")
        self.assertEqual(scan.outcome, "accepted")
        self.assertEqual(self._inserted(db, "receipt_learn_votes"), [])

    async def test_alias_name_is_sanitized(self):
        self.assertEqual(receipt_scan.clean_merchant_name("Indo<b>maret</b>`!"), "Indobmaretb")
        self.assertIsNone(receipt_scan.clean_merchant_name("!!"))

    async def test_feedback_ignores_other_users_scan(self):
        scan = SimpleNamespace(user_id=uuid4(), outcome=None)
        db = MagicMock(); db.get = AsyncMock(return_value=scan); db.commit = AsyncMock()
        self.assertIsNone(await receipt_scan.apply_feedback(_user(), uuid4(), db, saved=False))
        self.assertIsNone(await receipt_scan.apply_feedback(_user(), "bukan-uuid", db, saved=False))
        db.commit.assert_not_awaited()


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def incr(self, k):
        return await self.incrby(k, 1)

    async def incrby(self, k, n):
        self.d[k] = self.d.get(k, 0) + n
        return self.d[k]

    async def decr(self, k):
        return await self.incrby(k, -1)

    async def decrby(self, k, n):
        return await self.incrby(k, -n)

    async def expire(self, k, t):
        return True

    async def get(self, k):
        return self.d.get(k)

    async def aclose(self):
        pass


def _llm_settings(**kw):
    base = dict(
        RECEIPT_LLM_ENABLED=True, GROQ_API_KEY="k", RECEIPT_LLM_MODEL="m", RECEIPT_LLM_API_URL="https://x",
        RECEIPT_LLM_MONTHLY_BUDGET_IDR=1000, RECEIPT_LLM_USER_MONTHLY_BASIC=3, RECEIPT_LLM_USER_MONTHLY_PRO=10,
        RECEIPT_LLM_MAX_OUTPUT_TOKENS=400, RECEIPT_LLM_PRICE_IN_USD=0.8, RECEIPT_LLM_PRICE_OUT_USD=4.0,
        RECEIPT_LLM_USD_IDR=17500, REDIS_URL="redis://x",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _groq_ok(total=12000, prompt_tokens=2500, completion_tokens=60):
    res = MagicMock(status_code=200)
    res.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"merchant": "A", "date": None, "total": total})}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    client = AsyncMock()
    client.__aenter__.return_value.post = AsyncMock(return_value=res)
    return client


class TestLlmBudget(unittest.IsolatedAsyncioTestCase):
    async def _call(self, redis, settings, client=None, plan="basic"):
        with patch.object(receipt_llm, "get_settings", return_value=settings), \
             patch.object(receipt_llm, "_redis", return_value=redis), \
             patch.object(receipt_llm.httpx, "AsyncClient", return_value=client or _groq_ok()):
            return await receipt_llm.try_llm_fallback(b"img", "image/jpeg", "u1", plan)

    async def test_disabled_by_default(self):
        self.assertIsNone(await self._call(FakeRedis(), _llm_settings(RECEIPT_LLM_ENABLED=False)))

    async def test_success_records_actual_cost(self):
        r = FakeRedis()
        out = await self._call(r, _llm_settings())
        self.assertEqual(out["total"], 12000)
        month = receipt_llm._month_key()
        # 2500 in × $0.8/M + 60 out × $4/M = $0.00224 → Rp 39.2 → dibulatkan ke atas 40
        self.assertEqual(r.d[f"receipt_llm:cost:{month}"], 40)

    async def test_budget_cap_never_exceeded(self):
        r = FakeRedis()
        settings = _llm_settings(RECEIPT_LLM_MONTHLY_BUDGET_IDR=200, RECEIPT_LLM_USER_MONTHLY_BASIC=100)
        results = [await self._call(r, settings) for _ in range(20)]
        calls = sum(1 for x in results if x)
        spent = r.d[f"receipt_llm:cost:{receipt_llm._month_key()}"]
        self.assertLessEqual(spent, 200)
        self.assertGreater(calls, 0)
        self.assertIsNone(results[-1])  # plafon tercapai → berhenti

    async def test_user_quota(self):
        r = FakeRedis()
        results = [await self._call(r, _llm_settings(RECEIPT_LLM_MONTHLY_BUDGET_IDR=10**6)) for _ in range(4)]
        self.assertEqual([bool(x) for x in results], [True, True, True, False])

    async def test_rejected_request_refunds_quota_and_budget(self):
        r = FakeRedis()
        bad = AsyncMock()
        bad.__aenter__.return_value.post = AsyncMock(return_value=MagicMock(status_code=401))
        self.assertIsNone(await self._call(r, _llm_settings(), client=bad))
        month = receipt_llm._month_key()
        self.assertEqual(r.d[f"receipt_llm:cost:{month}"], 0)
        self.assertEqual(r.d[f"receipt_llm:user:u1:{month}"], 0)

    async def test_timeout_keeps_reservation(self):
        # Request mungkin sudah diproses & ditagih → reservasi tidak dikembalikan.
        r = FakeRedis()
        slow = AsyncMock()
        slow.__aenter__.return_value.post = AsyncMock(side_effect=receipt_llm.httpx.ReadTimeout("lambat"))
        self.assertIsNone(await self._call(r, _llm_settings(), client=slow))
        self.assertEqual(r.d[f"receipt_llm:cost:{receipt_llm._month_key()}"], receipt_llm.worst_case_cost_idr())

    async def test_repeated_timeouts_still_capped(self):
        r = FakeRedis()
        slow = AsyncMock()
        slow.__aenter__.return_value.post = AsyncMock(side_effect=receipt_llm.httpx.ReadTimeout("lambat"))
        settings = _llm_settings(RECEIPT_LLM_MONTHLY_BUDGET_IDR=300, RECEIPT_LLM_USER_MONTHLY_BASIC=100)
        for _ in range(20):
            await self._call(r, settings, client=slow)
        self.assertLessEqual(r.d[f"receipt_llm:cost:{receipt_llm._month_key()}"], 300)

    def test_parse_reply_strips_thinking_and_rejects_garbage(self):
        self.assertEqual(receipt_llm._parse_reply('<think>hmm</think>{"total":"Rp 9.200","merchant":null,"date":null}')["total"], 9200)
        self.assertIsNone(receipt_llm._parse_reply("bukan json"))
        far = receipt_llm._parse_reply('{"total": 9200, "merchant": "A", "date": "2001-01-01"}')
        self.assertIsNone(far["date"])  # tanggal di luar jendela 1 tahun ditolak


class TestUploadValidation(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_image_and_oversize(self):
        from app.api.routes.transactions import MAX_RECEIPT_BYTES, _read_receipt_upload

        class Up:
            def __init__(self, data, ct):
                self.data, self.content_type = data, ct

            async def read(self, n=-1):
                return self.data[:n] if n > 0 else self.data

        with self.assertRaises(HTTPException) as ctx:
            await _read_receipt_upload(Up(b"x", "application/pdf"))
        self.assertEqual(ctx.exception.status_code, 415)
        with self.assertRaises(HTTPException) as ctx:
            await _read_receipt_upload(Up(b"x" * (MAX_RECEIPT_BYTES + 5), "image/jpeg"))
        self.assertEqual(ctx.exception.status_code, 413)
        data, ct = await _read_receipt_upload(Up(b"jpg", "image/jpeg; charset=x"))
        self.assertEqual((data, ct), (b"jpg", "image/jpeg"))



class TestBotItemsSummary(unittest.TestCase):
    def test_summary_cocok_and_selisih(self):
        from app.bot.receipt_cmd import _items_summary, MAX_ITEM_LINES
        ok = _items_summary({
            "items": [{"name": "SOKLN SOFTR ROSY 720", "amount": 18900, "discount": 3000, "flag": "ok"}],
            "adjustments": [{"label": "VC PL", "amount": 5900, "kind": "discount"}],
            "reconciliation": {"status": "cocok", "diff": 0},
        })
        self.assertIn("cocok dengan total", ok)
        self.assertIn("voucher −Rp 3.000", ok)
        self.assertIn("VC PL  −Rp 5.900", ok)
        self.assertNotIn("webapp", ok)
        many = [{"name": f"BARANG {i}", "amount": 1000, "flag": "ok"} for i in range(MAX_ITEM_LINES + 3)]
        many[0].update(flag="cek", suggestion=1900)
        bad = _items_summary({"items": many, "reconciliation": {"status": "selisih", "diff": -900}})
        self.assertIn("lebih Rp 900", bad)
        self.assertIn("mungkin Rp 1.900?", bad)
        self.assertIn("+3 barang lagi", bad)
        self.assertIn("webapp", bad)
        self.assertEqual(_items_summary({"items": []}), "")


class TestBotReceipt(unittest.IsolatedAsyncioTestCase):
    async def test_photo_flow_offers_suggested_envelope_first_and_keeps_date(self):
        from app.bot import receipt_cmd

        env_a = SimpleNamespace(id=uuid4(), name="Makan", emoji="🍜", purpose="expense")
        env_b = SimpleNamespace(id=uuid4(), name="Belanja Harian", emoji="🛒", purpose="expense")
        env_save = SimpleNamespace(id=uuid4(), name="Tabungan", emoji="🐷", purpose="saving")
        status_msg = MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
        tg_file = MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"jpg")))
        photo = MagicMock(get_file=AsyncMock(return_value=tg_file))
        message = MagicMock(photo=[photo], document=None, reply_text=AsyncMock(return_value=status_msg))
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42, first_name="A"))
        scan = {"scan_id": "abc", "merchant": "Indomaret", "date": "2026-10-14", "total": 51000,
                "confidence": "tinggi", "quota": {"limit": 15, "used": 2, "remaining": 13}}
        redis = MagicMock(set=AsyncMock(), aclose=AsyncMock())

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=MagicMock())
        session.__aexit__ = AsyncMock(return_value=False)
        with patch.object(receipt_cmd, "_rate_limited", AsyncMock(return_value=False)), \
             patch.object(receipt_cmd, "AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.get_or_create_user", AsyncMock(return_value=_user())), \
             patch("app.bot.handlers._is_setup_complete", AsyncMock(return_value=(True, ""))), \
             patch("app.bot.handlers.get_household_id", AsyncMock(return_value=uuid4())), \
             patch("app.bot.handlers.get_envelopes_with_spent", AsyncMock(return_value=[
                 {"envelope": env_a}, {"envelope": env_save}, {"envelope": env_b}])), \
             patch("app.services.receipt_scan.scan_receipt", AsyncMock(return_value=scan)), \
             patch("app.services.txn_nlp.find_best_envelope", AsyncMock(return_value=(env_b, True))), \
             patch("redis.asyncio.from_url", return_value=redis):
            await receipt_cmd.handle_receipt_photo(update, None)

        text = status_msg.edit_text.call_args[0][0]
        self.assertIn("Indomaret", text)
        self.assertIn("Rp 51.000", text)
        self.assertIn("13/15", text)
        rows = status_msg.edit_text.call_args[1]["reply_markup"].inline_keyboard
        self.assertTrue(rows[0][0].text.startswith("⭐"))       # saran amplop di atas
        self.assertNotIn("Tabungan", " ".join(r[0].text for r in rows))  # amplop tabungan disembunyikan
        stored = json.loads(redis.set.call_args[0][1])
        self.assertEqual((stored["date"], stored["scan_id"], stored["amount"]), ("2026-10-14", "abc", 51000))

if __name__ == "__main__":
    unittest.main()
