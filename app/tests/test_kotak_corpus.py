import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import contextlib, copy, io, json, re, tempfile, unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.scripts import kotak_corpus
from app.scripts.kotak_corpus import GATE, evaluate, format_corpus, gate_failures, main, mask_line, sample_context
from app.services.kotak_struk.extract import PdfLocked
from app.services.kotak_struk.readers.labels import WIB

FIXTURE = Path(__file__).parent / "fixtures" / "kotak" / "corpus.json"
SAMPLES = json.loads(FIXTURE.read_text())["samples"]
SYNTHETIC = [s for s in SAMPLES if not s["real"]]
BY_ID = {s["id"]: s for s in SAMPLES}

TRANSFER_TXT = "\n".join([
    "Transfer Berhasil", "26 Okt 2026, 09:30 WIB", "Penerima", "BUDI SANTOSO", "Bank Tujuan BRI",
    "Rekening Tujuan 0123 0100 1234 567", "Nominal Rp150.000", "No. Ref 2026102612345678", "",
])


def _leftover_digit_runs(line: str) -> list[str]:
    """Deret >= 6 digit berurutan yang bukan NMID (`ID` + >= 10 digit) atau nominal langsung sesudah Rp/IDR.
    Tanggal dan nominal berkelompok (1.500.000) tidak pernah memuat 6 digit berurutan, jadi tidak perlu dikecualikan.
    Sengaja ditulis terpisah dari implementasi mask_line."""
    out = []
    for m in re.finditer(r"\d{6,}", line):
        before = line[:m.start()]
        if before.endswith("ID") and len(m.group()) >= 10:
            continue
        if re.search(r"(?:Rp|IDR)[\s.:]*$", before, re.IGNORECASE):
            continue
        out.append(m.group())
    return out


class CorpusTests(unittest.TestCase):
    def test_mask_line(self):
        self.assertEqual(mask_line("Rekening Tujuan 0123 0100 1234 567"), "Rekening Tujuan …4567")
        self.assertEqual(mask_line("No. Referensi 612345678812"), "No. Referensi …8812")
        self.assertEqual(mask_line("Nominal Rp1.500.000"), "Nominal Rp1.500.000")
        self.assertEqual(mask_line("NMID ID1024358806544"), "NMID ID1024358806544")

    def test_synthetic_corpus_passes_gate(self):
        r = evaluate([s for s in SAMPLES if not s["real"]])
        self.assertEqual(r["failures"], [])
        self.assertEqual(gate_failures(r), [])

    def test_real_corpus_meets_release_gate(self):
        real = [s for s in SAMPLES if s["real"] and s.get("reviewed")]
        if not real:
            self.skipTest("korpus nyata belum ada (FS.5, Task A14)")
        r = evaluate(real)
        self.assertEqual(gate_failures(r), [], f"gerbang {GATE} — gagal: {r['failures']}")


class MaskLineTests(unittest.TestCase):
    def test_account_number_masked_even_on_a_line_with_rp(self):
        self.assertEqual(mask_line("Rp50.000 ke 1234567890"), "Rp50.000 ke …7890")

    def test_dates_times_and_nominals_kept(self):
        for line in ["Tanggal 2026-10-26 10:15", "26-10-2026 08:12", "Total IDR 1500000", "Nominal 150,000.00",
                     "26/10/2026 19:05", "26.10.2026 08.12.33", "Tanggal 26 Okt 2026 08:12:33 WIB",
                     "Oct 26 2026 09:30", "Rp 1500000", "Rp. 1.500.000,00", "Jumlah: Rp:150000", "26/10/26"]:
            with self.subTest(line):
                self.assertEqual(mask_line(line), line)

    def test_dashed_and_spaced_runs_masked(self):
        self.assertEqual(mask_line("No. Rek 1234-5678-90"), "No. Rek …7890")
        self.assertEqual(mask_line("ID Transaksi 123 456 789"), "ID Transaksi …6789")
        self.assertEqual(mask_line("Rekening 0123-01-001234-56-7"), "Rekening …4567")
        self.assertEqual(mask_line("HP 0812-3456-7890"), "HP …7890")

    def test_date_like_parts_of_a_longer_number_are_masked(self):
        # Potongan yang mirip tanggal di dalam nomor panjang tidak melindungi nomor itu.
        self.assertEqual(mask_line("Rek 1234-12-10-26"), "Rek …1026")
        self.assertEqual(mask_line("Rek 26-10-2026-1234"), "Rek …1234")
        self.assertEqual(mask_line("Rek 12-10-1234"), "Rek …1234")   # bukan tanggal: tahun 1234

    def test_short_numbers_and_already_masked_text_kept(self):
        for line in ["Rekening Tujuan …4567", "Kartu ****1234", "No. Rek xxxx1234", "Terminal ID A01",
                     "ID Transaksi A1B2C3D4", "Kode 12345", "NMID ID10…6544"]:
            with self.subTest(line):
                self.assertEqual(mask_line(line), line)

    def test_mask_line_is_idempotent(self):
        for line in ["Rekening Tujuan 0123 0100 1234 567", "Rp50.000 ke 1234567890", "Ref 123456 12:30",
                     "No. Rek 1234-5678-90"]:
            with self.subTest(line):
                once = mask_line(line)
                self.assertEqual(mask_line(once), once)

    def test_no_secret_digit_run_left_in_masked_synthetic_lines(self):
        for s in SYNTHETIC:
            for line in s["lines"]:
                masked = mask_line(line)
                with self.subTest(sample=s["id"], line=line):
                    self.assertEqual(_leftover_digit_runs(masked), [])
                    for secret in ("012301001234567", "612345678812", "000151856123", "2026102612345678"):
                        self.assertNotIn(secret, re.sub(r"[\s-]", "", masked))

    def test_masked_synthetic_samples_still_read_the_same(self):
        # Penyamaran tidak merusak yang dibaca pembaca (nominal, tanggal, nama, status, arah).
        masked = [{**s, "lines": [mask_line(x) for x in s["lines"]]} for s in SYNTHETIC]
        self.assertEqual(evaluate(masked)["failures"], [])


class EvaluateTests(unittest.TestCase):
    def test_result_shape_and_perfect_synthetic_scores(self):
        r = evaluate(SYNTHETIC)
        self.assertEqual(r["n"], 6)
        for key in ("amount_date_status_pct", "counterparty_pct", "doc_type_pct", "flow_pct"):
            self.assertEqual(r[key], 100.0, key)
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
        topup["expect"]["counterparty"] = "GOPAY"
        self.assertEqual(evaluate([topup])["counterparty_pct"], 0.0)
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

    def test_flow_mismatch_is_a_failure_but_not_gated(self):
        s = copy.deepcopy(BY_ID["sint-masuk"])
        s["expect"]["flow"] = "keluar"
        r = evaluate([s])
        self.assertEqual((r["failures"], r["flow_pct"]), (["sint-masuk"], 0.0))
        self.assertEqual(gate_failures(r), [])

    def test_store_receipt_read_as_proof_fails_gate(self):
        s = copy.deepcopy(BY_ID["sint-qris-1"])
        s["id"] = "struk-terbaca-qris"
        s["expect"] = {**s["expect"], "doc_type": "struk_belanja"}
        r = evaluate([BY_ID["sint-transfer-1"], s])
        self.assertEqual(r["struk_as_proof"], ["struk-terbaca-qris"])
        self.assertEqual(r["doc_type_pct"], 50.0)
        self.assertIn("struk belanja terbaca sebagai bukti bayar: struk-terbaca-qris", gate_failures(r))

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


class CorpusFileTests(unittest.TestCase):
    def test_rewriting_fixture_is_byte_identical(self):
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(format_corpus(json.loads(text)["samples"]), text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            kotak_corpus.write_corpus(path, kotak_corpus.load_corpus(FIXTURE))
            self.assertEqual(path.read_bytes(), FIXTURE.read_bytes())


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
        self.assertEqual(sample["expect"], {"doc_type": "transfer", "total": 150000, "paid_at": "2026-10-26T09:30:00+07:00",
                                            "counterparty": "BUDI SANTOSO", "status": "berhasil", "flow": "keluar"})
        compact = re.sub(r"[\s-]", "", text[len(before) - len("]}\n"):])   # hanya sampel baru
        self.assertNotIn("012301001234567", compact)
        self.assertNotIn("2026102612345678", compact)
        # Gaya dua baris: sampel lama tidak berubah (hanya koma), sampel baru = baris data + baris expect.
        self.assertTrue(text.startswith(before[: -len("\n]}\n")] + ",\n"))
        lines = text.splitlines()
        self.assertTrue(lines[-3].startswith('  {"id": "bri-transfer-1", "real": true, "reviewed": false, "today": "'))
        self.assertTrue(lines[-3].endswith("],"))
        self.assertTrue(lines[-2].startswith('   "expect": {"doc_type": "transfer", "total": 150000, '))
        self.assertTrue(lines[-2].endswith("}}"))
        self.assertEqual(lines[-1], "]}")
        self.assertEqual(text, format_corpus(json.loads(text)["samples"]))
        # Ditampilkan untuk diperiksa manusia; berkas asli tidak disalin ke folder korpus.
        self.assertIn("Rekening Tujuan …4567", out)
        self.assertIn('"counterparty": "BUDI SANTOSO"', out)
        self.assertEqual(sorted(p.name for p in self.corpus.parent.iterdir()), ["corpus.json"])

    def test_add_synthetic_with_user_name(self):
        code, _, _ = self.run_main("add", str(self.txt), "--id", "sint-baru", "--user-name", "Budi Santoso",
                                   "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        sample = json.loads(self.corpus.read_text(encoding="utf-8"))["samples"][-1]
        self.assertEqual(list(sample), ["id", "real", "today", "user_name", "lines", "expect"])
        self.assertEqual((sample["real"], sample["user_name"]), (False, "Budi Santoso"))
        self.assertEqual(sample["expect"]["flow"], "antar_rekening_sendiri")
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

    def test_eval_exit_codes(self):
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 0)
        for s in SYNTHETIC:
            self.assertIn(s["id"], out)
        self.assertIn("100.0%", out)

        code, out, _ = self.run_main("eval", "--real-only", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("korpus nyata belum ada", out)

        data = json.loads(self.corpus.read_text(encoding="utf-8"))
        data["samples"][1]["expect"]["total"] = 16000
        self.corpus.write_text(json.dumps(data), encoding="utf-8")
        code, out, _ = self.run_main("eval", "--corpus", str(self.corpus))
        self.assertEqual(code, 1)
        self.assertIn("sint-qris-2", out)
        self.assertIn("16000", out)

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


if __name__ == "__main__":
    unittest.main()
