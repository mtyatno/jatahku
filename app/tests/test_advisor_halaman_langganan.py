"""AI Advisor v2 S12 — halaman Langganan: `susun_langganan` (murni, fixture) dan
`GET /advisor/page/langganan` (SQLite in-memory, Redis dipalsukan).

Mengunci (02-aturan.md §6D, §7 "Langganan"): satu insight terbaik per baris langganan
(TAG-01/02/03/04/06, DAT-06), TAG-01 menyerap AMP-01 amplopnya (penekanan 3), ringkasan K4
dengan TAG-05 bila beban > 40% dan TAG-09 selain itu, TAG-07 → `pola`, TAG-08 → `lain`,
dismiss menyembunyikan baris (§9), dan flag `advisor_v2_users`.
Run: python -m unittest app.tests.test_advisor_halaman_langganan -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.advisor.dashboard import analisa
from app.services.advisor.halaman import susun_langganan
from app.tests.advisor_v2_fixtures import SnapshotBuilder
from app.tests.test_advisor_aturan_s4 import contoh_lengkap, normal

JKT = ZoneInfo("Asia/Jakarta")
TODAY = date(2026, 10, 15)
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def halaman(b: SnapshotBuilder, dismiss=None, h=12):
    snap = b.build()
    t = snap.today
    now = datetime(t.year, t.month, t.day, h, tzinfo=JKT)
    ctx, sel = analisa(snap, now_local=now, dismiss=dismiss)
    return susun_langganan(ctx, sel, now_local=now, dismiss=dismiss)


def tagihan(dana, jatuh_tempo, nominal=500_000, frequency="monthly"):
    b = normal()
    b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
    if dana:
        b.fund("tagihan", dana, on=b.ps)
    b.recurring("tagihan", nominal, "Internet", jatuh_tempo, frequency=frequency, id="net")
    return b


class HalamanLanggananTests(unittest.TestCase):
    def test_contoh_12_kpr_telat_geser_bayar(self):
        p = halaman(contoh_lengkap(), h=6)
        self.assertTrue(p["enabled"])
        kpr = p["per_langganan"]["kpr"]
        self.assertEqual((kpr["aturan"], kpr["tone"]), ("TAG-01", "danger"))
        self.assertEqual([a["kind"] for a in kpr["aksi"]], ["plan", "pay"])
        keb = kpr["aksi"][0]["payload"]["kebutuhan"][0]
        self.assertEqual((keb["jumlah"], keb["bayar_recurring_id"]), (2_008_174, "kpr"))
        self.assertIn("AMP-01", [r["aturan"] for r in kpr.get("rincian", [])])   # penekanan 3

    def test_ringkasan_k4_dan_tag09(self):
        p = halaman(tagihan(600_000, date(2026, 10, 25)))
        r = p["ringkasan"]
        self.assertEqual(r["beban_bulanan"], 500_000)
        self.assertEqual(r["dana_belanja"], 4_100_000)
        self.assertEqual(r["beban_persen"], 12)
        self.assertEqual((r["belum"], r["tagihan_sisa"]), (1, 500_000))
        self.assertEqual(r["insight"]["aturan"], "TAG-09")
        self.assertEqual(p["per_langganan"], {})          # jatuh tempo masih jauh: baris tanpa insight

    def test_ringkasan_tag05_beban_tinggi(self):
        p = halaman(tagihan(3_000_000, date(2026, 10, 25), nominal=3_000_000))
        self.assertEqual(p["ringkasan"]["insight"]["aturan"], "TAG-05")
        self.assertGreater(p["ringkasan"]["beban_persen"], 40)

    def test_baris_tag03_dan_tag04(self):
        self.assertEqual(halaman(tagihan(600_000, TODAY + timedelta(days=3)))["per_langganan"]["net"]["aturan"],
                         "TAG-03")
        p = halaman(tagihan(400_000, date(2026, 12, 1), nominal=1_200_000, frequency="yearly"))
        self.assertEqual(p["per_langganan"]["net"]["aturan"], "TAG-04")

    def test_satu_insight_terbaik_per_baris(self):
        b = tagihan(200_000, TODAY + timedelta(days=2))                       # TAG-02 warn
        b.txn("tagihan", 450_000, on=date(2026, 10, 3), desc="🔄 Internet")   # + TAG-06 info
        p = halaman(b)
        self.assertEqual(p["per_langganan"]["net"]["aturan"], "TAG-02")

    def test_dat06_tandai_lunas(self):
        b = normal()
        b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
        b.fund("tagihan", 1_000_000, on=b.ps)
        b.recurring("tagihan", 750_000, "Listrik", date(2026, 10, 10), id="listrik")
        b.txn("tagihan", 750_000, on=date(2026, 10, 9), desc="bayar PLN")
        row = halaman(b)["per_langganan"]["listrik"]
        self.assertEqual(row["aturan"], "DAT-06")
        self.assertEqual(row["aksi"][0], {"kind": "mark_paid", "label": "Tandai lunas",
                                          "payload": {"recurring_id": "listrik"}})

    def test_pola_rutin_jadikan_langganan(self):
        b = normal()
        for ps, _ in b.snap.periods[-5:]:
            b.txn("makan", 65_000, on=ps + timedelta(days=4), desc="Spotify Family")
        p = halaman(b)
        self.assertEqual([i["aturan"] for i in p["pola"]], ["TAG-07"])
        self.assertEqual(p["pola"][0]["aksi"][0]["kind"], "make_recurring")

    def test_langganan_ganda(self):
        b = tagihan(2_000_000, date(2026, 10, 25), nominal=100_000)
        b.recurring("tagihan", 100_000, "Internet", date(2026, 10, 27), id="net2")
        lain = halaman(b)["lain"]
        self.assertEqual(len(lain), 1)
        self.assertEqual(sorted(lain[0]["recurring_ids"]), ["net", "net2"])

    def test_dismiss_menyembunyikan_baris(self):
        b = tagihan(600_000, TODAY + timedelta(days=3))
        kunci = halaman(b)["per_langganan"]["net"]["id"]
        p = halaman(tagihan(600_000, TODAY + timedelta(days=3)),
                    dismiss={kunci: {"pilihan": "periode", "tone": "info", "rupiah": "0"}})
        self.assertNotIn("net", p["per_langganan"])
        self.assertEqual([(d["kunci"], d["pilihan"]) for d in p["disembunyikan"]], [(kunci, "periode")])


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class EndpointLanggananTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income,
            RecurringTransaction, User,
        )
        from app.tests.test_advisor_dashboard_integration import FakeRedis
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        p = patch("redis.asyncio.from_url", return_value=FakeRedis())
        p.start()
        self.addCleanup(p.stop)

        today = datetime.now(JKT).date()
        async with self.Session() as db:
            me = User(name="Saya", payday_day=1, timezone="Asia/Jakarta")
            lain = User(name="Rina", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, lain, hh])
            await db.flush()
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=lain.id, household_id=hh.id, role=HouseholdRole.member)])
            env = Envelope(household_id=hh.id, name="Tagihan", classification="needs", budget_amount=D("0"))
            db.add(env)
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3000000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add(Allocation(income_id=gaji.id, envelope_id=env.id, amount=D("3000000")))
            rec = RecurringTransaction(envelope_id=env.id, amount=D("150000"),
                                       description="Internet", frequency="monthly", next_run=today)
            db.add(rec)
            db.add(AppSetting(key="advisor_v2_users", value=str(me.id)))
            await db.commit()
            self.me, self.lain, self.rec_id = me, lain, str(rec.id)

    async def page(self, user):
        from app.api.routes import advisor as advisor_routes
        async with self.Session() as db:
            return await advisor_routes.advisor_page_langganan(user=user, db=db)

    async def test_flag(self):
        self.assertEqual(await self.page(self.lain), {"enabled": False})

    async def test_bentuk_respons(self):
        data = await self.page(self.me)
        self.assertTrue(data["enabled"])
        self.assertEqual(set(data), {"enabled", "generated_at", "ringkasan", "per_langganan", "pola", "lain",
                                     "disembunyikan"})
        self.assertEqual(data["ringkasan"]["beban_bulanan"], 150_000)
        self.assertIn(self.rec_id, data["per_langganan"])                    # jatuh tempo hari ini


if __name__ == "__main__":
    unittest.main()
