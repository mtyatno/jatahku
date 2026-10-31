"""Skema siklus anggaran household (spec 2026-10-31-siklus-household-design, bagian 1).

Tanpa Postgres: yang dicek model, teks DDL, dan pemasangannya di lifespan.
Run: python -m unittest app.tests.test_household_cycle_schema -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import ast
import unittest
from pathlib import Path

from sqlalchemy import Numeric

from app.models.models import Household, MonthlySnapshot
from app.services.household_cycle_schema import HOUSEHOLD_CYCLE_DDL

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PY = REPO / "app" / "services" / "household_cycle_schema.py"
MAIN_PY = REPO / "app" / "main.py"

NEW_COLUMNS = [
    ("households", Household, "payday_day"),
    ("monthly_snapshots", MonthlySnapshot, "allocated_amount"),
    ("monthly_snapshots", MonthlySnapshot, "spent_amount"),
]


def _alters() -> list[str]:
    return [s for s in HOUSEHOLD_CYCLE_DDL if s.lstrip().upper().startswith("ALTER")]


def _backfill() -> str:
    """Satu-satunya UPDATE, spasi dirapatkan supaya tes tidak bergantung pada tata letak."""
    updates = [s for s in HOUSEHOLD_CYCLE_DDL if "UPDATE households" in s]
    if len(updates) != 1:
        raise AssertionError(f"harus tepat satu UPDATE households, ada {len(updates)}")
    return " ".join(updates[0].split())


class ModelColumnTests(unittest.TestCase):
    def test_household_payday_column_nullable_without_default(self):
        # NULL = belum dimigrasi; DEFAULT 1 akan membuat owner dengan gajian 25 terbaca 1.
        col = Household.__table__.c.payday_day
        self.assertIs(col.nullable, True)
        self.assertIsNone(col.default)
        self.assertIsNone(col.server_default)

    def test_snapshot_amount_columns(self):
        # NULL = snapshot lama yang belum dihitung ulang; default 0 akan berarti "sudah dihitung, nol".
        for name in ("allocated_amount", "spent_amount"):
            with self.subTest(name):
                col = MonthlySnapshot.__table__.c[name]
                self.assertIs(col.nullable, True)
                self.assertIsNone(col.default)
                self.assertIsNone(col.server_default)
                self.assertIsInstance(col.type, Numeric)
                self.assertEqual(col.type.precision, 15)
                self.assertEqual(col.type.scale, 2)


class DdlTests(unittest.TestCase):
    def test_ddl_additive_and_idempotent(self):
        alters = _alters()
        self.assertTrue(alters)
        for stmt in alters:
            with self.subTest(stmt):
                self.assertIn("ADD COLUMN IF NOT EXISTS", stmt)
        for stmt in HOUSEHOLD_CYCLE_DDL:
            with self.subTest(stmt):
                self.assertNotIn("DROP", stmt.upper())
        self.assertEqual(sum("UPDATE households" in s for s in HOUSEHOLD_CYCLE_DDL), 1)
        # Dijalankan di setiap startup: hanya baris yang belum diisi yang boleh disentuh.
        self.assertIn("h.payday_day IS NULL", _backfill())

    def test_ddl_covers_every_new_column(self):
        for table, model, col in NEW_COLUMNS:
            with self.subTest(col):
                self.assertEqual(model.__table__.name, table)
                self.assertIn(col, model.__table__.c)
                self.assertTrue(
                    any(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} " in s for s in _alters()),
                    f"tidak ada ALTER untuk {table}.{col}",
                )

    def test_ddl_order_alters_then_backfill(self):
        self.assertEqual(HOUSEHOLD_CYCLE_DDL[:3], [
            "ALTER TABLE households ADD COLUMN IF NOT EXISTS payday_day INTEGER",
            "ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS allocated_amount NUMERIC(15,2)",
            "ALTER TABLE monthly_snapshots ADD COLUMN IF NOT EXISTS spent_amount NUMERIC(15,2)",
        ])
        self.assertEqual(len(HOUSEHOLD_CYCLE_DDL), 4)
        self.assertTrue(HOUSEHOLD_CYCLE_DDL[3].startswith("UPDATE households h "))

    def test_backfill_orders_owner_admin_member_then_oldest(self):
        # Cermin pick_payday (Task 4): owner, lalu admin, lalu member; sesama peran yang terlama bergabung.
        backfill = _backfill()
        self.assertIn("DISTINCT ON (hm.household_id)", backfill)
        self.assertIn("ORDER BY hm.household_id, CASE hm.role", backfill)
        self.assertIn("WHEN 'owner' THEN 0", backfill)
        self.assertIn("WHEN 'admin' THEN 1", backfill)
        self.assertIn("ELSE 2 END, hm.created_at", backfill)

    def test_schema_module_imports_nothing(self):
        # Revisi alembic (Task 13) memuat daftar ini; modulnya tidak boleh menarik app/SQLAlchemy.
        tree = ast.parse(SCHEMA_PY.read_text(encoding="utf-8"))
        imports = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])


class LifespanTests(unittest.TestCase):
    def test_lifespan_runs_household_cycle_ddl(self):
        # Deploy tidak menjalankan alembic; lifespan wajib memasang kolom, hanya di Postgres.
        tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
        lifespan = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
        guard = next(n for n in ast.walk(lifespan)
                     if isinstance(n, ast.If) and "postgresql" in ast.unparse(n.test))
        body = ast.unparse(guard)
        self.assertIn("from app.services.household_cycle_schema import HOUSEHOLD_CYCLE_DDL", body)
        self.assertIn("for stmt in HOUSEHOLD_CYCLE_DDL:", body)
        self.assertIn("await conn.execute(text(stmt))", body)


if __name__ == "__main__":
    unittest.main()
