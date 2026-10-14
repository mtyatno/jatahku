"""Geser dana dari amplop lain saat pengeluaran via Telegram kurang dana
(padanan FundEnvelopeModal di web).

Run: python -m unittest app.tests.test_fund_shift -v
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

from app.bot import handlers
from app.models.models import Allocation, Income, Transaction
from app.services.behavior import BehaviorCheckResult
from app.services.fund_shift import (
    compute_shortfall, pick_sources, record_topup, record_transfer, transfer_error,
)
from app.tests.fakes import FakeResult

configure_mappers()

TG_ID = 777
USER = SimpleNamespace(id=uuid.uuid4(), payday_day=1, timezone=None)
HID = uuid.uuid4()


def env(name, purpose="expense", emoji="📁"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, emoji=emoji, purpose=purpose,
                           budget_amount=D("0"))


def row(e, remaining, reserved=0):
    remaining, reserved = D(str(remaining)), D(str(reserved))
    return {"envelope": e, "spent": D("0"), "allocated": remaining, "remaining": remaining,
            "reserved": reserved, "free": remaining - reserved}


class FakeRedis:
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.setex = AsyncMock(side_effect=lambda k, ttl, v: self.store.__setitem__(k, v))
        self.delete = AsyncMock(side_effect=lambda k: self.store.pop(k, None))
        self.getdel = AsyncMock(side_effect=lambda k: self.store.pop(k, None))
        self.aclose = AsyncMock()


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def fake_db():
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult(USER))  # lookup user by telegram_id
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.savepoint = MagicMock(rollback=AsyncMock())
    db.begin_nested = AsyncMock(return_value=db.savepoint)
    return db


def fake_query(data):
    q = MagicMock()
    q.data = data
    q.from_user = SimpleNamespace(id=TG_ID)
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return SimpleNamespace(callback_query=q), q


# ── Logika murni ─────────────────────────────────────────────────────────────

class ShortfallTests(unittest.TestCase):
    def test_shortfall_is_amount_minus_remaining(self):
        self.assertEqual(compute_shortfall(D("20000"), D("35000")), D("15000"))

    def test_negative_remaining_adds_to_shortfall(self):
        self.assertEqual(compute_shortfall(D("-5000"), D("10000")), D("15000"))

    def test_enough_funds_means_no_shortfall(self):
        self.assertEqual(compute_shortfall(D("50000"), D("35000")), D("0"))


class PickSourcesTests(unittest.TestCase):
    def setUp(self):
        self.target = env("Jajan")
        self.makan = env("Makan")
        self.transport = env("Transport")
        self.tabungan = env("Tabungan", purpose="saving")
        self.langganan = env("Langganan")

    def test_excludes_target_and_envelopes_that_cannot_cover(self):
        data = [row(self.target, 100000), row(self.makan, 10000), row(self.transport, 50000)]
        out = pick_sources(data, self.target.id, D("15000"))
        self.assertEqual([s["envelope"] for s in out], [self.transport])

    def test_uses_remaining_like_the_web_modal(self):
        # Modal web membatasi geser dengan sisa amplop sumber (bukan dana bebas)
        data = [row(self.target, 0), row(self.langganan, 100000, reserved=95000)]
        out = pick_sources(data, self.target.id, D("15000"))
        self.assertEqual([s["envelope"] for s in out], [self.langganan])

    def test_largest_remaining_first_any_purpose(self):
        # Urutan pilihan modal web: sisa terbesar dulu; amplop tabungan juga sumber sah
        data = [row(self.target, 0), row(self.tabungan, 900000),
                row(self.makan, 30000), row(self.transport, 80000)]
        out = pick_sources(data, self.target.id, D("15000"))
        self.assertEqual([s["envelope"] for s in out], [self.tabungan, self.transport, self.makan])

    def test_limit_and_zero_shortfall(self):
        data = [row(env(f"E{i}"), 100000) for i in range(6)]
        self.assertEqual(len(pick_sources(data, self.target.id, D("1000"))), 4)
        self.assertEqual(pick_sources(data, self.target.id, D("0")), [])


class RecordTransferTests(unittest.TestCase):
    def test_net_zero_income_with_paired_allocations(self):
        db = MagicMock()
        src, dst = env("Makan"), env("Jajan")
        income = record_transfer(db, HID, USER.id, src, dst, D("15000"))
        added = [c.args[0] for c in db.add.call_args_list]
        self.assertIsInstance(added[0], Income)
        self.assertEqual(income.amount, D("0"))
        self.assertEqual(income.description, "Transfer: Makan → Jajan")
        allocs = {a.envelope_id: a for a in added[1:]}
        self.assertTrue(all(isinstance(a, Allocation) for a in allocs.values()))
        self.assertEqual(allocs[src.id].amount, D("-15000"))
        self.assertEqual(allocs[dst.id].amount, D("15000"))
        self.assertTrue(all(a.income_id == income.id for a in allocs.values()))


class TransferRuleTests(unittest.TestCase):
    """Aturan yang juga ditegakkan POST /envelopes/transfer."""

    def test_valid(self):
        self.assertIsNone(transfer_error(row(env("A"), 50000), row(env("B"), 0), D("50000")))

    def test_more_than_source_remaining(self):
        err = transfer_error(row(env("Makan"), 50000), row(env("B"), 0), D("50001"))
        self.assertEqual(err, "Maksimal transfer dari Makan: Rp50.000")

    def test_missing_same_or_nonpositive(self):
        a = row(env("A"), 50000)
        self.assertEqual(transfer_error(None, a, D("1")), "Amplop tidak ditemukan")
        self.assertEqual(transfer_error(a, a, D("1")), "Amplop sumber dan tujuan tidak boleh sama")
        self.assertEqual(transfer_error(a, row(env("B"), 0), D("0")), "Jumlah harus lebih dari 0")

    def test_accepts_web_summary_rows(self):
        e = env("Makan")
        web_row = {"id": e.id, "name": "Makan", "remaining": D("1000")}
        self.assertIn("Maksimal", transfer_error(web_row, {"id": uuid.uuid4(), "name": "B", "remaining": D("0")}, D("2000")))


class RecordTopupTests(unittest.TestCase):
    def test_income_fully_allocated_like_web_topup_tab(self):
        db = MagicMock()
        dst = env("Jajan")
        income = record_topup(db, HID, USER.id, dst, D("15000"))
        added = [c.args[0] for c in db.add.call_args_list]
        self.assertEqual((income.amount, income.description), (D("15000"), "Top-up Jajan"))
        alloc, = [a for a in added if isinstance(a, Allocation)]
        self.assertEqual((alloc.envelope_id, alloc.amount, alloc.income_id), (dst.id, D("15000"), income.id))


# ── Tawaran di bot ───────────────────────────────────────────────────────────

class OfferTests(unittest.IsolatedAsyncioTestCase):
    async def test_offer_lists_sources_and_stores_payload(self):
        target, makan = env("Jajan", emoji="☕"), env("Makan", emoji="🍔")
        data = [row(target, 20000), row(makan, 100000)]
        redis = FakeRedis()
        send = AsyncMock()
        with patch.object(handlers, "get_envelopes_with_spent", new=AsyncMock(return_value=data)), \
             patch("redis.asyncio.from_url", return_value=redis):
            await handlers._send_fund_shift_offer(send, str(TG_ID), USER, HID, target,
                                                  D("35000"), "kopi <susu>", MagicMock())

        text = send.call_args.args[0]
        self.assertIn("Kurang <b>Rp15rb</b>", text)
        self.assertIn("kopi &lt;susu&gt;", text)  # deskripsi user di-escape untuk HTML
        buttons = send.call_args.kwargs["reply_markup"].inline_keyboard
        self.assertIn("Makan (sisa Rp100rb)", buttons[0][0].text)
        self.assertTrue(buttons[0][0].callback_data.startswith("fshift:"))
        self.assertIn("Top-up pemasukan Rp15rb", buttons[1][0].text)
        self.assertTrue(buttons[1][0].callback_data.endswith(":t"))
        self.assertTrue(buttons[-1][0].callback_data.endswith(":x"))
        self.assertLessEqual(len(buttons[0][0].callback_data.encode()), 64)

        (key, payload), = redis.store.items()
        self.assertTrue(key.startswith(f"fshift:{TG_ID}:"))
        payload = json.loads(payload)
        self.assertEqual(payload["sources"], [str(makan.id)])
        self.assertEqual(payload["amount"], "35000")

    async def test_no_source_can_cover_still_offers_topup(self):
        target = env("Jajan")
        data = [row(target, 0), row(env("Makan"), 1000)]
        redis = FakeRedis()
        send = AsyncMock()
        with patch.object(handlers, "get_envelopes_with_spent", new=AsyncMock(return_value=data)), \
             patch("redis.asyncio.from_url", return_value=redis):
            await handlers._send_fund_shift_offer(send, str(TG_ID), USER, HID, target,
                                                  D("35000"), "kopi", MagicMock())
        self.assertIn("Tidak ada amplop lain yang sisanya cukup", send.call_args.args[0])
        cbs = [r[0].callback_data for r in send.call_args.kwargs["reply_markup"].inline_keyboard]
        self.assertEqual([c.rsplit(":", 1)[1] for c in cbs], ["t", "x"])
        self.assertEqual(json.loads(next(iter(redis.store.values())))["sources"], [])


# ── Callback ─────────────────────────────────────────────────────────────────

class CallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target, self.makan = env("Jajan", emoji="☕"), env("Makan", emoji="🍔")
        self.token = "abcd1234abcd1234"
        self.key = f"fshift:{TG_ID}:{self.token}"
        self.redis = FakeRedis({self.key: json.dumps({
            "envelope_id": str(self.target.id), "amount": "35000",
            "description": "kopi", "sources": [str(self.makan.id)],
        })})
        self.db = fake_db()

    def patches(self, before, after=None, check=None):
        after = after or before
        return [
            patch("redis.asyncio.from_url", return_value=self.redis),
            patch.object(handlers, "AsyncSessionLocal", new=lambda: FakeSession(self.db)),
            patch.object(handlers, "get_household_id", new=AsyncMock(return_value=HID)),
            patch.object(handlers, "get_envelopes_with_spent", new=AsyncMock(side_effect=[before, after])),
            patch.object(handlers, "check_expense", new=AsyncMock(return_value=check or BehaviorCheckResult.ok())),
            patch.object(handlers, "after_expense_recorded", new=AsyncMock(return_value=None)),
        ]

    async def run_cb(self, data, patches):
        update, q = fake_query(data)
        for p in patches:
            p.start()
        try:
            await handlers.handle_fund_shift_callback(update, None)
        finally:
            for p in patches:
                p.stop()
        return q

    def added(self, cls):
        return [c.args[0] for c in self.db.add.call_args_list if isinstance(c.args[0], cls)]

    async def test_shift_then_record_in_one_commit(self):
        before = [row(self.target, 20000), row(self.makan, 100000)]
        after = [row(self.target, 0), row(self.makan, 85000)]
        q = await self.run_cb(f"fshift:{self.token}:0", self.patches(before, after))

        self.assertEqual(len(self.added(Income)), 1)
        allocs = {a.envelope_id: a.amount for a in self.added(Allocation)}
        self.assertEqual(allocs, {self.makan.id: D("-15000"), self.target.id: D("15000")})
        txn, = self.added(Transaction)
        self.assertEqual((txn.envelope_id, txn.amount), (self.target.id, D("35000")))
        self.db.commit.assert_awaited_once()
        text = q.edit_message_text.call_args.args[0]
        self.assertIn("Rp15rb digeser dari 🍔 Makan → ☕ Jajan", text)
        self.assertIn("Makan · sisa <b>Rp85rb</b>", text)
        self.assertNotIn(self.key, self.redis.store)

    async def test_source_drained_meanwhile_moves_nothing(self):
        before = [row(self.target, 20000), row(self.makan, 5000)]
        q = await self.run_cb(f"fshift:{self.token}:0", self.patches(before))
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()
        self.assertIn("Maksimal transfer dari Makan: Rp5.000", q.edit_message_text.call_args.args[0])

    async def test_topup_records_income_then_expense(self):
        before = [row(self.target, 20000), row(self.makan, 0)]
        after = [row(self.target, 0), row(self.makan, 0)]
        q = await self.run_cb(f"fshift:{self.token}:t", self.patches(before, after))
        inc, = self.added(Income)
        self.assertEqual((inc.amount, inc.description), (D("15000"), "Top-up Jajan"))
        alloc, = self.added(Allocation)
        self.assertEqual((alloc.envelope_id, alloc.amount), (self.target.id, D("15000")))
        self.assertEqual(len(self.added(Transaction)), 1)
        self.db.commit.assert_awaited_once()
        text = q.edit_message_text.call_args.args[0]
        self.assertIn("💰 Top-up pemasukan Rp15rb → ☕ Jajan", text)
        self.assertNotIn("Makan", text)

    async def test_topup_undone_when_blocked(self):
        before = [row(self.target, 20000), row(self.makan, 0)]
        limit = BehaviorCheckResult.blocked("plan_limit", "Limit 50 transaksi/bulan tercapai.")
        q = await self.run_cb(f"fshift:{self.token}:t", self.patches(before, check=limit))
        self.db.savepoint.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()
        self.assertIn("Pemasukan tidak dicatat", q.edit_message_text.call_args.args[0])

    async def test_target_already_topped_up_records_without_transfer(self):
        before = [row(self.target, 50000), row(self.makan, 100000)]
        await self.run_cb(f"fshift:{self.token}:0", self.patches(before))
        self.assertEqual(self.added(Income), [])
        self.assertEqual(len(self.added(Transaction)), 1)

    async def test_other_block_rolls_back_transfer(self):
        before = [row(self.target, 20000), row(self.makan, 100000)]
        locked = BehaviorCheckResult.blocked("locked", "Amplop Jajan sedang dikunci.")
        q = await self.run_cb(f"fshift:{self.token}:0", self.patches(before, check=locked))
        self.db.savepoint.rollback.assert_awaited_once()
        self.db.rollback.assert_not_awaited()  # rollback penuh meng-expire objek sesi
        self.db.commit.assert_not_awaited()
        self.assertEqual(self.added(Transaction), [])
        self.assertIn("Dana tidak digeser", q.edit_message_text.call_args.args[0])

    async def test_cancel_deletes_offer(self):
        q = await self.run_cb(f"fshift:{self.token}:x", self.patches([]))
        self.assertEqual(self.redis.store, {})
        self.db.add.assert_not_called()
        self.assertIn("dibatalkan", q.edit_message_text.call_args.args[0])

    async def test_second_tap_is_expired(self):
        self.redis.store.clear()
        q = await self.run_cb(f"fshift:{self.token}:0", self.patches([]))
        self.db.add.assert_not_called()
        self.assertIn("expired", q.edit_message_text.call_args.args[0])

    async def test_offer_is_bound_to_the_telegram_user(self):
        update, q = fake_query(f"fshift:{self.token}:0")
        q.from_user = SimpleNamespace(id=999)  # pengguna lain di grup tidak bisa memakai tombol ini
        with patch("redis.asyncio.from_url", return_value=self.redis):
            await handlers.handle_fund_shift_callback(update, None)
        self.assertIn(self.key, self.redis.store)
        self.assertIn("expired", q.edit_message_text.call_args.args[0])


class WiringTests(unittest.IsolatedAsyncioTestCase):
    """Pesan biasa yang terblokir kurang dana → tawaran geser dana, bukan pesan buntu."""

    async def check_message(self, check):
        target = env("Jajan")
        update = MagicMock()
        update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
        update.message.text = "kopi 35k"
        update.message.reply_text = AsyncMock()
        rl = MagicMock(incr=AsyncMock(return_value=1), expire=AsyncMock(), aclose=AsyncMock())
        offer = AsyncMock()
        with patch("redis.asyncio.from_url", return_value=rl), \
             patch.object(handlers, "AsyncSessionLocal", new=lambda: FakeSession(fake_db())), \
             patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=USER)), \
             patch.object(handlers, "_is_setup_complete", new=AsyncMock(return_value=(True, "ok"))), \
             patch.object(handlers, "get_household_id", new=AsyncMock(return_value=HID)), \
             patch.object(handlers, "find_best_envelope", new=AsyncMock(return_value=(target, True))), \
             patch.object(handlers, "check_expense", new=AsyncMock(return_value=check)), \
             patch.object(handlers, "_send_fund_shift_offer", new=offer):
            await handlers.handle_message(update, None)
        return offer, target

    async def test_insufficient_triggers_offer(self):
        check = BehaviorCheckResult.blocked("insufficient", "x", available=D("20000"), requested=D("35000"))
        offer, target = await self.check_message(check)
        offer.assert_awaited_once()
        self.assertEqual(offer.call_args.args[4:7], (target, D("35000"), "kopi"))

    async def test_not_funded_triggers_offer(self):
        offer, _ = await self.check_message(BehaviorCheckResult.blocked("not_funded", "x"))
        offer.assert_awaited_once()

    async def test_saving_envelope_and_plan_limit_are_refused_like_web(self):
        for check_type, expect in [("not_spendable", "🏦"), ("plan_limit", "jatahku.com/settings")]:
            offer = AsyncMock()
            update = MagicMock()
            update.effective_user = SimpleNamespace(id=TG_ID, first_name="Tes")
            update.message.text = "kopi 35k"
            update.message.reply_text = AsyncMock()
            rl = MagicMock(incr=AsyncMock(return_value=1), expire=AsyncMock(), aclose=AsyncMock())
            db = fake_db()
            with patch("redis.asyncio.from_url", return_value=rl), \
                 patch.object(handlers, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
                 patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=USER)), \
                 patch.object(handlers, "_is_setup_complete", new=AsyncMock(return_value=(True, "ok"))), \
                 patch.object(handlers, "get_household_id", new=AsyncMock(return_value=HID)), \
                 patch.object(handlers, "find_best_envelope", new=AsyncMock(return_value=(env("Tabungan"), True))), \
                 patch.object(handlers, "check_expense",
                              new=AsyncMock(return_value=BehaviorCheckResult.blocked(check_type, "ditolak"))), \
                 patch.object(handlers, "_send_fund_shift_offer", new=offer):
                await handlers.handle_message(update, None)
            offer.assert_not_awaited()
            db.add.assert_not_called()
            self.assertIn(expect, update.message.reply_text.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
