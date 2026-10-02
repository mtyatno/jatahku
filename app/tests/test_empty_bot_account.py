"""is_empty_bot_account: akun yang dibuat bot lewat /start dan belum pernah
dipakai boleh digabung otomatis ke akun web saat link Telegram. Akun dengan
email, data, atau household bersama tidak boleh (harus lewat pilihan merge).

Run: python -m unittest app.tests.test_empty_bot_account -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.merge import is_empty_bot_account
from app.tests.fakes import FakeResult, sql

HID = uuid.uuid4()
BOT_USER = SimpleNamespace(id=uuid.uuid4(), email=None, telegram_id="777")


def db_counts(hid=HID, members=1, envelopes=0, transactions=0, incomes=0):
    """db palsu yang menjawab menurut tabel yang di-query, bukan urutan panggilan."""
    def execute(stmt):
        s = sql(stmt)
        if "count(household_members.id)" in s:
            return FakeResult(members)
        if s.startswith("SELECT household_members.household_id"):
            return FakeResult(hid)
        if "FROM envelopes" in s:
            return FakeResult(envelopes)
        if "FROM transactions" in s:
            return FakeResult(transactions)
        if "FROM incomes" in s:
            return FakeResult(incomes)
        raise AssertionError(f"query tak terduga: {s}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


class IsEmptyBotAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_unused_bot_account_is_empty(self):
        self.assertTrue(await is_empty_bot_account(BOT_USER, db_counts()))

    async def test_bot_account_without_household_is_empty(self):
        self.assertTrue(await is_empty_bot_account(BOT_USER, db_counts(hid=None)))

    async def test_account_with_email_is_not_empty(self):
        web_user = SimpleNamespace(id=uuid.uuid4(), email="web@example.com", telegram_id="777")
        self.assertFalse(await is_empty_bot_account(web_user, db_counts()))

    async def test_shared_household_is_not_empty(self):
        self.assertFalse(await is_empty_bot_account(BOT_USER, db_counts(members=2)))

    async def test_household_with_envelope_is_not_empty(self):
        self.assertFalse(await is_empty_bot_account(BOT_USER, db_counts(envelopes=1)))

    async def test_account_with_transaction_is_not_empty(self):
        self.assertFalse(await is_empty_bot_account(BOT_USER, db_counts(transactions=3)))

    async def test_account_with_income_is_not_empty(self):
        self.assertFalse(await is_empty_bot_account(BOT_USER, db_counts(incomes=1)))


if __name__ == "__main__":
    unittest.main()
