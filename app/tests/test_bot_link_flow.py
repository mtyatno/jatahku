"""Penautan Telegram dari sisi bot:
- deep link /start link_KODE lewat jalur yang sama dengan /link KODE (API
  /auth/link/telegram), supaya bentrok dengan akun bot dari /start tertangani
  (dulu telegram_id ditulis langsung → bentrok unique constraint)
- balasan sukses mengajari cara mencatat pengeluaran pertama

Run: python -m unittest app.tests.test_bot_link_flow -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import handlers, link_cmd
from app.tests.fakes import FakeResult


def make_update(tg_id=777, first_name="Budi"):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=tg_id, first_name=first_name),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def fake_http(response):
    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    class FakeClient:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *exc):
            return False

    return FakeClient, client


class DeepLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_deep_link_goes_through_conflict_aware_link_flow(self):
        update = make_update()
        context = SimpleNamespace(args=["link_123456"])
        no_direct_write = MagicMock(side_effect=AssertionError("deep link menulis telegram_id langsung"))
        with patch.object(handlers, "link_with_code", new=AsyncMock()) as link, \
             patch.object(handlers, "AsyncSessionLocal", new=no_direct_write):
            await handlers.cmd_start(update, context)

        link.assert_awaited_once_with(update, "123456")


class LinkWithCodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_linked_reply_shows_how_to_record_first_expense(self):
        FakeClient, client = fake_http(FakeResponse(200, {"status": "linked", "user_name": "Budi"}))
        update = make_update()
        with patch.object(link_cmd.httpx, "AsyncClient", FakeClient):
            await link_cmd.link_with_code(update, "123456")

        self.assertEqual(client.post.await_args.kwargs["json"], {"code": "123456", "telegram_id": "777"})
        text = update.message.reply_text.await_args.args[0]
        self.assertIn("Budi", text)
        self.assertIn("kopi 35k", text)

    async def test_server_error_without_json_still_gets_a_reply(self):
        class HtmlErrorResponse(FakeResponse):
            def json(self):
                raise ValueError("Internal Server Error (bukan JSON)")

        FakeClient, _ = fake_http(HtmlErrorResponse(500, None))
        update = make_update()
        with patch.object(link_cmd.httpx, "AsyncClient", FakeClient):
            await link_cmd.link_with_code(update, "123456")

        update.message.reply_text.assert_awaited_once()
        self.assertIn("Gagal", update.message.reply_text.await_args.args[0])

    async def test_unreachable_api_still_gets_a_reply(self):
        FakeClient, client = fake_http(None)
        client.post = AsyncMock(side_effect=link_cmd.httpx.ConnectError("api down"))
        update = make_update()
        with patch.object(link_cmd.httpx, "AsyncClient", FakeClient):
            await link_cmd.link_with_code(update, "123456")

        update.message.reply_text.assert_awaited_once()
        self.assertIn("Gagal", update.message.reply_text.await_args.args[0])


def session_returning(user):
    """Pengganti AsyncSessionLocal: query akun berdasarkan telegram_id → `user`."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult(user))

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    return lambda: FakeSession()


class NoHttp:
    async def __aenter__(self):
        raise AssertionError("/link tanpa kode tak boleh membuat kode lewat API")

    async def __aexit__(self, *exc):
        return False


class LinkWithoutCodeTests(unittest.IsolatedAsyncioTestCase):
    async def reply_for(self, user):
        update = make_update()
        with patch("app.core.database.AsyncSessionLocal", new=session_returning(user)), \
             patch.object(link_cmd.httpx, "AsyncClient", NoHttp):
            await link_cmd.cmd_link(update, SimpleNamespace(args=[]))
        return update.message.reply_text.await_args.args[0]

    async def test_bot_only_account_is_not_told_it_is_linked(self):
        bot_only = SimpleNamespace(name="Budi", email=None, telegram_id="777")
        text = await self.reply_for(bot_only)
        self.assertNotIn("sudah terhubung", text)
        self.assertIn("Generate Link Telegram", text)

    async def test_unknown_telegram_user_gets_web_steps(self):
        text = await self.reply_for(None)
        self.assertIn("Generate Link Telegram", text)

    async def test_linked_web_account_is_told_it_is_linked(self):
        web = SimpleNamespace(name="Budi", email="budi@example.com", telegram_id="777")
        text = await self.reply_for(web)
        self.assertIn("sudah terhubung", text)


if __name__ == "__main__":
    unittest.main()
