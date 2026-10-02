"""reply_setup_needed: akun yang belum siap dibalas link login sekali ketuk ke
onboarding web (token tglogin yang sama dengan /webapp), bukan instruksi
"buka web, daftar, Settings, generate kode, kirim /link".

Run: python -m unittest app.tests.test_bot_setup_link -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import tglogin_cmd


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def close(self):
        pass


class ReplySetupNeededTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_carries_one_tap_login_link_for_this_user(self):
        redis = FakeRedis()
        update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
        user = SimpleNamespace(id=uuid.uuid4())

        with patch.object(tglogin_cmd.aioredis, "from_url", MagicMock(return_value=redis)):
            await tglogin_cmd.reply_setup_needed(update, user)

        self.assertEqual(len(redis.store), 1)
        key, (value, ex) = next(iter(redis.store.items()))
        self.assertTrue(key.startswith("tglogin:"))
        self.assertEqual(value, str(user.id))
        self.assertIsNotNone(ex, "token login wajib kedaluwarsa")
        token = key[len("tglogin:"):]
        text = update.effective_message.reply_text.await_args.args[0]
        self.assertIn(f"{tglogin_cmd.settings.APP_URL}/auth/tg?token={token}", text)


if __name__ == "__main__":
    unittest.main()
