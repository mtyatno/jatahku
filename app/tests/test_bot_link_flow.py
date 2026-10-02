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


if __name__ == "__main__":
    unittest.main()
