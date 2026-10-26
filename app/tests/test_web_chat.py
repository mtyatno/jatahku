"""Chat bot di webapp (app/bot/web_adapter.py + app/bot/channel.py):
- pesan & tombol webapp dijalankan oleh handler bot Telegram yang sama
- user dikenali lewat id chat web `web:<uuid>`, tidak pernah dibuat baru,
  dan id `web:` ditolak di luar kanal web
- transaksi dari chat web tercatat sebagai `webapp`
- hanya tombol yang benar-benar dikirim ke user itu yang bisa ditekan
- perintah akun khusus Telegram (/link, /unlink, /webapp) tidak jalan di web

Run: python -m unittest app.tests.test_web_chat -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import json
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select

from app.bot import behavior_cmd, channel, handlers, help_cmd, receipt_cmd, recurring_cmd, tglogin_cmd, web_adapter
from app.services.kotak_struk import intake, waiter
from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar
# Impor di luar event loop (lihat test_fund_shift_integration).
from app.services import streak as _streak, txn_nlp as _txn_nlp  # noqa: F401
from app.core.database import Base
from app.models.models import (
    Allocation, Envelope, Household, HouseholdMember, HouseholdRole, Income,
    PendingTransaction, PendingTransactionStatus, ReceiptScan, RecurringFrequency, RecurringTransaction,
    Transaction, TransactionSource, User,
)
from app.tests.fakes import FakeResult, db_with

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


class FakeRedis:
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def _check(self):
        if self.fail:
            raise ConnectionError("redis down")

    async def set(self, k, v, nx=False, ex=None):
        self._check()
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def setex(self, k, ttl, v):
        self.store[k] = v

    async def get(self, k):
        self._check()
        v = self.store.get(k)
        return v.encode() if isinstance(v, str) else v

    async def getdel(self, k):
        v = self.store.pop(k, None)
        return v.encode() if isinstance(v, str) else v

    async def delete(self, k):
        self.store.pop(k, None)

    async def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]

    async def expire(self, k, ttl):
        return True

    def pipeline(self):
        redis, ops = self, []

        class Pipe:
            def set(self, k, v, ex=None):
                ops.append(("set", k, v))

            def delete(self, k):
                ops.append(("delete", k))

            async def execute(self):
                redis._check()
                for op in ops:
                    if op[0] == "set":
                        redis.store[op[1]] = op[2]
                    else:
                        redis.store.pop(op[1], None)

        return Pipe()

    async def aclose(self):
        pass

    async def close(self):
        pass


def web_user(name="Sari Dewi"):
    return SimpleNamespace(id=uuid.uuid4(), name=name)


def btn_key(user, msg_id):
    return web_adapter.buttons_key(user.id, msg_id)


# ── Kanal & resolusi user ────────────────────────────────────────────────────

class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_id_is_rejected_outside_web_channel(self):
        db = db_with()
        self.assertIsNone(await channel.find_chat_user(f"web:{uuid.uuid4()}", db))
        db.execute.assert_not_called()

    async def test_web_id_looks_up_by_user_id_inside_web_channel(self):
        uid = uuid.uuid4()
        user = SimpleNamespace(id=uid)
        db = db_with(FakeResult(user))
        with channel.web_channel():
            found = await channel.find_chat_user(f"web:{uid}", db)
        self.assertIs(found, user)
        where = str(db.execute.call_args.args[0]).split("WHERE", 1)[1]
        self.assertIn("users.id", where)
        self.assertNotIn("telegram_id", where)

    async def test_malformed_web_id_is_rejected(self):
        db = db_with()
        with channel.web_channel():
            self.assertIsNone(await channel.find_chat_user("web:not-a-uuid", db))
        db.execute.assert_not_called()

    async def test_telegram_id_still_looks_up_by_telegram_id(self):
        user = SimpleNamespace(id=uuid.uuid4())
        db = db_with(FakeResult(user))
        self.assertIs(await channel.find_chat_user(12345, db), user)
        self.assertIn("telegram_id", str(db.execute.call_args.args[0]))

    def test_txn_source_follows_channel(self):
        self.assertEqual(channel.txn_source(), TransactionSource.telegram)
        with channel.web_channel():
            self.assertEqual(channel.txn_source(), TransactionSource.webapp)
        self.assertEqual(channel.txn_source(), TransactionSource.telegram)

    async def test_web_account_is_never_created_from_chat(self):
        db = db_with(FakeResult(None))
        with channel.web_channel():
            with self.assertRaises(LookupError):
                await handlers.get_or_create_user(f"web:{uuid.uuid4()}", "X", db)
        db.add.assert_not_called()
        db.commit.assert_not_called()


# ── Adapter (handler dipalsukan) ─────────────────────────────────────────────

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)
        self.user = web_user()

    def test_only_http_url_buttons_are_forwarded(self):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("ok", url="https://jatahku.com/upgrade")],
            [InlineKeyboardButton("jahat", url="javascript:alert(1)")],
        ])
        self.assertEqual(web_adapter.serialize_markup(markup),
                         [[{"text": "ok", "url": "https://jatahku.com/upgrade"}]])

    def test_parse_command(self):
        self.assertEqual(web_adapter.parse_command("/Status@JatahkuBot a b"), ("status", ["a", "b"]))
        self.assertEqual(web_adapter.parse_command("/amplop_baru Makan 1jt"), ("amplop_baru", ["Makan", "1jt"]))
        self.assertIsNone(web_adapter.parse_command("kopi 35k"))
        self.assertIsNone(web_adapter.parse_command("/"))
        self.assertIsNone(web_adapter.parse_command("/<script>"))

    async def test_text_goes_to_bot_message_handler_and_buttons_are_recorded(self):
        seen = {}

        async def fake_handle_message(update, context):
            seen["user_id"] = update.effective_user.id
            seen["first_name"] = update.effective_user.first_name
            seen["text"] = update.message.text
            seen["source"] = channel.txn_source()
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            await update.message.reply_text(
                "💰 <b>Rp35rb</b> — kopi\n\nMasuk ke amplop mana?", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Makan", callback_data="t_ab12_0")]]),
            )

        with patch.object(handlers, "handle_message", new=fake_handle_message):
            ops = await web_adapter.run_message(self.user, "  kopi 35k ")

        self.assertEqual(seen, {"user_id": f"web:{self.user.id}", "first_name": "Sari",
                                "text": "kopi 35k", "source": TransactionSource.webapp})
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual((op["type"], op["format"]), ("message", "html"))
        self.assertEqual(op["buttons"], [[{"text": "Makan", "data": "t_ab12_0"}]])
        self.assertEqual(json.loads(self.redis.store[btn_key(self.user, op["id"])]), ["t_ab12_0"])
        # Kanal kembali ke Telegram setelah request selesai
        self.assertFalse(channel.is_web())

    async def test_telegram_only_commands_do_not_run(self):
        for cmd in ("/link ABC123", "/unlink", "/webapp"):
            ops = await web_adapter.run_message(self.user, cmd)
            self.assertEqual(len(ops), 1)
            self.assertIn("khusus untuk Telegram", ops[0]["text"])

    async def test_start_ignores_deep_link_args(self):
        start = AsyncMock()
        with patch.object(handlers, "bot_commands", return_value={"start": start}):
            await web_adapter.run_message(self.user, "/start link_ABC123")
        self.assertEqual(start.call_args.args[1].args, [])

    async def test_command_args_are_passed(self):
        cmd = AsyncMock()
        with patch.object(handlers, "bot_commands", return_value={"setlimit": cmd}):
            await web_adapter.run_message(self.user, "/setlimit Jajan 50k")
        self.assertEqual(cmd.call_args.args[1].args, ["Jajan", "50k"])

    async def test_unknown_command_gets_a_reply(self):
        ops = await web_adapter.run_message(self.user, "/entahlah")
        self.assertIn("tidak dikenal", ops[0]["text"])

    async def test_handler_crash_becomes_friendly_reply(self):
        with patch.object(handlers, "handle_message", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with self.assertLogs("jatahku.webchat", level="ERROR"):
                ops = await web_adapter.run_message(self.user, "kopi 35k")
        self.assertEqual(ops[0]["text"], web_adapter.ERROR_REPLY)
        self.assertFalse(channel.is_web())

    async def test_button_not_sent_to_this_user_is_rejected(self):
        self.redis.store[btn_key(self.user, "aa11")] = json.dumps(["t_ab12_0"])
        cb = AsyncMock()
        with patch.object(handlers, "bot_callbacks", return_value=[(r"^t_", cb), (r"^cool_", cb)]):
            ops = await web_adapter.run_action(self.user, "aa11", "cool_confirm_123")  # dipalsukan
            ops2 = await web_adapter.run_action(web_user(), "aa11", "t_ab12_0")      # user lain
        cb.assert_not_called()
        for o in (ops, ops2):
            self.assertEqual(o[0], {"type": "toast", "text": web_adapter.STALE_BUTTON})
            self.assertEqual(o[1], {"type": "buttons", "id": "aa11", "buttons": []})

    async def test_issued_button_runs_callback_and_edit_replaces_buttons(self):
        self.redis.store[btn_key(self.user, "aa11")] = json.dumps(["t_ab12_0"])

        async def cb(update, context):
            q = update.callback_query
            assert update.effective_user.id == f"web:{self.user.id}"
            assert channel.is_web()
            await q.answer("Sip")
            await q.edit_message_text("✅ *Tercatat*", parse_mode="Markdown")

        with patch.object(handlers, "bot_callbacks", return_value=[(r"^t_", cb)]):
            ops = await web_adapter.run_action(self.user, "aa11", "t_ab12_0")
        self.assertEqual(ops, [
            {"type": "toast", "text": "Sip"},
            {"type": "edit", "id": "aa11", "text": "✅ *Tercatat*", "format": "markdown", "buttons": []},
        ])
        # Edit tanpa tombol (seperti Telegram) → tombol lama tidak bisa ditekan lagi
        self.assertNotIn(btn_key(self.user, "aa11"), self.redis.store)

    async def test_telegram_only_callback_is_rejected_even_if_issued(self):
        self.redis.store[btn_key(self.user, "aa11")] = json.dumps(["merge_x", "unlink_y"])
        cb = AsyncMock()
        with patch.object(handlers, "bot_callbacks", return_value=[(r"^merge_", cb), (r"^unlink_", cb)]):
            for data in ("merge_x", "unlink_y"):
                ops = await web_adapter.run_action(self.user, "aa11", data)
                self.assertEqual(ops[0]["text"], web_adapter.STALE_BUTTON)
        cb.assert_not_called()

    async def test_buttons_fail_closed_when_redis_is_down(self):
        self.redis.fail = True
        cb = AsyncMock()
        with patch.object(handlers, "bot_callbacks", return_value=[(r"^t_", cb)]):
            ops = await web_adapter.run_action(self.user, "aa11", "t_ab12_0")
        cb.assert_not_called()
        self.assertEqual(ops, [{"type": "toast", "text": web_adapter.BUTTONS_UNAVAILABLE}])

    async def test_photo_for_account_without_envelopes_removes_status_message(self):
        fake_user = SimpleNamespace(id=self.user.id, name="Sari")

        class NoDb:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *a):
                return False

        with patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=fake_user)), \
             patch.object(handlers, "_is_setup_complete", new=AsyncMock(return_value=(False, "no_envelopes"))), \
             patch.object(receipt_cmd, "AsyncSessionLocal", new=NoDb):
            ops = await web_adapter.run_photo(self.user, b"x", "image/jpeg")
        self.assertEqual([o["type"] for o in ops], ["message", "delete", "message"])
        self.assertEqual(ops[1]["id"], ops[0]["id"])
        self.assertIn("Budget kamu belum disiapkan", ops[2]["text"])

    async def test_reply_from_callback_message_appends_new_message(self):
        # intent_learning memakai query.message sebagai update.message
        self.redis.store[btn_key(self.user, "aa11")] = json.dumps(["intentlearn:t:sisa"])

        async def cb(update, context):
            q = update.callback_query
            await q.edit_message_text("⏳")
            await q.message.reply_text("Sisa amplop kamu ...")

        with patch.object(handlers, "bot_callbacks", return_value=[(r"^intentlearn:", cb)]):
            ops = await web_adapter.run_action(self.user, "aa11", "intentlearn:t:sisa")
        self.assertEqual([o["type"] for o in ops], ["edit", "message"])
        self.assertEqual(ops[1]["format"], "plain")


# ── Endpoint foto ────────────────────────────────────────────────────────────

class PhotoEndpointTests(unittest.TestCase):
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import bot_chat
        from app.core.deps import get_current_user

        app = FastAPI()
        app.state.limiter = bot_chat.limiter
        app.include_router(bot_chat.router, prefix="/bot/chat")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), name="Sari")
        return TestClient(app)

    def test_photo_is_validated_like_receipt_button_and_forwarded(self):
        run = AsyncMock(return_value=[{"type": "toast", "text": "ok"}])
        with patch("app.api.routes.bot_chat.run_photo", new=run):
            c = self.client()
            res = c.post("/bot/chat/photo", files={"image": ("s.jpg", b"\xff\xd8x", "image/jpeg")},
                         data={"client_id": "u1abc"}, headers={"Authorization": "Bearer t"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"ops": [{"type": "toast", "text": "ok"}]})
            self.assertEqual(run.call_args.args[1:], (b"\xff\xd8x", "image/jpeg", "u1abc"))
            bad = c.post("/bot/chat/photo", files={"image": ("a.pdf", b"%PDF", "application/pdf")},
                         headers={"Authorization": "Bearer t"})
            self.assertEqual(bad.status_code, 415)
            bad_id = c.post("/bot/chat/photo", files={"image": ("s.jpg", b"x", "image/jpeg")},
                            data={"client_id": "../etc"}, headers={"Authorization": "Bearer t"})
            self.assertEqual(bad_id.status_code, 422)
        self.assertEqual(run.await_count, 1)


# ── Teks khusus kanal ────────────────────────────────────────────────────────

class ChannelTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_hides_telegram_account_commands_on_web(self):
        upd = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        await help_cmd.cmd_help(upd, None)
        self.assertIn("/webapp", upd.message.reply_text.call_args.args[0])
        with channel.web_channel():
            await help_cmd.cmd_help(upd, None)
        text = upd.message.reply_text.call_args.args[0]
        self.assertNotIn("/webapp", text)
        self.assertNotIn("/unlink", text)
        self.assertNotIn("{akun}", text)
        self.assertIn("/status", text)

    async def test_setup_needed_on_web_does_not_issue_login_link(self):
        upd = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(tglogin_cmd, "create_login_url", new=AsyncMock()) as login:
            with channel.web_channel():
                await tglogin_cmd.reply_setup_needed(upd, SimpleNamespace(id=uuid.uuid4()))
        login.assert_not_called()
        self.assertIn("Buat amplop", upd.effective_message.reply_text.call_args.args[0])


# ── Integrasi: handler asli + database sungguhan ─────────────────────────────

@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class WebChatIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        # Dibersihkan juga bila setUp gagal (thread aiosqlite menahan proses).
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        async with self.Session() as db:
            # Akun web murni: belum pernah menautkan Telegram
            user = User(name="Sari Dewi", email="sari@example.com")
            hh = Household(name="Rumah Sari")
            db.add_all([user, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole.owner))
            self.env = {}
            for name in ("Makan", "Transport"):
                e = Envelope(household_id=hh.id, name=name, emoji="📁", budget_amount=D("0"))
                db.add(e)
                self.env[name] = e
            await db.flush()
            inc = Income(household_id=hh.id, user_id=user.id, amount=D("500000"),
                         description="Gaji", income_date=date.today())
            db.add(inc)
            await db.flush()
            for name in ("Makan", "Transport"):
                db.add(Allocation(income_id=inc.id, envelope_id=self.env[name].id, amount=D("250000")))
            # Anggota lain dengan amplop personal, langganan, dan transaksi pending
            rina = User(name="Rina", email="rina@example.com")
            db.add(rina)
            await db.flush()
            db.add(HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member))
            secret = Envelope(household_id=hh.id, owner_id=rina.id, name="Rahasia Rina",
                              emoji="📁", budget_amount=D("0"))
            db.add(secret)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=secret.id, amount=D("100000")))
            netflix = RecurringTransaction(envelope_id=self.env["Makan"].id, amount=D("54000"),
                                           description="Netflix", frequency=RecurringFrequency.monthly,
                                           next_run=date.today(), is_active=True)
            spa = RecurringTransaction(envelope_id=secret.id, amount=D("300000"), description="Spa Rina",
                                       frequency=RecurringFrequency.monthly, next_run=date.today(), is_active=True)
            pending = PendingTransaction(envelope_id=secret.id, user_id=rina.id, amount=D("90000"),
                                         description="tas", source=TransactionSource.telegram,
                                         status=PendingTransactionStatus.pending, cooling_hours=24,
                                         confirm_after=datetime.now(timezone.utc) - timedelta(hours=1),
                                         expires_at=datetime.now(timezone.utc) + timedelta(days=6))
            other_hh = Household(name="Rumah Lain")
            db.add_all([netflix, spa, pending, other_hh])
            await db.flush()
            outsider = Envelope(household_id=other_hh.id, name="Punya Orang", emoji="📁", budget_amount=D("0"))
            db.add(outsider)
            await db.commit()
            self.user = SimpleNamespace(id=user.id, name=user.name)
            self.secret_id, self.spa_id, self.netflix_id = secret.id, spa.id, netflix.id
            self.rina_pending_id, self.outsider_id = pending.id, outsider.id

    async def go(self, coro_fn, match=None, confident=True, real_find=False):
        async def find(desc, hid, db, user_id=None):
            return (self.env[match] if match else None), confident

        ps = [
            patch("redis.asyncio.from_url", return_value=self.redis),
            patch.object(handlers, "AsyncSessionLocal", new=self.Session),
            patch.object(recurring_cmd, "AsyncSessionLocal", new=self.Session),
            patch.object(behavior_cmd, "AsyncSessionLocal", new=self.Session),
            patch.object(receipt_cmd, "AsyncSessionLocal", new=self.Session),
        ]
        if not real_find:
            ps.append(patch.object(handlers, "find_best_envelope", new=find))
        for p in ps:
            p.start()
        try:
            return await coro_fn()
        finally:
            for p in ps:
                p.stop()

    async def txns(self):
        async with self.Session() as db:
            return (await db.execute(select(Transaction))).scalars().all()

    async def users(self):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(User))).scalar()

    async def test_expense_recorded_from_web_chat_as_webapp(self):
        users_before = await self.users()
        ops = await self.go(lambda: web_adapter.run_message(self.user, "kopi 25k"), match="Makan")
        self.assertEqual(len(ops), 1)
        self.assertIn("✅ Rp25rb — kopi", ops[0]["text"])
        self.assertIn("Masuk ke 📁 Makan", ops[0]["text"])
        [txn] = await self.txns()
        self.assertEqual((txn.user_id, txn.envelope_id, txn.amount), (self.user.id, self.env["Makan"].id, D("25000")))
        self.assertEqual(txn.source, TransactionSource.webapp)
        self.assertEqual(await self.users(), users_before)  # tidak ada akun bot baru

    async def test_pick_envelope_with_button_then_button_expires(self):
        ops = await self.go(lambda: web_adapter.run_message(self.user, "bensin 40rb"), match=None)
        [op] = ops
        self.assertIn("Masuk ke amplop mana?", op["text"])
        names = [row[0]["text"] for row in op["buttons"]]
        self.assertEqual(names, ["📁 Makan", "📁 Transport"])
        transport = op["buttons"][1][0]["data"]

        ops = await self.go(lambda: web_adapter.run_action(self.user, op["id"], transport))
        self.assertEqual(ops[0]["type"], "edit")
        self.assertEqual(ops[0]["id"], op["id"])
        self.assertIn("Masuk ke 📁 Transport", ops[0]["text"])
        self.assertEqual(ops[0]["buttons"], [])
        [txn] = await self.txns()
        self.assertEqual((txn.envelope_id, txn.source), (self.env["Transport"].id, TransactionSource.webapp))

        # Tombol yang sama ditekan lagi → ditolak, tidak tercatat dua kali
        ops = await self.go(lambda: web_adapter.run_action(self.user, op["id"], transport))
        self.assertEqual(ops[0]["text"], web_adapter.STALE_BUTTON)
        self.assertEqual(len(await self.txns()), 1)

    async def tap_directly(self, handler, data):
        """Jalankan handler tombol langsung (melewati allowlist), seperti tombol
        lama dari Telegram/tab lain — pertahanan lapis kedua di handler."""
        outbox = web_adapter.Outbox()
        tg_user = web_adapter.WebChatUser(self.user)
        q = web_adapter.WebCallbackQuery(outbox, data, tg_user, "aa11")

        async def run():
            with channel.web_channel():
                await handler(web_adapter.WebUpdate(tg_user, callback_query=q), web_adapter.WebContext())
            return outbox.ops
        return await self.go(run)

    async def test_expense_never_lands_in_other_members_personal_envelope(self):
        ops = await self.go(lambda: web_adapter.run_message(self.user, "rahasia rina 10k"), real_find=True)
        self.assertIn("Masuk ke amplop mana?", ops[0]["text"])
        names = [row[0]["text"] for row in ops[0]["buttons"]]
        self.assertNotIn("📁 Rahasia Rina", names)
        self.assertEqual(await self.txns(), [])

    async def test_subscriptions_of_other_members_are_hidden(self):
        ops = await self.go(lambda: web_adapter.run_message(self.user, "/langganan"))
        self.assertIn("Netflix", ops[0]["text"])
        self.assertNotIn("Spa Rina", ops[0]["text"])
        ops = await self.go(lambda: web_adapter.run_message(self.user, "/hapus_langganan"))
        labels = " ".join(b["text"] for row in ops[0]["buttons"] for b in row)
        self.assertIn("Netflix", labels)
        self.assertNotIn("Spa Rina", labels)

    async def test_subscription_buttons_check_ownership(self):
        for data in (f"delrec_{self.spa_id}", f"recstop_{self.spa_id}", f"recpay_{self.spa_id}"):
            ops = await self.tap_directly(
                {"delrec": recurring_cmd.handle_delrec_callback, "recstop": recurring_cmd.handle_recstop_callback,
                 "recpay": recurring_cmd.handle_recpay_callback}[data.split("_")[0]], data)
            self.assertIn("tidak ditemukan", ops[-1]["text"].lower())
        async with self.Session() as db:
            spa = await db.get(RecurringTransaction, self.spa_id)
            self.assertTrue(spa.is_active)
        self.assertEqual(await self.txns(), [])
        # langganan shared tetap bisa dihapus
        ops = await self.tap_directly(recurring_cmd.handle_delrec_callback, f"delrec_{self.netflix_id}")
        self.assertIn("dihapus", ops[-1]["text"])

    async def test_cooling_button_for_someone_elses_pending_is_rejected(self):
        ops = await self.tap_directly(handlers.handle_cooling_callback, f"cool_confirm_{self.rina_pending_id}")
        self.assertIn("tidak ditemukan", ops[-1]["text"])
        async with self.Session() as db:
            pending = await db.get(PendingTransaction, self.rina_pending_id)
            self.assertEqual(pending.status, PendingTransactionStatus.pending)

    async def test_lock_button_only_for_visible_envelopes(self):
        for env_id in (self.outsider_id, self.secret_id):
            ops = await self.tap_directly(behavior_cmd.handle_lock_callback, f"lock_{env_id}")
            self.assertIn("nggak ditemukan", ops[-1]["text"])
        ops = await self.tap_directly(behavior_cmd.handle_lock_callback, f"lock_{self.env['Makan'].id}")
        self.assertIn("dikunci", ops[-1]["text"])

    async def test_template_lists_only_visible_envelopes_and_is_not_created_twice(self):
        ops = await self.go(lambda: web_adapter.run_message(self.user, "/template"))
        self.assertIn("Makan", ops[0]["text"])
        self.assertNotIn("Rahasia Rina", ops[0]["text"])
        self.assertNotIn("/webapp", ops[0]["text"])
        ops = await self.tap_directly(handlers.handle_template_callback, "tpl_mahasiswa")
        self.assertIn("sudah ada", ops[-1]["text"])
        async with self.Session() as db:
            count = (await db.execute(select(func.count()).select_from(Envelope))).scalar()
        self.assertEqual(count, 4)  # Makan, Transport, Rahasia Rina, Punya Orang

    async def test_concurrent_presses_of_one_button_record_once(self):
        [op] = await self.go(lambda: web_adapter.run_message(self.user, "bensin 40rb"), match=None)
        data = op["buttons"][1][0]["data"]

        async def both():
            return await asyncio.gather(
                web_adapter.run_action(self.user, op["id"], data),
                web_adapter.run_action(self.user, op["id"], data),
            )
        results = await self.go(both)
        self.assertEqual(len(await self.txns()), 1)
        texts = [o.get("text") for ops in results for o in ops]
        self.assertIn(web_adapter.PROCESSING, texts)

    async def test_resend_with_same_client_id_is_not_recorded_twice(self):
        first = await self.go(lambda: web_adapter.run_message(self.user, "kopi 25k", client_id="u1abc"), match="Makan")
        again = await self.go(lambda: web_adapter.run_message(self.user, "kopi 25k", client_id="u1abc"), match="Makan")
        self.assertEqual(first, again)
        self.assertEqual(len(await self.txns()), 1)
        # id lain = pesan baru
        await self.go(lambda: web_adapter.run_message(self.user, "kopi 25k", client_id="u2abc"), match="Makan")
        self.assertEqual(len(await self.txns()), 2)

    # ── Foto struk dari chat web → alur foto bot (Kotak Struk) ─────────────
    def kotak(self, total=45500):
        """Intake Kotak Struk tiruan: foto langsung menjadi item struk belanja yang sudah dibaca (Indomaret,
        12 Okt 2026); penunggu mengembalikannya. Mengembalikan (permintaan intake, patch)."""
        requests = []

        async def create(db, req, **kw):
            requests.append(req)
            doc = DokumenBayar(doc_type="struk_belanja", counterparty=Counterparty(name="Indomaret"),
                               amounts=Amounts(total=total)).to_json()
            item = ReceiptScan(user_id=self.user.id, status="siap", source=req.source, doc_type="struk_belanja",
                               document=doc, merchant="Indomaret", parsed_total=D(total) if total else None,
                               parsed_date=date(2026, 10, 12), confidence="tinggi" if total else "gagal",
                               engine="rapidocr", channel_meta=req.channel_meta)
            db.add(item)
            await db.commit()
            return item, True

        async def wait(item_id, timeout_s, **kw):
            async with self.Session() as s:
                return await s.get(ReceiptScan, item_id)
        return requests, [patch.object(intake, "create_item", new=create), patch.object(waiter, "wait_for_item", new=wait)]

    async def photo(self, data, mime, total=45500, **kw):
        requests, ps = self.kotak(total)
        for p in ps:
            p.start()
        try:
            ops = await self.go(lambda: web_adapter.run_photo(self.user, data, mime, **kw), match=None)
        finally:
            for p in ps:
                p.stop()
        return requests, ops

    async def test_receipt_photo_then_pick_envelope(self):
        [req], ops = await self.photo(b"\xff\xd8jpeg", "image/jpeg")
        self.assertEqual((req.data, req.content_type, req.source), (b"\xff\xd8jpeg", "image/jpeg", "web_chat"))
        self.assertEqual([o["type"] for o in ops], ["message", "edit"])
        final = ops[-1]
        self.assertEqual(final["id"], ops[0]["id"])  # "Membaca bukti..." diganti hasilnya
        self.assertIn("Struk Indomaret · 12 Okt 2026", final["text"])
        self.assertIn("Rp 45.500", final["text"])
        self.assertNotIn("Sisa scan", final["text"])  # kuota scan dihapus
        datas = [b["data"] for row in final["buttons"] for b in row]
        self.assertTrue(any(d.startswith("t_") for d in datas))
        self.assertTrue(any(d.startswith("struk_fix_") for d in datas))

        makan = next(b["data"] for row in final["buttons"] for b in row if "Makan" in b["text"])
        ops = await self.go(lambda: web_adapter.run_action(self.user, final["id"], makan))
        self.assertIn("Masuk ke 📁 Makan", ops[0]["text"])
        [txn] = await self.txns()
        self.assertEqual((txn.amount, txn.transaction_date, txn.source),
                         (D("45500"), date(2026, 10, 12), TransactionSource.webapp))

    async def test_non_jpeg_goes_through_document_path(self):
        [req], _ = await self.photo(b"png", "image/png")
        self.assertEqual(req.content_type, "image/png")

    async def test_receipt_photo_resend_is_scanned_once(self):
        requests, ps = self.kotak()
        for p in ps:
            p.start()
        try:
            first = await self.go(lambda: web_adapter.run_photo(self.user, b"x", "image/jpeg", client_id="ph1"))
            again = await self.go(lambda: web_adapter.run_photo(self.user, b"x", "image/jpeg", client_id="ph1"))
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(first, again)
        self.assertEqual(len(requests), 1)  # tidak masuk Kotak Struk dua kali

    async def test_unreadable_total_and_rejected_upload_messages(self):
        _, ops = await self.photo(b"x", "image/jpeg", total=None)
        self.assertIn("Total struk tidak terbaca", ops[-1]["text"])
        self.assertEqual(ops[-1]["buttons"], [])
        with patch.object(intake, "create_item", new=AsyncMock(side_effect=intake.IntakeRejected(429, intake.MSG_RATE))):
            ops = await self.go(lambda: web_adapter.run_photo(self.user, b"x", "image/jpeg"))
        self.assertEqual([o["type"] for o in ops], ["message", "edit"])
        self.assertEqual(ops[-1]["text"], intake.MSG_RATE)   # "Membaca bukti..." tidak menggantung

    async def test_status_command_runs_on_web(self):
        ops = await self.go(lambda: web_adapter.run_message(self.user, "/status"))
        self.assertEqual(ops[0]["format"], "html")
        self.assertIn("Makan", ops[0]["text"])
        self.assertNotIn("Ketik /start dulu", ops[0]["text"])


if __name__ == "__main__":
    unittest.main()
