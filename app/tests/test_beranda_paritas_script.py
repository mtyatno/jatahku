"""Plugin B3 — skrip cek Gerbang B sebelum flag `beranda_registry_users` = `*`
(`app/scripts/beranda_paritas.py`).

Mengunci: lulus untuk household normal (periode berjalan dan lalu), user tanpa household dilewati,
sumber yang menyimpang dan nama amplop pribadi yang bocor terdeteksi (kode keluar 1), crash satu user
tidak menghentikan yang lain, keluaran tanpa nama amplop, dan cache AI Advisor tidak ditulis.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_beranda_paritas_script -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")

if HAS_AIOSQLITE:
    from app.scripts import beranda_paritas
    from app.tests.test_advisor_dashboard_integration import FakeRedis


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class BerandaParitasTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction, User,
        )
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            rina = User(name="Rina", payday_day=1, timezone="Asia/Jakarta")
            sendiri = User(name="Baru", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, rina, sendiri, hh])
            await db.flush()
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member)])
            makan = Envelope(household_id=hh.id, name="Makan", budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="KadoRahasiaRina", owner_id=rina.id, budget_amount=D("0"))
            db.add_all([makan, rahasia])
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3000000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add_all([
                Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("3000000")),
                Transaction(envelope_id=makan.id, user_id=me.id, amount=D("35000"), description="kopi",
                            transaction_date=today),
                Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("500000"), description="kado",
                            transaction_date=today),
                AppSetting(key="advisor_v2_users", value="*"),
            ])
            await db.commit()
        self.me, self.rina, self.sendiri = me, rina, sendiri

    async def jalankan(self, ids=None):
        out = io.StringIO()
        with redirect_stdout(out):
            kode = await beranda_paritas.jalankan(ids or [], Session=self.Session)
        return kode, out.getvalue()

    async def test_lulus_untuk_semua_user(self):
        kode, out = await self.jalankan()
        self.assertEqual(kode, 0, out)
        self.assertIn("ok 2", out)
        self.assertIn("lewati 1", out)
        self.assertIn("Gerbang B: LULUS", out)
        self.assertNotIn("KadoRahasiaRina", out)
        self.assertNotIn("kopi", out)

    async def test_cache_advisor_tidak_ditulis(self):
        await self.jalankan()
        self.assertFalse([k for k in self.redis.store if "dashboard" in k], self.redis.store)

    async def test_sumber_menyimpang_terdeteksi(self):
        # Hanya jalur batch yang menyimpang (penyedia kartu), endpoint lama tetap: harus terdeteksi.
        from app.services.dashboard import providers
        asli_penyedia = providers.PROVIDERS["core.pengeluaran_harian"]

        async def penyedia_salah(s, settings):
            d = await asli_penyedia(s, settings)
            d["sumber"]["harian"] = d["sumber"]["harian"] + [{"date": "2000-01-01", "total": 1.0, "count": 1}]
            return d

        with patch.dict(providers.PROVIDERS, {"core.pengeluaran_harian": penyedia_salah}):
            kode, out = await self.jalankan([str(self.me.id)])
        self.assertEqual(kode, 1)
        self.assertIn("sumber harian di core.pengeluaran_harian: beda dengan endpoint lama", out)
        self.assertIn("Gerbang B: BELUM LULUS", out)

    async def test_kebocoran_amplop_pribadi_terdeteksi_tanpa_mencetak_namanya(self):
        from app.services.dashboard import providers
        asli = providers.PROVIDERS["core.langganan"]

        async def bocor(s, settings):
            d = await asli(s, settings)
            d["catatan"] = "KadoRahasiaRina"
            return d

        with patch.dict(providers.PROVIDERS, {"core.langganan": bocor}):
            kode, out = await self.jalankan([str(self.me.id)])
        self.assertEqual(kode, 1)
        self.assertIn("nama amplop pribadi anggota lain muncul", out)
        self.assertNotIn("KadoRahasiaRina", out)

    async def test_kartu_error_dan_crash_dilaporkan_lalu_lanjut(self):
        from app.api.routes import recurring

        async def rusak(**_kw):
            raise RuntimeError("rusak")

        with patch.object(recurring, "recurring_period_summary", rusak):
            kode, out = await self.jalankan()
        self.assertEqual(kode, 1)
        self.assertIn("core.kpi.tagihan: error gagal_memuat", out)

        with patch.object(beranda_paritas, "nama_amplop_pribadi_lain", side_effect=RuntimeError("boom")):
            kode, out = await self.jalankan()
        self.assertEqual(kode, 1)
        self.assertIn("crash 2", out)
        self.assertIn("lewati 1", out)

    async def test_p95_melewati_anggaran(self):
        with patch.object(beranda_paritas, "TARGET_P95_MS", 0):
            kode, out = await self.jalankan([str(self.me.id)])
        self.assertEqual(kode, 1)
        self.assertIn("BELUM LULUS", out)

    def test_p95(self):
        self.assertEqual(beranda_paritas.p95([]), 0.0)
        self.assertEqual(beranda_paritas.p95(list(range(1, 21))), 19)
        self.assertEqual(beranda_paritas.p95([5]), 5)


if __name__ == "__main__":
    unittest.main()
