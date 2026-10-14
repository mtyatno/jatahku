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
    Transaction, User,
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
        q.from_user = SimpleNamespace(id=TG_ID)
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        update = SimpleNamespace(callback_query=q)
        if data.startswith("bshift_"):
            fn = batch_cmd.handle_batch_shift_callback
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

        # kopi: geser 20rb, tapi limit harian Jajan 10rb → transfer dibatalkan (savepoint),
        # lalu antrean lanjut ke xyz — di sinilah rollback penuh dulu memicu MissingGreenlet
        call = await self.tap(transport_btn)
        self.assertIn("Masuk ke amplop mana?", call.args[0])
        xyz_btn = next(r[0].callback_data for r in call.kwargs["reply_markup"].inline_keyboard
                       if "Transport" in r[0].text)

        call = await self.tap(xyz_btn)
        text = call.args[0]
        self.assertIn("3 transaksi dicatat", text)
        self.assertIn("🔁 +Rp20rb dari 📁 Transport", text)
        self.assertIn("mainan", text)
        self.assertIn("Melebihi limit harian", text)
        self.assertIn("Dana tidak digeser", text)
        self.assertIsNone(call.kwargs["reply_markup"])
        self.assertEqual(self.redis.store, {})

        self.assertEqual(await self.count(Transaction), 3)               # parkir, sate, xyz
        self.assertEqual(await self.count(Income, Income.amount == 0), 1)  # hanya geser untuk sate
        self.assertEqual(await self.remaining("Transport"), D("168000"))  # 200 − 5 − 20 − 7
        self.assertEqual(await self.remaining("Makan"), D("0"))
        self.assertEqual(await self.remaining("Jajan"), D("0"))
        self.assertEqual(await self.remaining("Hobi"), D("100000"))

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


if __name__ == "__main__":
    unittest.main()
