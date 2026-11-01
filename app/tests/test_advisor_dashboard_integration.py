"""AI Advisor v2 S3 — GET /advisor/dashboard, POST /advisor/dismiss, cache & hook invalidasi
terhadap database sungguhan (SQLite in-memory). Redis dipalsukan.

Mengunci: flag `advisor_v2_users`, cache per (household, viewer) dipakai ulang, commit yang
menulis transaksi/transfer/pemasukan oleh anggota mana pun menghapus cache household itu
(02-aturan.md §14), dan dismiss menyembunyikan item sampai kedaluwarsa (§9).

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_advisor_dashboard_integration -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import fnmatch
import importlib.util
import unittest
from datetime import datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.api.routes import advisor as advisor_routes
from app.core.database import Base
from app.models.models import (
    Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction, User,
)
from app.services.advisor import advisor_cache
from app.services.advisor import dashboard as advisor_dashboard_svc
from app.services.advisor.dashboard import dismiss as do_dismiss, get_dashboard

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
JKT = ZoneInfo("Asia/Jakarta")


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttl = {}       # kunci → `ex` terakhir (None = tanpa kedaluwarsa)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        self.ttl[k] = ex
        return True

    async def get(self, k):
        v = self.store.get(k)
        return v.encode() if isinstance(v, str) else v

    async def mget(self, keys):
        return [await self.get(k) for k in keys]

    async def delete(self, *keys):
        n = 0
        for k in keys:
            k = k.decode() if isinstance(k, bytes) else k
            self.ttl.pop(k, None)
            n += self.store.pop(k, None) is not None
        return n

    async def scan_iter(self, match="*", count=None):
        for k in list(self.store):
            if fnmatch.fnmatchcase(k, match):
                yield k

    async def aclose(self):
        pass


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DashboardIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)

        self.today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            rina = User(name="Rina", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, rina, hh])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member),
            ])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            db.add(makan)
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3000000"), description="Gaji",
                          income_date=self.today)
            db.add(gaji)
            await db.flush()
            db.add(Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("3000000")))
            db.add(AppSetting(key="advisor_v2_users", value=str(me.id)))
            await db.commit()
            self.me, self.rina, self.hid, self.makan = me, rina, str(hh.id), makan
            self.hh_id = hh.id

    async def dashboard(self, user=None):
        async with self.Session() as db:
            return await advisor_routes.advisor_dashboard(user=user or self.me, db=db, hid=self.hh_id)

    async def test_flag(self):
        self.assertEqual(await self.dashboard(self.rina), {"enabled": False})
        data = await self.dashboard()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["metrics"]["dana_belanja"], 3_000_000)
        self.assertIsNotNone(data["kpi"]["jatah"])

    async def test_flag_bintang(self):
        async with self.Session() as db:
            setting = await db.get(AppSetting, "advisor_v2_users")
            setting.value = "*"
            await db.commit()
        self.assertTrue((await self.dashboard(self.rina))["enabled"])

    async def test_cache_dipakai_ulang(self):
        first = await self.dashboard()
        self.assertIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)
        with patch("app.services.advisor.snapshot.load_snapshot", side_effect=AssertionError("tidak dimuat ulang")):
            again = await self.dashboard()
        self.assertEqual(first, again)

    async def test_hook_commit_menghapus_cache_household(self):
        advisor_cache.install()
        self.addCleanup(advisor_cache.uninstall)
        await self.dashboard()
        key = advisor_cache.kunci_dashboard(self.hid, self.me.id)
        self.redis.store[advisor_cache.kunci_dashboard(self.hid, self.rina.id)] = "{}"
        self.redis.store["advisor:lain:x"] = "{}"
        async with self.Session() as db:  # anggota lain mencatat transaksi
            db.add(Transaction(envelope_id=self.makan.id, user_id=self.rina.id, amount=D("25000"),
                               description="kopi", transaction_date=self.today))
            await db.commit()
        for _ in range(5):
            await asyncio.sleep(0)
        await asyncio.gather(*advisor_cache._tasks)
        self.assertNotIn(key, self.redis.store)
        self.assertNotIn(advisor_cache.kunci_dashboard(self.hid, self.rina.id), self.redis.store)
        self.assertIn("advisor:lain:x", self.redis.store)
        data = await self.dashboard()
        self.assertEqual(data["metrics"]["belanja_hari_ini"], 25_000)

    async def test_hook_rollback_tidak_menghapus(self):
        advisor_cache.install()
        self.addCleanup(advisor_cache.uninstall)
        await self.dashboard()
        async with self.Session() as db:
            db.add(Transaction(envelope_id=self.makan.id, user_id=self.me.id, amount=D("1"),
                               description="x", transaction_date=self.today))
            await db.flush()
            await db.rollback()
        await asyncio.sleep(0)
        self.assertIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)

    async def test_kumpulkan_household_dari_alokasi(self):
        async with self.Session() as db:
            income = (await db.execute(select(Income))).scalars().first()
            db.add(Allocation(income_id=income.id, envelope_id=self.makan.id, amount=D("1")))
            await db.flush()
            hids = await db.run_sync(lambda s: advisor_cache.kumpulkan_household(s))
            self.assertEqual(hids, set())   # sesudah flush tidak ada yang tertunda
            db.add(Allocation(income_id=income.id, envelope_id=self.makan.id, amount=D("2")))
            hids = await db.run_sync(lambda s: advisor_cache.kumpulkan_household(s))
            self.assertEqual(hids, {self.hid})
            await db.rollback()

    async def test_dismiss_menyembunyikan_lalu_cache_viewer_dihapus(self):
        # Belanja besar hari ini → HAR-01 danger, masuk daftar (periode masih aman).
        async with self.Session() as db:
            db.add(Transaction(envelope_id=self.makan.id, user_id=self.me.id, amount=D("400000"),
                               description="belanja", transaction_date=self.today))
            await db.commit()
        data = await self.dashboard()
        item = next((i for i in data["advisor"]["items"] if i["aturan"] == "HAR-01"), None)
        if item is None:
            self.skipTest("hari ini tidak memicu HAR-01 di daftar (awal/akhir periode)")
        async with self.Session() as db:
            resp = await advisor_routes.advisor_dismiss(
                advisor_routes.DismissRequest(kunci=item["id"], pilihan="nanti"), user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(resp.status_code, 204)
        stored = self.redis.store[advisor_cache.kunci_dismiss(self.me.id, item["id"])]
        self.assertIn('"tone": "danger"', stored)
        data = await self.dashboard()
        self.assertNotIn(item["id"], [i["id"] for i in data["advisor"]["items"]])

    async def test_dismiss_tanpa_cache(self):
        async with self.Session() as db:
            await do_dismiss(self.me, db, "PER-05:x", "periode", now=datetime.now(JKT), household_id=self.hh_id)
        self.assertIn(advisor_cache.kunci_dismiss(self.me.id, "PER-05:x"), self.redis.store)

    async def test_batal_dismiss_memunculkan_lagi(self):
        # #91: Sembunyikan chip Jatah hari ini → masuk `disembunyikan` → Urungkan → kembali.
        data = await self.dashboard()
        chip = data["kpi"]["jatah"]
        kunci = chip["dismiss"]["kunci"]
        self.assertEqual(data["advisor"]["disembunyikan"], [])
        async with self.Session() as db:
            await advisor_routes.advisor_dismiss(
                advisor_routes.DismissRequest(kunci=kunci, pilihan="nanti"), user=self.me, db=db, hid=self.hh_id)
        data = await self.dashboard()
        self.assertNotEqual((data["kpi"]["jatah"] or {}).get("id"), chip["id"])
        sembunyi = data["advisor"]["disembunyikan"]
        self.assertEqual([d["kunci"] for d in sembunyi], [kunci])
        self.assertEqual(sembunyi[0]["pilihan"], "nanti")
        self.assertTrue(sembunyi[0]["judul_pendek"])

        self.redis.store[advisor_cache.kunci_dismiss(self.rina.id, kunci)] = '{"pilihan": "nanti"}'
        async with self.Session() as db:
            resp = await advisor_routes.advisor_batal_dismiss(kunci=kunci, user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(resp.status_code, 204)
        self.assertNotIn(advisor_cache.kunci_dismiss(self.me.id, kunci), self.redis.store)
        self.assertNotIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)
        self.assertIn(advisor_cache.kunci_dismiss(self.rina.id, kunci), self.redis.store)  # milik viewer lain
        data = await self.dashboard()
        self.assertEqual(data["kpi"]["jatah"]["id"], chip["id"])
        self.assertEqual(data["advisor"]["disembunyikan"], [])

    async def test_batal_dismiss_idempoten(self):
        async with self.Session() as db:
            resp = await advisor_routes.advisor_batal_dismiss(kunci="PER-05:x", user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(resp.status_code, 204)
        async with self.Session() as db:
            self.assertFalse(await advisor_dashboard_svc.batal_dismiss(self.me, db, "PER-05:x", household_id=self.hh_id))
            await do_dismiss(self.me, db, "PER-05:x", "periode", now=datetime.now(JKT), household_id=self.hh_id)
            self.assertTrue(await advisor_dashboard_svc.batal_dismiss(self.me, db, "PER-05:x", household_id=self.hh_id))

    async def test_batal_dismiss_redis_gagal_503(self):
        from fastapi import HTTPException
        async def rusak(*a, **k):
            raise ConnectionError("redis putus")
        with patch.object(self.redis, "delete", rusak):
            async with self.Session() as db:
                with self.assertRaises(HTTPException) as cm:
                    await advisor_routes.advisor_batal_dismiss(kunci="PER-05:x", user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(cm.exception.status_code, 503)

    async def test_dismiss_berubah_saat_menghitung_tidak_disimpan_ke_cache(self):
        asli = advisor_dashboard_svc._hitung
        async def hitung_lalu_urungkan(*a, **k):
            hasil = await asli(*a, **k)
            self.redis.store[advisor_cache.kunci_dismiss(self.me.id, "PER-05:x")] = '{"pilihan": "nanti"}'
            return hasil
        with patch.object(advisor_dashboard_svc, "_hitung", hitung_lalu_urungkan):
            await self.dashboard()
        self.assertNotIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)
        await self.dashboard()   # muatan berikutnya stabil → disimpan
        self.assertIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)

    async def test_bukan_dobel_permanen_lalu_dimunculkan_lagi(self):
        # #93: "Bukan dobel" (DAT-03) disimpan tanpa TTL, dan Munculkan lagi (#91) tetap menghapusnya.
        async with self.Session() as db:
            for _ in range(2):
                db.add(Transaction(envelope_id=self.makan.id, user_id=self.me.id, amount=D("150000"),
                                   description="belanja pasar", transaction_date=self.today))
            await db.commit()

        def ids(data):
            adv = data["advisor"]
            return [i["id"] for i in adv["items"]] + [x["id"] for x in adv["sisa"]]
        kunci = next((k for k in ids(await self.dashboard()) if k.startswith("DAT-03:")), None)
        self.assertIsNotNone(kunci)
        async with self.Session() as db:
            resp = await advisor_routes.advisor_dismiss(
                advisor_routes.DismissRequest(kunci=kunci, pilihan="bukan_dobel"), user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(resp.status_code, 204)
        key = advisor_cache.kunci_dismiss(self.me.id, kunci)
        self.assertIsNone(self.redis.ttl[key])                                  # permanen
        self.assertIn('"pilihan": "bukan_dobel"', self.redis.store[key])
        data = await self.dashboard()
        self.assertNotIn(kunci, ids(data))
        self.assertIn((kunci, "bukan_dobel"), [(d["kunci"], d["pilihan"]) for d in data["advisor"]["disembunyikan"]])

        async with self.Session() as db:
            resp = await advisor_routes.advisor_batal_dismiss(kunci=kunci, user=self.me, db=db, hid=self.hh_id)
        self.assertEqual(resp.status_code, 204)
        self.assertNotIn(key, self.redis.store)
        self.assertIn(kunci, ids(await self.dashboard()))

    async def test_bukan_tagihan_sampai_akhir_periode(self):
        # #93: DAT-06 dikunci per langganan → "Bukan pembayaran tagihan" hanya untuk periode ini.
        from app.core.period import get_budget_period
        now = datetime.now(JKT)
        async with self.Session() as db:
            await do_dismiss(self.me, db, "DAT-06:listrik", "bukan_tagihan", now=now, household_id=self.hh_id)
        key = advisor_cache.kunci_dismiss(self.me.id, "DAT-06:listrik")
        pe = get_budget_period(self.me.payday_day, now.date())[1]
        self.assertEqual(self.redis.ttl[key], advisor_cache.ttl_dismiss("periode", now, pe))
        self.assertIn('"pilihan": "bukan_tagihan"', self.redis.store[key])

    async def test_tanggal_berganti_cache_lama_diabaikan(self):
        await self.dashboard()
        key = advisor_cache.kunci_dashboard(self.hid, self.me.id)
        besok = datetime.now(JKT) + timedelta(days=1)
        async with self.Session() as db:
            data = await get_dashboard(self.me, db, now=besok, household_id=self.hh_id)
        self.assertTrue(data["generated_at"].startswith(besok.date().isoformat()))
        self.assertIn(key, self.redis.store)


class DismissHttpTests(unittest.TestCase):
    """#93: `bukan_dobel` hanya untuk kunci DAT-03 dan `bukan_tagihan` hanya untuk DAT-06 → 422
    sebelum apa pun disimpan. Tidak butuh database (dismiss dipalsukan)."""

    def setUp(self):
        import uuid
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.database import get_db
        from app.core.deps import get_current_user

        async def tanpa_db():
            yield None
        app = FastAPI()
        app.include_router(advisor_routes.router, prefix="/advisor")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
        app.dependency_overrides[get_db] = tanpa_db
        from app.services.ruang import ruang_aktif
        app.dependency_overrides[ruang_aktif] = lambda: uuid.uuid4()  # tanpa database
        self.dismiss = AsyncMock()
        p = patch.object(advisor_dashboard_svc, "dismiss", self.dismiss)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app)

    def post(self, kunci, pilihan):
        return self.client.post("/advisor/dismiss", json={"kunci": kunci, "pilihan": pilihan})

    def test_pilihan_khusus_untuk_kunci_aturannya(self):
        self.assertEqual(self.post("DAT-03:t1", "bukan_dobel").status_code, 204)
        self.assertEqual(self.post("DAT-06:listrik", "bukan_tagihan").status_code, 204)
        self.assertEqual(self.post("DAT-03:t1", "tidak_relevan").status_code, 204)   # menu umum tetap boleh
        self.assertEqual([c.args[2:] for c in self.dismiss.await_args_list],
                         [("DAT-03:t1", "bukan_dobel"), ("DAT-06:listrik", "bukan_tagihan"),
                          ("DAT-03:t1", "tidak_relevan")])

    def test_pilihan_khusus_untuk_kunci_lain_ditolak(self):
        for kunci, pilihan in [("TAG-01:kpr", "bukan_dobel"), ("DAT-06:listrik", "bukan_dobel"),
                               ("DAT-03:t1", "bukan_tagihan"), ("DAT-03:t1", "selamanya")]:
            with self.subTest(kunci=kunci, pilihan=pilihan):
                self.assertEqual(self.post(kunci, pilihan).status_code, 422)
        self.dismiss.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
