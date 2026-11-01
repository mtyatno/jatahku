"""AI Advisor v2 — snapshot.py + field is_emergency terhadap database sungguhan (SQLite in-memory).

Mengunci: privasi household di loader (skenario 7), jumlah query tetap (tidak
tumbuh per amplop), dan snapshot → metrics berjalan ujung ke ujung.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_advisor_snapshot_integration -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal as D

from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import envelopes as env_routes
from app.core.database import Base
from app.models.models import (
    Allocation, BalanceCheck, Envelope, Goal, Household, HouseholdMember, HouseholdRole, Income,
    MonthlySnapshot, RecurringFrequency, RecurringTransaction, Transaction, User,
)
from app.services.advisor.metrics import compute_metrics
from app.services.advisor.snapshot import load_snapshot

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
TODAY = date(2026, 10, 15)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SnapshotLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)  # juga saat setUp gagal (kalau tidak, tes menggantung)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.queries = 0

        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def _count(*_a, **_k):
            self.queries += 1

        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, plan="pro")
            rina = User(name="Rina", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, rina, hh])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member),
            ])
            makan = Envelope(household_id=hh.id, name="Makan", budget_amount=D("0"))
            tagihan = Envelope(household_id=hh.id, name="Tagihan", purpose="debt", budget_amount=D("0"))
            mine = Envelope(household_id=hh.id, name="Jajan Saya", owner_id=me.id, budget_amount=D("0"))
            secret = Envelope(household_id=hh.id, name="Rahasia Rina", owner_id=rina.id, budget_amount=D("0"))
            darurat = Envelope(household_id=hh.id, name="Dana Darurat", purpose="saving",
                               is_emergency=True, budget_amount=D("0"))
            db.add_all([makan, tagihan, mine, secret, darurat])
            await db.flush()

            gaji = Income(household_id=hh.id, user_id=rina.id, amount=D("5000000"),
                          description="Gaji Rina", income_date=date(2026, 10, 1))
            lama = Income(household_id=hh.id, user_id=me.id, amount=D("1000000"),
                          description="Setoran lama", income_date=date(2025, 1, 5))
            db.add_all([gaji, lama])
            await db.flush()
            db.add_all([
                Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("2000000")),
                Allocation(income_id=gaji.id, envelope_id=tagihan.id, amount=D("1000000")),
                Allocation(income_id=gaji.id, envelope_id=secret.id, amount=D("1500000")),
                Allocation(income_id=gaji.id, envelope_id=darurat.id, amount=D("500000")),
                Allocation(income_id=lama.id, envelope_id=darurat.id, amount=D("1000000")),
            ])
            db.add_all([
                Transaction(envelope_id=makan.id, user_id=rina.id, amount=D("80000"),
                            description="kado ulang tahun", is_private=True,
                            transaction_date=date(2026, 10, 14)),
                Transaction(envelope_id=makan.id, user_id=me.id, amount=D("30000"),
                            description="kopi", is_private=True, transaction_date=TODAY),
                Transaction(envelope_id=secret.id, user_id=rina.id, amount=D("999000"),
                            description="rahasia", transaction_date=TODAY),
                Transaction(envelope_id=tagihan.id, user_id=me.id, amount=D("400000"),
                            description="🔄 Internet", transaction_date=date(2026, 10, 3)),
                Transaction(envelope_id=makan.id, user_id=me.id, amount=D("5000"),
                            description="dihapus", is_deleted=True, transaction_date=TODAY),
                Transaction(envelope_id=darurat.id, user_id=me.id, amount=D("200000"),
                            description="tarik", transaction_date=date(2025, 3, 1)),
            ])
            db.add(RecurringTransaction(envelope_id=tagihan.id, amount=D("400000"), description="Internet",
                                        frequency=RecurringFrequency.monthly, next_run=date(2026, 11, 3)))
            db.add(Goal(envelope_id=darurat.id, name="Darurat 6 bulan", target_amount=D("30000000")))
            db.add(MonthlySnapshot(envelope_id=makan.id, year=2026, month=9,
                                   rollover_amount=D("100000")))
            db.add(BalanceCheck(household_id=hh.id, user_id=me.id, actual_amount=D("1"), app_amount=D("1"),
                                gap=D("-25000"), created_at=datetime(2026, 10, 1, 3, tzinfo=timezone.utc)))
            await db.commit()
            self.me, self.rina, self.hid = me, rina, hh.id
            self.ids = {e.name: str(e.id) for e in (makan, tagihan, mine, secret, darurat)}

    async def snapshot(self):
        async with self.Session() as db:
            return await load_snapshot(self.me, db, today=TODAY, household_id=self.hid)

    async def test_amplop_pribadi_anggota_lain_tidak_dimuat(self):
        snap = await self.snapshot()
        names = {e.name for e in snap.envelopes}
        self.assertEqual(names, {"Makan", "Tagihan", "Jajan Saya", "Dana Darurat"})
        self.assertNotIn(self.ids["Rahasia Rina"], {t.envelope_id for t in snap.transactions})
        self.assertNotIn(D("999000"), {t.amount for t in snap.transactions})
        # alokasi ke amplop tak terlihat tetap ada (untuk P3) tanpa id amplop
        hidden = [a for a in snap.allocations if a.envelope_id is None]
        self.assertEqual([a.amount for a in hidden], [D("1500000")])

    async def test_deskripsi_privat_disamarkan(self):
        snap = await self.snapshot()
        desc = {t.amount: t.description for t in snap.transactions}
        self.assertEqual(desc[D("80000")], "Transaksi privat")    # privat milik Rina
        self.assertEqual(desc[D("30000")], "kopi")                # privat milik sendiri
        self.assertNotIn(D("5000"), desc)                         # dihapus

    async def test_isi_snapshot(self):
        snap = await self.snapshot()
        self.assertEqual(snap.household_id, str(self.hid))
        self.assertEqual(snap.current_period, (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(snap.member_names[str(self.rina.id)], "Rina")
        (bill,) = [t for t in snap.transactions if t.bill_desc]
        self.assertEqual(bill.bill_desc, "Internet")
        self.assertEqual(snap.rollover[(self.ids["Makan"], 2026, 9)], D("100000"))
        self.assertEqual(snap.lifetime_balance, {self.ids["Dana Darurat"]: D("1300000")})
        self.assertEqual(snap.last_balance_check.gap, D("-25000"))
        self.assertEqual(snap.last_balance_check.created_on, date(2026, 10, 1))
        self.assertEqual(snap.last_viewer_txn_date, TODAY)
        self.assertTrue(next(e for e in snap.envelopes if e.name == "Dana Darurat").is_emergency)

    async def test_snapshot_ke_metrics(self):
        m = compute_metrics(await self.snapshot())
        self.assertEqual(m.dana_belanja, D("3100000"))            # 2 jt + 1 jt + rollover 100 rb
        self.assertEqual(m.terpakai_belanja, D("510000"))
        self.assertEqual(m.tagihan_sisa, D("0"))                  # Internet sudah dibayar lewat Bayar
        self.assertEqual(m.sisa_bebas, D("2590000"))
        self.assertEqual(m.pemasukan_saya, D("0"))
        self.assertEqual(m.pemasukan_rumah_tangga, D("5000000"))
        self.assertEqual(m.pemasukan_per_anggota_bersama, {str(self.rina.id): D("3500000")})
        self.assertEqual(m.hari_sejak_cocokkan, 14)
        self.assertEqual(m.amplop_darurat, [self.ids["Dana Darurat"]])

    async def test_jumlah_query_tetap(self):
        self.queries = 0
        await self.snapshot()
        base = self.queries
        async with self.Session() as db:
            for i in range(8):
                db.add(Envelope(household_id=self.hid, name=f"Tambahan {i}", budget_amount=D("0")))
            await db.commit()
        self.queries = 0
        await self.snapshot()
        self.assertEqual(self.queries, base)
        self.assertLessEqual(base, 14)

    async def test_tanpa_household(self):
        async with self.Session() as db:
            loner = User(name="Sendiri")
            db.add(loner)
            await db.commit()
            snap = await load_snapshot(loner, db, today=TODAY, household_id=None)
        self.assertIsNone(snap.household_id)
        self.assertEqual(compute_metrics(snap).sisa_bebas, D("0"))


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class IsEmergencyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)  # juga saat setUp gagal (kalau tidak, tes menggantung)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            user = User(name="Saya", plan="pro")
            hh = Household(name="Rumah")
            db.add_all([user, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole.owner))
            await db.commit()
            self.user, self.user_hid = user, hh.id

    async def create(self, **kw):
        body = {"name": "Amplop", "budget_amount": D("0"), "purpose": "saving", **kw}
        async with self.Session() as db:
            return await env_routes.create_envelope(env_routes.EnvelopeCreate(**body), user=self.user, db=db,
                                                    hid=self.user_hid)

    async def update(self, env, **kw):
        body = {"name": env.name, "budget_amount": D("0"), "purpose": env.purpose, **kw}
        async with self.Session() as db:
            return await env_routes.update_envelope(env.id, env_routes.EnvelopeCreate(**body),
                                                    user=self.user, db=db)

    async def test_buat_ditebak_dari_nama(self):
        self.assertTrue((await self.create(name="Dana Darurat")).is_emergency)
        self.assertFalse((await self.create(name="Liburan")).is_emergency)
        self.assertFalse((await self.create(name="Darurat Liburan", is_emergency=False)).is_emergency)
        self.assertTrue((await self.create(name="Cadangan", is_emergency=True)).is_emergency)

    async def test_ubah_tanpa_field_mempertahankan_nilai(self):
        env = await self.create(name="Cadangan", is_emergency=True)
        self.assertTrue((await self.update(env, name="Cadangan Keluarga")).is_emergency)
        self.assertFalse((await self.update(env, is_emergency=False)).is_emergency)

    async def test_hanya_untuk_tabungan(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.create(name="Makan Darurat", purpose="expense", budget_amount=D("100000"),
                              is_emergency=True)
        self.assertEqual(ctx.exception.status_code, 400)
        env = await self.create(name="Darurat")
        self.assertTrue(env.is_emergency)
        moved = await self.update(env, purpose="expense", budget_amount=D("100000"))
        self.assertFalse(moved.is_emergency)                    # pindah ke belanja melepas tanda

    async def test_response_memuat_field(self):
        env = await self.create(name="Dana Darurat")
        self.assertTrue(env_routes.EnvelopeResponse.model_validate(env).is_emergency)


if __name__ == "__main__":
    unittest.main()
