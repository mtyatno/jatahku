"""Skema Kotak Struk (SQLite in-memory). Run: python -m unittest app.tests.test_kotak_schema -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import importlib.util, unittest
from datetime import timedelta
from pathlib import Path
from fractions import Fraction
from sqlalchemy.exc import IntegrityError
from app.core.database import Base
from app.models.models import Household, HouseholdMerchant, ReceiptScan, User
from app.services.kotak_struk import config as K
from app.services.kotak_struk.schema import KOTAK_DDL

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
NEW_COLS = ["source", "status", "doc_type", "household_id", "upload_id", "file_sha256", "content_type",
            "pages", "file_path", "ref_hash", "counterparty_key", "paid_at", "document", "parser",
            "attempts", "error", "channel_meta", "processed_at", "expires_at", "transaction_ids", "layout",
            "sample_lines"]
REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "alembic" / "versions" / "e7b3d5a9c1f4_kotak_belajar.py"
MIGRATION_2 = REPO / "alembic" / "versions" / "c9e4a7f2b5d8_kotak_belajar_2.py"   # tahap 2 (A16 M1a)

class ConstantsTests(unittest.TestCase):
    def test_constants_match_spec(self):
        self.assertEqual((K.WAIT_BOT_S, K.WAIT_FORM_S, K.MAX_ATTEMPTS, K.RATE_PER_HOUR), (10, 45, 3, 30))
        self.assertEqual((K.MAX_FILES_PER_SHARE, K.MAX_PENDING, K.PDF_MAX_PAGES, K.PDF_TIMEOUT_S), (10, 20, 5, 15))
        self.assertEqual(K.ITEM_EXPIRY, timedelta(days=7))
        self.assertEqual(K.SOFT_DUP_WINDOW, timedelta(hours=3))
        self.assertEqual(K.CONFIDENT_SHARE, Fraction(2, 3))

    def test_learning_constants(self):
        # Kotak Struk belajar (plan 2026-11-01, Global Constraints).
        self.assertEqual((K.LAYOUT_MAX_LINES, K.LAYOUT_LABEL_MAX, K.LAYOUT_LABEL_WORDS), (60, 40, 5))
        self.assertEqual(K.LAYOUT_TTL, timedelta(hours=24))
        self.assertEqual((K.RULE_MIN_USERS, K.RULE_CACHE_S, K.FIX_TTL_S), (2, 300, 300))
        self.assertEqual(K.LAYOUT_TYPES, {"qris", "transfer", "tidak_dikenali"})

    def test_donation_constants(self):
        # Kotak Struk belajar tahap 2 (plan 2026-11-04, Global Constraints).
        self.assertEqual((K.SAMPLE_MAX_LINES, K.SAMPLE_LINE_MAX), (80, 200))
        self.assertEqual(K.SAMPLE_TTL, timedelta(days=30))
        self.assertEqual(K.SAMPLE_TYPES, K.LAYOUT_TYPES)
        self.assertEqual((K.APP_NEW, K.ARAH_FLOWS, K.KEY_MAX), ("baru", ("top_up", "masuk", "antar_rekening_sendiri"), 60))

    def test_layout_ddl_is_jsonb(self):
        self.assertIn("ALTER TABLE receipt_scans ADD COLUMN IF NOT EXISTS layout JSONB", KOTAK_DDL)
        self.assertTrue(ReceiptScan.__table__.c.layout.nullable)

    def test_sample_lines_ddl_is_jsonb_and_sql_null(self):
        self.assertIn("ALTER TABLE receipt_scans ADD COLUMN IF NOT EXISTS sample_lines JSONB", KOTAK_DDL)
        col = ReceiptScan.__table__.c.sample_lines
        self.assertTrue(col.nullable)
        self.assertTrue(col.type.none_as_null)

    def test_every_new_column_has_ddl(self):
        ddl = "\n".join(KOTAK_DDL)
        for col in NEW_COLS:
            with self.subTest(col):
                self.assertIn(f"ADD COLUMN IF NOT EXISTS {col} ", ddl)
                self.assertIn(col, ReceiptScan.__table__.c)
        self.assertIn("WHERE upload_id IS NOT NULL", ddl)

class LearningTablesTests(unittest.TestCase):
    def test_learning_tables_shape(self):
        from app.models.models import ProofRule, ProofRuleVote
        votes, rules = ProofRuleVote.__table__, ProofRule.__table__
        self.assertEqual([c.name for c in votes.primary_key.columns], ["kind", "rule_key", "value", "user_id"])
        [fk] = votes.c.user_id.foreign_keys
        self.assertEqual((fk.target_fullname, fk.ondelete), ("users.id", "CASCADE"))
        self.assertEqual((votes.c.household_id.nullable, votes.c.household_id.foreign_keys), (True, set()))
        [fk] = rules.c.decided_by.foreign_keys
        self.assertEqual((fk.target_fullname, fk.ondelete), ("users.id", "SET NULL"))
        self.assertIn("uq_proof_rule", {c.name for c in rules.constraints})
        self.assertIn("ix_proof_rules_status", {i.name for i in rules.indexes})
        self.assertEqual((votes.c.kind.type.length, votes.c.rule_key.type.length, votes.c.value.type.length),
                         (20, 60, 60))
        self.assertEqual((rules.c.status.type.length, rules.c.note.type.length), (12, 200))

    def test_one_approved_value_index(self):
        # G8 (M3d carry): satu nilai `disetujui` per (jenis, kunci) untuk logo/arah, ditegakkan basis data.
        from app.models.models import ProofRule
        [ix] = [i for i in ProofRule.__table__.indexes if i.name == "ux_proof_rules_satu_nilai"]
        self.assertTrue(ix.unique)
        self.assertEqual([c.name for c in ix.columns], ["kind", "rule_key"])
        where = "status = 'disetujui' AND kind IN ('logo', 'arah')"
        self.assertEqual(str(ix.dialect_options["postgresql"]["where"]), where)
        self.assertEqual(str(ix.dialect_options["sqlite"]["where"]), where)

    def test_donation_tables_shape(self):
        from app.models.models import ProofSample, ProofSampleConsent
        consent, samples = ProofSampleConsent.__table__, ProofSample.__table__
        self.assertEqual([c.name for c in consent.primary_key.columns], ["user_id"])
        [fk] = consent.c.user_id.foreign_keys
        self.assertEqual((fk.target_fullname, fk.ondelete), ("users.id", "CASCADE"))
        self.assertIsNotNone(consent.c.consented_at.server_default)
        [fk] = samples.c.user_id.foreign_keys
        self.assertEqual((fk.target_fullname, fk.ondelete), ("users.id", "CASCADE"))
        [fk] = samples.c.decided_by.foreign_keys
        self.assertEqual((fk.target_fullname, fk.ondelete), ("users.id", "SET NULL"))
        self.assertEqual(samples.c.item_id.foreign_keys, set())   # tanpa FK: item boleh hilang lebih dulu
        nullable = {c.name for c in samples.columns if c.nullable}
        self.assertEqual(nullable, {"item_id", "rule_key", "user_name", "truth", "decided_at", "decided_by", "note"})
        self.assertEqual({c: samples.c[c].type.length for c in ("rule_key", "doc_type", "trigger", "user_name",
                                                                 "status", "note")},
                         {"rule_key": 60, "doc_type": 30, "trigger": 20, "user_name": 60, "status": 12, "note": 200})
        self.assertIn(("uq_proof_sample_item", ("item_id",)),
                      {(c.name, tuple(x.name for x in c.columns)) for c in samples.constraints
                       if c.__class__.__name__ == "UniqueConstraint"})
        self.assertEqual({i.name for i in samples.indexes}, {"ix_proof_samples_status", "ix_proof_samples_user_id"})
        self.assertTrue(samples.c.truth.type.none_as_null)


class _OpRecorder:
    """Pengganti `alembic.op`: mencatat pernyataan, tanpa basis data."""
    def __init__(self):
        self.statements, self.calls = [], []

    def execute(self, stmt):
        self.statements.append(str(stmt))

    def __getattr__(self, name):   # create_table, create_index, drop_table, ...
        return lambda *args, **kwargs: self.calls.append((name, args, kwargs))


def _load(path):
    spec = importlib.util.spec_from_file_location(f"migrasi_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_with(mod, fn):
    rec, real = _OpRecorder(), mod.op
    mod.op = rec
    try:
        getattr(mod, fn)()
    finally:
        mod.op = real
    return rec


def _pg_where(kwargs):
    where = kwargs.get("postgresql_where")
    return None if where is None else str(where)


class MigrationTests(unittest.TestCase):
    def load(self):
        return _load(MIGRATION)

    def run_with(self, mod, fn):
        return _run_with(mod, fn)

    def test_migration_is_idempotent(self):
        mod = self.load()
        self.assertEqual((mod.revision, mod.down_revision), ("e7b3d5a9c1f4", "a7e3c1f5d9b2"))
        first, second = self.run_with(mod, "upgrade"), self.run_with(mod, "upgrade")
        # Setiap pernyataan KOTAK_DDL (sumber yang sama dengan lifespan), semuanya IF NOT EXISTS: aman diulang.
        self.assertEqual(first.statements, KOTAK_DDL)
        self.assertEqual(second.statements, first.statements)
        self.assertTrue(all("IF NOT EXISTS" in stmt for stmt in first.statements))
        for name, _args, kwargs in first.calls:   # tabel/indeks baru (L2) juga idempoten
            with self.subTest(name):
                self.assertTrue(name.startswith("create_"), name)
                self.assertIs(kwargs.get("if_not_exists"), True)
        # L2: dua tabel belajar dan indeks status, sekali per upgrade.
        self.assertEqual([(name, args[0]) for name, args, _kw in first.calls],
                         [("create_table", "proof_rule_votes"), ("create_table", "proof_rules"),
                          ("create_index", "ix_proof_rules_status")])
        self.assertEqual(len(second.calls), len(first.calls))
        down = self.run_with(mod, "downgrade")
        self.assertIn("ALTER TABLE receipt_scans DROP COLUMN IF EXISTS layout", down.statements)
        self.assertEqual([(name, args[0]) for name, args, _kw in down.calls],
                         [("drop_index", "ix_proof_rules_status"), ("drop_table", "proof_rules"),
                          ("drop_table", "proof_rule_votes")])
        for name, _args, kwargs in down.calls:
            with self.subTest(name):
                self.assertIs(kwargs.get("if_exists"), True)

    def test_single_head_after_kotak_belajar(self):
        """Tahap 2 (c9e4a7f2b5d8) menyusul tahap 1 (e7b3d5a9c1f4), yang menyusul Plugin H1 (a7e3c1f5d9b2); satu head."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config(str(REPO / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "alembic"))   # tidak bergantung folder kerja
        script = ScriptDirectory.from_config(cfg)
        self.assertEqual(script.get_heads(), ["c9e4a7f2b5d8"])

        def children(parent):
            return [p.name for p in (REPO / "alembic" / "versions").glob("*.py")
                    if f"down_revision: Union[str, None] = '{parent}'" in p.read_text(encoding="utf-8")]
        self.assertEqual(children("a7e3c1f5d9b2"), [MIGRATION.name])
        self.assertEqual(children("e7b3d5a9c1f4"), [MIGRATION_2.name])


class DonationMigrationTests(unittest.TestCase):
    """Migrasi tahap 2 `c9e4a7f2b5d8`: `receipt_scans.sample_lines` lewat KOTAK_DDL, tabel donasi, indeks G8."""

    def test_migration_is_idempotent(self):
        mod = _load(MIGRATION_2)
        self.assertEqual((mod.revision, mod.down_revision), ("c9e4a7f2b5d8", "e7b3d5a9c1f4"))
        self.assertIn("Idempoten", mod.__doc__)
        first, second = _run_with(mod, "upgrade"), _run_with(mod, "upgrade")
        self.assertEqual(first.statements, KOTAK_DDL)   # termasuk sample_lines; sumber yang sama dengan lifespan
        self.assertIn("ALTER TABLE receipt_scans ADD COLUMN IF NOT EXISTS sample_lines JSONB", first.statements)
        self.assertEqual(second.statements, first.statements)
        self.assertTrue(all("IF NOT EXISTS" in stmt for stmt in first.statements))
        for name, _args, kwargs in first.calls:
            with self.subTest(name):
                self.assertTrue(name.startswith("create_"), name)
                self.assertIs(kwargs.get("if_not_exists"), True)
        self.assertEqual([(name, args[0]) for name, args, _kw in first.calls],
                         [("create_table", "proof_sample_consents"), ("create_table", "proof_samples"),
                          ("create_index", "ix_proof_samples_user_id"), ("create_index", "ix_proof_samples_status"),
                          ("create_index", "ux_proof_rules_satu_nilai")])
        self.assertEqual(len(second.calls), len(first.calls))
        down = _run_with(mod, "downgrade")
        self.assertEqual(down.statements, ["ALTER TABLE receipt_scans DROP COLUMN IF EXISTS sample_lines"])
        self.assertEqual([(name, args[0]) for name, args, _kw in down.calls],
                         [("drop_index", "ux_proof_rules_satu_nilai"), ("drop_index", "ix_proof_samples_status"),
                          ("drop_index", "ix_proof_samples_user_id"), ("drop_table", "proof_samples"),
                          ("drop_table", "proof_sample_consents")])
        for name, _args, kwargs in down.calls:
            with self.subTest(name):
                self.assertIs(kwargs.get("if_exists"), True)

    def test_migration_tables_match_the_models(self):
        """Pengganti lokal `alembic check` (CI "Migrasi" menjalankannya di Postgres): tabel yang dibuat kedua migrasi
        Kotak belajar sama dengan model: kolom, tipe Postgres, nullable, server default, kunci primer, FK + ondelete,
        unik, dan indeks (termasuk syarat WHERE indeks parsial)."""
        import sqlalchemy as sa
        from sqlalchemy.dialects import postgresql
        from app.models.models import ProofRule, ProofRuleVote, ProofSample, ProofSampleConsent
        calls = _run_with(_load(MIGRATION), "upgrade").calls + _run_with(_load(MIGRATION_2), "upgrade").calls
        md = sa.MetaData()
        sa.Table("users", md, sa.Column("id", sa.Uuid(), primary_key=True))
        for name, args, kwargs in calls:
            if name == "create_table":
                sa.Table(args[0], md, *args[1:])
        indexes = {(args[0], args[1], tuple(args[2]), bool(kwargs.get("unique")), _pg_where(kwargs))
                   for name, args, kwargs in calls if name == "create_index"}
        pg = postgresql.dialect()

        def shape(table):
            return {
                "cols": {c.name: (c.type.compile(dialect=pg), c.nullable, c.server_default is not None)
                         for c in table.columns},
                "pk": [c.name for c in table.primary_key.columns],
                "fks": {(fk.parent.name, fk.target_fullname, fk.ondelete) for fk in table.foreign_keys},
                "uniques": {(u.name, tuple(c.name for c in u.columns)) for u in table.constraints
                            if isinstance(u, sa.UniqueConstraint)},
            }

        def where(index):
            w = index.dialect_options["postgresql"]["where"]
            return None if w is None else str(w)
        for model in (ProofRuleVote, ProofRule, ProofSampleConsent, ProofSample):
            with self.subTest(model.__tablename__):
                self.assertEqual(shape(md.tables[model.__tablename__]), shape(model.__table__))
                self.assertEqual({(i.name, tuple(c.name for c in i.columns), bool(i.unique), where(i))
                                  for i in model.__table__.indexes},
                                 {(n, c, u, w) for (n, t, c, u, w) in indexes if t == model.__tablename__})


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_json_columns_roundtrip(self):
        async with self.Session() as db:
            u = User(name="A"); db.add(u); await db.flush()
            s = ReceiptScan(user_id=u.id, status=K.ST_SIAP, document={"schema": 1, "lines": []},
                            transaction_ids=["x"], channel_meta={"chat_id": 1},
                            layout={"v": 1, "key": "gopay", "lines": [{"i": 0, "label": None, "kind": "judul",
                                                                       "words": ["top", "up"]}]})
            db.add(s); await db.commit()
            got = await db.get(ReceiptScan, s.id)
            self.assertEqual((got.document["schema"], got.transaction_ids, got.attempts), (1, ["x"], 0))
            self.assertEqual(got.layout["lines"][0]["words"], ["top", "up"])

    async def test_layout_none_is_sql_null(self):
        # Pembersih kerangka mencari `layout IS NOT NULL`: None harus tersimpan sebagai SQL NULL, bukan JSON 'null'.
        from sqlalchemy import text
        async with self.Session() as db:
            u = User(name="A"); db.add(u); await db.flush()
            db.add(ReceiptScan(user_id=u.id, status=K.ST_SIAP, layout=None)); await db.commit()
            self.assertEqual((await db.execute(text("SELECT COUNT(*) FROM receipt_scans WHERE layout IS NULL"))).scalar(), 1)

    async def test_sample_lines_none_is_sql_null(self):
        from sqlalchemy import text
        async with self.Session() as db:
            u = User(name="A"); db.add(u); await db.flush()
            db.add_all([ReceiptScan(user_id=u.id, status=K.ST_SIAP, sample_lines=None),
                        ReceiptScan(user_id=u.id, status=K.ST_SIAP, sample_lines=["Total Rp12.500"])])
            await db.commit()
            self.assertEqual((await db.execute(text(
                "SELECT COUNT(*) FROM receipt_scans WHERE sample_lines IS NULL"))).scalar(), 1)

    async def test_household_merchant_unique_per_key(self):
        async with self.Session() as db:
            hh = Household(name="R"); db.add(hh); await db.flush()
            db.add_all([HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="A"),
                        HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="B")])
            with self.assertRaises(IntegrityError):
                await db.commit()
