"""Task A14 ronde 1: kalibrasi pembaca dengan 7 bukti asli pertama (Jago Syariah 5, BYOND by BSI 1, Livin' 1).

Baris di sini adalah baris TERSAMAR dari korpus (`fixtures/kotak/corpus.json`, nama samaran) atau varian sintetisnya;
gambar aslinya tidak pernah di-commit."""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import json, unittest
from datetime import date
from pathlib import Path
from app.scripts.kotak_corpus import evaluate, gate_failures, receipt_samples, sample_context
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.readers import profiles
from app.services.kotak_struk.readers.profiles import PROFILES, detect_issuer
from app.services.kotak_struk.readers.qris import QrisReader
from app.services.kotak_struk.readers.struk_belanja import StrukBelanjaReader
from app.services.kotak_struk.readers.transfer import TransferReader
from app.services.kotak_struk.registry import looks_like_proof, read_document
from app.services.receipt_parser import amounts_in, parse_receipt

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
BY_ID = {s["id"]: s for s in CORPUS}
REAL_IDS = ["real-jago-qris-01", "real-jago-transfer-01", "real-jago-pln-01", "real-jago-pulsa-01",
            "real-jago-sendiri-01", "real-bsi-sendiri-01", "real-livin-qris-01"]
FIX = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())
USER = "ANDI PRATAMA"
CTX = ParseContext(today=date(2026, 10, 30), user_name=USER)
JAGO_FOOTER = ["Resi ini merupakan bukti transaksi yang sah", "Ada pertanyaan?", "Hubungi Tanya Jago 24/7"]


def lines_of(sample_id):
    return list(BY_ID[sample_id]["lines"])


def textdoc(lines):
    return TextDoc(lines=list(lines), kind="image")


async def read(lines, ctx=CTX, enabled=True):
    return await read_document(textdoc(lines), ctx, proofs_enabled=enabled)


def jago_transfer(name_lines, provider, *, status_lines=(), footer=JAGO_FOOTER):
    """Bukti transfer Jago sintetis dalam tata letak sampel asli (nomor fiktif)."""
    return ["Jago Syariah", *name_lines, provider, "Rp75.000", "ID Transaksi", "…1A2B", *status_lines, "Sumber akun",
            "RINA WULANDARI", "Jago …0001", "Tanggal & waktu transaksi", "28 Okt 2026, 10:05 WIB", *footer]


class RealSamplesTests(unittest.IsolatedAsyncioTestCase):
    """Ketujuh sampel nyata terbaca sesuai kebenarannya (expect diisi tangan dari gambar dan jawaban pemilik)."""

    def test_samples_are_in_the_corpus_unreviewed_with_pseudonyms(self):
        for sample_id in REAL_IDS:
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                self.assertTrue(s["real"])
                self.assertIs(s["reviewed"], False)            # pemilik produk yang meninjau dan membaliknya
                self.assertEqual(s["today"], "2026-10-30")
                self.assertEqual(s["user_name"], USER)

    def test_every_field_reads_as_the_truth_with_the_flag_on(self):
        samples = [BY_ID[i] for i in REAL_IDS]
        result = evaluate(samples)
        bad = {row["id"]: {k: f for k, f in row["fields"].items() if not f["ok"]} for row in result["rows"] if not row["ok"]}
        self.assertEqual(bad, {})
        self.assertEqual(result["struk_as_proof"], [])

    def test_release_gate_passes_once_reviewed(self):
        reviewed = [{**BY_ID[i], "reviewed": True} for i in REAL_IDS]
        self.assertEqual(gate_failures(evaluate(reviewed + receipt_samples())), [])

    async def test_flag_off_reads_the_amount_and_never_stores_proof_text(self):
        expected = {"real-jago-qris-01": 25000, "real-jago-transfer-01": 500000, "real-jago-pln-01": 102750,
                    "real-jago-pulsa-01": 154958, "real-jago-sendiri-01": 100000, "real-bsi-sendiri-01": 52500,
                    "real-livin-qris-01": 25000}
        for sample_id, total in expected.items():
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                res = await read(s["lines"], sample_context(s), enabled=False)
                self.assertEqual(res.reader, "tidak_dikenali")          # bukti aplikasi bank bukan struk belanja
                self.assertEqual(res.parsed.doc.amounts.total, total)
                self.assertEqual(res.parsed.doc.lines, [])
                self.assertNotIn("status_gagal", [c.code for c in res.checks])
                self.assertTrue(looks_like_proof(textdoc(s["lines"])))   # teks, nama, rincian tidak disimpan


class FlagOffAppReceiptTotalTests(unittest.IsolatedAsyncioTestCase):
    """Saklar mati: resi aplikasi bank dibaca pembaca tidak dikenali; totalnya dari label total atau nominal utama resi
    (keyakinan `sedang`), bukan nominal Rp terbesar."""

    async def test_labelled_or_headline_total(self):
        for sample_id, total in (("real-bsi-sendiri-01", 52500), ("real-livin-qris-01", 25000),
                                 ("real-jago-pln-01", 102750), ("real-jago-qris-01", 25000),
                                 ("real-jago-transfer-01", 500000)):
            with self.subTest(sample_id):
                d = (await read(lines_of(sample_id), enabled=False)).parsed.doc
                self.assertEqual((d.amounts.total, d.confidence["total"]), (total, "sedang"))

    async def test_a_bigger_balance_line_is_not_the_total(self):
        lines = ["BYOND", "by BSI", "Transaksi Berhasil", "Nominal Transfer Rp 50.000", "Rekening Sumber BUDI",
                 "Total Rp 52.500", "Saldo Rp 1.000.000"]
        d = (await read(lines, enabled=False)).parsed.doc
        self.assertEqual((d.doc_type, d.amounts.total, d.confidence["total"]), ("tidak_dikenali", 52500, "sedang"))

    async def test_without_a_total_label_the_biggest_rp_amount_stays(self):
        lines = ["BYOND", "by BSI", "Rekening Sumber BUDI", "Rp 5.000", "Rp 7.500"]
        d = (await read(lines, enabled=False)).parsed.doc
        self.assertEqual((d.amounts.total, d.confidence["total"]), (7500, "rendah"))


class MaskedNumbersAreNotAmountsTests(unittest.TestCase):
    """Angka yang tercetak tersamar ("…0001", "••••4321", "*********9876") adalah ekor nomor rekening/HP, bukan nominal.
    Livin' mencetak "Bank Mandiri-…dddd" sendiri; baris korpus tersamar memakai bentuk yang sama."""

    def test_masked_tails_are_not_amounts(self):
        for line in ("Jago …0001", "…0001", "GoPay·…7890  6", "Bank Mandiri-…4321", "Terminal  *********9876",
                     "Kartu ****1234", "Rekening ••••4321", "BCA •• 4567"):
            with self.subTest(line):
                self.assertEqual(amounts_in(line), [])

    def test_amounts_next_to_single_symbols_stay_amounts(self):
        self.assertEqual(amounts_in("Rp25.000"), [25000])
        self.assertEqual(amounts_in("KOPI *15.000"), [15000])
        self.assertEqual(amounts_in("Total • Rp52.500"), [52500])
        self.assertEqual(amounts_in("ROTI • 12.500"), [12500])
        self.assertEqual(amounts_in("Harga… 12.500"), [12500])

    def test_masked_gopay_line_gives_no_fake_total(self):
        rp = parse_receipt(lines_of("real-jago-transfer-01"), date(2026, 10, 30))
        self.assertEqual(rp.total, 500000)


class JagoQrisTests(unittest.IsolatedAsyncioTestCase):
    def test_jago_labels_count_as_qris_markers(self):
        self.assertEqual(QrisReader().detect(textdoc(lines_of("real-jago-qris-01"))), 0.95)
        # "PAN Merchant" + "ID Terminal" saja (urutan kata Jago) sudah dua penanda.
        self.assertEqual(QrisReader().detect(textdoc(["Toko A", "Rp10.000", "PAN Merchant", "…0001", "ID Terminal", "A01"])),
                         0.95)

    async def test_merchant_city_time_status_from_the_jago_layout(self):
        d = (await read(lines_of("real-jago-qris-01"))).parsed.doc
        self.assertEqual((d.doc_type, d.issuer, d.status, d.flow), ("qris", "jago", "berhasil", "keluar"))
        self.assertEqual((d.counterparty.name, d.counterparty.city), ("RM AJO PIAMAN", "BANDUNG"))
        self.assertEqual(d.paid_at.isoformat(), "2026-10-29T19:15:00+07:00")
        self.assertEqual(d.amounts.total, 25000)
        self.assertEqual(d.confidence["total"], "sedang")      # nominal besar di bawah nama, tanpa label

    async def test_status_word_beside_the_id_is_not_part_of_the_reference(self):
        lines = ["Jago Syariah", "TOKO A  TA", "Rp10.000", "ID Transaksi", "123456-ABCD-EFGHIJ  Sukses", "Nama Acquirer",
                 "Bank X", "PAN Merchant", "…0001", "Tanggal & waktu transaksi", "28 Okt 2026, 10:05 WIB"]
        res = await read(lines)
        self.assertEqual(res.parsed.secrets.ref_values, ["123456ABCDEFGHIJ"])
        self.assertEqual([r.masked for r in res.parsed.doc.refs], ["…GHIJ"])
        self.assertEqual(res.parsed.doc.status, "berhasil")


class JagoTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_transfer_to_gopay(self):
        res = await read(lines_of("real-jago-transfer-01"))
        d = res.parsed.doc
        self.assertEqual((res.reader, d.issuer, d.flow, d.amounts.total), ("transfer.umum", "jago", "keluar", 500000))
        self.assertEqual(d.counterparty.name, "SITI AMINAH")      # inisial avatar "SA" dibuang
        self.assertEqual(d.counterparty.bank, "GOPAY")
        self.assertEqual(d.counterparty.id_kind, "rekening")
        self.assertEqual(res.parsed.secrets.account_number, "…6390")   # nomor di baris "GoPay·…", ikon "6" tidak ikut
        self.assertEqual(d.status, "berhasil")                     # kaki "Resi ini merupakan bukti transaksi yang sah"
        self.assertEqual(d.paid_at.isoformat(), "2026-10-29T23:23:00+07:00")

    async def test_unmasked_number_on_the_provider_line_stays_secret(self):
        res = await read(jago_transfer(["BUDI SANTOSO  BS"], "GoPay·081234567890  6"))
        self.assertEqual(res.parsed.secrets.account_number, "081234567890")
        self.assertEqual(res.parsed.doc.counterparty.id_masked, "…7890")
        self.assertNotIn("081234567890", json.dumps(res.parsed.doc.to_json()))

    async def test_own_account_with_the_name_on_two_lines(self):
        d = (await read(lines_of("real-jago-sendiri-01"))).parsed.doc
        self.assertEqual((d.doc_type, d.issuer), ("transfer", "jago"))   # "Mandiri·…" = bank tujuan, bukan aplikasinya
        self.assertEqual(d.counterparty.name, USER)
        self.assertEqual(d.counterparty.bank, "MANDIRI")
        self.assertEqual(d.flow, "antar_rekening_sendiri")

    async def test_unrecognised_avatar_keeps_only_the_first_name_line(self):
        d = (await read(jago_transfer(["BUDI SANTOSO", "XYZ"], "BCA·…1234"))).parsed.doc
        self.assertEqual(d.counterparty.name, "BUDI SANTOSO")
        d = (await read(jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234"))).parsed.doc
        self.assertEqual((d.counterparty.name, d.counterparty.bank), ("BUDI SANTOSO", "BCA"))
        # Huruf pendek di ujung nama yang bukan inisialnya adalah bagian nama.
        lines = ["Jago Syariah", "KOPI KITA ID", "BANDUNG", "Rp10.000", "PAN Merchant", "…0001", "ID Terminal", "A01"]
        self.assertEqual((await read(lines)).parsed.doc.counterparty.name, "KOPI KITA ID")

    async def test_success_footer_never_hides_a_failure_or_pending(self):
        for status_line, expected, blocked in (("Transaksi Gagal", "gagal", True), ("Gagal", "gagal", True),
                                               ("Sedang diproses", "pending", False)):
            with self.subTest(status_line):
                res = await read(jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", status_lines=[status_line]))
                self.assertEqual(res.parsed.doc.status, expected)
                self.assertEqual("status_gagal" in [c.code for c in res.checks], blocked)
        for enabled in (True, False):    # saklar mati: judul gagal di badan tetap memblokir
            with self.subTest(enabled=enabled):
                res = await read(jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", status_lines=["Transaksi Gagal"]),
                                 enabled=enabled)
                self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_without_the_footer_the_status_stays_unknown(self):
        res = await read(jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", footer=["Ada pertanyaan?"]))
        self.assertEqual(res.parsed.doc.status, "tidak_diketahui")

    async def test_the_footer_counts_only_for_the_app_that_prints_it(self):
        lines = ["Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp75.000", "Resi ini merupakan bukti transaksi yang sah"]
        self.assertEqual((await read(lines)).parsed.doc.status, "tidak_diketahui")
        jago = next(p for p in PROFILES if p.key == "jago")
        self.assertTrue(jago.party_on_top and jago.done_phrases)
        self.assertEqual([p.key for p in PROFILES if p.party_on_top or p.done_phrases], ["jago"])

    def test_biller_is_not_a_transfer(self):
        for sample_id in ("real-jago-pln-01", "real-jago-pulsa-01"):
            with self.subTest(sample_id):
                self.assertEqual(TransferReader().detect(textdoc(lines_of(sample_id))), 0.0)
                self.assertEqual(QrisReader().detect(textdoc(lines_of(sample_id))), 0.0)

    def test_money_providers(self):
        for name in ("GoPay", "Mandiri", "BCA", "Bank Jago Syariah", "OVO", "SeaBank", "BRI"):
            with self.subTest(name):
                self.assertTrue(profiles.is_money_provider(name))
        for name in ("PLN Prepaid", "Indosat", "Telkomsel", "BPJS Kesehatan", ""):
            with self.subTest(name):
                self.assertFalse(profiles.is_money_provider(name))

    def test_destination_bank_line_is_not_the_issuer(self):
        self.assertEqual(detect_issuer(pc.clean_lines(lines_of("real-jago-sendiri-01"))).key, "jago")
        self.assertEqual(detect_issuer(["Jago Syariah", "BUDI", "Mandiri · …4321"]).key, "jago")
        self.assertEqual(detect_issuer(pc.clean_lines(lines_of("real-bsi-sendiri-01"))).key, "bsi")


class BillsAreNotStoreReceiptsTests(unittest.IsolatedAsyncioTestCase):
    """Tagihan/pulsa dari aplikasi bank (FS-2: `tagihan`) dibaca `tidak_dikenali` dengan total yang didebet; bukan struk
    belanja, supaya PPn/PPj/Materai tidak menjadi baris barang di form Catat."""

    async def test_pln_prepaid_total_is_the_debited_amount(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                res = await read(lines_of("real-jago-pln-01"), enabled=enabled)
                d = res.parsed.doc
                self.assertEqual((res.reader, d.doc_type, d.amounts.total), ("tidak_dikenali", "tidak_dikenali", 102750))
                self.assertEqual(d.lines, [])
                self.assertEqual(d.paid_at.date(), date(2026, 10, 29))

    async def test_pulsa(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                d = (await read(lines_of("real-jago-pulsa-01"), enabled=enabled)).parsed.doc
                self.assertEqual((d.doc_type, d.amounts.total), ("tidak_dikenali", 154958))

    def test_app_receipt_rule(self):
        self.assertTrue(pc.is_app_receipt(lines_of("real-jago-pln-01")))
        self.assertLess(StrukBelanjaReader().detect(textdoc(lines_of("real-jago-pln-01"))), 0.5)
        # Aplikasi di baris logo + label rekening sumber; tanpa salah satunya bukan aturan ini.
        self.assertFalse(pc.is_app_receipt(["INDOMARET", "Sumber Dana", "ROTI 10.000", "SUSU 12.000", "TOTAL 22.000"]))
        self.assertFalse(pc.is_app_receipt(["Jago Syariah", "PPj Rp2.913", "Total Bayar Rp 102.750"]))
        self.assertFalse(pc.is_app_receipt(["TOKO MAJU", "DEBIT BCA", "ROTI 10.000", "TOTAL 10.000"]))
        # Bank di bawah (kartu debit, slip EDC) bukan logo aplikasi.
        self.assertFalse(pc.is_app_receipt(["TOKO MAJU", "ROTI 10.000", "SUSU 12.000", "TOTAL 22.000", "DEBIT BCA",
                                            "Sumber Dana TABUNGAN"]))

    def test_store_receipts_stay_store_receipts(self):
        for rec in FIX["receipts"]:
            with self.subTest(rec.get("name")):
                self.assertFalse(pc.is_app_receipt(rec["lines"]))
                self.assertGreaterEqual(StrukBelanjaReader().detect(textdoc(rec["lines"])), 0.5)


class NameOnTwoLinesTests(unittest.IsolatedAsyncioTestCase):
    """BYOND mencetak nilai rata kanan; nama panjang terbelah, baris pertamanya di atas baris label."""

    async def test_bsi_own_account(self):
        d = (await read(lines_of("real-bsi-sendiri-01"))).parsed.doc
        self.assertEqual((d.doc_type, d.issuer, d.amounts.total), ("transfer", "bsi", 52500))
        self.assertEqual(d.counterparty.name, USER)
        self.assertEqual(d.flow, "antar_rekening_sendiri")

    async def test_only_an_orphan_name_line_is_joined(self):
        cases = {
            # baris di atas = nilai label lain, judul status, bank, nominal, atau huruf kecil: tidak digabung
            "label value": ["Transfer Berhasil", "Nominal Rp50.000", "Keterangan", "BAYAR", "Penerima BUDI", "Bank Tujuan BCA"],
            "status title": ["TRANSFER BERHASIL", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000"],
            "bank": ["Transfer Berhasil", "BANK BCA", "Penerima BUDI", "Nominal Rp50.000"],
            "app": ["BRIMO", "Transfer Berhasil", "Nominal Rp50.000", "BRIMO", "Penerima BUDI"],
            "lowercase": ["Transfer Berhasil", "Nominal Rp50.000", "Andi", "Penerima BUDI", "Bank Tujuan BCA"],
            "label line": ["Transfer Berhasil", "Nominal Rp50.000", "BERITA", "Penerima BUDI", "Bank Tujuan BCA"],
            "document word": ["Pembayaran Berhasil", "QRIS", "Merchant BUDI", "Nominal Rp50.000"],
        }
        for name, lines in cases.items():
            with self.subTest(name):
                self.assertEqual((await read(lines)).parsed.doc.counterparty.name, "BUDI")
        joined = ["Transfer Berhasil", "Nominal Rp50.000", "ANDI", "Nama Penerima PRATAMA", "Bank Tujuan BCA"]
        self.assertEqual((await read(joined)).parsed.doc.counterparty.name, "ANDI PRATAMA")


class LivinStaysCorrectTests(unittest.IsolatedAsyncioTestCase):
    async def test_livin_qris(self):
        d = (await read(lines_of("real-livin-qris-01"))).parsed.doc
        self.assertEqual((d.doc_type, d.issuer, d.counterparty.name, d.amounts.total, d.status),
                         ("qris", "livin", "POINT COFFEE INDOMARET", 25000, "berhasil"))


if __name__ == "__main__":
    unittest.main()


# ── Fix round 1 (review A14r1) ──────────────────────────────────────────────

JAGO_FAILED_SENTENCES = {
    "Transaksi gagal, dana dikembalikan ke saldo kamu": "gagal",
    "Transfer kamu gagal diproses, dana dikembalikan ke akun": "gagal",
    "Transaksi tidak berhasil": "gagal",
    "Transaksi kamu sedang diproses bank tujuan": "pending",
}


class JagoFailureWithFooterTests(unittest.IsolatedAsyncioTestCase):
    """I1: kalimat gagal/pending di badan bukti Jago tetap memblokir/memperingatkan dengan saklar menyala; kalimat resi
    hanya berarti berhasil bila tidak ada kata gagal/pending/negatif sama sekali."""

    async def test_failure_or_pending_sentence_blocks_or_warns_in_both_modes(self):
        for sentence, expected in JAGO_FAILED_SENTENCES.items():
            for footer in (JAGO_FOOTER, ["Ada pertanyaan?"]):
                for enabled in (True, False):
                    with self.subTest(sentence, footer=bool(footer[0].startswith("Resi")), enabled=enabled):
                        lines = jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", footer=[sentence, *footer])
                        res = await read(lines, enabled=enabled)
                        codes = [c.code for c in res.checks]
                        self.assertEqual(res.parsed.doc.status, expected)
                        self.assertIn("status_gagal" if expected == "gagal" else "status_pending", codes)

    async def test_failure_sentence_also_counts_on_a_jago_qris(self):
        lines = ["Jago Syariah", "TOKO A  TA", "Rp10.000", "ID Transaksi", "…1A2B", "PAN Merchant", "…0001", "ID Terminal",
                 "A01", "Transaksi gagal, dana dikembalikan ke saldo kamu", *JAGO_FOOTER]
        res = await read(lines)
        self.assertEqual((res.reader, res.parsed.doc.status), ("qris.umum", "gagal"))
        self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_negative_words_keep_the_footer_from_meaning_success(self):
        for extra in (["Dibatalkan"], ["Ditolak"], ["Menunggu"], ["Dikembalikan"], ["Pembayaran tertunda"],
                      ["Transaksi dibatalkan oleh sistem"]):
            with self.subTest(extra[0]):
                lines = jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", status_lines=extra)
                self.assertNotEqual((await read(lines)).parsed.doc.status, "berhasil")
        lines = jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234")
        self.assertEqual((await read(lines)).parsed.doc.status, "berhasil")


class StatusWordInANameAboveAFailureTests(unittest.IsolatedAsyncioTestCase):
    """Sesudah I1, judul gagal di badan juga dibaca pembaca bukti: kata status di nama toko di judul ("TOKO SUKSES MAKMUR")
    tidak lagi menutupi "Pembayaran Gagal" di bawahnya (bentuk N2 dengan judul status)."""

    async def test_failure_title_below_a_name_with_sukses(self):
        res = await read(["QRIS", "TOKO SUKSES MAKMUR", "Rp25.000", "26/10/2026 08:12", "Pembayaran Gagal"])
        self.assertEqual((res.reader, res.parsed.doc.status), ("qris.umum", "gagal"))
        self.assertIn("status_gagal", [c.code for c in res.checks])


class AppLogoLineTests(unittest.IsolatedAsyncioTestCase):
    """m3: logo aplikasi = baris berisi nama aplikasi saja (boleh "Syariah", "by", "Mobile", "Bank"); nama toko yang memuat
    kata bank tetap struk belanja."""

    async def test_store_names_with_a_bank_word_stay_store_receipts(self):
        cases = [
            ["TOKO MANDIRI JAYA", "Jl. Merdeka 10 Bandung", "29/10/2026 19:20", "ROTI TAWAR 1 x 15.000 15.000",
             "SUSU UHT 2 x 6.000 12.000", "TELUR 1 x 28.000 28.000", "TOTAL 55.000", "Non Tunai (QRIS) 55.000",
             "Sumber Dana : GOPAY", "Transaksi berhasil", "Terima kasih"],
            ["BAKSO MANDIRI", "Cab. Dago", "Bakso Urat 2 x 20.000 40.000", "Es Jeruk 2 x 7.000 14.000", "Sub Total 54.000",
             "Pajak 5.400", "Total 59.400", "Rekening Sumber BCA ****1234"],
            ["KANTIN BNI", "Gedung BNI Lt 2", "Nasi Goreng 25.000", "Es Teh 5.000", "Kerupuk 3.000", "Rp 33.000",
             "Sumber Dana: Debit BNI"],
        ]
        for lines in cases:
            with self.subTest(lines[0]):
                self.assertFalse(pc.is_app_receipt(lines))
                for enabled in (True, False):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.reader, "struk_belanja")
                    self.assertGreaterEqual(len(res.parsed.doc.lines), 2)

    def test_app_logo_lines(self):
        for logo in ("Jago Syariah", "BYOND", "by BSI", "livin'  by mandiri", "GoPay", "Bank Jago", "BCA mobile"):
            with self.subTest(logo):
                self.assertTrue(pc.is_app_receipt([logo, "Sumber Dana", "Rp10.000"]))
        for name in ("JAGO COFFEE", "TOKO MANDIRI JAYA", "KANTIN BNI", "BANK SAMPAH"):
            with self.subTest(name):
                self.assertFalse(pc.is_app_receipt([name, "Sumber Dana", "Rp10.000"]))

    async def test_a_store_named_like_an_app_has_no_header_party(self):
        lines = ["JAGO COFFEE", "Mitra Bank · 0812345678", "Rp45.000", "Kopi Susu 2 x 22.500 45.000", "Total 45.000"]
        self.assertIsNone(pc.read_header_party(pc.clean_lines(lines), next(p for p in PROFILES if p.key == "jago")))
        self.assertEqual((await read(lines)).reader, "struk_belanja")


class DotLeaderAmountsTests(unittest.TestCase):
    """m4: "…" atau "•••" sebagai titik penuntun sebelum nominal berpemisah ribuan tetap nominal."""

    def test_leaders_before_thousands_grouped_amounts(self):
        self.assertEqual(amounts_in("TOTAL…27.000"), [27000])
        self.assertEqual(amounts_in("TOTAL ••• 27.000"), [27000])
        self.assertEqual(amounts_in("ROTI TAWAR…15.000"), [15000])
        self.assertEqual(amounts_in("Bank Mandiri-…4321"), [])
        self.assertEqual(amounts_in("Kartu ****1234"), [])
        rp = parse_receipt(["TOKO A", "ROTI TAWAR…15.000", "SUSU…12.000", "TOTAL…27.000"], date(2026, 10, 30))
        self.assertEqual(rp.total, 27000)
        rp = parse_receipt(["TOKO A", "ROTI •• 15.000", "SUSU •• 12.000", "TOTAL ••• 27.000"], date(2026, 10, 30))
        self.assertEqual((rp.total, rp.confidence), (27000, "tinggi"))


class StatusLineUnderTheLogoTests(unittest.IsolatedAsyncioTestCase):
    """m5: judul status di bawah logo bukan nama pihak lawan; nama yang memuat kata status tetap nama."""

    async def test_status_title_is_not_the_name(self):
        lines = ["Jago Syariah", "Transfer Sedang Diproses", "BUDI SANTOSO  BS", "BCA·…1234", "Rp75.000", "ID Transaksi",
                 "…1A2B", "Sumber akun", "RINA WULANDARI", "Jago …0001", "Tanggal & waktu transaksi", "28 Okt 2026, 10:05 WIB"]
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.counterparty.name, d.status), ("BUDI SANTOSO", "pending"))
        lines[1] = "Transfer Gagal"
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.counterparty.name, d.status), ("BUDI SANTOSO", "gagal"))

    async def test_name_with_a_status_word_stays_the_name(self):
        d = (await read(jago_transfer(["CV SUKSES JAYA  CJ"], "BCA·…1234"))).parsed.doc
        self.assertEqual(d.counterparty.name, "CV SUKSES JAYA")


class RemainingRuleTests(unittest.IsolatedAsyncioTestCase):
    """m6: aturan yang belum teruji di ronde 1."""

    async def test_wrapped_name_needs_an_uppercase_value_of_at_most_three_words(self):
        for value in ("pratama", "PRATAMA BIN AHMAD YUSUF"):
            with self.subTest(value):
                lines = ["Transfer Berhasil", "Nominal Rp50.000", "ANDI", f"Nama Penerima {value}", "Bank Tujuan BCA"]
                self.assertEqual((await read(lines)).parsed.doc.counterparty.name, value)

    async def test_jago_style_pan_and_terminal_lines_are_not_names(self):
        for noise in ("PAN Merchant 9360001234567890", "PAN Pelanggan 9360009876543210", "Customer PAN 9360001112223334",
                      "ID Terminal A01"):
            with self.subTest(noise):
                lines = ["Pembayaran Berhasil", "QRIS", "Merchant", noise, "NMID ID1024358806544", "Nominal Rp25.000"]
                self.assertIsNone((await read(lines)).parsed.doc.counterparty.name)

    async def test_jago_transaction_id_is_the_first_reference(self):
        lines = ["Jago Syariah", "TOKO A  TA", "Rp10.000", "ID Transaksi", "123456-ABCD-EFGHIJ", "PAN Merchant", "…0001",
                 "ID Terminal", "A01", "Nomor Referensi", "a1b2c3d4e5f6", *JAGO_FOOTER]
        res = await read(lines)
        self.assertEqual(res.parsed.secrets.ref_values[0], "123456ABCDEFGHIJ")


class FixRoundMutantTests(unittest.IsolatedAsyncioTestCase):
    """Kasus yang membedakan aturan ronde perbaikan 1 dari varian yang lebih longgar."""

    async def test_a_body_pending_title_never_softens_a_failure(self):
        lines = jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234", status_lines=["Gagal"],
                              footer=["Transaksi kamu sedang diproses bank tujuan", *JAGO_FOOTER])
        res = await read(lines)
        self.assertEqual(res.parsed.doc.status, "gagal")
        self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_a_status_word_in_a_long_sentence_keeps_the_footer_from_meaning_success(self):
        lines = jago_transfer(["BUDI SANTOSO  BS"], "BCA·…1234",
                              status_lines=["Mohon maaf, transaksi ini tidak dapat kami proses karena gagal verifikasi"])
        self.assertNotEqual((await read(lines)).parsed.doc.status, "berhasil")

    async def test_a_bare_status_word_under_the_logo_is_not_part_of_the_name(self):
        lines = ["Jago Syariah", "Berhasil", "BUDI SANTOSO  BS", "BCA·…1234", "Rp75.000", "ID Transaksi", "…1A2B",
                 "Sumber akun", "RINA WULANDARI", "Jago …0001", "Tanggal & waktu transaksi", "28 Okt 2026, 10:05 WIB"]
        self.assertEqual((await read(lines)).parsed.doc.counterparty.name, "BUDI SANTOSO")

    def test_an_app_name_alone_at_the_bottom_is_not_a_logo(self):
        self.assertFalse(pc.is_app_receipt(["TOKO MAJU", "ROTI 10.000", "SUSU 12.000", "TOTAL 22.000", "BCA",
                                            "Sumber Dana TABUNGAN"]))

    def test_a_single_symbol_before_a_plain_number_is_not_a_mask(self):
        self.assertEqual(amounts_in("KOPI *15000"), [15000])
        self.assertEqual(amounts_in("Total • 52500"), [52500])



# ── Ronde 2: 4 bukti GoPay ─────────────────────────────────────────────────

GOPAY_IDS = ["real-gopay-topup-01", "real-gopay-qris-01", "real-gopay-transfer-01", "real-gopay-sendiri-01"]
GOPAY_TOTALS = {"real-gopay-topup-01": 11000, "real-gopay-qris-01": 64900, "real-gopay-transfer-01": 300000,
                "real-gopay-sendiri-01": 10000}


def gopay_transfer(fee_line="Biaya admin  Gratis!", *, status="Selesai", extra=()):
    """Bukti transfer GoPay sintetis dalam tata letak sampel asli (nama dan nomor fiktif)."""
    return ["gopay", "Rp10.000", "Ditransfer ke Rina Wulandari", "BCA …1234", "Chat dengan CS", "Status",
            "Berhasil transfer uang ke penerima", "Uang ditarik dari GoPay kamu", "Rincian transaksi", f"Status  {status}",
            "Metode pembayaran  GoPay Saldo", "Waktu  9:31", "Tanggal  28 Okt 2026", "ID transaksi  …1a2b...",
            "Jumlah  Rp10.000", fee_line, *extra, "Total  Rp10.000", "Harga tercantum sudah termasuk PPN",
            "Dikirim dari app GoPay. Dapetin gratis"]


class GopaySamplesTests(unittest.IsolatedAsyncioTestCase):
    def test_samples_are_in_the_corpus_unreviewed_with_pseudonyms(self):
        for sample_id in GOPAY_IDS:
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                self.assertEqual((s["real"], s["reviewed"], s["today"], s["user_name"]), (True, False, "2026-10-31", USER))

    def test_every_field_reads_as_the_truth_with_the_flag_on(self):
        result = evaluate([BY_ID[i] for i in GOPAY_IDS])
        bad = {row["id"]: {k: f for k, f in row["fields"].items() if not f["ok"]} for row in result["rows"] if not row["ok"]}
        self.assertEqual(bad, {})

    def test_release_gate_passes_on_all_real_samples_once_reviewed(self):
        reviewed = [{**s, "reviewed": True} for s in CORPUS if s["real"]]
        self.assertEqual(len(reviewed), 15)             # Jago 5, BSI 1, Livin 1, GoPay 4, ShopeePay 3 (+1 varian)
        self.assertEqual(gate_failures(evaluate(reviewed + receipt_samples())), [])

    async def test_no_warnings_with_the_flag_on(self):
        for sample_id in GOPAY_IDS:
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                res = await read(s["lines"], sample_context(s))
                self.assertEqual(res.checks, [])
                self.assertEqual(res.parsed.doc.confidence["total"], "tinggi")

    async def test_flag_off_reads_the_total_and_keeps_no_proof_text(self):
        for sample_id, total in GOPAY_TOTALS.items():
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                res = await read(s["lines"], sample_context(s), enabled=False)
                self.assertEqual(res.parsed.doc.amounts.total, total)
                self.assertEqual(res.checks, [])
                self.assertTrue(looks_like_proof(textdoc(s["lines"])))

    async def test_indomaret_qris_stays_qris(self):
        res = await read(lines_of("real-gopay-qris-01"))
        d = res.parsed.doc
        self.assertEqual((res.reader, d.counterparty.name, d.counterparty.city), ("qris.umum", "Indomaret", "JAKARTA UTARA"))


class SeparateTimeAndDateLinesTests(unittest.IsolatedAsyncioTestCase):
    """GoPay mencetak jam dan tanggal di baris berlabel terpisah ("Waktu 9:31", "Tanggal 31 Okt 2026")."""

    async def test_labelled_time_line_above_or_below_the_date(self):
        base = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000"]
        for lines, expected in (
                (base + ["Waktu  9:31", "Tanggal  26 Okt 2026"], "2026-10-26T09:31:00+07:00"),
                (base + ["Tanggal  26 Okt 2026", "ID transaksi  …1a2b", "Waktu  19:37"], "2026-10-26T19:37:00+07:00"),
                (base + ["Tanggal: 26/10/2026", "Jam: 14.05"], "2026-10-26T14:05:00+07:00"),
                (base + ["Tanggal  26 Okt 2026", "Pukul 08:12:33 WIB"], "2026-10-26T08:12:33+07:00")):
            with self.subTest(lines[-2:]):
                d = (await read(lines)).parsed.doc
                self.assertEqual((d.paid_at.isoformat(), d.confidence["paid_at"]), (expected, "tinggi"))

    async def test_an_unlabelled_or_impossible_time_is_not_taken(self):
        base = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000", "Tanggal  26 Okt 2026"]
        for extra in (["Biaya  2:00 menit"], ["Waktu  25:10"], ["Waktu proses 1-3 hari"], ["Jam operasional 08.00 - 21.00"]):
            with self.subTest(extra):
                d = (await read(base + extra)).parsed.doc
                self.assertEqual((d.paid_at.isoformat(), d.confidence["paid_at"]), ("2026-10-26T00:00:00+07:00", "sedang"))


class StruckThroughFeeTests(unittest.IsolatedAsyncioTestCase):
    """Harga coret: "Biaya admin Rp2.000 Rp1.000" (biaya sebenarnya yang terakhir), "Rp2.000 Gratis!" (0)."""

    async def test_fee_is_the_last_price_or_free(self):
        for fee_line, total_line, fee in (("Biaya admin  Rp2.000 Rp1.000", "Total  Rp11.000", 1000),
                                          ("Biaya admin  Rp2.000 Gratis!", "Total  Rp10.000", 0),
                                          ("Biaya admin  Gratis!", "Total  Rp10.000", 0),
                                          ("Biaya admin  Rp2.500", "Total  Rp12.500", 2500)):
            with self.subTest(fee_line):
                lines = [line if line != "Total  Rp10.000" else total_line for line in gopay_transfer(fee_line)]
                res = await read(lines)
                d = res.parsed.doc
                self.assertEqual((d.amounts.fee, d.amounts.total), (fee, int(total_line.split("Rp")[1].replace(".", ""))))
                self.assertEqual(res.checks, [])

    async def test_a_wrong_total_still_warns(self):
        lines = [line if line != "Total  Rp10.000" else "Total  Rp12.000" for line in gopay_transfer("Biaya admin  Rp2.000 Rp1.000")]
        self.assertIn("selisih_nominal", [c.code for c in (await read(lines)).checks])


class GopayLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_selesai_is_success(self):
        for lines in (["QRIS", "Merchant Name TOKO A", "Status  Selesai", "Jumlah  Rp5.000", "NMID ID1024358806544"],
                      ["QRIS", "Merchant Name TOKO A", "Status", "Selesai", "Jumlah  Rp5.000", "NMID ID1024358806544"],
                      ["QRIS", "Merchant Name TOKO A", "Status: Completed", "Jumlah  Rp5.000", "NMID ID1024358806544"]):
            with self.subTest(lines[2:4]):
                self.assertEqual((await read(lines)).parsed.doc.status, "berhasil")

    async def test_failed_gopay_transfer_is_blocked(self):
        for status in ("Gagal", "Dibatalkan"):
            with self.subTest(status):
                lines = gopay_transfer(status=status)
                lines[6] = "Transfer gagal"
                res = await read(lines)
                self.assertEqual(res.parsed.doc.status, "gagal")
                self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_ditransfer_ke_is_the_recipient_and_the_line_under_it_is_their_bank(self):
        res = await read(gopay_transfer())
        d = res.parsed.doc
        self.assertEqual((d.issuer, d.counterparty.name, d.counterparty.bank), ("gopay", "Rina Wulandari", "BCA"))
        self.assertEqual(res.parsed.secrets.account_number, "…1234")
        lines = gopay_transfer()
        lines[3] = "Mandiri 1234567890123"
        res = await read(lines)
        self.assertEqual((res.parsed.doc.issuer, res.parsed.doc.counterparty.bank), ("gopay", "MANDIRI"))
        self.assertEqual(res.parsed.secrets.account_number, "1234567890123")
        self.assertNotIn("1234567890123", json.dumps(res.parsed.doc.to_json()))

    async def test_only_a_bank_or_wallet_under_an_inline_name_is_the_recipient_bank(self):
        lines = gopay_transfer()
        lines[3] = "Kode Booking 12345678"
        res = await read(lines)
        self.assertEqual((res.parsed.doc.counterparty.bank, res.parsed.secrets.account_number), (None, None))
        # Label tanpa nilai sebaris: baris di bawahnya adalah nilai nama, bukan baris bank pihak lawan.
        self.assertIsNone(pc.read_party_account(["Transfer Berhasil", "Ditransfer ke", "BCA 1234567890", "Nominal Rp10.000"],
                                                None))
        self.assertEqual(pc.read_party_account(["Ditransfer ke RINA", "BCA 1234567890"], None), ("BCA", "1234567890"))

    def test_recipient_bank_line_is_not_the_issuer(self):
        for bank_line in ("Mandiri …5279", "Tabungan by Jago …8136", "BCA 1234567890"):
            with self.subTest(bank_line):
                self.assertEqual(detect_issuer(["gopay", "Rp10.000", "Ditransfer ke Rina", bank_line]).key, "gopay")

    async def test_merchant_name_label_wins_over_merchant(self):
        lines = ["QRIS", "Rp5.000", "Merchant Location BANDUNG", "Merchant Name TOKO A", "NMID ID1024358806544"]
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.counterparty.name, d.counterparty.city), ("TOKO A", "BANDUNG"))


# ── Ronde 2, perbaikan 1 (review A14 r2) ────────────────────────────────────

class StruckFeeNarrowTests(unittest.IsolatedAsyncioTestCase):
    """Harga coret hanya bila tepat dua nominal dan yang terakhir lebih kecil; "Gratis" hanya sebagai nilai baris."""
    BASE = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000"]

    async def test_reviewer_lines(self):
        res = await read(self.BASE + ["Biaya transfer Rp2.500 (gratis 25x/bulan)", "Total Rp52.500", "30 Okt 2026 09:31"])
        d = res.parsed.doc
        self.assertEqual((d.amounts.fee, d.amounts.total, d.confidence["total"], res.checks), (2500, 52500, "tinggi", []))
        d = (await read(self.BASE + ["Biaya Admin Rp2.500 Total Rp52.500", "31 Okt 2026 09:31"])).parsed.doc
        self.assertEqual((d.amounts.fee, d.amounts.total), (2500, 52500))

    async def test_struck_shapes(self):
        for fee_line, fee in (("Biaya admin Rp2.000 Rp1.000", 1000), ("Biaya admin Rp2.000 Gratis!", 0),
                              ("Biaya admin Gratis!", 0), ("Biaya admin Gratis", 0), ("Biaya admin Rp1.000 Rp2.000", 1000),
                              ("Biaya admin Rp2.500", 2500)):
            with self.subTest(fee_line):
                d = (await read(self.BASE + [fee_line])).parsed.doc
                self.assertEqual(d.amounts.fee, fee)


class SelesaiIsNotDoneTests(unittest.IsolatedAsyncioTestCase):
    """"Status Selesai" tidak berarti berhasil bila bukti memuat kata belum selesai (batal, dikembalikan, refund, ...),
    dan nilai label harus utuh "Selesai" ("Belum selesai" bukan selesai)."""

    async def test_not_done_words_beat_selesai(self):
        base = lines_of("real-gopay-qris-01")
        for extra in ("Dibatalkan", "Dana dikembalikan", "Refund Rp64.900", "Kedaluwarsa", "Refunded"):
            with self.subTest(extra):
                lines = base[:5] + [extra] + base[5:]
                self.assertNotEqual((await read(lines)).parsed.doc.status, "berhasil")
        self.assertEqual((await read(base)).parsed.doc.status, "berhasil")

    async def test_gopay_transfer_with_a_not_done_status_line(self):
        for value in ("Transfer ke penerima dikembalikan", "Transfer ke penerima dibatalkan", "Menunggu transfer ke penerima"):
            with self.subTest(value):
                lines = gopay_transfer()
                lines[6] = value                     # di bawah "Status"; "Status  Selesai" tetap di rincian
                res = await read(lines)
                self.assertEqual(res.reader, "transfer.umum")
                self.assertNotEqual(res.parsed.doc.status, "berhasil")

    async def test_value_must_be_the_whole_word(self):
        for value in ("Belum selesai", "Not completed", "Selesai sebagian"):
            with self.subTest(value):
                lines = ["QRIS", "Merchant Name TOKO A", f"Status: {value}", "Jumlah  Rp5.000", "NMID ID1024358806544"]
                self.assertNotEqual((await read(lines)).parsed.doc.status, "berhasil")


class LabelledTimeOnlyWithoutTimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_time_on_the_date_line_wins(self):
        lines = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp1.000", "29 Okt 2026 19:15", "Jam 08:00"]
        self.assertEqual((await read(lines)).parsed.doc.paid_at.isoformat(), "2026-10-29T19:15:00+07:00")


class FlagOffLabelledFailureTests(unittest.IsolatedAsyncioTestCase):
    """Saklar mati: bukti (looks_like_proof) yang dibaca jalur struk/tidak dikenali dengan status BERLABEL gagal/pending
    diblokir/diperingatkan; struk belanja biasa tidak terpengaruh."""

    async def test_failed_or_pending_gopay_transfer_without_a_failure_title(self):
        for status, check in (("Gagal", "status_gagal"), ("Pending", "status_pending"), ("Diproses", "status_pending")):
            with self.subTest(status):
                lines = gopay_transfer(status=status)
                lines[6] = "Transfer uang ke penerima"
                self.assertTrue(looks_like_proof(textdoc(lines)))
                res = await read(lines, enabled=False)
                self.assertEqual(res.parsed.doc.status, "gagal" if check == "status_gagal" else "pending")
                self.assertIn(check, [c.code for c in res.checks])

    async def test_status_label_with_its_value_on_the_next_line(self):
        lines = gopay_transfer()
        lines[6] = "Gagal transfer uang ke penerima"        # "Status" lalu nilainya di baris bawah (probe R4)
        res = await read(lines, enabled=False)
        self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_status_block_with_progress_steps(self):
        lines = gopay_transfer()
        lines[6:8] = ["Uang ditarik dari GoPay kamu", "Gagal transfer uang ke penerima"]   # probe R4: langkah di bawah "Status"
        res = await read(lines, enabled=False)
        self.assertIn("status_gagal", [c.code for c in res.checks])
        self.assertEqual((await read(gopay_transfer(), enabled=False)).checks, [])           # langkah berhasil: tidak ada cek

    async def test_status_block_stops_at_the_next_label(self):
        lines = gopay_transfer()
        lines[6:8] = ["Transfer uang ke penerima", "Catatan arisan gagal kemarin"]   # nilai catatan, bukan status
        self.assertEqual((await read(lines, enabled=False)).checks, [])

    async def test_status_colon_value(self):
        lines = ["BYOND", "by BSI", "Nominal Transfer  Rp 50.000", "Nama Penerima  BUDI", "Rekening Sumber  ANDI",
                 "Status: Gagal", "Total  Rp 52.500"]
        res = await read(lines, enabled=False)
        self.assertEqual((res.reader, res.parsed.doc.status), ("tidak_dikenali", "gagal"))
        self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_store_receipts_are_untouched(self):
        lines = ["TOKO MAJU", "01-10-2026 08:15", "ROTI 10.000", "SUSU 5.000", "TOTAL 15.000", "TUNAI 15.000",
                 "Status: Gagal cetak ulang"]
        self.assertFalse(looks_like_proof(textdoc(lines)))
        res = await read(lines, enabled=False)
        self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))


# ── Ronde 2, perbaikan 2 (re-review A14 r2: R2-1) ───────────────────────────

NOT_PAYMENT_STATUS = {   # store receipts / proofs whose "Status …" line is not about the payment (reviewer probes)
    "C2": ["ALFAMART", "Roti 15.000", "Total Rp15.000", "Debit BCA", "Transaksi berhasil", "Status Member: Gagal diperbarui"],
    "C2_two_items": ["ALFAMART", "Roti 15.000", "Susu 12.000", "Total Rp27.000", "QRIS", "Status Member: Gagal diperbarui"],
    "C3": ["TOKO KITA", "Roti 15.000", "Total Rp15.000", "Bayar QRIS NMID ID123456789", "Status Member: Gagal"],
    "N": ["INDOMARET", "Roti 15.000", "Total Rp15.000", "Non Tunai (QRIS)", "Pembayaran Berhasil", "Status Poin: Gagal ditambahkan"],
    "B2": ["TOKO ONLINE MAJU", "Kaos 1 x 75.000 75.000", "Total Rp75.000", "Pembayaran Berhasil", "Status Pengiriman: Gagal"],
    "A": ["KOPI NUSANTARA", "Jl. Dago 5", "Kopi Susu 1 25.000", "Total 25.000", "Bayar QRIS", "NMID ID1234567890123",
          "Status Pesanan: Diproses"],
    "A2": ["KOPI NUSANTARA", "Kopi Susu 1 25.000", "Total Rp25.000", "QRIS", "NMID ID1234567890123", "Status: Pending"],
    "B": ["WARUNG BU SRI", "Nasi Box 2 x 25.000 50.000", "Total Rp50.000", "Pembayaran Berhasil", "Status: Pending (dikirim besok)"],
    "H": ["LAUNDRY BERSIH", "Cuci Kiloan 3kg 21.000", "Total Rp21.000", "Bayar QRIS", "Status: Diproses", "Ambil: 2 hari"],
    "G": ["INDOMARET", "Roti 15.000", "Total Rp15.000", "QRIS", "Pembayaran Berhasil", "Status Refund: Diproses"],
    "F2": ["BRI", "TOKO MAJU", "SALE QRIS", "TOTAL RP 45.000", "TRANSAKSI BERHASIL", "STATUS SETTLEMENT: PENDING"],
    "M": ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "Status Member: Pending verifikasi"],
    "L2": ["gopay", "Rp50.000", "Ditransfer ke Budi Hartono", "Mandiri …1234", "Status", "Berhasil transfer uang ke penerima",
           "Uang ditarik dari GoPay kamu", "Transaksi pending akan diproses otomatis", "Rincian transaksi", "Status  Selesai",
           "Total  Rp50.000"],
}


class PaymentStatusLabelOnlyTests(unittest.IsolatedAsyncioTestCase):
    """Hanya "Status", "Status Transaksi/Pembayaran/Transfer" adalah status pembayaran; "Status Member/Poin/Pengiriman/
    Pesanan/Refund/Settlement" bukan. Judul sukses di bukti mengalahkan status berlabel (saklar mati), dan teks berisi baris
    barang bukan bukti yang statusnya dibaca dari label."""

    async def test_qualified_status_lines_never_block_or_warn_with_the_flag_off(self):
        for name, lines in NOT_PAYMENT_STATUS.items():
            if name == "L2":
                continue          # status pending dari judul "Transaksi pending ..." di badan (sudah begitu di c12ab5b)
            with self.subTest(name):
                res = await read(lines, enabled=False)
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])

    async def test_l2_status_block_starts_with_success(self):
        self.assertIsNone(pc.read_labelled_failure(NOT_PAYMENT_STATUS["L2"]))

    async def test_member_or_points_lines_do_not_set_the_qris_status_with_the_flag_on(self):
        for name in ("C2_two_items", "C3", "N", "M"):
            with self.subTest(name):
                res = await read(NOT_PAYMENT_STATUS[name])
                self.assertNotIn(res.parsed.doc.status, ("gagal", "pending"))
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])

    async def test_intended_labelled_failures_still_count(self):
        gopay_failed = ["gopay", "Rp50.000", "Ditransfer ke Budi Hartono", "Mandiri …1234", "Status",
                        "Gagal transfer uang ke penerima", "Rincian transaksi", "Status  Gagal", "Waktu  9:31",
                        "Tanggal  31 Okt 2026", "Jumlah  Rp50.000", "Total  Rp50.000"]
        cases = {"K": (gopay_failed, "status_gagal"),
                 "O": (["Pembayaran", "Penerima BUDI", "Nominal Rp50.000", "Status Transaksi: Gagal"], "status_gagal"),
                 "Status Pembayaran": (["Pembayaran", "Penerima BUDI", "Nominal Rp50.000", "Status Pembayaran: Pending"],
                                       "status_pending")}
        for status, check in (("Gagal", "status_gagal"), ("Pending", "status_pending"), ("Diproses", "status_pending")):
            lines = gopay_transfer(status=status)
            lines[6] = "Transfer uang ke penerima"
            cases[f"gopay Status {status}"] = (lines, check)
        r4 = gopay_transfer()
        r4[6:8] = ["Uang ditarik dari GoPay kamu", "Gagal transfer uang ke penerima"]
        cases["R4"] = (r4, "status_gagal")
        r5 = gopay_transfer(status="Diproses")
        r5[6] = "Sedang transfer uang ke penerima"
        cases["R5"] = (r5, "status_pending")
        for name, (lines, check) in cases.items():
            with self.subTest(name):
                self.assertIn(check, [c.code for c in (await read(lines, enabled=False)).checks])

    async def test_a_success_title_beats_a_labelled_pending(self):
        # Di bawah baris 4 (judul 4 baris pertama dibaca `read_header_status`, aturan lama yang tidak diubah di sini).
        lines = ["Tokopedia", "Pembayaran Berhasil", "Total Belanja Rp100.000", "Metode Pembayaran BCA Virtual Account",
                 "Status: Pending"]
        self.assertTrue(looks_like_proof(textdoc(lines)))
        self.assertEqual([c.code for c in (await read(lines, enabled=False)).checks if c.code.startswith("status_")], [])

    async def test_text_that_is_not_proof_like_is_never_touched(self):
        lines = ["PARKIR MALL", "Masuk 10:00", "Keluar 12:00", "Rp6.000", "Status: Gagal cetak ulang"]
        self.assertFalse(looks_like_proof(textdoc(lines)))
        self.assertEqual([c.code for c in (await read(lines, enabled=False)).checks if c.code.startswith("status_")], [])

    def test_payment_status_labels(self):
        for line, value in (("Status", ""), ("Status: Gagal", "Gagal"), ("Status  Selesai", "Selesai"),
                            ("Status Transaksi: Berhasil", "Berhasil"), ("Status Pembayaran Pending", "Pending"),
                            ("STATUS TRANSFER : GAGAL", "GAGAL"), ("Status Gagal", "Gagal")):
            with self.subTest(line):
                self.assertEqual(pc.payment_status_value(line), value)
        for line in ("Status Member: Gagal", "Status Poin: Gagal ditambahkan", "Status Pengiriman: Gagal",
                     "Status Pesanan: Diproses", "Status Refund: Diproses", "STATUS SETTLEMENT: PENDING",
                     "Status Pengiriman Gagal", "Status: Pesanan Diproses", "Order Status: Processing"):
            with self.subTest(line):
                self.assertIsNone(pc.payment_status_value(line))


# ── Ronde 2, perbaikan 3 (re-review 2 A14 r2: R2b-1) ────────────────────────

SENTENCE_STATUS_VALUES = {"Uang gagal dikirim": "gagal", "Dana gagal dikirim": "gagal", "Sedang diproses": "pending",
                          "Masih diproses": "pending", "Dalam antrian (pending)": "pending", "✓ Berhasil": "berhasil",
                          "Dana berhasil dikirim": "berhasil"}


def transfer_with_status(value):
    return ["Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31", f"Status: {value}"]


def gopay_qris_with_status(value):
    return ["gopay", "Rp64.900", "Indomaret", "Rincian transaksi", f"Status  {value}", "Waktu  15:10", "Tanggal  30 Okt 2026",
            "Acquirer Name  gopay", "Merchant Name  Indomaret", "Merchant PAN  …6860", "Terminal ID  A01", "Total  Rp64.900"]


class SentenceStatusValueTests(unittest.IsolatedAsyncioTestCase):
    """Nilai label status pembayaran yang memuat kata status di mana saja tetap dibaca ("Status: Uang gagal dikirim"); hanya
    label berkualifikasi lain ("Status Pesanan:") atau nilai yang diawali kata benda bukan pembayaran ("Pesanan Diproses")
    yang ditolak."""

    async def test_flag_on_transfer_and_qris_layouts(self):
        for value, status in SENTENCE_STATUS_VALUES.items():
            for name, make, reader in (("transfer", transfer_with_status, "transfer.umum"),
                                       ("qris", gopay_qris_with_status, "qris.umum")):
                with self.subTest(value, layout=name):
                    res = await read(make(value))
                    codes = [c.code for c in res.checks]
                    self.assertEqual((res.reader, res.parsed.doc.status), (reader, status))
                    self.assertEqual("status_gagal" in codes, status == "gagal")
                    self.assertEqual("status_pending" in codes, status == "pending")

    async def test_flag_off_blocks_or_warns_the_failure_and_pending_values(self):
        for value, status in SENTENCE_STATUS_VALUES.items():
            if status == "berhasil":
                continue
            for name, make in (("transfer", transfer_with_status), ("qris", gopay_qris_with_status)):
                with self.subTest(value, layout=name):
                    codes = [c.code for c in (await read(make(value), enabled=False)).checks]
                    self.assertIn("status_gagal" if status == "gagal" else "status_pending", codes)

    def test_value_rules(self):
        for line, value in (("Status: Uang gagal dikirim", "Uang gagal dikirim"), ("Status  Masih diproses", "Masih diproses"),
                            ("Status Transaksi: Dana gagal dikirim", "Dana gagal dikirim"), ("Status Lunas", "Lunas")):
            with self.subTest(line):
                self.assertEqual(pc.payment_status_value(line), value)
        for line in ("Status: Pesanan Diproses", "Status Pengiriman Gagal", "Status Member Gold", "Status: Order processing",
                     "Status Member: Gagal", "STATUS SETTLEMENT: PENDING"):
            with self.subTest(line):
                self.assertIsNone(pc.payment_status_value(line))

    async def test_earlier_round_probes_keep_their_results(self):
        for name, lines in NOT_PAYMENT_STATUS.items():
            if name == "L2":
                continue
            with self.subTest(name):
                res = await read(lines, enabled=False)
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])
        for name in ("C2_two_items", "C3", "N", "M"):
            with self.subTest(name, flag="on"):
                self.assertNotIn((await read(NOT_PAYMENT_STATUS[name])).parsed.doc.status, ("gagal", "pending"))


# ── Ronde 2, perbaikan 4 (re-review 3 A14 r2: R2c-1, R2c-2) ────────────────

NEGATION_VALUES = {   # probes9: nilai label status, tata letak transfer dan QRIS GoPay
    "Belum berhasil": "pending", "Belum sukses": "pending", "Transaksi belum berhasil": "pending", "Belum diterima": "pending",
    "Belum terkirim": "pending", "Pembayaran belum diterima": "pending", "Dana belum masuk": "pending",
    "Tidak berhasil": "gagal", "Tidak sukses": "gagal", "Not successful": "gagal", "Unsuccessful": "gagal",
    "Tidak terkirim": "gagal", "Dana tidak terkirim": "gagal", "Akun tujuan tidak aktif, transaksi gagal": "gagal",
    "Order gagal dibayar": "gagal",
}


class NegatedSuccessAndPaymentNounTests(unittest.IsolatedAsyncioTestCase):
    async def test_values_in_both_layouts_and_both_modes(self):
        for value, status in NEGATION_VALUES.items():
            check = "status_gagal" if status == "gagal" else "status_pending"
            for name, make in (("transfer", transfer_with_status), ("qris", gopay_qris_with_status)):
                for enabled in (True, False):
                    with self.subTest(value, layout=name, enabled=enabled):
                        res = await read(make(value), enabled=enabled)
                        self.assertEqual(res.parsed.doc.status, status)
                        self.assertIn(check, [c.code for c in res.checks])
        # Baris probes9 lainnya: tidak memblokir/memperingatkan seperti di main (saklar mati), dan saklar menyala tidak
        # pernah membacanya berhasil (gagal atau tidak_diketahui: nilai ambigu, tidak dikunci di sini). "Kartu ditolak"
        # sejak Task L5 (keputusan pemilik 3) = gagal di kedua saklar: `CancelledVocabularyTests`.
        for value in ("Refund gagal",):
            for name, make in (("transfer", transfer_with_status), ("qris", gopay_qris_with_status)):
                for enabled in (True, False):
                    with self.subTest(value, layout=name, enabled=enabled):
                        res = await read(make(value), enabled=enabled)
                        if enabled:
                            self.assertNotEqual(res.parsed.doc.status, "berhasil")
                        else:
                            self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])

    async def test_header_titles(self):
        for title, status in (("Transfer belum berhasil", "pending"), ("Pembayaran tidak berhasil", "gagal"),
                              ("Transfer tidak terkirim", "gagal"), ("Pembayaran belum diterima", "pending")):
            for enabled in (True, False):
                with self.subTest(title, enabled=enabled):
                    lines = [title, "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31"]
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, status)
                    self.assertIn("status_gagal" if status == "gagal" else "status_pending", [c.code for c in res.checks])

    async def test_conditional_and_question_footers_stay_success(self):
        for footer in ("Jika transaksi tidak berhasil, hubungi 14017", "Belum berhasil? Coba lagi"):
            for enabled in (True, False):
                with self.subTest(footer, enabled=enabled):
                    lines = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31",
                             footer]
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, "berhasil")
                    self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])

    async def test_store_receipts_unchanged(self):
        d2 = ["TOKO BANGUNAN JAYA", "Semen 2 x 60.000 120.000", "Total Rp120.000", "Transfer BCA", "Status: Belum Lunas"]
        for lines in (d2, ["TOKO MAJU", "ROTI 10.000", "TOTAL 10.000", "TUNAI 10.000", "Harga belum termasuk PPN"]):
            for enabled in (True, False):
                with self.subTest(lines[0], enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))

    async def test_belum_lunas_is_not_a_payment_proof_status(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                res = await read(transfer_with_status("Belum Lunas"), enabled=enabled)
                self.assertNotIn("status_pending", [c.code for c in res.checks])

    def test_other_noun_rule(self):
        for line in ("Status: Akun tujuan tidak aktif, transaksi gagal", "Status: Order gagal dibayar",
                     "Status: Kartu ditolak", "Status: Pelanggan belum membayar"):
            with self.subTest(line):
                self.assertIsNotNone(pc.payment_status_value(line))
        for line in ("Status: Pesanan Diproses", "Status Member Gold", "Status: Pengiriman gagal"):
            with self.subTest(line):
                self.assertIsNone(pc.payment_status_value(line))

    async def test_earlier_probes_still_hold(self):
        for name, lines in NOT_PAYMENT_STATUS.items():
            if name == "L2":
                continue
            with self.subTest(name):
                res = await read(lines, enabled=False)
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])
        tokopedia = ["Tokopedia", "Pembayaran Berhasil", "Status: Pesanan Diproses", "Total Belanja Rp100.000",
                     "Metode Pembayaran BCA Virtual Account"]
        for enabled in (True, False):
            with self.subTest("E_tokopedia", enabled=enabled):
                res = await read(tokopedia, enabled=enabled)
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])


# ── Ronde 2, perbaikan 5 (re-review 4 A14 r2: R2d-1) ───────────────────────

def store_receipt(footer):
    """Struk belanja tunai 3 barang dengan satu baris kaki (probes10 "S_store")."""
    return ["TOKO MAJU", "Jl. Merdeka 1", "30/10/2026 15:10", "ROTI 1 x 15.000 15.000", "SUSU 2 x 6.000 12.000",
            "TELUR 1 x 28.000 28.000", "TOTAL 55.000", "TUNAI 60.000", "KEMBALI 5.000", footer]


def small_qris_receipt(note, *, first=False):
    """Struk toko kecil 1 barang dibayar QRIS; catatan di kaki ("S_small") atau di baris pertama ("S_head")."""
    body = ["KOPI NUSANTARA", "Kopi Susu 1 25.000", "Total Rp25.000", "Bayar QRIS", "NMID ID1234567890123"]
    return [note, *body] if first else [*body, note]


def status_checks(res):
    return [c.code for c in res.checks if c.code.startswith("status_")]


# Kaki struk belanja dengan negasi kata tiba (masuk/diterima/terkirim) yang bukan status pembayaran (probes10).
STORE_ARRIVAL_NOTES = ("Transaksi tidak masuk poin", "Transaksi QRIS tidak diterima untuk refund",
                       "Transfer tidak diterima di kasir", "Poin belum masuk", "Kembalian tidak diterima",
                       "Barang promo tidak masuk hitungan poin")
# Pemberitahuan toko yang bersubjek uang dan menutup klausa: di teks berbaris barang tetap bukan status.
STORE_MONEY_NOTICES = ("Transfer tidak diterima", "Pembayaran non tunai tidak diterima",
                       "Pembayaran dengan kartu kredit tidak diterima", "Transaksi tidak masuk", "Uang palsu tidak diterima")
SMALL_AS_ON_MAIN = {False: ("struk_belanja", "berhasil"), True: ("qris.umum", "tidak_diketahui")}


class ArrivalNegationTests(unittest.IsolatedAsyncioTestCase):
    """Negasi kata tiba (masuk/diterima/terkirim) hanya status bila menutup klausa, dan di luar nilai label status pembayaran
    hanya dengan subjek uang di klausanya; di teks berbaris barang negasi "tidak ..." kata tiba tidak pernah status. Negasi
    kata sukses tidak dibatasi; "tidak dibayar"/"not paid" = pending."""

    async def test_store_receipt_footers_read_as_on_main(self):
        notes = STORE_ARRIVAL_NOTES + (
            "Transaksi Berhasil - Poin belum masuk",                      # tanda pisah memisahkan klausa
            "Poin belum masuk, transaksi gagal akan dicek ulang besok")   # 9 kata: kata yang diabaikan tetap terhitung
        for note in notes:
            for enabled in (True, False):
                with self.subTest(note, enabled=enabled):
                    res = await read(store_receipt(note), enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))

    async def test_small_qris_receipts_read_as_on_main(self):
        notes = STORE_ARRIVAL_NOTES + ("Kembalian tidak diterima, transaksi berhasil dicetak ulang hari ini",)
        for note in notes:
            for first in (False, True):
                for enabled in (True, False):
                    with self.subTest(note, first=first, enabled=enabled):
                        res = await read(small_qris_receipt(note, first=first), enabled=enabled)
                        self.assertEqual((res.reader, res.parsed.doc.status, status_checks(res)),
                                         (*SMALL_AS_ON_MAIN[enabled], []))

    async def test_store_notices_with_a_money_subject_never_block(self):
        for note in STORE_MONEY_NOTICES:
            for enabled in (True, False):
                with self.subTest(note, layout="store", enabled=enabled):
                    res = await read(store_receipt(note), enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))
                for first in (False, True):
                    with self.subTest(note, layout="small", first=first, enabled=enabled):
                        res = await read(small_qris_receipt(note, first=first), enabled=enabled)
                        self.assertEqual((res.reader, res.parsed.doc.status, status_checks(res)),
                                         (*SMALL_AS_ON_MAIN[enabled], []))
        # Di baris pertama struk belanja juga bukan judul status: tidak diblokir dan tidak menjadikannya bukti (seperti main).
        for note in ("Transfer tidak diterima", "Pembayaran non tunai tidak diterima"):
            lines = [note, *store_receipt(note)[:-1]]
            with self.subTest(note, layout="store, first line", check="looks_like_proof"):
                self.assertFalse(looks_like_proof(textdoc(lines)))
            for enabled in (True, False):
                with self.subTest(note, layout="store, first line", enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))
        warung = ["WARUNG BU SRI", "Nasi Box 25.000", "Es Teh 5.000", "Total Rp30.000", "Pembayaran non tunai tidak diterima"]
        with self.subTest("badan teks tanpa pola struk", check="looks_like_proof"):   # bukan judul status: tetap bukan bukti
            self.assertFalse(looks_like_proof(textdoc(warung)))
        # Bukti tanpa baris barang: kalimat yang sama tetap kegagalan.
        for enabled in (True, False):
            with self.subTest("proof", enabled=enabled):
                res = await read(["Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31",
                                  "Transfer tidak diterima"], enabled=enabled)
                self.assertEqual((res.parsed.doc.status, status_checks(res)), ("gagal", ["status_gagal"]))

    async def test_money_subject_arrival_warns_only_at_clause_end(self):
        for note in ("Pembayaran belum diterima, harap tunggu", "Pembayaran Anda belum diterima"):
            for enabled in (True, False):
                with self.subTest(note, enabled=enabled):
                    res = await read(store_receipt(note), enabled=enabled)
                    self.assertEqual((res.parsed.doc.status, status_checks(res)), ("pending", ["status_pending"]))
        for enabled in (True, False):
            with self.subTest("di tengah klausa", enabled=enabled):
                res = await read(store_receipt("Pembayaran belum diterima di kasir"), enabled=enabled)
                self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))
        header = ["Dana Rp50.000 belum masuk", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000"]
        for enabled in (True, False):     # titik ribuan di nominal bukan batas klausa
            with self.subTest("Dana Rp50.000 belum masuk", enabled=enabled):
                res = await read(header, enabled=enabled)
                self.assertEqual((res.parsed.doc.status, status_checks(res)), ("pending", ["status_pending"]))

    async def test_unpaid_is_pending_not_failed(self):
        for value in ("Tidak dibayar", "Not paid", "Belum dibayar"):
            for enabled in (True, False):
                with self.subTest(value, enabled=enabled):
                    res = await read(transfer_with_status(value), enabled=enabled)
                    self.assertEqual((res.parsed.doc.status, status_checks(res)), ("pending", ["status_pending"]))
        for enabled in (True, False):
            with self.subTest("Not paid di judul struk kecil", enabled=enabled):
                res = await read(small_qris_receipt("Not paid", first=True), enabled=enabled)
                self.assertEqual((res.parsed.doc.status, status_checks(res)), ("pending", ["status_pending"]))

    async def test_status_values_need_no_subject_but_bare_lines_do(self):
        labelled = ["Status: Belum diterima", "KOPI NUSANTARA", "Kopi Susu 1 25.000", "Total Rp25.000", "Bayar QRIS"]
        bare = ["Belum diterima", *labelled[1:]]
        for enabled in (True, False):
            with self.subTest("label status di jalur struk", enabled=enabled):
                res = await read(labelled, enabled=enabled)
                self.assertEqual((res.parsed.doc.status, status_checks(res)), ("pending", ["status_pending"]))
            with self.subTest("baris lepas di jalur struk", enabled=enabled):
                res = await read(bare, enabled=enabled)
                self.assertEqual((res.reader, res.parsed.doc.status, status_checks(res)), (*SMALL_AS_ON_MAIN[enabled], []))
            with self.subTest("baris lepas di judul bukti", enabled=enabled):
                res = await read(["Belum diterima", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000"], enabled=enabled)
                self.assertNotIn(res.parsed.doc.status, ("gagal", "pending"))
                self.assertEqual(status_checks(res), [])

    def test_arrival_verb_counts_only_at_clause_end(self):
        for text, status in (("Dana tidak masuk", "gagal"), ("Dana tidak masuk.", "gagal"), ("Dana tidak terkirim)", "gagal"),
                             ("Dana belum masuk, tunggu", "pending"), ("Dana belum masuk; tunggu", "pending"),
                             ("Dana belum masuk: cek mutasi", "pending"),
                             ("Transfer tidak diterima di kasir", None), ("Transaksi tidak masuk poin", None),
                             ("Dana belum terkirim ke penerima", None), ("Belum diterima? Hubungi CS", None),
                             ("Tidak sukses karena saldo kurang", "gagal"), ("Belum berhasil diproses", "pending"),
                             ("Biaya tidak dibayar penerima", None), ("Belum dibayar", "pending"), ("Not paid", "pending")):
            with self.subTest(text):
                self.assertEqual(pc._classify(text), status)

    def test_arrival_outside_a_status_value_needs_a_money_subject_in_its_clause(self):
        for text, status in (("Poin belum masuk", None), ("Kembalian tidak diterima", None), ("Belum diterima", None),
                             ("Dana belum masuk", "pending"), ("Uang tidak terkirim", "gagal"), ("Saldo belum masuk", "pending"),
                             ("Transfer ke BCA tidak diterima", "gagal"), ("Pembayaran QRIS belum diterima", "pending"),
                             ("Transaksi belum masuk", "pending"), ("Payment belum diterima", "pending"),
                             ("Poin, dana belum masuk", "pending"), ("Pembayaran tunai, poin belum masuk", None),
                             ("Dana aman. Poin belum masuk", None), ("Dana aman; poin belum masuk", None),
                             ("Transaksi Berhasil - Poin belum masuk", "berhasil"),
                             ("Transaksi Berhasil | Poin belum masuk", "berhasil"), ("Pembayaran: belum diterima", "pending"),
                             ("Dana Rp50.000 belum masuk", "pending"), ("Dana Rp 50,000 belum masuk", "pending"),
                             ("Poin belum masuk, transaksi gagal akan dicek ulang besok", None),
                             ("Tidak sukses", "gagal"), ("Not paid", "pending")):
            with self.subTest(text):
                self.assertEqual(pc._strongest(pc._status_lines([text], pc.HEADER_WORDS)), status)
        for line, status in (("Status: Belum diterima", "pending"), ("Status: Tidak terkirim", "gagal")):
            with self.subTest(line):
                self.assertEqual(pc.read_status(["Transfer", line]), status)


# ── Ronde 3: bukti ShopeePay (A14 r3) ─────────────────────────────────────────

SITI = "SITI AMINAH"
SHOPEEPAY_IDS = ["real-shopeepay-qris-01", "real-shopeepay-topup-01", "real-shopeepay-transfer-01", "real-shopeepay-masuk-01"]
SHOPEEPAY_TOTALS = {"real-shopeepay-qris-01": 16000, "real-shopeepay-topup-01": 11000, "real-shopeepay-transfer-01": 10000,
                    "real-shopeepay-masuk-01": 10000}


class ShopeePaySamplesTests(unittest.IsolatedAsyncioTestCase):
    """Tiga bukti ShopeePay (QRIS, kirim ke GoPay sendiri, kirim ke Jago orang lain); bukti ketiga dicatat dua kali: oleh
    pengirim (keluar) dan oleh penerima (uang masuk)."""

    def test_samples_are_in_the_corpus_unreviewed_with_pseudonyms(self):
        for sample_id in SHOPEEPAY_IDS:
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                user = USER if sample_id == "real-shopeepay-masuk-01" else SITI
                self.assertEqual((s["real"], s["reviewed"], s["today"], s["user_name"]), (True, False, "2026-10-31", user))
        self.assertEqual(BY_ID["real-shopeepay-transfer-01"]["lines"], BY_ID["real-shopeepay-masuk-01"]["lines"])

    def test_every_field_reads_as_the_truth_with_the_flag_on(self):
        result = evaluate([BY_ID[i] for i in SHOPEEPAY_IDS])
        bad = {row["id"]: sorted(k for k, f in row["fields"].items() if not f["ok"]) for row in result["rows"] if not row["ok"]}
        # Top-up GoPay sendiri tidak memuat kata "top up" ("GOPAY TOPU-…"): terbaca transfer keluar, bukan `top_up`.
        self.assertEqual(bad, {"real-shopeepay-topup-01": ["flow"]})

    async def test_details_with_the_flag_on(self):
        expected = {   # reader, flow, bank, rekening tersamar, biaya, keyakinan total
            "real-shopeepay-qris-01": ("qris.umum", "keluar", None, None, 0, "sedang"),
            "real-shopeepay-topup-01": ("transfer.umum", "keluar", "GOPAY", "…6390", 0, "tinggi"),
            "real-shopeepay-transfer-01": ("transfer.umum", "keluar", "JAGO SYARIAH", "…2753", 0, "tinggi"),
            "real-shopeepay-masuk-01": ("transfer.umum", "masuk", None, None, 0, "tinggi"),
        }
        for sample_id, want in expected.items():
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                res = await read(s["lines"], sample_context(s))
                d = res.parsed.doc
                self.assertEqual((res.reader, d.flow, d.counterparty.bank, d.counterparty.id_masked, d.amounts.fee,
                                  d.confidence["total"]), want)
                self.assertEqual((d.amounts.total, d.amounts.tax), (SHOPEEPAY_TOTALS[sample_id], 0))   # kaki: cashback, NPWP
                self.assertEqual(res.checks, [])
        qris = (await read(lines_of("real-shopeepay-qris-01"), sample_context(BY_ID["real-shopeepay-qris-01"]))).parsed.doc
        self.assertEqual(qris.counterparty.city, "BEKASI")

    async def test_flag_off_reads_the_total_and_keeps_no_proof_text(self):
        for sample_id, total in SHOPEEPAY_TOTALS.items():
            with self.subTest(sample_id):
                s = BY_ID[sample_id]
                res = await read(s["lines"], sample_context(s), enabled=False)
                self.assertEqual(res.parsed.doc.amounts.total, total)          # kaki "Cashback … Rp100.000", NPWP bukan total
                self.assertEqual([c.code for c in res.checks if c.code.startswith("status_")], [])
                self.assertTrue(looks_like_proof(textdoc(s["lines"])))       # teks, nama, rincian tidak disimpan

    def test_month_name_with_a_zero_for_o(self):
        from app.services.kotak_struk.readers.labels import WIB, parse_datetime_id
        from datetime import datetime
        for text, want in (("Waktu Selesai: 31 0kt 2026, 10:57AM", datetime(2026, 10, 31, 10, 57, tzinfo=WIB)),
                           ("Waktu Selesai: 31 0kt 2026, 11:06", datetime(2026, 10, 31, 11, 6, tzinfo=WIB)),
                           ("1 N0v 2026 08:15", datetime(2026, 11, 1, 8, 15, tzinfo=WIB)),
                           ("31 0ct 2026, 9:05PM", datetime(2026, 10, 31, 21, 5, tzinfo=WIB))):
            with self.subTest(text):
                self.assertEqual(parse_datetime_id(text), want)
        for text in ("Rp100.000 2026", "Lot 10.1-6 2026", "12 000 2026"):
            with self.subTest(text):
                self.assertIsNone(parse_datetime_id(text))

    def test_the_logo_breaks_a_tie_between_apps(self):
        for lines in (["ShopeePay", "RP  16.000", "Berhasil", "Nama Pengakuisisi  Gopay"],
                      ["ShopeePay", "Rp 11.000", "Berhasil", "GOPAY TOPU-SXXXX", "Kirim Ke  Axxxxxxx", "GoPay: …6390"]):
            with self.subTest(lines[3]):
                self.assertEqual(detect_issuer(lines).key, "shopeepay")
        self.assertEqual(detect_issuer(["Bayar pakai Gopay", "Saldo ShopeePay"]).key, "gopay")   # tanpa logo: seperti dulu


class SenderAndRecipientFlowTests(unittest.IsolatedAsyncioTestCase):
    """Bukti yang mencetak pengirim dan penerima: penerima = user dan pengirim orang lain -> uang masuk (pihak lawan =
    pengirim); keduanya user -> antar rekening sendiri; nama pengirim yang disamarkan aplikasi ("ANDI ********") cocok
    bila bagian yang terlihat cocok."""

    @staticmethod
    def proof(sender_line):
        return ["Transfer Berhasil", "Rp50.000", sender_line, "Penerima  ANDI PRATAMA", "Bank Tujuan BCA", "30 Okt 2026 09:31"]

    async def test_flow_from_the_sender_and_the_recipient(self):
        cases = {
            "Pengirim  BUDI HARTONO": ("masuk", "BUDI HARTONO"),
            "Dikirim Dari  BUDI  ********": ("masuk", "BUDI"),
            "Dikirim Dari  ANDI  ********": ("antar_rekening_sendiri", "ANDI PRATAMA"),
            "Pengirim  ANDI PRATAMA": ("antar_rekening_sendiri", "ANDI PRATAMA"),
            "Pengirim  Axxx Pxxxxxx": ("antar_rekening_sendiri", "ANDI PRATAMA"),
            "Dikirim dari app GoPay. Dapetin gratis": ("antar_rekening_sendiri", "ANDI PRATAMA"),   # kaki aplikasi
            "Dikirim dari aplikasi kami": ("antar_rekening_sendiri", "ANDI PRATAMA"),               # kalimat, bukan nama
            "Sumber Dana  Saldo ShopeePay": ("antar_rekening_sendiri", "ANDI PRATAMA"),             # sumber dana, bukan nama
            "Pengirim  Bxxx Hxxxxxx": ("masuk", "Bxxx Hxxxxxx"),        # samaran yang tidak cocok dengan nama user
        }
        for sender_line, (flow, name) in cases.items():
            with self.subTest(sender_line):
                d = (await read(self.proof(sender_line))).parsed.doc
                self.assertEqual((d.flow, d.counterparty.name), (flow, name))
                if flow == "masuk":
                    self.assertEqual((d.counterparty.bank, d.counterparty.id_masked), (None, None))   # rekening user sendiri
        with self.subTest("tanpa nama user"):
            d = (await read(self.proof("Pengirim  BUDI HARTONO"), ParseContext(today=date(2026, 10, 30)))).parsed.doc
            self.assertEqual(d.flow, "keluar")
        with self.subTest("penerima orang lain"):
            lines = ["Transfer Berhasil", "Rp50.000", "Pengirim  ANDI PRATAMA", "Penerima  BUDI HARTONO", "Bank Tujuan BCA"]
            self.assertEqual((await read(lines)).parsed.doc.flow, "keluar")

    async def test_a_sender_who_is_also_the_user_keeps_own_account(self):
        # Nama resmi yang lebih panjang ("BIN SUPARDI", gelar "IR", nama belakang tambahan) tetap nama user (A14 r3 fix 1).
        bca = ["Transfer Berhasil", "Nominal Rp100.000"]
        cases = {
            "nama resmi lebih panjang": (USER, [*bca, "Rekening Sumber ANDI PRATAMA BIN SUPARDI",
                                                "Nama Penerima ANDI PRATAMA BIN SUPARDI", "Bank Tujuan BCA", "31 Okt 2026 10:00"],
                                         "ANDI PRATAMA BIN SUPARDI"),
            "gelar": (USER, [*bca, "Dari IR ANDI PRATAMA", "Penerima ANDI PRATAMA", "Bank Tujuan BCA", "31 Okt 2026 10:00"],
                      "ANDI PRATAMA"),
            "BYOND": (USER, ["BYOND", "by BSI", "Transaksi Berhasil", "29Okt 2026·23:30:17", "Nominal Transfer  Rp 50.000", "ANDI",
                             "Nama Penerima  PRATAMA SAPUTRA", "Bank Jago Syariah•", "…4821", "ANDI",
                             "Rekening Sumber  PRATAMA SAPUTRA", "Total  Rp 52.500"], "ANDI PRATAMA SAPUTRA"),
            "inisial": ("SITI NUR AISYAH", [*bca, "Dari S NUR AISYAH", "Penerima SITI NUR HALIZA", "Bank Tujuan BCA",
                                            "31 Okt 2026 10:00"], "SITI NUR HALIZA"),
        }
        for name, (user, lines, recipient) in cases.items():
            with self.subTest(name):
                d = (await read(lines, ParseContext(today=date(2026, 10, 31), user_name=user))).parsed.doc
                self.assertEqual((d.flow, d.counterparty.name), ("antar_rekening_sendiri", recipient))
        with self.subTest("pengirim orang lain"):
            lines = [*bca, "Dari BUDI SANTOSO", "Penerima ANDI PRATAMA", "Bank Tujuan BCA", "31 Okt 2026 10:00"]
            d = (await read(lines)).parsed.doc
            self.assertEqual((d.flow, d.counterparty.name), ("masuk", "BUDI SANTOSO"))

    async def test_kirim_uang_counts_only_as_the_amount_label(self):
        # Instruksi bayar di faktur ("Silakan kirim uang ke rekening BCA …") bukan penanda transfer: seperti 18ec64f.
        invoices = (["TOKO ONLINE MAJU", "Kaos 1 x 75.000 75.000", "Total Rp75.000", "Penerima: Budi",
                     "Silakan kirim uang ke rekening BCA 1234567890"],
                    ["INVOICE", "Jasa desain 500.000", "Total Rp500.000", "Kirim uang ke BCA 1234567890 a.n. BUDI",
                     "Berita: INV-001"])
        for lines in invoices:
            with self.subTest(lines[0], check="looks_like_proof"):
                self.assertFalse(looks_like_proof(textdoc(lines)))      # rincian dan teks struk tetap disimpan
            for enabled in (True, False):
                with self.subTest(lines[0], enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual((res.reader, len(res.parsed.doc.lines)), ("struk_belanja", 1))
        # Label "Jumlah Kirim Uang" tetap penanda transfer (ShopeePay), tetapi satu penanda saja tidak cukup.
        self.assertGreaterEqual(TransferReader().detect(textdoc(["Rp 10.000", "Berhasil", "Penerima  BUDI HARTONO",
                                                                 "Jumlah Kirim Uang  Rp10.000"])), 0.9)
        self.assertLess(TransferReader().detect(textdoc(["Rp 10.000", "Berhasil", "Jumlah Kirim Uang  Rp10.000"])), 0.9)

    async def test_source_account_name_is_the_sender(self):
        lines = jago_transfer(["ANDI PRATAMA  AP"], "Mandiri·…7342")       # "Sumber akun" RINA WULANDARI -> ANDI PRATAMA
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.flow, d.counterparty.name), ("masuk", "RINA WULANDARI"))
        # Nama sumber yang terbelah dua baris (BYOND): digabung.
        lines = ["BYOND", "by BSI", "Transaksi Berhasil", "29 Okt 2026 23:30", "Nominal Transfer  Rp 50.000", "ANDI",
                 "Nama Penerima  PRATAMA", "BUDI", "Rekening Sumber  HARTONO", "Total  Rp 50.000"]
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.flow, d.counterparty.name), ("masuk", "BUDI HARTONO"))

    async def test_kirim_ke_block_name_above_and_bank_beside_the_label(self):
        # ShopeePay: nama, lalu "Bank: nomor", rata kanan di tengah label; OCR menaruh nama di atas baris label.
        lines = ["ShopeePay", "Rp 10.000", "Berhasil", "BUDI HARTONO", "Kirim Ke  Bank BCA:", "…1234", "Jumlah Kirim Uang  Rp10.000"]
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.doc_type, d.counterparty.name, d.counterparty.bank, d.counterparty.id_masked),
                         ("transfer", "BUDI HARTONO", "BCA", "…1234"))
        # Tanpa nama di atasnya, nama bank bukan nama penerima; baris di atas yang hanya nama bank atau kata status bukan nama.
        for above in ((), ("JAGO SYARIAH",), ("BERHASIL",)):
            with self.subTest(above=above):
                d = (await read([lines[0], lines[1], lines[2], *above, *lines[4:]])).parsed.doc
                self.assertEqual((d.counterparty.name, d.counterparty.bank, d.counterparty.id_masked), (None, "BCA", "…1234"))
        # Nilai bertitik dua yang bukan hanya nama bank ("Toko Mandiri Jaya:") tetap nama penerima.
        d = (await read([*lines[:4], "Kirim Ke  Toko Mandiri Jaya:", *lines[5:]])).parsed.doc
        self.assertEqual(d.counterparty.name, "Toko Mandiri Jaya")
        # "Penyedia:" tanpa nomor di bawah potongan nama bukan blok: nama = nilai labelnya saja.
        d = (await read(["ShopeePay", "Rp 11.000", "Berhasil", "GOPAY TOPU-SXXXX", "Kirim Ke  Axxxxxxx", "GoPay:",
                         "Jumlah Kirim Uang  Rp11.000"])).parsed.doc
        self.assertEqual(d.counterparty.name, "Axxxxxxx")

    async def test_markers_labels_and_refs(self):
        qris = ["ShopeePay", "Rp 16.000", "Berhasil", "Nama Merchant  Kopi A"]
        for extra in (["PAN Merchant  …5207", "Nama Pengakuisisi  Gopay"], ["PAN Merchant  …5207", "PAN Pelanggan  …4416"]):
            with self.subTest(extra[1]):
                self.assertGreaterEqual(QrisReader().detect(textdoc(qris + extra)), 0.95)
        transfer = ["Rp 10.000", "Berhasil", "Penerima  BUDI HARTONO", "Jumlah Kirim Uang  Rp10.000"]
        self.assertGreaterEqual(TransferReader().detect(textdoc(transfer)), 0.9)      # "Kirim Uang" penanda transfer biasa
        # "Kirim ke" di luar ShopeePay bukan label penerima: struk kecil tidak mendapat nama "alamat pembeli".
        res = await read(small_qris_receipt("Kirim ke alamat pembeli"))
        self.assertEqual((res.reader, res.parsed.doc.counterparty.name), ("qris.umum", None))
        # Nomor referensi ShopeePay ("Transaksi SN", "Order SN"; nilai rekaan).
        lines = ["ShopeePay", "Rp 10.000", "Berhasil", "Transaksi SN  AB12CD34EF56", "Order SN  QW98ER76TY54"]
        self.assertEqual(pc.read_refs(lines, detect_issuer(lines)), [("ref", "AB12CD34EF56"), ("ref", "QW98ER76TY54")])
        # Baris "Penyedia: nomor" di bawah nama berlabel (titik dua): bank dan rekening pihak lawan.
        lines = gopay_transfer()
        lines[3] = "GoPay: …1234"                       # di bawah "Ditransfer ke Rina Wulandari"
        d = (await read(lines)).parsed.doc
        self.assertEqual((d.counterparty.name, d.counterparty.bank, d.counterparty.id_masked), ("Rina Wulandari", "GOPAY", "…1234"))


class RewardFooterTests(unittest.IsolatedAsyncioTestCase):
    """Carry re-review 5 m1: "belum …" kata tiba yang klausanya menyebut poin/cashback/voucher/... bukan status pembayaran,
    dan klausa juga dipisah "dan"/"tetapi"/"tapi"/"namun"."""

    NOTES = ("Poin transaksi ini belum masuk", "Transaksi berhasil dan poin belum masuk",
             "Transaksi berhasil tapi poin belum masuk", "Saldo poin belum masuk", "Cashback transaksi belum masuk",
             "Pembayaran berhasil namun voucher belum diterima")

    async def test_store_and_small_receipts_read_as_on_main(self):
        for note in self.NOTES:
            for enabled in (True, False):
                with self.subTest(note, layout="store", enabled=enabled):
                    res = await read(store_receipt(note), enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))
                with self.subTest(note, layout="small", enabled=enabled):
                    res = await read(small_qris_receipt(note), enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, status_checks(res)), (*SMALL_AS_ON_MAIN[enabled], []))

    def test_clause_rules(self):
        for text, status in (("Poin transaksi ini belum masuk", None), ("Transaksi berhasil dan poin belum masuk", "berhasil"),
                             ("Saldo poin belum masuk", None), ("Dana cashback belum masuk", None),
                             ("Transfer gagal tetapi kupon belum diterima", "gagal"),
                             ("Transaksi berhasil tetapi dana belum masuk", "pending"),
                             ("Transaksi berhasil dan kembalian belum diterima", "berhasil"),
                             # Batas klausa tetap berlaku tanpa kata imbalan (aturan imbalan tidak menggantikannya).
                             ("Dana aman. Kembalian belum diterima", None), ("Dana aman; kembalian belum diterima", None),
                             ("Transaksi Berhasil - Kembalian belum diterima", "berhasil"),
                             ("Transaksi Berhasil | Kembalian belum diterima", "berhasil"),
                             ("Pembayaran belum diterima, harap tunggu", "pending"), ("Dana belum masuk", "pending")):
            with self.subTest(text):
                self.assertEqual(pc._strongest(pc._status_lines([text], pc.HEADER_WORDS)), status)


# ── Tahap 1 Kotak Belajar, Task L5: kosakata "dibatalkan/ditolak" → gagal (spec §7) ─────────────

D_L5 = "26/10/2026 08:12"
# Bukti dibatalkan/ditolak yang diblokir seperti gagal di kedua saklar (nama dan nomor rekaan).
CANCELLED_PROOFS = {
    "judul transfer": ["GoPay", "Transfer Dibatalkan", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "label status": ["GoPay", "Ke BUDI", "Nominal Rp50.000", "Status: Ditolak", D_L5],
    "payment cancelled": ["QRIS", "Payment cancelled", "Merchant TOKO A", "Amount Rp25.000", "NMID ID1024358806544", D_L5],
    "transaksi batal": ["Transaksi Batal", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5],
    "pembayaran ditolak": ["Pembayaran Ditolak", "QRIS", "Merchant TOKO A", "Rp 25.000", "NMID ID1024358806544", D_L5],
    "payment rejected": ["Payment rejected", "Recipient BUDI", "Bank BCA", "Amount Rp50.000", D_L5],
    "transaction canceled": ["Transaction canceled", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5],
    "transaksi void": ["Transaksi Void", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5],
    "telah dibatalkan": ["Transaksi Anda telah dibatalkan", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5],
    "kata saja dibatalkan": ["DANA", "Dibatalkan", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja ditolak": ["DANA", "Ditolak", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja rejected": ["DANA", "Rejected", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja cancelled": ["DANA", "Cancelled!", "Ke SITI", "Nominal Rp50.000", D_L5],
    "status transaksi ditolak": ["BCA mobile", D_L5, "Ke BUDI", "Status Transaksi Ditolak", "Nominal Rp150.000"],
    "status batal": ["GoPay", "Ke BUDI", "Nominal Rp50.000", "Status: Batal", D_L5],
    "status void": ["GoPay", "Ke BUDI", "Nominal Rp50.000", "Status: VOID", D_L5],
    "judul di badan": ["Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5, "No. Ref 2026102612345678",
                       "Transfer Dibatalkan"],
    # Fix round 1 (review L5 I1, m1, m2, m3): kata itu menutup klausanya; "to"/"yang" jauh dari kata itu bukan penjaga;
    # ajakan/syarat sesudah tanda baca tetap status; tanggal/jam, oleh/karena sesudahnya; awalan telah/sudah/has been/was.
    "judul to": ["GoPay", "Transfer to BUDI cancelled", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul yang jauh": ["GoPay", "Transaksi yang Anda lakukan dibatalkan", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul lalu syarat": ["Transaksi Dibatalkan, jika saldo terpotong hubungi 14017", "Penerima BUDI", "Bank Tujuan BCA",
                          "Nominal Rp50.000", D_L5],
    "judul lalu kalimat": ["GoPay", "Transfer Dibatalkan. Hubungi CS jika saldo terpotong", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul bertanggal": ["GoPay", "Transfer Dibatalkan 26/10/2026 08:12", "Ke BUDI", "Nominal Rp50.000"],
    "judul oleh": ["Transaksi Dibatalkan oleh sistem", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", D_L5],
    "judul karena": ["Transaksi dibatalkan karena saldo tidak cukup", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000",
                     D_L5],
    "kata saja bertanggal": ["DANA", "Dibatalkan 26/10/2026 08:12", "Ke SITI", "Nominal Rp50.000"],
    "kata saja bertanggal wib": ["DANA", "Ditolak 26 Okt 2026, 08:12 WIB", "Ke SITI", "Nominal Rp50.000"],
    "kata saja bintang": ["DANA", "*** CANCELLED ***", "Ke SITI", "Nominal Rp50.000", D_L5],
    "telah dibatalkan saja": ["DANA", "Telah dibatalkan", "Ke SITI", "Nominal Rp50.000", D_L5],
    "sudah ditolak saja": ["DANA", "Sudah ditolak", "Ke SITI", "Nominal Rp50.000", D_L5],
    "has been cancelled saja": ["DANA", "Has been cancelled", "Ke SITI", "Nominal Rp50.000", D_L5],
    "was rejected saja": ["DANA", "Was rejected", "Ke SITI", "Nominal Rp50.000", D_L5],
    # Fix round 2 (re-review I3, m8): satu kata pelaku/cara, nominal Rp, #id, tanggal tanpa tahun, "on"/"•" + tanggal, ":".
    "judul ditolak bank": ["GoPay", "Pembayaran Ditolak Bank", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul ditolak sistem": ["GoPay", "Transfer Ditolak Sistem", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul penerbit kartu": ["GoPay", "Pembayaran Ditolak Penerbit Kartu", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul otomatis": ["GoPay", "Transaksi Dibatalkan Otomatis", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul nominal": ["GoPay", "Transfer Dibatalkan Rp50.000", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul id": ["GoPay", "Transaksi Dibatalkan #12345", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul on tanggal": ["GoPay", "Transaction Cancelled on 31 Oct 2026", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul tanpa tahun": ["GoPay", "Transfer dibatalkan 31/10 09:00", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "judul titik dua": ["GoPay", "Transfer Dibatalkan: rekening tidak aktif", "Ke BUDI", "Nominal Rp50.000", D_L5],
    "kata saja tanpa tahun": ["DANA", "Dibatalkan 31/10 09:00", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja otomatis": ["DANA", "Dibatalkan otomatis", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja bank": ["DANA", "Ditolak bank", "Ke SITI", "Nominal Rp50.000", D_L5],
    "kata saja titik tengah": ["DANA", "Dibatalkan • 31 Okt 2026", "Ke SITI", "Nominal Rp50.000", D_L5],
}
# Label status dengan nilai dibatalkan/ditolak pada tata letak transfer dan QRIS GoPay (kedua saklar).
CANCELLED_VALUES = ("Dibatalkan", "Ditolak", "Batal", "Void", "Rejected", "Cancelled", "Canceled", "Kartu ditolak",
                    "Transaksi dibatalkan",
                    # Fix round 1 (I1, m1): penjaga hanya di klausa kata itu; syarat sesudah tanda baca = ajakan.
                    "Saldo tidak cukup, transaksi ditolak", "Rekening tujuan tidak aktif, transfer dibatalkan",
                    "Dibatalkan (jika saldo terpotong akan dikembalikan)", "Ditolak, jika saldo terpotong hubungi 14017",
                    "Pembayaran yang kamu lakukan ditolak", "Payment to merchant rejected", "Ditolak oleh bank tujuan",
                    "Saldo tidak cukup, ditolak", "Akun tujuan tidak aktif; dibatalkan",      # tanpa judul: hanya nilai label
                    "Saldo tidak cukup (ditolak)")                                          # fix round 2 (m8): "(" batas klausa
# Kaki bersyarat/kebijakan/tanya: bukan status, tidak pernah menghitung kata dibatalkan/ditolak.
CANCEL_FOOTERS = ("Jika transaksi dibatalkan, dana kembali dalam 3 hari",
                  "Barang yang sudah dibeli tidak dapat dibatalkan",
                  "Transaksi tidak dapat dibatalkan",
                  "Transaksi yang dibatalkan tidak dapat dikembalikan",
                  "Pembayaran akan dibatalkan otomatis",
                  "Transaksi dibatalkan otomatis jika tidak dibayar",
                  "Transaksi dibatalkan? Hubungi 14017",
                  "Pengaduan transaksi dibatalkan: 14017",
                  "Payment cannot be cancelled",
                  "Batal",
                  "VOID",
                  # Fix round 1 (I2): kata itu tidak menutup klausanya = kalimat kebijakan.
                  "Transaksi dibatalkan maks 1x24 jam",
                  "Transaksi dibatalkan otomatis setelah 1x24 jam",
                  "Pembayaran dibatalkan otomatis dalam 15 menit",
                  "Pembelian dibatalkan tidak dapat direfund",
                  "Transaksi batal tidak dapat diuangkan",
                  "Dana transaksi dibatalkan dikembalikan dalam 3 hari kerja",
                  # Fix round 2 (re-review m7, I3): modal sesudah pelaku/sebab di klausa yang sama; angka polos bukan ekor.
                  "Transaksi dibatalkan oleh pembeli tidak dapat direfund",
                  "Transaksi dibatalkan karena barang rusak dapat ditukar",
                  "TRANSAKSI VOID 15.000",
                  "Transaksi Batal 2")
# Bukti sukses yang statusnya hanya label (tanpa judul; dibaca jalur struk di kedua saklar), untuk kaki di atas.
def success_label_proof(footer):
    return ["BCA mobile", "30/10/2026 14:22", "Ke BUDI", "Nominal Rp150.000", "Status : Berhasil", "Total Rp150.000", footer]


class CancelledVocabularyTests(unittest.IsolatedAsyncioTestCase):
    """Task L5 (spec §7, keputusan pemilik 3): "dibatalkan", "ditolak", "batal", "rejected", "cancelled"/"canceled", "void"
    = gagal, hanya di judul status (kata benda transaksi + kata itu, kata itu menutup klausanya), nilai label status
    pembayaran, dan baris yang diawali kata itu di 4 baris pertama (bukan "Batal"/"Void" tanpa kata benda: tombol, baris
    VOID struk). Baris badan pendek tidak membacanya; kaki bersyarat/tanya/bantuan, negasi/modal di klausa kata itu
    ("tidak dapat dibatalkan", "akan dibatalkan") dan kalimat kebijakan ("dibatalkan maks 1x24 jam") tidak dihitung."""

    async def test_cancelled_or_rejected_proofs_are_blocked_in_both_modes(self):
        for name, lines in CANCELLED_PROOFS.items():
            for enabled in (True, False):
                with self.subTest(name, enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, "gagal")
                    self.assertEqual([(c.code, c.level) for c in res.checks if c.code == "status_gagal"],
                                     [("status_gagal", "block")])

    async def test_cancelled_values_in_both_layouts_and_both_modes(self):
        for value in CANCELLED_VALUES:
            for name, make in (("transfer", transfer_with_status), ("qris", gopay_qris_with_status)):
                for enabled in (True, False):
                    with self.subTest(value, layout=name, enabled=enabled):
                        res = await read(make(value), enabled=enabled)
                        self.assertEqual(res.parsed.doc.status, "gagal")
                        self.assertIn("status_gagal", [c.code for c in res.checks])

    async def test_gopay_status_block_with_a_cancelled_value(self):
        for value in ("Transfer ke penerima dibatalkan", "Transfer uang ke penerima ditolak"):
            lines = gopay_transfer()
            lines[6] = value                         # di bawah "Status"; "Status  Selesai" tetap di rincian
            for enabled in (True, False):
                with self.subTest(value, enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, "gagal")
                    self.assertIn("status_gagal", [c.code for c in res.checks])
        # Kata saja di bawah "Status" dibaca persis seperti "Gagal" di posisi itu (tanpa penanda transfer, teks ini tidak
        # dikenali sebagai bukti: titik terbuka N1/L6e, bukan kosakata).
        for enabled in (True, False):
            got = {}
            for value in ("Gagal", "Dibatalkan", "Ditolak"):
                lines = gopay_transfer()
                lines[6] = value
                res = await read(lines, enabled=enabled)
                got[value] = (res.reader, res.parsed.doc.status, [c.code for c in res.checks])
            with self.subTest(enabled=enabled):
                self.assertEqual(got["Dibatalkan"], got["Gagal"])
                self.assertEqual(got["Ditolak"], got["Gagal"])

    async def test_batal_button_does_not_block(self):
        for lines in (["QRIS", "Menunggu pembayaran", "Merchant TOKO A", "Total Rp25.000", "NMID ID1024358806544", D_L5, "Batal"],
                      ["QRIS", "Batal", "Menunggu pembayaran", "Merchant TOKO A", "Total Rp25.000", "NMID ID1024358806544"],
                      ["Menunggu pembayaran", "Transfer ke BUDI", "Nominal Rp50.000", "Bayar", "Batal"]):
            for enabled in (True, False):
                with self.subTest(lines[1], enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertNotEqual(res.parsed.doc.status, "gagal")
                    self.assertNotIn("status_gagal", [c.code for c in res.checks])
        # Blok di bawah "Status" (saklar mati, `read_labelled_failure`): hanya baris tepat di bawah label adalah nilainya;
        # tombol "Batal" di bawah langkah-langkah bukan status.
        lines = gopay_transfer()
        lines[6:8] = ["Menunggu transfer ke penerima", "Batal"]
        self.assertIsNone(pc.read_labelled_failure(lines))
        for enabled in (True, False):
            with self.subTest("blok status", enabled=enabled):
                self.assertNotIn("status_gagal", [c.code for c in (await read(lines, enabled=enabled)).checks])

    async def test_store_receipts_with_void_or_cancel_footers_are_unchanged(self):
        void_line = ["TOKO MAJU", "01-10-2026 08:15", "KOPI 1 15.000", "VOID 1 KOPI 15.000", "ROTI 1 10.000", "SUSU 1 5.000",
                     "TOTAL 15.000", "TUNAI 15.000"]
        receipts = {"void": void_line, **{f: store_receipt(f) for f in CANCEL_FOOTERS}}
        for name, lines in receipts.items():
            for enabled in (True, False):
                with self.subTest(name, enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual((res.reader, res.parsed.doc.status, res.checks), ("struk_belanja", "berhasil", []))
                    self.assertFalse(looks_like_proof(textdoc(lines)))

    async def test_conditional_policy_and_question_footers_stay_success_on_proofs(self):
        for footer in CANCEL_FOOTERS:
            for enabled in (True, False):
                with self.subTest(footer, enabled=enabled):
                    lines = ["Transfer Berhasil", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31",
                             footer]
                    res = await read(lines, enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, "berhasil")
                    self.assertEqual(status_checks(res), [])
                with self.subTest(footer, layout="label saja", enabled=enabled):
                    res = await read(success_label_proof(footer), enabled=enabled)
                    self.assertEqual(res.parsed.doc.status, "berhasil")
                    self.assertEqual(status_checks(res), [])

    async def test_edc_void_slip_is_blocked(self):
        """Keputusan pengendali (fix round 1): "TRANSAKSI VOID" di slip EDC = transaksi dibatalkan, diblokir."""
        for lines in (store_receipt("TRANSAKSI VOID"), success_label_proof("TRANSAKSI VOID")):
            for enabled in (True, False):
                with self.subTest(lines[0], enabled=enabled):
                    res = await read(lines, enabled=enabled)
                    self.assertEqual((res.parsed.doc.status, status_checks(res)), ("gagal", ["status_gagal"]))

    async def test_selesai_with_a_cancel_word_anywhere_is_never_berhasil(self):
        """Jalur bukti (saklar menyala): "Status Selesai" + kata itu di baris mana pun bukan berhasil (`_NOT_DONE` tetap);
        di judul kata saja itu gagal."""
        base = lines_of("real-gopay-qris-01")
        for at in (1, 5, len(base)):
            for word in ("Dibatalkan", "Ditolak", "Batal", "Rejected", "Cancelled"):
                lines = base[:at] + [word] + base[at:]
                with self.subTest(word, at=at):
                    status = (await read(lines)).parsed.doc.status
                    self.assertNotEqual(status, "berhasil")
                    if at == 1 and word != "Batal":
                        self.assertEqual(status, "gagal")

    def test_positions(self):
        lines = ["QRIS", "Merchant TOKO A", "Jumlah Rp5.000", "NMID ID1024358806544", D_L5, "Dibatalkan"]
        # Kata saja di badan (sesudah 4 baris pertama) tidak dibaca; di judul dibaca.
        self.assertEqual(pc.read_status(lines), pc.TIDAK_DIKETAHUI)
        self.assertEqual(pc.read_status([lines[0], "Dibatalkan", *lines[1:5]]), pc.GAGAL)
        # "Batal"/"Void" tanpa kata benda tidak pernah dibaca, juga di judul.
        for word in ("Batal", "VOID", "Batal!"):
            with self.subTest(word):
                self.assertEqual(pc.read_status([lines[0], word, *lines[1:5]]), pc.TIDAK_DIKETAHUI)
        for text, status in (("Transfer Dibatalkan", pc.GAGAL), ("Pembayaran Ditolak", pc.GAGAL), ("Transaksi Batal", pc.GAGAL),
                             ("Payment rejected", pc.GAGAL), ("Payment cancelled", pc.GAGAL), ("Transaksi VOID", pc.GAGAL),
                             ("Transaksi telah dibatalkan oleh bank", pc.GAGAL),
                             ("Transaksi Dibatalkan, silakan coba lagi", pc.GAGAL),
                             ("Transaksi tidak dapat dibatalkan", None), ("Transaksi bisa dibatalkan", None),
                             ("Transaksi yang dibatalkan tidak dapat dikembalikan", None),
                             ("Pembayaran akan dibatalkan otomatis", None), ("Payment will be cancelled", None),
                             ("Transaksi dibatalkan jika tidak dibayar", None), ("Jika transaksi dibatalkan, dana kembali", None),
                             ("Transaksi dibatalkan?", None), ("Untuk transaksi yang dibatalkan hubungi 14017", None),
                             ("Pembatalan transaksi", None), ("TOKO BATAL JAYA", None), ("Kartu ditolak", None),
                             # Fix round 1: kata itu harus menutup klausanya (I2), boleh diikuti tanggal/jam atau pelaku/sebab.
                             ("Transaksi Dibatalkan 26/10/2026 08:12", pc.GAGAL), ("Transaksi Dibatalkan.", pc.GAGAL),
                             ("Transaksi dibatalkan karena saldo tidak cukup", pc.GAGAL),
                             ("Payment cancelled by user", pc.GAGAL), ("Transfer to BUDI cancelled", pc.GAGAL),
                             ("Pembayaran yang Anda lakukan dibatalkan", pc.GAGAL),
                             ("Transaksi dibatalkan maks 1x24 jam", None), ("Transaksi dibatalkan setelah 26/10/2026", None),
                             ("Pembayaran dibatalkan otomatis dalam 15 menit", None),
                             ("Pembelian dibatalkan tidak dapat direfund", None),
                             ("Transaksi dibatalkan 24 jam", None), ("Total transaksi dibatalkan 3", None),
                             ("Daftar transaksi yang dibatalkan", None),
                             # Fix round 2 (I3): satu kata pelaku/cara, lalu nominal Rp/#id/tanggal (juga tanpa tahun).
                             ("Pembayaran Ditolak Bank", pc.GAGAL), ("Transaksi Dibatalkan Otomatis", pc.GAGAL),
                             ("Pembayaran Ditolak Penerbit Kartu", pc.GAGAL), ("Transfer Dibatalkan Rp50.000", pc.GAGAL),
                             ("Transaksi Dibatalkan #12345", pc.GAGAL), ("Transaction Cancelled on 31 Oct 2026", pc.GAGAL),
                             ("Transfer dibatalkan 31/10 09:00", pc.GAGAL), ("Transaksi Dibatalkan 31 Okt", pc.GAGAL),
                             ("Transaksi Ditolak Bank Rp50.000", pc.GAGAL), ("Transfer Dibatalkan: rekening tidak aktif", pc.GAGAL),
                             ("TRANSAKSI VOID 15.000", None), ("Transaksi Batal 2", None),
                             ("Transaksi Ditolak Bank Tujuan", None), ("Transaksi Dibatalkan Otomatis Sistem", None),
                             # m7: modal sesudah pelaku/sebab di klausa yang sama = kebijakan; "tidak" saja bukan modal.
                             ("Transaksi dibatalkan oleh pembeli tidak dapat direfund", None),
                             ("Transaksi dibatalkan karena barang rusak dapat ditukar", None),
                             ("Transaksi dibatalkan oleh sistem, dana akan dikembalikan", pc.GAGAL)):
            with self.subTest(text):
                self.assertEqual(pc._strongest(pc._status_lines([text], pc.HEADER_WORDS)), status)
        self.assertTrue(pc._is_status_title("Transfer Dibatalkan"))
        self.assertFalse(pc._is_status_title("Transaksi tidak dapat dibatalkan"))
        # Satu daftar kata benda untuk judul gagal biasa dan judul batal (L6c menambah kata benda di satu tempat).
        self.assertIn(pc._TITLE_NOUN, pc._STATUS_TITLE.pattern)
        self.assertIn(pc._TITLE_NOUN, pc._CANCEL_TITLE.pattern)
        # Baris (c) di judul: awalan telah/sudah/has been/was, tanggal/jam sesudahnya; bukan kalimat kebijakan.
        for word, status in (("Telah dibatalkan", pc.GAGAL), ("Sudah ditolak", pc.GAGAL), ("Has been cancelled", pc.GAGAL),
                             ("Was rejected", pc.GAGAL), ("Dibatalkan 26/10/2026 08:12", pc.GAGAL),
                             ("Ditolak oleh bank", pc.GAGAL), ("Dibatalkan otomatis dalam 15 menit", pc.TIDAK_DIKETAHUI),
                             ("Ditolak bank", pc.GAGAL), ("Dibatalkan 31/10 09:00", pc.GAGAL),
                             ("Dibatalkan • 31 Okt 2026", pc.GAGAL), ("Dibatalkan 15", pc.TIDAK_DIKETAHUI),
                             ("Dibatalkan jika tidak dibayar", pc.TIDAK_DIKETAHUI), ("Telah batal", pc.TIDAK_DIKETAHUI)):
            with self.subTest("judul", word=word):
                self.assertEqual(pc.read_status([lines[0], word, *lines[1:5]]), status)
        # Label "Status" berdiri sendiri, nilainya di baris bawah (di badan): dibaca dari tingkat label, bukan baris badan.
        below = ["Transfer", "Penerima BUDI", "Bank Tujuan BCA", "Nominal Rp50.000", "30 Okt 2026 09:31", "Status"]
        for word in ("Dibatalkan", "Ditolak", "Batal", "Void"):
            with self.subTest("label di atas", word=word):
                self.assertEqual(pc.read_status([*below, word]), pc.GAGAL)
                self.assertEqual(pc.read_status([*below[:-1], word]), pc.TIDAK_DIKETAHUI)   # tanpa label: baris badan
        # Nilai label status: kata itu di mana saja di nilainya, kecuali sesudah negasi/modal.
        for line, status in (("Status: Dibatalkan", "gagal"), ("Status Transaksi Ditolak", "gagal"), ("Status: Batal", "gagal"),
                             ("Status: Void", "gagal"), ("Status: Kartu ditolak", "gagal"),
                             ("Status: Tidak dapat dibatalkan", None),
                             # Fix round 1 (I1): penjaga di klausa kata itu saja; syarat tepat sesudahnya tidak dihitung.
                             ("Status: Saldo tidak cukup, transaksi ditolak", "gagal"),
                             ("Status: Ditolak, jika saldo terpotong hubungi 14017", "gagal"),
                             ("Status: Dibatalkan (jika saldo terpotong akan dikembalikan)", "gagal"),
                             ("Status: Pembayaran yang kamu lakukan ditolak", "gagal"),
                             ("Status: Dibatalkan jika tidak dibayar", None),
                             ("Status: Dibatalkan otomatis bila tidak dibayar", None),
                             ("Status: Saldo cukup, tidak dapat dibatalkan", None),
                             ("Status: Saldo tidak cukup, ditolak", "gagal"),
                             ("Status: Dibatalkan kecuali dibayar hari ini", None),
                             ("Status: Cancelled unless paid today", None),
                             # Fix round 2 (m8): "(" memutus klausa penjaga nilai label.
                             ("Status: Saldo tidak cukup (ditolak)", "gagal"),
                             ("Status: Berhasil (tidak bisa dibatalkan)", None)):
            with self.subTest(line):
                self.assertEqual(pc.read_labelled_failure([line]), status)
