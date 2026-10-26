import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import contextlib, copy, io, json, re, stat, subprocess, sys, tempfile, unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.scripts import kotak_corpus
from app.scripts.kotak_corpus import (
    GATE, CorpusError, evaluate, expect_from, format_corpus, gate_failures, load_corpus, main, mask_line, needs_review,
    receipt_samples, sample_context, write_corpus,
)
from app.services.kotak_struk.document import Counterparty, DokumenBayar
from app.services.kotak_struk.extract import PdfLocked
from app.services.kotak_struk.readers.labels import WIB

FIXTURE = Path(__file__).parent / "fixtures" / "kotak" / "corpus.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = json.loads(FIXTURE.read_text())["samples"]
SYNTHETIC = [s for s in SAMPLES if not s["real"]]
BY_ID = {s["id"]: s for s in SAMPLES}
RECEIPTS = receipt_samples()

TRANSFER_TXT = "\n".join([
    "Transfer Berhasil", "26 Okt 2026, 09:30 WIB", "Penerima", "BUDI SANTOSO", "Bank Tujuan BRI",
    "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp150.000", "No. Ref 2026102612345678", "",
])

# Baris yang dulu bocor atau mudah bocor (review A13 I1, I2, M1, dan aturan dua spasi / ribuan ketat).
LEAKY_LINES = [
    "No. Rekening 1234 5678 9012", "HP 0812 - 3456 - 7890", "Rek 0812–3456–7890",
    "Rek 0812‑3456‑7890", "Rek 0812−3456−7890", "Ref 6123\t4567\t8812",
    "Rekening 0123  0100  1234  567", "Rek 123.456.7890", "Transaction ID2026102612345678", "User ID081234567890",
    "Ref IDR1234567890", "Rp:0812345678", "Rp 150.000.123456", "Rp 1.500.000,001234567", "IDR1,500,000.001234",
    "Rp50.000 ke 1234567890", "No. Rek: 123-456-7890", "+62 812 3456 7890", "VA 8077 0812 3456 7890",
    "Ref 2026-10-26-123456", "Jam 10.15.30.123456", "NPWP 01.234.567.8-901.000", "Kode 12 1999 5678",
    "Rekening 1234 5678  9012", "Ref 6123  4567", "Saldo 150.000.123456", "Ref 150.000-1234",
    "Rek 0812 – 3456 – 7890", "ID1024358806544",
    "HP 081.234.567.890", "Rek 0.123.456.789", "Rp 081234567", "NMID ID1024358806544 TID1234567890",
    "Rek 1234–26-10-2026", "Kode 24.13.34",
]

# Baris yang setelah disamarkan masih menampilkan 7-10 digit di samping huruf OCR, "/", atau >= 3 spasi
# (re-review A13 I1-r1): mask_line tidak menyamarkan semuanya, jadi `add` harus memberi tanda PERIKSA.
HALF_MASKED = {
    "HP 0812 34S6 7890": "HP …1234S6 7890",
    "Rek 1234 S678 9012": "Rek 1234 S…9012",
    "Rek 12345 67S9 012": "Rek …4567S9 012",
    "No. Rek 0123 0100 1234 S67": "No. Rek …1234 S67",
    "No. Rek 6788 472B 7639 4242": "No. Rek …8472B …4242",
    "Ref 61234567/8812": "Ref …4567/8812",
    "Ref 61234567   8812": "Ref …4567   8812",
}

_SEP = r"[\s.,\-‐-―−]"
_END = r"(?![.,:/\-]?\d)"
_THOUSANDS = r"(?!0)\d{1,3}([.,])\d{3}(?:\1\d{3})*(?:[.,]\d{2})?"     # nominal tidak berawalan 0


def _leftover_digit_runs(line: str) -> list[str]:
    """Deret >= 6 digit (boleh dipisah spasi apa pun, strip apa pun, titik, atau koma) yang tersisa sesudah bentuk
    yang boleh tetap utuh dibuang: penanda tersamar, NMID di baris NMID, nominal, tanggal, jam.
    Sengaja ditulis terpisah dari implementasi mask_line."""
    allowed = [
        r"…\d{4}",
        rf"(?<![\d.,])(?:Rp|IDR)[ .:]*(?:{_THOUSANDS}|(?!0\d)\d{{1,9}}(?:[.,]\d{{2}})?){_END}",
        rf"(?<![\d.,\-]){_THOUSANDS}{_END}",
        rf"(?<![\d.,/\-])\d{{1,2}}([-/.])\d{{1,2}}\1(?:\d{{4}}|\d{{2}}){_END}",
        rf"(?<![\d.,/\-])\d{{4}}([-/.])\d{{1,2}}\1\d{{1,2}}{_END}",
        rf"(?<![\d:.])\d{{1,2}}[:.]\d{{2}}(?:[:.]\d{{2}})?{_END}",
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Okt|Nov|Dec|Des)[a-z]*\.? \d{1,2},? \d{4}(?!\d)",
    ]
    if "NMID" in line.upper():
        allowed.insert(0, r"(?<![A-Za-z0-9])ID\s?\d{10,}")
    rest = line
    for rx in allowed:
        rest = re.sub(rx, "#", rest)
    return re.findall(rf"\d(?:{_SEP}{{0,3}}\d){{5,}}", rest)


class CorpusTests(unittest.TestCase):
    def test_mask_line(self):
        self.assertEqual(mask_line("Rekening Tujuan 0123 0100 1234 567"), "Rekening Tujuan …4567")
        self.assertEqual(mask_line("No. Referensi 612345678812"), "No. Referensi …8812")
        self.assertEqual(mask_line("Nominal Rp1.500.000"), "Nominal Rp1.500.000")
        self.assertEqual(mask_line("NMID ID1024358806544"), "NMID ID1024358806544")

    def test_synthetic_corpus_passes_gate(self):
        samples = load_corpus(FIXTURE)   # sampel yang salah isi -> CorpusError yang menyebut sampel dan field-nya
        r = evaluate([s for s in samples if not s["real"]] + RECEIPTS)
        self.assertEqual(r["failures"], [])
        self.assertEqual(gate_failures(r), [])
        self.assertEqual(r["n"], 10)

    def test_real_corpus_meets_release_gate(self):
        real = [s for s in load_corpus(FIXTURE) if s["real"] and s.get("reviewed")]
        if not real:
            self.skipTest("korpus nyata belum ada (FS.5, Task A14)")
        r = evaluate(real + RECEIPTS)
        self.assertEqual(gate_failures(r), [], f"gerbang {GATE} — gagal: {r['failures']}")


class MaskLineTests(unittest.TestCase):
    def assertMasked(self, cases: dict):
        for line, expected in cases.items():
            with self.subTest(line):
                self.assertEqual(mask_line(line), expected)

    def assertKept(self, lines):
        self.assertMasked({line: line for line in lines})

    def test_account_number_masked_even_on_a_line_with_rp(self):
        self.assertEqual(mask_line("Rp50.000 ke 1234567890"), "Rp50.000 ke …7890")

    def test_dates_times_and_nominals_kept(self):
        self.assertKept([
            "Tanggal 2026-10-26 10:15", "26-10-2026 08:12", "Total IDR 1500000", "Nominal 150,000.00",
            "26/10/2026 19:05", "26.10.2026 08.12.33", "Tanggal 26 Okt 2026 08:12:33 WIB", "Oct 26 2026 09:30",
            "Okt 26, 2026", "Rp 1500000", "Rp. 1.500.000,00", "Jumlah: Rp:150000", "26/10/26", "Rp25.000,-",
            "26/10/2026 - 08:12", "Tanggal 2026-10-26  10:15", "Rp 1.500.000", "Saldo 12.345.678.901",
        ])

    def test_digit_threshold(self):
        self.assertMasked({"Ref 12345": "Ref 12345", "Ref 123456": "Ref …3456", "Ref 12 345": "Ref 12 345",
                           "Ref 12 3456": "Ref …3456"})

    def test_separators_inside_a_digit_run(self):
        self.assertMasked({
            "No. Rek 1234-5678-90": "No. Rek …7890",
            "ID Transaksi 123 456 789": "ID Transaksi …6789",
            "Rekening 0123-01-001234-56-7": "Rekening …4567",
            "HP 0812-3456-7890": "HP …7890",
            "Rekening 0123  0100  1234  567": "Rekening …4567",              # OCR: dua spasi antarkotak
            "No. Rekening 1234 5678 9012": "No. Rekening …9012",   # NBSP dari lapisan teks PDF
            "Rek 1234 5678  9012": "Rek …9012",                     # U+202F, U+2009 + spasi
            "Ref 6123\t4567\t8812": "Ref …8812",
            "HP 0812 - 3456 - 7890": "HP …7890",
            "Rek 0812–3456–7890": "Rek …7890",                     # en dash
            "Rek 0812 – 3456 – 7890": "Rek …7890",
            "Rek 0812‑3456‑7890": "Rek …7890",                     # non-breaking hyphen
            "Rek 0812−3456−7890": "Rek …7890",                     # minus sign
            "Rek 0812―3456": "Rek …3456",                                # horizontal bar
        })

    def test_three_spaces_or_a_newline_end_a_digit_run(self):
        self.assertKept(["Ref 1234   5678"])
        self.assertEqual(mask_line("Ref 1234\n5678"), "Ref 1234\n5678")

    def test_strict_thousands_only(self):
        self.assertKept(["Total 1.500.000", "Nominal 150,000.00", "Total 1.500.000,00", "Biaya 2.500"])
        self.assertMasked({
            "Rek 123.456.7890": "Rek …7890",
            "Rek 12.3456.789": "Rek …6789",
            "Saldo 1.500,000": "Saldo …0000",            # pemisah tidak konsisten
            "Saldo 1.500.000.00": "Saldo …0000",         # desimal harus memakai pemisah yang lain
            "Saldo 150.000.123456": "Saldo …3456",
            "Ref 1.500.000,001234567": "Ref …4567",
            "NPWP 01.234.567.8-901.000": "NPWP …1000",   # nominal yang menempel strip pada deret lain bukan nominal
            "Ref 150.000-1234": "Ref …1234",
            "Rek 1234.567": "Rek …4567",                 # nominal tidak boleh mulai di tengah deret
        })

    def test_currency_amount_shape(self):
        self.assertKept(["Rp 1500000", "Total IDR 1500000", "Rp 999999999", "IDR 150000.00", "Rp 150.000"])
        self.assertMasked({
            "Ref IDR1234567890": "Ref IDR…7890",
            "IDR 612345678812": "IDR …8812",
            "Rp:0812345678": "Rp:…5678",
            "Rp 1000000000": "Rp …0000",
            "Rp 150.000.123456": "Rp …3456",
            "Rp 1.500.000,001234567": "Rp …4567",
            "IDR1,500,000.001234": "IDR…1234",
            "Grp1234567": "Grp…4567",                    # "rp" di dalam kata bukan Rupiah
        })

    def test_numbers_starting_with_zero_are_not_amounts(self):
        self.assertMasked({
            "HP 081.234.567.890": "HP …7890",
            "Rek 0.123.456.789": "Rek …6789",
            "Rek 012.345.678": "Rek …5678",
            "Rp 081234567": "Rp …4567",
            "Rp. 0.123.456": "Rp. …3456",
        })
        self.assertKept(["Rp 0", "Rp 0,00", "Diskon Rp0", "Total Rp 1.500.000", "Rp 10.000"])

    def test_nmid_kept_only_on_an_nmid_line(self):
        self.assertKept(["NMID ID1024358806544", "NMID: ID 1024358806544", "nmid : ID1024358806544"])
        self.assertMasked({
            "Transaction ID2026102612345678": "Transaction ID…5678",
            "User ID081234567890": "User ID…7890",
            "ID1024358806544": "ID…6544",
            "NMID ID123456789": "NMID ID…6789",          # 9 digit: bukan NMID
            # "ID" di dalam kata lain di baris NMID bukan NMID.
            "NMID ID1024358806544 TID1234567890": "NMID ID1024358806544 TID…7890",
        })

    def test_dates_and_times_need_their_guards(self):
        self.assertMasked({
            "Kode 12 1999 5678": "Kode …5678",           # "12 1999" tanpa nama bulan bukan tanggal
            "Ref 2026-10-26-1234": "Ref …1234",
            "Ref 2026-10-26-123456": "Ref …3456",
            "Rek 1234-12-10-26": "Rek …1026",
            "Rek 26-10-2026-1234": "Rek …1234",
            "Rek 12-10-1234": "Rek …1234",               # tahun 1234 bukan tanggal
            "Rek 12-10.2026": "Rek …2026",               # pemisah tanggal harus sama
            "Kode 99.99.99": "Kode …9999",               # bukan jam
            "Kode 24.13.34": "Kode …1334",               # jam 24 bukan jam (dan bulan 13 bukan tanggal)
            "Jam 10.15.30.123456": "Jam …3456",
            "Rek 1234–26-10-2026": "Rek …2026",          # tanggal yang menempel en dash pada deret lain
        })
        self.assertKept(["Kode 24.12.34"])                # tanggal d.m.yy yang sah (24 Des 2034) tetap utuh
        self.assertKept(["Jam 08:12:33", "Jam 08.12.33", "Jam 23.59"])

    def test_short_numbers_and_already_masked_text_kept(self):
        self.assertKept(["Rekening Tujuan …4567", "Kartu ****1234", "No. Rek xxxx1234", "Terminal ID A01",
                         "ID Transaksi A1B2C3D4", "Kode 12345", "NMID ID10…6544"])

    def test_mask_line_is_idempotent(self):
        for line in ["Rekening Tujuan 0123 0100 1234 567", "Rp50.000 ke 1234567890", "Ref 123456 12:30",
                     "No. Rek 1234-5678-90", *LEAKY_LINES]:
            with self.subTest(line):
                once = mask_line(line)
                self.assertEqual(mask_line(once), once)

    def test_no_secret_digit_run_left_after_masking(self):
        lines = [(s["id"], line) for s in SYNTHETIC for line in s["lines"]] + [("bocor", line) for line in LEAKY_LINES]
        for sample_id, line in lines:
            masked = mask_line(line)
            with self.subTest(sample=sample_id, line=line):
                self.assertEqual(_leftover_digit_runs(masked), [])
                compact = re.sub(r"[^\d]", "", masked)
                for secret in ("012301001234567", "612345678812", "000151856123", "2026102612345678", "081234567890"):
                    self.assertNotIn(secret, compact)

    def test_independent_checker_sees_spaced_and_dotted_runs(self):
        for leak in ["Rek 1234 5678 9012", "HP 0812 - 3456 - 7890", "Rek 123.456.7890", "Ref 0123  0100  1234",
                     "Transaction ID2026102612345678", "Rp 150.000.123456"]:
            with self.subTest(leak):
                self.assertNotEqual(_leftover_digit_runs(leak), [])

    def test_masked_synthetic_samples_still_read_the_same(self):
        # Penyamaran tidak merusak yang dibaca pembaca (nominal, tanggal, nama, status, arah).
        masked = [{**s, "lines": [mask_line(x) for x in s["lines"]]} for s in SYNTHETIC]
        self.assertEqual(evaluate(masked)["failures"], [])


class ReviewFlagTests(unittest.TestCase):
    def test_lines_with_six_digits_left_are_flagged(self):
        for line in ["Ref 6123/4567/8812", "No 123 4S6 7890", "Kode 12_3456_78", "Ref 1234   5678", "Ref 1234, 5678",
                     "Kode 12_3456", "Rek 1234 26/10/2026 5678", "Ref 12:34:56:78"]:
            with self.subTest(line):
                self.assertEqual(mask_line(line), line)   # premis: tidak disamarkan aturan mana pun
                self.assertTrue(needs_review(line))

    def test_half_masked_numbers_are_flagged(self):
        for line, masked in HALF_MASKED.items():
            with self.subTest(line):
                self.assertEqual(mask_line(line), masked)   # premis: >= 6 digit masih terlihat (7-10 bila huruf OCR dibaca)
                self.assertGreaterEqual(len(re.findall(r"\d", masked)), 6)
                self.assertTrue(needs_review(masked))

    def test_masked_tokens_count_as_four_digits(self):
        self.assertTrue(needs_review("Ref …4567 12"))         # token + 2 digit lepas = 6
        self.assertFalse(needs_review("Ref …4567 1"))         # 5: di bawah ambang
        self.assertTrue(needs_review("Ref …4567,…1234"))   # dua token menempel tanda baca
        self.assertTrue(needs_review("Ref …4567/…1234"))
        self.assertFalse(needs_review("Ref …4567 …1234"))  # token berdiri sendiri, dipisah spasi
        self.assertFalse(needs_review("…4567 …1234"))      # awal dan akhir baris juga pemisah
        self.assertFalse(needs_review("Ref (…4567)"))          # satu token: 4 digit saja
        # Dua nomor >= 6 digit yang dipisah huruf OCR: token kedua menempel huruf di depannya.
        self.assertEqual(mask_line("Rek 678812 B47276394242"), "Rek …8812 B…4242")
        self.assertTrue(needs_review("Rek …8812 B…4242"))
        # Hanya keluaran mask_line (`…` + tepat 4 digit) yang dihitung sebagai penanda; "…123" adalah digit lepas.
        self.assertTrue(needs_review("Ref …123 …4567"))
        # Nominal nol tetap bentuk yang dibiarkan: tidak ikut dihitung bersama penanda di sebelahnya.
        self.assertFalse(needs_review("Biaya Rp 0,00 …4567"))
        self.assertTrue(needs_review("Biaya 0,00 …4567"))     # tanpa Rp bukan nominal: 3 + 4 digit

    def test_kept_forms_masked_numbers_and_short_codes_not_flagged(self):
        lines = [mask_line(x) for s in SYNTHETIC for x in s["lines"]] + [
            "Rekening: …7890 a.n. BUDI", "No. Rek: …7890", "+…7890", "Kode 24.12.34",
            "Tanggal 26 Okt 2026 08:12:33 WIB", "Kasir 01 14-10-2026 08:15", "NMID ID1024358806544", "Nominal Rp1.500.000",
            "Rekening Tujuan …4567", "Ref …5678 …1234", "ID Transaksi A1B2C3D4", "Kode 1_2345", "Terminal ID A01 Ref 12345",
            "Rp 25.000 x 3 = Rp 75.000", "26/10/2026 19:05",
        ]
        for line in lines:
            with self.subTest(line):
                self.assertFalse(needs_review(line))


class EvaluateTests(unittest.TestCase):
    def test_result_shape_and_perfect_synthetic_scores(self):
        r = evaluate(SYNTHETIC)
        self.assertEqual(set(r), {"n", "amount_date_status_pct", "counterparty_pct", "doc_type_pct", "flow_pct", "issuer_pct",
                                  "struk_as_proof", "failures", "rows"})
        self.assertEqual(r["n"], 6)
        for key in ("amount_date_status_pct", "counterparty_pct", "doc_type_pct", "flow_pct"):
            self.assertEqual(r[key], 100.0, key)
        self.assertIsNone(r["issuer_pct"])   # tidak ada sampel dengan issuer yang diharapkan
        self.assertEqual((r["struk_as_proof"], r["failures"]), ([], []))
        self.assertEqual([row["id"] for row in r["rows"]], [s["id"] for s in SYNTHETIC])
        row = r["rows"][0]
        self.assertTrue(row["ok"])
        self.assertEqual(set(row["fields"]), {"doc_type", "total", "date", "status", "flow", "counterparty"})
        self.assertEqual(row["fields"]["total"], {"ok": True, "expected": 25000, "actual": 25000})
        self.assertEqual(row["fields"]["date"]["actual"], "2026-10-26")

    def test_counterparty_ignores_case_and_spacing_and_date_ignores_time_and_offset(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        s["expect"]["counterparty"] = "  siti   aminah "
        s["expect"]["paid_at"] = "2026-10-25T20:00:00+00:00"   # = 26 Okt 03:00 WIB; jam berbeda, tanggal WIB sama
        self.assertEqual(evaluate([s])["failures"], [])
        s["expect"]["paid_at"] = "2026-10-25T16:00:00+00:00"   # = 25 Okt 23:00 WIB
        r = evaluate([s])
        self.assertEqual(r["failures"], ["sint-qris-1"])
        self.assertEqual(r["rows"][0]["fields"]["date"], {"ok": False, "expected": "2026-10-25", "actual": "2026-10-26"})

    def test_none_expectations(self):
        topup = copy.deepcopy(BY_ID["sint-topup"])           # counterparty null ↔ None
        self.assertEqual(evaluate([topup])["failures"], [])
        topup["expect"]["counterparty"] = ""                   # "" ↔ None
        self.assertEqual(evaluate([topup])["failures"], [])
        topup["expect"]["counterparty"] = "GOPAY"
        self.assertEqual(evaluate([topup])["counterparty_pct"], 0.0)
        qris = copy.deepcopy(BY_ID["sint-qris-1"])
        qris["expect"]["counterparty"] = ""
        self.assertEqual(evaluate([qris])["failures"], ["sint-qris-1"])
        empty = {"id": "kosong", "real": False, "lines": ["halo"],
                 "expect": {"doc_type": "tidak_dikenali", "total": None, "paid_at": None, "counterparty": None,
                            "status": "tidak_diketahui", "flow": "tidak_diketahui"}}
        r = evaluate([empty])
        self.assertEqual(r["failures"], [])
        self.assertEqual(r["doc_type_pct"], 100.0)

    def test_proof_percentages_only_over_expected_proofs_and_rounded_down(self):
        wrong = copy.deepcopy(BY_ID["sint-qris-2"])
        wrong["expect"]["total"] = 16000
        r = evaluate([BY_ID["sint-qris-1"], wrong, BY_ID["sint-transfer-1"]])
        self.assertEqual(r["amount_date_status_pct"], 66.6)   # 2/3, dibulatkan ke bawah: 66.66 tidak jadi 66.7
        self.assertEqual((r["counterparty_pct"], r["doc_type_pct"]), (100.0, 100.0))
        self.assertEqual(r["failures"], ["sint-qris-2"])
        self.assertEqual(gate_failures(r), ["amount_date_status_pct 66.6% < 95.0%"])

    def test_status_and_date_each_count_in_the_gate_metric(self):
        samples = copy.deepcopy(SYNTHETIC)
        samples[0]["expect"]["status"] = "gagal"                              # sint-qris-1: status saja
        samples[2]["expect"]["paid_at"] = "2026-10-25T09:30:00+07:00"         # sint-transfer-1: tanggal saja
        r = evaluate(samples)
        self.assertEqual(r["amount_date_status_pct"], 66.6)                   # 4/6
        self.assertEqual(r["failures"], ["sint-qris-1", "sint-transfer-1"])
        self.assertEqual([row["ok"] for row in r["rows"]], [False, True, False, True, True, True])
        self.assertEqual((r["counterparty_pct"], r["flow_pct"], r["doc_type_pct"]), (100.0, 100.0, 100.0))

    def test_flow_mismatch_is_a_failure_but_not_gated(self):
        s = copy.deepcopy(BY_ID["sint-masuk"])
        s["expect"]["flow"] = "keluar"
        r = evaluate([s])
        self.assertEqual((r["failures"], r["flow_pct"]), (["sint-masuk"], 0.0))
        self.assertEqual(gate_failures(r), [])

    def test_issuer_compared_only_when_expected(self):
        topup, qris = copy.deepcopy(BY_ID["sint-topup"]), copy.deepcopy(BY_ID["sint-qris-1"])
        topup["expect"]["issuer"] = "gopay"
        r = evaluate([topup, qris])
        self.assertEqual((r["failures"], r["issuer_pct"]), ([], 100.0))       # pembagi: hanya sampel dengan issuer
        self.assertNotIn("issuer", r["rows"][1]["fields"])
        topup["expect"]["issuer"] = "ovo"
        qris["expect"]["issuer"] = None                                        # None ↔ None
        r = evaluate([topup, qris])
        self.assertEqual((r["failures"], r["issuer_pct"]), (["sint-topup"], 50.0))
        self.assertEqual(r["rows"][0]["fields"]["issuer"], {"ok": False, "expected": "ovo", "actual": "gopay"})
        self.assertEqual(gate_failures(r), [])                                 # issuer tidak digerbang

    def test_store_receipt_read_as_proof_fails_gate(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        s["id"] = "struk-terbaca-qris"
        s["expect"] = {**s["expect"], "doc_type": "struk_belanja"}
        r = evaluate([BY_ID["sint-transfer-1"], s])
        self.assertEqual(r["struk_as_proof"], ["struk-terbaca-qris"])
        self.assertEqual(r["doc_type_pct"], 50.0)
        self.assertIn("struk belanja terbaca sebagai bukti bayar: struk-terbaca-qris", gate_failures(r))

    def test_only_expected_store_receipts_count_as_struk_as_proof(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        s["expect"] = {**s["expect"], "doc_type": "tidak_dikenali"}
        r = evaluate([BY_ID["sint-transfer-1"], s])
        self.assertEqual((r["struk_as_proof"], r["failures"]), ([], ["sint-qris-1"]))

    def test_gate_fails_without_proof_samples(self):
        store = {"id": "struk-1", "real": True, "reviewed": True,
                 "lines": ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400"],
                 "expect": {"doc_type": "struk_belanja", "total": 45400, "paid_at": "2026-10-14T00:00:00+07:00",
                            "counterparty": "Alfamart", "status": "berhasil", "flow": "keluar"}}
        r = evaluate([store])
        self.assertEqual((r["n"], r["failures"], r["doc_type_pct"]), (1, [], 100.0))
        self.assertIsNone(r["amount_date_status_pct"])
        self.assertIsNone(r["counterparty_pct"])
        reasons = gate_failures(r)
        self.assertEqual(len(reasons), 2)
        self.assertTrue(all("tidak ada sampel QRIS/transfer" in x for x in reasons))

    def test_indomaret_receipts_checked_for_doc_type_only(self):
        self.assertEqual([s["id"] for s in RECEIPTS], ["indomaret-s1", "indomaret-s2", "indomaret-s3", "indomaret-s4"])
        self.assertTrue(all(s["expect"] == {"doc_type": "struk_belanja"} for s in RECEIPTS))
        self.assertEqual(RECEIPTS[0]["today"], "2025-05-24")   # tanggal struk: evaluasi tidak ikut kalender
        r = evaluate(RECEIPTS)
        self.assertEqual((r["n"], r["doc_type_pct"], r["failures"], r["struk_as_proof"]), (4, 100.0, [], []))
        self.assertIsNone(r["amount_date_status_pct"])
        self.assertTrue(all(set(row["fields"]) == {"doc_type"} for row in r["rows"]))
        # Struk yang terbaca sebagai bukti bayar menggagalkan gerbang lewat struk_as_proof.
        fake = {**RECEIPTS[0], "id": "indomaret-palsu", "lines": BY_ID["sint-qris-1"]["lines"]}
        r = evaluate([*SYNTHETIC, fake])
        self.assertEqual((r["struk_as_proof"], r["failures"]), (["indomaret-palsu"], ["indomaret-palsu"]))

    def test_proof_sample_missing_an_expected_field_fails(self):
        s = copy.deepcopy(BY_ID["sint-masuk"])
        del s["expect"]["flow"]
        r = evaluate([s])
        self.assertEqual(r["failures"], ["sint-masuk"])
        self.assertIn("expect.flow", r["rows"][0]["fields"]["flow"]["reason"])

    def test_expected_total_must_be_an_int_or_none(self):
        for bad in ("25.000", "25000", 25000.0, 25000.9, True):
            s = copy.deepcopy(BY_ID["sint-qris-1"])
            s["expect"]["total"] = bad
            with self.subTest(bad=bad):
                r = evaluate([s])
                self.assertEqual(r["failures"], ["sint-qris-1"])
                field = r["rows"][0]["fields"]["total"]
                self.assertFalse(field["ok"])
                self.assertIn("expect.total", field["reason"])
        s = copy.deepcopy(BY_ID["sint-topup"])
        s["expect"]["total"] = None
        self.assertEqual(evaluate([s])["failures"], ["sint-topup"])           # None ≠ 100000, tanpa crash

    def test_invalid_expected_paid_at_fails_without_crashing(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        s["expect"]["paid_at"] = "26 Okt 2026"
        r = evaluate([s])
        self.assertEqual(r["failures"], ["sint-qris-1"])
        self.assertIn("expect.paid_at", r["rows"][0]["fields"]["date"]["reason"])

    def test_user_name_from_sample_drives_own_account_flow(self):
        s = copy.deepcopy(BY_ID["sint-transfer-1"])
        s["user_name"] = "Budi Santoso"
        self.assertEqual(evaluate([s])["failures"], ["sint-transfer-1"])   # arah jadi antar_rekening_sendiri
        s["expect"]["flow"] = "antar_rekening_sendiri"
        self.assertEqual(evaluate([s])["failures"], [])

    def test_sample_context_today(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        self.assertEqual(sample_context(s).today, date(2026, 10, 26))         # dari paid_at yang diharapkan
        s["expect"]["paid_at"] = "2026-10-25T20:00:00+00:00"
        self.assertEqual(sample_context(s).today, date(2026, 10, 26))         # tanggal WIB
        s["today"] = "2026-11-01"
        self.assertEqual(sample_context(s).today, date(2026, 11, 1))
        s.pop("today")
        s["expect"]["paid_at"] = None
        self.assertEqual(sample_context(s).today, datetime.now(WIB).date())
        s["user_name"] = "Rina"
        self.assertEqual(sample_context(s).user_name, "Rina")

    def test_expect_from_document(self):
        doc = DokumenBayar(doc_type="qris", issuer="dana", status="berhasil", flow="keluar",
                           paid_at=datetime(2026, 10, 25, 18, 12, 33, tzinfo=timezone.utc),   # = 26 Okt 01:12:33 WIB
                           counterparty=Counterparty(name=""))
        doc.amounts.total = 25000
        self.assertEqual(expect_from(doc), {"doc_type": "qris", "issuer": "dana", "total": 25000,
                                            "paid_at": "2026-10-26T01:12:33+07:00", "counterparty": None,
                                            "status": "berhasil", "flow": "keluar"})
        self.assertEqual(list(expect_from(doc)), ["doc_type", "issuer", "total", "paid_at", "counterparty", "status", "flow"])


class CorpusFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_rewriting_fixture_is_byte_identical(self):
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(format_corpus(json.loads(text)["samples"]), text)
        path = self.root / "corpus.json"
        write_corpus(path, load_corpus(FIXTURE))
        self.assertEqual(path.read_bytes(), FIXTURE.read_bytes())

    def test_write_keeps_permission_bits(self):
        path = self.root / "corpus.json"
        for mode in (0o644, 0o640):
            path.write_bytes(FIXTURE.read_bytes())
            os.chmod(path, mode)
            write_corpus(path, load_corpus(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
        fresh = self.root / "baru.json"
        write_corpus(fresh, [])
        self.assertEqual(stat.S_IMODE(fresh.stat().st_mode), 0o644)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["baru.json", "corpus.json"])   # tanpa sisa sementara

    def test_load_corpus_rejects_missing_or_broken_files(self):
        broken = {"tidak-ada.json": None, "rusak.json": "{rusak", "bukan-objek.json": "[]", "tanpa-samples.json": "{}",
                  "samples-bukan-daftar.json": '{"samples": {}}', "sampel-tanpa-id.json": '{"samples": [{"real": false}]}'}
        for name, text in broken.items():
            path = self.root / name
            if text is not None:
                path.write_text(text, encoding="utf-8")
            with self.subTest(name), self.assertRaises(CorpusError) as caught:
                load_corpus(path)
            self.assertIn(name, str(caught.exception))

    def test_load_corpus_validates_each_sample(self):
        good = copy.deepcopy(BY_ID["sint-qris-1"])
        cases = {
            "reviewed": ({**good, "real": True, "reviewed": "false"}, "reviewed"),
            "real": ({**good, "real": "false"}, "real"),
            "real hilang": ({k: v for k, v in good.items() if k != "real"}, "real"),
            "today format lain": ({**good, "today": "27-10-2026"}, "today"),
            "today ISO dasar": ({**good, "today": "20261027"}, "today"),
            "today bukan tanggal": ({**good, "today": "2026-02-30"}, "today"),
            "today angka": ({**good, "today": 20261027}, "today"),
            "user_name": ({**good, "user_name": ["Rina"]}, "user_name"),
            "lines teks": ({**good, "lines": "Pembayaran Berhasil"}, "lines"),
            "lines berisi angka": ({**good, "lines": ["QRIS", 25000]}, "lines"),
            "expect": ({**good, "expect": ["qris"]}, "expect"),
            "expect hilang": ({k: v for k, v in good.items() if k != "expect"}, "expect"),
            "id kosong": ({**good, "id": ""}, "id"),
            "id angka": ({**good, "id": 7}, "id"),
        }
        path = self.root / "corpus.json"
        for label, (bad, field) in cases.items():
            path.write_text(json.dumps({"samples": [BY_ID["sint-transfer-1"], bad]}), encoding="utf-8")
            with self.subTest(label), self.assertRaises(CorpusError) as caught:
                load_corpus(path)
            message = str(caught.exception)
            self.assertIn("sampel ke-2", message)
            if isinstance(bad.get("id"), str) and bad["id"]:
                self.assertIn(bad["id"], message)
            self.assertIn(field, message)

    def test_load_corpus_rejects_duplicate_ids(self):
        path = self.root / "corpus.json"
        path.write_text(json.dumps({"samples": [BY_ID["sint-qris-1"], BY_ID["sint-transfer-1"], BY_ID["sint-qris-1"]]}),
                        encoding="utf-8")
        with self.assertRaises(CorpusError) as caught:
            load_corpus(path)
        self.assertIn("sint-qris-1", str(caught.exception))
        self.assertIn("ganda", str(caught.exception))

    def test_load_corpus_accepts_valid_optional_fields(self):
        sample = {**copy.deepcopy(BY_ID["sint-transfer-1"]), "id": "bri-1", "real": True, "reviewed": False,
                  "today": "2026-10-27", "user_name": "Budi Santoso"}
        path = self.root / "corpus.json"
        write_corpus(path, [*SAMPLES, sample])
        self.assertEqual(load_corpus(path)[-1], sample)
        self.assertEqual(load_corpus(FIXTURE), SAMPLES)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "korpus").mkdir()
        (root / "masukan").mkdir()
        self.corpus = root / "korpus" / "corpus.json"
        self.corpus.write_bytes(FIXTURE.read_bytes())
        self.txt = root / "masukan" / "bukti.txt"
        self.txt.write_text(TRANSFER_TXT, encoding="utf-8")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write_txt(self, name, lines):
        path = self.txt.with_name(name)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_add_writes_masked_sample_in_fixture_style(self):
        before = self.corpus.read_text(encoding="utf-8")
        code, out, _ = self.run_main("add", str(self.txt), "--id", "bri-transfer-1", "--real", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        text = self.corpus.read_text(encoding="utf-8")
        sample = json.loads(text)["samples"][-1]
        today = datetime.now(WIB).date().isoformat()
        self.assertEqual(list(sample), ["id", "real", "reviewed", "today", "lines", "expect"])
        self.assertEqual((sample["id"], sample["real"], sample["reviewed"], sample["today"]), ("bri-transfer-1", True, False, today))
        self.assertIn("Rekening Tujuan …4567", sample["lines"])
        self.assertIn("No. Ref …5678", sample["lines"])
        self.assertEqual(sample["expect"], {"doc_type": "transfer", "issuer": None, "total": 150000,
                                            "paid_at": "2026-10-26T09:30:00+07:00", "counterparty": "BUDI SANTOSO",
                                            "status": "berhasil", "flow": "keluar"})
        compact = re.sub(r"[\s-]", "", text[len(before) - len("]}\n"):])   # hanya sampel baru
        self.assertNotIn("012301001234567", compact)
        self.assertNotIn("2026102612345678", compact)
        # Gaya dua baris: sampel lama tidak berubah (hanya koma), sampel baru = baris data + baris expect.
        self.assertTrue(text.startswith(before[: -len("\n]}\n")] + ",\n"))
        lines = text.splitlines()
        self.assertTrue(lines[-3].startswith('  {"id": "bri-transfer-1", "real": true, "reviewed": false, "today": "'))
        self.assertTrue(lines[-3].endswith("],"))
        self.assertTrue(lines[-2].startswith('   "expect": {"doc_type": "transfer", "issuer": null, "total": 150000, '))
        self.assertTrue(lines[-2].endswith("}}"))
        self.assertEqual(lines[-1], "]}")
        self.assertEqual(text, format_corpus(json.loads(text)["samples"]))
        # Ditampilkan untuk diperiksa manusia; berkas asli tidak disalin ke folder korpus.
        self.assertIn("Rekening Tujuan …4567", out)
        self.assertIn('"counterparty": "BUDI SANTOSO"', out)
        self.assertNotIn("PERIKSA", out)
        self.assertIn("user_name", out)
        self.assertIn("nama samaran", out)
        self.assertIn("dua baris", out)                  # nomor yang terpotong ke baris berikutnya
        self.assertIn("huruf", out)                      # referensi campuran huruf dan angka pendek
        self.assertEqual(sorted(p.name for p in self.corpus.parent.iterdir()), ["corpus.json"])

    def test_add_reads_the_masked_lines(self):
        # "Nominal 150000" (tanpa Rp, tidak berkelompok) disamarkan; expect harus mengikuti baris yang disimpan.
        txt = self.write_txt("nominal.txt", ["Transfer Berhasil", "Penerima ANDI", "Nominal 150000", "26/10/2026 10:00"])
        self.assertEqual(self.run_main("add", str(txt), "--id", "sint-nominal", "--corpus", str(self.corpus))[0], 0)
        sample = json.loads(self.corpus.read_text(encoding="utf-8"))["samples"][-1]
        self.assertIn("Nominal …0000", sample["lines"])
        self.assertIsNone(sample["expect"]["total"])
        self.assertEqual(evaluate([sample])["failures"], [])

    def test_add_flags_lines_that_still_hold_six_digits(self):
        txt = self.write_txt("periksa.txt", ["Transfer Berhasil", "Penerima ANDI", "Nominal Rp50.000", "26/10/2026 10:00",
                                             "Kode Bayar 6123/4567/8812", "Ref 1234567890"])
        code, out, _ = self.run_main("add", str(txt), "--id", "sint-periksa", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)   # peringatan tidak memblokir
        self.assertIn("PERIKSA baris 5: Kode Bayar 6123/4567/8812", out)
        self.assertEqual(out.count("PERIKSA"), 1)   # baris 6 sudah disamarkan (Ref …7890)
        self.assertIn("sint-periksa", self.corpus.read_text(encoding="utf-8"))

    def test_add_synthetic_with_user_name(self):
        code, out, _ = self.run_main("add", str(self.txt), "--id", "sint-baru", "--user-name", "Budi Santoso",
                                     "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        sample = json.loads(self.corpus.read_text(encoding="utf-8"))["samples"][-1]
        self.assertEqual(list(sample), ["id", "real", "today", "user_name", "lines", "expect"])
        self.assertEqual((sample["real"], sample["user_name"]), (False, "Budi Santoso"))
        self.assertEqual(sample["expect"]["flow"], "antar_rekening_sendiri")
        self.assertIn("user_name", out)
        self.assertEqual(self.run_main("eval", "--corpus", str(self.corpus))[0], 0)

    def test_add_refuses_duplicate_id(self):
        before = self.corpus.read_bytes()
        code, _, err = self.run_main("add", str(self.txt), "--id", "sint-qris-1", "--corpus", str(self.corpus))
        self.assertEqual(code, 2)
        self.assertIn("sint-qris-1", err)
        self.assertEqual(self.corpus.read_bytes(), before)

    def test_add_reports_extract_error(self):
        pdf = self.txt.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4")
        before = self.corpus.read_bytes()
        with patch.object(kotak_corpus, "extract_text", AsyncMock(side_effect=PdfLocked())) as fake:
            code, _, err = self.run_main("add", str(pdf), "--id", "pdf-1", "--real", "--corpus", str(self.corpus))
        self.assertEqual(code, 2)
        self.assertIn("PDF terkunci kata sandi", err)
        self.assertEqual(fake.await_args.args[1], "application/pdf")
        self.assertEqual(self.corpus.read_bytes(), before)

    def test_add_refuses_missing_corpus_or_folder_before_extracting(self):
        typo = self.corpus.with_name("corpus.jsn")
        nowhere = self.corpus.parent / "tidak-ada" / "corpus.json"
        for path, message in ((typo, "berkas korpus tidak ada"), (nowhere, "folder korpus tidak ada")):
            with self.subTest(str(path)), patch.object(kotak_corpus, "extract_text", AsyncMock()) as fake:
                code, _, err = self.run_main("add", str(self.txt), "--id", "x-1", "--corpus", str(path))
                self.assertEqual(code, 2)
                self.assertIn(message, err)
                fake.assert_not_awaited()
                self.assertFalse(path.exists())
        self.assertFalse(nowhere.parent.exists())

    def test_broken_corpus_is_reported_and_left_untouched(self):
        self.corpus.write_text('{"samples": [{"id": "a",', encoding="utf-8")
        before = self.corpus.read_bytes()
        with patch.object(kotak_corpus, "extract_text", AsyncMock()) as fake:
            code, _, err = self.run_main("add", str(self.txt), "--id", "x-1", "--corpus", str(self.corpus))
        self.assertEqual(code, 2)
        self.assertIn("rusak", err)
        fake.assert_not_awaited()
        self.assertEqual(self.corpus.read_bytes(), before)
        code, _, err = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 2)
        self.assertIn("rusak", err)

    def test_invalid_sample_exits_2_for_add_and_eval(self):
        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][0]["reviewed"] = "false"
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        before = self.corpus.read_bytes()
        for argv in (("add", str(self.txt), "--id", "x-1"), ("eval",), ("eval", "--real-only")):
            with self.subTest(argv), patch.object(kotak_corpus, "extract_text", AsyncMock()) as fake:
                code, _, err = self.run_main(*argv, "--corpus", str(self.corpus))
                self.assertEqual(code, 2)
                self.assertIn("sint-qris-1", err)
                self.assertIn("reviewed", err)
                fake.assert_not_awaited()
        self.assertEqual(self.corpus.read_bytes(), before)

    def test_eval_missing_corpus_exits_2(self):
        code, out, err = self.run_main("eval", "--corpus", str(self.corpus.with_name("corpus.jsn")))
        self.assertEqual(code, 2)
        self.assertIn("berkas korpus tidak ada", err)
        self.assertNotIn("korpus nyata belum ada", out)

    def test_add_keeps_corpus_permission_bits(self):
        os.chmod(self.corpus, 0o644)
        self.assertEqual(self.run_main("add", str(self.txt), "--id", "sint-mode", "--corpus", str(self.corpus))[0], 0)
        self.assertEqual(stat.S_IMODE(self.corpus.stat().st_mode), 0o644)

    def test_eval_exit_codes(self):
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        for s in [*SYNTHETIC, *RECEIPTS]:
            self.assertIn(s["id"], out)
        self.assertIn("10 sampel (6 sintetis, 0 nyata, 4 struk Indomaret)", out)
        self.assertIn("100.0%", out)

        code, out, _ = self.run_main("eval", "--real-only", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("korpus nyata belum ada", out)
        self.assertNotIn("indomaret-s1", out)

        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][1]["expect"]["total"] = 16000
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("sint-qris-2", out)
        self.assertIn("16000", out)

    def test_eval_prints_the_reason_for_a_bad_expectation(self):
        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][0]["expect"]["total"] = "25.000"
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("expect.total", out)

    def test_eval_skips_unreviewed_real_samples(self):
        self.assertEqual(self.run_main("add", str(self.txt), "--id", "bri-transfer-1", "--real",
                                       "--corpus", str(self.corpus))[0], 0)
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        self.assertIn("1 sampel nyata belum ditinjau", out)
        self.assertNotIn("bri-transfer-1", out)
        code, out, _ = self.run_main("eval", "--real-only", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("korpus nyata belum ada", out)

        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][-1]["reviewed"] = True
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        code, out, _ = self.run_main("eval", "--real-only", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        self.assertIn("bri-transfer-1", out)
        self.assertNotIn("sint-qris-1", out)
        self.assertNotIn("indomaret-s1", out)


class ScriptEnvironmentTests(unittest.TestCase):
    def test_runs_without_database_settings_in_the_environment(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET")}
        proc = subprocess.run([sys.executable, "-m", "app.scripts.kotak_corpus", "eval"], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        self.assertIn("Gerbang rilis: lulus", proc.stdout)


if __name__ == "__main__":
    unittest.main()
