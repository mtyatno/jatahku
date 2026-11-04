"""Siklus saldo per ruang (temuan review keamanan PR #177, di luar PR itu).

Ruang usaha memakai siklusnya sendiri (`households.payday_day`, bulan kalender), bukan tanggal gajian keluarga
pemanggil. Owner dengan gajian keluarga tgl 25 dan "hari ini" 26 Nov (dipatok):

1. `payday_ruang`: ruang keluarga = payday user (angka lama tidak berubah), ruang usaha = siklus ruang itu.
2. `GET /envelopes/summary` di ruang usaha menghitung November kalender: isi 2 Nov dan pengeluaran 10 Nov ikut.
3. Geser dana di ruang usaha tidak melampaui sisa bulan kalender.
4. Catat pengeluaran (cek perilaku "belum diisi") melihat isi amplop sejak tgl 1, bukan sejak tgl 25.
5. Ruang keluarga pengguna yang sama tetap memakai siklus tgl 25.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_siklus_ruang_usaha -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
HARI_INI = date(2026, 11, 26)

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI

    from app.api.routes import envelopes, transactions
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, Income,
        Transaction, User,
    )
    from app.services import ruang
    from app.services.household_cycle import payday_ruang
    from app.tests.test_advisor_dashboard_integration import FakeRedis


class _Hari(date):
    @classmethod
    def today(cls):
        return HARI_INI


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SiklusRuangUsahaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        for target, nilai in (("redis.asyncio.from_url", self.redis),):
            p = patch(target, return_value=nilai)
            p.start()
            self.addCleanup(p.stop)
        for modul in ("app.core.period.date", "app.services.envelope_balance.date"):
            p = patch(modul, _Hari)
            p.start()
            self.addCleanup(p.stop)

        async with self.Session() as db:
            self.me = User(name="Saya", payday_day=25, timezone="Asia/Jakarta", plan="pro")
            rumah = Household(name="Rumah", payday_day=25)
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA, payday_day=1)
            db.add_all([self.me, rumah, usaha])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=self.me.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.me.id, household_id=usaha.id, role=HouseholdRole.owner),
                AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"),
            ])
            self.kas = await self._amplop(db, usaha.id, "Kas", D("1000000"), date(2026, 11, 2))
            self.bahan = await self._amplop(db, usaha.id, "Bahan", D("0"), None)
            self.makan = await self._amplop(db, rumah.id, "Makan", D("500000"), date(2026, 11, 2))
            db.add(Transaction(envelope_id=self.kas, user_id=self.me.id, amount=D("300000"),
                               description="sewa kios", transaction_date=date(2026, 11, 10)))
            await db.commit()
        self.rumah_id, self.usaha_id = rumah.id, usaha.id

        app = FastAPI()
        ruang.install(app)
        app.include_router(envelopes.router, prefix="/envelopes")
        app.include_router(transactions.router, prefix="/transactions")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.me
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def _amplop(self, db, hid, nama, isi, tanggal):
        env = Envelope(household_id=hid, name=nama, emoji="💼", budget_amount=D("1"))
        db.add(env)
        await db.flush()
        if isi:
            inc = Income(household_id=hid, user_id=self.me.id, amount=isi, description=f"Isi {nama}",
                         income_date=tanggal)
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=env.id, amount=isi))
            await db.flush()
        return env.id

    async def _summary(self, hid):
        r = await self.client.get("/envelopes/summary", headers={ruang.RUANG_HEADER: str(hid)})
        self.assertEqual(r.status_code, 200, r.text)
        return {row["name"]: row for row in r.json()}

    async def test_payday_ruang(self):
        async with self.Session() as db:
            self.assertEqual(await payday_ruang(db, self.me, self.rumah_id), 25)
            self.assertEqual(await payday_ruang(db, self.me, self.usaha_id), 1)
            self.assertEqual(await payday_ruang(db, self.me, None), 25)

    async def test_summary_ruang_usaha_bulan_kalender(self):
        kas = (await self._summary(self.usaha_id))["Kas"]
        # Siklus tgl 25 (salah) hanya melihat 25–26 Nov: isi 0, pengeluaran 0.
        self.assertEqual(D(str(kas["allocated"])), D("1000000"))
        self.assertEqual(D(str(kas["spent"])), D("300000"))
        self.assertEqual(D(str(kas["remaining"])), D("700000"))

    async def test_summary_ruang_keluarga_tetap_siklus_gajian(self):
        makan = (await self._summary(self.rumah_id))["Makan"]
        self.assertEqual(D(str(makan["allocated"])), D("0"))   # isi 2 Nov milik periode 25 Okt–24 Nov

    async def test_geser_dana_dibatasi_sisa_bulan_kalender(self):
        r = await self.client.post("/envelopes/transfer", params={
            "from_id": str(self.kas), "to_id": str(self.bahan), "amount": "800000"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("700.000", r.json()["detail"])
        r = await self.client.post("/envelopes/transfer", params={
            "from_id": str(self.kas), "to_id": str(self.bahan), "amount": "700000"})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_catat_pengeluaran_melihat_isi_sejak_tanggal_1(self):
        r = await self.client.post("/transactions/", json={
            "envelope_id": str(self.kas), "amount": "50000", "description": "kardus",
            "transaction_date": HARI_INI.isoformat(), "client_ref": "kardus-1"})
        self.assertEqual(r.status_code, 201, r.text)


if __name__ == "__main__":
    unittest.main()
