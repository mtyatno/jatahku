"""Penyesuaian cocokkan saldo dikecualikan dari bot 'hari ini/hari lalu',
meter usage profil, dan dashboard admin.

Run: python -m unittest app.tests.test_adjustment_surfaces -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import configure_mappers

from app.api.routes.admin import admin_dashboard
from app.api.routes.user_settings import get_profile
from app.bot import handlers, nlp_cmd
from app.tests.fakes import FakeResult, executed_sql

# Konfigurasi mapper pertama (~50ms) jangan jatuh di dalam event loop test:
# asyncio debug mode akan mencetak "Executing <Task ...> took 0.1xx seconds".
configure_mappers()

NOT_ADJ_TXN = "transactions.balance_check_id IS NULL"
USER = SimpleNamespace(id=uuid.uuid4(), payday_day=1, timezone=None)


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def fake_update(text):
    update = MagicMock()
    update.effective_user = SimpleNamespace(id=123, first_name="Tes")
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


class BotTodayTests(unittest.IsolatedAsyncioTestCase):
    async def test_hari_ini_excludes_adjustments(self):
        db = MagicMock()
        # 1) per-envelope totals: fungsi mengiterasi hasil langsung; 2) recent: .scalars().all()
        db.execute = AsyncMock(side_effect=[[], FakeResult(rows=[])])
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db)), \
             patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(USER, uuid.uuid4(), []))):
            await nlp_cmd.handle_pengeluaran_hari_ini(fake_update("pengeluaran hari ini"), None)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 2)
        for s in stmts:
            self.assertIn(NOT_ADJ_TXN, s)

    async def test_hari_lalu_excludes_adjustments(self):
        db = MagicMock()
        # 1) transaksi tanggal target: .scalars().all(); 2) total hari ini: .scalar()
        db.execute = AsyncMock(side_effect=[FakeResult(rows=[]), FakeResult(0)])
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db)), \
             patch.object(nlp_cmd, "_get_user_envelopes", new=AsyncMock(return_value=(USER, uuid.uuid4(), []))):
            await nlp_cmd.handle_pengeluaran_hari_lalu(fake_update("kemarin"), None)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 2)
        for s in stmts:
            self.assertIn(NOT_ADJ_TXN, s)


class BotLastTransactionTests(unittest.IsolatedAsyncioTestCase):
    """'Transaksi terakhir yang user input' (/batal, koreksi) tak boleh mengenai baris penyesuaian:
    tepat setelah cocokkan saldo, baris terbaru adalah penyesuaian (semua baris satu apply
    ber-created_at sama)."""

    async def test_batal_picks_latest_non_adjustment(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(None)])  # scalar_one_or_none() → tak ada transaksi
        with patch.object(handlers, "AsyncSessionLocal", new=lambda: FakeSession(db)), \
             patch.object(handlers, "get_or_create_user", new=AsyncMock(return_value=USER)):
            await handlers.cmd_batal(fake_update("/batal"), None)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 1)
        self.assertIn("ORDER BY transactions.created_at DESC", stmts[0])  # = pemilihan "terakhir"
        self.assertIn(NOT_ADJ_TXN, stmts[0])

    async def test_koreksi_picks_latest_non_adjustment(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[FakeResult(None)])  # scalar_one_or_none() → tak ada transaksi
        with patch("app.core.database.AsyncSessionLocal", new=lambda: FakeSession(db)), \
             patch.object(nlp_cmd, "get_or_create_user", new=AsyncMock(return_value=USER)):
            await nlp_cmd.handle_koreksi(fake_update("batalin yang tadi"), None)
        stmts = executed_sql(db)
        self.assertEqual(len(stmts), 1)
        self.assertIn("ORDER BY transactions.created_at DESC", stmts[0])  # = pemilihan "terakhir"
        self.assertIn(NOT_ADJ_TXN, stmts[0])


class ProfileUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_txn_usage_meter_excludes_adjustments(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: FakeResult(0))
        user = SimpleNamespace(
            id=uuid.uuid4(), name="U", email=None, telegram_id=None, password_hash=None,
            timezone="Asia/Jakarta", payday_day=1, profile_pic=None, plan="basic",
            default_cooling_threshold=None, default_daily_limit=None, default_is_locked=False,
            last_login=None, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await get_profile(user=user, db=db)
        first = executed_sql(db)[0]
        self.assertIn("count(transactions.id)", first)
        self.assertIn(NOT_ADJ_TXN, first)


class AdminDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_and_daily_exclude_adjustments_month_total_keeps_them(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: FakeResult(1, rows=[]))
        await admin_dashboard(admin=SimpleNamespace(id=uuid.uuid4(), is_admin=True), db=db)
        txn = [s for s in executed_sql(db) if "FROM transactions" in s]
        per_event = [s for s in txn if "EXTRACT(" not in s]
        month_total = [s for s in txn if "EXTRACT(" in s]
        self.assertTrue(per_event)
        for s in per_event:
            self.assertIn(NOT_ADJ_TXN, s)
        self.assertEqual(len(month_total), 1)
        self.assertNotIn(NOT_ADJ_TXN, month_total[0])


if __name__ == "__main__":
    unittest.main()
