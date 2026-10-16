"""AI Advisor v2 — POST /advisor/plan & /advisor/execute terhadap database sungguhan (SQLite in-memory).

Mengunci (02-aturan.md §8.9, §13 skenario 7 & 10): transfer + bayar tagihan dalam satu
commit, idempoten dengan client_ref, 409 + rencana_baru bila saldo berubah, rencana
yang diubah klien divalidasi ulang di server, dan transfer manual tetap jalan dengan
kunci household. Redis dipalsukan.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_advisor_plan_integration -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from sqlalchemy import func, select

from app.api.routes import advisor as advisor_routes, envelopes as env_routes
# Impor di luar event loop (impor lambat di dalam tes memicu peringatan asyncio debug).
from app.services import goal_notify as _goal_notify, recurring_processor as _recurring  # noqa: F401
from app.core.database import Base
from app.models.models import (
    Allocation, Envelope, Household, HouseholdMember, HouseholdRole, Income, RecurringFrequency,
    RecurringTransaction, Transaction, User,
)
from app.services.advisor.execute import PlanError, build_plan, execute_plan

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def get(self, k):
        v = self.store.get(k)
        return v.encode() if isinstance(v, str) else v

    async def delete(self, k):
        self.store.pop(k, None)

    async def aclose(self):
        pass


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class PlanExecuteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)  # juga saat setUp gagal (kalau tidak, tes menggantung)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        today = date.today()
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
            envs = {
                "Makan": Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0")),
                "Tagihan": Envelope(household_id=hh.id, name="Tagihan", purpose="debt", budget_amount=D("0")),
                "Hobi": Envelope(household_id=hh.id, name="Hobi", classification="wants", budget_amount=D("100000")),
                "Kunci": Envelope(household_id=hh.id, name="Kunci", classification="wants", is_locked=True,
                                  budget_amount=D("100000")),
                "Rahasia": Envelope(household_id=hh.id, name="Rahasia Rina", classification="wants",
                                    owner_id=rina.id, budget_amount=D("100000")),
                "Tabungan": Envelope(household_id=hh.id, name="Tabungan", purpose="saving", budget_amount=D("0")),
            }
            db.add_all(envs.values())
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3100000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            for name, amt in [("Makan", 500_000), ("Tagihan", 100_000), ("Hobi", 500_000), ("Kunci", 500_000),
                              ("Rahasia", 500_000), ("Tabungan", 1_000_000)]:
                db.add(Allocation(income_id=gaji.id, envelope_id=envs[name].id, amount=D(amt)))
            internet = RecurringTransaction(envelope_id=envs["Tagihan"].id, amount=D("300000"),
                                            description="Internet", frequency=RecurringFrequency.monthly,
                                            next_run=today)
            db.add(internet)
            await db.commit()
            self.me, self.rina, self.hid = me, rina, hh.id
            self.ids = {k: str(e.id) for k, e in envs.items()}
            self.rec_id, self.rec_next = str(internet.id), internet.next_run

        self.kebutuhan = [{"tujuan_id": self.ids["Tagihan"], "jumlah": 200_000, "bayar_recurring_id": self.rec_id}]

    async def count(self, model):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(model))).scalar()

    async def plan(self, **kw):
        async with self.Session() as db:
            return await build_plan(self.me, db, self.kebutuhan, **kw)

    async def execute(self, plan, ref="ref-1", **override):
        body = {"rencana": [r for r in plan["rencana"] if r["tercentang"]], "bayar": plan["bayar"],
                "saldo_versi": plan["saldo_versi"], "client_ref": ref, "kebutuhan": plan["kebutuhan"]}
        body.update(override)
        async with self.Session() as db:
            return await execute_plan(self.me, db, json.loads(json.dumps(body)))

    # ── plan ─────────────────────────────────────────────────────────────
    async def test_plan_hanya_sumber_sah(self):
        """Skenario 7 & 10: terkunci, pribadi anggota lain, tabungan tidak dipakai otomatis."""
        plan = await self.plan()
        self.assertEqual([(r["dari_nama"], r["jumlah"], r["tingkat"]) for r in plan["rencana"]],
                         [("Hobi", 200_000, "a")])
        self.assertEqual(plan["kurang"], 0)
        self.assertEqual(plan["bayar"], [{"recurring_id": self.rec_id, "jumlah": 300_000}])
        dump = json.dumps(plan)
        for name in ("Rahasia", "Kunci", "Tabungan"):
            self.assertNotIn(self.ids[name], dump)

    async def test_plan_route_400_untuk_amplop_tak_terlihat(self):
        req = advisor_routes.PlanRequest(kebutuhan=[{"tujuan_id": self.ids["Rahasia"], "jumlah": 1000}])
        async with self.Session() as db:
            with self.assertRaises(Exception) as ctx:
                await advisor_routes.advisor_plan(req, self.me, db)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 400)

    # ── execute ──────────────────────────────────────────────────────────
    async def test_execute_transfer_dan_bayar_satu_commit(self):
        plan = await self.plan()
        res = await self.execute(plan)
        self.assertEqual(res["status"], "ok")
        self.assertEqual([(t["dari_nama"], t["ke_nama"], t["jumlah"]) for t in res["transfer"]],
                         [("Hobi", "Tagihan", 200_000)])
        self.assertEqual([(d["deskripsi"], d["jumlah"]) for d in res["dibayar"]], [("Internet", 300_000)])
        async with self.Session() as db:
            transfer = (await db.execute(select(Income).where(Income.amount == 0))).scalars().one()
            allocs = (await db.execute(select(Allocation.envelope_id, Allocation.amount)
                                       .where(Allocation.income_id == transfer.id))).all()
            self.assertEqual(sorted((str(e), a) for e, a in allocs),
                             sorted([(self.ids["Hobi"], D("-200000")), (self.ids["Tagihan"], D("200000"))]))
            txn = (await db.execute(select(Transaction))).scalars().one()
            self.assertEqual((txn.description, txn.amount, str(txn.envelope_id)),
                             ("🔄 Internet", D("300000"), self.ids["Tagihan"]))
            rec = await db.get(RecurringTransaction, _uuid(self.rec_id))
            self.assertGreater(rec.next_run, self.rec_next)
        self.assertEqual(self.redis.store[f"txnref:{self.me.id}:ref-1"], json.dumps(res))

    async def test_client_ref_sama_hanya_sekali(self):
        plan = await self.plan()
        first = await self.execute(plan)
        again = await self.execute(plan)
        self.assertEqual(again, first)
        self.assertEqual(await self.count(Transaction), 1)
        self.assertEqual(await self.count(Income), 2)  # gaji + satu transfer

    async def test_saldo_berubah_409_dengan_rencana_baru(self):
        plan = await self.plan()
        async with self.Session() as db:  # Rina belanja dari Hobi sesudah rencana dibuat
            db.add(Transaction(envelope_id=_uuid(self.ids["Hobi"]), user_id=self.rina.id, amount=D("450000"), description="sepatu",
                               transaction_date=date.today()))
            await db.commit()
        req = advisor_routes.ExecuteRequest(
            rencana=plan["rencana"], bayar=plan["bayar"], saldo_versi=plan["saldo_versi"],
            client_ref="ref-409", kebutuhan=plan["kebutuhan"])
        async with self.Session() as db:
            resp = await advisor_routes.advisor_execute(req, self.me, db)
        self.assertEqual(resp.status_code, 409)
        body = json.loads(resp.body)
        self.assertEqual(body["detail"], "Saldo berubah")
        baru = body["rencana_baru"]
        self.assertNotEqual(baru["saldo_versi"], plan["saldo_versi"])
        self.assertLess(sum(r["jumlah"] for r in baru["rencana"] if r["tercentang"]), 200_000)
        self.assertEqual(await self.count(Income), 1)          # tidak ada transfer
        self.assertEqual(await self.count(Transaction), 1)     # hanya belanja Rina
        self.assertNotIn(f"txnref:{self.me.id}:ref-409", self.redis.store)  # ref dilepas

    async def test_rencana_diubah_klien_ditolak(self):
        plan = await self.plan()
        cases = {
            "terkunci": [{"dari_id": self.ids["Kunci"], "ke": [{"tujuan_id": self.ids["Tagihan"], "jumlah": 1000}]}],
            "tak terlihat": [{"dari_id": self.ids["Rahasia"], "ke": [{"tujuan_id": self.ids["Tagihan"], "jumlah": 1000}]}],
            "melebihi sisa": [{"dari_id": self.ids["Hobi"], "ke": [{"tujuan_id": self.ids["Tagihan"], "jumlah": 600_000}]}],
            "sumber = tujuan": [{"dari_id": self.ids["Hobi"], "ke": [{"tujuan_id": self.ids["Hobi"], "jumlah": 1000}]}],
        }
        for label, rencana in cases.items():
            with self.subTest(label):
                with self.assertRaises(PlanError) as ctx:
                    await self.execute(plan, ref=f"ref-{label}", rencana=rencana)
                self.assertEqual(ctx.exception.status, 400)
                self.assertNotIn(f"txnref:{self.me.id}:ref-{label}", self.redis.store)
        self.assertEqual(await self.count(Income), 1)
        self.assertEqual(await self.count(Transaction), 0)

    async def test_tabungan_dipakai_bila_dipilih(self):
        self.kebutuhan = [{"tujuan_id": self.ids["Makan"], "jumlah": 900_000}]
        plan = await self.plan(sertakan=[self.ids["Tabungan"]])
        self.assertEqual([(r["dari_nama"], r["tingkat"], r["jumlah"]) for r in plan["rencana"]],
                         [("Hobi", "a", plan["rencana"][0]["jumlah"]), ("Tabungan", "d", 900_000 - plan["rencana"][0]["jumlah"])])
        res = await self.execute(plan, ref="ref-tab")
        self.assertEqual(sum(t["jumlah"] for t in res["transfer"]), 900_000)

    async def test_transfer_manual_tetap_jalan_dengan_kunci(self):
        async with self.Session() as db:
            res = await env_routes.transfer_between_envelopes(
                _uuid(self.ids["Hobi"]), _uuid(self.ids["Makan"]), D("1000"), self.me, db)
        self.assertEqual(res["status"], "transferred")


def _uuid(s):
    import uuid
    return uuid.UUID(s)


if __name__ == "__main__":
    unittest.main()
