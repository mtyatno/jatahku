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

