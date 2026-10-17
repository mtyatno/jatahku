"""Integrasi geser dana di bot terhadap database sungguhan (SQLite in-memory):
model, check_behavior, get_envelopes_with_spent, dan transfer asli — hanya
Redis, Telegram, dan pencocokan amplop yang dipalsukan.

Menangkap bug ORM yang lolos dari tes mock, mis. objek sesi yang ter-expire
setelah rollback (MissingGreenlet) saat item antrean berikutnya diproses.

Butuh `aiosqlite` (pip install aiosqlite); dilewati bila tidak ada.
Run: python -m unittest app.tests.test_fund_shift_integration -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import unittest
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select

from app.bot import batch_cmd, handlers
# Impor di luar event loop: impor pertama yang lambat di dalam tes memicu
# peringatan "Executing <Task ...> took 0.2 seconds" di mode debug asyncio.
from app.api.routes import envelopes as _envelopes_routes, transactions as _txn_routes  # noqa: F401
from app.services import streak as _streak, txn_nlp as _txn_nlp  # noqa: F401
from app.core.database import Base
from app.models.models import (
    Allocation, Envelope, Household, HouseholdMember, HouseholdRole, Income,
    PendingTransaction, Transaction, User,
)

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
TG_ID = 4242


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def setex(self, k, ttl, v):
        self.store[k] = v

    async def get(self, k):
        v = self.store.get(k)
        return v.encode() if isinstance(v, str) else v

    async def getdel(self, k):
        v = self.store.pop(k, None)
        return v.encode() if isinstance(v, str) else v

    async def delete(self, k):
        self.store.pop(k, None)

    async def aclose(self):
        pass

    async def close(self):  # klien lama di handle_txn_callback memakai close()
        pass


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class FundShiftIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Sama dengan app.core.database.AsyncSessionLocal
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()

        async with self.Session() as db:
            user = User(name="Tes", telegram_id=str(TG_ID))
            hh = Household(name="Rumah Tes")
            db.add_all([user, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole.owner))
            self.env = {}
            for name, kw in [("Makan", {}), ("Jajan", {"daily_limit": D("10000")}),
                             ("Transport", {}), ("Hobi", {"is_locked": True}),
                             ("Tabungan", {"purpose": "saving"})]:
                e = Envelope(household_id=hh.id, name=name, emoji="📁", budget_amount=D("0"), **kw)
                db.add(e)
                self.env[name] = e
            await db.flush()
            inc = Income(household_id=hh.id, user_id=user.id, amount=D("1310000"),
                         description="Gaji", income_date=date.today())
            db.add(inc)
            await db.flush()
            for name, amt in [("Makan", 10000), ("Transport", 200000), ("Hobi", 100000),
                              ("Tabungan", 1000000)]:
                db.add(Allocation(income_id=inc.id, envelope_id=self.env[name].id, amount=D(amt)))
            await db.commit()
            self.user_id, self.hid = user.id, hh.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    def patches(self, matches=None):
        ps = [
            patch("redis.asyncio.from_url", return_value=self.redis),
            patch.object(handlers, "AsyncSessionLocal", new=self.Session),
            patch.object(batch_cmd, "AsyncSessionLocal", new=self.Session),
        ]  # streak & pembelajaran kata kunci (after_expense_recorded) berjalan sungguhan
        if matches is not None:
            async def find(desc, hid, db, user_id=None):
                name = matches.get(desc)
                return (self.env[name] if name else None), True
            ps.append(patch.object(batch_cmd, "find_best_envelope", new=find))
        return ps

    async def go(self, coro_fn, matches=None):
        ps = self.patches(matches)
        for p in ps:
            p.start()
        try:
            return await coro_fn()
        finally:
            for p in ps:
                p.stop()

    async def tap(self, data):
        q = MagicMock()
        q.data = data
        q.from_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        update = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=TG_ID, first_name="Tes"))
        if data.startswith("bshift_"):
            fn = batch_cmd.handle_batch_shift_callback
        elif data.startswith("blimit_"):
            fn = batch_cmd.handle_batch_limit_callback
        elif data.startswith("t_"):
            fn = handlers.handle_txn_callback
        elif data.startswith("dlimit:"):
            fn = handlers.handle_daily_limit_callback
        elif data.startswith("batch_"):
            fn = batch_cmd.handle_batch_callback
        else:
            fn = handlers.handle_fund_shift_callback
        await self.go(lambda: fn(update, None))
        return q.edit_message_text.call_args

    async def remaining(self, name):
        async with self.Session() as db:
            user = (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()
            rows = await handlers.get_envelopes_with_spent(self.hid, db, user.id)
            return next(r["remaining"] for r in rows if r["envelope"].name == name)

    async def count(self, model, *where):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()

    async def test_multi_item_end_to_end(self):
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        items = [(D("5000"), "parkir"), (D("30000"), "sate"), (D("20000"), "kopi"),
                 (D("10000"), "mainan"), (D("7000"), "xyz")]
        matches = {"parkir": "Transport", "sate": "Makan", "kopi": "Jajan", "mainan": "Hobi"}
        await self.go(lambda: batch_cmd.handle_multi_expense(update, None, items), matches)

        # parkir tercatat, mainan (amplop dikunci) tidak; sate ditawari geser 20rb
        call = update.message.reply_text.call_args
        self.assertIn("Kurang <b>Rp20rb</b>", call.args[0])
        btns = [r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard]
        labels = [r[0].text for r in call.kwargs["reply_markup"].inline_keyboard]
        # Sumber sah sama dengan modal web: amplop lain dengan sisa cukup, sisa terbesar dulu
        self.assertEqual([l.split(" (")[0] for l in labels[:3]],
                         ["🔁 📁 Tabungan", "🔁 📁 Transport", "🔁 📁 Hobi"])
        self.assertIn("Top-up pemasukan Rp20rb", labels[3])
        self.assertEqual(len(btns), 5)
        transport_btn = next(b for b, r in zip(btns, call.kwargs["reply_markup"].inline_keyboard)
                             if "Transport" in r[0].text)

        # sate: geser dari Transport → tercatat
        call = await self.tap(transport_btn)
        self.assertIn("Kurang <b>Rp20rb</b>", call.args[0])  # kopi: Jajan belum didanai
        transport_btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                             if "Transport" in r[0].text)

        # kopi: geser 20rb, tapi limit harian Jajan 10rb → dana tetap tersimpan, lalu
        # ditawari "naikkan limit hari ini" (sama dengan web & alur satu item)
        call = await self.tap(transport_btn)
        self.assertIn("Limit harian terlampaui", call.args[0])
        self.assertIn("Dana untuk item ini sudah ditambahkan", call.args[0])
        limit_btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                         if r[0].callback_data.endswith("_y"))

        # ✅ → bypass Redis ditulis lewat raise_daily_limit_today, check_behavior asli lolos
        call = await self.tap(limit_btn)
        self.assertIn("Masuk ke amplop mana?", call.args[0])
        self.assertTrue(any(k.startswith("dlimit_temp:") for k in self.redis.store))
        xyz_btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                       if "Transport" in r[0].text)

        call = await self.tap(xyz_btn)
        text = call.args[0]
        self.assertIn("4 transaksi dicatat", text)
        self.assertIn("🔁 +Rp20rb dari 📁 Transport", text)
        self.assertIn("📁 Jajan: Rp20rb — kopi · 🔁 +Rp20rb dari 📁 Transport", text)
        self.assertIn("mainan", text)
        self.assertIsNone(call.kwargs["reply_markup"])
        self.assertFalse(any(k.startswith("batch") for k in self.redis.store))

        self.assertEqual(await self.count(Transaction), 4)               # parkir, sate, kopi, xyz
        self.assertEqual(await self.count(Income, Income.amount == 0), 2)  # geser untuk sate & kopi
        self.assertEqual(await self.remaining("Transport"), D("148000"))  # 200 − 5 − 20 − 20 − 7
        self.assertEqual(await self.remaining("Makan"), D("0"))
        self.assertEqual(await self.remaining("Jajan"), D("0"))
        self.assertEqual(await self.remaining("Hobi"), D("100000"))

    # ── Naikkan limit harian: web memakai mekanisme yang sama dengan bot ─────

    async def test_web_raise_daily_limit_single(self):
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        await self.income("Jajan", 50000)  # Jajan: limit harian 10rb
        jajan = self.env["Jajan"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as ctx:
                    await create_transaction(TransactionCreate(envelope_id=jajan, amount=D("20000"), description="kopi"),
                                             await self.web_user(db), db)
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertEqual(ctx.exception.detail,
                             "Melebihi limit harian Jajan: limit Rp10.000/hari, terpakai Rp0, diminta Rp20.000.")
            self.assertEqual(await self.count(Transaction), 0)

            async with self.Session() as db:
                await create_transaction(TransactionCreate(envelope_id=jajan, amount=D("20000"), description="kopi",
                                                           raise_daily_limit=True), await self.web_user(db), db)
            self.assertIn(f"dlimit_temp:{self.user_id}:{jajan}", self.redis.store)  # kunci yang sama dengan bot
            async with self.Session() as db:  # sisa hari ini limitnya sudah dinaikkan — sama dengan bot
                await create_transaction(TransactionCreate(envelope_id=jajan, amount=D("5000"), description="es"),
                                         await self.web_user(db), db)
        self.assertEqual(await self.count(Transaction), 2)

    async def test_web_raise_daily_limit_batch(self):
        from app.api.routes.transactions import BatchTransactionCreate, BatchTransactionItem, batch_create_transactions
        await self.income("Jajan", 50000)
        jajan = self.env["Jajan"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                out = await batch_create_transactions(BatchTransactionCreate(items=[
                    BatchTransactionItem(envelope_id=jajan, amount=D("20000"), description="kopi"),
                ]), await self.web_user(db), db)
            self.assertFalse(out[0].ok)
            self.assertIn("limit harian Jajan", out[0].error)
            async with self.Session() as db:
                out = await batch_create_transactions(BatchTransactionCreate(items=[
                    BatchTransactionItem(envelope_id=jajan, amount=D("20000"), description="kopi",
                                         raise_daily_limit=True),
                ]), await self.web_user(db), db)
        self.assertTrue(out[0].ok)
        self.assertEqual(await self.count(Transaction), 1)

    # ── Struk: tanggal struk & feedback terbawa lewat isi dana / naikkan limit ─

    def seed_receipt(self, env_name, amount):
        self.redis.store["txn:rcpt0001"] = json.dumps({
            "amount": amount, "desc": "Indomaret", "envs": {"0": str(self.env[env_name].id)},
            "date": "2026-10-10", "scan_id": "scan-1"})

    async def receipt_txn(self):
        async with self.Session() as db:
            return (await db.execute(select(Transaction))).scalars().all()

    async def test_receipt_date_kept_through_fund_shift(self):
        self.seed_receipt("Makan", 30000)  # Makan sisa 10rb → kurang 20rb
        feedback = AsyncMock()
        with patch("app.services.receipt_scan.apply_feedback", new=feedback):
            call = await self.tap("t_rcpt0001_0")
            self.assertIn("Kurang <b>Rp20rb</b>", call.args[0])
            btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                       if "Transport" in r[0].text)
            call = await self.tap(btn)
        self.assertIn("digeser dari", call.args[0])
        txn, = await self.receipt_txn()
        self.assertEqual(txn.transaction_date, date(2026, 10, 10))
        feedback.assert_awaited_once()
        self.assertEqual(feedback.call_args.kwargs["txn_date"], date(2026, 10, 10))

    async def test_receipt_date_kept_through_daily_limit_raise(self):
        await self.income("Jajan", 50000)  # limit harian Jajan 10rb
        self.seed_receipt("Jajan", 20000)
        feedback = AsyncMock()
        with patch("app.services.receipt_scan.apply_feedback", new=feedback):
            call = await self.tap("t_rcpt0001_0")
            self.assertIn("Limit harian terlampaui", call.args[0])
            btn = call.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
            await self.tap(btn)
        txn, = await self.receipt_txn()
        self.assertEqual(txn.transaction_date, date(2026, 10, 10))
        feedback.assert_awaited_once()

    async def test_receipt_feedback_failure_does_not_break_reply(self):
        """Dulu: db.rollback() setelah feedback gagal → user/amplop ter-expire → crash."""
        self.seed_receipt("Transport", 5000)

        async def failing_feedback(user, scan_id, db, **kw):
            await db.execute(select(User))  # gagal SETELAH menyentuh DB, seperti kegagalan sungguhan
            raise RuntimeError("x")
        with patch("app.services.receipt_scan.apply_feedback", new=failing_feedback):
            call = await self.tap("t_rcpt0001_0")
        self.assertIn("Masuk ke 📁 Transport", call.args[0])
        self.assertEqual(len(await self.receipt_txn()), 1)

    async def test_blocked_after_shift_rolls_back_and_queue_continues(self):
        """Blok setelah dana digeser (di sini: amplop dikunci di antara tawaran dan
        ketukan) dibatalkan dengan savepoint; item berikutnya tetap diproses.
        Dengan db.rollback() penuh, langkah ini dulu crash (MissingGreenlet)."""
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await self.go(lambda: batch_cmd.handle_multi_expense(
            update, None, [(D("30000"), "sate"), (D("7000"), "xyz")]), {"sate": "Makan"})
        btn = next(r[0].callback_data for r in update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
                   if "Transport" in r[0].text)
        async with self.Session() as db:
            makan = await db.get(Envelope, self.env["Makan"].id)
            makan.is_locked = True
            await db.commit()

        call = await self.tap(btn)
        self.assertIn("Dana tidak digeser", call.args[0])
        self.assertIn("Masuk ke amplop mana?", call.args[0])  # antrean lanjut ke xyz
        self.assertEqual(await self.count(Income, Income.amount == 0), 0)
        self.assertEqual(await self.remaining("Transport"), D("200000"))

    async def test_single_item_offer_and_shift(self):
        async def offer():
            async with self.Session() as db:
                user = (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()
                env = (await db.execute(select(Envelope).where(Envelope.name == "Makan"))).scalar_one()
                send = AsyncMock()
                await handlers._send_fund_shift_offer(send, str(TG_ID), user, self.hid, env,
                                                      D("35000"), "sate", db)
                return send.call_args
        call = await self.go(offer)
        self.assertIn("Kurang <b>Rp25rb</b>", call.args[0])
        btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                   if "Transport" in r[0].text)

        call = await self.tap(btn)
        self.assertIn("Rp25rb digeser dari 📁 Transport → 📁 Makan", call.args[0])
        self.assertEqual(await self.remaining("Makan"), D("0"))
        self.assertEqual(await self.remaining("Transport"), D("175000"))
        self.assertEqual(await self.count(Transaction), 1)

        call = await self.tap(btn)  # ketukan kedua
        self.assertIn("expired", call.args[0])
        self.assertEqual(await self.remaining("Transport"), D("175000"))


    # ── Kunci household: sama dengan POST /envelopes/transfer & /advisor/execute ─

    def record_lock_order(self, module):
        """Catat urutan kunci household vs hitung ulang saldo di `module` (handlers/batch_cmd).
        SQLite mengabaikan FOR UPDATE, jadi yang diuji: kunci diambil, dengan household yang
        benar, SEBELUM saldo dihitung ulang (penerus kunci melihat data yang sudah di-commit)."""
        from app.services import fund_shift
        events = []
        real_lock, real_rows = fund_shift.lock_household, module.get_envelopes_with_spent

        async def lock(db, hid):
            events.append(("kunci", hid))
            await real_lock(db, hid)

        async def rows(*a, **kw):
            events.append(("saldo", None))
            return await real_rows(*a, **kw)

        ps = [patch.object(fund_shift, "lock_household", new=lock),
              patch.object(module, "get_envelopes_with_spent", new=rows)]
        if module is batch_cmd:
            ps.append(patch.object(batch_cmd, "lock_household", new=lock))
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        return events

    async def single_item_offer(self):
        async def offer():
            async with self.Session() as db:
                user = (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()
                env = (await db.execute(select(Envelope).where(Envelope.name == "Makan"))).scalar_one()
                send = AsyncMock()
                await handlers._send_fund_shift_offer(send, str(TG_ID), user, self.hid, env,
                                                      D("35000"), "sate", db)
                return send.call_args
        return (await self.go(offer)).kwargs["reply_markup"].inline_keyboard

    async def test_single_item_shift_locks_household_before_recount(self):
        keyboard = await self.single_item_offer()
        events = self.record_lock_order(handlers)
        await self.tap(next(r[0].callback_data for r in keyboard if "Transport" in r[0].text))
        self.assertEqual(events[0], ("kunci", self.hid))
        self.assertEqual([e for e, _ in events].count("kunci"), 1)
        self.assertIn("saldo", [e for e, _ in events[1:]])
        self.assertEqual(await self.remaining("Transport"), D("175000"))

    async def test_single_item_topup_takes_no_lock(self):
        keyboard = await self.single_item_offer()
        events = self.record_lock_order(handlers)
        await self.tap(next(r[0].callback_data for r in keyboard if r[0].callback_data.endswith(":t")))
        self.assertNotIn("kunci", [e for e, _ in events])
        self.assertEqual(await self.count(Transaction), 1)

    async def test_multi_item_shift_locks_household_before_recount(self):
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await self.go(lambda: batch_cmd.handle_multi_expense(update, None, [(D("30000"), "sate")]),
                      {"sate": "Makan"})
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
        events = self.record_lock_order(batch_cmd)
        call = await self.tap(next(r[0].callback_data for r in keyboard if "Transport" in r[0].text))
        self.assertIn("1 transaksi dicatat", call.args[0])
        names = [e for e, _ in events]
        self.assertEqual(events[0], ("kunci", self.hid))
        self.assertEqual(names.count("kunci"), 1)
        self.assertIn("saldo", names[1:])
        self.assertEqual(await self.remaining("Transport"), D("180000"))

    async def test_multi_item_topup_and_skip_take_no_lock(self):
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await self.go(lambda: batch_cmd.handle_multi_expense(
            update, None, [(D("30000"), "sate"), (D("30000"), "soto")]), {"sate": "Makan", "soto": "Makan"})
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
        events = self.record_lock_order(batch_cmd)
        call = await self.tap(next(r[0].callback_data for r in keyboard if r[0].callback_data.endswith("_t")))
        keyboard = call.kwargs["reply_markup"].inline_keyboard
        await self.tap(next(r[0].callback_data for r in keyboard if r[0].callback_data.endswith("_skip")))
        self.assertNotIn("kunci", [e for e, _ in events])

    # ── Sisi web: aturan yang sama ditegakkan server ─────────────────────────

    async def web_user(self, db):
        return (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()

    async def test_web_transfer_enforces_same_rule_as_bot(self):
        from fastapi import HTTPException
        from app.api.routes.envelopes import transfer_between_envelopes
        mk, tr = self.env["Makan"].id, self.env["Transport"].id
        async with self.Session() as db:
            with self.assertRaises(HTTPException) as ctx:
                await transfer_between_envelopes(tr, mk, D("200001"), await self.web_user(db), db)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Maksimal transfer dari Transport", ctx.exception.detail)
        async with self.Session() as db:
            out = await transfer_between_envelopes(tr, mk, D("200000"), await self.web_user(db), db)
        self.assertEqual(out["status"], "transferred")
        self.assertEqual(await self.remaining("Transport"), D("0"))
        self.assertEqual(await self.remaining("Makan"), D("210000"))

    async def test_web_refuses_saving_envelope_and_plan_limit(self):
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        async with self.Session() as db:
            req = TransactionCreate(envelope_id=self.env["Tabungan"].id, amount=D("1000"), description="x")
            with self.assertRaises(HTTPException) as ctx:
                await create_transaction(req, await self.web_user(db), db)
            self.assertIn("Amplop tabungan", ctx.exception.detail)
        with patch("app.api.routes.transactions.check_transaction_limit",
                   new=AsyncMock(return_value=(False, "Limit 50 transaksi/bulan tercapai."))):
            async with self.Session() as db:
                req = TransactionCreate(envelope_id=self.env["Transport"].id, amount=D("1000"), description="x")
                with self.assertRaises(HTTPException) as ctx:
                    await create_transaction(req, await self.web_user(db), db)
                self.assertIn("Limit 50", ctx.exception.detail)
        self.assertEqual(await self.count(Transaction), 0)

    async def test_web_create_runs_shared_after_hook(self):
        from app.api.routes.transactions import TransactionCreate, create_transaction
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                req = TransactionCreate(envelope_id=self.env["Transport"].id, amount=D("1000"),
                                        description="ojek kantor")
                await create_transaction(req, await self.web_user(db), db)
        from app.models.models import UserEnvelopeKeyword, UserStreak
        self.assertGreater(await self.count(UserEnvelopeKeyword), 0)
        self.assertEqual(await self.count(UserStreak), 1)

    # ── Idempotensi client_ref: kirim ulang setelah respons hilang ───────────

    def ref_key(self, ref):
        return f"txnref:{self.user_id}:{ref}"

    async def web_batch(self, items):
        from app.api.routes.transactions import BatchTransactionCreate, BatchTransactionItem, batch_create_transactions
        async with self.Session() as db:
            return await batch_create_transactions(
                BatchTransactionCreate(items=[BatchTransactionItem(**it) for it in items]),
                await self.web_user(db), db)

    async def test_web_create_same_client_ref_records_once(self):
        from app.api.routes.transactions import TransactionCreate, create_transaction
        req = TransactionCreate(envelope_id=self.env["Transport"].id, amount=D("15000"),
                                description="ojek", client_ref="ref-ojek")
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                first = await create_transaction(req, await self.web_user(db), db)
            async with self.Session() as db:
                again = await create_transaction(req, await self.web_user(db), db)
        self.assertEqual(again.id, first.id)
        self.assertEqual(await self.count(Transaction), 1)
        self.assertEqual(self.redis.store[self.ref_key("ref-ojek")], str(first.id))

    async def test_web_batch_resend_after_partial_success_records_rest_once(self):
        t = self.env["Transport"].id
        g0 = {"envelope_id": t, "amount": D("60000"), "description": "Toko (2 barang)", "client_ref": "g0"}
        g1 = {"envelope_id": t, "amount": D("40000"), "description": "Toko (1 barang)", "client_ref": "g1"}
        with patch("redis.asyncio.from_url", return_value=self.redis):
            first = await self.web_batch([g0])          # respons hilang setelah g0 tercatat
            again = await self.web_batch([g0, g1])      # klien kirim ulang semuanya
            third = await self.web_batch([g0, g1])
        self.assertTrue(all(r.ok for r in first + again + third))
        self.assertEqual(again[0].id, first[0].id)
        self.assertEqual([r.id for r in third], [r.id for r in again])
        self.assertEqual(await self.count(Transaction), 2)

    async def test_web_ref_still_in_flight_is_not_recorded(self):
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        self.redis.store[self.ref_key("busy")] = "pending"
        t = self.env["Transport"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as cm:
                    await create_transaction(TransactionCreate(envelope_id=t, amount=D("1000"),
                                                               description="x", client_ref="busy"),
                                             await self.web_user(db), db)
            out = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": "x",
                                         "client_ref": "busy"}])
        self.assertEqual(cm.exception.status_code, 409)
        self.assertFalse(out[0].ok)
        self.assertTrue(out[0].pending)
        self.assertEqual(await self.count(Transaction), 0)

    async def test_web_rejected_txn_leaves_ref_free(self):
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        req = TransactionCreate(envelope_id=self.env["Makan"].id, amount=D("50000"),
                                description="makan", client_ref="ref-makan")
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as cm:
                    await create_transaction(req, await self.web_user(db), db)
            self.assertEqual(cm.exception.status_code, 403)
            self.assertNotIn(self.ref_key("ref-makan"), self.redis.store)
            await self.income("Makan", 50000)
            async with self.Session() as db:
                await create_transaction(req, await self.web_user(db), db)
            out = await self.web_batch([{"envelope_id": self.env["Makan"].id, "amount": D("50000"),
                                         "description": "makan", "client_ref": "ref-makan"}])
        self.assertTrue(out[0].ok)
        self.assertEqual(await self.count(Transaction), 1)

    async def test_web_concurrent_send_loses_reservation(self):
        """Dua kiriman bersamaan: keduanya lolos lookup, hanya satu yang dapat reservasi."""
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        from app.services import idempotency
        t = self.env["Transport"].id
        self.redis.store[self.ref_key("race")] = "pending"   # kiriman pertama sedang membuat

        async def lookup_before_reserve(user_id, ref):
            return None  # lookup terjadi sebelum kiriman pertama mereservasi
        with patch("redis.asyncio.from_url", return_value=self.redis), \
                patch.object(idempotency, "lookup", lookup_before_reserve):
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as cm:
                    await create_transaction(TransactionCreate(envelope_id=t, amount=D("1000"),
                                                               description="x", client_ref="race"),
                                             await self.web_user(db), db)
            out = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": "x",
                                         "client_ref": "race"}])
        self.assertEqual(cm.exception.status_code, 409)
        self.assertTrue(out[0].pending)
        self.assertEqual(await self.count(Transaction), 0)

    async def test_web_failed_commit_releases_ref(self):
        from app.api.routes.transactions import TransactionCreate, create_transaction
        req = TransactionCreate(envelope_id=self.env["Transport"].id, amount=D("15000"),
                                description="ojek", client_ref="ref-crash")
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                async def boom():
                    raise RuntimeError("koneksi DB putus")
                db.commit = boom
                with self.assertRaises(RuntimeError):
                    await create_transaction(req, await self.web_user(db), db)
            self.assertNotIn(self.ref_key("ref-crash"), self.redis.store)
            async with self.Session() as db:
                await create_transaction(req, await self.web_user(db), db)
            async with self.Session() as db:
                await create_transaction(req, await self.web_user(db), db)
        self.assertEqual(await self.count(Transaction), 1)

    async def test_receipt_items_teach_per_item_envelope_suggestions(self):
        """Struk dicatat per barang ("SABUN MANDI (Indomaret)") → kata kunci barang
        dipelajari → scan berikutnya menyarankan amplop per barang dari nama barang."""
        from app.api.routes.transactions import BatchSuggestEnvelopeRequest, suggest_envelopes
        t, m = self.env["Transport"].id, self.env["Makan"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            out = await self.web_batch([
                {"envelope_id": t, "amount": D("3000"), "description": "SABUN MANDI (Indomaret)"},
                {"envelope_id": m, "amount": D("2000"), "description": "ROTI TAWAR (Indomaret)"},
            ])
            self.assertTrue(all(r.ok for r in out))
            async with self.Session() as db:
                res = await suggest_envelopes(
                    BatchSuggestEnvelopeRequest(descriptions=["SABUN CAIR", "ROTI TAWAR", "XYZ QWERTY"]),
                    await self.web_user(db), db)
        got = [(r["envelope_id"], r["confident"]) for r in res["results"]]
        self.assertEqual(got[0], (str(t), True))
        self.assertEqual(got[1], (str(m), True))
        self.assertEqual(got[2], (None, False))

    # ── Kuota Basic: input yang dimulai saat kuota masih ada diselesaikan utuh ──

    async def fill_month(self, n, env_name="Transport"):
        from app.models.models import TransactionSource
        async with self.Session() as db:
            for i in range(n):
                db.add(Transaction(envelope_id=self.env[env_name].id, user_id=self.user_id,
                                   amount=D("100"), description=f"isi {i}",
                                   source=TransactionSource.webapp, transaction_date=date.today()))
            await db.commit()

    async def test_basic_quota_web_batch_finishes_started_input(self):
        from fastapi import HTTPException
        from app.api.routes.transactions import TransactionCreate, create_transaction
        await self.fill_month(48)
        t = self.env["Transport"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            out = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": f"barang {i}",
                                         "client_ref": f"q{i}"} for i in range(4)])
            self.assertTrue(all(r.ok for r in out))            # 48 + 4 = 52: tetap selesai utuh
            self.assertIn("sudah habis (sudah 52 transaksi)", out[0].quota_notice)
            nxt = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": "baru",
                                         "client_ref": "q-new"}])
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as cm:
                    await create_transaction(TransactionCreate(envelope_id=t, amount=D("1000"), description="satu"),
                                             await self.web_user(db), db)
        self.assertFalse(nxt[0].ok)                            # input berikutnya ditolak
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis", nxt[0].error)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("bisa lagi mulai 1 ", cm.exception.detail)
        self.assertEqual(await self.count(Transaction), 52)

    async def test_basic_quota_resend_of_started_input_still_allowed(self):
        await self.fill_month(48)
        t, m = self.env["Transport"].id, self.env["Makan"].id
        items = [{"envelope_id": t, "amount": D("1000"), "description": "a", "client_ref": "r-a"},
                 {"envelope_id": t, "amount": D("1000"), "description": "b", "client_ref": "r-b"},
                 {"envelope_id": m, "amount": D("30000"), "description": "c", "client_ref": "r-c"}]  # Makan sisa 10rb
        with patch("redis.asyncio.from_url", return_value=self.redis):
            out = await self.web_batch(items)
            self.assertEqual([r.ok for r in out], [True, True, False])  # 50 → kuota habis
            self.assertIn("sudah habis", out[0].quota_notice)
            await self.income("Makan", 50000)
            again = await self.web_batch([items[2], {"envelope_id": t, "amount": D("1000"),
                                                     "description": "baru", "client_ref": "r-new"}])
        self.assertTrue(again[0].ok)        # bagian dari input yang dimulai saat kuota ada
        self.assertFalse(again[1].ok)       # input baru
        self.assertIn("sudah habis", again[1].error)
        self.assertEqual(await self.count(Transaction), 51)

    async def test_pro_batch_has_no_quota_bookkeeping(self):
        async with self.Session() as db:
            (await self.web_user(db)).plan = "pro"
            await db.commit()
        await self.fill_month(60)
        t = self.env["Transport"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            out = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": "x", "client_ref": "p1"}])
        self.assertTrue(out[0].ok)
        self.assertIsNone(out[0].quota_notice)
        self.assertFalse(any(k.startswith("quotapass:") for k in self.redis.store))

    async def test_basic_quota_bot_multi_item_finishes_message(self):
        await self.fill_month(48)
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        matches = {"parkir": "Transport", "bensin": "Transport", "tol": "Transport"}
        items = [(D("1000"), "parkir"), (D("2000"), "bensin"), (D("3000"), "tol")]
        await self.go(lambda: batch_cmd.handle_multi_expense(update, None, items), matches)
        text = update.message.reply_text.call_args.args[0]
        self.assertIn("3 transaksi dicatat", text)
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis (sudah 51 transaksi)", text)
        update.message.reply_text = AsyncMock()
        await self.go(lambda: batch_cmd.handle_multi_expense(update, None, [(D("1000"), "parkir")]), matches)
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis", update.message.reply_text.call_args.args[0])
        self.assertEqual(await self.count(Transaction), 51)

    async def test_basic_quota_bot_queue_finishes_after_crossing(self):
        await self.fill_month(49)
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        matches = {"parkir": "Transport", "sate": "Makan"}
        await self.go(lambda: batch_cmd.handle_multi_expense(
            update, None, [(D("1000"), "parkir"), (D("30000"), "sate")]), matches)
        call = update.message.reply_text.call_args       # parkir tercatat (50), sate kurang dana
        self.assertIn("Kurang <b>Rp20rb</b>", call.args[0])
        btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                   if "Transport" in r[0].text)
        call = await self.tap(btn)                       # geser → tetap tercatat walau sudah 50
        self.assertIn("2 transaksi dicatat", call.args[0])
        self.assertIn("sudah habis (sudah 51 transaksi)", call.args[0])
        self.assertEqual(await self.count(Transaction), 51)

    async def test_basic_quota_bot_single_item_notice_then_block(self):
        await self.fill_month(49)
        self.redis.store["txn:k1"] = json.dumps({"amount": 5000, "desc": "kopi",
                                                 "envs": {"0": str(self.env["Transport"].id)}})
        call = await self.tap("t_k1_0")
        self.assertIn("✅", call.args[0])
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis (sudah 50 transaksi)", call.args[0])
        self.redis.store["txn:k2"] = json.dumps({"amount": 5000, "desc": "teh",
                                                 "envs": {"0": str(self.env["Transport"].id)}})
        call = await self.tap("t_k2_0")
        self.assertIn("Kuota 50 transaksi bulan ini sudah habis", call.args[0])
        self.assertNotIn("✅", call.args[0])
        self.assertEqual(await self.count(Transaction), 50)

    async def test_basic_quota_bot_fund_shift_finishes_started_input(self):
        await self.fill_month(49)
        self.seed_receipt("Makan", 30000)  # Makan sisa 10rb → kurang 20rb
        with patch("app.services.receipt_scan.apply_feedback", new=AsyncMock()):
            call = await self.tap("t_rcpt0001_0")
            self.assertIn("Kurang <b>Rp20rb</b>", call.args[0])
            await self.fill_month(1)        # kuota habis selagi tombol menunggu
            btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                       if "Transport" in r[0].text)
            call = await self.tap(btn)
        self.assertIn("digeser dari", call.args[0])
        self.assertIn("sudah habis (sudah 51 transaksi)", call.args[0])
        self.assertEqual(await self.count(Transaction), 51)

    async def test_web_long_description_is_trimmed_not_failed(self):
        from app.api.routes.transactions import TransactionCreate, create_transaction
        t = self.env["Transport"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:
                single = await create_transaction(
                    TransactionCreate(envelope_id=t, amount=D("1000"), description="a" * 700),
                    await self.web_user(db), db)
            out = await self.web_batch([{"envelope_id": t, "amount": D("1000"), "description": "b" * 501}])
        self.assertEqual(len(single.description), 500)
        self.assertTrue(out[0].ok)
        async with self.Session() as db:
            lengths = sorted(len(d) for d in (await db.execute(select(Transaction.description))).scalars())
        self.assertEqual(lengths, [500, 500])


    # ── Notifikasi goal: hanya saat saldo melewati target ───────────────────

    async def add_goal(self, env_name, target):
        from app.models.models import Goal
        async with self.Session() as db:
            db.add(Goal(envelope_id=self.env[env_name].id, name="Dana_Darurat", target_amount=D(target)))
            await db.commit()

    async def goal_notifs(self):
        from app.models.models import Notification
        return await self.count(Notification, Notification.title == "🎯 Goal tercapai!")

    async def income(self, env_name, amount):
        from app.api.routes.incomes import AllocationItem, IncomeCreate, create_income
        async with self.Session() as db:
            req = IncomeCreate(amount=D(amount), source="Bonus",
                               allocations=[AllocationItem(envelope_id=self.env[env_name].id, amount=D(amount))])
            await create_income(req, await self.web_user(db), db)

    async def test_goal_notified_once_when_income_crosses_target(self):
        from app.api.routes.transactions import TransactionCreate, create_transaction
        await self.add_goal("Transport", 250000)  # saldo awal 200rb
        await self.income("Transport", 30000)     # 230rb: belum
        self.assertEqual(await self.goal_notifs(), 0)
        await self.income("Transport", 30000)     # 260rb: melewati target
        self.assertEqual(await self.goal_notifs(), 1)
        await self.income("Transport", 30000)     # 290rb: sudah tercapai, tidak berulang
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:      # pengeluaran tidak pernah memicu notifikasi goal
                await create_transaction(TransactionCreate(envelope_id=self.env["Transport"].id,
                                                           amount=D("1000"), description="ojek"),
                                         await self.web_user(db), db)
        self.assertEqual(await self.goal_notifs(), 1)

    async def test_goal_notified_via_web_transfer_and_bot_topup(self):
        from app.api.routes.envelopes import transfer_between_envelopes
        await self.add_goal("Makan", 50000)  # saldo awal 10rb
        async with self.Session() as db:
            await transfer_between_envelopes(self.env["Transport"].id, self.env["Makan"].id, D("50000"),
                                             await self.web_user(db), db)
        self.assertEqual(await self.goal_notifs(), 1)

        await self.add_goal("Jajan", 1)  # saldo 0

        async def topup_kopi():
            async def offer():
                async with self.Session() as db:
                    send = AsyncMock()
                    await handlers._send_fund_shift_offer(send, str(TG_ID), await self.web_user(db), self.hid,
                                                          self.env["Jajan"], D("5000"), "kopi", db)
                    return send.call_args
            call = await self.go(offer)
            btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                       if r[0].callback_data.endswith(":t"))
            return await self.tap(btn)

        # Top-up langsung habis dipakai transaksinya → saldo tak pernah mencapai target
        call = await topup_kopi()
        self.assertIn("Top-up pemasukan Rp5rb", call.args[0])
        self.assertEqual(await self.goal_notifs(), 1)

        # Cooling tidak lagi menahan pencatatan (Pikir-Pikir Fase 0): kopi di atas
        # ambang tetap tercatat, top-up habis terpakai lagi → target tidak terlewati.
        async with self.Session() as db:
            jajan = await db.get(Envelope, self.env["Jajan"].id)
            jajan.cooling_threshold = D("1000")
            await db.commit()
        call = await topup_kopi()
        self.assertIn("✅", call.args[0])
        self.assertNotIn("Cooling", call.args[0])
        self.assertEqual(await self.goal_notifs(), 1)
        self.assertEqual(await self.count(PendingTransaction), 0)

    async def test_large_expense_recorded_despite_cooling_threshold(self):
        """Pikir-Pikir Fase 0: cooling threshold (amplop maupun default user) tidak
        lagi menahan pencatatan di web maupun bot. Dulu web menolak (403) dan tidak
        mencatat apa pun; bot membuat transaksi pending."""
        from app.api.routes.transactions import (
            BatchTransactionCreate, BatchTransactionItem, TransactionCreate,
            batch_create_transactions, create_transaction,
        )
        async with self.Session() as db:
            (await db.get(Envelope, self.env["Transport"].id)).cooling_threshold = D("1000")
            (await self.web_user(db)).default_cooling_threshold = D("1000")  # berlaku ke Makan
            await db.commit()
        tr, mk = self.env["Transport"].id, self.env["Makan"].id
        with patch("redis.asyncio.from_url", return_value=self.redis):
            async with self.Session() as db:  # web, satu item
                txn = await create_transaction(
                    TransactionCreate(envelope_id=tr, amount=D("50000"), description="servis motor"),
                    await self.web_user(db), db)
            self.assertEqual(txn.amount, D("50000"))
            async with self.Session() as db:  # web, multi-item
                out = await batch_create_transactions(BatchTransactionCreate(items=[
                    BatchTransactionItem(envelope_id=tr, amount=D("40000"), description="ban"),
                    BatchTransactionItem(envelope_id=mk, amount=D("5000"), description="nasi"),
                ]), await self.web_user(db), db)
            self.assertEqual([(r.ok, r.error) for r in out], [(True, None), (True, None)])

        # bot, multi-item
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        await self.go(lambda: batch_cmd.handle_multi_expense(
            update, None, [(D("30000"), "bensin"), (D("2000"), "parkir")]),
            {"bensin": "Transport", "parkir": "Makan"})
        text = update.message.reply_text.call_args.args[0]
        self.assertIn("2 transaksi dicatat", text)
        self.assertNotIn("cooling", text.lower())

        self.assertEqual(await self.count(Transaction), 5)
        self.assertEqual(await self.count(PendingTransaction), 0)
        self.assertEqual(await self.remaining("Transport"), D("80000"))  # 200rb − 50 − 40 − 30

    async def test_telegram_text_escapes_markdown(self):
        await self.add_goal("Transport", 250000)
        sent = []

        class FakeBot:
            def __init__(self, token):
                pass

            async def send_message(self, chat_id, text, parse_mode):
                sent.append(text)
        with patch("app.services.notification_service.Bot", FakeBot), \
             patch("app.services.notification_service.settings",
                   SimpleNamespace(TELEGRAM_BOT_TOKEN="x")):
            await self.income("Transport", 60000)
        self.assertEqual(len(sent), 1)
        self.assertIn("Dana\\_Darurat", sent[0])  # nama goal ber-underscore tidak merusak Markdown


class GoalCrossingTests(unittest.TestCase):
    def test_crossed(self):
        from app.services.goal_notify import crossed
        self.assertTrue(crossed(D("99"), D("100"), D("100")))
        self.assertFalse(crossed(D("100"), D("150"), D("100")))   # sudah tercapai sebelumnya
        self.assertFalse(crossed(D("50"), D("99"), D("100")))
        self.assertFalse(crossed(D("150"), D("90"), D("100")))    # turun (pengeluaran)


if __name__ == "__main__":
    unittest.main()
