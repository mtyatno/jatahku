"""Skema Kotak Struk (SQLite in-memory). Run: python -m unittest app.tests.test_kotak_schema -v"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import importlib.util, unittest
from datetime import timedelta
from fractions import Fraction
from sqlalchemy.exc import IntegrityError
from app.core.database import Base
from app.models.models import Household, HouseholdMerchant, ReceiptScan, User
from app.services.kotak_struk import config as K
from app.services.kotak_struk.schema import KOTAK_DDL

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
NEW_COLS = ["source", "status", "doc_type", "household_id", "upload_id", "file_sha256", "content_type",
            "pages", "file_path", "ref_hash", "counterparty_key", "paid_at", "document", "parser",
            "attempts", "error", "channel_meta", "processed_at", "expires_at", "transaction_ids"]

class ConstantsTests(unittest.TestCase):
    def test_constants_match_spec(self):
        self.assertEqual((K.WAIT_BOT_S, K.WAIT_FORM_S, K.MAX_ATTEMPTS, K.RATE_PER_HOUR), (10, 45, 3, 30))
        self.assertEqual((K.MAX_FILES_PER_SHARE, K.MAX_PENDING, K.PDF_MAX_PAGES, K.PDF_TIMEOUT_S), (10, 20, 5, 15))
        self.assertEqual(K.ITEM_EXPIRY, timedelta(days=7))
        self.assertEqual(K.SOFT_DUP_WINDOW, timedelta(hours=3))
        self.assertEqual(K.CONFIDENT_SHARE, Fraction(2, 3))

    def test_every_new_column_has_ddl(self):
        ddl = "\n".join(KOTAK_DDL)
        for col in NEW_COLS:
            with self.subTest(col):
                self.assertIn(f"ADD COLUMN IF NOT EXISTS {col} ", ddl)
                self.assertIn(col, ReceiptScan.__table__.c)
        self.assertIn("WHERE upload_id IS NOT NULL", ddl)

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
                            transaction_ids=["x"], channel_meta={"chat_id": 1})
            db.add(s); await db.commit()
            got = await db.get(ReceiptScan, s.id)
            self.assertEqual((got.document["schema"], got.transaction_ids, got.attempts), (1, ["x"], 0))

    async def test_household_merchant_unique_per_key(self):
        async with self.Session() as db:
            hh = Household(name="R"); db.add(hh); await db.flush()
            db.add_all([HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="A"),
                        HouseholdMerchant(household_id=hh.id, counterparty_key="nmid:ID1", raw_name="B")])
            with self.assertRaises(IntegrityError):
                await db.commit()
