"""merge_users: baris milik akun sumber yang FK-nya ke users.id tanpa CASCADE
harus dibereskan sebelum akun sumber dihapus. Akun bot-only hampir selalu
punya user_streaks (dibuat oleh check-in nudge), jadi tanpa ini DELETE users
gagal (FK violation) dan link/merge Telegram ikut gagal.

Run: python -m unittest app.tests.test_merge_users -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.services.merge import merge_users
from app.tests.fakes import FakeResult, sql

SRC_ID, TGT_ID, SRC_HH, TGT_HH = (uuid.uuid4() for _ in range(4))


def make_db():
    source = SimpleNamespace(id=SRC_ID, telegram_id="777", email=None)
    target = SimpleNamespace(id=TGT_ID, telegram_id=None, email="web@example.com")
    src_mem = SimpleNamespace(user_id=SRC_ID, household_id=SRC_HH, role="owner")
    tgt_mem = SimpleNamespace(user_id=TGT_ID, household_id=TGT_HH, role="owner")
    first = [FakeResult(source), FakeResult(target), FakeResult(src_mem), FakeResult(tgt_mem)]

    def execute(stmt):
        if first:
            return first.pop(0)
        if sql(stmt).startswith("SELECT household_members"):
            return FakeResult(tgt_mem)  # target sudah anggota household yang dipertahankan
        return FakeResult()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def statements(db):
    """[(sql, set nilai parameter)] untuk tiap db.execute, berurutan."""
    out = []
    for call in db.execute.call_args_list:
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        out.append((str(compiled), set(compiled.params.values())))
    return out


def index_of(stmts, prefix, values):
    for i, (text, params) in enumerate(stmts):
        if text.startswith(prefix) and values <= params:
            return i
    return -1


class MergeUsersCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        await merge_users(SRC_ID, TGT_ID, TGT_HH, self.db)
        self.stmts = statements(self.db)
        self.delete_user = index_of(self.stmts, "DELETE FROM users", {SRC_ID})
        self.assertNotEqual(self.delete_user, -1, "akun sumber harus tetap dihapus")

    def assert_before_user_delete(self, prefix, values):
        i = index_of(self.stmts, prefix, values)
        self.assertNotEqual(i, -1, f"tidak ada statement {prefix!r} untuk {values}")
        self.assertLess(i, self.delete_user, f"{prefix!r} harus sebelum DELETE FROM users")

    async def test_source_streak_deleted_before_user(self):
        self.assert_before_user_delete("DELETE FROM user_streaks", {SRC_ID})

    async def test_source_notification_preferences_deleted_before_user(self):
        self.assert_before_user_delete("DELETE FROM notification_preferences", {SRC_ID})

    async def test_source_notifications_moved_to_target(self):
        self.assert_before_user_delete("UPDATE notifications", {SRC_ID, TGT_ID})

    async def test_source_pending_transactions_moved_to_target(self):
        self.assert_before_user_delete("UPDATE pending_transactions", {SRC_ID, TGT_ID})

    async def test_source_payment_orders_moved_to_target(self):
        self.assert_before_user_delete("UPDATE payment_orders", {SRC_ID, TGT_ID})


if __name__ == "__main__":
    unittest.main()
