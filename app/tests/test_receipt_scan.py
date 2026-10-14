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

    def test_learned_merchant_alias(self):
        p = self.parse("1NDOMAREI\nTOTAL 9.000", merchant_aliases={"1NDOMAREI": "Indomaret"})
        self.assertEqual(p.merchant, "Indomaret")


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
        with self.assertRaises(receipt_scan.ScanQuotaExceeded):
            await receipt_scan.scan_receipt(_user(), b"img", "image/jpeg", db, ocr=AsyncMock(), llm=AsyncMock())

    async def test_pro_unlimited_and_result_shape(self):
        lines = FIXTURES["receipts"][1]["lines"]
        db = db_with(FakeResult(500), FakeResult(rows=[]), FakeResult(rows=[]))
        db.refresh = AsyncMock()
        llm = AsyncMock()
        out = await receipt_scan.scan_receipt(
            _user("pro"), b"img", "image/jpeg", db,
            ocr=AsyncMock(return_value=OcrResult(lines=lines, score=0.9, seconds=1.0)), llm=llm,
        )
        self.assertEqual(out["total"], 51000)
        self.assertEqual(out["engine"], "rapidocr")
        self.assertIsNone(out["quota"]["limit"])
        llm.assert_not_awaited()  # keyakinan tinggi → LLM tidak dipanggil
        saved = db.add.call_args[0][0]
        self.assertEqual(saved.parsed_total, Decimal(51000))

    async def test_low_confidence_uses_llm_fallback(self):
        db = db_with(FakeResult(0), FakeResult(rows=[]), FakeResult(rows=[]))
        db.refresh = AsyncMock()
        llm = AsyncMock(return_value={"merchant": "Toko A", "date": None, "total": 12000})
        out = await receipt_scan.scan_receipt(
            _user(), b"img", "image/jpeg", db,
            ocr=AsyncMock(return_value=OcrResult(lines=["buram"], score=0.2, seconds=1.0)), llm=llm,
        )
        self.assertEqual((out["engine"], out["total"], out["merchant"]), ("llm", 12000, "Toko A"))
        self.assertEqual(out["quota"], {"limit": 15, "used": 1, "remaining": 14})

    async def test_feedback_correction_learns_label_and_clears_text(self):
        user = _user()
        scan = SimpleNamespace(
            user_id=user.id, outcome=None, engine="rapidocr", merchant="Toko Maju", parsed_total=Decimal(70000),
            total_label="SUBTOTAL", ocr_lines=json.dumps(["TOKO MAJU", "SUBTOTAL 70.000", "JML BYR 77.000"]),
            feedback_at=None, final_total=None, final_date=None, final_merchant=None,
        )
        db = MagicMock()
        db.get = AsyncMock(side_effect=[scan, None])  # scan, lalu label belum ada
        db.commit = AsyncMock()
        await receipt_scan.apply_feedback(user, uuid4(), db, saved=True, total=77000, merchant="Toko Maju")
        self.assertEqual(scan.outcome, "corrected")
        learned = db.add.call_args[0][0]
        self.assertEqual((learned.merchant_key, learned.label), ("TOKOMAJU", "JML BYR"))
        self.assertIsNone(scan.ocr_lines)

    async def test_feedback_ignores_other_users_scan(self):
        scan = SimpleNamespace(user_id=uuid4(), outcome=None)
        db = MagicMock(); db.get = AsyncMock(return_value=scan); db.commit = AsyncMock()
        self.assertIsNone(await receipt_scan.apply_feedback(_user(), uuid4(), db, saved=False))
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

    async def test_api_error_refunds_quota_and_budget(self):
        r = FakeRedis()
        bad = AsyncMock()
        bad.__aenter__.return_value.post = AsyncMock(return_value=MagicMock(status_code=500))
        self.assertIsNone(await self._call(r, _llm_settings(), client=bad))
        month = receipt_llm._month_key()
        self.assertEqual(r.d[f"receipt_llm:cost:{month}"], 0)
        self.assertEqual(r.d[f"receipt_llm:user:u1:{month}"], 0)

    def test_parse_reply_strips_thinking_and_rejects_garbage(self):
        self.assertEqual(receipt_llm._parse_reply('<think>hmm</think>{"total":"Rp 9.200","merchant":null,"date":null}')["total"], 9200)
        self.assertIsNone(receipt_llm._parse_reply("bukan json"))


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


if __name__ == "__main__":
    unittest.main()
