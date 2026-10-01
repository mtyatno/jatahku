"""Merge akun & reset data harus memperhitungkan balance_checks (FK ke users/households).

Run: python -m unittest app.tests.test_balance_check_lifecycle -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.routes.user_settings import ResetDataRequest, reset_data
from app.services.merge import merge_users
from app.tests.fakes import FakeResult, executed_sql


def scripted_db(*first_results):
    """db.execute: hasil berurutan `first_results`, setelah itu FakeResult kosong."""
    first = iter(first_results)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=lambda *a, **k: next(first, None) or FakeResult(None, rows=[]))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def index_of(stmts, prefix):
    return next(i for i, s in enumerate(stmts) if s.startswith(prefix))


class MergeUsersTests(unittest.IsolatedAsyncioTestCase):
    async def test_reparents_balance_checks_before_deleting_user_and_household(self):
        src, tgt, h_src, h_tgt = (uuid.uuid4() for _ in range(4))
        db = scripted_db(
            FakeResult(SimpleNamespace(id=src, telegram_id="123")),                # source user
            FakeResult(SimpleNamespace(id=tgt, telegram_id=None)),                 # target user
            FakeResult(SimpleNamespace(household_id=h_src, role="owner")),        # source membership
            FakeResult(SimpleNamespace(household_id=h_tgt, role="owner")),        # target membership
        )
        out = await merge_users(src, tgt, h_src, db)  # simpan household sumber → household target dibuang
        self.assertEqual(out["status"], "merged")
        stmts = executed_sql(db)
        self.assertLess(index_of(stmts, "UPDATE balance_checks SET user_id"),
                        index_of(stmts, "DELETE FROM users"))
        self.assertLess(index_of(stmts, "UPDATE balance_checks SET household_id"),
                        index_of(stmts, "DELETE FROM households"))


class ResetDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_deletes_household_balance_checks_after_incomes(self):
        db = scripted_db(FakeResult(uuid.uuid4()), FakeResult("owner"))  # household id, role
        user = SimpleNamespace(id=uuid.uuid4(), email=None, name="U")
        out = await reset_data(ResetDataRequest(), user=user, db=db)
        self.assertTrue(out["success"])
        stmts = executed_sql(db)
        i_bc = index_of(stmts, "DELETE FROM balance_checks")
        self.assertLess(index_of(stmts, "DELETE FROM incomes"), i_bc)
        # Log yang masih dirujuk income penyesuaian anggota lain tidak boleh dihapus (FK).
        self.assertIn("NOT (EXISTS", stmts[i_bc])
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
