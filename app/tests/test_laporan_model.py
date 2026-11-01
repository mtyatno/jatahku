"""Laporan berkala tahap 1, Task 1: tabel `reports` dan `report_settings`, kolom
`users.email_verified_at`, dan pemasangannya di lifespan (spec 2026-11-01-laporan-berkala-design,
bagian 2a-2b dan 9).

Metadata model, teks DDL, dan sumber lifespan dicek tanpa basis data. Constraint, default, dan
cascade dicoba di SQLite in-memory dengan FK menyala (butuh `aiosqlite`; dilewati bila tidak ada).
Run: python -m unittest app.tests.test_laporan_model -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import ast
import importlib.util
import inspect
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, String, Text, delete, event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app import main
from app.core.database import Base
from app.models.models import JENIS_BULANAN, Household, Report, ReportSettings, User
from app.services.laporan.schema import LAPORAN_DDL

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
REPO = Path(__file__).resolve().parents[2]
SCHEMA_PY = REPO / "app" / "services" / "laporan" / "schema.py"
MAIN_PY = REPO / "app" / "main.py"

DATA_V1 = {"versi": 1, "judul": "Laporan Oktober 2026", "ringkasan": {"terpakai": "1250000.00"}}


class ReportsTableTests(unittest.TestCase):
    def test_reports_table_contract(self):
        t = Report.__table__
        self.assertEqual(t.name, "reports")
        self.assertIn("uq_reports_user_jenis_periode", {c.name for c in t.constraints})
        self.assertIn("ix_reports_email_antrean", {i.name for i in t.indexes})
        self.assertEqual(next(iter(t.c.household_id.foreign_keys)).ondelete, "SET NULL")
        self.assertEqual(next(iter(t.c.user_id.foreign_keys)).ondelete, "CASCADE")
        self.assertTrue(t.c.email_status.nullable)

    def test_unique_and_queue_index_columns(self):
        # Revisi alembic (Task 11) menirukan nama dan urutan kolom ini persis.
        t = Report.__table__
        uq = next(c for c in t.constraints if c.name == "uq_reports_user_jenis_periode")
        self.assertEqual([c.name for c in uq.columns], ["user_id", "jenis", "periode_mulai"])
        ix = next(i for i in t.indexes if i.name == "ix_reports_email_antrean")
        self.assertEqual([c.name for c in ix.columns], ["email_status", "email_terakhir_at"])
        self.assertFalse(ix.unique)

    def test_foreign_key_targets(self):
        t = Report.__table__
        self.assertEqual(next(iter(t.c.user_id.foreign_keys)).target_fullname, "users.id")
        self.assertEqual(next(iter(t.c.household_id.foreign_keys)).target_fullname, "households.id")
        self.assertFalse(t.c.user_id.nullable)
        # Laporan mantan anggota tetap ada saat household dihapus: household_id boleh NULL.
        self.assertTrue(t.c.household_id.nullable)

    def test_column_types_and_nullability(self):
        c = Report.__table__.c
        # (kolom, kelas tipe, panjang, nullable)
        kontrak = [
            ("jenis", String, 16, False),
            ("periode_mulai", Date, None, False),
            ("periode_akhir", Date, None, False),
            ("payday_day", Integer, None, False),
            ("terbit_at", DateTime, None, False),
            ("notified_at", DateTime, None, True),
            ("email_status", String, 16, True),
            ("email_alasan", String, 32, True),
            ("email_percobaan", Integer, None, False),
            ("email_terakhir_at", DateTime, None, True),
            ("email_terkirim_at", DateTime, None, True),
        ]
        for name, tipe, panjang, nullable in kontrak:
            with self.subTest(name):
                col = c[name]
                self.assertIsInstance(col.type, tipe)
                self.assertIs(col.nullable, nullable)
                if panjang is not None:
                    self.assertEqual(col.type.length, panjang)
                if tipe is DateTime:
                    self.assertTrue(col.type.timezone)

    def test_data_is_json_with_jsonb_on_postgres(self):
        col = Report.__table__.c.data
        self.assertIs(col.nullable, False)
        self.assertIsInstance(col.type, JSON)
        self.assertEqual(col.type.compile(dialect=postgresql.dialect()), "JSONB")

    def test_server_side_defaults(self):
        c = Report.__table__.c
        self.assertEqual(c.terbit_at.server_default.arg.compile(dialect=postgresql.dialect()).string, "now()")
        self.assertEqual(c.email_percobaan.default.arg, 0)
        self.assertEqual(c.email_percobaan.server_default.arg, "0")
        # Tahap 1 membiarkan email_status NULL (keputusan rencana 3): tidak boleh ada bawaan.
        for name in ("email_status", "email_alasan", "notified_at", "email_terakhir_at", "email_terkirim_at"):
            with self.subTest(name):
                self.assertIsNone(c[name].default)
                self.assertIsNone(c[name].server_default)

    def test_jenis_bulanan_constant(self):
        self.assertEqual(JENIS_BULANAN, "bulanan")

    def test_postgres_ddl_for_new_tables(self):
        # create_all di lifespan membuat kedua tabel di Postgres; periksa DDL yang akan keluar.
        pg = postgresql.dialect()
        reports = " ".join(str(CreateTable(Report.__table__).compile(dialect=pg)).split())
        self.assertIn("data JSONB NOT NULL", reports)
        self.assertIn("terbit_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL", reports)
        self.assertIn("FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE SET NULL", reports)
        self.assertIn("FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE", reports)
        self.assertIn("CONSTRAINT uq_reports_user_jenis_periode UNIQUE (user_id, jenis, periode_mulai)", reports)
        settings = " ".join(str(CreateTable(ReportSettings.__table__).compile(dialect=pg)).split())
        self.assertIn("kata_sandi_enc TEXT", settings)
        self.assertNotIn("kata_sandi_enc TEXT NOT NULL", settings)
        for kolom in ("email_on", "kuartalan_on", "tahunan_on"):
            self.assertIn(f"{kolom} BOOLEAN DEFAULT true NOT NULL", settings)
        self.assertIn("FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE", settings)


class ReportSettingsTableTests(unittest.TestCase):
    def test_report_settings_defaults(self):
        t = ReportSettings.__table__
        self.assertEqual(t.name, "report_settings")
        # kata_sandi_enc NULL = belum ada kata sandi laporan.
        self.assertIsInstance(t.c.kata_sandi_enc.type, Text)
        self.assertTrue(t.c.kata_sandi_enc.nullable)
        self.assertIsNone(t.c.kata_sandi_enc.default)
        self.assertIsNone(t.c.kata_sandi_enc.server_default)
        for name in ("email_on", "kuartalan_on", "tahunan_on"):
            with self.subTest(name):
                col = t.c[name]
                self.assertIsInstance(col.type, Boolean)
                self.assertFalse(col.nullable)
                self.assertIs(col.default.arg, True)
                self.assertEqual(col.server_default.arg.text, "true")

    def test_primary_key_is_user_with_cascade(self):
        t = ReportSettings.__table__
        self.assertEqual([c.name for c in t.primary_key.columns], ["user_id"])
        fk = next(iter(t.c.user_id.foreign_keys))
        self.assertEqual(fk.target_fullname, "users.id")
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_updated_at_is_maintained_by_the_database_layer(self):
        col = ReportSettings.__table__.c.updated_at
        self.assertIsInstance(col.type, DateTime)
        self.assertTrue(col.type.timezone)
        self.assertFalse(col.nullable)
        self.assertIsNotNone(col.server_default)
        self.assertIsNotNone(col.onupdate)


class UsersColumnAndDdlTests(unittest.TestCase):
    def test_users_email_verified_at_column_and_ddl(self):
        self.assertTrue(User.__table__.c.email_verified_at.nullable)
        self.assertTrue(all("IF NOT EXISTS" in s for s in LAPORAN_DDL))

    def test_email_verified_at_is_timezone_aware_without_default(self):
        # NULL = belum (atau tidak lagi) terverifikasi; bawaan apa pun akan berarti "sudah terverifikasi".
        col = User.__table__.c.email_verified_at
        self.assertIsInstance(col.type, DateTime)
        self.assertTrue(col.type.timezone)
        self.assertIsNone(col.default)
        self.assertIsNone(col.server_default)

    def test_ddl_is_the_single_additive_statement(self):
        self.assertEqual(LAPORAN_DDL, [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE",
        ])
        # Tabel baru dibuat create_all; daftar ini hanya kolom di tabel yang sudah ada.
        for stmt in LAPORAN_DDL:
            self.assertNotIn("DROP", stmt.upper())
            self.assertNotIn("CREATE TABLE", stmt.upper())

    def test_ddl_covers_the_model_column(self):
        self.assertIn("email_verified_at", User.__table__.c)
        self.assertTrue(any("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at " in s
                            for s in LAPORAN_DDL))

    def test_schema_module_imports_nothing(self):
        # Revisi alembic (Task 11) memuat daftar ini; modulnya tidak boleh menarik app/SQLAlchemy.
        tree = ast.parse(SCHEMA_PY.read_text(encoding="utf-8"))
        imports = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])


class LifespanTests(unittest.TestCase):
    def test_lifespan_runs_laporan_ddl_and_key_check(self):
        src = inspect.getsource(main.lifespan)
        self.assertIn("for stmt in LAPORAN_DDL", src)
        self.assertIn("rahasia.check_configured()", src)

    def test_laporan_ddl_runs_postgres_only_after_household_cycle(self):
        # Deploy tidak menjalankan alembic: kolom harus dipasang lifespan, hanya di Postgres
        # (SQLite tidak mengenal ADD COLUMN IF NOT EXISTS), setelah DDL siklus household.
        tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
        lifespan = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
        guard = next(n for n in ast.walk(lifespan)
                     if isinstance(n, ast.If) and "postgresql" in ast.unparse(n.test))
        body = ast.unparse(guard)
        self.assertIn("from app.services.laporan.schema import LAPORAN_DDL", body)
        self.assertIn("for stmt in LAPORAN_DDL:", body)
        self.assertIn("await conn.execute(text(stmt))", body)
        self.assertLess(body.index("for stmt in HOUSEHOLD_CYCLE_DDL:"), body.index("for stmt in LAPORAN_DDL:"))

    def test_key_check_runs_after_email_check_outside_the_ddl_block(self):
        src = inspect.getsource(main.lifespan)
        self.assertLess(src.index("email_service.check_configured()"), src.index("rahasia.check_configured()"))
        self.assertLess(src.index("for stmt in LAPORAN_DDL"), src.index("rahasia.check_configured()"))


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class ReportsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)

        # Postgres menegakkan FK dan ON DELETE; tanpa ini SQLite meloloskan semuanya.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.user = User(name="Budi", email="budi@contoh.test")
            self.other = User(name="Sari", email="sari@contoh.test")
            self.hh = Household(name="Rumah Budi")
            db.add_all([self.user, self.other, self.hh])
            await db.commit()

    def _report(self, user=None, **kw):
        base = dict(user_id=(user or self.user).id, household_id=self.hh.id, jenis=JENIS_BULANAN,
                    periode_mulai=date(2026, 9, 25), periode_akhir=date(2026, 10, 24), payday_day=25,
                    data=DATA_V1)
        base.update(kw)
        return Report(**base)

    async def _count(self, model):
        async with self.Session() as db:
            return len((await db.execute(select(model))).scalars().all())

    async def test_new_report_defaults_and_json_roundtrip(self):
        async with self.Session() as db:
            r = self._report()
            db.add(r)
            await db.commit()
            rid = r.id
        async with self.Session() as db:
            got = await db.get(Report, rid)
        self.assertEqual(got.data, DATA_V1)
        self.assertEqual((got.periode_mulai, got.periode_akhir), (date(2026, 9, 25), date(2026, 10, 24)))
        self.assertIsNotNone(got.terbit_at)
        self.assertEqual(got.email_percobaan, 0)
        for name in ("email_status", "email_alasan", "notified_at", "email_terakhir_at", "email_terkirim_at"):
            with self.subTest(name):
                self.assertIsNone(getattr(got, name))

    async def test_one_report_per_user_jenis_and_period_start(self):
        async with self.Session() as db:
            db.add(self._report())
            await db.commit()
        async with self.Session() as db:
            db.add(self._report())
            with self.assertRaises(IntegrityError):
                await db.commit()
        # Jenis lain, awal periode lain, atau user lain di periode yang sama tidak bentrok.
        async with self.Session() as db:
            db.add_all([
                self._report(jenis="kuartalan"),
                self._report(periode_mulai=date(2026, 10, 25), periode_akhir=date(2026, 11, 24)),
                self._report(user=self.other),
            ])
            await db.commit()
        self.assertEqual(await self._count(Report), 4)

    async def test_deleting_user_cascades_reports_and_settings(self):
        async with self.Session() as db:
            db.add_all([self._report(), self._report(user=self.other),
                        ReportSettings(user_id=self.user.id), ReportSettings(user_id=self.other.id)])
            await db.commit()
        async with self.Session() as db:
            await db.execute(delete(User).where(User.id == self.user.id))
            await db.commit()
        async with self.Session() as db:
            reports = (await db.execute(select(Report))).scalars().all()
            settings = (await db.execute(select(ReportSettings))).scalars().all()
        self.assertEqual([r.user_id for r in reports], [self.other.id])
        self.assertEqual([s.user_id for s in settings], [self.other.id])

    async def test_deleting_household_keeps_reports_with_null_household(self):
        async with self.Session() as db:
            r = self._report()
            db.add(r)
            await db.commit()
            rid = r.id
        async with self.Session() as db:
            await db.execute(delete(Household).where(Household.id == self.hh.id))
            await db.commit()
        async with self.Session() as db:
            got = await db.get(Report, rid)
        self.assertIsNotNone(got)
        self.assertIsNone(got.household_id)

    async def test_report_requires_an_existing_user(self):
        async with self.Session() as db:
            db.add(self._report(user=User(name="Belum disimpan", id=uuid.uuid4())))
            with self.assertRaises(IntegrityError):
                await db.commit()

    async def test_report_settings_defaults_via_orm(self):
        async with self.Session() as db:
            db.add(ReportSettings(user_id=self.user.id))
            await db.commit()
        async with self.Session() as db:
            got = await db.get(ReportSettings, self.user.id)
        self.assertIsNone(got.kata_sandi_enc)
        self.assertEqual((got.email_on, got.kuartalan_on, got.tahunan_on), (True, True, True))
        self.assertIsNotNone(got.updated_at)

    async def test_report_settings_server_defaults_without_orm(self):
        # Baris yang ditulis tanpa ORM (psql, revisi data) tetap mendapat bawaan dari basis data.
        async with self.Session() as db:
            await db.execute(text("INSERT INTO report_settings (user_id) VALUES (:uid)"),
                             {"uid": self.user.id.hex})
            await db.commit()
        async with self.Session() as db:
            row = (await db.execute(text(
                "SELECT kata_sandi_enc, email_on, kuartalan_on, tahunan_on, updated_at "
                "FROM report_settings"))).one()
        self.assertIsNone(row.kata_sandi_enc)
        self.assertEqual((row.email_on, row.kuartalan_on, row.tahunan_on), (1, 1, 1))
        self.assertIsNotNone(row.updated_at)

    async def test_report_settings_one_row_per_user(self):
        async with self.Session() as db:
            db.add(ReportSettings(user_id=self.user.id))
            await db.commit()
        async with self.Session() as db:
            db.add(ReportSettings(user_id=self.user.id))
            with self.assertRaises(IntegrityError):
                await db.commit()

    async def test_user_email_verified_at_is_null_until_set(self):
        async with self.Session() as db:
            u = await db.get(User, self.user.id)
            self.assertIsNone(u.email_verified_at)
            u.email_verified_at = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)
            await db.commit()
        async with self.Session() as db:
            u = await db.get(User, self.user.id)
            other = await db.get(User, self.other.id)
        self.assertIsNotNone(u.email_verified_at)
        self.assertIsNone(other.email_verified_at)


if __name__ == "__main__":
    unittest.main()
