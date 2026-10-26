"""Worker Kotak Struk, penunggu hasil, peta merchant, dan saklar fitur (SQLite berkas sementara).
Run: python -m unittest app.tests.test_kotak_worker -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import contextlib
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import event, func, select, update

from app.core.database import Base
from app.main import app, lifespan
from app.models.models import AppSetting, Household, HouseholdMember, HouseholdMerchant, HouseholdRole, ReceiptScan, User
from app.services.app_config import FEATURES, feature_enabled
from app.services.kotak_struk import merchants, waiter, worker
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.extract import ExtractError, PdfLocked, TextDoc
from app.services.kotak_struk.intake import IntakeRequest, create_item
from app.services.kotak_struk.merchants import hmac_hex, upsert_household_merchant
from app.services.kotak_struk.waiter import publish_done, wait_for_item
from app.services.kotak_struk.worker import claim_next, process_item, recover_stale, run_worker

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)  # 10:00 WIB
JPG = b"\xff\xd8\xff\xe0jpeg"
INDOMARET = json.loads((Path(__file__).parent / "fixtures" / "receipt_ocr_lines.json").read_text())["receipts"][0]["lines"]
SECRET_NUMBERS = ("012301001234567", "2026102612345678")  # rekening dan nomor referensi di CORPUS[2]
STORE_LINES = ["ALFAMART", "14-10-2026 08:15", "ROTI 1 15.000", "SUSU 2 30.400", "Total Belanja 45.400",
               "Non Tunai (QRIS) 45.400"]
MSG_UNREADABLE = "Bukti tidak bisa dibaca. Coba kirim ulang."


_TEMPLATE_DB = None


def setUpModule():
    """Skema SQLite dibuat sekali; tiap tes menyalin berkasnya (lebih cepat, dan tidak memblokir event loop tes)."""
    global _TEMPLATE_DB
    if HAS_AIOSQLITE:
        from sqlalchemy import create_engine
        _TEMPLATE_DB = os.path.join(tempfile.mkdtemp(), "template.db")
        engine = create_engine(f"sqlite:///{_TEMPLATE_DB}")
        Base.metadata.create_all(engine)
        engine.dispose()


def tearDownModule():
    if _TEMPLATE_DB:
        shutil.rmtree(os.path.dirname(_TEMPLATE_DB), ignore_errors=True)


def fake_extract(lines, kind="image"):
    return AsyncMock(return_value=TextDoc(lines=list(lines), kind=kind))


def broken_redis():
    raise ConnectionError("redis mati")


class FakeRedis:
    def __init__(self):
        self.counts = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        return True


class WorkerBase(unittest.IsolatedAsyncioTestCase):
    patch_publish = True  # kabar Redis diganti tiruan; WaiterTests menguji publish_done asli

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.dir = tempfile.mkdtemp()
        self.kotak = os.path.join(self.dir, "kotak")
        shutil.copyfile(_TEMPLATE_DB, f"{self.dir}/t.db")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.dir}/t.db")
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT terluar butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            user, hh = User(name="Rina Wulandari"), Household(name="Rumah Tes")
            db.add_all([user, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole.owner))
            await db.commit()
            self.user_id, self.hh_id = user.id, hh.id
        patcher = patch.object(merchants, "_warned_no_key", True)  # peringatan kunci HMAC turunan: bukan urusan tes ini
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.patch_publish:
            patcher = patch.object(waiter, "publish_done", new_callable=AsyncMock)
            self.publish = patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await self.engine.dispose()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def item(self, text=None, data=None, source="telegram", **cols):
        async with self.Session() as db:
            user = await db.get(User, self.user_id)
            req = IntakeRequest(user, source, text=text, data=data, channel_meta=cols.pop("channel_meta", None))
            it, _ = await create_item(db, req, redis=FakeRedis(), kotak_dir=self.kotak, now=NOW)
        if cols:
            await self.set(it.id, **cols)
        return it

    async def get(self, item_id):
        async with self.Session() as db:
            return await db.get(ReceiptScan, item_id)

    async def set(self, item_id, **cols):
        async with self.Session() as db:
            await db.execute(update(ReceiptScan).where(ReceiptScan.id == item_id).values(**cols))
            await db.commit()

    async def merchant(self, key):
        async with self.Session() as db:
            return (await db.execute(select(HouseholdMerchant).where(HouseholdMerchant.counterparty_key == key))).scalars().first()

    async def count_merchants(self):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(HouseholdMerchant))).scalar()

    async def enable_proofs(self, value=True):
        async with self.Session() as db:
            db.add(AppSetting(key="app_config", value=json.dumps({"features": {"receipt_inbox": {"web": value}}})))
            await db.commit()

    async def process(self, item, lines=None, **kw):
        kw.setdefault("extract", fake_extract(lines if lines is not None else CORPUS[0]["lines"]))
        kw.setdefault("now", NOW)
        kw.setdefault("proofs_enabled", True)
        return await process_item(item.id, session_factory=self.Session, **kw)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class WorkerTests(WorkerBase):
    # --- brief ---------------------------------------------------------

    async def test_process_qris_to_siap(self):
        item = await self.item(text="ignored")
        status = await process_item(item.id, session_factory=self.Session, extract=fake_extract(CORPUS[0]["lines"]),
                                    now=NOW, proofs_enabled=True)
        self.assertEqual(status, "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, int(got.parsed_total), got.merchant), ("qris", "qris.umum", 25000, "SITI AMINAH"))
        self.assertEqual(got.counterparty_key, "nmid:ID1024358806544")
        self.assertEqual(got.ref_hash, hmac_hex("612345678812"))
        self.assertEqual(got.paid_at.isoformat()[:16], "2026-10-26T08:12")
        self.assertIsNone(got.file_path)
        self.assertEqual(os.listdir(self.kotak), [])
        self.assertEqual(got.expires_at.replace(tzinfo=timezone.utc), NOW + timedelta(days=7))
        self.assertEqual((await self.merchant("nmid:ID1024358806544")).raw_name, "SITI AMINAH")

    async def test_extract_error_marks_gagal_with_message(self):
        item = await self.item(text="x")
        status = await process_item(item.id, session_factory=self.Session, extract=AsyncMock(side_effect=PdfLocked()), now=NOW)
        got = await self.get(item.id)
        self.assertEqual((status, got.status, got.error, got.file_path), ("gagal", "gagal", "PDF terkunci kata sandi", None))
        self.assertEqual(os.listdir(self.kotak), [])
        self.publish.assert_awaited_once_with(item.id, "gagal")

    async def test_claim_is_exclusive(self):
        item = await self.item(text="x")
        async with self.Session() as db:
            self.assertEqual(await claim_next(db), item.id)
            self.assertIsNone(await claim_next(db))

    async def test_stale_item_recovered_then_processed(self):
        item = await self.item(text="x")
        async with self.Session() as db:
            await claim_next(db, now=NOW)
        async with self.Session() as db:
            self.assertEqual(await recover_stale(db, now=NOW + timedelta(minutes=6)), 1)
        self.assertEqual((await self.get(item.id)).status, "diterima")
        self.assertTrue(Path((await self.get(item.id)).file_path).exists())
        async with self.Session() as db:
            self.assertEqual(await claim_next(db, now=NOW), item.id)
        self.assertEqual(await self.process(item, ["Transfer Berhasil"]), "siap")

    async def test_third_stale_attempt_gives_up(self):
        item = await self.item(text="x")
        await self.set(item.id, status="diproses", attempts=3, processed_at=NOW - timedelta(minutes=10))
        async with self.Session() as db:
            await recover_stale(db, now=NOW)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.error, got.file_path), ("gagal", MSG_UNREADABLE, None))
        self.assertEqual(os.listdir(self.kotak), [])
        self.assertEqual(got.expires_at.replace(tzinfo=timezone.utc), NOW + timedelta(days=7))
        self.publish.assert_awaited_once_with(item.id, "gagal")

    # --- claim / recover ----------------------------------------------

    async def test_claim_takes_oldest_and_counts_attempt(self):
        old = await self.item(text="lama")
        new = await self.item(text="baru")
        await self.set(old.id, created_at=NOW - timedelta(hours=1))
        await self.set(new.id, created_at=NOW)
        async with self.Session() as db:
            self.assertEqual(await claim_next(db, now=NOW), old.id)
        got = await self.get(old.id)
        self.assertEqual((got.status, got.attempts), ("diproses", 1))
        self.assertEqual(got.processed_at.replace(tzinfo=timezone.utc), NOW)
        self.assertEqual((await self.get(new.id)).status, "diterima")

    async def test_claim_with_nothing_waiting_returns_none(self):
        async with self.Session() as db:
            self.assertIsNone(await claim_next(db))

    async def test_recover_leaves_fresh_and_final_items_alone(self):
        fresh = await self.item(text="segar", status="diproses", attempts=1, processed_at=NOW - timedelta(minutes=2))
        done = await self.item(text="selesai", status="siap", processed_at=NOW - timedelta(hours=2))
        async with self.Session() as db:
            self.assertEqual(await recover_stale(db, now=NOW), 0)
        self.assertEqual((await self.get(fresh.id)).status, "diproses")
        self.assertEqual((await self.get(done.id)).status, "siap")
        self.publish.assert_not_awaited()

    async def test_recover_notifies_when_it_gives_up_on_a_telegram_item(self):
        item = await self.item(text="x", status="diproses", attempts=3, processed_at=NOW - timedelta(minutes=10),
                               channel_meta={"chat_id": 1, "notify": True})
        fake = types.SimpleNamespace(send_ready_message=AsyncMock())
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": fake}):
            async with self.Session() as db:
                await recover_stale(db, now=NOW)
        fake.send_ready_message.assert_awaited_once_with(item.id)

    # --- process_item: isi kolom --------------------------------------

    async def test_transfer_keeps_account_number_out_of_every_column(self):
        item = await self.item(text="transfer")
        self.assertEqual(await self.process(item, CORPUS[2]["lines"]), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, got.merchant, int(got.parsed_total)), ("transfer", "transfer.umum", "BUDI SANTOSO", 152500))
        self.assertTrue(got.counterparty_key.startswith("rek:"), got.counterparty_key)
        self.assertEqual(got.ref_hash, hmac_hex("2026102612345678"))
        self.assertIsNone(got.ocr_lines)
        blob = json.dumps([got.document, got.counterparty_key, got.ref_hash, got.merchant, got.error, got.ocr_lines])
        self.assertNotIn("012301001234567", blob.replace(" ", ""))
        self.assertNotIn("2026102612345678", blob)
        self.assertNotIn("receipt", got.document)
        doc = DokumenBayar.from_json(got.document)
        self.assertEqual(doc.doc_type, "transfer")
        self.assertTrue(doc.checks is not None and isinstance(doc.checks, list))
        self.assertEqual(got.confidence, doc.confidence["total"])
        self.assertEqual(got.pages, 1)

    async def test_store_receipt_keeps_legacy_data_and_learning_text(self):
        item = await self.item(text="struk")
        self.assertEqual(await self.process(item, STORE_LINES), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, got.engine, got.merchant), ("struk_belanja", "struk_belanja", "rapidocr", "Alfamart"))
        self.assertEqual((int(got.parsed_total), got.parsed_date), (45400, date(2026, 10, 14)))
        self.assertEqual(got.merchant_key, "ALFAMART")
        self.assertEqual(got.total_label, "TOTAL BELANJA")
        self.assertEqual(got.confidence, "tinggi")
        self.assertIn("ROTI 1 15.000", json.loads(got.ocr_lines))
        receipt = got.document["receipt"]
        self.assertEqual(set(receipt), {"item_discounts", "adjustments", "reconciliation", "confidence_source", "total_label"})
        self.assertEqual(receipt["total_label"], "TOTAL BELANJA")
        self.assertEqual(len(receipt["item_discounts"]), len([ln for ln in got.document["lines"] if ln["kind"] == "item"]))
        self.assertEqual(got.counterparty_key, "nama:alfamart|")
        self.assertEqual((await self.merchant("nama:alfamart|")).raw_name, "Alfamart")
        self.assertEqual(DokumenBayar.from_json(got.document).doc_type, "struk_belanja")  # kunci "receipt" diabaikan

    async def test_proofs_read_as_store_receipt_while_flag_is_off_keep_no_text_and_no_merchant(self):
        """Saklar mati (bawaan produksi): bukti bayar dibaca pembaca struk, tapi teks OCR-nya memuat nomor
        rekening/referensi dan nama pihak ketiga, jadi tidak disimpan, dan namanya tidak masuk peta merchant."""
        for sample in CORPUS:
            if sample["expect"]["doc_type"] not in ("qris", "transfer") and sample["id"] != "sint-masuk":
                continue
            with self.subTest(sample["id"]):
                item = await self.item(text=sample["id"])
                self.assertEqual(await self.process(item, sample["lines"], proofs_enabled=False), "siap")
                got = await self.get(item.id)
                self.assertNotIn(got.parser, ("qris.umum", "transfer.umum"))  # memang lewat jalur struk/tak dikenali
                self.assertIsNone(got.ocr_lines)
                blob = json.dumps([got.document, got.ocr_lines, got.counterparty_key, got.ref_hash]).replace(" ", "")
                for number in SECRET_NUMBERS:
                    self.assertNotIn(number, blob)
        self.assertEqual(await self.count_merchants(), 0)

    async def test_transfer_text_with_flag_off_reads_the_same_as_before_just_without_retention(self):
        item = await self.item(text="transfer")
        self.assertEqual(await self.process(item, CORPUS[2]["lines"], proofs_enabled=False), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.status), ("struk_belanja", "siap"))
        self.assertIn("receipt", got.document)  # data respons scan lama tetap ada
        self.assertEqual(await self.count_merchants(), 0)

    async def test_real_store_receipt_still_keeps_normalized_text_and_merchant_with_flag_off(self):
        item = await self.item(text="indomaret")
        self.assertEqual(await self.process(item, INDOMARET, proofs_enabled=False), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser), ("struk_belanja", "struk_belanja"))
        self.assertTrue(json.loads(got.ocr_lines))
        self.assertTrue(got.counterparty_key)
        self.assertEqual((await self.merchant(got.counterparty_key)).raw_name, got.merchant)

    async def test_store_receipt_mentioning_qris_still_keeps_text_and_merchant_with_flag_off(self):
        item = await self.item(text="alfamart")
        await self.process(item, STORE_LINES, proofs_enabled=False)
        got = await self.get(item.id)
        self.assertIn("ROTI 1 15.000", json.loads(got.ocr_lines))
        self.assertEqual((await self.merchant("nama:alfamart|")).raw_name, "Alfamart")

    async def test_unrecognised_text_is_siap_without_retaining_text(self):
        item = await self.item(text="acak")
        self.assertEqual(await self.process(item, ["halo apa kabar", "tidak ada nominal"]), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, got.parsed_total, got.ocr_lines, got.confidence),
                         ("tidak_dikenali", "tidak_dikenali", None, None, "gagal"))
        self.assertIsNone(got.counterparty_key)
        self.assertEqual(await self.count_merchants(), 0)

    async def test_sparse_text_without_rp_is_a_low_confidence_unknown_document_guess(self):
        """Tanpa baris Rp pembaca cadangan menebak seperti scan struk lama (bukan tanpa total), selalu `rendah`, tetap
        `tidak_dikenali` (spec 6a): tanpa teks OCR (itu hanya untuk struk belanja), tanpa data belajar struk."""
        item = await self.item(text="sepi")
        self.assertEqual(await self.process(item, ["TOKO", "14-10-2026 08:15", "45.500"]), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, int(got.parsed_total), got.confidence, got.parsed_date),
                         ("tidak_dikenali", "tidak_dikenali", 45500, "rendah", date(2026, 10, 14)))
        self.assertEqual((got.merchant, got.engine), ("Toko", "rapidocr"))
        self.assertEqual((got.ocr_lines, got.merchant_key, got.total_label), (None, None, None))
        self.assertNotIn("receipt", got.document)
        self.assertEqual(got.document["lines"], [])

    async def test_account_number_text_without_rp_is_a_digit_free_unknown_document(self):
        """Teks yang tidak dikenali siapa pun dan bukan bukti bayar (nomor rekening di baris biasa) dulu bisa jadi
        struk belanja yang menyimpan teksnya 24 jam dan menamai merchant dari baris itu. Kini: tidak_dikenali, tanpa
        teks OCR, dan deret digitnya tidak ada di kolom mana pun (dokumen, merchant, kunci pihak, teks, HMAC)."""
        item = await self.item(text="rekening")
        self.assertEqual(await self.process(item, ["Rek BCA 1234567890", "a.n. BUDI", "150.000"]), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, int(got.parsed_total), got.confidence), ("tidak_dikenali", 150000, "rendah"))
        self.assertIsNone(got.ocr_lines)
        columns = [got.document, got.merchant, got.counterparty_key, got.ocr_lines, got.ref_hash, got.merchant_key,
                   got.total_label, got.error]
        self.assertNotIn("1234567890", json.dumps(columns).replace(" ", ""))
        self.assertEqual((got.merchant, got.counterparty_key), ("A.N. Budi", "nama:an budi|"))   # nama saja (aturan A7)
        async with self.Session() as db:
            rows = (await db.execute(select(HouseholdMerchant.raw_name, HouseholdMerchant.counterparty_key))).all()
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(re.search(r"\d{8}", " ".join(row)), row)

    async def test_digit_heavy_guessed_name_is_dropped_before_it_becomes_a_merchant(self):
        item = await self.item(text="telepon")
        self.assertEqual(await self.process(item, ["Toko Sembako Berkah Makmur 081234567", "45.500"]), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, int(got.parsed_total)), ("tidak_dikenali", 45500))
        self.assertEqual((got.merchant, got.counterparty_key, got.ocr_lines), (None, None, None))
        self.assertEqual(await self.count_merchants(), 0)

    async def test_unread_proof_text_without_rp_is_guessed_low_but_keeps_no_text_and_no_merchant(self):
        """Bukti bayar yang jatuh ke pembaca cadangan lewat tebakan struk lama (tanpa "Rp", saklar mati) tetap dijaga:
        tanpa teks OCR dan tanpa peta merchant ("Pembayaran Berhasil" bukan merchant). Saklar menyala: pembaca QRIS menang."""
        lines = [re.sub(r"(?i)\brp\s*", "", ln) for ln in next(c for c in CORPUS if c["id"] == "sint-qris-1")["lines"]]
        item = await self.item(text="qris tanpa rp")
        self.assertEqual(await self.process(item, lines, proofs_enabled=False), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, int(got.parsed_total), got.confidence),
                         ("tidak_dikenali", "tidak_dikenali", 25000, "rendah"))
        self.assertIsNone(got.ocr_lines)
        self.assertEqual(await self.count_merchants(), 0)   # "Pembayaran Berhasil" bukan merchant (penjaga `unread_proof`)
        blob = json.dumps([got.document, got.ocr_lines, got.counterparty_key, got.ref_hash]).replace(" ", "")
        for number in ("ID1024358806544", "612345678812"):
            self.assertNotIn(number, blob)
        on = await self.item(text="qris tanpa rp, saklar menyala")
        self.assertEqual(await self.process(on, lines, proofs_enabled=True), "siap")
        self.assertEqual((await self.get(on.id)).doc_type, "qris")

    async def test_llm_rescue_is_struk_belanja_by_doc_type_not_by_reader_name(self):
        item = await self.item(data=JPG)
        llm = AsyncMock(return_value={"merchant": "Kedai Maju", "date": date(2026, 10, 20), "total": 12000})
        with patch.object(worker, "try_llm_fallback", llm):
            status = await self.process(item, ["kabur", "tak terbaca"])
        self.assertEqual(status, "siap")
        llm.assert_awaited_once_with(JPG, "image/jpeg", self.user_id, "basic")
        got = await self.get(item.id)
        self.assertEqual((got.doc_type, got.parser, got.engine, int(got.parsed_total)), ("struk_belanja", "tidak_dikenali", "llm", 12000))
        self.assertEqual((got.merchant, got.merchant_key, got.parsed_date), ("Kedai Maju", "KEDAIMAJU", date(2026, 10, 20)))
        self.assertEqual(json.loads(got.ocr_lines), ["kabur", "tak terbaca"])
        self.assertEqual(got.document["receipt"]["confidence_source"], "llm")
        self.assertEqual(got.counterparty_key, "nama:kedai maju|")

    async def test_context_carries_image_only_for_images(self):
        seen = []
        real = worker.read_document

        async def spy(doc, ctx, *, proofs_enabled):
            seen.append(ctx)
            return await real(doc, ctx, proofs_enabled=proofs_enabled)

        image, text = await self.item(data=JPG), await self.item(text="teks")
        with patch.object(worker, "read_document", spy):
            await self.process(image, STORE_LINES)
            await self.process(text, STORE_LINES, extract=fake_extract(STORE_LINES, "text"))
        img_ctx, txt_ctx = seen
        self.assertEqual((img_ctx.image, img_ctx.content_type, img_ctx.llm), (JPG, "image/jpeg", worker.try_llm_fallback))
        self.assertEqual((img_ctx.user_id, img_ctx.plan, img_ctx.user_name, img_ctx.today), (self.user_id, "basic", "Rina Wulandari", date(2026, 10, 26)))
        self.assertEqual((txt_ctx.image, txt_ctx.content_type, txt_ctx.llm), (None, None, None))

    async def test_pdf_context_has_no_image(self):
        seen = []
        real = worker.read_document

        async def spy(doc, ctx, *, proofs_enabled):
            seen.append(ctx)
            return await real(doc, ctx, proofs_enabled=proofs_enabled)

        item = await self.item(text="pdf", content_type="application/pdf")
        with patch.object(worker, "read_document", spy):
            await self.process(item, STORE_LINES)
        self.assertEqual((seen[0].image, seen[0].content_type, seen[0].llm), (None, None, None))

    async def test_learning_data_reaches_the_context(self):
        from app.models.models import ReceiptMerchantAlias, ReceiptTotalLabel
        async with self.Session() as db:
            db.add_all([ReceiptMerchantAlias(raw_key="ALFAMRT", merchant="Alfamart", hits=2),
                        ReceiptTotalLabel(merchant_key="ALFAMART", label="TOTAL BELANJA", hits=2)])
            await db.commit()
        seen = []
        real = worker.read_document

        async def spy(doc, ctx, *, proofs_enabled):
            seen.append(ctx)
            return await real(doc, ctx, proofs_enabled=proofs_enabled)

        with patch.object(worker, "read_document", spy):
            await self.process(await self.item(text="belajar"), STORE_LINES)
        self.assertEqual(seen[0].merchant_aliases, {"ALFAMRT": "Alfamart"})
        self.assertEqual(seen[0].merchant_profiles, {"ALFAMART": ["TOTAL BELANJA"]})

    async def test_merchant_map_updates_instead_of_duplicating(self):
        first = await self.item(text="satu")
        await self.process(first)
        second = await self.item(text="dua")
        later = NOW + timedelta(days=1)
        await self.process(second, [l.replace("SITI AMINAH", "SITI AMINAH BARU") for l in CORPUS[0]["lines"]], now=later)
        self.assertEqual(await self.count_merchants(), 1)
        self.assertEqual((await self.merchant("nmid:ID1024358806544")).raw_name, "SITI AMINAH BARU")

    async def test_merchant_map_failure_does_not_fail_the_item(self):
        item = await self.item(text="x")
        with patch.object(worker, "upsert_household_merchant", AsyncMock(side_effect=RuntimeError("peta rusak"))):
            with self.assertLogs("app.services.kotak_struk.worker", "WARNING"):
                self.assertEqual(await self.process(item), "siap")
        got = await self.get(item.id)
        self.assertEqual((got.status, got.doc_type, got.file_path), ("siap", "qris", None))
        self.assertEqual(await self.count_merchants(), 0)

    async def test_household_less_user_gets_no_merchant_row(self):
        item = await self.item(text="x")
        await self.set(item.id, household_id=None)
        self.assertEqual(await self.process(item), "siap")
        got = await self.get(item.id)
        self.assertEqual(got.counterparty_key, "nmid:ID1024358806544")
        self.assertEqual(await self.count_merchants(), 0)

    async def test_finished_item_is_announced(self):
        item = await self.item(text="x")
        await self.process(item)
        self.publish.assert_awaited_once_with(item.id, "siap")

    # --- process_item: saklar fitur -----------------------------------

    async def test_flag_decides_whether_proof_readers_run(self):
        off, on = await self.item(text="mati"), await self.item(text="nyala")
        await self.process(off, proofs_enabled=None)
        self.assertNotEqual((await self.get(off.id)).doc_type, "qris")
        await self.enable_proofs(True)
        await self.process(on, proofs_enabled=None)
        self.assertEqual((await self.get(on.id)).doc_type, "qris")

    # --- process_item: kegagalan --------------------------------------

    async def test_extract_error_subclass_message_is_stored_as_is(self):
        item = await self.item(text="x")
        await self.process(item, extract=AsyncMock(side_effect=ExtractError("Pesan khusus")))
        self.assertEqual((await self.get(item.id)).error, "Pesan khusus")

    async def test_unexpected_error_requeues_until_attempts_run_out(self):
        item = await self.item(text="x", status="diproses", attempts=1)
        boom = AsyncMock(side_effect=RuntimeError("meledak"))
        with self.assertLogs("app.services.kotak_struk.worker", "ERROR"):
            self.assertEqual(await self.process(item, extract=boom), "diterima")
        got = await self.get(item.id)
        self.assertEqual((got.status, got.error), ("diterima", None))
        self.assertTrue(Path(got.file_path).exists())
        self.publish.assert_not_awaited()

        await self.set(item.id, status="diproses", attempts=3)
        with self.assertLogs("app.services.kotak_struk.worker", "ERROR"):
            self.assertEqual(await self.process(item, extract=boom), "gagal")
        got = await self.get(item.id)
        self.assertEqual((got.status, got.error, got.file_path), ("gagal", MSG_UNREADABLE, None))
        self.assertEqual(os.listdir(self.kotak), [])
        self.publish.assert_awaited_once_with(item.id, "gagal")

    async def test_missing_file_fails_without_retry(self):
        item = await self.item(text="x")
        os.unlink((await self.get(item.id)).file_path)
        with self.assertLogs("app.services.kotak_struk.worker", "WARNING"):
            self.assertEqual(await self.process(item), "gagal")
        got = await self.get(item.id)
        self.assertEqual((got.status, got.error, got.file_path), ("gagal", MSG_UNREADABLE, None))

    async def test_item_that_is_no_longer_waiting_is_left_alone(self):
        item = await self.item(text="x", status="dilewati")
        extract = fake_extract(CORPUS[0]["lines"])
        self.assertEqual(await self.process(item, extract=extract), "dilewati")
        extract.assert_not_awaited()
        self.assertEqual((await self.get(item.id)).status, "dilewati")
        self.publish.assert_not_awaited()

    async def test_unknown_item_id_is_not_an_error(self):
        import uuid
        with self.assertLogs("app.services.kotak_struk.worker", "WARNING"):
            status = await process_item(uuid.uuid4(), session_factory=self.Session, extract=fake_extract([]), now=NOW)
        self.assertEqual(status, "hilang")

    async def test_item_skipped_while_reading_is_not_overwritten(self):
        item = await self.item(text="x")

        async def slow_extract(data, content_type):
            await self.set(item.id, status="dilewati")
            return TextDoc(lines=CORPUS[0]["lines"], kind="text")

        self.assertEqual(await self.process(item, extract=slow_extract), "dilewati")
        got = await self.get(item.id)
        self.assertEqual((got.status, got.doc_type, got.file_path), ("dilewati", None, None))
        self.assertEqual(os.listdir(self.kotak), [])

    # --- process_item: kabar ke kanal ---------------------------------

    async def test_notify_flag_calls_bot_hook(self):
        item = await self.item(text="x", channel_meta={"chat_id": 7, "notify": True})
        fake = types.SimpleNamespace(send_ready_message=AsyncMock())
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": fake}):
            await self.process(item)
        fake.send_ready_message.assert_awaited_once_with(item.id)

    async def test_notify_also_fires_when_reading_failed(self):
        item = await self.item(text="x", channel_meta={"chat_id": 7, "notify": True})
        fake = types.SimpleNamespace(send_ready_message=AsyncMock())
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": fake}):
            await self.process(item, extract=AsyncMock(side_effect=PdfLocked()))
        fake.send_ready_message.assert_awaited_once_with(item.id)

    async def test_no_notify_flag_no_hook(self):
        item = await self.item(text="x", channel_meta={"chat_id": 7})
        fake = types.SimpleNamespace(send_ready_message=AsyncMock())
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": fake}):
            await self.process(item)
        fake.send_ready_message.assert_not_awaited()

    async def test_missing_or_failing_bot_hook_never_breaks_the_worker(self):
        item = await self.item(text="x", channel_meta={"notify": True})
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": types.SimpleNamespace()}):  # tanpa send_ready_message
            with self.assertLogs("app.services.kotak_struk.worker", "WARNING"):
                self.assertEqual(await self.process(item), "siap")
        item = await self.item(text="y", channel_meta={"notify": True})
        fake = types.SimpleNamespace(send_ready_message=AsyncMock(side_effect=RuntimeError("telegram mati")))
        with patch.dict(sys.modules, {"app.bot.receipt_cmd": fake}):
            with self.assertLogs("app.services.kotak_struk.worker", "WARNING"):
                self.assertEqual(await self.process(item), "siap")
        self.assertEqual((await self.get(item.id)).status, "siap")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RunWorkerTests(WorkerBase):
    async def run_until(self, predicate, **kw):
        stop = asyncio.Event()
        task = asyncio.create_task(run_worker(stop, session_factory=self.Session, poll_s=0.05, **kw))
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if await predicate():
                    break
                await asyncio.sleep(0.05)
        finally:
            stop.set()
            await asyncio.wait_for(task, 3)

    async def test_loop_processes_waiting_items_and_stops_promptly(self):
        a, b = await self.item(text="Transfer berhasil ke Budi"), await self.item(text="halo dunia")

        async def both_done():
            return [(await self.get(i.id)).status for i in (a, b)] == ["siap", "siap"]

        await self.run_until(both_done)
        for i in (a, b):
            got = await self.get(i.id)
            self.assertEqual((got.status, got.attempts, got.file_path), ("siap", 1, None))

    async def test_wake_makes_a_new_item_start_without_waiting_for_the_poll(self):
        stop = asyncio.Event()
        task = asyncio.create_task(run_worker(stop, session_factory=self.Session, poll_s=30))
        try:
            await asyncio.sleep(0.2)  # loop menganggur menunggu wake()
            item = await self.item(text="baru masuk")  # create_item memanggil worker.wake()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (await self.get(item.id)).status != "siap":
                await asyncio.sleep(0.05)
            self.assertEqual((await self.get(item.id)).status, "siap")
        finally:
            stop.set()
            await asyncio.wait_for(task, 3)

    async def test_startup_recovers_stale_item_then_processes_it(self):
        item = await self.item(text="macet")
        await self.set(item.id, status="diproses", attempts=1, processed_at=datetime.now(timezone.utc) - timedelta(minutes=30))

        async def done():
            return (await self.get(item.id)).status == "siap"

        await self.run_until(done)
        self.assertEqual((await self.get(item.id)).status, "siap")

    async def test_loop_survives_a_failing_database_round(self):
        item = await self.item(text="tahan banting")
        calls = {"n": 0}
        real = worker.claim_next

        async def flaky(db, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("db putus")
            return await real(db, **kw)

        async def done():
            return (await self.get(item.id)).status == "siap"

        with patch.object(worker, "claim_next", flaky), self.assertLogs("app.services.kotak_struk.worker", "ERROR"):
            await self.run_until(done)
        self.assertEqual((await self.get(item.id)).status, "siap")

    async def test_item_that_keeps_failing_ends_gagal_after_max_attempts(self):
        item = await self.item(text="rusak")

        async def done():
            return (await self.get(item.id)).status == "gagal"

        boom = AsyncMock(side_effect=RuntimeError("meledak"))
        with patch.object(worker, "extract_text", boom), self.assertLogs("app.services.kotak_struk.worker", "ERROR"):
            await self.run_until(done)
        got = await self.get(item.id)
        self.assertEqual((got.status, got.attempts, got.error, got.file_path), ("gagal", 3, MSG_UNREADABLE, None))

    def test_wake_before_the_loop_exists_is_harmless(self):
        worker.wake()


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class MerchantUpsertTests(WorkerBase):
    async def test_creates_then_updates_in_place(self):
        async with self.Session() as db:
            row = await upsert_household_merchant(db, self.hh_id, "nama:warung|bandung", "WARUNG", "BANDUNG", now=NOW)
            await db.commit()
            first_id = row.id
        async with self.Session() as db:
            row = await upsert_household_merchant(db, self.hh_id, "nama:warung|bandung", "Warung Baru", None, now=NOW + timedelta(days=2))
            await db.commit()
        got = await self.merchant("nama:warung|bandung")
        self.assertEqual((got.id, got.raw_name, got.city), (first_id, "Warung Baru", "BANDUNG"))  # kota lama tidak dihapus oleh None
        self.assertEqual(got.last_seen_at.replace(tzinfo=timezone.utc), NOW + timedelta(days=2))
        self.assertEqual(await self.count_merchants(), 1)

    async def test_display_name_is_never_touched(self):
        async with self.Session() as db:
            await upsert_household_merchant(db, self.hh_id, "k", "A", None, now=NOW)
            await db.commit()
        async with self.Session() as db:
            await db.execute(update(HouseholdMerchant).values(display_name="Warung Langganan"))
            await db.commit()
        async with self.Session() as db:
            await upsert_household_merchant(db, self.hh_id, "k", "B", "Solo", now=NOW)
            await db.commit()
        got = await self.merchant("k")
        self.assertEqual((got.raw_name, got.display_name, got.city), ("B", "Warung Langganan", "Solo"))

    async def test_long_names_are_cut_to_column_size(self):
        async with self.Session() as db:
            await upsert_household_merchant(db, self.hh_id, "k", "N" * 300, "K" * 300, now=NOW)
            await db.commit()
        got = await self.merchant("k")
        self.assertEqual((len(got.raw_name), len(got.city)), (100, 60))

    async def test_name_missing_on_first_sight_is_stored_empty_and_filled_later(self):
        async with self.Session() as db:
            await upsert_household_merchant(db, self.hh_id, "nmid:X", None, None, now=NOW)
            await db.commit()
        self.assertEqual((await self.merchant("nmid:X")).raw_name, "")
        async with self.Session() as db:
            await upsert_household_merchant(db, self.hh_id, "nmid:X", "TOKO X", None, now=NOW)
            await db.commit()
        self.assertEqual((await self.merchant("nmid:X")).raw_name, "TOKO X")

    async def test_lost_insert_race_falls_back_to_update(self):
        async with self.Session() as db:
            real_get = merchants._find_merchant
            calls = {"n": 0}

            async def blind_first(*a, **kw):
                calls["n"] += 1
                if calls["n"] == 1:  # baris yang sama baru dibuat pihak lain: pencarian pertama tidak melihatnya
                    return None
                return await real_get(*a, **kw)

            async with self.Session() as other:
                await upsert_household_merchant(other, self.hh_id, "k", "PERTAMA", None, now=NOW)
                await other.commit()
            with patch.object(merchants, "_find_merchant", blind_first):
                row = await upsert_household_merchant(db, self.hh_id, "k", "KEDUA", None, now=NOW)
                await db.commit()
        self.assertEqual((row.raw_name, await self.count_merchants()), ("KEDUA", 1))


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class FeatureEnabledTests(WorkerBase):
    async def enabled(self, name="receipt_inbox", platform="web"):
        async with self.Session() as db:
            return await feature_enabled(db, name, platform)

    async def test_default_without_setting(self):
        self.assertIs(await self.enabled(), FEATURES["receipt_inbox"])
        self.assertFalse(await self.enabled())

    async def test_override_per_platform_and_plain_bool(self):
        async with self.Session() as db:
            db.add(AppSetting(key="app_config", value=json.dumps(
                {"features": {"receipt_inbox": {"web": True, "android": False}, "push": True}})))
            await db.commit()
        self.assertTrue(await self.enabled("receipt_inbox", "web"))
        self.assertFalse(await self.enabled("receipt_inbox", "android"))
        self.assertFalse(await self.enabled("receipt_inbox", "ios"))  # platform tanpa nilai: bawaan
        self.assertTrue(await self.enabled("push", "ios"))

    async def test_broken_setting_or_database_falls_back_to_default(self):
        async with self.Session() as db:
            db.add(AppSetting(key="app_config", value="{bukan json"))
            await db.commit()
        with self.assertLogs("app.services.app_config", "WARNING"):
            self.assertFalse(await self.enabled())
        db = AsyncMock()
        db.execute.side_effect = ConnectionError("db putus")
        with self.assertLogs("app.services.app_config", "WARNING"):
            self.assertFalse(await feature_enabled(db, "receipt_inbox"))

    async def test_unknown_feature_is_off(self):
        self.assertFalse(await self.enabled("tidak_ada"))


# --- penunggu -----------------------------------------------------------

class FakePubSub:
    def __init__(self, *, messages=(), on_subscribe=None, on_get=None, fail_subscribe=False, fail_get=False):
        self.messages, self.on_subscribe, self.on_get = list(messages), on_subscribe, on_get
        self.fail_subscribe, self.fail_get = fail_subscribe, fail_get
        self.subscribed, self.closed = [], False

    async def subscribe(self, channel):
        if self.fail_subscribe:
            raise ConnectionError("redis mati")
        self.subscribed.append(channel)
        if self.on_subscribe:
            await self.on_subscribe()

    async def get_message(self, ignore_subscribe_messages=False, timeout=0.0):
        if self.fail_get:
            raise ConnectionError("redis putus")
        if self.on_get:
            await self.on_get()
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(timeout)
        return None

    async def aclose(self):
        self.closed = True


class FakeRedisClient:
    def __init__(self, pubsub=None, *, fail_publish=False):
        self._pubsub, self.fail_publish = pubsub, fail_publish
        self.published, self.closed = [], False

    def pubsub(self):
        return self._pubsub

    async def publish(self, channel, message):
        if self.fail_publish:
            raise ConnectionError("redis putus")
        self.published.append((channel, message))
        return 1

    async def aclose(self):
        self.closed = True


def message(status="siap"):
    return {"type": "message", "channel": b"kotak:done:x", "data": status.encode()}


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class WaiterTests(WorkerBase):
    patch_publish = False

    async def wait(self, item, timeout, client=None, **kw):
        return await wait_for_item(item.id, timeout, session_factory=self.Session,
                                   redis_factory=(lambda: client) if client else broken_redis, **kw)

    # --- brief ---

    async def test_wait_returns_final_item_and_falls_back_to_db_poll(self):
        item = await self.item(text="x")
        await self.set(item.id, status="siap")
        got = await wait_for_item(item.id, 1, session_factory=self.Session, redis_factory=broken_redis)
        self.assertEqual(got.status, "siap")
        item2 = await self.item(text="y")
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            got2 = await wait_for_item(item2.id, 0.3, session_factory=self.Session, redis_factory=broken_redis, poll_s=0.1)
        self.assertEqual(got2.status, "diterima")

    # --- DB lebih dulu, Redis sesudahnya ---

    async def test_final_item_is_returned_without_touching_redis(self):
        item = await self.item(text="x", status="gagal")
        made = []
        got = await wait_for_item(item.id, 5, session_factory=self.Session, redis_factory=lambda: made.append(1))
        self.assertEqual((got.status, made), ("gagal", []))

    async def test_unknown_item_returns_none(self):
        import uuid
        self.assertIsNone(await wait_for_item(uuid.uuid4(), 1, session_factory=self.Session, redis_factory=broken_redis))

    async def test_db_poll_picks_up_completion_when_redis_is_down(self):
        item = await self.item(text="x", status="diproses")

        async def finish_later():
            await asyncio.sleep(0.25)
            await self.set(item.id, status="siap")

        task = asyncio.create_task(finish_later())
        started = time.monotonic()
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            got = await self.wait(item, 5, poll_s=0.1)
        await task
        self.assertEqual(got.status, "siap")
        self.assertLess(time.monotonic() - started, 2)

    async def test_message_wakes_the_waiter(self):
        item = await self.item(text="x", status="diproses")

        async def finish():  # worker menulis hasil lalu mem-publish
            await self.set(item.id, status="siap")

        ps = FakePubSub(messages=[message()], on_get=finish)
        client = FakeRedisClient(ps)
        started = time.monotonic()
        got = await self.wait(item, 5, client)
        self.assertEqual(got.status, "siap")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(ps.subscribed, [f"kotak:done:{item.id}"])
        self.assertTrue(ps.closed and client.closed)

    async def test_completion_between_first_check_and_subscribe_is_not_missed(self):
        item = await self.item(text="x", status="diproses")

        async def finish():  # selesai tepat setelah cek DB pertama, sebelum langganan aktif: tidak ada pesan
            await self.set(item.id, status="siap")

        ps = FakePubSub(on_subscribe=finish)
        client = FakeRedisClient(ps)
        started = time.monotonic()
        got = await self.wait(item, 10, client)
        self.assertEqual(got.status, "siap")
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(ps.closed and client.closed)

    async def test_timeout_returns_latest_db_state_and_closes_connections(self):
        item = await self.item(text="x", status="diproses")
        ps = FakePubSub()
        client = FakeRedisClient(ps)
        started = time.monotonic()
        got = await self.wait(item, 0.3, client)
        self.assertEqual(got.status, "diproses")
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(ps.closed and client.closed)

    async def test_missed_message_is_caught_by_the_periodic_db_check(self):
        item = await self.item(text="x", status="diproses")
        ps = FakePubSub()
        client = FakeRedisClient(ps)

        async def finish_silently():
            await asyncio.sleep(0.2)
            await self.set(item.id, status="siap")  # publish hilang

        task = asyncio.create_task(finish_silently())
        with patch.object(waiter, "REDIS_RECHECK_S", 0.1):
            got = await self.wait(item, 5, client)
        await task
        self.assertEqual(got.status, "siap")

    async def test_redis_failing_midway_falls_back_to_polling(self):
        item = await self.item(text="x", status="diproses")
        ps = FakePubSub(fail_get=True)
        client = FakeRedisClient(ps)

        async def finish_later():
            await asyncio.sleep(0.25)
            await self.set(item.id, status="siap")

        task = asyncio.create_task(finish_later())
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            got = await self.wait(item, 5, client, poll_s=0.1)
        await task
        self.assertEqual(got.status, "siap")
        self.assertTrue(ps.closed and client.closed)

    async def test_subscribe_failure_closes_the_client_and_polls(self):
        item = await self.item(text="x", status="diproses")
        ps = FakePubSub(fail_subscribe=True)
        client = FakeRedisClient(ps)
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            got = await self.wait(item, 0.3, client, poll_s=0.1)
        self.assertEqual(got.status, "diproses")
        self.assertTrue(ps.closed and client.closed)

    async def test_cancelled_waiter_still_closes_connections(self):
        item = await self.item(text="x", status="diproses")
        ps = FakePubSub()
        client = FakeRedisClient(ps)
        task = asyncio.create_task(self.wait(item, 30, client))
        await asyncio.sleep(0.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(ps.closed and client.closed)

    # --- publish_done ---

    async def test_publish_done_sends_status_on_the_item_channel_and_closes(self):
        client = FakeRedisClient()
        import uuid
        item_id = uuid.uuid4()
        await publish_done(item_id, "siap", redis_factory=lambda: client)
        self.assertEqual(client.published, [(f"kotak:done:{item_id}", "siap")])
        self.assertTrue(client.closed)

    async def test_publish_done_swallows_errors(self):
        import uuid
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            await publish_done(uuid.uuid4(), "siap", redis_factory=broken_redis)
        client = FakeRedisClient(fail_publish=True)
        with self.assertLogs("app.services.kotak_struk.waiter", "WARNING"):
            await publish_done(uuid.uuid4(), "siap", redis_factory=lambda: client)
        self.assertTrue(client.closed)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class LifespanTests(unittest.IsolatedAsyncioTestCase):
    """Worker dijalankan dan dihentikan oleh `lifespan` API (tes lain yang mengimpor app.main tidak menjalankannya)."""

    @contextlib.asynccontextmanager
    async def lifespan(self, fake_run):
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))  # lifespan mencetak banner
                stack.enter_context(patch("app.core.database.engine", engine))
                stack.enter_context(patch("app.main.start_scheduler"))
                stack.enter_context(patch("app.main.stop_scheduler"))
                stack.enter_context(patch("app.services.advisor.advisor_cache.install"))
                stack.enter_context(patch.object(worker, "run_worker", fake_run))
                async with lifespan(app):
                    yield
        finally:
            await engine.dispose()

    async def test_worker_starts_with_the_api_and_stops_on_shutdown(self):
        events = []

        async def fake_run(stop):
            events.append("start")
            await stop.wait()
            events.append("stop")

        async with self.lifespan(fake_run):
            await asyncio.sleep(0.05)
            self.assertEqual(events, ["start"])
        self.assertEqual(events, ["start", "stop"])

    async def test_a_worker_that_died_does_not_break_shutdown(self):
        async def fake_run(stop):
            raise RuntimeError("worker mati")

        with self.assertLogs("app.main", "ERROR"):
            async with self.lifespan(fake_run):
                await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
