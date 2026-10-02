"""Akun yang belum siap (belum punya amplop) selalu dibalas reply_setup_needed
(link login sekali ketuk ke onboarding web) — di /start, saat mencatat
pengeluaran, dan saat bertanya lewat NLP — dan tidak ada yang tercatat.

Run: python -m unittest app.tests.test_bot_setup_entry -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import handlers, nlp_cmd

BOT_USER = SimpleNamespace(id=uuid.uuid4(), email=None, telegram_id="777", name="Budi", payday_day=1)


def make_update(text="/start"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=777, first_name="Budi"),
        message=message,
        effective_message=message,
    )


def fake_session(db):
    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    return lambda: FakeSession()


class NotReadyEntryTests(unittest.IsolatedAsyncioTestCase):
    def patch_handlers(self, stack, ready):
        self.db = MagicMock()
        self.db.add = MagicMock()
        self.db.commit = AsyncMock()
        self.setup_reply = AsyncMock()
        stack.enter_context(patch.object(handlers, "AsyncSessionLocal", new=fake_session(self.db)))
        stack.enter_context(patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=BOT_USER)))
        stack.enter_context(patch.object(handlers, "_is_setup_complete",
                                         new=AsyncMock(return_value=(True, "ok") if ready else (False, "no_envelopes"))))
        stack.enter_context(patch.object(handlers, "reply_setup_needed", new=self.setup_reply))
        # rate limiter Redis: gagal → fail open (tanpa server Redis di tes)
        stack.enter_context(patch("redis.asyncio.from_url", new=MagicMock(side_effect=Exception("no redis"))))

    async def test_start_gives_not_ready_account_the_setup_link(self):
        update = make_update("/start")
        with ExitStack() as stack:
            self.patch_handlers(stack, ready=False)
            await handlers.cmd_start(update, SimpleNamespace(args=[]))
        self.setup_reply.assert_awaited_once_with(update, BOT_USER)
        update.message.reply_text.assert_not_awaited()

    async def test_start_greets_ready_account_without_setup_link(self):
        update = make_update("/start")
        with ExitStack() as stack:
            self.patch_handlers(stack, ready=True)
            await handlers.cmd_start(update, SimpleNamespace(args=[]))
        self.setup_reply.assert_not_awaited()
        update.message.reply_text.assert_awaited_once()

    async def test_expense_from_not_ready_account_gets_setup_link_and_records_nothing(self):
        update = make_update("kopi 35k")
        with ExitStack() as stack:
            self.patch_handlers(stack, ready=False)
            await handlers.handle_message(update, SimpleNamespace(args=[]))
        self.setup_reply.assert_awaited_once_with(update, BOT_USER)
        self.db.add.assert_not_called()


class NotReadyNlpTests(unittest.IsolatedAsyncioTestCase):
    async def test_balance_question_from_not_ready_account_gets_setup_link(self):
        update = make_update("sisa berapa")
        setup_reply = AsyncMock()
        with patch("app.core.database.AsyncSessionLocal", new=fake_session(MagicMock())), \
             patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(BOT_USER, None, None))), \
             patch.object(nlp_cmd, "reply_setup_needed", new=setup_reply, create=True):
            await nlp_cmd.handle_sisa(update, SimpleNamespace(args=[]))
        setup_reply.assert_awaited_once_with(update, BOT_USER)
        update.message.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
