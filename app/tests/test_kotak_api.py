"""API Kotak Struk: unggah, daftar, detail, saran, lewati, nama merchant, dan `soft_duplicate`
(SQLite in-memory; klien httpx langsung ke ASGI supaya satu event loop dengan mesin async).
Run: python -m unittest app.tests.test_kotak_api -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import shutil
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select, update
from sqlalchemy.orm import configure_mappers

from app.api.routes import kotak_struk as kotak_route
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.models.models import (
    Envelope, Household, HouseholdMember, HouseholdMerchant, HouseholdRole, MerchantEnvelopeMap, ReceiptScan,
    Transaction, User,
)
from app.services.kotak_struk import intake as intake_mod, merchants, waiter
from app.services.kotak_struk.dedup import soft_duplicate
from app.services.kotak_struk.extract import TextDoc
from app.services.kotak_struk.intake import IntakeRequest, create_item
from app.services.kotak_struk.record import claim_for_recording
from app.services.kotak_struk.view import item_detail
from app.services.kotak_struk.worker import process_item

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
CORPUS = json.loads((Path(__file__).parent / "fixtures" / "kotak" / "corpus.json").read_text())["samples"]
JPG = b"\xff\xd8\xff\xe0jpeg"
NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)
PAID = datetime(2026, 10, 26, 1, 12, 33, tzinfo=timezone.utc)   # 08:12 WIB; SQLite menyimpan jam dinding apa adanya
QRIS_KEY = "nmid:ID1024358806544"
NO_FLAGS = {"duplicate_of": None, "skip_suggestion": None, "blocked": None, "warnings": []}


class FakeRedis:
    def __init__(self):
        self.counts = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        return True

    async def aclose(self):
        pass


def fake_extract(lines, kind="image"):
    return AsyncMock(return_value=TextDoc(lines=list(lines), kind=kind))


class ApiBase(unittest.IsolatedAsyncioTestCase):
    """Database, klien, dan pembantu bersama (tanpa tes sendiri)."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        # Worker sungguhan membaca bukti di thread loop; mode debug asyncio mengeluh bila satu langkah > 0,1 detik.
        asyncio.get_running_loop().slow_callback_duration = 2.0
        self.dir = tempfile.mkdtemp()
        self.kotak = os.path.join(self.dir, "kotak")
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT terluar butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.statements = []   # semua SQL yang dijalankan (tes GET tanpa tulis)
        event.listen(self.engine.sync_engine, "before_cursor_execute",
                     lambda conn, cur, statement, *_a: self.statements.append(statement))

        async with self.Session() as db:
            self.a, self.b = User(name="Ani"), User(name="Budi")
            self.hh, self.other_hh = Household(name="Rumah"), Household(name="Rumah Lain")
            db.add_all([self.a, self.b, self.hh, self.other_hh])
            await db.flush()
            db.add_all([HouseholdMember(user_id=self.a.id, household_id=self.hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=self.b.id, household_id=self.hh.id, role=HouseholdRole.member)])
            self.env = {}
            for name, extra in [("Makan", {}), ("Jajan", {}), ("Pribadi B", {"owner_id": self.b.id})]:
                self.env[name] = Envelope(household_id=self.hh.id, name=name, **extra)
            db.add_all(self.env.values())
            await db.commit()

        app = FastAPI()
        app.include_router(kotak_route.router, prefix="/kotak-struk")
        app.dependency_overrides[get_current_user] = lambda: self.a

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.c.aclose)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

        settings = types.SimpleNamespace(KOTAK_DIR=self.kotak, REDIS_URL="redis://tes")
        for p in (patch("app.services.kotak_struk.intake.get_settings", return_value=settings),
                  patch("redis.asyncio.from_url", return_value=FakeRedis()),
                  patch.object(merchants, "_warned_no_key", True),
                  patch.object(waiter, "publish_done", new_callable=AsyncMock)):
            p.start()
            self.addCleanup(p.stop)

    # --- pembantu ------------------------------------------------------

    async def ready(self, lines, owner=None, paid_at=PAID):
        """Item `siap` milik `owner` lewat intake + worker sungguhan dengan hasil OCR palsu."""
        owner = owner or self.a
        async with self.Session() as db:
            user = await db.get(User, owner.id)
            req = IntakeRequest(user, "pwa_share", data=JPG + uuid4().bytes, content_type="image/jpeg")
            item, _ = await create_item(db, req, redis=FakeRedis(), kotak_dir=self.kotak, now=NOW)
        status = await process_item(item.id, session_factory=self.Session, extract=fake_extract(lines), now=NOW,
                                    proofs_enabled=True)
        self.assertEqual(status, "siap")
        if paid_at is not None:
            await self.set(item.id, paid_at=paid_at)
        return item

    async def ready_qris(self, owner=None):
        """QRIS SITI AMINAH Rp25.000; peta merchant rumah tangga: Makan x1."""
        item = await self.ready(CORPUS[0]["lines"], owner)
        mid = await self.merchant_id(QRIS_KEY)
        async with self.Session() as db:
            has_map = (await db.execute(select(MerchantEnvelopeMap).where(
                MerchantEnvelopeMap.merchant_id == mid))).first()
            if has_map is None:
                db.add(MerchantEnvelopeMap(merchant_id=mid, envelope_id=self.env["Makan"].id, count=1,
                                           last_used_at=NOW))
                await db.commit()
        return item

    async def ready_transfer(self, lines, owner=None):
        return await self.ready(lines, owner)

    async def set(self, item_id, **cols):
        async with self.Session() as db:
            await db.execute(update(ReceiptScan).where(ReceiptScan.id == item_id).values(**cols))
            await db.commit()

    async def get(self, item_id):
        async with self.Session() as db:
            return await db.get(ReceiptScan, item_id)

    async def merchant_id(self, key):
        async with self.Session() as db:
            return (await db.execute(select(HouseholdMerchant.id).where(
                HouseholdMerchant.household_id == self.hh.id, HouseholdMerchant.counterparty_key == key))).scalar_one()

    async def other_household_merchant(self):
        async with self.Session() as db:
            row = HouseholdMerchant(household_id=self.other_hh.id, counterparty_key="nama:toko lain|", raw_name="TOKO LAIN",
                                    last_seen_at=NOW, created_at=NOW)
            db.add(row)
            await db.commit()
            return row.id

    async def add_txn(self, *, amount, description, created_at, on, user=None, envelope="Makan", private=False,
                      deleted=False, household=None):
        async with self.Session() as db:
            env_id = self.env[envelope].id
            if household is not None:   # amplop di rumah tangga lain
                other = Envelope(household_id=household, name="Lain")
                db.add(other)
                await db.flush()
                env_id = other.id
            txn = Transaction(envelope_id=env_id, user_id=(user or self.a).id, amount=Decimal(amount),
                              description=description, created_at=created_at, transaction_date=on,
                              is_private=private, is_deleted=deleted)
            db.add(txn)
            await db.commit()
            return txn

    async def upload(self, data=None, **form):
        form.setdefault("source", "pwa_share")
        files = {"file": ("a.jpg", JPG + (data or b""), "image/jpeg")}
        return await self.c.post("/kotak-struk/", data=form, files=files)

    async def detail(self, item):
        r = await self.c.get(f"/kotak-struk/{item.id}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class KotakApiTests(ApiBase):
    # --- brief ---------------------------------------------------------

    async def test_upload_then_detail_then_idempotent(self):
        r = await self.c.post("/kotak-struk/", data={"source": "pwa_share", "upload_id": "u1"}, files={"file": ("a.jpg", JPG, "image/jpeg")})
        self.assertEqual((r.status_code, r.json()["status"]), (201, "diterima"))
        again = await self.c.post("/kotak-struk/", data={"source": "pwa_share", "upload_id": "u1"}, files={"file": ("a.jpg", JPG, "image/jpeg")})
        self.assertEqual((again.status_code, again.json()["id"]), (200, r.json()["id"]))

    async def test_bad_type_and_missing_input(self):
        self.assertEqual((await self.c.post("/kotak-struk/", data={"source": "pwa_share"}, files={"file": ("a.html", b"<html>", "text/html")})).status_code, 415)
        self.assertEqual((await self.c.post("/kotak-struk/", data={"source": "pwa_share"})).status_code, 422)

    async def test_ready_item_detail_shape(self):
        item = await self.ready_qris()   # item siap: SITI AMINAH Rp25.000, peta merchant Makan x1
        d = (await self.c.get(f"/kotak-struk/{item.id}")).json()
        self.assertEqual(d["description_preview"], "Siti Aminah (QRIS)")
        self.assertEqual((d["suggestion"]["envelope_name"], d["suggestion"]["confident"]), ("Makan", True))
        self.assertEqual(d["flags"], {"duplicate_of": None, "skip_suggestion": None, "blocked": None, "warnings": []})
        self.assertEqual(d["merchant"]["name"], "Siti Aminah")
        # bentuk lengkap spec 5d
        self.assertEqual(set(d), {"id", "status", "doc_type", "source", "created_at", "paid_at", "document", "merchant",
                                  "suggestion", "description_preview", "flags", "error"})
        self.assertEqual((d["id"], d["status"], d["doc_type"], d["source"], d["error"]),
                         (str(item.id), "siap", "qris", "pwa_share", None))
        self.assertEqual(d["merchant"], {"id": str(await self.merchant_id(QRIS_KEY)), "name": "Siti Aminah", "display_name": None})
        self.assertEqual(d["document"]["amounts"]["total"], 25000)
        self.assertTrue(d["paid_at"].startswith("2026-10-26T01:12:33"))

    async def test_other_users_item_is_404(self):
        item = await self.ready_qris(owner=self.b)
        r = await self.c.get(f"/kotak-struk/{item.id}")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Bukti tidak ditemukan"))

    async def test_saran_with_note(self):
        item = await self.ready_qris()
        d = (await self.c.post(f"/kotak-struk/{item.id}/saran", json={"note": "bakso 2, es teh"})).json()
        self.assertEqual((d["description_preview"], d["suggestion"]["source"]), ("bakso 2, es teh (Siti Aminah)", "note"))
        self.assertEqual(set(d), {"suggestion", "description_preview"})

    async def test_flags_blocked_skip_and_soft_dup(self):
        failed = await self.ready_transfer(CORPUS[3]["lines"])
        self.assertEqual((await self.c.get(f"/kotak-struk/{failed.id}")).json()["flags"]["blocked"], "transaksi_gagal")
        topup = await self.ready_transfer(CORPUS[4]["lines"])
        self.assertEqual((await self.c.get(f"/kotak-struk/{topup.id}")).json()["flags"]["skip_suggestion"], "top_up")
        await self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID + timedelta(hours=2), on=PAID.date())
        dup = (await self.c.get(f"/kotak-struk/{(await self.ready_qris()).id}")).json()["flags"]["duplicate_of"]
        self.assertEqual((dup["kind"], dup["transaction"]["description"]), ("soft", "bakso 25rb"))

    async def test_skip_and_rename_merchant(self):
        item = await self.ready_qris()
        self.assertEqual((await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "bukan_pengeluaran"})).json()["status"], "dilewati")
        mid = await self.merchant_id("nmid:ID1024358806544")
        r = await self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "Warung Bakso Bu Siti<script>"})
        self.assertEqual(r.json()["display_name"], "Warung Bakso Bu Siti")
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{await self.other_household_merchant()}", json={"display_name": "x"})).status_code, 404)

    async def test_list_only_own_ready_items(self):
        mine, theirs = await self.ready_qris(), await self.ready_qris(owner=self.b)
        ids = [i["id"] for i in (await self.c.get("/kotak-struk/?status=siap")).json()["items"]]
        self.assertIn(str(mine.id), ids); self.assertNotIn(str(theirs.id), ids)

    # --- unggah --------------------------------------------------------

    async def test_unknown_source_is_rejected_by_intake(self):
        r = await self.upload(source="faks")
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "Sumber tidak dikenal"))

    async def test_text_upload_creates_item(self):
        r = await self.c.post("/kotak-struk/", data={"source": "web_chat", "text": "Transfer Berhasil\nRp 10.000"})
        self.assertEqual((r.status_code, r.json()["status"], r.json()["source"]), (201, "diterima", "web_chat"))

    async def test_upload_reads_at_most_one_byte_past_the_pdf_limit(self):
        seen = []
        real = kotak_route.create_item

        async def spy(db, req, **kw):
            seen.append(len(req.data))
            return await real(db, req, **kw)

        # Batas dikecilkan supaya tes tidak mengirim belasan MB; yang diuji: rute berhenti membaca di batas + 1.
        with patch.object(kotak_route, "PDF_MAX_BYTES", 1000), patch.object(intake_mod, "PDF_MAX_BYTES", 1000), \
                patch.object(kotak_route, "create_item", spy):
            r = await self.c.post("/kotak-struk/", data={"source": "pwa_share"},
                                  files={"file": ("a.pdf", b"%PDF-1.4" + b"0" * 5000, "application/pdf")})
        self.assertEqual((r.status_code, r.json()["detail"]), (413, "PDF terlalu besar (maks 10 MB)"))
        self.assertEqual(seen, [1001])   # intake yang menolak, rute tidak membaca seluruh isi

    async def test_oversize_image_is_413_from_intake(self):
        with patch.object(intake_mod, "IMAGE_MAX_BYTES", 100):
            r = await self.upload(b"0" * 200)
        self.assertEqual((r.status_code, r.json()["detail"]), (413, "Foto terlalu besar (maks 8 MB)"))

    async def test_wait_returns_the_settled_item(self):
        async def settle(item_id, timeout_s):   # worker selesai selagi rute menunggu
            await process_item(item_id, session_factory=self.Session, extract=fake_extract(CORPUS[0]["lines"]), now=NOW,
                               proofs_enabled=True)

        wait = AsyncMock(side_effect=settle)
        with patch.object(kotak_route, "wait_for_item", wait):
            r = await self.upload(b"x", wait="5")
        self.assertEqual((r.status_code, r.json()["status"], r.json()["doc_type"]), (201, "siap", "qris"))
        self.assertEqual(wait.await_args.args[1], 5)

    async def test_waiting_holds_no_open_transaction_on_the_request_session(self):
        """Item yang sudah ada (upload_id sama) dikembalikan `create_item` dengan transaksi baca masih terbuka. Rute
        meng-commit sebelum menunggu, supaya koneksi permintaan tidak tertahan `idle in transaction` sampai 45 dtk."""
        first = await self.upload(b"m1", upload_id="m1")
        self.assertEqual(first.status_code, 201)
        real, sessions, seen = kotak_route.create_item, [], []

        async def spy(db, req, **kw):
            sessions.append(db)
            return await real(db, req, **kw)

        async def wait(item_id, timeout_s):
            seen.append(sessions[-1].in_transaction())

        with patch.object(kotak_route, "create_item", spy), \
                patch.object(kotak_route, "wait_for_item", AsyncMock(side_effect=wait)):
            again = await self.upload(b"m1", upload_id="m1", wait="1")
            new = await self.upload(b"m2", upload_id="m2", wait="1")
        self.assertEqual((again.status_code, again.json()["id"], new.status_code), (200, first.json()["id"], 201))
        self.assertEqual(seen, [False, False])

    async def test_no_wait_by_default_and_wait_is_bounded(self):
        wait = AsyncMock()
        with patch.object(kotak_route, "wait_for_item", wait):
            self.assertEqual((await self.upload(b"a")).status_code, 201)
            wait.assert_not_awaited()
            self.assertEqual((await self.upload(b"b", wait="46")).status_code, 422)
            self.assertEqual((await self.upload(b"c", upload_id="x" * 65)).status_code, 422)

    # --- detail item ---------------------------------------------------

    async def test_waiting_and_failed_items_have_no_document(self):
        waiting = (await self.upload(b"w")).json()
        self.assertEqual((waiting["status"], waiting["document"], waiting["merchant"], waiting["suggestion"],
                          waiting["description_preview"], waiting["flags"], waiting["error"]),
                         ("diterima", None, None, None, None, NO_FLAGS, None))
        await self.set(UUID(waiting["id"]), status="gagal", error="PDF terkunci kata sandi")
        failed = (await self.c.get(f"/kotak-struk/{waiting['id']}")).json()
        self.assertEqual((failed["status"], failed["error"], failed["document"], failed["suggestion"], failed["flags"]),
                         ("gagal", "PDF terkunci kata sandi", None, None, NO_FLAGS))

    async def test_legacy_scan_history_row_is_not_an_inbox_item(self):
        async with self.Session() as db:
            row = ReceiptScan(user_id=self.a.id)   # riwayat scan lama: status NULL
            db.add(row)
            await db.commit()
        self.assertEqual((await self.c.get(f"/kotak-struk/{row.id}")).status_code, 404)
        self.assertEqual((await self.c.post(f"/kotak-struk/{row.id}/lewati", json={"reason": "batal"})).status_code, 404)

    async def test_merchant_nickname_is_used_in_preview_and_empty_clears_it(self):
        item = await self.ready_qris()
        mid = await self.merchant_id(QRIS_KEY)
        r = await self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "Bakso Bu Siti"})
        self.assertEqual((r.status_code, r.json()), (200, {"id": str(mid), "name": "Siti Aminah", "display_name": "Bakso Bu Siti"}))
        d = await self.detail(item)
        self.assertEqual((d["description_preview"], d["merchant"]["name"], d["merchant"]["display_name"]),
                         ("Bakso Bu Siti (QRIS)", "Siti Aminah", "Bakso Bu Siti"))
        saran = (await self.c.post(f"/kotak-struk/{item.id}/saran", json={"note": "bakso 2"})).json()
        self.assertEqual(saran["description_preview"], "bakso 2 (Bakso Bu Siti)")
        cleared = await self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "<b></b>"})
        self.assertIsNone(cleared.json()["display_name"])
        self.assertEqual((await self.detail(item))["description_preview"], "Siti Aminah (QRIS)")

    async def test_merchant_without_row_falls_back_to_document_name(self):
        item = await self.ready_qris()
        async with self.Session() as db:
            await db.execute(update(HouseholdMerchant).values(counterparty_key="nmid:LAIN"))
            await db.commit()
        self.assertEqual((await self.detail(item))["merchant"], {"id": None, "name": "Siti Aminah", "display_name": None})

    async def test_pending_ref_from_another_member_is_a_warning(self):
        await self.ready_qris(owner=self.b)   # nomor referensi yang sama, belum tercatat
        d = await self.detail(await self.ready_qris())
        self.assertEqual((d["flags"]["duplicate_of"]["kind"], d["flags"]["duplicate_of"]["recorded"]), ("ref", False))
        self.assertEqual((d["flags"]["blocked"], d["flags"]["warnings"]), (None, ["Bukti ini juga dibagikan Budi"]))

    async def test_recorded_duplicate_blocks_and_wins_over_soft(self):
        recorded = await self.ready_qris(owner=self.b)
        await self.set(recorded.id, status="tercatat")
        await self.add_txn(amount=25000, description="bakso", created_at=PAID, on=PAID.date())
        d = await self.detail(await self.ready_qris())
        self.assertEqual((d["flags"]["blocked"], d["flags"]["duplicate_of"]["kind"], d["flags"]["duplicate_of"]["recorded"]),
                         ("sudah_tercatat", "ref", True))

    async def test_recorded_proof_item_is_blocked_but_store_receipt_is_not(self):
        proof = await self.ready_qris()
        await self.set(proof.id, status="tercatat")
        self.assertEqual((await self.detail(proof))["flags"]["blocked"], "sudah_tercatat")
        store = await self.ready(CORPUS[0]["lines"])
        await self.set(store.id, status="tercatat", doc_type="struk_belanja", ref_hash=None, file_sha256="x")
        self.assertIsNone((await self.detail(store))["flags"]["blocked"])

    async def test_warn_checks_become_warnings_and_flow_flags(self):
        item = await self.ready_qris()
        async with self.Session() as db:
            row = await db.get(ReceiptScan, item.id)
            doc = dict(row.document)
            doc["checks"] = [{"code": "bukti_lama", "level": "warn", "message": "Bukti ini lebih dari 60 hari lalu"},
                             {"code": "x", "level": "info", "message": "diabaikan"}]
            doc["flow"] = "masuk"
            row.document = doc
            await db.commit()
        flags = (await self.detail(item))["flags"]
        self.assertEqual((flags["warnings"], flags["skip_suggestion"], flags["blocked"]),
                         (["Bukti ini lebih dari 60 hari lalu"], "masuk", None))
        for flow, expected in [("antar_rekening_sendiri", "antar_rekening_sendiri"), ("keluar", None)]:
            async with self.Session() as db:
                row = await db.get(ReceiptScan, item.id)
                row.document = {**row.document, "flow": flow}
                await db.commit()
            self.assertEqual((await self.detail(item))["flags"]["skip_suggestion"], expected)

    async def test_soft_duplicate_only_for_ready_items(self):
        await self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID, on=PAID.date())
        item = await self.ready_qris()
        self.assertEqual((await self.detail(item))["flags"]["duplicate_of"]["kind"], "soft")
        await self.set(item.id, status="dilewati")
        self.assertIsNone((await self.detail(item))["flags"]["duplicate_of"])

    async def test_household_signals_end_when_the_user_leaves(self):
        item = await self.ready_qris()
        await self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID, on=PAID.date())
        async with self.Session() as db:
            await db.execute(HouseholdMember.__table__.delete().where(HouseholdMember.user_id == self.a.id))
            await db.commit()
        d = await self.detail(item)
        self.assertEqual((d["flags"], d["merchant"]["id"], d["suggestion"]["source"]), (NO_FLAGS, None, "none"))

    async def test_get_endpoints_never_write(self):
        item = await self.ready_qris()
        await self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID, on=PAID.date())
        await self.ready_qris(owner=self.b)
        self.statements.clear()
        self.assertEqual((await self.c.get(f"/kotak-struk/{item.id}")).status_code, 200)
        self.assertEqual((await self.c.get("/kotak-struk/?status=siap")).status_code, 200)
        writes = [s for s in self.statements if s.lstrip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE")]
        self.assertEqual(writes, [])
        self.assertGreater(len(self.statements), 0)

    # --- daftar --------------------------------------------------------

    async def test_list_is_newest_first_filtered_by_status_and_capped(self):
        old, new = await self.ready_qris(), await self.ready_qris()
        await self.set(old.id, created_at=NOW - timedelta(hours=2))
        await self.set(new.id, created_at=NOW)
        failed = await self.ready_transfer(CORPUS[2]["lines"])
        await self.set(failed.id, status="gagal", error="x", created_at=NOW + timedelta(hours=1))
        ids = [i["id"] for i in (await self.c.get("/kotak-struk/?status=siap")).json()["items"]]
        self.assertEqual(ids, [str(new.id), str(old.id)])
        self.assertEqual([i["id"] for i in (await self.c.get("/kotak-struk/?status=gagal")).json()["items"]], [str(failed.id)])
        self.assertEqual((await self.c.get("/kotak-struk/?status=tercatat")).json(), {"items": []})
        self.assertEqual([i["id"] for i in (await self.c.get("/kotak-struk/")).json()["items"]], ids)   # bawaan: siap
        with patch.object(kotak_route, "LIST_LIMIT", 1):
            self.assertEqual(len((await self.c.get("/kotak-struk/?status=siap")).json()["items"]), 1)

    # --- lewati --------------------------------------------------------

    async def test_lewati_stores_reason_and_works_from_gagal(self):
        item = await self.ready_qris()
        await self.set(item.id, channel_meta={"chat_id": 7})
        d = (await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "duplikat"})).json()
        self.assertEqual(d["status"], "dilewati")
        self.assertEqual((await self.get(item.id)).channel_meta, {"chat_id": 7, "skip_reason": "duplikat"})
        failed = await self.ready_transfer(CORPUS[2]["lines"])
        await self.set(failed.id, status="gagal", error="x")
        r = await self.c.post(f"/kotak-struk/{failed.id}/lewati", json={"reason": "batal"})
        self.assertEqual((r.status_code, r.json()["status"], r.json()["error"]), (200, "dilewati", "x"))

    async def test_lewati_refuses_items_that_are_not_siap_or_gagal(self):
        item = await self.ready_qris()
        for status in ("diterima", "diproses", "tercatat", "dilewati", "kedaluwarsa"):
            with self.subTest(status):
                await self.set(item.id, status=status)
                r = await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "batal"})
                self.assertEqual((r.status_code, r.json()["detail"]), (409, "Bukti ini tidak bisa dilewati"))
                self.assertEqual((await self.get(item.id)).status, status)
        self.assertIsNone((await self.get(item.id)).channel_meta)

    async def test_lewati_loses_to_recording_claim(self):
        item = await self.ready_qris()
        async with self.Session() as db:   # pencatatan menang lebih dulu (siap -> tercatat)
            self.assertTrue(await claim_for_recording(db, item.id, self.a.id))
            await db.commit()
        r = await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "batal"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual((await self.get(item.id)).status, "tercatat")
        # sebaliknya: sesudah dilewati, klaim pencatatan tidak lolos
        other = await self.ready_qris()
        self.assertEqual((await self.c.post(f"/kotak-struk/{other.id}/lewati", json={"reason": "batal"})).status_code, 200)
        async with self.Session() as db:
            self.assertFalse(await claim_for_recording(db, other.id, self.a.id))

    async def test_lewati_other_users_item_is_404_and_untouched(self):
        item = await self.ready_qris(owner=self.b)
        r = await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "batal"})
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Bukti tidak ditemukan"))
        self.assertEqual((await self.get(item.id)).status, "siap")

    async def test_lewati_and_saran_validate_input(self):
        item = await self.ready_qris()
        self.assertEqual((await self.c.post(f"/kotak-struk/{item.id}/lewati", json={"reason": "iseng"})).status_code, 422)
        self.assertEqual((await self.c.post(f"/kotak-struk/{item.id}/lewati", json={})).status_code, 422)
        self.assertEqual((await self.c.post(f"/kotak-struk/{item.id}/saran", json={"note": "x" * 201})).status_code, 422)
        self.assertEqual((await self.c.post(f"/kotak-struk/{item.id}/saran", json={})).status_code, 200)
        self.assertEqual((await self.get(item.id)).status, "siap")

    async def test_saran_for_other_users_or_waiting_item(self):
        theirs = await self.ready_qris(owner=self.b)
        self.assertEqual((await self.c.post(f"/kotak-struk/{theirs.id}/saran", json={"note": "x"})).status_code, 404)
        waiting = (await self.upload(b"w")).json()
        d = (await self.c.post(f"/kotak-struk/{waiting['id']}/saran", json={"note": "x"})).json()
        self.assertEqual(d, {"suggestion": None, "description_preview": None})

    # --- nama merchant -------------------------------------------------

    async def test_rename_merchant_validation_and_scope(self):
        await self.ready_qris()
        mid = await self.merchant_id(QRIS_KEY)
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "x" * 61})).status_code, 422)
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{mid}", json={})).status_code, 422)
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{uuid4()}", json={"display_name": "x"})).status_code, 404)
        other = await self.other_household_merchant()
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{other}", json={"display_name": "x"})).status_code, 404)
        async with self.Session() as db:
            self.assertIsNone((await db.get(HouseholdMerchant, other)).display_name)   # tidak tersentuh
        async with self.Session() as db:   # user tanpa rumah tangga
            await db.execute(HouseholdMember.__table__.delete().where(HouseholdMember.user_id == self.a.id))
            await db.commit()
        self.assertEqual((await self.c.put(f"/kotak-struk/merchants/{mid}", json={"display_name": "x"})).status_code, 404)

    async def test_rename_is_visible_to_other_household_members(self):
        mine = await self.ready_qris()
        theirs = await self.ready_qris(owner=self.b)
        await self.c.put(f"/kotak-struk/merchants/{await self.merchant_id(QRIS_KEY)}", json={"display_name": "Bu Siti"})
        async with self.Session() as db:
            user_b = await db.get(User, self.b.id)
            item_b = await db.get(ReceiptScan, theirs.id)
            self.assertEqual((await item_detail(db, item_b, user_b))["description_preview"], "Bu Siti (QRIS)")
        self.assertEqual((await self.detail(mine))["merchant"]["display_name"], "Bu Siti")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SoftDuplicateTests(ApiBase):
    """`dedup.soft_duplicate` langsung."""

    async def soft(self, *, amount=25000, paid_at=PAID, viewer=None, household=None):
        async with self.Session() as db:
            return await soft_duplicate(db, household or self.hh.id, amount=amount, paid_at=paid_at,
                                        viewer_id=(viewer or self.a).id)

    async def test_matches_same_amount_date_within_window_inclusive(self):
        t = await self.add_txn(amount=25000, description="bakso 25rb", created_at=PAID + timedelta(hours=3), on=PAID.date())
        got = await self.soft()
        self.assertEqual(got, {"kind": "soft", "transaction": {
            "id": str(t.id), "description": "bakso 25rb", "amount": 25000, "created_at": got["transaction"]["created_at"],
            "envelope_name": "Makan"}})
        self.assertTrue(got["transaction"]["created_at"].startswith("2026-10-26T04:12:33"))

    async def test_misses(self):
        day = PAID.date()
        await self.add_txn(amount=25001, description="beda nominal", created_at=PAID, on=day)
        await self.add_txn(amount=25000, description="beda hari", created_at=PAID, on=day - timedelta(days=1))
        await self.add_txn(amount=25000, description="kejauhan", created_at=PAID + timedelta(hours=3, minutes=1), on=day)
        await self.add_txn(amount=25000, description="terhapus", created_at=PAID, on=day, deleted=True)
        await self.add_txn(amount=25000, description="rumah lain", created_at=PAID, on=day, household=self.other_hh.id)
        self.assertIsNone(await self.soft())
        self.assertIsNone(await self.soft(amount=0))

    async def test_date_is_the_wib_date_of_paid_at(self):
        late = datetime(2026, 10, 25, 20, 30, tzinfo=timezone.utc)   # 26 Okt 03.30 WIB
        await self.add_txn(amount=25000, description="dini hari", created_at=late, on=late.date() + timedelta(days=1))
        await self.add_txn(amount=25000, description="tanggal UTC", created_at=late, on=late.date())
        self.assertEqual((await self.soft(paid_at=late))["transaction"]["description"], "dini hari")

    async def test_private_description_of_another_member_is_masked(self):
        await self.add_txn(amount=25000, description="hadiah rahasia", created_at=PAID, on=PAID.date(), user=self.b, private=True)
        self.assertEqual((await self.soft())["transaction"]["description"], "Transaksi privat")
        self.assertEqual((await self.soft(viewer=self.b))["transaction"]["description"], "hadiah rahasia")

    async def test_own_private_and_other_members_shared_descriptions_are_shown(self):
        await self.add_txn(amount=25000, description="punyaku", created_at=PAID, on=PAID.date(), private=True)
        self.assertEqual((await self.soft())["transaction"]["description"], "punyaku")
        await self.add_txn(amount=30000, description="dari budi", created_at=PAID, on=PAID.date(), user=self.b)
        self.assertEqual((await self.soft(amount=30000))["transaction"]["description"], "dari budi")

    async def test_other_members_personal_envelope_is_invisible(self):
        await self.add_txn(amount=25000, description="pribadi b", created_at=PAID, on=PAID.date(), user=self.b, envelope="Pribadi B")
        self.assertIsNone(await self.soft())
        self.assertEqual((await self.soft(viewer=self.b))["transaction"]["envelope_name"], "Pribadi B")

    async def test_without_viewer_fails_closed(self):
        await self.add_txn(amount=25000, description="rahasia", created_at=PAID, on=PAID.date(), private=True)
        await self.add_txn(amount=30000, description="pribadi b", created_at=PAID, on=PAID.date(), user=self.b, envelope="Pribadi B")
        async with self.Session() as db:
            got = await soft_duplicate(db, self.hh.id, amount=25000, paid_at=PAID)
            self.assertEqual(got["transaction"]["description"], "Transaksi privat")
            self.assertIsNone(await soft_duplicate(db, self.hh.id, amount=30000, paid_at=PAID))
            self.assertIsNone(await soft_duplicate(db, None, amount=25000, paid_at=PAID, viewer_id=self.a.id))


if __name__ == "__main__":
    unittest.main()
