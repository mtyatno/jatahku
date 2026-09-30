"""Skema cocokkan saldo (spec 2026-09-30).

Run: python -m unittest app.tests.test_balance_check_model -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from pathlib import Path

from app.models.models import Base, Transaction, Income, BalanceCheck

REPO = Path(__file__).resolve().parents[2]


class BalanceCheckSchemaTests(unittest.TestCase):
    def test_balance_checks_columns(self):
        cols = set(Base.metadata.tables["balance_checks"].c.keys())
        self.assertEqual(cols, {
            "id", "household_id", "user_id", "actual_amount", "app_amount",
            "gap", "undone_at", "created_at", "updated_at",
        })
        self.assertTrue(BalanceCheck.__table__.c.undone_at.nullable)

    def _assert_link_column(self, model):
        col = model.__table__.c.balance_check_id
        self.assertTrue(col.nullable)
        self.assertTrue(col.index)
        self.assertEqual({fk.target_fullname for fk in col.foreign_keys}, {"balance_checks.id"})

    def test_transaction_link_column(self):
        self._assert_link_column(Transaction)

    def test_income_link_column(self):
        self._assert_link_column(Income)

    def test_startup_self_heals_link_columns(self):
        # Deploy tidak menjalankan alembic; lifespan main.py wajib menambah kolom.
        src = (REPO / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS balance_check_id UUID", src)
        self.assertIn('("transactions", "incomes")', src)

    def test_migration_chains_from_current_head(self):
        src = (REPO / "alembic" / "versions" / "e4c8a1f9b2d6_add_balance_checks.py").read_text(encoding="utf-8")
        self.assertIn("revision: str = 'e4c8a1f9b2d6'", src)
        self.assertIn("down_revision: Union[str, None] = 'b3d1f7a2c9e4'", src)


if __name__ == "__main__":
    unittest.main()
