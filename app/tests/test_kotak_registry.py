import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, re, unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.services.kotak_struk import checks as checks_module
from app.services.kotak_struk import registry
from app.services.kotak_struk.config import READER_THRESHOLD
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers import labels as L
from app.services.kotak_struk.readers.base import Check, Parsed, ParseContext, Secrets
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.proof_common import (
    clean_lines, has_header_status_title, looks_like_store_receipt, read_header_status,
)
from app.services.kotak_struk.readers.struk_belanja import StrukBelanjaReader, parsed_from_receipt
from app.services.kotak_struk.readers.unknown import UnknownReader
from app.services.kotak_struk.registry import looks_like_proof, read_document
from app.services.receipt_parser import ReceiptAdjustment, ReceiptItem, ReceiptParse, merchant_key, parse_receipt

FIX = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())
CTX = ParseContext(today=date(2026, 10, 15))
LLM_LOGGER = "app.services.kotak_struk.readers.struk_belanja"
# Struk berbentuk struk tapi tanpa baris TOTAL: parse_receipt menilainya `rendah`.
LOW_RECEIPT = ["TOKO MAJU", "ROTI 10.000", "SUSU 5.000", "SUBTOTAL 15.000"]


def doc(lines, kind="image"):
    return TextDoc(lines=lines, kind=kind)


def llm_ctx(llm, **kw):
    return ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg", llm=llm, **kw)


class LabelTests(unittest.TestCase):
    def test_value_same_line_or_next_line(self):
        lines = ["Merchant", "SITI AMINAH", "Nominal: Rp 25.000"]
        self.assertEqual(L.find_value(lines, ["merchant"]), "SITI AMINAH")
        self.assertEqual(L.find_amount(lines, ["nominal", "jumlah"]), 25000)

    def test_datetime_formats(self):
        for text, expect in [("26 Okt 2026 08:12:33 WIB", (2026, 10, 26, 8, 12)),
                             ("26 Oktober 2026, 08.12", (2026, 10, 26, 8, 12)),
                             ("26/10/2026 08:12", (2026, 10, 26, 8, 12)),
                             ("Oct 26, 2026 08:12 PM", (2026, 10, 26, 20, 12)),
                             ("2026-10-26", (2026, 10, 26, 0, 0))]:
            with self.subTest(text):
                d = L.parse_datetime_id(text)
                self.assertEqual((d.year, d.month, d.day, d.hour, d.minute), expect)
                self.assertEqual(d.utcoffset().total_seconds(), 7 * 3600)

    def test_more_datetime_formats(self):
        for text, expect in [("26-10-2026", (2026, 10, 26, 0, 0, 0)),
                             ("2026-10-26 08:12:33", (2026, 10, 26, 8, 12, 33)),
                             ("Tanggal 26 Agustus 2026 19.05 WIB", (2026, 8, 26, 19, 5, 0)),
                             ("26 Mei 2026", (2026, 5, 26, 0, 0, 0)),
                             ("26 May 2026 08:12 AM", (2026, 5, 26, 8, 12, 0)),
                             ("Dec 1, 2026 12:30 AM", (2026, 12, 1, 0, 30, 0)),
                             ("Dec 1, 2026 12:30 PM", (2026, 12, 1, 12, 30, 0)),
                             ("26.10.2026 08.12.33", (2026, 10, 26, 8, 12, 33))]:
            with self.subTest(text):
                d = L.parse_datetime_id(text)
                self.assertEqual((d.year, d.month, d.day, d.hour, d.minute, d.second), expect)

    def test_datetime_unreadable_is_none(self):
        for text in ["", "Rp 25.000", "31/02/2026 08:12", "26 Foo 2026", "No. Ref 2026102612345678"]:
            with self.subTest(text):
                self.assertIsNone(L.parse_datetime_id(text))

    def test_find_datetime_takes_first_readable_line(self):
        lines = ["Transfer Berhasil", "26 Okt 2026, 09:30 WIB", "27/10/2026 10:00"]
        self.assertEqual(L.find_datetime(lines), datetime.fromisoformat("2026-10-26T09:30:00+07:00"))
        self.assertIsNone(L.find_datetime(["Transfer Berhasil", "Rp 1.000"]))

    def test_find_value_label_rules(self):
        lines = ["MERCHANT : Warung Bakso", "Keterangan bayar arisan", "Ke", "", "Kota: SEMARANG"]
        self.assertEqual(L.find_value(lines, ["merchant"]), "Warung Bakso")   # huruf besar, titik dua
        self.assertEqual(L.find_value(lines, ["ke"]), None)                    # "Keterangan" bukan label "ke"; nilai di bawah kosong
        self.assertEqual(L.find_value(lines, ["keterangan"]), "bayar arisan")
        self.assertEqual(L.find_value(lines, ["kota"]), "SEMARANG")
        self.assertIsNone(L.find_value(lines, ["nmid"]))

    def test_find_value_prefers_earlier_synonym_and_longest_label(self):
        lines = ["Total Rp152.500", "Jumlah Pembayaran Rp15.000", "Nominal Rp150.000"]
        self.assertEqual(L.find_amount(lines, ["nominal", "total"]), 150000)       # urutan sinonim = prioritas
        self.assertEqual(L.find_value(lines, ["jumlah", "jumlah pembayaran"]), "Rp15.000")
        self.assertEqual(L.find_amount(lines, ["jumlah pembayaran"]), 15000)

    def test_find_value_label_on_last_line_has_no_next_line(self):
        self.assertIsNone(L.find_value(["Nominal"], ["nominal"]))
        self.assertIsNone(L.find_amount(["Nominal", "bukan angka"], ["nominal"]))

    def test_find_amount_formats(self):
        for text, expect in [("Nominal Rp25.000", 25000), ("Nominal Rp 25.000,00", 25000),
                             ("Nominal IDR 25,000.00", 25000), ("Nominal: 25000", 25000)]:
            with self.subTest(text):
                self.assertEqual(L.find_amount([text], ["nominal"]), expect)

    def test_count_markers_whole_words_unique(self):
        lines = ["Pembayaran QRIS Berhasil", "NMID ID123", "qris lagi", "Merchant PAN 1234", "BI-FAST", "Transfers"]
        self.assertEqual(L.count_markers(lines, ["qris", "nmid", "merchant pan", "terminal id"]), 3)
        self.assertEqual(L.count_markers(lines, ["bi-fast", "transfer"]), 1)  # "Transfers" bukan kata "transfer"
        self.assertEqual(L.count_markers([], ["qris"]), 0)


class StrukBelanjaReaderTests(unittest.IsolatedAsyncioTestCase):
    def test_detect_scores(self):
        r = StrukBelanjaReader()
        full = FIX["receipts"][0]["lines"]
        cases = [(full, 0.9),
                 (["TOKO", "TOTAL 10.000", "x"], 0.6),            # hanya baris total
                 (LOW_RECEIPT, 0.6),                              # hanya barang, tanpa baris total kuat
                 (["foto buram", "Rp 12.000", "Rp 2.000"], 0.2),  # nominal tanpa nama barang
                 (["foto buram"], 0.2),
                 ([], 0.2)]
        for lines, expect in cases:
            with self.subTest(lines[:3]):
                self.assertEqual(r.detect(doc(lines)), expect)
        self.assertGreaterEqual(r.detect(doc(LOW_RECEIPT)), READER_THRESHOLD)
        self.assertLess(r.detect(doc(["foto buram"])), READER_THRESHOLD)

    def test_detect_total_labels(self):
        r = StrukBelanjaReader()
        items = ["ROTI 10.000", "SUSU 5.000"]
        for label, expect in [("TOTAL 15.000", 0.9), ("Grand Total 15.000", 0.9), ("TOTAL BELANJA : 15,000", 0.9),
                              ("T0TAL BAYAR 15.000", 0.9),          # salah baca OCR yang dinormalkan parser
                              ("TOTAL ITEM 2", 0.6), ("TOTAL QTY 2", 0.6), ("SUB TOTAL 15.000", 0.6)]:
            with self.subTest(label):
                self.assertEqual(r.detect(doc(items + [label])), expect)

    def test_name_and_type(self):
        r = StrukBelanjaReader()
        self.assertEqual((r.doc_type, r.name), ("struk_belanja", "struk_belanja"))

    async def test_mapping_of_store_receipt(self):
        rec = FIX["receipts"][0]
        parsed = await StrukBelanjaReader().parse(doc(rec["lines"]), CTX)
        d = parsed.doc
        self.assertEqual((d.doc_type, d.method, d.flow, d.status), ("struk_belanja", "lainnya", "keluar", "berhasil"))
        self.assertEqual((d.amounts.total, d.counterparty.name), (rec["expect"]["total"], rec["expect"]["merchant"]))
        self.assertEqual(d.confidence["total"], "tinggi")
        items = [l for l in d.lines if l.kind == "item"]
        self.assertEqual(len(items), 8)
        self.assertEqual([l.kind for l in d.lines if l.kind != "item"], [])   # voucher menempel di barang, bukan baris sendiri
        self.assertEqual((items[4].name, items[4].amount, items[4].qty, items[4].unit_price, items[4].flag),
                         ("SOKLN SOFTR ROSY 720", 18900, 1.0, 18900, "ok"))
        self.assertEqual(parsed.extra["item_discounts"], [0, 0, 0, 0, 3000, 1000, 0, 5000])
        self.assertEqual(parsed.extra["adjustments"], [])
        self.assertEqual(parsed.extra["engine"], "rapidocr")
        self.assertEqual(parsed.extra["merchant_key"], "INDOMARET")
        self.assertEqual(parsed.extra["total_label"], "TOTAL BELANJA")
        self.assertEqual(parsed.extra["confidence_source"], "payment")
        self.assertEqual(parsed.extra["reconciliation"]["status"], "cocok")
        self.assertEqual(parsed.secrets, Secrets())

    async def test_items_and_adjustments_become_lines(self):
        lines = ["TOKO SERBA ADA", "ROTI 2 x 5.000 10.000", "SUSU 1 x 20.000 20.000", "DISKON 3.000", "PPN 11% 2.000",
                 "TOTAL 29.000", "TUNAI 30.000", "KEMBALI 1.000"]
        res = await read_document(doc(lines), CTX, proofs_enabled=False)
        d = res.parsed.doc
        self.assertEqual([(l.kind, l.name, l.amount, l.qty, l.unit_price) for l in d.lines],
                         [("item", "ROTI", 10000, 2.0, 5000), ("item", "SUSU", 20000, 1.0, 20000), ("tax", "PPN 11%", 2000, None, None)])
        self.assertEqual(res.parsed.extra["item_discounts"], [0, 3000])
        self.assertEqual(res.parsed.extra["adjustments"], [{"label": "PPN 11%", "amount": 2000, "kind": "charge"}])
        self.assertEqual(res.parsed.extra["reconciliation"],
                         {"items_total": 30000, "discounts": 3000, "charges": 2000, "expected": 29000, "diff": 0, "status": "cocok", "note": None})
        self.assertEqual(d.amounts.total, 29000)

    async def test_global_discount_becomes_discount_line(self):
        res = await read_document(doc(FIX["receipts"][2]["lines"]), CTX, proofs_enabled=False)
        self.assertEqual([(l.kind, l.name, l.amount) for l in res.parsed.doc.lines if l.kind != "item"],
                         [("discount", "VC PL", 5900), ("discount", "VC INDOMARCO PRI", 22900)])
        self.assertEqual([a["kind"] for a in res.parsed.extra["adjustments"]], ["discount", "discount"])

    async def test_normalized_ocr_lines_are_kept_for_learning(self):
        # Pembelajaran umpan balik (payment_amounts, find_label_for_amount) memakai baris yang SUDAH
        # dinormalkan parse_receipt, seperti kolom ocr_lines pada scan_receipt lama.
        raw = ["TOKO MAJU", "  T0TAL   15.000 ", "", "ROTI  10.000", "SUSU 5.000"]
        normalized = ["TOKO MAJU", "TOTAL 15.000", "ROTI 10.000", "SUSU 5.000"]
        self.assertEqual(parse_receipt(raw, CTX.today).lines, normalized)       # asumsi tes: normalisasi mengubah baris
        parsed = await StrukBelanjaReader().parse(doc(raw), CTX)
        self.assertEqual(parsed.extra["ocr_lines"], normalized)
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        parsed = await StrukBelanjaReader().parse(doc(LOW_RECEIPT), llm_ctx(llm))   # jalur LLM: baris OCR tetap yang dinormalkan
        self.assertEqual(parsed.extra["ocr_lines"], parse_receipt(LOW_RECEIPT, CTX.today).lines)
        # Penyelamatan LLM lewat UnknownReader: tidak ada parse yang berjalan, jadi baris mentah dokumen.
        parsed = await UnknownReader().parse(doc(["  foto  buram "]), llm_ctx(llm))
        self.assertEqual((parsed.doc.doc_type, parsed.extra["ocr_lines"]), ("struk_belanja", ["  foto  buram "]))
        self.assertIsInstance(parsed.extra["ocr_lines"], list)

    async def test_date_becomes_midnight_wib(self):
        lines = FIX["receipts"][0]["lines"]
        ctx = ParseContext(today=date(2025, 5, 25))
        parsed = await StrukBelanjaReader().parse(doc(lines), ctx)
        self.assertEqual(parsed.doc.paid_at, datetime.fromisoformat("2025-05-24T00:00:00+07:00"))
        self.assertEqual(parsed.doc.paid_at.utcoffset().total_seconds(), 7 * 3600)

    async def test_learned_aliases_and_profiles_are_passed_through(self):
        with patch("app.services.kotak_struk.readers.struk_belanja.parse_receipt", wraps=parse_receipt) as pr:
            ctx = ParseContext(today=date(2026, 10, 15), merchant_aliases={"TOKOX": "Toko X"}, merchant_profiles={"TOKOX": ["TOTAL"]})
            await StrukBelanjaReader().parse(doc(LOW_RECEIPT), ctx)
        self.assertEqual(pr.call_args.kwargs["merchant_aliases"], {"TOKOX": "Toko X"})
        self.assertEqual(pr.call_args.kwargs["merchant_profiles"], {"TOKOX": ["TOTAL"]})

    async def test_no_llm_call_when_confidence_is_good(self):
        llm = AsyncMock(return_value={"merchant": "X", "date": None, "total": 1})
        await StrukBelanjaReader().parse(doc(FIX["receipts"][0]["lines"]), llm_ctx(llm))
        llm.assert_not_called()

    async def test_no_llm_call_without_image_or_llm(self):
        llm = AsyncMock(return_value={"merchant": "X", "date": None, "total": 1})
        for ctx in (ParseContext(today=date(2026, 10, 15), llm=llm),                        # tanpa gambar
                    ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg")):  # tanpa llm
            parsed = await StrukBelanjaReader().parse(doc(LOW_RECEIPT), ctx)
            self.assertEqual((parsed.doc.amounts.total, parsed.extra["engine"]), (15000, "rapidocr"))
        llm.assert_not_called()

    async def test_llm_overrides_low_confidence_total(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": date(2026, 10, 14), "total": 12000})
        parsed = await StrukBelanjaReader().parse(doc(LOW_RECEIPT), llm_ctx(llm, user_id="u1", plan="pro"))
        llm.assert_awaited_once_with(b"img", "image/jpeg", "u1", "pro")
        d = parsed.doc
        self.assertEqual((d.amounts.total, d.counterparty.name, d.confidence["total"]), (12000, "Toko A", "sedang"))
        self.assertEqual(d.paid_at, datetime.fromisoformat("2026-10-14T00:00:00+07:00"))
        self.assertIn("Dibaca ulang dengan AI cadangan", d.evidence)
        self.assertEqual((parsed.extra["engine"], parsed.extra["confidence_source"]), ("llm", "llm"))
        self.assertEqual(parsed.extra["merchant_key"], merchant_key("Toko A"))
        self.assertEqual(parsed.extra["reconciliation"]["status"], "selisih")   # rincian 15.000 vs total AI 12.000
        self.assertEqual(len([l for l in d.lines if l.kind == "item"]), 2)      # rincian OCR tetap ada

    async def test_llm_keeps_ocr_merchant_and_date_when_it_returns_none(self):
        llm = AsyncMock(return_value={"merchant": None, "date": None, "total": 12000})
        parsed = await StrukBelanjaReader().parse(doc(LOW_RECEIPT), llm_ctx(llm))
        self.assertEqual(parsed.doc.counterparty.name, "Toko Maju")

    async def test_llm_failures_keep_ocr_result(self):
        for name, llm in [("none", AsyncMock(return_value=None)),
                          ("tanpa total", AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": None}))]:
            with self.subTest(name):
                await self.assert_ocr_result_kept(llm)
        llm = AsyncMock(side_effect=RuntimeError("boom"))
        with self.assertLogs(LLM_LOGGER, "WARNING") as logs:
            await self.assert_ocr_result_kept(llm)
        self.assertIn("fallback LLM gagal: boom", logs.output[0])

    async def assert_ocr_result_kept(self, llm):
        parsed = await StrukBelanjaReader().parse(doc(LOW_RECEIPT), llm_ctx(llm))
        self.assertEqual((parsed.doc.amounts.total, parsed.extra["engine"], parsed.doc.confidence["total"]),
                         (15000, "rapidocr", "rendah"))
        self.assertEqual(parsed.doc.counterparty.name, "Toko Maju")
        llm.assert_awaited_once()

    def test_llm_reset_of_flagged_items_and_reconcile_again(self):
        flagged = ReceiptItem(name="ROTI", amount=10000, flag="cek", note="harga janggal", suggestion=1000)
        fine = ReceiptItem(name="SUSU", amount=5000, flag="auto", note="dikoreksi")
        rp = ReceiptParse(merchant="Toko", date=None, total=None, confidence="gagal",
                          items=[flagged, fine], adjustments=[ReceiptAdjustment("DISKON", 1000, "discount")])
        parsed = parsed_from_receipt(rp, {"merchant": None, "date": None, "total": 14000})
        self.assertEqual((flagged.flag, flagged.note, flagged.suggestion), ("ok", None, None))
        self.assertEqual((fine.flag, fine.note), ("auto", "dikoreksi"))   # hanya tanda "cek" yang direset
        self.assertEqual(parsed.extra["reconciliation"]["status"], "cocok")  # 15.000 - 1.000 = 14.000
        self.assertEqual([(l.flag, l.note, l.suggestion) for l in parsed.doc.lines if l.kind == "item"],
                         [("ok", None, None), ("auto", "dikoreksi", None)])

    def test_checks_is_empty(self):
        self.assertEqual(StrukBelanjaReader().checks(Parsed(doc=None), CTX), [])


class UnknownReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_type_detect(self):
        r = UnknownReader()
        self.assertEqual((r.doc_type, r.name, r.detect(doc(FIX["receipts"][0]["lines"]))), ("tidak_dikenali", "tidak_dikenali", 0.0))

    async def test_largest_rp_amount_only_from_rp_lines(self):
        parsed = await UnknownReader().parse(doc(["No 123456", "5.000.000", "bayar rp12.000", "IDR 2,500.00", "Rp 2.000"]), CTX)
        self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total, parsed.doc.confidence["total"]),
                         ("tidak_dikenali", 12000, "rendah"))

    async def test_no_amount_means_no_total(self):
        for lines in (["foto buram"], ["halo apa kabar", "tidak ada nominal"]):
            with self.subTest(lines):
                parsed = await UnknownReader().parse(doc(lines), CTX)
                self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total, parsed.doc.confidence),
                                 ("tidak_dikenali", None, {}))
                self.assertEqual((parsed.doc.status, parsed.doc.flow, parsed.doc.lines),
                                 ("tidak_diketahui", "tidak_diketahui", []))
                self.assertEqual(parsed.extra, {})

    async def test_no_rp_amount_falls_back_to_the_legacy_receipt_guess_as_an_unknown_document(self):
        """Tanpa baris "Rp"/"IDR", pembaca ini menebak seperti scan struk lama (`parse_receipt`): total, tanggal,
        nama merchant. Tetap `tidak_dikenali` (spec 6a: nominal berkeyakinan rendah, isi manual): sekali-catat,
        tanpa rincian barang, tanpa data belajar struk, selalu `rendah`."""
        parsed = await UnknownReader().parse(doc(["TOKO", "14-10-2026 08:15", "45.500"]), CTX)
        d = parsed.doc
        self.assertEqual((d.doc_type, d.counterparty.name, d.amounts.total, d.confidence), ("tidak_dikenali", "Toko", 45500, {"total": "rendah"}))
        self.assertEqual(d.paid_at, datetime.fromisoformat("2026-10-14T00:00:00+07:00"))
        self.assertEqual((d.status, d.flow, d.lines), ("tidak_diketahui", "tidak_diketahui", []))
        self.assertEqual(d.evidence, ["Jenis bukti tidak dikenali", "Total ditebak dari teks tanpa baris Rp"])
        self.assertEqual(parsed.extra, {})   # tanpa ocr_lines/merchant_key/total_label: itu data belajar struk belanja

    async def test_the_guess_is_never_more_confident_than_low(self):
        lines = ["ALFAMART", "ROTI 15.000", "SUSU 30.400", "TOTAL BELANJA 45.400", "TUNAI 50.000", "KEMBALI 4.600"]
        self.assertEqual(parse_receipt(lines, CTX.today).confidence, "tinggi")   # tanpa "Rp": pembaca ini memakainya
        parsed = await UnknownReader().parse(doc(lines), CTX)
        self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total, parsed.doc.confidence),
                         ("tidak_dikenali", 45400, {"total": "rendah"}))
        self.assertEqual((parsed.doc.lines, parsed.extra), ([], {}))   # barang tidak ikut: hanya total, tanggal, nama

    async def test_the_guess_carries_no_digits_from_the_text_into_the_document(self):
        """Nomor rekening/telepon di teks tidak boleh masuk Dokumen Bayar: baris rincian ("Rek BCA 1234567890" terbaca
        sebagai barang), bukti (kutipan baris di `evidence`), maupun nama merchant tebakan."""
        for lines in (["Rek BCA 1234567890", "a.n. BUDI", "150.000"],
                      ["Rek BCA 1234567890", "150.000"],
                      ["Toko Sembako Berkah Makmur 081234567", "45.500"],
                      ["Toko Maju 0812 3456 7890", "45.500"]):
            with self.subTest(lines):
                parsed = await UnknownReader().parse(doc(lines), CTX)
                self.assertEqual(parsed.doc.doc_type, "tidak_dikenali")
                self.assertIsNotNone(parsed.doc.amounts.total)
                blob = json.dumps(parsed.doc.to_json(), default=str)
                self.assertFalse(re.search(r"\d{8}|\d{4}[ -]\d{4}", blob), blob)
        named = await UnknownReader().parse(doc(["Rek BCA 1234567890", "a.n. BUDI", "150.000"]), CTX)
        self.assertEqual((named.doc.counterparty.name, named.doc.amounts.total), ("A.N. Budi", 150000))   # nama saja
        digit_heavy = await UnknownReader().parse(doc(["Toko Sembako Berkah Makmur 081234567", "45.500"]), CTX)
        self.assertIsNone(digit_heavy.doc.counterparty.name)   # nama berisi deret digit sepanjang rekening: dibuang
        short = await UnknownReader().parse(doc(["Warung Bu Tini 24 Jam", "14-10-2026", "45.500"]), CTX)
        self.assertEqual(short.doc.counterparty.name, "Warung Bu Tini 24 Jam")   # angka pendek di nama tetap boleh

    async def test_rp_amount_keeps_the_legacy_date(self):
        """H3: bukti QRIS Jago Syariah yang tidak dikenali (ID transaksi bukan nominal lagi) tetap membawa tanggal
        tebakan scan struk lama, supaya pertanyaan tanggal periode lalu (H1) tetap muncul; nominalnya dari baris Rp.
        Nama tebakan tidak dibawa (judul/label seperti "Foto Buram")."""
        lines = ["Jago Syariah", "RM AJO PIAMAN", "Rp19.000", "ID Transaksi", "2610264RL9-PVRERW",
                 "Tanggal & waktu transaksi", "26 Okt 2026, 18:52 WIB", "Status", "Sukses", "ID Terminal", "A01"]
        for flag in (False, True):
            with self.subTest(proofs_enabled=flag):
                res = await read_document(doc(lines), ParseContext(today=date(2026, 10, 28)), proofs_enabled=flag)
                d = res.parsed.doc
                self.assertEqual((res.reader, d.doc_type, d.amounts.total, d.confidence, d.counterparty.name),
                                 ("tidak_dikenali", "tidak_dikenali", 19000, {"total": "rendah"}, None))
                self.assertEqual(d.paid_at, datetime.fromisoformat("2026-10-26T00:00:00+07:00"))
                self.assertEqual(d.evidence, ["Jenis bukti tidak dikenali", "Total ditebak dari nominal Rp terbesar"])
        blurry = await UnknownReader().parse(doc(["foto buram", "14-10-2026", "Rp 12.000"]), CTX)
        self.assertEqual((blurry.doc.counterparty.name, blurry.doc.amounts.total), (None, 12000))
        self.assertEqual(blurry.doc.paid_at, datetime.fromisoformat("2026-10-14T00:00:00+07:00"))
        self.assertEqual(blurry.extra, {})

    async def test_an_rp_line_still_wins_over_the_guess_and_the_llm_over_both(self):
        parsed = await UnknownReader().parse(doc(["TOKO", "45.500", "bayar rp12.000"]), CTX)
        self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total), ("tidak_dikenali", 12000))
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 9000})
        parsed = await UnknownReader().parse(doc(["TOKO", "45.500"]), llm_ctx(llm))
        self.assertEqual((parsed.doc.amounts.total, parsed.extra["engine"]), (9000, "llm"))

    async def test_the_guess_reaches_read_document_for_text_no_reader_claims(self):
        res = await read_document(doc(["TOKO", "45.500"]), CTX, proofs_enabled=False)
        self.assertEqual((res.reader, res.parsed.doc.doc_type, res.parsed.doc.amounts.total),
                         ("tidak_dikenali", "tidak_dikenali", 45500))

    async def test_llm_rescues_unreadable_photo(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": date(2026, 10, 14), "total": 12000})
        ctx = llm_ctx(llm, user_id="u1", plan="basic")
        parsed = await UnknownReader().parse(doc(["foto buram"]), ctx)
        llm.assert_awaited_once_with(b"img", "image/jpeg", "u1", "basic")
        d = parsed.doc
        self.assertEqual((d.doc_type, d.counterparty.name, d.amounts.total, d.confidence["total"]),
                         ("struk_belanja", "Toko A", 12000, "sedang"))
        self.assertEqual((d.method, d.flow, d.status), ("lainnya", "keluar", "berhasil"))
        self.assertEqual(d.paid_at, datetime.fromisoformat("2026-10-14T00:00:00+07:00"))
        self.assertEqual((parsed.extra["engine"], parsed.extra["confidence_source"]), ("llm", "llm"))
        self.assertEqual(parsed.extra["merchant_key"], merchant_key("Toko A"))
        self.assertIn("Dibaca ulang dengan AI cadangan", d.evidence)
        self.assertEqual(d.lines, [])

    async def test_no_llm_call_without_ctx_llm_or_image(self):
        llm = AsyncMock(return_value={"merchant": "X", "date": None, "total": 1})
        for ctx in (CTX,                                                       # tidak ada keduanya
                    ParseContext(today=date(2026, 10, 15), llm=llm),           # llm tanpa gambar (mis. PDF/teks)
                    ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg")):
            parsed = await UnknownReader().parse(doc(["foto buram", "Rp 12.000"]), ctx)
            self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total), ("tidak_dikenali", 12000))
        llm.assert_not_called()

    async def test_llm_failures_fall_back_to_normal_result(self):
        for name, llm in [("none", AsyncMock(return_value=None)),
                          ("tanpa total", AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": None}))]:
            with self.subTest(name):
                await self.assert_normal_result(llm)
        with self.assertLogs(LLM_LOGGER, "WARNING"):
            await self.assert_normal_result(AsyncMock(side_effect=RuntimeError("boom")))

    async def assert_normal_result(self, llm):
        parsed = await UnknownReader().parse(doc(["foto buram", "Rp 12.000"]), llm_ctx(llm))
        self.assertEqual((parsed.doc.doc_type, parsed.doc.amounts.total, parsed.doc.confidence["total"]),
                         ("tidak_dikenali", 12000, "rendah"))
        self.assertEqual(parsed.extra, {})
        llm.assert_awaited_once()

    def test_checks_is_empty(self):
        self.assertEqual(UnknownReader().checks(Parsed(doc=None), CTX), [])


class FakeReader:
    def __init__(self, name, doc_type, score):
        self.name, self.doc_type, self.score = name, doc_type, score
        self.parsed = 0

    def detect(self, d):
        return self.score

    async def parse(self, d, ctx):
        from app.services.kotak_struk.document import DokumenBayar
        self.parsed += 1
        return Parsed(doc=DokumenBayar(doc_type=self.doc_type))

    def checks(self, parsed, ctx):
        return [Check("dari_pembaca", "warn", "pesan pembaca")]


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(registry, "_PROOF_READERS", [])
        self.proofs = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_store_receipts_read_by_struk_belanja_same_as_before(self):
        for rec in FIX["receipts"][:3]:
            with self.subTest(rec["id"]):
                res = await read_document(TextDoc(lines=rec["lines"], kind="image"), CTX, proofs_enabled=True)
                self.assertEqual((res.reader, res.parsed.doc.doc_type), ("struk_belanja", "struk_belanja"))
                self.assertEqual(res.parsed.doc.amounts.total, rec["expect"]["total"])
                self.assertEqual(res.parsed.doc.counterparty.name, rec["expect"]["merchant"])
                self.assertTrue(all(l.kind == "item" for l in res.parsed.doc.lines if l.kind == "item"))

    async def test_unreadable_goes_to_unknown_with_largest_rp(self):
        res = await read_document(TextDoc(lines=["foto buram", "Rp 12.000", "Rp 2.000"], kind="image"), CTX, proofs_enabled=True)
        self.assertEqual((res.reader, res.parsed.doc.amounts.total, res.parsed.doc.confidence["total"]), ("tidak_dikenali", 12000, "rendah"))

    async def test_llm_fallback_kept_for_low_confidence_receipt(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        ctx = ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg", llm=llm)
        res = await read_document(TextDoc(lines=LOW_RECEIPT, kind="image"), ctx, proofs_enabled=False)
        self.assertEqual(res.reader, "struk_belanja")
        self.assertEqual((res.parsed.doc.amounts.total, res.parsed.extra["engine"]), (12000, "llm"))
        llm.assert_awaited_once()

    async def test_unreadable_photo_still_tries_llm_via_unknown_reader(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        ctx = ParseContext(today=date(2026, 10, 15), image=b"img", content_type="image/jpeg", llm=llm)
        res = await read_document(TextDoc(lines=["foto buram"], kind="image"), ctx, proofs_enabled=True)
        self.assertEqual((res.reader, res.parsed.doc.doc_type, res.parsed.doc.amounts.total, res.parsed.extra["engine"]),
                         ("tidak_dikenali", "struk_belanja", 12000, "llm"))
        llm.assert_awaited_once()

    async def test_no_llm_without_image_or_llm_in_context(self):
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        ctx = ParseContext(today=date(2026, 10, 15), llm=llm)       # teks/PDF: tidak ada gambar
        res = await read_document(TextDoc(lines=["foto buram"], kind="text"), ctx, proofs_enabled=True)
        self.assertEqual(res.reader, "tidak_dikenali")
        llm.assert_not_called()

    def test_readers_for(self):
        self.assertEqual([r.name for r in registry.readers_for(False)], ["struk_belanja"])
        self.assertEqual([r.name for r in registry.readers_for(True)], ["struk_belanja"])  # belum ada bukti terdaftar
        qris, transfer = FakeReader("qris.umum", "qris", 0.9), FakeReader("transfer.umum", "transfer", 0.9)
        registry.register_proof_reader(qris)
        registry.register_proof_reader(transfer)
        self.assertEqual([r.name for r in registry.readers_for(True)], ["qris.umum", "transfer.umum", "struk_belanja"])
        self.assertEqual([r.name for r in registry.readers_for(False)], ["struk_belanja"])  # saklar mati: bukti tidak aktif

    def test_register_proof_reader_is_idempotent_by_name(self):
        first, second = FakeReader("qris.umum", "qris", 0.9), FakeReader("qris.umum", "qris", 0.8)
        registry.register_proof_reader(first)
        registry.register_proof_reader(FakeReader("transfer.umum", "transfer", 0.9))
        registry.register_proof_reader(second)       # nama sama (mis. modul diimpor ulang): satu entri, posisi tetap
        registry.register_proof_reader(second)
        self.assertEqual([r.name for r in self.proofs], ["qris.umum", "transfer.umum"])
        self.assertIs(self.proofs[0], second)

    async def test_highest_score_wins_and_ties_go_to_proofs_first(self):
        proof, other = FakeReader("qris.umum", "qris", 0.9), FakeReader("transfer.umum", "transfer", 0.9)
        registry.register_proof_reader(proof)
        registry.register_proof_reader(other)
        lines = FIX["receipts"][0]["lines"]                    # struk belanja skor 0.9
        res = await read_document(doc(lines), CTX, proofs_enabled=True)
        self.assertEqual(res.reader, "qris.umum")              # seri: bukti bayar sebelum struk belanja
        self.assertEqual((proof.parsed, other.parsed), (1, 0))
        proof.score = other.score = 0.85
        res = await read_document(doc(lines), CTX, proofs_enabled=True)
        self.assertEqual(res.reader, "struk_belanja")          # skor lebih tinggi menang
        res = await read_document(doc(lines), CTX, proofs_enabled=False)
        self.assertEqual(res.reader, "struk_belanja")          # pembaca bukti tidak dijalankan saat saklar mati
        self.assertEqual(proof.parsed, 1)

    async def test_below_threshold_goes_to_unknown(self):
        registry.register_proof_reader(FakeReader("qris.umum", "qris", READER_THRESHOLD - 0.01))
        res = await read_document(doc(["foto buram", "Rp 12.000"]), CTX, proofs_enabled=True)
        self.assertEqual(res.reader, "tidak_dikenali")
        res = await read_document(doc(["foto buram"]), CTX, proofs_enabled=True)
        self.assertEqual((res.reader, res.parsed.doc.amounts.total), ("tidak_dikenali", None))
        registry.register_proof_reader(FakeReader("transfer.umum", "transfer", READER_THRESHOLD))   # tepat di ambang lolos
        res = await read_document(doc(["foto buram"]), CTX, proofs_enabled=True)
        self.assertEqual(res.reader, "transfer.umum")

    async def test_checks_and_flow_are_run_and_stored_on_document(self):
        registry.register_proof_reader(FakeReader("qris.umum", "qris", 0.9))
        common = [Check("umum", "block", "pesan umum")]
        calls = []
        with patch.object(checks_module, "common_checks", lambda parsed, ctx: calls.append(("checks", parsed)) or common), \
             patch.object(checks_module, "apply_flow", lambda parsed, ctx: calls.append(("flow", parsed))):
            res = await read_document(doc(["x"]), CTX, proofs_enabled=True)
        self.assertEqual([c.code for c in res.checks], ["dari_pembaca", "umum"])          # pembaca dulu, lalu umum
        self.assertEqual(res.parsed.doc.checks, [{"code": "dari_pembaca", "level": "warn", "message": "pesan pembaca"},
                                                 {"code": "umum", "level": "block", "message": "pesan umum"}])
        self.assertEqual(sorted(k for k, _ in calls), ["checks", "flow"])
        self.assertTrue(all(p is res.parsed for _, p in calls))

    async def test_cross_checks_apply_to_payment_proofs_not_store_receipts(self):
        # Kontrak checks.py: cek nominal dan tanggal hanya untuk bukti QRIS/transfer; cek status berlaku untuk semua jenis
        # dokumen (lihat FailureBlockIndependentOfReaderTests). Struk belanja yang berhasil tidak diberi cek apa pun,
        # bahkan yang tanggalnya > 60 hari lalu: jalur scan lama tidak punya cek silang dan perilakunya tidak boleh berubah.
        res = await read_document(doc(FIX["receipts"][0]["lines"]), CTX, proofs_enabled=True)
        self.assertEqual((res.checks, res.parsed.doc.checks), ([], []))
        old = ["TOKO MAJU", "01-07-2026 08:15", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000", "TUNAI 15.000"]
        res = await read_document(doc(old), CTX, proofs_enabled=True)
        self.assertEqual((res.reader, res.parsed.doc.paid_at.date().isoformat()), ("struk_belanja", "2026-07-01"))   # 106 hari lalu
        self.assertEqual((res.checks, res.parsed.doc.checks, res.parsed.doc.confidence), ([], [], {"total": "tinggi"}))
        # Dokumen bukti dari pembaca terdaftar mendapat cek silang bersama, sesudah cek pembacanya.
        class FailedTransfer(FakeReader):
            async def parse(self, d, ctx):
                parsed = await super().parse(d, ctx)
                parsed.doc.status = "gagal"
                return parsed
        self.proofs.append(FailedTransfer("transfer.umum", "transfer", 0.9))
        res = await read_document(doc(["x"]), CTX, proofs_enabled=True)
        self.assertEqual([(c.code, c.level) for c in res.checks], [("dari_pembaca", "warn"), ("status_gagal", "block")])

    def test_check_as_dict(self):
        self.assertEqual(Check("status_gagal", "block", "Transaksi gagal").as_dict(),
                         {"code": "status_gagal", "level": "block", "message": "Transaksi gagal"})

    def test_context_defaults_are_not_shared(self):
        a, b = ParseContext(today=date(2026, 10, 15)), ParseContext(today=date(2026, 10, 15))
        a.merchant_aliases["X"] = "y"
        self.assertEqual((b.merchant_aliases, b.merchant_profiles, a.plan, a.user_name, a.llm), ({}, {}, "basic", None, None))
        s1, s2 = Secrets(), Secrets()
        s1.ref_values.append("1")
        self.assertEqual((s2.ref_values, s2.account_number, s2.bank_code, s2.nmid), ([], None, None, None))


CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
STORE_LINES = ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400", "Non Tunai (QRIS) 45.400"]


class LooksLikeProofTests(unittest.TestCase):
    """`looks_like_proof`: deteksi saja (tidak bergantung pada saklar fitur), dipakai worker untuk tidak menyimpan
    teks OCR bukti bayar yang kebetulan dibaca sebagai struk belanja."""

    def test_proof_samples_look_like_proofs(self):
        for sample in CORPUS:
            if sample["expect"]["doc_type"] in ("qris", "transfer"):
                with self.subTest(sample["id"]):
                    self.assertTrue(looks_like_proof(doc(sample["lines"])))

    def test_store_receipts_do_not(self):
        for rec in FIX["receipts"]:
            with self.subTest(rec["id"]):
                self.assertFalse(looks_like_proof(doc(rec["lines"])))
                self.assertIsNone(read_header_status(rec["lines"]))   # struk Indomaret: tanpa status di judul sama sekali
        self.assertFalse(looks_like_proof(doc(STORE_LINES)))
        self.assertIsNone(read_header_status(STORE_LINES))

    def test_empty_and_unrelated_text_do_not(self):
        self.assertFalse(looks_like_proof(doc([])))
        self.assertFalse(looks_like_proof(doc(["halo apa kabar", "tidak ada nominal"])))

    def test_status_title_in_header_marks_text_as_proof_like(self):
        """Bukti dengan satu penanda saja (pembaca bukti tidak mengenalinya) tetap tampak bukti bila 4 baris pertamanya
        memuat judul status ("Transfer Berhasil", "Pembayaran Gagal"). Hanya untuk penyimpanan; perutean tidak berubah."""
        for lines in (["Transfer Berhasil", "BUDI SANTOSO", "BRI", "0123 0100 1234 567", "Nominal Rp150.000",
                       "Biaya Admin Rp2.500", "Total Rp152.500", "26/10/2026 09:30"],
                      ["Transfer Berhasil", "BRI 0123 0100 1234 567", "Nominal Rp150.000", "Biaya Admin Rp2.500",
                       "Total Rp152.500"],
                      ["Transfer Berhasil", "Ke SITI 0812 3456 7890", "Nominal Rp150.000", "Total Rp150.000"],
                      ["BCA", "m-Transfer", "Pembayaran Gagal", "Rp50.000"],
                      ["Kirim ke SITI AMINAH WULAN 081234567890", "Transfer Berhasil", "Total Rp150.000"]):
            with self.subTest(lines[:2]):
                self.assertFalse(any(r.detect(doc(lines)) >= READER_THRESHOLD for r in registry._PROOF_READERS))  # premis
                self.assertTrue(looks_like_proof(doc(lines)))
        for rec in FIX["receipts"]:
            with self.subTest(rec["id"]):
                self.assertFalse(looks_like_proof(doc(rec["lines"])))
        self.assertFalse(looks_like_proof(doc(STORE_LINES)))
        # Kata status di nama toko bukan judul status: `read_header_status` memang membacanya "berhasil" (nilai bawaan
        # struk), tetapi struk seperti ini tetap bukan bukti, jadi rinciannya tetap disimpan.
        for name in ("TOKO SUKSES MAKMUR", "SUKSES JAYA MART", "Warung Sukses", "CV BERHASIL JAYA ABADI", "KOPI SUCCESS"):
            lines = [name, "JL MERDEKA 1", "01-10-2026 08:15", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000", "TUNAI 15.000"]
            with self.subTest(name):
                self.assertEqual(read_header_status(lines), "berhasil")   # premis
                self.assertFalse(looks_like_proof(doc(lines)))
        # Judul status di luar 4 baris pertama pada teks berpola struk belanja, atau kalimat bantuan, bukan bukti. (Tanpa
        # pola struk, judul di baris mana pun menandainya: test_status_title_below_the_header_…, N1.)
        self.assertFalse(looks_like_proof(doc(["TOKO MAJU", "JL MERDEKA 1", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000",
                                               "TUNAI 15.000", "Transfer Berhasil"])))
        self.assertFalse(looks_like_proof(doc(["TOKO MAJU", "Jika transaksi gagal hubungi 14017", "ROTI 10.000"])))

    # N1: bukti satu penanda yang judul statusnya di bawah baris 4 (di bawah rincian, atau di bawah baris status bar dan
    # nama aplikasi): pembaca bukti tidak mengenalinya, pembaca struk memecah nomornya menjadi "barang".
    N1_SLIPS = {
        "gagal": ["BCA mobile", "26/10/2026 14:22", "Ke BUDI 1234 5678 9012", "Nominal Rp150.000", "Total Rp150.000",
                  "Transaksi Gagal"],
        "berhasil": ["BCA mobile", "26/10/2026 14:22", "Ke BUDI 1234 5678 9012", "Nominal Rp150.000", "Total Rp150.000",
                     "Transaksi Berhasil"],
        "status bar": ["14:22", "4G 85%", "BCA mobile", "m-Transfer", "Transfer Berhasil", "Ke BUDI 1234 5678 9012",
                       "Nominal Rp150.000", "Total Rp150.000"],
        "rekening sebaris": ["BCA mobile", "26/10/2026 14:22", "BUDI SANTOSO", "BRI 0123 0100 1234 567", "Nominal Rp150.000",
                             "Total Rp150.000", "Transaksi Berhasil"],
        "va": ["BCA mobile", "26/10/2026 14:22", "VA 8808 0812 3456 7890", "Nominal Rp150.000", "Total Rp150.000",
               "Pembayaran Berhasil"],
        "english": ["Jenius", "Send Money", "26/10/2026 14:22", "To BUDI 1234 5678 9012", "Amount Rp150.000",
                    "Total Rp150.000", "Transaction Successful"],
        "e-wallet hp": ["DANA", "26/10/2026 14:22", "Kirim ke SITI 0812 3456 7890", "Rp50.000", "Total Rp50.000",
                        "Transaksi Berhasil"],
    }
    # Struk belanja berpola struk (barang berkuantitas + baris bayar bernominal sama, baris tunai, atau >= 3 barang) yang
    # mencetak judul status di kakinya, atau deret angka panjang (PLU, telepon toko).
    TITLED_STORES = {
        "qris berhasil": ["KEDAI KOPI", "01-10-2026 08:15", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "TOTAL 40.000",
                          "QRIS 40.000", "Pembayaran QRIS berhasil"],
        "terima kasih": ["KEDAI KOPI", "01-10-2026 08:15", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "TOTAL 40.000",
                         "QRIS 40.000", "Transaksi Berhasil", "Terima kasih"],
        "edc": ["RESTO SEDAP", "01-10-2026 08:15", "NASI GORENG 1 25.000", "ES TEH 2 5.000", "TOTAL 35.000",
                "DEBIT BCA 35.000", "TRANSAKSI BERHASIL"],
        "batal": ["TOKO MAJU", "01-10-2026 08:15", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000", "TUNAI 15.000",
                  "Transaksi gagal - struk ini tidak sah"],
        "pending": ["TOKO MAJU", "01-10-2026 08:15", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000", "TUNAI 15.000",
                    "Pembayaran pending akan diproses otomatis"],
        "plu": ["INDOMARET", "14.10.26-10:00/1/A/01", "20036598 INDOMIE GRG 2 3100 6,200", "10012345 AQUA 600ML 2 3800 7,600",
                "TOTAL : 13,800", "TUNAI : 20,000", "KEMBALI : 6,200", "TERIMA KASIH, TRANSAKSI BERHASIL"],
        "telp toko": ["TOKO MAJU JAYA", "TELP 0812 3456 7890", "01-10-2026 08:15", "ROTI 10.000", "SUSU 5.000",
                      "KOPI 2 x 3.500 7.000", "TOTAL 22.000", "TUNAI 22.000", "Pembayaran QRIS berhasil"],
    }

    def test_status_title_below_the_header_marks_text_without_store_pattern_as_proof_like(self):
        """N1: judul status di baris mana pun menandai teks sebagai bukti (hanya untuk penyimpanan) bila teks itu tidak
        berpola struk belanja (`looks_like_store_receipt`, penjaga yang sama dengan `detect` pembaca bukti, dibaca dari
        baris yang dinormalkan seperti `parse_receipt`). Struk belanja yang mencetak "Pembayaran QRIS berhasil" atau
        "TRANSAKSI BERHASIL" di kakinya tetap struk."""
        for name, lines in self.N1_SLIPS.items():
            with self.subTest(name):
                self.assertFalse(any(r.detect(doc(lines)) >= READER_THRESHOLD for r in registry._PROOF_READERS))  # premis
                self.assertFalse(has_header_status_title(lines))                                                    # premis
                self.assertTrue(looks_like_proof(doc(lines)))
        # Teks pendek tanpa pola struk (2 barang, tanpa TOTAL/tunai) yang berjudul status: dianggap bukti (arah aman, C3).
        self.assertTrue(looks_like_proof(doc(["TOKO MAJU", "JL MERDEKA 1", "ROTI 10.000", "SUSU 5.000", "Transfer Berhasil"])))
        # Hanya judul: kata status di nama toko dan kalimat biasa pada teks tanpa pola struk tidak menjadikannya bukti.
        for lines in (["WARUNG SUKSES", "01-10-2026 08:15", "NASI GORENG 25.000", "TOTAL 25.000"],
                      ["TOKO MAJU", "ROTI 10.000", "Cetak ulang gagal"]):
            with self.subTest(lines[0], last=lines[-1]):
                self.assertFalse(looks_like_store_receipt(clean_lines(lines)))   # premis: tanpa pola struk
                self.assertFalse(looks_like_proof(doc(lines)))
        for name, lines in self.TITLED_STORES.items():
            with self.subTest(name):
                self.assertTrue(pc.has_status_title(lines))   # premis: penjaga pola struk yang memutuskan
                self.assertFalse(looks_like_proof(doc(lines)))
        for rec in FIX["receipts"]:
            with self.subTest(rec["id"]):
                self.assertFalse(looks_like_proof(doc(rec["lines"])))
                self.assertFalse(looks_like_proof(doc([*rec["lines"], "TRANSAKSI BERHASIL"])))
        self.assertFalse(looks_like_proof(doc([*STORE_LINES, "Pembayaran QRIS berhasil"])))
        # Struk Indomaret s4 ber-OCR buruk ("TUNAL 50.000", "KEHBALI 40.800"): tanpa normalisasi ia tidak berpola struk,
        # jadi judul status di kakinya akan menjadikannya bukti dan rinciannya hilang.
        s4 = [*FIX["receipts"][3]["lines"], "TRANSAKSI BERHASIL"]
        self.assertFalse(looks_like_store_receipt(clean_lines(s4)))   # premis
        self.assertFalse(looks_like_proof(doc(s4)))

    def test_status_title_anywhere_unit_rules(self):
        top = ["BCA mobile", "26/10/2026 14:22", "Ke BUDI", "Nominal Rp150.000"]
        for body, expect in ((["Transaksi Gagal"], True), (["Transaksi Berhasil"], True), (["Transfer Diproses"], True),
                             (["Transaction Successful"], True), (["Terima kasih, transaksi berhasil"], True),
                             (["Penerima", "Transfer Sukses Abadi"], False),                      # judul dari baris nama
                             (["Tujuan Transfer CV SUKSES JAYA"], False),
                             (["Info untuk transaksi gagal: 14017"], False), (["Jika transaksi gagal hubungi 14017"], False),
                             (["Transaksi gagal? Hubungi kami"], False), (["Cetak ulang gagal"], False), (["BERHASIL"], False),
                             (["Status: Berhasil"], False), (["WARUNG SUKSES"], False), ([], False)):
            with self.subTest(body):
                self.assertEqual(pc.has_status_title([*top, *body]), expect)
        self.assertTrue(pc.has_status_title(["Transfer Berhasil", "Rp50.000"]))   # 4 baris pertama juga dihitung

    def test_uses_the_reader_threshold_and_every_registered_proof_reader(self):
        below = FakeReader("tipis", "qris", READER_THRESHOLD - 0.01)
        at = FakeReader("pas", "transfer", READER_THRESHOLD)
        with patch.object(registry, "_PROOF_READERS", [below]):
            self.assertFalse(looks_like_proof(doc(["apa saja"])))
        with patch.object(registry, "_PROOF_READERS", [below, at]):
            self.assertTrue(looks_like_proof(doc(["apa saja"])))
