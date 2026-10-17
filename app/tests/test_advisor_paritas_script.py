"""AI Advisor v2 S10 — skrip cek sebelum flag `*` (`app/scripts/advisor_paritas.py`).

Run: python -m unittest app.tests.test_advisor_paritas_script -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import configure_mappers

from app.scripts import advisor_paritas

configure_mappers()
JKT = ZoneInfo("Asia/Jakarta")


class SkripParitasTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction, User,
        )
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        for p in (patch("redis.asyncio.from_url", side_effect=Exception("tanpa redis")),
                  patch("app.services.advisor.advisor_cache.logger")):
            p.start()
            self.addCleanup(p.stop)
        today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            rina = User(name="Rina", payday_day=1)
            baru = User(name="Baru", payday_day=1)                  # belum punya household
            hh = Household(name="Rumah")
            db.add_all([me, rina, baru, hh])
            await db.flush()
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member)])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="Rahasia Rina", owner_id=rina.id, budget_amount=D("0"))
            db.add_all([makan, rahasia])
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3500000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add_all([Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("3000000")),
                        Allocation(income_id=gaji.id, envelope_id=rahasia.id, amount=D("500000")),
                        Transaction(envelope_id=makan.id, user_id=me.id, amount=D("45000"), description="nasi",
                                    transaction_date=today),
                        Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("99000"),
                                    description="kado", transaction_date=today)])
            await db.commit()     # tanpa AppSetting: flag mati, skrip tetap memeriksa
            self.me, self.rina, self.baru = me, rina, baru

    async def _periksa(self, user):
        async with self.Session() as db:
            return await advisor_paritas.periksa(user, db)

    async def test_angka_identik_walau_flag_mati(self):
        for u in (self.me, self.rina):
            h = await self._periksa(u)
            self.assertEqual(h["status"], "ok", h)
            self.assertEqual(h["beda"], [])

    async def test_tanpa_household_dilewati(self):
        h = await self._periksa(self.baru)
        self.assertEqual(h["status"], "lewati")

    async def test_teks_chat_berbeda_dilaporkan(self):
        with patch("app.services.advisor.chat.jawab_sisa", return_value="Sisa bebas  Rp1"):
            h = await self._periksa(self.me)
        self.assertEqual(h["status"], "beda")
        self.assertTrue(all(b.startswith("sisa:") for b in h["beda"]), h["beda"])

    async def test_amplop_pribadi_anggota_lain_dilaporkan(self):
        with patch("app.services.advisor.chat.ringkasan_harian",
                   side_effect=lambda a: "Rahasia Rina " + "\n".join(advisor_paritas.baris_wajib(a.ctx.m.to_api()))):
            h = await self._periksa(self.me)
        self.assertEqual(h["status"], "beda", h)
        self.assertEqual(h["beda"], ["ringkasan: memuat amplop pribadi anggota lain 'Rahasia Rina'"])

    async def test_crash_dilaporkan_bukan_dilempar(self):
        with patch("app.services.advisor.dashboard.compute_metrics", side_effect=ZeroDivisionError("x")):
            h = await self._periksa(self.me)
        self.assertEqual(h["status"], "crash")
        self.assertIn("ZeroDivisionError", h["pesan"])

    async def test_tidak_menulis_database(self):
        from app.models.models import AppSetting, Transaction
        await self._periksa(self.me)
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(AppSetting))).scalar(), 0)
            self.assertEqual((await db.execute(select(func.count()).select_from(Transaction))).scalar(), 2)

    async def test_jalankan_semua_user_dan_kode_keluar(self):
        out = io.StringIO()
        with patch("app.core.database.AsyncSessionLocal", self.Session), redirect_stdout(out):
            kode = await advisor_paritas.jalankan([])
        self.assertEqual(kode, 0, out.getvalue())
        self.assertIn("3 user · ok 2 · beda 0 · crash 0 · lewati 1", out.getvalue())

        out = io.StringIO()
        with patch("app.core.database.AsyncSessionLocal", self.Session), redirect_stdout(out), \
                patch("app.services.advisor.dashboard.compute_metrics", side_effect=ValueError("rusak")):
            kode = await advisor_paritas.jalankan([str(self.me.id)])
        self.assertEqual(kode, 1)
        self.assertIn("1 user · ok 0 · beda 0 · crash 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
