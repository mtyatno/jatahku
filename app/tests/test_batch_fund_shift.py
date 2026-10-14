"""Pencatatan multi-item via Telegram dengan tawaran geser dana untuk setiap
amplop yang kurang dana.

Run: python -m unittest app.tests.test_batch_fund_shift -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import unittest
import uuid
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import configure_mappers

from app.bot import batch_cmd
from app.models.models import Allocation, Income, Transaction
from app.services.behavior import BehaviorCheckResult
from app.tests.fakes import FakeResult

configure_mappers()

TG_ID = 777
USER = SimpleNamespace(id=uuid.uuid4(), payday_day=1, timezone=None)
HID = uuid.uuid4()
KEY = "k1k2k3k4"


def env(name, emoji="📁", purpose="expense"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, emoji=emoji, purpose=purpose)


class FakeRedis:
    def __init__(self, store=None):
        self.store = dict(store or {})

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def get(self, k):
        v = self.store.get(k)
        return v.encode() if isinstance(v, str) else v

    async def delete(self, k):
        self.store.pop(k, None)

    async def aclose(self):
        pass

    def batch(self):
        return json.loads(self.store[f"batch:{KEY}"])


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class World:
    """Saldo amplop yang ikut berubah saat Allocation/Transaction ditambahkan,
    plus check_behavior palsu yang membaca saldo itu."""

    def __init__(self, *rows):
        self.envs = [e for e, _, _ in rows]
        self.bal = {e.id: D(str(b)) for e, b, _ in rows}
        self.res = {e.id: D(str(r)) for e, _, r in rows}
        self.locked = set()
        self.added = []
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=FakeResult(USER))
        self.db.add = MagicMock(side_effect=self._add)
        self.db.flush = AsyncMock()
        self.db.commit = AsyncMock()
        self.db.rollback = AsyncMock()
        self.redis = FakeRedis()

    def _add(self, obj):
        self.added.append(obj)
        if isinstance(obj, Allocation):
            self.bal[obj.envelope_id] += obj.amount
        elif isinstance(obj, Transaction):
            self.bal[obj.envelope_id] -= obj.amount

    def of(self, cls):
        return [o for o in self.added if isinstance(o, cls)]

    async def envs_with_spent(self, hid, db, user_id=None, payday_day=1):
        return [{"envelope": e, "remaining": self.bal[e.id], "reserved": self.res[e.id],
                 "free": self.bal[e.id] - self.res[e.id], "spent": D("0"), "allocated": D("0")}
                for e in self.envs]

    async def check(self, env_id, user_id, amount, db):
        if env_id in self.locked:
            return BehaviorCheckResult.blocked("locked", "Amplop sedang dikunci.")
        if self.bal[env_id] <= 0:
            return BehaviorCheckResult.blocked("not_funded", "Belum ada dana.")
        if amount > self.bal[env_id]:
            return BehaviorCheckResult.blocked("insufficient", "Dana tidak cukup.",
                                               available=self.bal[env_id], requested=amount)
        return BehaviorCheckResult.ok()

    def patches(self, matches=None):
        ps = [
            patch("redis.asyncio.from_url", return_value=self.redis),
            patch.object(batch_cmd, "AsyncSessionLocal", new=lambda: FakeSession(self.db)),
            patch.object(batch_cmd, "get_or_create_user", new=AsyncMock(return_value=USER)),
            patch.object(batch_cmd, "_is_setup_complete", new=AsyncMock(return_value=(True, "ok"))),
            patch.object(batch_cmd, "get_household_id", new=AsyncMock(return_value=HID)),
            patch.object(batch_cmd, "get_envelopes_with_spent", new=self.envs_with_spent),
            patch.object(batch_cmd, "check_behavior", new=self.check),
            patch.object(batch_cmd, "save_learned_keywords", new=AsyncMock()),
            patch.object(batch_cmd, "create_pending_transaction", new=AsyncMock()),
        ]
        if matches is not None:
            ps.append(patch.object(batch_cmd, "find_best_envelope",
                                   new=AsyncMock(side_effect=[(m, True) for m in matches])))
        return ps

    async def send(self, items, matches):
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.reply_text = AsyncMock()
        ps = self.patches(matches)
        for p in ps:
            p.start()
        try:
            await batch_cmd.handle_multi_expense(update, None, items)
        finally:
            for p in ps:
                p.stop()
        return update.message.reply_text

    async def tap(self, data, user_id=TG_ID):
        q = MagicMock()
        q.data = data
        q.from_user = SimpleNamespace(id=user_id)
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        update = SimpleNamespace(callback_query=q)
        handler = (batch_cmd.handle_batch_shift_callback if data.startswith("bshift_")
                   else batch_cmd.handle_batch_callback)
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            await handler(update, None)
        finally:
            for p in ps:
                p.stop()
        return q.edit_message_text

    def seed(self, queue, pos=0, stage="pick", sources=None, user_id=USER.id):
        self.redis.store[f"batch:{KEY}"] = json.dumps({
            "user_id": str(user_id), "queue": queue, "pos": pos, "stage": stage,
            "sources": sources or [], "auto_lines": [], "notes": [], "total": 0,
        })


def buttons(reply_markup):
    return [row[0].callback_data for row in reply_markup.inline_keyboard]


# ── Rencana (murni) ──────────────────────────────────────────────────────────

class PlanTests(unittest.TestCase):
    def test_running_balance_across_items_in_same_envelope(self):
        makan = env("Makan")
        items = [(D("30000"), "sate", makan), (D("10000"), "es teh", makan),
                 (D("15000"), "martabak", makan), (D("5000"), "parkir", None)]
        record, queue = batch_cmd.plan_items(items, {str(makan.id): D("45000")})
        self.assertEqual([d for _, d, _ in record], ["sate", "es teh"])
        self.assertEqual(queue, [
            {"amount": 15000, "desc": "martabak", "env_id": str(makan.id)},  # 30+10 sudah memakai 40 dari 45
            {"amount": 5000, "desc": "parkir", "env_id": None},
        ])

    def test_unfunded_envelope_is_queued(self):
        jajan = env("Jajan")
        record, queue = batch_cmd.plan_items([(D("1"), "x", jajan)], {str(jajan.id): D("-5000")})
        self.assertEqual(record, [])
        self.assertEqual(queue[0]["env_id"], str(jajan.id))


# ── Pesan multi-item ─────────────────────────────────────────────────────────

class MultiMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.makan, self.jajan, self.transport = env("Makan", "🍔"), env("Jajan", "☕"), env("Transport", "🚌")

    async def test_all_funded_records_everything_without_queue(self):
        w = World((self.makan, 100000, 0), (self.jajan, 50000, 0))
        reply = await w.send([(D("30000"), "sate"), (D("20000"), "kopi")], [self.makan, self.jajan])
        self.assertEqual(len(w.of(Transaction)), 2)
        text = reply.call_args.args[0]
        self.assertIn("2 transaksi dicatat", text)
        self.assertIn("Total: <b>Rp50rb</b>", text)
        self.assertIsNone(reply.call_args.kwargs["reply_markup"])
        self.assertEqual(w.redis.store, {})

    async def test_short_envelope_gets_shift_offer_after_funded_items_recorded(self):
        w = World((self.makan, 100000, 0), (self.jajan, 20000, 0), (self.transport, 40000, 0))
        reply = await w.send([(D("30000"), "sate"), (D("35000"), "kopi <3>")], [self.makan, self.jajan])

        self.assertEqual([t.description for t in w.of(Transaction)], ["sate"])
        text = reply.call_args.args[0]
        self.assertIn("🍔 Makan: Rp30rb — sate", text)       # item yang cukup sudah tercatat
        self.assertIn("Kurang <b>Rp15rb</b>", text)
        self.assertIn("kopi &lt;3&gt;", text)
        cbs = buttons(reply.call_args.kwargs["reply_markup"])
        key = cbs[0].split("_")[1]
        self.assertEqual(cbs, [f"bshift_{key}_0_0", f"bshift_{key}_0_1", f"bshift_{key}_0_skip"])
        self.assertTrue(all(len(c.encode()) <= 64 for c in cbs))
        state = json.loads(next(v for k, v in w.redis.store.items() if k.startswith("batch:")))
        self.assertEqual((state["pos"], state["stage"]), (0, "shift"))
        # Makan (bebas 70rb setelah sate) dan Transport (40rb) sama-sama cukup; terbesar dulu
        self.assertEqual(state["sources"], [str(self.makan.id), str(self.transport.id)])

    async def test_each_short_envelope_is_offered_in_turn(self):
        w = World((self.makan, 10000, 0), (self.jajan, 0, 0), (self.transport, 200000, 0))
        reply = await w.send([(D("30000"), "sate"), (D("20000"), "kopi")], [self.makan, self.jajan])
        self.assertEqual(w.of(Transaction), [])
        key = buttons(reply.call_args.kwargs["reply_markup"])[0].split("_")[1]

        # item 1: Makan kurang 20rb → geser dari Transport
        edit = await w.tap(f"bshift_{key}_0_0")
        self.assertIn("Kurang <b>Rp20rb</b>", edit.call_args.args[0])  # item 2: Jajan belum didanai
        self.assertIn("(2/2)", edit.call_args.args[0])
        edit = await w.tap(f"bshift_{key}_1_0")

        self.assertEqual([t.description for t in w.of(Transaction)], ["sate", "kopi"])
        self.assertEqual(len(w.of(Income)), 2)
        self.assertEqual(w.bal[self.transport.id], D("160000"))
        self.assertEqual((w.bal[self.makan.id], w.bal[self.jajan.id]), (D("0"), D("0")))
        text = edit.call_args.args[0]
        self.assertIn("2 transaksi dicatat", text)
        self.assertIn("🔁 +Rp20rb dari 🚌 Transport", text)
        self.assertIn("Total: <b>Rp50rb</b>", text)
        self.assertEqual(w.redis.store, {})

    async def test_no_source_can_cover_is_noted_and_rest_continues(self):
        w = World((self.makan, 100000, 0), (self.jajan, 0, 0))
        reply = await w.send([(D("500000"), "tv"), (D("20000"), "kopi")], [self.jajan, self.makan])
        text = reply.call_args.args[0]
        self.assertIn("1 transaksi dicatat", text)
        self.assertIn("kurang Rp500rb", text)
        self.assertIn("Tidak dicatat", text)
        self.assertEqual(w.redis.store, {})


# ── Tombol antrean ───────────────────────────────────────────────────────────

class CallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.makan, self.jajan = env("Makan", "🍔"), env("Jajan", "☕")
        self.w = World((self.makan, 100000, 0), (self.jajan, 20000, 0))

    async def test_picked_envelope_short_turns_into_shift_offer(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": None}])
        edit = await self.w.tap(f"batch_{KEY}_0_{self.jajan.id}")
        self.assertEqual(self.w.of(Transaction), [])
        self.assertIn("Kurang <b>Rp15rb</b>", edit.call_args.args[0])
        st = self.w.redis.batch()
        self.assertEqual((st["stage"], st["sources"]), ("shift", [str(self.makan.id)]))

        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        txn, = self.w.of(Transaction)
        self.assertEqual((txn.envelope_id, txn.amount), (self.jajan.id, D("35000")))
        self.assertIn("1 transaksi dicatat", edit.call_args.args[0])

    async def test_picked_envelope_with_funds_records(self):
        self.w.seed([{"amount": 15000, "desc": "kopi", "env_id": None}])
        edit = await self.w.tap(f"batch_{KEY}_0_{self.jajan.id}")
        self.assertEqual(len(self.w.of(Transaction)), 1)
        self.assertIn("1 transaksi dicatat", edit.call_args.args[0])

    async def test_cannot_pick_inaccessible_envelope(self):
        self.w.seed([{"amount": 15000, "desc": "kopi", "env_id": None}])
        edit = await self.w.tap(f"batch_{KEY}_0_{uuid.uuid4()}")
        self.assertEqual(self.w.of(Transaction), [])
        self.assertIn("tidak tersedia", edit.call_args.args[0])
        self.assertEqual(self.w.redis.batch()["pos"], 0)

    async def test_source_drained_meanwhile_asks_again(self):
        transport = env("Transport", "🚌")
        self.w.envs.append(transport)
        self.w.bal[transport.id], self.w.res[transport.id] = D("30000"), D("0")
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id), str(transport.id)])
        self.w.bal[self.makan.id] = D("5000")
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        self.assertEqual(self.w.added, [])
        self.assertIn("tidak cukup. Pilih amplop lain", edit.call_args.args[0])
        self.assertEqual(self.w.redis.batch()["sources"], [str(transport.id)])  # tawaran disegarkan

    async def test_source_drained_and_nothing_else_is_noted(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id)])
        self.w.bal[self.makan.id] = D("5000")
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        self.assertEqual(self.w.added, [])
        self.assertIn("tidak ada amplop lain dengan dana bebas cukup", edit.call_args.args[0])

    async def test_skip_shift_moves_on_without_transfer(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id)])
        edit = await self.w.tap(f"bshift_{KEY}_0_skip")
        self.assertEqual(self.w.added, [])
        self.assertIn("dilewati", edit.call_args.args[0])
        self.assertEqual(self.w.redis.store, {})

    async def test_locked_after_shift_rolls_back(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id)])
        real_add = self.w._add

        def add_then_lock(obj):
            real_add(obj)
            if isinstance(obj, Allocation):
                self.w.locked.add(self.jajan.id)
        self.w.db.add.side_effect = add_then_lock
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        self.w.db.rollback.assert_awaited_once()
        self.assertEqual(self.w.of(Transaction), [])
        self.assertIn("Dana tidak digeser", edit.call_args.args[0])

    async def test_stale_or_double_tap_does_nothing(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)},
                     {"amount": 5000, "desc": "parkir", "env_id": None}],
                    pos=1, stage="pick")
        edit = await self.w.tap(f"bshift_{KEY}_0_0")  # tombol item 0 sudah diproses
        edit.assert_not_awaited()
        self.assertEqual(self.w.added, [])

    async def test_concurrent_tap_is_locked_out(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id)])
        self.w.redis.store[f"batchlock:{KEY}"] = "1"
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        edit.assert_not_awaited()
        self.assertEqual(self.w.added, [])

    async def test_other_user_cannot_drive_the_queue(self):
        self.w.seed([{"amount": 35000, "desc": "kopi", "env_id": str(self.jajan.id)}],
                    stage="shift", sources=[str(self.makan.id)], user_id=uuid.uuid4())
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        edit.assert_not_awaited()
        self.assertEqual(self.w.added, [])

    async def test_expired_session(self):
        edit = await self.w.tap(f"bshift_{KEY}_0_0")
        self.assertIn("expired", edit.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
