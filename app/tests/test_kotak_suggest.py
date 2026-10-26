"""Saran amplop dari peta merchant rumah tangga dan pembelajarannya (SQLite berkas sementara).
Run: python -m unittest app.tests.test_kotak_suggest -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import delete, event, func, select

from app.core.database import Base
from app.models.models import (
    Envelope, Household, HouseholdMember, HouseholdMerchant, HouseholdRole, MerchantEnvelopeMap, ReceiptScan, User,
)
from app.services.expense_rules import after_expense_recorded
from app.services.kotak_struk import record
from app.services.kotak_struk.document import Counterparty, DokumenBayar
from app.services.kotak_struk.merchants import merchant_for_item, set_display_name
from app.services.kotak_struk.record import NotRecordable, check_recordable, learn_text_for_item, mark_recorded
from app.services.kotak_struk.suggest import suggest_for_item, visible_expense_envelopes

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
T1 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=1)
KEY = "nmid:ID1"

_TEMPLATE_DB = None


def setUpModule():
    """Skema SQLite dibuat sekali; tiap tes menyalin berkasnya."""
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


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class KotakSuggestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.dir = tempfile.mkdtemp()
        shutil.copyfile(_TEMPLATE_DB, f"{self.dir}/t.db")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.dir}/t.db")
        # Resep SQLAlchemy untuk pysqlite: SAVEPOINT terluar butuh BEGIN eksplisit.
        event.listen(self.engine.sync_engine, "connect", lambda conn, _rec: setattr(conn, "isolation_level", None))
        event.listen(self.engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.db = self.Session()
        self.a, self.b = User(name="Ani"), User(name="Budi")
        self.hh, self.other = Household(name="Rumah"), Household(name="Rumah Lain")
        self.db.add_all([self.a, self.b, self.hh, self.other])
        await self.db.flush()
        self.db.add_all([HouseholdMember(user_id=self.a.id, household_id=self.hh.id, role=HouseholdRole.owner),
                         HouseholdMember(user_id=self.b.id, household_id=self.hh.id, role=HouseholdRole.member)])
        self.env = {}
        for name, hid, extra in [
            ("Makan", self.hh.id, {}), ("Jajan", self.hh.id, {}),
            ("Pribadi B", self.hh.id, {"owner_id": self.b.id}),
            ("Lama", self.hh.id, {"is_active": False}),
            ("Tabungan", self.hh.id, {"purpose": "saving"}),
            ("Rumah Lain", self.other.id, {}),
        ]:
            self.env[name] = Envelope(household_id=hid, name=name, **extra)
        self.db.add_all(self.env.values())
        await self.db.flush()
        self.item = await self.qris_item("SITI AMINAH", key=KEY)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- pembantu ------------------------------------------------------

    async def qris_item(self, name, *, key, doc_type="qris", merchant_row=True, **cols):
        if merchant_row:
            self.db.add(HouseholdMerchant(household_id=self.hh.id, counterparty_key=key, raw_name=name,
                                          last_seen_at=T1, created_at=T1))
        doc = DokumenBayar(doc_type=doc_type, counterparty=Counterparty(name=name, city="Bandung"))
        cols = {"user_id": self.a.id, "status": "siap", "doc_type": doc_type, "household_id": self.hh.id,
                "merchant": name, "counterparty_key": key, "document": doc.to_json(), "source": "telegram", **cols}
        item = ReceiptScan(**cols)
        self.db.add(item)
        await self.db.commit()
        return item

    async def store_item(self, **cols):
        cols.setdefault("ocr_lines", json.dumps(["ALFAMART", "Total 45.000"]))
        return await self.qris_item("ALFAMART", key="nama:alfamart|", doc_type="struk_belanja",
                                    merchant_row=False, **cols)

    async def merchant_id(self, key=KEY):
        return (await self.db.execute(
            select(HouseholdMerchant.id).where(HouseholdMerchant.counterparty_key == key))).scalar_one()

    async def map(self, env, count, used=T1):
        self.db.add(MerchantEnvelopeMap(merchant_id=await self.merchant_id(), envelope_id=env.id,
                                        count=count, last_used_at=used))
        await self.db.commit()

    async def map_row(self, env):
        async with self.Session() as db:
            return (await db.execute(
                select(MerchantEnvelopeMap).where(MerchantEnvelopeMap.envelope_id == env.id))).scalars().first()

    async def map_count(self):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(MerchantEnvelopeMap))).scalar()

    async def get(self, item_id):
        async with self.Session() as db:
            return await db.get(ReceiptScan, item_id)

    async def record(self, item, env, user=None, tid=None):
        return await mark_recorded(self.db, item.id, user_id=(user or self.a).id,
                                   transaction_id=tid or uuid4(), envelope_id=env.id)

    # --- brief ---------------------------------------------------------

    async def test_note_wins(self):
        s = await suggest_for_item(self.db, self.item, self.a, note="beli soto")
        self.assertEqual((s["envelope_name"], s["source"]), ("Makan", "note"))

    async def test_merchant_majority_is_confident(self):
        await self.map(self.env["Makan"], 2); await self.map(self.env["Jajan"], 1)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual((s["envelope_name"], s["confident"], s["source"]), ("Makan", True, "merchant"))

    async def test_split_history_not_confident_and_tie_uses_latest(self):
        await self.map(self.env["Makan"], 1, used=T1); await self.map(self.env["Jajan"], 1, used=T2)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual((s["envelope_name"], s["confident"]), ("Jajan", False))

    async def test_hidden_or_inactive_envelopes_never_suggested(self):
        await self.map(self.env["Pribadi B"], 5); await self.map(self.env["Lama"], 5); await self.map(self.env["Tabungan"], 5)
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertNotIn(s["envelope_name"], ("Pribadi B", "Lama", "Tabungan"))

    async def test_keyword_fallback_from_merchant_name(self):
        item = await self.qris_item("WARUNG BAKSO PAK DI", key="nama:warung bakso pak di|")
        s = await suggest_for_item(self.db, item, self.a)
        self.assertEqual((s["envelope_name"], s["source"]), ("Makan", "keyword"))

    async def test_mark_recorded_learns_household_map(self):
        ok = await mark_recorded(self.db, self.item.id, user_id=self.b.id, transaction_id=uuid4(), envelope_id=self.env["Makan"].id)
        self.assertTrue(ok)
        row = await self.map_row(self.env["Makan"])
        self.assertEqual((row.count, row.last_user_id), (1, self.b.id))
        self.assertEqual((await self.get(self.item.id)).status, "tercatat")
        s = await suggest_for_item(self.db, self.item, self.a)   # anggota lain langsung dapat saran yakin
        self.assertEqual((s["envelope_name"], s["confident"]), ("Makan", True))

    async def test_learn_text_excludes_merchant_names(self):
        self.assertEqual(await learn_text_for_item(self.db, self.item.id, "bakso 2, es teh (Siti Aminah)"), "bakso 2, es teh")
        self.assertEqual(await learn_text_for_item(self.db, self.item.id, "Siti Aminah (QRIS)"), "")

    async def test_recordable_rules(self):
        await check_recordable(self.db, self.item.id, self.a)
        with self.assertRaises(NotRecordable):
            await check_recordable(self.db, self.item.id, self.b)            # bukan pemilik
        await mark_recorded(self.db, self.item.id, user_id=self.a.id, transaction_id=uuid4(), envelope_id=self.env["Makan"].id)
        with self.assertRaises(NotRecordable) as cm:
            await check_recordable(self.db, self.item.id, self.a)
        self.assertEqual(cm.exception.detail, "Bukti ini sudah tercatat")
        store = await self.store_item(status="tercatat")
        await check_recordable(self.db, store.id, self.a)                    # struk belanja: banyak transaksi

    async def test_after_expense_recorded_learn_text(self):
        with patch("app.services.txn_nlp.save_learned_keywords", new=AsyncMock()) as save, \
             patch("app.services.streak.record_activity", new=AsyncMock()):
            await after_expense_recorded(self.db, self.a, self.env["Makan"].id, "Siti Aminah (QRIS)", learn_text="")
            save.assert_not_awaited()
            await after_expense_recorded(self.db, self.a, self.env["Makan"].id, "x (Siti)", learn_text="bakso")
            self.assertEqual(save.await_args.args[1], "bakso")

    # --- tambahan: aturan keputusan pengendali ---------------------------

    async def test_after_expense_recorded_default_learns_description(self):
        with patch("app.services.txn_nlp.save_learned_keywords", new=AsyncMock()) as save, \
             patch("app.services.streak.record_activity", new=AsyncMock()):
            await after_expense_recorded(self.db, self.a, self.env["Makan"].id, "kopi 35k")
            self.assertEqual(save.await_args.args[1], "kopi 35k")

    async def test_visible_envelopes_are_active_expense_and_not_others_private(self):
        names = lambda envs: sorted(e.name for e in envs)
        self.assertEqual(names(await visible_expense_envelopes(self.db, self.hh.id, self.a.id)), ["Jajan", "Makan"])
        self.assertEqual(names(await visible_expense_envelopes(self.db, self.hh.id, self.b.id)), ["Jajan", "Makan", "Pribadi B"])

    async def test_user_who_left_household_gets_no_suggestion(self):
        await self.map(self.env["Makan"], 3)
        await self.db.execute(delete(HouseholdMember).where(HouseholdMember.user_id == self.a.id))
        await self.db.commit()
        s = await suggest_for_item(self.db, self.item, self.a, note="beli soto")
        self.assertEqual((s["envelope_id"], s["source"], s["confident"]), (None, "none", False))

    async def test_item_of_another_household_skips_merchant_map(self):
        await self.map(self.env["Makan"], 3)
        self.item.household_id = self.other.id
        await self.db.commit()
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual(s["source"], "none")

    async def test_no_signal_gives_none(self):
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual(s, {"envelope_id": None, "envelope_name": None, "confident": False, "source": "none"})

    async def test_nickname_is_used_for_keyword_step(self):
        mid = await self.merchant_id()
        await set_display_name(self.db, mid, self.hh.id, "Bakso Bu Siti")
        s = await suggest_for_item(self.db, self.item, self.a)
        self.assertEqual((s["envelope_name"], s["source"]), ("Makan", "keyword"))

    async def test_store_receipt_never_feeds_merchant_map(self):
        # Struk belanja (termasuk bukti saklar-mati dengan kunci sampah) tidak mengajari peta merchant.
        store = await self.store_item(counterparty_key="nama:transfer berhasil|")
        self.db.add(HouseholdMerchant(household_id=self.hh.id, counterparty_key="nama:transfer berhasil|",
                                      raw_name="Transfer Berhasil", last_seen_at=T1, created_at=T1))
        await self.db.commit()
        t1, t2 = uuid4(), uuid4()
        self.assertTrue(await self.record(store, self.env["Makan"], tid=t1))
        self.assertTrue(await self.record(store, self.env["Jajan"], tid=t2))
        got = await self.get(store.id)
        self.assertEqual((got.status, got.transaction_ids), ("tercatat", [str(t1), str(t2)]))
        self.assertEqual(got.ocr_lines, json.dumps(["ALFAMART", "Total 45.000"]))
        self.assertEqual(await self.map_count(), 0)
        self.assertIsNone(await learn_text_for_item(self.db, store.id, "roti"))

    async def test_missing_merchant_row_is_created_when_recording_proof(self):
        item = await self.qris_item("TOKO BARU", key="nmid:ID9", merchant_row=False)
        await self.record(item, self.env["Jajan"])
        async with self.Session() as db:
            merchant = (await db.execute(select(HouseholdMerchant).where(
                HouseholdMerchant.counterparty_key == "nmid:ID9"))).scalar_one()
        self.assertEqual((merchant.household_id, merchant.raw_name, merchant.city), (self.hh.id, "TOKO BARU", "Bandung"))
        self.assertEqual((await self.map_row(self.env["Jajan"])).count, 1)

    async def test_envelope_of_other_household_marks_item_without_learning(self):
        self.assertTrue(await self.record(self.item, self.env["Rumah Lain"]))
        self.assertEqual((await self.get(self.item.id)).status, "tercatat")
        self.assertEqual(await self.map_count(), 0)

    async def test_recording_again_increments_count(self):
        await self.record(self.item, self.env["Makan"])
        await self.record(self.item, self.env["Makan"], user=self.b)
        row = await self.map_row(self.env["Makan"])
        self.assertEqual((row.count, row.last_user_id), (2, self.b.id))
        self.assertEqual(await self.map_count(), 1)

    async def test_unknown_item_is_not_recorded(self):
        self.assertFalse(await mark_recorded(self.db, uuid4(), user_id=self.a.id, transaction_id=uuid4(),
                                             envelope_id=self.env["Makan"].id))
        self.assertIsNone(await learn_text_for_item(self.db, uuid4(), "bakso"))

    async def test_learning_failure_does_not_block_marking(self):
        with patch.object(record, "_learn", new=AsyncMock(side_effect=RuntimeError("galat"))), \
                self.assertLogs(record.log, level="WARNING"):
            self.assertTrue(await self.record(self.item, self.env["Makan"]))
        self.assertEqual((await self.get(self.item.id)).status, "tercatat")
        self.assertEqual(await self.map_count(), 0)

    async def test_not_recordable_reasons(self):
        async def reason(item_id, user=None):
            with self.assertRaises(NotRecordable) as cm:
                await check_recordable(self.db, item_id, user or self.a)
            return cm.exception.detail
        self.assertEqual(await reason(uuid4()), "Bukti tidak ditemukan")
        diproses = await self.qris_item("X", key="nmid:ID2", merchant_row=False, status="diproses")
        self.assertEqual(await reason(diproses.id), "Bukti ini belum siap dicatat")
        gagal_doc = DokumenBayar(doc_type="transfer", status="gagal",
                                 checks=[{"code": "status_gagal", "level": "block",
                                          "message": "Transaksi gagal, tidak bisa dicatat"}]).to_json()
        gagal = await self.qris_item("Y", key="nmid:ID3", merchant_row=False, doc_type="transfer", document=gagal_doc)
        self.assertEqual(await reason(gagal.id), "Transaksi gagal, tidak bisa dicatat")
        warn_doc = DokumenBayar(doc_type="qris", checks=[{"code": "bukti_lama", "level": "warn", "message": "lama"}]).to_json()
        warn = await self.qris_item("Z", key="nmid:ID4", merchant_row=False, document=warn_doc)
        await check_recordable(self.db, warn.id, self.a)                    # peringatan tidak memblokir

    async def test_recorded_duplicate_blocks(self):
        await self.qris_item("Dup", key="nmid:ID5", merchant_row=False, status="tercatat", ref_hash="r" * 64)
        item = await self.qris_item("Dup", key="nmid:ID5", merchant_row=False, ref_hash="r" * 64)
        with self.assertRaises(NotRecordable) as cm:
            await check_recordable(self.db, item.id, self.a)
        self.assertEqual(cm.exception.detail, "Bukti ini sudah tercatat")

    async def test_merchant_for_item(self):
        self.assertEqual((await merchant_for_item(self.db, self.item)).counterparty_key, KEY)
        self.assertIsNone(await merchant_for_item(self.db, await self.qris_item("X", key="nmid:ID6", merchant_row=False)))
        self.item.counterparty_key = None
        self.assertIsNone(await merchant_for_item(self.db, self.item))
        self.item.counterparty_key, self.item.household_id = KEY, None
        self.assertIsNone(await merchant_for_item(self.db, self.item))

    async def test_set_display_name_cleans_cuts_and_clears(self):
        mid = await self.merchant_id()
        row = await set_display_name(self.db, mid, self.hh.id, "  Warung   Bakso <b>Bu</b> Siti!<script>  ")
        self.assertEqual(row.display_name, "Warung Bakso Bu Siti")
        row = await set_display_name(self.db, mid, self.hh.id, "Toko & Kopi O'Neil-1.0 " + "x" * 100)
        self.assertEqual(len(row.display_name), 60)
        self.assertTrue(row.display_name.startswith("Toko & Kopi O'Neil-1.0 x"))
        row = await set_display_name(self.db, mid, self.hh.id, "<>!!")      # tidak ada yang tersisa: nama panggilan dihapus
        self.assertEqual((row.id, row.display_name), (mid, None))

    async def test_set_display_name_other_household_or_missing(self):
        mid = await self.merchant_id()
        await set_display_name(self.db, mid, self.hh.id, "Bu Siti")
        self.assertIsNone(await set_display_name(self.db, mid, self.other.id, "Curian"))
        self.assertIsNone(await set_display_name(self.db, uuid4(), self.hh.id, "Hantu"))
        self.assertEqual((await self.db.get(HouseholdMerchant, mid)).display_name, "Bu Siti")


if __name__ == "__main__":
    unittest.main()
