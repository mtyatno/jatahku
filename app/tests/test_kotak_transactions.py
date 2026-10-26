"""`scan-receipt` lewat Kotak Struk, kuota scan dihapus, dan `receipt_item_id` di POST /transactions
(+ /transactions/batch) (SQLite in-memory; klien httpx langsung ke ASGI supaya satu event loop dengan mesin async).
Run: python -m unittest app.tests.test_kotak_transactions -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import contextlib
import json
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import transactions as txn_route
from app.api.routes.transactions import _read_receipt_upload, run_receipt_scan
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    Allocation, Income, MerchantEnvelopeMap, ReceiptScan, Transaction, User, UserEnvelopeKeyword,
)
from app.services.kotak_struk import record as record_mod
from app.services.kotak_struk import waiter as waiter_mod
from app.services.kotak_struk.intake import IntakeRejected
from app.services.kotak_struk.worker import process_item
from app.services.receipt_ocr import OcrFailed
from app.services.receipt_scan import ScanBusy, scan_receipt
from app.tests import test_kotak_api as kapi
from app.tests.test_kotak_api import CORPUS, HAS_AIOSQLITE, JPG, NOW, QRIS_KEY, fake_extract

STORE_LINES = ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400",
               "Non Tunai (QRIS) 45.400"]
INDOMARET = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())["receipts"][1]["lines"]
MSG_RECORDED = "Bukti ini sudah tercatat"
RECORD_LOG = "app.services.kotak_struk.record"


class Up:
    """UploadFile tiruan: hanya `content_type` dan `read`."""

    def __init__(self, data, content_type):
        self.data, self.content_type = data, content_type

    async def read(self, n=-1):
        return self.data[:n] if n > 0 else self.data


class KvRedis:
    """Redis tiruan: idempotensi `client_ref` (get/set NX/delete) dan batas per jam intake (incr/expire)."""

    def __init__(self):
        self.kv, self.counts = {}, {}

    async def get(self, key):
        value = self.kv.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def delete(self, key):
        self.kv.pop(key, None)

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        return True

    async def aclose(self):
        pass


class TxnBase(kapi.ApiBase):
    """ApiBase + rute transaksi: klien `self.c` memanggil /transactions; amplop Makan dan Jajan berdana."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.redis = KvRedis()
        patcher = patch("redis.asyncio.from_url", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        async with self.Session() as db:
            income = Income(household_id=self.hh.id, user_id=self.a.id, amount=D("5000000"), description="Gaji",
                            income_date=date.today())
            db.add(income)
            await db.flush()
            db.add_all([Allocation(income_id=income.id, envelope_id=self.env[name].id, amount=D("1000000"))
                        for name in ("Makan", "Jajan")])
            await db.commit()

        app = FastAPI()
        app.include_router(txn_route.router, prefix="/transactions")
        app.state.limiter = txn_route.limiter

        async def _db():
            async with self.Session() as db:
                yield db

        async def _user(db=Depends(get_db)):   # user di sesi permintaan, seperti produksi (rollback meng-expire-nya)
            return await db.get(User, self.a.id)

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.c.aclose)

    # --- pembantu ------------------------------------------------------

    def run_inline(self, lines):
        """Penunggu yang menjalankan worker sungguhan (dengan hasil OCR palsu) lalu mengembalikan item-nya."""
        async def waiter(item_id, timeout_s):
            await process_item(item_id, session_factory=self.Session, extract=fake_extract(lines), now=NOW,
                               proofs_enabled=True)
            return await self.get(item_id)
        return waiter

    async def return_unprocessed(self, item_id, timeout_s):   # penunggu habis waktu: item masih `diterima`
        return await self.get(item_id)

    async def scan(self, lines, user=None, data=None, waiter=None):
        async with self.Session() as db:
            user = await db.get(User, (user or self.a).id)
            return await scan_receipt(user, data or JPG + uuid4().bytes, "image/jpeg", db,
                                      waiter=waiter or self.run_inline(lines))

    async def ready_store_receipt(self):
        item = await self.ready(STORE_LINES)
        self.assertEqual((await self.get(item.id)).doc_type, "struk_belanja")
        return item

    async def ready_unknown(self):
        """Item `siap` berjenis tidak_dikenali (ada nominal Rp, tanpa pembaca yang cocok)."""
        item = await self.ready(["foto buram", "Rp 12.000"])
        self.assertEqual((await self.get(item.id)).doc_type, "tidak_dikenali")
        return item

    @contextlib.contextmanager
    def db_fails_once(self, prefix, needle=""):
        """Satu galat DATABASE sungguhan (OperationalError dari lapisan eksekusi, sesi menjadi tidak aktif seperti saat
        disk/koneksi bermasalah) pada pernyataan SQL pertama yang berawalan `prefix` dan memuat `needle`.
        Menghasilkan penghitung: `[0]` berarti galatnya benar-benar terjadi."""
        left = [1]

        def hook(conn, cursor, statement, parameters, context, executemany):
            if left[0] and statement.lstrip().startswith(prefix) and needle in statement:
                left[0] -= 1
                raise OperationalError(statement, parameters, Exception("disk I/O error"))
        event.listen(self.engine.sync_engine, "before_cursor_execute", hook)
        try:
            yield left
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", hook)

    async def use_up_all_but_one_of_the_basic_quota(self):
        async with self.Session() as db:
            db.add_all([Transaction(envelope_id=self.env["Jajan"].id, user_id=self.a.id, amount=D("1000"),
                                    description="permen", transaction_date=date.today()) for _ in range(49)])
            await db.commit()

    async def post(self, item=None, *, ref=None, desc="bakso 2 (Siti Aminah)", amount=25000, env="Makan", **extra):
        body = {"envelope_id": str(self.env[env].id), "amount": amount, "description": desc, **extra}
        if item is not None:
            body["receipt_item_id"] = str(item.id)
        if ref is not None:
            body["client_ref"] = ref
        return await self.c.post("/transactions/", json=body)

    async def learned_keywords(self):
        async with self.Session() as db:
            return set((await db.execute(select(UserEnvelopeKeyword.keyword))).scalars())

    async def count(self, model):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model))).scalar_one()

    async def map_count(self, envelope="Makan"):
        mid = await self.merchant_id(QRIS_KEY)
        async with self.Session() as db:
            return (await db.execute(select(MerchantEnvelopeMap.count).where(
                MerchantEnvelopeMap.merchant_id == mid, MerchantEnvelopeMap.envelope_id == self.env[envelope].id))
            ).scalar_one()

    def other_session_claims(self):
        """`check_recordable` asli, lalu "sesi lain" mengklaim dan meng-commit bukti itu sebelum pemanggil
        sempat meng-klaim (dua simpan bersamaan, `client_ref` berbeda). SQLite tidak bisa mengaburkan dua sesi
        sungguhan di satu koneksi, jadi klaim sesi lain ditulis lewat sesi pemanggil lalu di-commit."""
        real = txn_route.check_recordable

        async def racing(db, item_id, user):
            item = await real(db, item_id, user)
            await db.execute(update(ReceiptScan).where(ReceiptScan.id == item_id).values(status="tercatat"))
            await db.commit()
            return item
        return patch.object(txn_route, "check_recordable", racing)


# ──────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class ScanReceiptTests(TxnBase):
    async def test_scan_receipt_returns_old_shape_plus_new_fields(self):
        out = await self.scan(CORPUS[0]["lines"])
        self.assertEqual((out["total"], out["doc_type"], out["quota"]["limit"]), (25000, "qris", None))
        self.assertEqual(out["scan_id"], out["item_id"])
        self.assertEqual(out["description_preview"], "Siti Aminah (QRIS)")
        self.assertEqual((await self.get(UUID(out["item_id"]))).source, "web_form")   # satu pintu: lewat intake Kotak Struk
        json.dumps(out)   # bisa diserialisasi untuk respons API

    async def test_proof_response_has_every_legacy_key_and_the_new_ones(self):
        out = await self.scan(CORPUS[0]["lines"])
        self.assertTrue({"scan_id", "merchant", "date", "total", "confidence", "confidence_source", "evidence",
                         "engine", "ocr_seconds", "quota", "items", "adjustments", "reconciliation"} <= set(out))
        self.assertTrue({"item_id", "doc_type", "counterparty", "paid_at", "flags", "suggestion",
                         "description_preview"} <= set(out))
        self.assertEqual((out["merchant"], out["date"], out["ocr_seconds"]), ("SITI AMINAH", "2026-10-26", 0))
        self.assertEqual((out["items"], out["adjustments"], out["reconciliation"]), ([], [], None))
        self.assertEqual(out["quota"], {"limit": None, "used": 0, "remaining": None})
        self.assertEqual((out["counterparty"]["name"], out["counterparty"]["id_kind"]), ("SITI AMINAH", "nmid"))
        self.assertTrue(out["paid_at"].startswith("2026-10-26T08:12:33"))   # 08:12 WIB (SQLite menyimpan jam dinding)
        self.assertEqual(out["flags"], kapi.NO_FLAGS)
        self.assertEqual(out["suggestion"]["source"], "none")
        self.assertNotIn("1024358806544", json.dumps(out))   # NMID utuh tidak pernah keluar

    async def test_store_receipt_keeps_the_legacy_item_breakdown(self):
        out = await self.scan(INDOMARET)
        self.assertEqual((out["doc_type"], out["total"], out["engine"]), ("struk_belanja", 51000, "rapidocr"))
        self.assertTrue(out["confidence_source"])   # asal keyakinan struk belanja ikut terbawa
        self.assertEqual(len(out["items"]), 5)
        self.assertEqual(out["reconciliation"]["status"], "cocok")
        self.assertEqual(out["items"][1]["discount"], 4800)   # voucher KOBE melekat ke barangnya
        self.assertEqual(set(out["items"][0]), {"name", "qty", "unit_price", "amount", "discount", "flag", "note", "suggestion"})
        self.assertEqual(set(out["reconciliation"]), {"items_total", "discounts", "charges", "expected", "diff", "status", "note"})
        json.dumps(out)

    async def test_scan_receipt_busy_when_not_done(self):
        with self.assertRaises(ScanBusy):   # penunggu habis waktu: item masih "diterima"
            await self.scan(None, waiter=self.return_unprocessed)
        [item] = await self.items()
        self.assertEqual(item.status, "diterima")   # tetap diproses worker dan muncul di banner

    async def test_scan_receipt_waits_form_timeout_for_the_item(self):
        seen = []

        async def waiter(item_id, timeout_s):
            seen.append(timeout_s)
            return await self.get(item_id)
        with self.assertRaises(ScanBusy):
            await self.scan(None, waiter=waiter)
        self.assertEqual(seen, [45])

    async def test_failed_item_raises_ocr_failed_with_its_message(self):
        async def failing(item_id, timeout_s):
            await self.set(item_id, status="gagal", error="PDF terkunci kata sandi")
            return await self.get(item_id)
        with self.assertRaises(OcrFailed) as cm:
            await self.scan(None, waiter=failing)
        self.assertEqual(str(cm.exception), "PDF terkunci kata sandi")

    async def test_same_photo_while_open_returns_the_same_item(self):
        data = JPG + b"sama"
        first = await self.scan(CORPUS[0]["lines"], data=data)
        again = await self.scan(CORPUS[0]["lines"], data=data)   # item pertama masih `siap`: tidak dibaca ulang
        self.assertEqual(again["item_id"], first["item_id"])
        self.assertEqual(len(await self.items()), 1)

    async def items(self):
        async with self.Session() as db:
            return list((await db.execute(select(ReceiptScan))).scalars())

    # --- rute ----------------------------------------------------------

    async def test_endpoint_returns_the_scan_result(self):
        with patch.object(waiter_mod, "wait_for_item", AsyncMock(side_effect=self.run_inline(CORPUS[0]["lines"]))):
            r = await self.c.post("/transactions/scan-receipt", files={"image": ("a.jpg", JPG + b"x", "image/jpeg")})
        self.assertEqual((r.status_code, r.json()["total"], r.json()["doc_type"]), (200, 25000, "qris"))

    async def test_endpoint_accepts_pdf(self):
        with patch.object(waiter_mod, "wait_for_item", AsyncMock(side_effect=self.run_inline(CORPUS[0]["lines"]))):
            r = await self.c.post("/transactions/scan-receipt", files={"image": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        self.assertEqual((r.status_code, r.json()["total"]), (200, 25000))

    async def test_endpoint_busy_is_503(self):
        with patch.object(waiter_mod, "wait_for_item", AsyncMock(side_effect=self.return_unprocessed)):
            r = await self.c.post("/transactions/scan-receipt", files={"image": ("a.jpg", JPG + b"y", "image/jpeg")})
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (503, "Scan struk sedang ramai. Coba lagi beberapa detik lagi."))

    async def test_run_receipt_scan_maps_errors(self):
        async def run_with(exc):
            with patch("app.services.receipt_scan.scan_receipt", AsyncMock(side_effect=exc)):
                with self.assertRaises(HTTPException) as cm:
                    await run_receipt_scan(self.a, b"x", "image/jpeg", None)
            return cm.exception.status_code, cm.exception.detail

        self.assertEqual(await run_with(ScanBusy()), (503, "Scan struk sedang ramai. Coba lagi beberapa detik lagi."))
        self.assertEqual(await run_with(OcrFailed("PDF terkunci kata sandi")), (422, "PDF terkunci kata sandi"))
        self.assertEqual(await run_with(IntakeRejected(429, "Masih ada bukti yang sedang dibaca. Tunggu sebentar.")),
                         (429, "Masih ada bukti yang sedang dibaca. Tunggu sebentar."))

    # --- unggahan ------------------------------------------------------

    async def test_pdf_upload_accepted_and_limits(self):
        data, ct = await _read_receipt_upload(Up(b"%PDF-1.4 x", "application/pdf"))
        self.assertEqual((data, ct), (b"%PDF-1.4 x", "application/pdf"))
        with self.assertRaises(HTTPException) as cm:
            await _read_receipt_upload(Up(b"%PDF" + b"0" * (10 * 1024 * 1024), "application/pdf"))
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (413, "PDF terlalu besar (maks 10 MB)"))

    async def test_image_limit_stays_8mb_and_unknown_type_is_415(self):
        with self.assertRaises(HTTPException) as cm:
            await _read_receipt_upload(Up(b"\xff\xd8\xff" + b"0" * (8 * 1024 * 1024), "image/jpeg"))
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (413, "Foto terlalu besar (maks 8 MB)"))
        with self.assertRaises(HTTPException) as cm:
            await _read_receipt_upload(Up(b"x", "text/plain"))
        self.assertEqual((cm.exception.status_code, cm.exception.detail),
                         (415, "Format tidak didukung. Pakai JPG, PNG, WebP, atau PDF."))
        with self.assertRaises(HTTPException) as cm:
            await _read_receipt_upload(Up(b"", "application/pdf"))
        self.assertEqual(cm.exception.status_code, 422)

    async def test_chat_photo_validation_stays_image_only(self):
        with self.assertRaises(HTTPException) as cm:   # alur foto bot (chat web) belum membaca PDF
            await _read_receipt_upload(Up(b"%PDF-1.4 x", "application/pdf"), allow_pdf=False)
        self.assertEqual((cm.exception.status_code, cm.exception.detail),
                         (415, "Format foto tidak didukung. Pakai JPG, PNG, atau WebP."))
        self.assertEqual(await _read_receipt_upload(Up(b"jpg", "image/jpeg"), allow_pdf=False), (b"jpg", "image/jpeg"))

    # --- kuota ---------------------------------------------------------

    async def test_quota_endpoint_unlimited(self):
        r = await self.c.get("/transactions/scan-receipt/quota")
        self.assertEqual(r.json(), {"limit": None, "used": 0, "remaining": None})   # saklar receipt_inbox tidak diset

    async def test_quota_endpoint_counts_scans_but_never_limits(self):
        await self.scan(CORPUS[0]["lines"])
        self.assertEqual((await self.c.get("/transactions/scan-receipt/quota")).json(),
                         {"limit": None, "used": 1, "remaining": None})


# ──────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RecordWithReceiptItemTests(TxnBase):
    async def test_create_with_receipt_item_records_and_learns(self):
        item = await self.ready_qris()
        r = await self.post(item, ref="r1")
        self.assertEqual(r.status_code, 201, r.text)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [r.json()["id"]]))
        self.assertEqual(await self.learned_keywords(), {"bakso"})   # tanpa "siti"/"aminah"
        self.assertEqual(await self.map_count(), 2)                  # peta merchant: Makan 1 -> 2

    async def test_second_record_of_same_proof_is_409_but_resend_is_same(self):
        item = await self.ready_qris()
        first = await self.post(item, ref="r1", desc="x")
        again = await self.post(item, ref="r1", desc="x")
        self.assertEqual(again.json()["id"], first.json()["id"])
        dup = await self.post(item, ref="r2", desc="x")
        self.assertEqual((dup.status_code, dup.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 1)
        self.assertEqual((await self.get(item.id)).transaction_ids, [first.json()["id"]])
        self.assertNotIn(f"txnref:{self.a.id}:r2", self.redis.kv)   # kunci `r2` dilepas, bisa dicoba lagi

    async def test_failed_transfer_cannot_be_recorded(self):
        item = await self.ready_transfer(CORPUS[3]["lines"])
        r = await self.post(item, desc="x", amount=50000)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Transaksi gagal, tidak bisa dicatat"))
        self.assertEqual(await self.count(Transaction), 0)

    async def test_other_users_or_missing_item_is_409_not_found(self):
        theirs = await self.ready_qris(owner=self.b)
        for item_id in (theirs.id, uuid4()):
            r = await self.c.post("/transactions/", json={"envelope_id": str(self.env["Makan"].id), "amount": 25000,
                                                          "description": "x", "receipt_item_id": str(item_id)})
            self.assertEqual((r.status_code, r.json()["detail"]), (409, "Bukti tidak ditemukan"))
        self.assertEqual((await self.get(theirs.id)).status, "siap")

    async def test_item_not_ready_is_409(self):
        item = await self.ready_qris()
        await self.set(item.id, status="dilewati")
        r = await self.post(item)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Bukti ini belum siap dicatat"))

    async def test_expired_item_is_409_with_expired_message(self):
        item = await self.ready_qris()
        await self.set(item.id, status="kedaluwarsa")
        r = await self.post(item)
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (409, "Bukti ini sudah kedaluwarsa. Bagikan lagi untuk mencatatnya."))
        self.assertEqual(await self.count(Transaction), 0)

    async def test_receipt_check_runs_after_idempotency_and_before_envelope_checks(self):
        item = await self.ready_transfer(CORPUS[3]["lines"])
        r = await self.c.post("/transactions/", json={"envelope_id": str(uuid4()), "amount": 1, "description": "x",
                                                      "receipt_item_id": str(item.id)})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Transaksi gagal, tidak bisa dicatat"))

    async def test_without_receipt_item_nothing_changes(self):
        r = await self.post(desc="kopi susu", amount=10000, ref="n1")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(await self.learned_keywords(), {"kopi", "susu", "kopi susu"})   # keterangan utuh, seperti dulu

    async def test_rejected_transaction_leaves_the_proof_ready(self):
        item = await self.ready_qris()
        r = await self.post(item, amount=50_000_000, ref="big")   # dana tidak cukup
        self.assertEqual(r.status_code, 403)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("siap", None))
        self.assertEqual((await self.post(item, ref="big2")).status_code, 201)

    async def test_commit_failure_rolls_the_claim_back_with_the_transaction(self):
        item = await self.ready_qris()
        real_commit = AsyncSession.commit
        calls = []

        async def commit(self_):
            calls.append(1)
            if len(calls) == 1:   # commit yang memuat transaksi + klaim
                raise RuntimeError("disk penuh")
            return await real_commit(self_)
        with patch.object(AsyncSession, "commit", commit), self.assertRaises(RuntimeError):
            await self.post(item, ref="gagal")
        got = await self.get(item.id)
        self.assertEqual((got.status, await self.count(Transaction)), ("siap", 0))
        self.assertNotIn(f"txnref:{self.a.id}:gagal", self.redis.kv)

    # --- klaim atomik ---------------------------------------------------

    async def test_proof_claimed_by_another_save_between_check_and_commit_is_409(self):
        item = await self.ready_qris()
        with self.other_session_claims():
            r = await self.post(item, ref="kalah")
        self.assertEqual((r.status_code, r.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 0)             # tidak ada baris transaksi
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", None))   # klaim pihak lain utuh
        self.assertNotIn(f"txnref:{self.a.id}:kalah", self.redis.kv)   # kunci dilepas
        self.assertEqual(await self.learned_keywords(), set())

    async def test_unknown_document_claimed_by_another_save_between_check_and_commit_is_409(self):
        """`tidak_dikenali` dicatat sekali saja seperti bukti bayar (spec 5c), jadi klaimnya juga eksklusif."""
        item = await self.ready_unknown()
        with self.other_session_claims():
            r = await self.post(item, ref="kalah", desc="x", amount=12000)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 0)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", None))
        self.assertNotIn(f"txnref:{self.a.id}:kalah", self.redis.kv)
        self.assertEqual(await self.learned_keywords(), set())

    async def test_guessed_total_item_is_an_unknown_document_with_an_exclusive_claim(self):
        """Foto yang hanya terbaca lewat tebakan struk lama (`["TOKO","45.500"]`, tanpa baris Rp) tetap tidak_dikenali:
        sekali dicatat, klaimnya eksklusif."""
        item = await self.ready(["TOKO", "45.500"])
        self.assertEqual((await self.get(item.id)).doc_type, "tidak_dikenali")
        with self.other_session_claims():
            lost = await self.post(item, ref="kalah", desc="x", amount=45500)
        self.assertEqual((lost.status_code, lost.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 0)
        fresh = await self.ready(["TOKO", "45.500"])
        first = await self.post(fresh, ref="a", desc="titipan", amount=45500)
        self.assertEqual(first.status_code, 201, first.text)
        again = await self.post(fresh, ref="b", desc="titipan", amount=45500)
        self.assertEqual((again.status_code, again.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 1)

    async def test_unknown_document_is_recorded_once_and_never_teaches_the_merchant_map(self):
        item = await self.ready_unknown()
        first = await self.post(item, ref="a", desc="titipan", amount=12000)
        self.assertEqual(first.status_code, 201, first.text)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [first.json()["id"]]))
        again = await self.post(item, ref="b", desc="titipan", amount=12000)
        self.assertEqual((again.status_code, again.json()["detail"]), (409, MSG_RECORDED))
        self.assertEqual(await self.count(Transaction), 1)
        self.assertEqual(await self.count(MerchantEnvelopeMap), 0)   # peta merchant hanya belajar dari QRIS/transfer

    async def test_store_receipt_claim_is_not_exclusive(self):
        item = await self.ready_store_receipt()
        with self.other_session_claims():   # struk belanja: tidak ada klaim eksklusif; dicatat per barang
            r = await self.post(item, ref="a", desc="ROTI (Alfamart)", amount=15000)
        self.assertEqual(r.status_code, 201)

    # --- kirim ulang menyembuhkan -------------------------------------

    async def test_replay_heals_a_lost_mark_recorded(self):
        item = await self.ready_qris()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("commit gagal"))), \
                self.assertLogs(RECORD_LOG, "WARNING") as logs:
            first = await self.post(item, ref="r1")
        self.assertEqual(first.status_code, 201)   # transaksi tetap sukses
        self.assertIn("mark_recorded", logs.output[0])
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", None))   # klaim sudah ikut commit transaksi

        again = await self.post(item, ref="r1")    # klien mengirim ulang
        self.assertEqual(again.json()["id"], first.json()["id"])
        self.assertEqual((await self.get(item.id)).transaction_ids, [first.json()["id"]])
        self.assertEqual(await self.map_count(), 2)

        await self.post(item, ref="r1")             # dan sekali lagi: tidak ganda
        self.assertEqual((await self.get(item.id)).transaction_ids, [first.json()["id"]])
        self.assertEqual((await self.map_count(), await self.count(Transaction)), (2, 1))
        self.assertEqual(await self.learned_keywords(), {"bakso"})
        async with self.Session() as db:
            kw = (await db.execute(select(UserEnvelopeKeyword.count))).scalar_one()
        self.assertEqual(kw, 1)                     # tidak belajar dua kali

    async def test_replay_never_touches_other_users_or_unclaimed_items(self):
        mine = await self.ready_qris()
        first = await self.post(mine, ref="r1")
        theirs = await self.ready_qris(owner=self.b)
        unclaimed = await self.ready_transfer(CORPUS[2]["lines"])
        for item in (theirs, unclaimed):
            again = await self.post(item, ref="r1")   # `client_ref` lama, tapi bukti lain
            self.assertEqual(again.json()["id"], first.json()["id"])
            got = await self.get(item.id)
            self.assertEqual((got.status, got.transaction_ids), ("siap", None))

    async def test_replay_never_touches_an_unclaimed_unknown_document(self):
        mine = await self.ready_qris()
        first = await self.post(mine, ref="r1")
        unknown = await self.ready_unknown()   # `siap`, belum diklaim transaksi mana pun
        again = await self.post(unknown, ref="r1")   # `client_ref` lama, tapi bukti lain
        self.assertEqual(again.json()["id"], first.json()["id"])
        got = await self.get(unknown.id)
        self.assertEqual((got.status, got.transaction_ids), ("siap", None))

    async def test_replay_heals_a_lost_mark_recorded_for_an_unknown_document(self):
        item = await self.ready_unknown()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("commit gagal"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            first = await self.post(item, ref="r1", desc="titipan", amount=12000)
        self.assertEqual(first.status_code, 201)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", None))   # diklaim, belum ditandai
        again = await self.post(item, ref="r1", desc="titipan", amount=12000)
        self.assertEqual(again.json()["id"], first.json()["id"])
        self.assertEqual((await self.get(item.id)).transaction_ids, [first.json()["id"]])

    # --- galat database yang ditelan tidak boleh merusak sisa permintaan ------

    async def test_marking_failure_at_the_database_still_answers_201_with_the_quota_notice(self):
        """Commit `mark_recorded` gagal sungguhan (sesi jadi tidak aktif): transaksinya sudah tercatat, jadi respons
        tetap 201 dan pemberitahuan kuota Basic (pertanyaan ke DB) tetap terhitung; kirim ulang menyembuhkan."""
        await self.use_up_all_but_one_of_the_basic_quota()
        item = await self.ready_qris()
        with self.db_fails_once("UPDATE receipt_scans", "transaction_ids") as left, \
                self.assertLogs(RECORD_LOG, "WARNING") as logs:
            r = await self.post(item, ref="r1")
        self.assertEqual(left, [0])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis", r.json()["quota_notice"])
        self.assertIn("mark_recorded", logs.output[0])
        self.assertEqual(await self.count(Transaction), 50)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", None))   # klaim ikut commit transaksi
        again = await self.post(item, ref="r1")   # dan kirim ulang yang sama menandainya
        self.assertEqual(again.json()["id"], r.json()["id"])
        self.assertEqual((await self.get(item.id)).transaction_ids, [r.json()["id"]])

    async def test_resend_whose_healing_fails_at_the_database_still_answers_with_the_same_transaction(self):
        item = await self.ready_qris()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("commit gagal"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            first = await self.post(item, ref="r1")
        self.assertEqual(first.status_code, 201)
        with self.db_fails_once("UPDATE receipt_scans", "transaction_ids") as left, \
                self.assertLogs(RECORD_LOG, "WARNING"):
            again = await self.post(item, ref="r1")   # penyembuhan gagal di DB; respons tetap transaksi yang sama
        self.assertEqual(left, [0])
        self.assertEqual((again.status_code, again.json()["id"]), (201, first.json()["id"]))
        self.assertEqual((await self.get(item.id)).transaction_ids, None)
        third = await self.post(item, ref="r1")   # DB sehat lagi: tersembuhkan
        self.assertEqual(third.json()["id"], first.json()["id"])
        self.assertEqual((await self.get(item.id)).transaction_ids, [first.json()["id"]])

    async def test_keyword_learning_failure_at_the_database_still_answers_201_and_marks_the_item(self):
        await self.use_up_all_but_one_of_the_basic_quota()
        item = await self.ready_qris()
        with self.db_fails_once("INSERT INTO user_envelope_keywords") as left, \
                self.assertLogs(RECORD_LOG, "WARNING"):
            r = await self.post(item, ref="r1")
        self.assertEqual(left, [0])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis", r.json()["quota_notice"])
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [r.json()["id"]]))
        self.assertEqual(await self.map_count(), 2)   # peta merchant tetap belajar
        self.assertEqual(await self.learned_keywords(), set())   # kata kunci yang gagal tidak dipelajari

    async def test_mark_recorded_failure_is_logged_not_raised(self):
        item = await self.ready_qris()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("x"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            r = await self.post(item)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["description"], "bakso 2 (Siti Aminah)")

    async def test_learn_text_failure_skips_keyword_learning_but_keeps_the_transaction(self):
        item = await self.ready_qris()
        with patch.object(record_mod, "learn_text_for_item", AsyncMock(side_effect=RuntimeError("x"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            r = await self.post(item)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(await self.learned_keywords(), set())   # tidak pernah belajar nama merchant
        self.assertEqual((await self.get(item.id)).status, "tercatat")


# ──────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class BatchWithReceiptItemTests(TxnBase):
    async def batch(self, items):
        r = await self.c.post("/transactions/batch", json={"items": items})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def line(self, item=None, *, ref, env="Makan", amount=10000, desc="ROTI (Indomaret)"):
        out = {"envelope_id": str(self.env[env].id), "amount": amount, "description": desc, "client_ref": ref}
        if item is not None:
            out["receipt_item_id"] = str(item.id)
        return out

    async def test_batch_store_receipt_items_share_one_receipt_item(self):
        item = await self.ready_store_receipt()
        out = await self.batch([self.line(item, ref="a"),
                                self.line(item, ref="b", env="Jajan", amount=5000, desc="PERMEN (Indomaret)")])
        self.assertTrue(all(x["ok"] for x in out))
        got = await self.get(item.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [x["id"] for x in out]))
        self.assertEqual(await self.count(Transaction), 2)
        self.assertTrue({"roti", "permen"} <= await self.learned_keywords())   # struk belanja: belajar dari keterangan utuh

    async def test_same_proof_twice_in_one_batch_second_line_rejected(self):
        item = await self.ready_qris()
        out = await self.batch([self.line(item, ref="a", amount=25000, desc="bakso (Siti Aminah)"),
                                self.line(item, ref="b", amount=25000, desc="es teh (Siti Aminah)")])
        self.assertEqual([x["ok"] for x in out], [True, False])
        self.assertEqual(out[1]["error"], MSG_RECORDED)
        self.assertEqual(await self.count(Transaction), 1)
        self.assertEqual((await self.get(item.id)).transaction_ids, [out[0]["id"]])
        self.assertEqual(await self.learned_keywords(), {"bakso"})

    async def test_failed_first_line_leaves_the_proof_for_the_next_line(self):
        item = await self.ready_qris()
        out = await self.batch([self.line(item, ref="a", amount=50_000_000), self.line(item, ref="b", amount=25000)])
        self.assertEqual([x["ok"] for x in out], [False, True])
        self.assertEqual((await self.get(item.id)).transaction_ids, [out[1]["id"]])

    async def test_line_lost_to_another_save_is_rejected_and_the_rest_still_records(self):
        item = await self.ready_qris()
        with self.other_session_claims():
            out = await self.batch([self.line(item, ref="a", amount=25000),
                                    self.line(None, ref="b", env="Jajan", amount=4000, desc="permen")])
        self.assertEqual([x["ok"] for x in out], [False, True])
        self.assertEqual(out[0]["error"], MSG_RECORDED)
        self.assertEqual(await self.count(Transaction), 1)
        self.assertNotIn(f"txnref:{self.a.id}:a", self.redis.kv)

    async def test_blocked_unknown_and_foreign_items_are_per_line_errors(self):
        failed = await self.ready_transfer(CORPUS[3]["lines"])
        theirs = await self.ready_qris(owner=self.b)
        out = await self.batch([self.line(failed, ref="a"), self.line(theirs, ref="b"), self.line(None, ref="c")])
        self.assertEqual([x["ok"] for x in out], [False, False, True])
        self.assertEqual([x["error"] for x in out[:2]], ["Transaksi gagal, tidak bisa dicatat", "Bukti tidak ditemukan"])
        self.assertEqual((await self.get(theirs.id)).status, "siap")

    async def test_line_whose_marking_fails_at_the_database_does_not_break_the_next_line(self):
        """Commit `mark_recorded` baris 1 gagal sungguhan: sesinya dipulihkan, jadi baris 2 (cek `check_recordable`,
        klaim, simpan) dan pemberitahuan kuota di akhir tetap jalan."""
        await self.use_up_all_but_one_of_the_basic_quota()
        proof = await self.ready_qris()
        store = await self.ready_store_receipt()
        with self.db_fails_once("UPDATE receipt_scans", "transaction_ids") as left, \
                self.assertLogs(RECORD_LOG, "WARNING"):
            out = await self.batch([self.line(proof, ref="a", amount=25000, desc="bakso (Siti Aminah)"),
                                    self.line(store, ref="b", env="Jajan", amount=15000, desc="ROTI (Alfamart)")])
        self.assertEqual(left, [0])
        self.assertEqual([x["ok"] for x in out], [True, True])
        self.assertEqual(await self.count(Transaction), 51)
        self.assertEqual((await self.get(proof.id)).transaction_ids, None)            # menunggu kirim ulang
        self.assertEqual((await self.get(store.id)).transaction_ids, [out[1]["id"]])  # baris 2 ditandai
        self.assertIn("roti", await self.learned_keywords())
        self.assertTrue(all("Kuota 50" in x["quota_notice"] for x in out))
        again = await self.batch([self.line(proof, ref="a", amount=25000, desc="bakso (Siti Aminah)")])
        self.assertEqual((again[0]["id"], (await self.get(proof.id)).transaction_ids), (out[0]["id"], [out[0]["id"]]))

    async def test_line_whose_keyword_learning_fails_at_the_database_does_not_break_the_next_line(self):
        proof = await self.ready_qris()
        store = await self.ready_store_receipt()
        with self.db_fails_once("INSERT INTO user_envelope_keywords") as left, \
                self.assertLogs(RECORD_LOG, "WARNING"):
            out = await self.batch([self.line(proof, ref="a", amount=25000, desc="bakso (Siti Aminah)"),
                                    self.line(store, ref="b", env="Jajan", amount=15000, desc="ROTI (Alfamart)")])
        self.assertEqual(left, [0])
        self.assertEqual([x["ok"] for x in out], [True, True])
        self.assertEqual((await self.get(proof.id)).transaction_ids, [out[0]["id"]])
        self.assertEqual((await self.get(store.id)).transaction_ids, [out[1]["id"]])
        learned = await self.learned_keywords()
        self.assertIn("roti", learned)            # baris 2 belajar
        self.assertNotIn("bakso", learned)        # baris 1 gagal belajar

    async def test_resent_line_whose_healing_fails_at_the_database_does_not_break_the_next_line(self):
        proof = await self.ready_qris()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("x"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            first = await self.batch([self.line(proof, ref="a", amount=25000, desc="bakso (Siti Aminah)")])
        with self.db_fails_once("UPDATE receipt_scans", "transaction_ids") as left, \
                self.assertLogs(RECORD_LOG, "WARNING"):
            out = await self.batch([self.line(proof, ref="a", amount=25000, desc="bakso (Siti Aminah)"),
                                    self.line(None, ref="b", env="Jajan", amount=4000, desc="permen")])
        self.assertEqual(left, [0])
        self.assertEqual([x["ok"] for x in out], [True, True])
        self.assertEqual(out[0]["id"], first[0]["id"])
        self.assertEqual(await self.count(Transaction), 2)

    async def test_resend_of_a_batch_line_heals_and_does_not_double(self):
        item = await self.ready_qris()
        with patch.object(record_mod, "mark_recorded", AsyncMock(side_effect=RuntimeError("x"))), \
                self.assertLogs(RECORD_LOG, "WARNING"):
            first = await self.batch([self.line(item, ref="a", amount=25000, desc="bakso (Siti Aminah)")])
        self.assertTrue(first[0]["ok"])
        self.assertEqual((await self.get(item.id)).transaction_ids, None)
        again = await self.batch([self.line(item, ref="a", amount=25000, desc="bakso (Siti Aminah)")])
        self.assertEqual(again[0]["id"], first[0]["id"])
        self.assertEqual((await self.get(item.id)).transaction_ids, [first[0]["id"]])
        self.assertEqual(await self.count(Transaction), 1)


if __name__ == "__main__":
    unittest.main()
