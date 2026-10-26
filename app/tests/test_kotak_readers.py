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
        plan = {
            "amount": ["nominal", "jumlah", "jumlah pembayaran", "total bayar", "total pembayaran", "total", "amount"],
            "fee": ["biaya admin", "biaya", "admin", "fee"],
            "merchant": ["merchant", "nama merchant", "penerima", "tujuan", "ke"],
            "city": ["lokasi", "kota"],
            "ref": ["no. referensi", "no referensi", "referensi", "no. ref", "ref", "rrn", "reference no", "id transaksi", "no. transaksi"],
            "nmid": ["nmid"],
            "account": ["rekening tujuan", "no. rekening", "rekening"],
            "bank": ["bank tujuan", "bank"],
            "note": ["berita", "keterangan", "catatan"],
        }
        for key, labels in plan.items():          # semua label rencana tetap ada, dalam urutan relatif yang sama
            with self.subTest(key):
                got = GENERIC_LABELS[key]
                self.assertEqual([l for l in got if l in labels], labels)
        self.assertEqual([p.key for p in PROFILES], ["bca_mobile", "livin", "brimo", "bni", "bsi", "jago", "seabank", "blu", "gopay", "ovo", "dana", "shopeepay"])
        self.assertEqual(PROFILES[0].markers, ["bca", "m-bca", "mybca"])

    def test_common_label_variants_are_known(self):
        variants = {
            "merchant": ["nama penerima", "nama tujuan"],
            "account": ["nomor rekening", "no rekening", "nomor rekening tujuan", "rekening penerima"],
            "ref": ["nomor referensi", "no ref", "nomor transaksi", "no transaksi", "transaction id"],
            "bank": ["bank penerima"],
            "note": ["berita transfer"],
            "sender": ["pengirim", "nama pengirim"],
            "discount": ["diskon", "potongan", "promo", "voucher", "discount"],
        }
        for key, labels in variants.items():
            for label in labels:
                with self.subTest(key=key, label=label):
                    self.assertIn(label, GENERIC_LABELS[key])

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
        self.assertFalse(pc.looks_like_store_receipt(["ROTI 15.000", "SUSU 30.400", "TOTAL 45.400", "AIR 4.000"]))   # hanya yang sebelum Total
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
        long_plain = "Transaksi anda tercatat gagal dan dana dikembalikan ke rekening sumber otomatis"   # panjang, tanpa kata bersyarat
        self.assertEqual(await self.status("Transfer", "Penerima ANDI", "Nominal Rp1.000", long_plain), "tidak_diketahui")
        self.assertEqual(await self.status("Transfer Berhasil", "Penerima ANDI", "Nominal Rp1.000", long_plain), "berhasil")

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


# ── Perbaikan review A5 ─────────────────────────────────────────────────────

class AccountNumbersNeverLeakTests(unittest.IsolatedAsyncioTestCase):
    """Temuan 1: nomor rekening utuh tidak boleh masuk DokumenBayar maupun kunci pihak (tanpa HMAC)."""

    async def leaks(self, lines, *numbers):
        res = await read(lines)
        blob = json.dumps(res.parsed.doc.to_json(), ensure_ascii=False).replace(" ", "")
        for n in numbers:
            self.assertNotIn(n.replace(" ", ""), blob)
        return res

    async def test_number_in_the_name_line(self):
        res = await self.leaks(["Transfer Berhasil", "Penerima", "BUDI SANTOSO - 0123456789", "Bank Tujuan BCA", "Nominal Rp150.000"], "0123456789")
        self.assertEqual(res.parsed.doc.counterparty.name, "BUDI SANTOSO")
        self.assertEqual((res.parsed.secrets.account_number, res.parsed.doc.counterparty.id_kind, res.parsed.doc.counterparty.id_masked),
                         ("0123456789", "rekening", "…6789"))        # tanpa label rekening: dipindah ke Secrets

    async def test_bank_and_number_on_the_name_line(self):
        res = await self.leaks(["Transfer Berhasil", "Tujuan", "BCA 0123456789 BUDI SANTOSO", "Nominal Rp150.000", "Berita arisan"], "0123456789")
        self.assertEqual(res.parsed.secrets.account_number, "0123456789")
        self.assertNotRegex(res.parsed.doc.counterparty.name, r"\d{4}")

    async def test_number_glued_to_the_bank(self):
        from app.services.kotak_struk.merchants import counterparty_key
        for line in ("Bank Tujuan BCA-0123456789", "Bank Tujuan BCA - 0123456789", "Bank Tujuan BCA 0123456789", "Bank Tujuan BCA0123456789",
                     "Bank Tujuan Bank BCA – 0123456789"):
            with self.subTest(line):
                res = await self.leaks(["Transfer Berhasil", "Penerima BUDI", line, "Nominal Rp150.000"], "0123456789")
                s = res.parsed.secrets
                self.assertEqual((s.bank_code, res.parsed.doc.counterparty.bank, s.account_number), ("BCA", "BCA", "0123456789"))
                key = counterparty_key(res.parsed.doc.counterparty, nmid=s.nmid, account_number=s.account_number, bank_code=s.bank_code)
                self.assertTrue(key.startswith("rek:"), key)
                self.assertNotIn("0123456789", key)

    async def test_digits_in_parentheses_are_not_a_bank(self):
        res = await self.leaks(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BRI (01230100)", "Nominal Rp150.000"], "01230100")
        self.assertEqual((res.parsed.secrets.bank_code, res.parsed.doc.counterparty.bank), ("BRI", "BRI"))
        res = await self.leaks(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan (01230100)", "Nominal Rp150.000"], "01230100")
        self.assertEqual((res.parsed.secrets.bank_code, res.parsed.doc.counterparty.bank), (None, None))
        res = await self.leaks(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan 0123456789", "Nominal Rp150.000"], "0123456789")
        self.assertEqual(res.parsed.secrets.bank_code, None)
        self.assertEqual(pc.normalize_bank("Bank Rakyat Indonesia (BRI)"), "BRI")
        self.assertEqual(pc.normalize_bank("(12345)"), None)
        for raw, expect in [("BCA-0123456789", "BCA"), ("BCA – 0123456789", "BCA"), ("BCA 12345", "BCA"), ("Bank Mandiri/1234567890", "MANDIRI"),
                            ("BRI (01230100)", "BRI"), ("01230100", None), ("12", None), ("", None), (None, None), ("(BRI)", "BRI")]:
            with self.subTest(raw):
                self.assertEqual(pc.normalize_bank(raw), expect)

    async def test_labelled_account_wins_over_a_number_found_elsewhere(self):
        res = await self.leaks(["Transfer Berhasil", "Penerima BUDI SANTOSO 0999888777", "Bank Tujuan BCA", "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp1.000"],
                               "0999888777", "012301001234567")
        self.assertEqual(res.parsed.secrets.account_number, "0123 0100 1234 567")
        self.assertEqual(res.parsed.doc.counterparty.name, "BUDI SANTOSO")

    async def test_grouped_and_glued_numbers_in_names(self):
        for value, name in [("BUDI SANTOSO 0123 0100 1234 567", "BUDI SANTOSO"), ("BUDI 0123-0100-1234", "BUDI"), ("BUDI0123456789", "BUDI"),
                            ("0123456789 BUDI SANTOSO", "BUDI SANTOSO")]:
            with self.subTest(value):
                res = await self.leaks(["Transfer Berhasil", f"Penerima {value}", "Bank Tujuan BCA", "Nominal Rp1.000"], "0123456789", "012301001234567", "012301001234")
                self.assertEqual(res.parsed.doc.counterparty.name, name)

    async def test_short_numbers_stay_in_names(self):
        res = await read(["Transfer Berhasil", "Penerima KIOS 24 JAM", "Bank Tujuan BCA", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.name, "KIOS 24 JAM")
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant TOKO 17 AGUSTUS", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.name, "TOKO 17 AGUSTUS")
        res = await read(["Transfer Berhasil", "Penerima BUDI 12345", "Bank Tujuan BCA", "Nominal Rp1.000"])        # 5 digit: bukan rekening
        self.assertEqual((res.parsed.doc.counterparty.name, res.parsed.secrets.account_number), ("BUDI 12345", None))

    async def test_a_name_made_only_of_digits_is_no_name(self):
        res = await self.leaks(["Transfer Berhasil", "Ke 0123456789", "Bank Tujuan BCA", "Nominal Rp1.000"], "0123456789")
        self.assertEqual((res.parsed.doc.counterparty.name, res.parsed.secrets.account_number), (None, "0123456789"))
        self.assertNotIn("counterparty", res.parsed.doc.confidence)

    async def test_nmid_and_numbers_in_qris_merchant_or_city(self):
        res = await self.leaks(["Pembayaran Berhasil", "QRIS", "Merchant", "WARUNG X ID1024358806544", "Lokasi BANDUNG 40123 0812345678", "Nominal Rp1.000"],
                               "ID1024358806544", "1024358806544", "0812345678")
        self.assertEqual((res.parsed.doc.counterparty.name, res.parsed.doc.counterparty.city), ("WARUNG X", "BANDUNG"))   # kode pos + telepon berurutan = satu deret
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Lokasi BANDUNG 40123", "Nominal Rp1.000"])
        self.assertEqual(res.parsed.doc.counterparty.city, "BANDUNG 40123")

    async def test_secret_numbers_quoted_in_the_note_are_removed(self):
        res = await self.leaks(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Rekening Tujuan 0123 0100 1234 567", "No. Ref 2026102612345678",
                                "Nominal Rp1.000", "Berita ke rek 012301001234567 ref 2026102612345678 arisan"], "012301001234567", "2026102612345678")
        self.assertEqual(res.parsed.doc.note, "ke rek ref arisan")
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Berita listrik 123456789012"])
        self.assertEqual(res.parsed.doc.note, "listrik 123456789012")          # angka lain milik user: tidak diubah
        res = await read(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Rekening Tujuan 0123456789", "Nominal Rp1.000", "Berita 0123456789"])
        self.assertIsNone(res.parsed.doc.note)

    async def test_no_corpus_style_layout_leaks_any_secret(self):
        layouts = [
            ["BRImo", "Transaksi Berhasil", "Nama Penerima", "BUDI SANTOSO", "Bank Tujuan", "Bank BCA", "Nomor Rekening", "0123456789", "Nominal Rp150.000", "Nomor Referensi", "123456789012"],
            ["Transfer Berhasil", "Rp 150.000", "Penerima", "BUDI SANTOSO", "Bank Mandiri - 1234567890", "Sumber Dana", "RINA WULANDARI", "No. Referensi 123456789012"],
            ["m-Transfer", "BERHASIL", "26/10/2026 09:30:12", "Ke 0123456789", "BUDI SANTOSO", "Rp 150.000,00", "Berita: arisan", "Ref 1234567890"],
        ]
        for lines in layouts:
            with self.subTest(lines[0]):
                res = await read(lines)
                s = res.parsed.secrets
                raw = [*s.ref_values, (s.account_number or "").replace(" ", "")]
                await self.leaks(lines, *[r for r in raw if r])


class StatusFooterTests(unittest.IsolatedAsyncioTestCase):
    """Temuan 2: kalimat peringatan di kaki bukti tidak boleh membuat transfer berhasil jadi gagal."""

    BASE = ["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer", "Transaksi Berhasil", "Penerima BUDI", "Bank Tujuan BCA"]

    async def test_footer_warnings_do_not_flip_a_successful_transfer(self):
        for footer in ("Jika gagal hubungi 14017", "Transaksi gagal? Hubungi kami", "Bila transaksi gagal, saldo kembali", "Hubungi 14017 jika gagal",
                       "Gagal? Hubungi CS", "Failed? Contact us", "Silakan hubungi kami bila gagal", "Jika pending cek lagi"):
            with self.subTest(footer):
                res = await read([*self.BASE, footer])
                self.assertEqual(res.parsed.doc.status, "berhasil")
                self.assertNotIn("status_gagal", {c.code for c in res.checks})
                self.assertNotIn("status_pending", {c.code for c in res.checks})

    async def test_warning_sentences_before_the_status_line_are_skipped_too(self):
        banner = ["Jika gagal hubungi 14017", "BRImo", "26 Okt 2026 09:30", "Transaksi Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000"]    # judul
        self.assertEqual((await read(banner)).parsed.doc.status, "berhasil")
        body = ["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer", "Jika gagal hubungi 14017", "Transaksi Berhasil", "Penerima BUDI", "Bank Tujuan BCA"]  # badan
        self.assertEqual((await read(body)).parsed.doc.status, "berhasil")
        only_footer = ["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Jika gagal hubungi 14017"]
        self.assertEqual((await read(only_footer)).parsed.doc.status, "tidak_diketahui")                    # kalimat bersyarat bukan status

    async def test_body_tier_takes_the_first_status_line_in_document_order(self):
        self.assertEqual((await read([*self.BASE, "Gagal"])).parsed.doc.status, "berhasil")          # kata tunggal sesudah status: urutan dokumen
        self.assertEqual((await read([*self.BASE[:4], "Transaksi Gagal", "Penerima BUDI", "Bank Tujuan BCA", "Berhasil"])).parsed.doc.status, "gagal")
        self.assertEqual((await read([*self.BASE[:4], "Pending", "Penerima BUDI", "Bank Tujuan BCA", "Gagal"])).parsed.doc.status, "pending")

    async def test_header_and_label_tiers_still_prefer_failure(self):
        self.assertEqual((await read(["Transfer Gagal", "Transaksi sebelumnya berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000"])).parsed.doc.status, "gagal")
        self.assertEqual((await read(["Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Status Berhasil atau gagal"])).parsed.doc.status, "gagal")

    async def test_header_tier_keeps_failure_first(self):
        res = await read(["Transfer Berhasil", "26 Okt 2026", "Penerima BUDI", "Gagal", "Bank Tujuan BCA", "Nominal Rp1.000"])         # 4 baris pertama memuat keduanya
        self.assertEqual(res.parsed.doc.status, "gagal")

    async def test_a_failure_without_footer_noise_is_still_blocked(self):
        res = await read([*self.BASE[:4], "Transfer Gagal", "Penerima BUDI", "Bank Tujuan BCA"])
        self.assertEqual((res.parsed.doc.status, {c.code: c.level for c in res.checks}), ("gagal", {"status_gagal": "block"}))
        res = await read(["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer", "Gagal", "Penerima BUDI", "Bank Tujuan BCA", "Jika saldo terpotong hubungi 14017"])
        self.assertEqual(res.parsed.doc.status, "gagal")


class StoreReceiptWithFewItemsTests(unittest.IsolatedAsyncioTestCase):
    """Temuan 3: struk toko berisi <= 2 barang yang dibayar QRIS tetap struk belanja, rincian barang tidak hilang."""

    CASES = {
        "QRIS + kata status": ["KOPI KENANGAN", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "Total 40.000", "QRIS 40.000", "Pembayaran Berhasil"],
        "QRIS + Terminal ID": ["WARUNG KOPI", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "Total 40.000", "QRIS 40.000", "Terminal ID 0123"],
        "QRIS + NMID, satu barang": ["CAFE X", "LATTE 1 30.000", "TOTAL 30.000", "QRIS 30.000", "NMID ID1024358806544"],
        "QRIS + NMID + Terminal ID, tanpa kuantitas": ["TOKO MAJU", "ROTI 15.000", "SUSU 30.400", "TOTAL 45.400", "Pembayaran QRIS 45.400", "NMID ID1024358806544", "Terminal ID A01"],
        "Non Tunai (QRIS) sebaris": ["ALFAMART", "ROTI 15.000", "SUSU 30.400", "Total Belanja 45.400", "Non Tunai (QRIS) 45.400", "Berhasil"],
        "dua baris kuantitas tanpa baris total": ["KEDAI X", "NASI GORENG 2 50.000", "ES TEH 2 10.000", "QRIS", "Merchant PAN 9360001234567", "NMID ID1024358806544"],
        "transfer sebagai cara bayar": ["TOKO ABC", "BERAS 1 60.000", "MINYAK 1 20.000", "TOTAL 80.000", "Transfer 80.000", "Berita -"],
        "debit": ["INDOMARET", "ROTI TAWAR 1 15.000", "SUSU UHT 2 30.400", "TOTAL 45.400", "DEBIT BCA 45.400"],
    }

    async def test_stays_struk_belanja_with_items(self):
        for name, lines in self.CASES.items():
            with self.subTest(name):
                self.assertEqual((QrisReader().detect(textdoc(lines)), TransferReader().detect(textdoc(lines))), (0.0, 0.0))
                res = await read(lines)
                self.assertEqual(res.reader, "struk_belanja")
                self.assertGreaterEqual(len([l for l in res.parsed.doc.lines if l.kind == "item"]), 1 if "TOTAL 30.000" in lines else 2)

    def test_store_receipt_guard_rules(self):
        self.assertTrue(pc.looks_like_store_receipt(["ROTI 15.000", "TOTAL 15.000", "QRIS 15.000"]))                        # 1 barang + baris bayar sesudah total
        self.assertTrue(pc.looks_like_store_receipt(["ROTI 15.000", "TOTAL 15.000", "Pembayaran QRIS Rp 15.000"]))
        self.assertTrue(pc.looks_like_store_receipt(["KOPI SUSU 1 25.000", "ROTI 1 15.000"]))                               # 2 baris NAMA QTY HARGA
        self.assertTrue(pc.looks_like_store_receipt(["KOPI SUSU 1 x 25.000", "ROTI 2 x 15.000"]))
        self.assertFalse(pc.looks_like_store_receipt(["KOPI SUSU 1 25.000", "Pembayaran Berhasil"]))                        # satu baris kuantitas saja
        self.assertFalse(pc.looks_like_store_receipt(["TOTAL 15.000", "QRIS 15.000"]))                                      # tanpa barang
        self.assertFalse(pc.looks_like_store_receipt(["Pembayaran Berhasil", "QRIS", "Total Pembayaran Rp25.000", "QRIS Rp25.000"]))   # bukti: tanpa barang
        self.assertFalse(pc.looks_like_store_receipt(["ROTI 15.000", "QRIS 15.000", "TOTAL 15.000"]))                       # baris bayar harus sesudah total

    async def test_qris_proofs_with_totals_and_method_lines_are_not_store_receipts(self):
        proofs = {
            "metode sesudah total": ["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Nominal Rp25.000", "Biaya Layanan Rp500", "Total Rp25.500", "QRIS Rp25.500", "26/10/2026 08:12"],
            "satu penanda + terminal": ["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Nominal Rp25.000", "Terminal ID 0123", "26/10/2026 08:12"],
            "korpus": sample("sint-qris-1"),
        }
        for name, lines in proofs.items():
            with self.subTest(name):
                self.assertEqual((await read(lines)).reader, "qris.umum")

    async def test_note_with_cash_word_and_digit_does_not_make_a_transfer_a_store_receipt(self):
        lines = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Total Rp152.500", "Berita titip tunai 2 bulan"]
        self.assertFalse(pc.looks_like_store_receipt(lines))
        self.assertEqual((await read(lines)).reader, "transfer.umum")
        self.assertFalse(pc.looks_like_store_receipt(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Berita bayar tunai 2"]))   # berita berakhir angka
        self.assertFalse(pc.looks_like_store_receipt(["Pembayaran Berhasil", "QRIS", "Merchant KIOS", "Nominal Rp1.000", "Keterangan kembali 3"]))
        self.assertTrue(pc.looks_like_store_receipt(["TUNAI 50.000"]))
        self.assertTrue(pc.looks_like_store_receipt(["KEMBALI : 0"]))


class AmountsFalseWarningTests(unittest.IsolatedAsyncioTestCase):
    """Temuan 4: bukti sah tidak boleh diberi peringatan `selisih_nominal` palsu."""

    async def amounts(self, lines):
        res = await read(lines)
        a = res.parsed.doc.amounts
        return (a.subtotal, a.fee, a.discount, a.total), res

    async def test_two_fee_lines_are_summed(self):
        got, res = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Biaya Layanan Rp1.000", "Total Rp153.500", "26/10/2026 09:30"])
        self.assertEqual(got, (150000, 3500, 0, 153500))
        self.assertEqual((res.checks, res.parsed.doc.confidence["total"]), ([], "tinggi"))

    async def test_one_line_is_not_counted_twice_by_overlapping_labels(self):
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Biaya Admin Rp2.500"])       # "biaya admin" dan "biaya" cocok baris yang sama
        self.assertEqual(got, (150000, 2500, 0, 152500))
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Admin Rp2.500", "Fee Rp1.000"])
        self.assertEqual(got, (150000, 3500, 0, 153500))

    async def test_fee_label_without_value_does_not_borrow_the_next_label(self):
        got, res = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Biaya Admin", "Total Rp150.000"])
        self.assertEqual(got, (150000, 0, 0, 150000))
        self.assertEqual(res.checks, [])
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Biaya Admin", "Rp2.500", "Total Rp152.500"])    # label di atas nilai
        self.assertEqual(got, (150000, 2500, 0, 152500))

    async def test_discount_lines_are_read(self):
        for line in ("Diskon -Rp5.000", "Diskon Rp5.000", "Potongan Harga: -Rp 5.000", "Promo (Rp5.000)", "Voucher - 5.000", "Discount -IDR 5,000.00"):
            with self.subTest(line):
                got, res = await self.amounts(["Pembayaran Berhasil", "QRIS", "NMID ID1024358806544", "Merchant WARUNG X", "Nominal Rp25.000", line, "Total Rp20.000", "26/10/2026 08:12"])
                self.assertEqual(got, (25000, 0, 5000, 20000))
                self.assertEqual((res.checks, res.parsed.doc.confidence["total"]), ([], "tinggi"))

    async def test_total_is_computed_with_fee_and_discount_when_missing(self):
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Diskon Rp1.000"])
        self.assertEqual(got, (150000, 2500, 1000, 151500))

    async def test_a_discount_that_is_not_in_the_total_still_warns(self):
        _, res = await self.amounts(["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Nominal Rp25.000", "Diskon Rp5.000", "Total Rp25.000"])
        self.assertEqual({c.code for c in res.checks}, {"selisih_nominal"})

    async def test_tax_line_is_read(self):
        got, res = await self.amounts(["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Nominal Rp100.000", "PPN Rp11.000", "Total Rp111.000"])
        self.assertEqual((got[3], res.parsed.doc.amounts.tax, res.checks), (111000, 11000, []))

    async def test_total_biaya_is_not_the_total(self):
        got, res = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Total Biaya Rp2.500", "Total Rp152.500", "26/10/2026 09:30"])
        self.assertEqual((got, res.checks), ((150000, 2500, 0, 152500), []))
        got, res = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Total Biaya Rp2.500"])
        self.assertEqual((got, res.checks), ((150000, 2500, 0, 152500), []))
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000", "Biaya Admin Rp2.000", "Biaya Layanan Rp500", "Total Biaya Rp2.500", "Total Rp152.500"])
        self.assertEqual(got, (150000, 2500, 0, 152500))                  # jumlah baris biaya, bukan dihitung dua kali
        got, _ = await self.amounts(["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Biaya Admin Rp2.500", "Total Biaya Rp2.500"])
        self.assertEqual(got[3], None)                                    # hanya biaya: tidak ada nominal sama sekali

    async def test_total_labels_still_work(self):
        for line in ("Total Bayar Rp152.500", "Total Pembayaran: Rp152.500", "Total Rp152.500", "Total"):
            with self.subTest(line):
                lines = ["Transfer Berhasil", "Penerima BUDI", "Nominal Rp150.000", "Biaya Admin Rp2.500", line] + (["Rp152.500"] if line == "Total" else [])
                got, _ = await self.amounts(lines)
                self.assertEqual(got, (150000, 2500, 0, 152500))


class BrimoStyleLabelTests(unittest.IsolatedAsyncioTestCase):
    """Temuan 5: label umum "Nama Penerima", "Nomor Rekening", "Nomor Referensi" dan varian dekatnya."""

    BRIMO = ["BRImo", "Transaksi Berhasil", "26 Oktober 2026, 09:30:12 WIB", "Nomor Referensi", "123456789012", "Nama Penerima", "BUDI SANTOSO", "Bank Tujuan", "Bank BCA",
             "Nomor Rekening", "0123456789", "Nominal Rp150.000", "Biaya Admin Rp2.500", "Total Rp152.500"]

    async def test_brimo_layout_gets_name_account_and_reference(self):
        res = await read(self.BRIMO)
        d, s = res.parsed.doc, res.parsed.secrets
        self.assertEqual((res.reader, d.issuer, d.counterparty.name, d.counterparty.bank), ("transfer.umum", "brimo", "BUDI SANTOSO", "BCA"))
        self.assertEqual((s.account_number, d.counterparty.id_kind, d.counterparty.id_masked), ("0123456789", "rekening", "…6789"))
        self.assertEqual((s.ref_values, [r.masked for r in d.refs]), (["123456789012"], ["…9012"]))
        self.assertEqual((d.amounts.total, d.status, res.checks), (152500, "berhasil", []))
        blob = json.dumps(d.to_json()).replace(" ", "")
        self.assertNotIn("0123456789", blob)
        self.assertNotIn("123456789012", blob)

    async def test_label_variants(self):
        base = ["Transfer Berhasil", "BI-FAST", "Nominal Rp1.000"]       # dua penanda transfer: dibaca transfer.umum
        cases = [
            (["Nama Penerima BUDI SANTOSO"], lambda r: r.parsed.doc.counterparty.name, "BUDI SANTOSO"),
            (["Nama Tujuan BUDI SANTOSO"], lambda r: r.parsed.doc.counterparty.name, "BUDI SANTOSO"),
            (["Nomor Rekening 0123456789"], lambda r: r.parsed.secrets.account_number, "0123456789"),
            (["No Rekening 0123456789"], lambda r: r.parsed.secrets.account_number, "0123456789"),
            (["Nomor Rekening Tujuan 0123456789"], lambda r: r.parsed.secrets.account_number, "0123456789"),
            (["Rekening Penerima 0123456789"], lambda r: r.parsed.secrets.account_number, "0123456789"),
            (["Nomor Referensi 123456789012"], lambda r: r.parsed.secrets.ref_values, ["123456789012"]),
            (["No Ref 123456789012"], lambda r: r.parsed.secrets.ref_values, ["123456789012"]),
            (["Nomor Transaksi A1B2C3D4E5"], lambda r: r.parsed.secrets.ref_values, ["A1B2C3D4E5"]),
            (["Transaction ID TRX20261026"], lambda r: r.parsed.secrets.ref_values, ["TRX20261026"]),
            (["Bank Penerima Bank Mandiri"], lambda r: r.parsed.secrets.bank_code, "MANDIRI"),
            (["Berita Transfer bayar arisan"], lambda r: r.parsed.doc.note, "bayar arisan"),
        ]
        for extra, get, expect in cases:
            with self.subTest(extra[0]):
                self.assertEqual(get(await read(base + extra)), expect)

    async def test_incoming_with_name_label(self):
        res = await read(["Dana Masuk", "Nama Pengirim RINA", "Nominal Rp500.000"])
        self.assertEqual((res.parsed.doc.flow, res.parsed.doc.counterparty.name), ("masuk", "RINA"))

    async def test_name_labels_do_not_hide_destination_for_issuer_detection(self):
        self.assertIsNone(detect_issuer(["Nama Penerima BCA SAKTI", "Bank Penerima BCA", "Nama Tujuan OVO CELL"]))


# ── Perbaikan review A5, putaran 2 ──────────────────────────────────────────

class StatusWithCallToActionTests(unittest.IsolatedAsyncioTestCase):
    """Kegagalan sungguhan yang diikuti ajakan di baris yang sama ("Gagal, silakan coba lagi") tetap diblokir;
    hanya kalimat bersyarat/tanya yang memuat kata status (kata bersyarat SEBELUM kata status, atau "?" tepat sesudahnya) dilewati."""

    async def status(self, lines):
        res = await read(lines)
        return res.parsed.doc.status, {c.code: c.level for c in res.checks}

    async def test_real_failure_with_call_to_action_after_the_status_word_is_blocked(self):
        tail = ["Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp150.000"]
        for header in ("Transaksi Gagal, silakan coba lagi", "Transfer gagal. Hubungi 1500888", "Transfer Gagal - silahkan ulangi", "Gagal, hubungi CS",
                       "Transaksi gagal, jika saldo terpotong hubungi 14017", "Transfer gagal. Ada kendala?"):
            with self.subTest(header):
                self.assertEqual(await self.status([header, *tail]), ("gagal", {"status_gagal": "block"}))

    async def test_english_failure_with_please_is_blocked(self):
        self.assertEqual(await self.status(["Payment failed, please try again", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Nominal Rp25.000"]),
                         ("gagal", {"status_gagal": "block"}))
        self.assertEqual((await self.status(["Transaction failed. Contact us", "QRIS", "Merchant WARUNG X", "Nominal Rp25.000"]))[0], "gagal")

    async def test_body_line_with_call_to_action_after_the_status_word_is_blocked(self):
        banner = ["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer"]
        for line in ("Gagal, silakan ulangi", "Gagal. Hubungi 14017", "Gagal, jika saldo terpotong hubungi"):
            with self.subTest(line):
                self.assertEqual((await self.status([*banner, line, "Penerima BUDI", "Bank Tujuan BCA"]))[0], "gagal")

    async def test_pending_with_call_to_action_after_the_status_word_still_warns(self):
        self.assertEqual(await self.status(["Transfer diproses, mohon tunggu", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000"]),
                         ("pending", {"status_pending": "warn"}))

    async def test_conditional_or_question_sentences_are_still_skipped(self):
        base = ["BRImo", "26 Okt 2026 09:30", "Rp150.000", "Bukti Transfer", "Transaksi Berhasil", "Penerima BUDI", "Bank Tujuan BCA"]
        for footer in ("Jika gagal hubungi 14017", "Transaksi gagal? Hubungi kami", "Hubungi 14017 jika gagal", "Silakan hubungi kami bila gagal",
                       "Please contact us if failed", "Failed? Contact us", "Gagal? Hubungi CS", "Apakah transaksi gagal?", "Hubungi kami untuk transaksi gagal", "Untuk transaksi gagal, cek riwayat",
                       "Bila transaksi gagal, saldo kembali", "Jika pending cek lagi"):
            with self.subTest(footer):
                self.assertEqual(await self.status([*base, footer]), ("berhasil", {}))
                # Juga bila kalimat itu mendahului baris status: filter yang harus menolaknya, bukan urutan dokumen.
                self.assertEqual(await self.status([*base[:4], footer, *base[4:]]), ("berhasil", {}))

    async def test_conditional_sentence_in_the_first_lines_does_not_decide_the_status(self):
        self.assertEqual(await self.status(["Jika gagal hubungi 14017", "BRImo", "26 Okt 2026 09:30", "Transaksi Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000"]),
                         ("berhasil", {}))

    def test_read_status_unit_rules(self):
        cases = [(["Transfer Gagal, silakan coba lagi"], "gagal"), (["Gagal? Hubungi kami"], "tidak_diketahui"), (["Apakah gagal?"], "tidak_diketahui"),
                 (["Gagal ?"], "tidak_diketahui"), (["Gagal. Ada kendala?"], "gagal"), (["Berhasil, jika ada kendala hubungi kami"], "berhasil"),
                 (["Jika berhasil, silakan cek saldo"], "tidak_diketahui"), (["Please try again, failed"], "tidak_diketahui"),
                 (["Hubungi kami. Gagal"], "tidak_diketahui"), (["Tidak berhasil, silakan ulangi"], "gagal"),
                 (["Untuk transaksi gagal, cek riwayat"], "tidak_diketahui"), (["Gagal untuk rekening ini"], "gagal")]
        for lines, expect in cases:
            with self.subTest(lines):
                self.assertEqual(pc.read_status(lines), expect)


class StoreReceiptGuardDoesNotVetoProofsTests(unittest.IsolatedAsyncioTestCase):
    """Aturan struk belanja baru (baris cara bayar, kuantitas) tidak boleh menolak bukti QRIS/transfer sungguhan."""

    PROOFS = {
        "QRIS gagal: Subtotal + Total + QRIS Rp": (["Pembayaran Gagal", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Subtotal Rp25.000", "Total Rp25.000", "QRIS Rp25.000"], "qris.umum"),
        "QRIS gagal: Harga + Total + QRIS RRN": (["Pembayaran Gagal", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Harga Rp25.000", "Total Rp25.000", "QRIS RRN 000151856123", "26/10/2026 08:12"], "qris.umum"),
        "QRIS: Tip + Total + QRIS Ref": (["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Tip Rp2.000", "Total Rp27.000", "QRIS Ref 123456789012", "26/10/2026 08:12"], "qris.umum"),
        "QRIS: Tagihan + Total Bayar + QRIS RRN": (["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Tagihan Rp25.000", "Total Bayar Rp25.000", "QRIS RRN 000151856123"], "qris.umum"),
        "QRIS: Harga + Total + Debit dari Tahapan": (["Pembayaran QRIS Berhasil", "Merchant WARUNG X", "NMID ID1024358806544", "Harga Rp25.000", "Total Rp25.000", "Debit dari Tahapan 0123456789"], "qris.umum"),
        "top-up: Top Up + Total + Debit BCA ****1234": (["Top Up Berhasil", "GoPay", "Top Up Rp100.000", "Biaya Admin Rp1.000", "Total Rp101.000", "Debit BCA ****1234", "26/10/2026 10:15"], "transfer.umum"),
        "top-up: Isi Saldo + Total + Debit": (["Isi Saldo Berhasil", "OVO", "Isi Saldo Rp100.000", "Total Rp100.000", "Debit BCA 1234", "26/10/2026 10:15"], "transfer.umum"),
        "transfer: rekening 3-3-4 dengan nama bank": (["Transfer Berhasil", "Rekening Sumber", "BCA 123 456 7890", "Rekening Tujuan", "BRI 012 345 6789", "Penerima BUDI", "Nominal Rp150.000", "26/10/2026 09:30"], "transfer.umum"),
        "transfer: rekening 3-3-4 dan 4-4-4": (["Transfer Berhasil", "Rekening Sumber", "BCA 123 456 7890", "Rekening Tujuan", "MANDIRI 1234 5678 9012", "Penerima BUDI", "Nominal Rp150.000"], "transfer.umum"),
        "transfer: rekening 2 dan 3 digit": (["Transfer Berhasil", "Rekening Tujuan", "BRI 12 345 6789", "Penerima BUDI", "Nominal Rp150.000", "Bank Tujuan BRI"], "transfer.umum"),
    }

    async def test_real_proofs_stay_with_their_proof_reader(self):
        for name, (lines, reader) in self.PROOFS.items():
            with self.subTest(name):
                self.assertFalse(pc.looks_like_store_receipt(pc.clean_lines(lines)))
                self.assertEqual((await read(lines)).reader, reader)

    async def test_failed_qris_with_payment_method_line_is_still_blocked(self):
        res = await read(self.PROOFS["QRIS gagal: Subtotal + Total + QRIS Rp"][0])
        self.assertEqual((res.reader, res.parsed.doc.status, {c.code: c.level for c in res.checks}), ("qris.umum", "gagal", {"status_gagal": "block"}))

    def test_payment_line_amount_must_equal_the_total(self):
        receipt = ["KOPI SUSU 25.000", "Total 25.000"]
        for line, expect in [("QRIS 25.000", True), ("Pembayaran QRIS Rp 25.000", True), ("Non Tunai (QRIS) 25.000", True), ("DEBIT BCA 25.000", True),
                             ("QRIS RRN 000151856123", False), ("QRIS Ref 123456789012", False), ("Debit BCA ****1234", False), ("QRIS 999", False),
                             ("QRIS 30.000", False), ("QRIS", False)]:
            with self.subTest(line):
                self.assertEqual(pc.looks_like_store_receipt([*receipt, line]), expect)
        self.assertTrue(pc.looks_like_store_receipt(["KOPI SUSU 25.000", "Total", "25.000", "QRIS 25.000"]))       # nilai total di baris bawah label
        self.assertFalse(pc.looks_like_store_receipt(["KOPI SUSU 25.000", "Total", "QRIS 25.000"]))                  # total tak terbaca: tidak bisa dicocokkan

    def test_labelled_lines_are_never_items(self):
        for head in ("Subtotal", "Sub Total", "Harga", "Tip", "Tagihan", "Top Up", "Topup", "Isi Saldo", "Saldo", "Nominal", "Jumlah", "Kode Unik", "Cashback", "Pembayaran", "Biaya Layanan"):
            with self.subTest(head):
                self.assertFalse(pc.looks_like_store_receipt([f"{head} Rp25.000", "Total Rp25.000", "QRIS Rp25.000"]))
                self.assertFalse(pc._is_item_line(f"{head} Rp25.000"))
        self.assertTrue(pc._is_item_line("KOPI SUSU Rp25.000"))
        self.assertTrue(pc._is_item_line("Tipe Roti 25.000"))                           # "Tip" hanya kata utuh, bukan awalan kata lain
        self.assertTrue(pc.looks_like_store_receipt(["Tipe Roti 25.000", "Total 25.000", "QRIS 25.000"]))

    def test_quantity_rule_needs_a_small_quantity_and_a_priced_amount(self):
        for lines in (["KOPI SUSU 1 25.000", "ROTI 1 15.000"], ["KOPI SUSU 2 x 25.000", "ROTI 12 15.000"], ["TEPUNG 0,5 12.500", "GULA 1,5 18.000"],
                      ["KOPI SUSU 1 Rp25.000", "ROTI 3 Rp15.000"]):
            with self.subTest(lines):
                self.assertTrue(pc.looks_like_store_receipt(lines))
        for lines in (["BCA 123 456 7890", "BRI 012 345 6789"], ["BCA 1234 5678 9012", "BRI 1234 5678 9012"], ["BCA 12 3456 7890", "BRI 01 2345 6789"],
                      ["BCA 123 456.789", "BRI 012 345.678"], ["TELKOMSEL 081 234 5678", "XL 087 765 4321"],
                      ["BCA 12 34567", "BRI 01 23456"], ["BCA 012 34 5678", "BRI 012 34 5679"]):          # harga tanpa pemisah ribuan: bukan harga
            with self.subTest(lines):
                self.assertFalse(pc.looks_like_store_receipt(lines))

    async def test_small_store_receipts_keep_their_items(self):
        for name, lines in StoreReceiptWithFewItemsTests.CASES.items():
            with self.subTest(name):
                self.assertTrue(pc.looks_like_store_receipt(pc.clean_lines(lines)))
                self.assertEqual((await read(lines)).reader, "struk_belanja")
        for lines in (["KOPI KENANGAN", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "Total 40.000", "QRIS 40.000", "Pembayaran Berhasil"],
                      ["WARUNG KOPI", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "Total 40.000", "QRIS 40.000", "Terminal ID 0123"],
                      ["WARUNG KOPI", "KOPI SUSU 1 25.000", "ROTI 1 15.000", "Total 40.000", "QRIS 40.000", "NMID ID1024358806544"]):
            self.assertEqual((await read(lines)).reader, "struk_belanja")


class CashLineAndTipFollowUpTests(unittest.IsolatedAsyncioTestCase):
    """Ditemukan saat membandingkan probe putaran 2: baris tunai dengan akhiran mata uang, dan Tip pada bukti sah."""

    async def test_cash_lines_with_a_currency_suffix_are_cash_lines(self):
        for line in ("TUNAI 50.000 IDR", "KEMBALI 35.000 IDR", "Tunai IDR 50,000", "Tunai Rp 50.000", "KEMBALI : 0", "TUNAI 50.000", "Non Tunai (QRIS) 45.400"):
            with self.subTest(line):
                self.assertTrue(pc.looks_like_store_receipt([line]))
        for line in ("Kembali ke Beranda", "Berita titip tunai 2 bulan", "Keterangan tunai Rp50.000", "Bayar tunai 2 kali", "Tunai"):
            with self.subTest(line):
                self.assertFalse(pc.looks_like_store_receipt([line]))

    async def test_store_receipt_with_cash_and_currency_suffix_stays_struk_belanja(self):
        lines = ["TOKO X", "ROTI 15.000", "Total 15.000", "TUNAI 50.000 IDR", "KEMBALI 35.000 IDR", "QRIS NMID ID1024358806544"]
        self.assertEqual((await read(lines)).reader, "struk_belanja")

    async def test_tip_is_an_extra_charge_not_a_mismatch(self):
        lines = ["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "NMID ID1024358806544", "Nominal Rp25.000", "Tip Rp2.000", "Total Rp27.000", "QRIS Ref 123456789012", "26/10/2026 08:12"]
        res = await read(lines)
        a = res.parsed.doc.amounts
        self.assertEqual((res.reader, a.subtotal, a.fee, a.total, res.checks, res.parsed.doc.confidence["total"]), ("qris.umum", 25000, 2000, 27000, [], "tinggi"))
        res = await read(["Pembayaran Berhasil", "QRIS", "Merchant WARUNG X", "Nominal Rp25.000", "Tip Rp2.000", "Total Rp25.000"])
        self.assertEqual({c.code for c in res.checks}, {"selisih_nominal"})            # tip yang tidak masuk total tetap peringatan
