"""_is_setup_complete: akun siap dipakai lewat bot = punya household dengan
minimal satu amplop aktif. Email TIDAK disyaratkan: akun yang dibuat bot lewat
/start lalu onboarding di web (login sekali ketuk) harus langsung bisa mencatat.

Run: python -m unittest app.tests.test_bot_setup_gate -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.bot import handlers
from app.tests.fakes import FakeResult, sql

HID = uuid.uuid4()
BOT_USER = SimpleNamespace(id=uuid.uuid4(), email=None, telegram_id="777")


def db_for(hid, envelopes):
    def execute(stmt):
        s = sql(stmt)
        if s.startswith("SELECT household_members.household_id"):
            return FakeResult(hid)
        if "FROM envelopes" in s:
            return FakeResult(envelopes)
        raise AssertionError(f"query tak terduga: {s}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


class SetupGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_account_without_email_but_with_envelopes_is_ready(self):
        self.assertEqual(await handlers._is_setup_complete(BOT_USER, db_for(HID, 3)), (True, "ok"))

    async def test_account_without_envelopes_is_not_ready(self):
        self.assertEqual(await handlers._is_setup_complete(BOT_USER, db_for(HID, 0)), (False, "no_envelopes"))

    async def test_account_without_household_is_not_ready(self):
        self.assertEqual(await handlers._is_setup_complete(BOT_USER, db_for(None, 0)), (False, "no_household"))


if __name__ == "__main__":
    unittest.main()
