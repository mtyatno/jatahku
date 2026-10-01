"""Ringkasan harian/mingguan: sender tidak crash, mingguan memfilter privasi,
label amplop aman bila amplop tidak ditemukan.

Run: python -m unittest app.tests.test_summary_senders -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import summary
from app.tests.fakes import FakeResult, sql, executed_sql


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def empty_users_db():
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult(rows=[]))  # query users → []
    return db


class SenderSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_summary_runs_without_unbound_local(self):
        db = empty_users_db()
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            await summary.send_daily_summary(user_id=uuid.uuid4())
        self.assertEqual(db.execute.await_count, 1)
        self.assertIn("FROM users", executed_sql(db)[0])

    async def test_weekly_summary_runs_without_unbound_local(self):
        db = empty_users_db()
        with patch.object(summary, "AsyncSessionLocal", new=lambda: FakeSession(db)):
            await summary.send_weekly_summary(user_id=uuid.uuid4())
        self.assertEqual(db.execute.await_count, 1)
        self.assertIn("FROM users", executed_sql(db)[0])


class WeeklyPrivacyTests(unittest.TestCase):
    def test_week_query_filters_other_members_personal_envelopes(self):
        q = sql(summary._week_txns_query(uuid.uuid4(), uuid.uuid4(), date(2026, 9, 23), date(2026, 9, 30)))
        self.assertIn("envelopes.owner_id IS NULL", q)
        self.assertIn("envelopes.owner_id = ", q)
        self.assertIn("transactions.balance_check_id IS NULL", q)


class EnvLabelTests(unittest.TestCase):
    def test_unknown_envelope_does_not_crash(self):
        self.assertEqual(summary._env_label(None), ("📁", "Lain"))

    def test_known_envelope_uses_emoji_and_first_word(self):
        self.assertEqual(summary._env_label(SimpleNamespace(emoji="🍜", name="Makan Siang")), ("🍜", "Makan"))

    def test_blank_name_falls_back(self):
        self.assertEqual(summary._env_label(SimpleNamespace(emoji="", name=None)), ("", "Lain"))

    def test_whitespace_only_name_falls_back(self):
        # "   ".split() == [] → dulu IndexError saat mengambil kata pertama
        self.assertEqual(summary._env_label(SimpleNamespace(emoji="🍜", name="   ")), ("🍜", "Lain"))


if __name__ == "__main__":
    unittest.main()
