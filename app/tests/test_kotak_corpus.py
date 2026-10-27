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

# Huruf mirip angka (OCR "88" -> "BB", "10" -> "lO") memotong nomor menjadi potongan < 6 digit, jadi mask_line hanya
# menyamarkan sebagian (re-review A13 I1-r2): hitungan seluruh baris harus menandainya.
LOOKALIKE_SPLIT = {
    "HP 866 8BB74 127 96": "HP 866 8BB…2796",
    "RRN 6288 BB92 - 4674": "RRN 6288 BB…4674",
    "ID Transaksi 4223 149 - 8BB98 6798": "ID Transaksi …1498BB…6798",
    "Rekening Tujuan 65525-2Ol6  508": "Rekening Tujuan …5252Ol6  508",
}

# Potongan nomor berbentuk jam yang menempel (langsung atau lewat satu pemisah) pada penanda, digit, atau huruf mirip
# angka (re-review A13 m-c): aturan jam membiarkannya, tetapi digitnya harus ikut dihitung.
TIME_FRAGMENT = {
    "RRN 612345675412   S6:25": "RRN …5412   S6:25",
    "No. Rek 61234901389/3B12:56": "No. Rek …1389/3B12:56",
    "No. Rek 61234903/09:45": "No. Rek …4903/09:45",
    "HP 081234560995l1:43": "HP …0995l1:43",
    "No. Rek 61239281-05:39": "No. Rek …9281-05:39",
    "Ref 08:12:612345674567": "Ref 08:12:…4567",
}

# Potongan nomor berbentuk nominal ribuan (OCR membaca satu celah antarkelompok sebagai "." / ","): mask_line
# membiarkannya sebagai nominal (ruling A13 fix round 1), jadi sisa nomornya saja yang tersamar (re-review A13 I1-r4).
# Menempel digit/penanda/huruf mirip angka — langsung, lewat satu pemisah, atau lewat 1-2 spasi — harus dihitung.
GROUPED_FRAGMENT = {
    "No. Rekening 703.123 456 700": "No. Rekening 703.123 …6700",
    "RRN 182.222 8783": "RRN 182.222 8783",
    "Rekening Tujuan 1234 5678 9.012": "Rekening Tujuan …5678 9.012",
    "NPWP 01.234.567.8 - 901.000": "NPWP …5678 - 901.000",
    "Nomor Rekening Jago 1,048 3333 9078": "Nomor Rekening Jago 1,048 …9078",
    "VA 7156  738.628": "VA 7156  738.628",
    "HP 739,850  3397": "HP 739,850  3397",
}

# Jam yang menempel pada kata, tanggal, atau jam lain (bukan potongan nomor) tetap sunyi.
CLEAN_TIME_FORMS = [
    "Tanggal 2026-10-26T09:30:15+07:00", "26/10/2026,08:12:33", "Jam08:12:33", "08:12:33WIB", "Pukul08.12.33",
    "Jam 08.12.33 WIB", "Waktu: 08:12:33", "(08:12:33)", "08:12 - 08:15", "26/10/2026 08:12:33 Ref …8812",
    "26/10/2026 - 08:12:33", "08:12:33,26/10/2026", "08:12:33, 26/10/2026", "Transaction Date 2026-10-26 08:12:33",
]

# Dua penanda tersamar dari satu nomor yang terpotong (ruling A13 fix round 4: setiap cara penyambungan ditandai,
# termasuk satu spasi — "Ref …5678 …1234" menampilkan 8 digit).
TOKEN_PAIRS = {
    "RRN 612345673091 | 612345673755": "RRN …3091 | …3755",            # m-a: tanda baca lain
    "Ref 612345673091 ; 612345673755": "Ref …3091 ; …3755",
    "Ref 612345673091 , 612345673755": "Ref …3091 , …3755",
    "Ref 612345673091 . 612345673755": "Ref …3091 . …3755",
    "Ref 612345673091  -  612345673755": "Ref …3091  -  …3755",
    "Ref 612345673091  /  612345673755": "Ref …3091  /  …3755",        # m-b: dua spasi mengapit "/"
    "Ref 612345673091/612345673755": "Ref …3091/…3755",
    "Ref 612345673091   612345673755": "Ref …3091   …3755",
    "Ref 612345673091 / 612345673755": "Ref …3091 / …3755",
    "Ref 612345673091 : 612345673755": "Ref …3091 : …3755",
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

    def test_day_month_name_year_is_a_kept_date(self):
        # "26 Okt 2026" (bentuk yang dibaca pembaca, labels._DMY_NAME, dengan pemisah yang sama: spasi, ".", "-", "/",
        # atau menempel) adalah rentang yang dibiarkan: hitungan PERIKSA tidak menghitung 6 digitnya, dan deret di
        # sampingnya tidak menyeret harinya ("1234 26 Okt 2026").
        self.assertKept(["26 Okt 2026, 09:30 WIB", "26 Oktober 2026", "26 Okt. 2026", "Ref 1234 26 Okt 2026 08:12",
                         "26 Okt 2026 12345", "26-Okt-2026 08:12", "26/Okt/2026", "26.Okt.2026", "26Okt2026 08:12",
                         "Ref 1234 26-Okt-2026"])
        self.assertMasked({
            "26 Okt 2026 123456": "26 Okt 2026 …3456",      # tanggal utuh, deret di sampingnya disamarkan sendiri
            "Ref 123456-26 Okt 2026": "Ref …5626 Okt 2026",   # tanggal yang menempel strip pada deret lain bukan tanggal
            "Ref 123456-26-Okt-2026": "Ref …5626-Okt-2026",
            "26 Okt 2026-123456": "26 Okt …3456",
            "26-Okt-2026-123456": "26-Okt-…3456",
            "Kode 12 1999 5678": "Kode …5678",               # tanpa nama bulan bukan tanggal
            "12 Xyz 2026 5678": "12 Xyz …5678",
            "32 Okt 2026 5678": "32 Okt …5678",              # hari 32 bukan tanggal
            "26 Okt 1234 5678": "26 Okt …5678",              # tahun 1234 bukan tanggal
        })
        for line in ["26 Okt 2026, 09:30 WIB", "Tanggal 26 Oktober 2026 08:12:33 WIB", "26 Okt 2026 • 08:12",
                     "26 Oct 2026, 08:12 AM", "Ref 1234 26 Okt 2026 08:12", "26-Okt-2026 08:12", "26/Okt/2026 08:12",
                     "Tanggal 26Okt2026 08:12:33"]:
            with self.subTest(line):
                self.assertFalse(needs_review(line))
        self.assertTrue(needs_review("Kode 12 Xyz 2026 5"))      # bukan tanggal: 2 + 4 + 1 = 7 digit lepas
        self.assertTrue(needs_review("Kode 32 Okt 2026"))        # hari 32 bukan tanggal: 2 + 4 digit lepas

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

    def test_whole_line_count_digits_and_tokens(self):
        # Hitungan seluruh baris (ruling A13 fix round 4): digit 1, penanda `…dddd` 4; ambang >= 6, apa pun yang
        # ada di antaranya (kata, spasi, tanda baca).
        self.assertTrue(needs_review("Ref …4567 12"))         # 4 + 2
        self.assertFalse(needs_review("Ref …4567 1"))         # 5: di bawah ambang
        self.assertTrue(needs_review("Ref 123 a.n. BUDI 456"))   # kata tidak memisahkan: 3 + 3
        self.assertFalse(needs_review("Ref 123 a.n. BUDI 45"))
        self.assertTrue(needs_review("Ref …4567,…1234"))
        self.assertTrue(needs_review("Ref …4567/…1234"))
        self.assertEqual(mask_line("Rek 678812 B47276394242"), "Rek …8812 B…4242")   # dua deret dipisah huruf OCR
        self.assertTrue(needs_review("Rek …8812 B…4242"))
        self.assertTrue(needs_review("Ref …123 …4567"))      # "…123" = 3 digit lepas + penanda 4
        self.assertFalse(needs_review("Ref (…4567)"))          # satu penanda: 4
        self.assertFalse(needs_review("…4567"))
        self.assertTrue(needs_review("Biaya 0,00 …4567"))     # "0,00" tanpa Rp bukan nominal: 3 + 4
        self.assertFalse(needs_review("Biaya Rp 0,00 …4567"))  # nominal dibiarkan: 0 + 4
        self.assertFalse(needs_review("Ref 12345"))
        self.assertTrue(needs_review("Ref 12345 6"))          # tepat 6 digit lepas
        self.assertTrue(needs_review("Terminal ID A01 Ref 12345"))   # 2 + 5: kata di antaranya tidak memisahkan

    def test_every_pair_of_masked_tokens_is_flagged(self):
        # Dua penanda dari satu nomor yang terpotong menampilkan 8 digit, apa pun penyambungnya (m-a, m-b) — juga
        # satu spasi, yang dulu sunyi ("Ref …5678 …1234" kini ditandai, ruling fix round 4).
        for line in ["Ref …5678 …1234", "…4567 …1234", "Ref …5678  …1234", "Ref …5678\t…1234", "Rek …4567 a.n. …1234",
                     "Ref …4567 08:12 …8812", "Ref …4567 26/10/2026 …8812", "No. Ref …3091 / …3755", "Ref …4567   …8812",
                     "Ref …4567:…8812", "Ref …4567_…8812", "Ref …4567 : …8812", "Ref …4567 _ …8812", "Ref …4567/ …8812",
                     "Ref …4567\t\t\t…8812", "Ref …4567 / …8812", "Ref …4567    …8812", "…1111 / …2222 / …3333",
                     "…6642 | …5446", "…1940 ; …5690", "…1524 , …5280", "…0036 . …3316", "…0311  -  …8625",
                     *TOKEN_PAIRS.values()]:
            with self.subTest(line):
                self.assertTrue(needs_review(line))
        for raw, masked in TOKEN_PAIRS.items():
            with self.subTest(raw):
                self.assertEqual(mask_line(raw), masked)   # bentuk tersimpan persis seperti yang dipin di atas

    def test_lookalike_letters_count_when_touching_digits(self):
        for raw, masked in LOOKALIKE_SPLIT.items():
            with self.subTest(raw):
                self.assertEqual(mask_line(raw), masked)
                self.assertTrue(needs_review(masked))
        # Huruf mirip angka [OoDlIiSsBZGgq] dihitung 1 hanya dalam deret 1-3 huruf yang menempel digit atau penanda.
        self.assertTrue(needs_review("Ref 12BB3 45"))          # 5 digit + BB = 7
        self.assertTrue(needs_review("Ref lO…4567"))          # lO menempel penanda: 2 + 4
        self.assertTrue(needs_review("Ref …4567S1"))          # S di antara penanda dan digit: 4 + 1 + 1
        self.assertFalse(needs_review("Ref 12345 S"))         # tidak menempel (spasi): 5
        self.assertFalse(needs_review("Ref 1234 SO 5"))       # SO tidak menempel digit: 5
        self.assertFalse(needs_review("Ref 123 SOSIS 45"))    # deret 5 huruf: bukan salah baca, 5 digit
        self.assertFalse(needs_review("Ref 1234 BOSS5"))      # deret 4 huruf (> 3) tidak dihitung: 5
        self.assertFalse(needs_review("Ref 12345R"))          # "R" bukan huruf mirip angka: 5
        self.assertFalse(needs_review("Ref 12345ok"))         # "o" diikuti huruf lain: bagian kata, bukan salah baca
        self.assertFalse(needs_review("Ref 1234A5"))          # "A" bukan huruf mirip angka: 5
        self.assertTrue(needs_review("Ref 1234o5"))           # huruf kecil juga
        self.assertTrue(needs_review("Ref 1234Z5"))
        self.assertTrue(needs_review("Ref 1234GD"))           # 4 + G + D
        self.assertTrue(needs_review("Ref 1234qI"))
        self.assertTrue(needs_review("Ref 1234gi"))
        self.assertTrue(needs_review("Ref 1234sD"))
        self.assertTrue(needs_review("Ref 12345i"))
        self.assertTrue(needs_review("Ref 12345l"))
        self.assertTrue(needs_review("Ref 12345O"))
        self.assertTrue(needs_review("Ref 12345B"))
        self.assertTrue(needs_review("Ref 1234 5S"))          # 5 + S yang menempel "5" = 6
        self.assertTrue(needs_review("Transaction ID…5678"))    # "ID" = dua huruf mirip angka yang menempel penanda: 4 + 2
        self.assertFalse(needs_review("Transaction ID …5678"))  # tidak menempel: 4
        self.assertFalse(needs_review("TID…5678"))              # "ID" di dalam kata (didahului huruf T): 4

    def test_time_fragment_glued_to_a_number_counts(self):
        for raw, masked in TIME_FRAGMENT.items():
            with self.subTest(raw):
                self.assertEqual(mask_line(raw), masked)
                self.assertTrue(needs_review(masked))
        # Setiap pemisah penyambung (/ - _ : . , –) dan menempel langsung; di kedua sisi jam.
        for sep in ("/", "-", "_", ":", ".", ",", "–", ""):
            with self.subTest(sep=sep):
                self.assertTrue(needs_review(f"Ref …4567{sep}08:12"))
                self.assertTrue(needs_review(f"Ref 08:12{sep}…4567"))
                self.assertTrue(needs_review(f"Ref 08:12{sep}lO1"))            # 4 + 1 + lO yang menempel "1" (2)
                self.assertTrue(needs_review(f"Ref 1lO{sep}08:12"))
                if sep not in (":", "."):                                      # "12:08:12" / "12.08:12" = satu jam
                    self.assertTrue(needs_review(f"Ref 12{sep}08:12"))          # 2 + 4
        self.assertTrue(needs_review("Ref 08:12lO"))          # jam menempel langsung huruf mirip angka: 4 + 2
        self.assertFalse(needs_review("Ref 08:12/lO"))        # jam dihitung (4), tetapi "lO" sendiri tidak menempel digit
        self.assertFalse(needs_review("Ref …4567 08:12"))     # spasi memutus: jam dibiarkan, 4
        self.assertFalse(needs_review("Ref …4567//08:12"))    # tepat satu pemisah yang menyambung; dua tidak
        self.assertFalse(needs_review("Ref …4567 /08:12"))
        self.assertFalse(needs_review("Ref …4567|08:12"))     # hanya / - _ : . , – yang menyambung (ruling), bukan "|"
        self.assertFalse(needs_review("Ref 08:12(…4567)"))
        self.assertFalse(needs_review("Ref 08:12 S"))
        self.assertFalse(needs_review("Ref 1 08:12"))
        self.assertFalse(needs_review("Ref …4567 03:43 1"))   # jam dibiarkan: 4 + 1 (bentuk yang diserahkan ke manusia)
        # Hanya rentang berbentuk jam yang kehilangan perlindungannya: nominal, tanggal angka, dan NMID yang menempel
        # penanda tetap dikosongkan (penyamaran sudah menjaga tanggal/nominal yang menempel digit lain).
        self.assertFalse(needs_review("Ref …4567/Rp25.000"))
        self.assertFalse(needs_review("Ref …4567,26/10/2026"))
        self.assertFalse(needs_review("26/10/2026-…4567"))
        self.assertFalse(needs_review("NMID …4567/ID1024358806544"))
        # Tetangga yang bagian dari rentang lain yang dibiarkan bukan penyambung — juga bila hurufnya mirip angka
        # ("ID" di dalam NMID).
        self.assertFalse(needs_review("NMID 08:12:33/ID1024358806544"))
        for line in CLEAN_TIME_FORMS:
            with self.subTest(line):
                self.assertEqual(mask_line(line), line)      # premis: bentuk bersih tidak berubah
                self.assertFalse(needs_review(line))
        # Jam yang menempel kata >= 2 huruf atau rentang lain yang dibiarkan (tanggal, jam) tidak dihitung — juga
        # bila hurufnya kebetulan mirip angka tetapi bagian dari kata yang lebih panjang.
        self.assertFalse(needs_review("08:12:33SOSIS"))
        self.assertFalse(needs_review("SOSIS08:12:33"))
        self.assertFalse(needs_review("08:12:33,26/10/2026"))
        self.assertFalse(needs_review("08:12:33-Rp25.000"))
        # Tanggal yang menempel strip pada digit lain bukan rentang yang dibiarkan (aturan mask_line yang ada), jadi
        # 8 digitnya dihitung seluruhnya.
        self.assertTrue(needs_review("08:12:33-26/10/2026"))
        # "12.10.26" dibiarkan sebagai tanggal d.m.yy, tetapi berbentuk jam juga: menempel penanda -> dihitung (arah
        # aman untuk bentuk yang rancu).
        self.assertTrue(needs_review("Ref …4567/12.10.26"))
        self.assertFalse(needs_review("Ref …4567 12.10.26"))
        # "24.12.34" bukan jam (jam 24), hanya tanggal d.m.yy: tetap dibiarkan walau menempel penanda (ruling: hanya
        # rentang berbentuk jam yang kehilangan perlindungannya).
        self.assertFalse(needs_review("Ref …4567 24.12.34"))
        self.assertFalse(needs_review("Ref …4567,24.12.34"))
        self.assertTrue(needs_review("08:12:33SO"))           # 2 huruf mirip angka lepas: dihitung

    def test_every_dash_kind_glues_a_time(self):
        # m-e: semua strip yang dianggap pemisah deret oleh mask_line (_DASH: "-", U+2010..U+2015, U+2212) juga
        # menempelkan jam ke potongan nomor; bukan hanya "-" dan "–".
        for dash in ("-", "‐", "‑", "‒", "–", "—", "―", "−"):
            with self.subTest(dash=hex(ord(dash))):
                self.assertEqual(mask_line(f"No. Rek 61239281{dash}05:39"), f"No. Rek …9281{dash}05:39")
                self.assertTrue(needs_review(f"No. Rek …9281{dash}05:39"))
                self.assertTrue(needs_review(f"Ref 08:12{dash}…4567"))
                self.assertTrue(needs_review(f"Rek 1.234{dash}…5678"))     # pemisah yang sama untuk nominal tanpa Rp
                self.assertFalse(needs_review(f"08:12:33{dash}Rp25.000"))   # tetangga di rentang lain tetap sunyi
        self.assertFalse(needs_review("Ref …9281~05:39"))      # "~" bukan strip
        self.assertFalse(needs_review("Ref …9281⁃05:39"))      # U+2043 (tanda hubung bulatan) bukan bagian _DASH

    def test_grouped_fragment_next_to_a_number_counts(self):
        # I1-r4 (ruling): nominal ribuan tanpa Rp/IDR yang menempel digit, penanda, atau huruf mirip angka — langsung,
        # lewat satu pemisah, atau lewat 1-2 spasi — adalah potongan nomor, dan digitnya dihitung.
        for raw, masked in GROUPED_FRAGMENT.items():
            with self.subTest(raw):
                self.assertEqual(mask_line(raw), masked)
                self.assertTrue(needs_review(raw))         # bentuk mentah juga ditandai
                self.assertTrue(needs_review(masked))
        self.assertTrue(needs_review("RRN 182.222 B783"))       # lewat spasi ke huruf mirip angka: 6 + 1 + 3
        self.assertTrue(needs_review("Rek 1.234/…5678"))        # satu pemisah
        self.assertTrue(needs_review("Rek 1.234-…5678"))
        self.assertTrue(needs_review("Rek …5678-1.234"))        # "8-1.234" bukan nominal sama sekali (aturan mask_line)
        self.assertTrue(needs_review("Rek …5678  1.234"))       # dua spasi (celah antarkotak OCR)
        self.assertTrue(needs_review("Rek 1.234 …5678"))    # NBSP
        self.assertTrue(needs_review("Rek …5678 - 1.234"))      # spasi di sekitar pemisah (bentuk NPWP), juga dua
        self.assertTrue(needs_review("Rek …5678  /  1.234"))
        self.assertTrue(needs_review("Rp 25.000 ke 703.123 …6700"))   # nominal Rp di tempat lain tidak melindunginya
        self.assertTrue(needs_review("Rek 12 1.234"))           # 2 + 4 = 6
        self.assertFalse(needs_review("Rek 1 1.234"))           # 5
        self.assertFalse(needs_review("RRN 182.222   8783"))    # tiga spasi memutus (seperti deret di mask_line)
        self.assertFalse(needs_review("Rek …5678   - 1.234"))
        self.assertFalse(needs_review("Rek …5678 -   1.234"))
        self.assertFalse(needs_review("Rek …5678 // 1.234"))    # dua pemisah
        self.assertFalse(needs_review("Rek …5678\n1.234"))      # ganti baris bukan spasi (seperti deret di mask_line)
        self.assertFalse(needs_review("Ref …4567 / 08:12"))     # jam tidak mendapat kelonggaran spasi (aturan jam tetap)
        # Nominal langsung sesudah Rp/IDR tetap dikosongkan, juga bila menempel penanda; nominal tanpa Rp yang
        # dipisah kata, berdiri sendiri, atau bersebelahan dengan nominal lain (dua rentang yang dikosongkan tidak
        # saling menempelkan) tetap sunyi.
        for line in ["Total Rp153.500", "Biaya Admin Rp2.500", "Nominal 150.000", "Rp 1.500.000 Biaya 2.500",
                     "Qty 2 x 15.000", "Ref …4567 / Rp 25.000", "Ref …4567 Rp 25.000", "Rp 25.000 …4567",
                     "Rp 25.000 x 3 = Rp 75.000", "Rp 25.000 x 3 = 75.000", "Jumlah 25.000 Biaya 2.500",
                     "Saldo 12.345.678.901", "Nominal  150.000  Biaya  2.500", "Harga 18.000 x 2",
                     "Subtotal 153.500 PPN 16.885", "Total Rp 150.000 2.500", "2 x Roti 24.000 48.000",
                     "150.000 + 2.500 = 152.500", "Qty 2 @ 18.000 = 36.000", "1 x Kopi 18.000"]:
            with self.subTest(line):
                self.assertFalse(needs_review(line))
        # "Qty 2 x 15.000": "x" bukan pemisah penyambung atau huruf mirip angka, jadi 15.000 tetap dikosongkan (1 →
        # sunyi). Jumlah + harga yang langsung bersebelahan memang terhitung (ruling: satu lirikan).
        self.assertTrue(needs_review("Qty 2 15.000"))           # 1 + 5 = 6
        self.assertTrue(needs_review("Kopi 2 18.000"))

    def test_kept_forms_masked_numbers_and_short_codes_not_flagged(self):
        lines = [
            "Rekening: …7890 a.n. BUDI", "No. Rek: …7890", "+…7890", "Kode 24.12.34", "Rekening Tujuan …4567",
            "No. Referensi …8812", "Transaction ID …5678", "Tanggal 26 Okt 2026 08:12:33 WIB", "Kasir 01 14-10-2026 08:15",
            "NMID ID1024358806544", "Nominal Rp1.500.000", "Total Rp153.500", "Biaya Admin Rp2.500", "Kode 1_2345",
            "Terminal ID A01", "Rp 25.000 x 3 = Rp 75.000", "26/10/2026 19:05", "Ref …4567 / Rp 25.000",
            "26 Okt 2026, 09:30 WIB", "26 Okt 2026 10:00", "Oct 26 2026 09:30", "Tanggal 2026-10-26 10:15",
            "Rp 0", "Rp 0,00", "BI-FAST", "Kode Bayar …7890 (BRIVA)", "NMID ID1024358806544 TID…7890",
            "Jumlah: Rp:150000", "Saldo 12.345.678.901", "26/10/2026 - 08:12", "Kartu ****1234", "No. Rek xxxx1234",
            *CLEAN_TIME_FORMS,
        ]
        for line in lines:
            with self.subTest(line):
                self.assertFalse(needs_review(line))

    def test_synthetic_samples_flag_only_the_alphanumeric_reference(self):
        # Ruling fix round 4: referensi huruf-angka pendek ditandai ("ID Transaksi A1B2C3D4" = 4 digit + B + D);
        # semua baris sintetis lain sunyi.
        flagged = [(s["id"], mask_line(x)) for s in SYNTHETIC for x in s["lines"] if needs_review(mask_line(x))]
        self.assertEqual(flagged, [("sint-topup", "ID Transaksi A1B2C3D4")])


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
            "id dicadangkan": ({**good, "id": "indomaret-s1"}, "indomaret-"),   # bentrok dengan struk Indomaret (m-d)
            "id dicadangkan baru": ({**good, "id": "indomaret-qris-9"}, "indomaret-"),
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
                                             "Kode Bayar 6123/4567/8812", "Ref 1234567890", "RRN 612345673091   612345673755",
                                             "26 Okt 2026, 09:30 WIB", "HP 866 8BB74 127 96", "No. Rek 61234903/09:45",
                                             "Ref 612345675678 612345671234"])
        code, out, _ = self.run_main("add", str(txt), "--id", "sint-periksa", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)   # peringatan tidak memblokir
        self.assertIn("PERIKSA baris 5: Kode Bayar 6123/4567/8812", out)
        self.assertIn("PERIKSA baris 7: RRN …3091   …3755", out)
        self.assertIn("PERIKSA baris 9: HP 866 8BB…2796", out)
        self.assertIn("PERIKSA baris 10: No. Rek …4903/09:45", out)
        self.assertEqual(out.count("PERIKSA"), 4)   # baris 6 (Ref …7890), 8 (tanggal) dan 11 (satu deret: …1234) sunyi
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

    def test_add_refuses_reserved_indomaret_id(self):
        # Id berawalan "indomaret-" milik struk Indomaret (receipt_samples); evaluasi bawaan akan menampilkannya
        # dua kali (m-d). Ditolak sebelum ekstraksi, berkas tidak disentuh.
        before = self.corpus.read_bytes()
        for bad in ("indomaret-s1", "indomaret-s9", "indomaret-"):
            with self.subTest(bad), patch.object(kotak_corpus, "extract_text", AsyncMock()) as fake:
                code, _, err = self.run_main("add", str(self.txt), "--id", bad, "--corpus", str(self.corpus))
                self.assertEqual(code, 2)
                self.assertIn("indomaret-", err)
                fake.assert_not_awaited()
        self.assertEqual(self.corpus.read_bytes(), before)
        # Awalan lain yang mirip tetap boleh.
        self.assertEqual(self.run_main("add", str(self.txt), "--id", "indomaret", "--corpus", str(self.corpus))[0], 0)
        self.assertEqual(self.run_main("add", str(self.txt), "--id", "alfamart-s1", "--corpus", str(self.corpus))[0], 0)

    def test_reserved_indomaret_id_in_corpus_exits_2(self):
        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][0]["id"] = "indomaret-s1"
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        before = self.corpus.read_bytes()
        with self.assertRaises(CorpusError) as caught:
            load_corpus(self.corpus)
        self.assertIn("indomaret-", str(caught.exception))
        for argv in (("add", str(self.txt), "--id", "x-1"), ("eval",), ("eval", "--real-only")):
            with self.subTest(argv), patch.object(kotak_corpus, "extract_text", AsyncMock()) as fake:
                code, out, err = self.run_main(*argv, "--corpus", str(self.corpus))
                self.assertEqual(code, 2)
                self.assertIn("indomaret-", err)
                self.assertNotIn("Gerbang", out)
                fake.assert_not_awaited()
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
