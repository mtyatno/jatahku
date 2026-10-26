import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, subprocess, sys, unittest
from datetime import date
from pathlib import Path
from app.services.kotak_struk import checks as checks_module
from app.services.kotak_struk import registry
from app.services.kotak_struk.document import Counterparty, DokumenBayar, Amounts
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Parsed, ParseContext
from app.services.kotak_struk.readers.profiles import GENERIC_LABELS, PROFILES, AppProfile, detect_issuer, labels_for
from app.services.kotak_struk.readers.qris import QrisReader
from app.services.kotak_struk.readers.struk_belanja import StrukBelanjaReader
from app.services.kotak_struk.readers.transfer import TransferReader
from app.services.kotak_struk.registry import read_document

FIX = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
CTX = ParseContext(today=date(2026, 10, 26), user_name="Rina Wulandari")

async def read(lines, ctx=CTX, enabled=True):
    return await read_document(TextDoc(lines=lines, kind="image"), ctx, proofs_enabled=enabled)

class SyntheticCorpusTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_sample_matches_expectation(self):
        for s in CORPUS:
            with self.subTest(s["id"]):
                d = (await read(s["lines"])).parsed.doc
                e = s["expect"]
                self.assertEqual((d.doc_type, d.amounts.total, d.status, d.flow), (e["doc_type"], e["total"], e["status"], e["flow"]))
                self.assertEqual(d.paid_at.isoformat(), e["paid_at"])
                self.assertEqual(d.counterparty.name, e["counterparty"])

    async def test_secrets_never_in_document(self):
        res = await read(CORPUS[2]["lines"])
        blob = json.dumps(res.parsed.doc.to_json())
        self.assertNotIn("012301001234567", blob.replace(" ", ""))
        self.assertNotIn("2026102612345678", blob)
        self.assertEqual(res.parsed.secrets.ref_values, ["2026102612345678"])
        self.assertEqual((res.parsed.doc.amounts.subtotal, res.parsed.doc.amounts.fee), (150000, 2500))

    async def test_nmid_kept_as_secret_and_masked(self):
        res = await read(CORPUS[0]["lines"])
        self.assertEqual(res.parsed.secrets.nmid, "ID1024358806544")
        self.assertEqual(res.parsed.doc.counterparty.id_kind, "nmid")

class ClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_receipt_with_qris_word_stays_struk_belanja(self):
        res = await read(["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400", "Non Tunai (QRIS) 45.400"])
        self.assertEqual(res.reader, "struk_belanja")

    async def test_proof_readers_off_when_flag_disabled(self):
        res = await read(CORPUS[0]["lines"], enabled=False)
        self.assertNotIn(res.reader, ("qris.umum", "transfer.umum"))

class CheckTests(unittest.IsolatedAsyncioTestCase):
    def codes(self, res):
        return {c.code: c.level for c in res.checks}

    async def test_failed_transfer_blocked(self):
        self.assertEqual(self.codes(await read(CORPUS[3]["lines"]))["status_gagal"], "block")

    async def test_fee_mismatch_warns_and_lowers_confidence(self):
        lines = [l if not l.startswith("Total") else "Total Rp160.000" for l in CORPUS[2]["lines"]]
        res = await read(lines)
        self.assertEqual(self.codes(res)["selisih_nominal"], "warn")
        self.assertEqual(res.parsed.doc.confidence["total"], "sedang")

    async def test_pending_future_and_old_dates(self):
        self.assertIn("status_pending", self.codes(await read(["Transfer Diproses", "Penerima ANDI", "Nominal Rp1.000", "26/10/2026 10:00"])))
        self.assertIn("tanggal_depan", self.codes(await read(["Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", "26/12/2026 10:00"])))
        self.assertIn("bukti_lama", self.codes(await read(["Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", "01/08/2026 10:00"])))

    async def test_transfer_to_own_name_flagged(self):
        res = await read(["Transfer Berhasil", "Penerima RINA WULANDARI", "Bank Tujuan BCA", "Nominal Rp1.000.000", "26/10/2026 10:00"])
        self.assertEqual(res.parsed.doc.flow, "antar_rekening_sendiri")


def sample(sample_id):
    return next(s["lines"] for s in CORPUS if s["id"] == sample_id)


def textdoc(lines):
    return TextDoc(lines=lines, kind="image")


class RegistrationTests(unittest.TestCase):
    def test_proof_readers_are_always_registered_in_priority_order(self):
        self.assertEqual([r.name for r in registry.readers_for(True)], ["qris.umum", "transfer.umum", "struk_belanja"])
        self.assertEqual([r.name for r in registry.readers_for(False)], ["struk_belanja"])

    def test_registration_is_idempotent(self):
        registry.register_proof_reader(QrisReader())
        registry.register_proof_reader(TransferReader())
        self.assertEqual([r.name for r in registry.readers_for(True)], ["qris.umum", "transfer.umum", "struk_belanja"])

    def test_import_order_does_not_matter(self):
        """Modul pembaca tidak mengimpor registry dan registry mengimpor modul pembaca: tidak melingkar."""
        probe = "import {first}, {second}; from app.services.kotak_struk.registry import readers_for; " \
                "print([r.name for r in readers_for(True)])"
        modules = ["app.services.kotak_struk.readers.qris", "app.services.kotak_struk.readers.transfer",
                   "app.services.kotak_struk.registry", "app.services.kotak_struk.checks"]
        for first, second in [(modules[0], modules[2]), (modules[2], modules[0]), (modules[1], modules[3]), (modules[3], modules[2])]:
            with self.subTest(first=first.rsplit(".", 1)[1], second=second.rsplit(".", 1)[1]):
                out = subprocess.run([sys.executable, "-c", probe.format(first=first, second=second)], capture_output=True,
                                     text=True, cwd=Path(__file__).resolve().parents[2], env=os.environ.copy())
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(out.stdout.strip(), "['qris.umum', 'transfer.umum', 'struk_belanja']")


class ProfileTests(unittest.TestCase):
    def test_generic_labels_follow_the_plan(self):
        self.assertEqual(GENERIC_LABELS["amount"], ["nominal", "jumlah", "jumlah pembayaran", "total bayar", "total pembayaran", "total", "amount"])
        self.assertEqual(GENERIC_LABELS["fee"], ["biaya admin", "biaya", "admin", "fee"])
        self.assertEqual(GENERIC_LABELS["merchant"], ["merchant", "nama merchant", "penerima", "tujuan", "ke"])
        self.assertEqual(GENERIC_LABELS["bank"], ["bank tujuan", "bank"])
        self.assertEqual([p.key for p in PROFILES], ["bca_mobile", "livin", "brimo", "bni", "bsi", "jago", "seabank", "blu", "gopay", "ovo", "dana", "shopeepay"])
        self.assertEqual(PROFILES[0].markers, ["bca", "m-bca", "mybca"])

    def test_labels_for_puts_profile_labels_first_without_duplicates(self):
        profile = AppProfile("x", "X", ["x"], {"amount": ["total transfer", "Nominal"], "bonus": ["lain"]})
        self.assertEqual(labels_for(profile, "amount")[:3], ["total transfer", "Nominal", "jumlah"])
        self.assertEqual(labels_for(profile, "bonus"), ["lain"])
        self.assertEqual(labels_for(None, "fee"), GENERIC_LABELS["fee"])
        self.assertEqual(labels_for(profile, "tidak_ada"), [])
        self.assertEqual(AppProfile("a", "A", []).labels, {})

    def test_detect_issuer_most_markers_then_list_order(self):
        self.assertEqual(detect_issuer(["Livin' by Mandiri", "Transfer Berhasil"]).key, "livin")
        self.assertEqual(detect_issuer(["BRImo", "BCA"]).key, "bca_mobile")        # seri 1-1: yang lebih dulu di daftar
        self.assertEqual(detect_issuer(["BRImo", "BRI", "BCA"]).key, "brimo")      # 2 penanda mengalahkan 1
        self.assertIsNone(detect_issuer(["Transfer Berhasil", "Nominal Rp1.000"]))
        self.assertIsNone(detect_issuer([]))

    def test_destination_bank_is_not_the_issuer(self):
        self.assertIsNone(detect_issuer(sample("sint-transfer-1")))                      # "Bank Tujuan BRI"
        self.assertEqual(detect_issuer(["BRImo", "Bank Tujuan BCA", "Penerima ANDI"]).key, "brimo")
        self.assertIsNone(detect_issuer(["Bank Tujuan", "BCA", "Penerima ANDI"]))        # nilai di baris bawah label
        self.assertIsNone(detect_issuer(["Merchant OVO CELL"]))                          # nama merchant bukan aplikasi

    def test_plain_word_dana_is_not_the_dana_app(self):
        self.assertIsNone(detect_issuer(sample("sint-masuk")))
        self.assertEqual(detect_issuer(["DANA", "Dana Masuk"]).key, "dana")
        self.assertEqual(detect_issuer(sample("sint-topup")).key, "gopay")


class ClassificationDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_corpus_sample_picks_its_own_reader(self):
        names = {"qris": "qris.umum", "transfer": "transfer.umum"}
        for s in CORPUS:
            with self.subTest(s["id"]):
                self.assertEqual((await read(s["lines"])).reader, names[s["expect"]["doc_type"]])

    async def test_proofs_that_struk_belanja_scores_high_still_go_to_proof_readers(self):
        cases = [  # (nama, baris, pembaca yang benar); struk belanja menilai semuanya 0.9 (ada baris Total + >= 2 baris "kata + nominal")
            ("transfer biasa", sample("sint-transfer-1"), "transfer.umum"),
            ("transfer dengan 2 baris biaya", ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Biaya Admin Rp2.500",
                                               "Biaya Layanan Rp1.000", "Total Rp153.500", "26/10/2026 09:30"], "transfer.umum"),
            ("top-up dengan biaya dan total", ["Top Up Berhasil", "OVO", "Nominal Rp100.000", "Biaya Admin Rp1.500", "Total Rp101.500",
                                               "26/10/2026 10:15", "ID Transaksi A1B2C3D4"], "transfer.umum"),
            ("QRIS satu penanda dengan biaya dan total", ["Pembayaran Berhasil", "QRIS", "Merchant WARUNG MAJU", "Nominal Rp25.000", "Biaya Layanan Rp500",
                                                          "Total Rp25.500", "26/10/2026 08:12"], "qris.umum"),
        ]
        for name, lines, expected in cases:
            with self.subTest(name):
                self.assertEqual(StrukBelanjaReader().detect(textdoc(lines)), 0.9)      # premis: struk belanja menilai 0.9
                res = await read(lines)
                self.assertEqual(res.reader, expected)
                proof = {r.name: r.detect(textdoc(lines)) for r in registry.readers_for(True)}[expected]
                self.assertGreaterEqual(proof, 0.9)

    async def test_indomaret_fixtures_stay_struk_belanja_with_proofs_enabled(self):
        for rec in FIX["receipts"]:
            with self.subTest(rec["id"]):
                d = textdoc(rec["lines"])
                self.assertEqual((QrisReader().detect(d), TransferReader().detect(d)), (0.0, 0.0))
                res = await read(rec["lines"], ctx=ParseContext(today=date(2026, 10, 15)))
                self.assertEqual((res.reader, res.parsed.doc.doc_type, res.checks), ("struk_belanja", "struk_belanja", []))

    async def test_store_receipts_paid_by_qris_or_transfer_stay_struk_belanja(self):
        cases = {
            "KEMBALI": ["ALFAMART", "ROTI 15.000", "SUSU 30.400", "Total Belanja 45.400", "QRIS 45.400", "KEMBALI 0"],
            "tiga barang tanpa kata tunai": ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "AIR MINERAL 1 4.000",
                                             "Total Belanja 49.400", "Pembayaran QRIS 49.400"],
            "dua barang, QRIS tanpa penanda lain": ["ALFAMART", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400", "QRIS 45.400"],
            "struk toko yang mencetak NMID dan Terminal ID QRIS": ["INDOMARET", "ROTI 1 15.000", "SUSU 2 30.400", "AIR MINERAL 1 4.000", "Total Belanja 49.400",
                                                                  "Pembayaran QRIS 49.400", "NMID ID1024358806544", "Terminal ID 01234"],
            "top-up pulsa di kasir": ["INDOMARET", "TOP UP GOPAY 100.000", "ADMIN 2.000", "TOTAL 102.000", "TUNAI 102.000"],
            "transfer sebagai cara bayar": ["TOKO ABC", "BERAS 1 60.000", "MINYAK 1 20.000", "GULA 1 16.000", "TOTAL 96.000", "Transfer BCA 96.000", "Penerima TOKO ABC"],
        }
        for name, lines in cases.items():
            with self.subTest(name):
                self.assertEqual((await read(lines)).reader, "struk_belanja")

    def test_store_receipt_guard(self):
        self.assertTrue(pc.looks_like_store_receipt(["KEMBALI 1.000"]))
        self.assertTrue(pc.looks_like_store_receipt(["Non Tunai (QRIS) 45.400"]))
        self.assertTrue(pc.looks_like_store_receipt(["TUNAI : 0"]))
        self.assertFalse(pc.looks_like_store_receipt(["Pembayaran Berhasil", "Kembali ke Beranda"]))          # tombol, bukan baris kembalian
        self.assertTrue(pc.looks_like_store_receipt(["ROTI 1 15.000", "SUSU 2 30.400", "AIR 4.000"]))
        self.assertFalse(pc.looks_like_store_receipt(["ROTI 1 15.000", "SUSU 2 30.400", "TOTAL 45.400", "AIR 4.000"]))   # hanya yang sebelum Total
        self.assertTrue(pc.looks_like_store_receipt(["ROTI 15.000", "SUSU 30.400", "AIR 4.000", "SUBTOTAL 49.400"]))   # SUBTOTAL bukan baris total
        # baris berlabel bukti bayar, tanggal, dan nomor panjang bukan barang
        self.assertFalse(pc.looks_like_store_receipt(["Transfer Berhasil", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Biaya Layanan Rp1.000",
                                                      "Rekening Tujuan 0123 0100 1234 567", "26 Okt 2026", "No. Ref 2026102612345678", "Total Rp153.500"]))
        self.assertFalse(pc.looks_like_store_receipt([]))

    async def test_no_proof_reader_claims_unreadable_or_plain_documents(self):
        for lines in (["foto buram", "Rp 12.000"], [], ["Transfer"], ["Dari: PT Maju Jaya", "Total: Rp100.000"], ["QRIS"]):
            with self.subTest(lines):
                self.assertEqual((QrisReader().detect(textdoc(lines)), TransferReader().detect(textdoc(lines))), (0.0, 0.0))
                self.assertEqual((await read(lines)).reader in ("qris.umum", "transfer.umum"), False)

    def test_detect_scores(self):
        q, t = QrisReader(), TransferReader()
        cases = [
            (q, sample("sint-qris-1"), 0.95), (q, sample("sint-qris-2"), 0.95),
            (q, ["QRIS", "Merchant WARUNG", "Nominal Rp25.000"], 0.7),                      # satu penanda, tanpa status
            (q, ["Pembayaran Berhasil", "QRIS", "Nominal Rp25.000"], 0.9),                   # + kata status
            (q, ["Pembayaran Berhasil", "QRIS"], 0.0),                                       # tanpa label merchant/nominal
            (q, ["Pembayaran Berhasil", "Nominal Rp25.000"], 0.0),                           # tanpa kata QRIS
            (t, sample("sint-transfer-1"), 0.9), (t, sample("sint-transfer-gagal"), 0.9),
            (t, ["Top Up", "Nominal Rp100.000"], 0.85),                                      # top-up polos
            (t, ["Top Up Berhasil", "Nominal Rp100.000"], 0.9),                              # + kata status
            (t, ["Isi Saldo", "Berita saldo", "Rp 100.000"], 0.9),                           # + penanda transfer, nominal tanpa label
            (t, ["Top Up Berhasil"], 0.0),                                                   # tanpa nominal
            (t, ["Transfer Berhasil", "Nominal Rp1.000"], 0.0),                              # hanya satu penanda transfer
        ]
        for reader, lines, expect in cases:
            with self.subTest((reader.name, lines[:2])):
                self.assertEqual(reader.detect(textdoc(lines)), expect)
        self.assertEqual((q.doc_type, q.name, t.doc_type, t.name), ("qris", "qris.umum", "transfer", "transfer.umum"))


def blob_of(res):
    return json.dumps(res.parsed.doc.to_json(), ensure_ascii=False).replace(" ", "")


class SecretsAndMaskingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_raw_secret_in_any_corpus_document(self):
        for s in CORPUS:
            with self.subTest(s["id"]):
                res = await read(s["lines"])
                blob, secrets = blob_of(res), res.parsed.secrets
                raw = [*secrets.ref_values, secrets.nmid, (secrets.account_number or "").replace(" ", "")]
                for value in filter(None, raw):
                    self.assertNotIn(value, blob)
                self.assertEqual(res.parsed.extra, {})        # tidak ada baris OCR mentah yang ikut tersimpan

    async def test_masked_forms(self):
        d = (await read(sample("sint-transfer-1"))).parsed.doc
        self.assertEqual([(r.kind, r.masked) for r in d.refs], [("ref", "…5678")])
        self.assertEqual((d.counterparty.id_kind, d.counterparty.id_masked, d.counterparty.bank), ("rekening", "…4567", "BRI"))
        d = (await read(sample("sint-qris-1"))).parsed.doc
        self.assertEqual((d.counterparty.id_kind, d.counterparty.id_masked), ("nmid", "ID10…6544"))   # seperti contoh di spec
        self.assertEqual([(r.kind, r.masked) for r in d.refs], [("ref", "…8812")])
        d = (await read(sample("sint-qris-2"))).parsed.doc
        self.assertEqual([(r.kind, r.masked) for r in d.refs], [("rrn", "…6123")])
        d = (await read(sample("sint-topup"))).parsed.doc
        self.assertEqual([(r.kind, r.masked) for r in d.refs], [("ref", "…C3D4")])                 # bukan digit saja: 4 karakter terakhir
        self.assertEqual(pc.mask_ref("612345678812"), "…8812")
        self.assertEqual(pc.mask_id("ID1024358806544"), "ID10…6544")
        self.assertEqual(pc.mask_id("12345678"), "…5678")

    async def test_secret_values_are_normalized(self):
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Rekening Tujuan 0123 0100 1234 567", "No. Ref 2026 1026-1234 5678", "Nominal Rp1.000", "RRN abc123456"])
        s = res.parsed.secrets
        self.assertEqual(s.ref_values, ["2026102612345678", "ABC123456"])                           # huruf dan angka saja, huruf besar
        self.assertEqual([r.kind for r in res.parsed.doc.refs], ["ref", "rrn"])
        self.assertEqual(s.account_number, "0123 0100 1234 567")
        res = await read(["Pembayaran QRIS Berhasil", "NMID : id 1024358806544", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.secrets.nmid, "ID1024358806544")

    async def test_short_or_wordy_references_are_not_references(self):
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp1.000", "Ref 123", "No. Referensi Berhasil", "ID Transaksi"])
        self.assertEqual((res.parsed.secrets.ref_values, res.parsed.doc.refs), ([], []))

    async def test_account_rules(self):
        for line, expect in [("Rekening Tujuan 0123 0100 1234 567", "0123 0100 1234 567"), ("No. Rekening 012301001234567", "012301001234567"),
                             ("Rekening Tujuan ****4567", "****4567"), ("Rekening Tujuan BRI - 0123010012345", "0123010012345"),
                             ("Rekening Sumber 1111222233", None), ("Rekening Tujuan 12", None), ("Rekening Tujuan", None)]:
            with self.subTest(line):
                res = await read(["Transfer Berhasil", "Penerima BUDI", line, "Nominal Rp1.000"])
                self.assertEqual(res.parsed.secrets.account_number, expect)
                if expect:
                    self.assertNotIn(expect.replace(" ", ""), blob_of(res))

    async def test_bank_code_is_normalized(self):
        for line, expect in [("Bank Tujuan BRI", "BRI"), ("Bank Tujuan  bri ", "BRI"), ("Bank Tujuan Bank BCA", "BCA"),
                             ("Bank Tujuan Bank Central Asia", "BCA"), ("Bank Tujuan BANK MANDIRI", "MANDIRI"),
                             ("Bank Tujuan Bank Rakyat Indonesia (BRI)", "BRI"), ("Bank Tujuan Bank Syariah Indonesia", "BSI"),
                             ("Bank Tujuan BCA 0123456789", "BCA"), ("Bank Tujuan Bank Sinarmas", "SINARMAS"), ("Bank BNI", "BNI")]:
            with self.subTest(line):
                res = await read(["Transfer Berhasil", "Penerima BUDI", line, "Nominal Rp1.000"])
                self.assertEqual((res.parsed.secrets.bank_code, res.parsed.doc.counterparty.bank), (expect, expect))
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp1.000"])
        self.assertEqual((res.parsed.secrets.bank_code, res.parsed.doc.counterparty.bank), (None, None))
        # Nilai "Bank Tujuan" hilang di OCR: label umum "bank" tidak boleh membaca "Tujuan" sebagai nama bank.
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan", "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp1.000"])
        self.assertEqual((res.parsed.secrets.bank_code, res.parsed.doc.counterparty.bank, res.parsed.secrets.account_number), (None, None, "0123 0100 1234 567"))

    async def test_counterparty_key_input_is_stable_across_apps(self):
        from app.services.kotak_struk.merchants import counterparty_key
        keys = set()
        for bank in ("Bank Tujuan BCA", "Bank Tujuan  bca", "Bank Tujuan Bank Central Asia"):
            res = await read(["Transfer Berhasil", "Penerima BUDI", bank, "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp1.000"])
            s = res.parsed.secrets
            keys.add(counterparty_key(res.parsed.doc.counterparty, nmid=s.nmid, account_number=s.account_number, bank_code=s.bank_code))
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys.pop().startswith("rek:"))
        res = await read(sample("sint-qris-1"))
        s = res.parsed.secrets
        self.assertEqual(counterparty_key(res.parsed.doc.counterparty, nmid=s.nmid), "nmid:ID1024358806544")


class AmountTests(unittest.IsolatedAsyncioTestCase):
    async def amounts(self, lines):
        res = await read(lines)
        a = res.parsed.doc.amounts
        return (a.subtotal, a.fee, a.total), res

    async def test_total_is_nominal_plus_fee_without_total_line(self):
        got, res = await self.amounts(["Transfer Berhasil", "Penerima ANDI", "Nominal Rp150.000", "Biaya Admin Rp2.500"])
        self.assertEqual(got, (150000, 2500, 152500))
        self.assertNotIn("selisih_nominal", {c.code for c in res.checks})

    async def test_missing_or_tiny_fee_counts_as_zero(self):
        for fee_line in (None, "Biaya Admin Rp0", "Biaya Admin Rp50", "Biaya Admin Gratis", "Biaya Admin", "Fee Rp 99"):
            with self.subTest(fee_line):
                lines = ["Transfer Berhasil", "Penerima ANDI", "Nominal Rp50.000"] + ([fee_line] if fee_line else [])
                got, _ = await self.amounts(lines)
                self.assertEqual(got, (50000, 0, 50000))

    async def test_total_without_nominal(self):
        got, res = await self.amounts(["Transfer Berhasil", "Penerima ANDI", "Biaya Admin Rp2.500", "Total Rp52.500"])
        self.assertEqual(got, (None, 2500, 52500))
        self.assertEqual("selisih_nominal" in {c.code for c in res.checks}, False)          # tanpa nominal, tidak ada yang dicocokkan

    async def test_label_above_value_and_formats(self):
        for lines, total in [(["Transfer Berhasil", "Penerima ANDI", "Nominal", "Rp 25.000,00"], 25000),
                             (["Transfer Berhasil", "Penerima ANDI", "Amount", "IDR 25,000.00"], 25000),
                             (["Transfer Berhasil", "Penerima ANDI", "Total Bayar: Rp25.000"], 25000),
                             (["Pembayaran Berhasil", "QRIS", "Jumlah", "Rp 7.500", "Merchant KIOS"], 7500)]:
            with self.subTest(lines):
                got, res = await self.amounts(lines)
                self.assertEqual(got[2], total)
                self.assertEqual(res.parsed.doc.confidence["total"], "tinggi")

    async def test_bare_amount_fallback_confidence(self):
        got, res = await self.amounts(["Transfer Berhasil", "Rp 150.000", "Penerima ANDI", "Biaya Admin Rp2.500"])
        self.assertEqual((got[0], got[2], res.parsed.doc.confidence["total"]), (None, 150000, "sedang"))   # setelah baris status
        got, res = await self.amounts(["Rp 9.000", "Transfer Berhasil", "Penerima ANDI"])
        self.assertEqual((got[2], res.parsed.doc.confidence["total"]), (9000, "rendah"))               # sebelum baris status: kurang pasti
        got, res = await self.amounts(["Pembayaran Berhasil", "QRIS", "Merchant KIOS"])
        self.assertEqual((got[2], "total" in res.parsed.doc.confidence), (None, False))                 # tanpa nominal: tanpa keyakinan
        self.assertEqual((await self.amounts(sample("sint-qris-1")))[1].parsed.doc.confidence["total"], "sedang")
        self.assertEqual((await self.amounts(sample("sint-qris-2")))[1].parsed.doc.confidence["total"], "tinggi")


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def status(self, *lines):
        return (await read(list(lines))).parsed.doc.status

    async def test_status_words(self):
        for header, expect in [("Transfer Berhasil", "berhasil"), ("Transaksi Sukses", "berhasil"), ("Payment Successful", "berhasil"),
                               ("Transfer Gagal", "gagal"), ("Transaction Failed", "gagal"), ("Transfer tidak berhasil", "gagal"),
                               ("Transfer Diproses", "pending"), ("Transaksi sedang diproses", "pending"), ("Status: Pending", "pending"),
                               ("Transaksi berhasil diproses", "berhasil"), ("Transfer", "tidak_diketahui")]:
            with self.subTest(header):
                self.assertEqual(await self.status(header, "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000"), expect)

    async def test_failure_wins_over_other_words_in_the_header(self):
        self.assertEqual(await self.status("Transfer Gagal", "Transaksi sebelumnya berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000"), "gagal")

    async def test_long_footer_sentences_do_not_decide_the_status(self):
        footer = "Jika transaksi gagal atau pending silakan hubungi layanan nasabah kami"
        self.assertEqual(await self.status("Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", footer), "berhasil")
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Nominal Rp1.000", footer), "tidak_diketahui")   # tanpa judul: kalimat panjang diabaikan

    async def test_status_label_and_short_lines_anywhere(self):
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Nominal Rp1.000", "Status", "Gagal"), "gagal")
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Nominal Rp1.000", "Status Transaksi: Berhasil"), "berhasil")
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Berhasil"), "berhasil")
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Status Selesai", "Pending"), "pending")

    async def test_incoming_without_status_word_counts_as_berhasil(self):
        self.assertEqual((await read(sample("sint-masuk"))).parsed.doc.status, "berhasil")
        self.assertEqual((await read(["Dana Masuk", "Dari RINA", "Nominal Rp500.000", "Transaksi Gagal"])).parsed.doc.status, "gagal")

    async def test_failed_qris_is_blocked(self):
        res = await read(["Pembayaran Gagal", "QRIS", "Merchant KIOS", "Nominal Rp1.000"])
        self.assertEqual({c.code: c.level for c in res.checks}, {"status_gagal": "block"})


class FieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_qris_fields_and_confidence(self):
        d = (await read(sample("sint-qris-2"))).parsed.doc
        self.assertEqual((d.method, d.flow, d.counterparty.name, d.counterparty.city, d.counterparty.id_kind), ("qris", "keluar", "WARUNG BAKSO PAK DI", "SEMARANG", None))
        self.assertEqual(d.confidence, {"total": "tinggi", "counterparty": "tinggi", "paid_at": "tinggi"})
        self.assertEqual(d.note, None)

    async def test_issuer_is_the_profile_key(self):
        res = await read(["Pembayaran Berhasil", "GoPay", "QRIS", "Merchant KIOS", "Nominal Rp1.000"])
        self.assertEqual((res.parsed.doc.issuer, res.reader), ("gopay", "qris.umum"))
        self.assertIn("Aplikasi GoPay", res.parsed.doc.evidence)
        self.assertIsNone((await read(sample("sint-qris-1"))).parsed.doc.issuer)

    async def test_merchant_pan_and_terminal_lines_are_not_merchant_names(self):
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant PAN 9360001234567", "Merchant ID 123456", "Merchant WARUNG X", "Terminal ID A01", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.name, "WARUNG X")
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant", "Merchant PAN 9360001234567", "Nominal Rp1.000"])
        self.assertIsNone(res.parsed.doc.counterparty.name)                    # nilai label hilang: bukan "PAN 9360..."

    async def test_missing_value_is_not_taken_from_the_next_label(self):
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant", "Lokasi BANDUNG", "Nominal Rp25.000"])
        d = res.parsed.doc
        self.assertEqual((d.counterparty.name, d.counterparty.city, d.amounts.total), (None, "BANDUNG", 25000))
        self.assertNotIn("counterparty", d.confidence)
        res = await read(["Transfer Berhasil", "Penerima", "Bank Tujuan BCA", "Nominal Rp25.000", "Berita", "No. Ref 2026102612345678"])
        self.assertEqual((res.parsed.doc.counterparty.name, res.parsed.doc.note, res.parsed.secrets.ref_values), (None, None, ["2026102612345678"]))

    async def test_same_line_value_starting_with_a_label_word_is_still_a_name(self):
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant: BANK SAMPAH INDAH", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.name, "BANK SAMPAH INDAH")
        res = await read(["Transfer Berhasil", "Penerima TOTAL BUAH", "Bank Tujuan BCA", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.name, "TOTAL BUAH")

    async def test_name_must_have_letters_and_fit_the_column(self):
        res = await read(["Transfer Berhasil", "Penerima 081234567890", "Bank Tujuan BCA", "Nominal Rp1.000"])
        self.assertIsNone(res.parsed.doc.counterparty.name)
        res = await read(["Transfer Berhasil", "Penerima " + "A" * 150, "Bank Tujuan BCA", "Nominal Rp1.000"])
        self.assertEqual(len(res.parsed.doc.counterparty.name), 100)

    async def test_note_comes_from_berita_keterangan_or_catatan(self):
        for label in ("Berita", "Keterangan", "Catatan"):
            with self.subTest(label):
                res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", f"{label} bayar arisan"])
                self.assertEqual(res.parsed.doc.note, "bayar arisan")
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Berita " + "x" * 400])
        self.assertEqual(len(res.parsed.doc.note), 200)

    async def test_datetime_reading(self):
        for extra, expect in [(["26 Okt 2026, 09:30 WIB"], "2026-10-26T09:30:00+07:00"), (["26 Okt 2026", "09:30:15 WIB"], "2026-10-26T09:30:15+07:00"),
                              (["26/10/2026 08.12"], "2026-10-26T08:12:00+07:00"), (["Oct 26, 2026 08:12 PM"], "2026-10-26T20:12:00+07:00")]:
            with self.subTest(extra):
                res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", *extra])
                self.assertEqual((res.parsed.doc.paid_at.isoformat(), res.parsed.doc.confidence["paid_at"]), (expect, "tinggi"))
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "26 Okt 2026", "Berita arisan"])
        self.assertEqual((res.parsed.doc.paid_at.isoformat(), res.parsed.doc.confidence["paid_at"]), ("2026-10-26T00:00:00+07:00", "sedang"))
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000"])
        self.assertEqual((res.parsed.doc.paid_at, "paid_at" in res.parsed.doc.confidence), (None, False))
        self.assertNotIn("tanggal_depan", {c.code for c in res.checks})

    async def test_dates_inside_notes_and_references_are_not_the_payment_date(self):
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Berita arisan 15/10/2026", "Nominal Rp1.000", "26 Okt 2026 09:30"])
        self.assertEqual(res.parsed.doc.paid_at.isoformat(), "2026-10-26T09:30:00+07:00")


class FlowDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def flow(self, lines):
        return (await read(lines)).parsed.doc.flow

    async def test_corpus_flows(self):
        self.assertEqual([await self.flow(sample(i)) for i in ("sint-transfer-1", "sint-topup", "sint-masuk")], ["keluar", "top_up", "masuk"])

    async def test_top_up_and_incoming_phrases(self):
        self.assertEqual(await self.flow(["Isi Saldo Berhasil", "OVO", "Nominal Rp50.000"]), "top_up")
        self.assertEqual(await self.flow(["Topup Berhasil", "DANA", "Jumlah Rp50.000"]), "top_up")
        self.assertEqual(await self.flow(["Top-Up Sukses", "ShopeePay", "Total Rp50.000"]), "top_up")
        self.assertEqual(await self.flow(["Uang Masuk", "Nominal Rp50.000", "Berita gaji"]), "masuk")
        self.assertEqual(await self.flow(["Terima Dana Berhasil", "Nominal Rp50.000"]), "masuk")

    async def test_incoming_by_sender_label_needs_status_and_no_destination(self):
        self.assertEqual(await self.flow(["Transfer Berhasil", "Pengirim RINA", "Nominal Rp50.000", "Berita gaji"]), "masuk")
        self.assertEqual(await self.flow(["Transfer Berhasil", "Dari RINA WULANDARI", "Penerima BUDI", "Nominal Rp50.000"]), "keluar")   # "Dari" = sumber
        self.assertEqual(await self.flow(["Transfer Berhasil", "Dari RINA WULANDARI", "Bank Tujuan BCA", "Nominal Rp50.000"]), "keluar")
        res = await read(["Dari RINA", "Nominal Rp50.000"])                                                                              # tanpa status/penanda: bukan bukti
        self.assertEqual(res.reader, "tidak_dikenali")

    async def test_incoming_name_is_the_sender(self):
        d = (await read(["Dana Masuk", "Dari RINA", "Pengirim BUDI", "Nominal Rp500.000", "26 Okt 2026 11:00"])).parsed.doc
        self.assertEqual((d.flow, d.counterparty.name), ("masuk", "BUDI"))      # "Pengirim" lebih diutamakan dari "Dari"

    async def test_top_up_phrase_in_a_note_does_not_make_it_a_top_up(self):
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp50.000", "Berita top up gopay"])
        self.assertEqual(res.parsed.doc.flow, "keluar")

    async def test_unrelated_dana_masuk_text_in_qris_stays_keluar(self):
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant KIOS", "Nominal Rp1.000", "Dana Masuk"])
        self.assertEqual((res.reader, res.parsed.doc.flow), ("qris.umum", "keluar"))        # QRIS selalu keluar


class OwnTransferTests(unittest.IsolatedAsyncioTestCase):
    async def flow(self, recipient, *, user="Rina Wulandari", flow_lines=()):
        ctx = ParseContext(today=date(2026, 10, 26), user_name=user)
        res = await read(["Transfer Berhasil", f"Penerima {recipient}", "Bank Tujuan BCA", "Nominal Rp1.000", *flow_lines], ctx=ctx)
        return res.parsed.doc.flow

    async def test_same_name_or_two_shared_words(self):
        self.assertEqual(await self.flow("RINA WULANDARI"), "antar_rekening_sendiri")
        self.assertEqual(await self.flow("rina, wulandari"), "antar_rekening_sendiri")                # huruf besar-kecil dan tanda baca tidak berpengaruh
        self.assertEqual(await self.flow("WULANDARI RINA PUTRI"), "antar_rekening_sendiri")           # >= 2 kata, urutan bebas
        self.assertEqual(await self.flow("RINA ANGGRAINI WULANDARI"), "antar_rekening_sendiri")
        self.assertEqual(await self.flow("P.T. RINA", user="PT Rina"), "antar_rekening_sendiri")      # nama sama setelah normalisasi

    async def test_one_shared_word_is_not_enough(self):
        for recipient in ("RINA ANGGRAINI", "BUDI WULANDARI", "RINA W", "RINAWULANDARI"):
            with self.subTest(recipient):
                self.assertEqual(await self.flow(recipient), "keluar")

    async def test_needs_a_user_name_and_a_recipient(self):
        self.assertEqual(await self.flow("RINA WULANDARI", user=None), "keluar")
        self.assertEqual(await self.flow("RINA WULANDARI", user="  "), "keluar")
        res = await read(["Transfer Berhasil", "Bank Tujuan BCA", "Nominal Rp1.000", "Berita rina wulandari"])
        self.assertEqual(res.parsed.doc.flow, "keluar")                                               # tanpa nama penerima

    async def test_single_word_user_name_needs_an_exact_match(self):
        self.assertEqual(await self.flow("RINA", user="Rina"), "antar_rekening_sendiri")
        self.assertEqual(await self.flow("RINA PUTRI", user="Rina"), "keluar")

    async def test_only_outgoing_transfers_are_asked_about(self):
        ctx = ParseContext(today=date(2026, 10, 26), user_name="Rina Wulandari")
        res = await read(["Dana Masuk", "Dari RINA WULANDARI", "Nominal Rp1.000"], ctx=ctx)
        self.assertEqual(res.parsed.doc.flow, "masuk")
        res = await read(["Top Up Berhasil", "Penerima RINA WULANDARI", "Nominal Rp1.000"], ctx=ctx)
        self.assertEqual(res.parsed.doc.flow, "top_up")
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant RINA WULANDARI", "Nominal Rp1.000"], ctx=ctx)
        self.assertEqual((res.parsed.doc.doc_type, res.parsed.doc.flow), ("qris", "keluar"))

    async def test_flag_is_recorded_as_evidence(self):
        ctx = ParseContext(today=date(2026, 10, 26), user_name="Rina Wulandari")
        res = await read(["Transfer Berhasil", "Penerima RINA WULANDARI", "Bank Tujuan BCA", "Nominal Rp1.000"], ctx=ctx)
        self.assertIn("Nama penerima mirip nama akun kamu", res.parsed.doc.evidence)


def parsed_doc(**kw):
    amounts = kw.pop("amounts", Amounts())
    return Parsed(doc=DokumenBayar(doc_type=kw.pop("doc_type", "transfer"), amounts=amounts, **kw))


class CommonChecksTests(unittest.IsolatedAsyncioTestCase):
    def codes(self, res):
        return {c.code: c.level for c in res.checks}

    async def test_clean_proofs_have_no_checks(self):
        for s in CORPUS:
            if s["id"] == "sint-transfer-gagal":
                continue
            with self.subTest(s["id"]):
                res = await read(s["lines"])
                self.assertEqual((res.checks, res.parsed.doc.checks), ([], []))

    async def test_messages_and_levels_are_exact(self):
        past = ["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000"]
        cases = [
            (past + ["Total Rp9.000", "26/10/2026 10:00"], {"selisih_nominal": ("warn", "Nominal + biaya tidak sama dengan total")}),
            (["Transfer Gagal", *past[1:], "26/10/2026 10:00"], {"status_gagal": ("block", "Transaksi gagal, tidak bisa dicatat")}),
            (["Transfer Diproses", *past[1:], "26/10/2026 10:00"], {"status_pending": ("warn", "Transaksi masih diproses bank")}),
            (past + ["27/10/2026 00:00"], {"tanggal_depan": ("warn", "Tanggal di bukti ada di masa depan")}),
            (past + ["01/08/2026 10:00"], {"bukti_lama": ("warn", "Bukti ini lebih dari 60 hari lalu")}),
        ]
        for lines, expect in cases:
            with self.subTest(list(expect)):
                res = await read(lines)
                self.assertEqual({c.code: (c.level, c.message) for c in res.checks}, expect)
                self.assertEqual(res.parsed.doc.checks, [c.as_dict() for c in res.checks])

    async def test_old_proof_boundary_is_60_days(self):
        base = ["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000"]
        self.assertEqual(self.codes(await read([*base, "27/08/2026 10:00"])), {})                      # tepat 60 hari lalu
        self.assertEqual(self.codes(await read([*base, "26/08/2026 10:00"])), {"bukti_lama": "warn"})  # 61 hari
        self.assertEqual(self.codes(await read([*base, "26/10/2026 23:59"])), {})                      # hari ini, jam lebih lambat: bukan masa depan

    async def test_future_date_lowers_paid_at_confidence(self):
        res = await read(["Transfer Berhasil", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "26/12/2026 10:00"])
        self.assertEqual(res.parsed.doc.confidence["paid_at"], "rendah")
        self.assertEqual(res.parsed.doc.confidence["total"], "tinggi")

    async def test_statuses_are_independent_of_the_other_checks(self):
        res = await read(["Transfer Gagal", "Penerima ANDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Total Rp9.000", "01/08/2026 10:00"])
        self.assertEqual(self.codes(res), {"selisih_nominal": "warn", "status_gagal": "block", "bukti_lama": "warn"})

    def test_mismatch_includes_tax_and_discount_and_needs_both_amounts(self):
        ctx = CTX
        ok = parsed_doc(amounts=Amounts(subtotal=100, fee=10, tax=11, discount=21, total=100))
        self.assertEqual(checks_module.common_checks(ok, ctx), [])
        bad = parsed_doc(amounts=Amounts(subtotal=100, fee=10, total=100), confidence={"total": "tinggi"})
        self.assertEqual([c.code for c in checks_module.common_checks(bad, ctx)], ["selisih_nominal"])
        self.assertEqual(bad.doc.confidence["total"], "sedang")
        for amounts in (Amounts(subtotal=None, fee=10, total=99), Amounts(subtotal=100, fee=10, total=None)):
            self.assertEqual(checks_module.common_checks(parsed_doc(amounts=amounts), ctx), [])

    def test_mismatch_never_raises_confidence(self):
        for before, after in (("rendah", "rendah"), ("sedang", "sedang"), ("tinggi", "sedang")):
            doc = parsed_doc(amounts=Amounts(subtotal=1, total=2), confidence={"total": before})
            checks_module.common_checks(doc, CTX)
            self.assertEqual(doc.doc.confidence["total"], after)
        doc = parsed_doc(amounts=Amounts(subtotal=1, total=2))
        checks_module.common_checks(doc, CTX)
        self.assertEqual(doc.doc.confidence, {"total": "sedang"})

    def test_checks_only_apply_to_payment_proofs(self):
        from datetime import datetime
        from app.services.kotak_struk.readers.labels import WIB
        for doc_type in ("struk_belanja", "tidak_dikenali"):
            doc = parsed_doc(doc_type=doc_type, status="gagal", amounts=Amounts(subtotal=1, total=2), paid_at=datetime(2025, 1, 1, tzinfo=WIB))
            self.assertEqual(checks_module.common_checks(doc, CTX), [])
            self.assertEqual(doc.doc.confidence, {})
        for doc_type in ("qris", "transfer"):
            doc = parsed_doc(doc_type=doc_type, status="gagal")
            self.assertEqual([c.code for c in checks_module.common_checks(doc, CTX)], ["status_gagal"])

    def test_naive_datetimes_are_compared_by_date(self):
        from datetime import datetime
        doc = parsed_doc(paid_at=datetime(2026, 10, 27, 1, 0))
        self.assertEqual([c.code for c in checks_module.common_checks(doc, CTX)], ["tanggal_depan"])

    def test_apply_flow_changes_only_flow_of_outgoing_transfers(self):
        own = parsed_doc(flow="keluar", counterparty=Counterparty(name="Rina Wulandari"))
        checks_module.apply_flow(own, CTX)
        self.assertEqual(own.doc.flow, "antar_rekening_sendiri")
        for flow in ("masuk", "top_up", "tidak_diketahui", "antar_rekening_sendiri"):
            doc = parsed_doc(flow=flow, counterparty=Counterparty(name="Rina Wulandari"))
            checks_module.apply_flow(doc, CTX)
            self.assertEqual(doc.doc.flow, flow)
        doc = parsed_doc(doc_type="qris", flow="keluar", counterparty=Counterparty(name="Rina Wulandari"))
        checks_module.apply_flow(doc, CTX)
        self.assertEqual(doc.doc.flow, "keluar")
