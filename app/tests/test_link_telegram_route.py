"""POST /auth/link/telegram saat telegram_id sudah dipegang akun lain:
- akun bot yang belum dipakai → digabung otomatis ke akun web, status "linked"
- akun bot yang punya data → tetap "conflict" (user memilih household)

Run: python -m unittest app.tests.test_link_telegram_route -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.api.routes import link as route
from app.tests.fakes import FakeResult

CODE = "123456"
TG_ID = "777"
BOT_ID, BOT_HH, WEB_ID, WEB_HH = (uuid.uuid4() for _ in range(4))
BOT_USER = SimpleNamespace(id=BOT_ID, email=None, telegram_id=TG_ID, name="Budi TG")
WEB_USER = SimpleNamespace(id=WEB_ID, email="budi@example.com", telegram_id=None, name="Budi")


class FakeRedis:
    def __init__(self, store):
        self.store = dict(store)

    async def get(self, key):
        value = self.store.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def close(self):
        pass


def make_db(bot_transactions=0):
    """Menjawab menurut tabel & parameter query, bukan urutan panggilan."""
    def execute(stmt):
        compiled = stmt.compile(dialect=postgresql.dialect())
        s, params = str(compiled), set(compiled.params.values())
        if s.startswith("SELECT users.") and TG_ID in params:
            return FakeResult(BOT_USER)
        if s.startswith("SELECT users.") and WEB_ID in params:
            return FakeResult(WEB_USER)
        if s.startswith("SELECT household_members.household_id"):
            return FakeResult(BOT_HH if BOT_ID in params else WEB_HH)
        if "count(household_members.id)" in s:
            return FakeResult(1)
        if "FROM envelopes" in s:
            return FakeResult(0)
        if "FROM transactions" in s:
            return FakeResult(bot_transactions)
        if "FROM incomes" in s:
            return FakeResult(0)
        raise AssertionError(f"query tak terduga: {s}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    return db


class LinkTelegramConflictTests(unittest.IsolatedAsyncioTestCase):
    async def link(self, db):
        self.redis = FakeRedis({f"link:webapp:{CODE}": str(WEB_ID)})
        self.merge = AsyncMock(return_value={"status": "merged"})
        self.preview = AsyncMock(return_value={"source": {}, "target": {}})
        with patch.object(route, "_redis", new=AsyncMock(return_value=self.redis)), \
             patch.object(route, "merge_users", new=self.merge), \
             patch.object(route, "get_merge_preview", new=self.preview):
            req = route.LinkTelegramRequest(code=CODE, telegram_id=TG_ID)
            return await route.link_telegram_account(req, db=db)

    async def test_unused_bot_account_is_merged_automatically(self):
        result = await self.link(make_db(bot_transactions=0))

        self.assertEqual(result.status, "linked")
        self.assertEqual(result.user_name, "Budi")
        self.merge.assert_awaited_once()
        kwargs = self.merge.await_args.kwargs
        self.assertEqual(kwargs["source_user_id"], BOT_ID)
        self.assertEqual(kwargs["target_user_id"], WEB_ID)
        self.assertEqual(kwargs["keep_household_id"], WEB_HH)
        self.assertNotIn(f"link:webapp:{CODE}", self.redis.store)

    async def test_bot_account_with_data_still_asks_which_household(self):
        result = await self.link(make_db(bot_transactions=5))

        self.assertEqual(result.status, "conflict")
        self.merge.assert_not_awaited()
        self.assertIn(f"merge:{CODE}", self.redis.store)


if __name__ == "__main__":
    unittest.main()
