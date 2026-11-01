"""AI Advisor v2 S13 — GET /advisor/page/transaksi: banner per filter & penanda baris (02-aturan.md §7).

Bagian murni memakai `SnapshotBuilder`; bagian integrasi memakai SQLite in-memory + Redis palsu untuk
flag, dismiss, dan privasi household (amplop pribadi anggota lain tidak pernah muncul).
Run: python -m unittest app.tests.test_advisor_page_transaksi -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.advisor.page_transaksi import susun_halaman
from app.tests.advisor_v2_fixtures import SnapshotBuilder
from app.tests.test_advisor_aturan_s4 import normal

JKT = ZoneInfo("Asia/Jakarta")
TODAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 12, tzinfo=JKT)
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def halaman(b: SnapshotBuilder, **kw):
    return susun_halaman(b.build(), now_local=NOW, **kw)


def aturan_di(p, tid):
    return [x["aturan"] for x in p["penanda"].get(tid, [])]


class PenandaTests(unittest.TestCase):
    def test_har03_belanja_besar(self):
        b = normal(dana=6_000_000)
        kulkas = b.txn("makan", 2_000_000, desc="kulkas")
        p = halaman(b)
        self.assertEqual(aturan_di(p, kulkas), ["HAR-03"])
        self.assertEqual(p["penanda"][kulkas][0]["chip"], "Belanja besar Rp2 jt")

    def test_dat03_dobel_kedua_baris(self):
        b = normal()
        t0 = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)
        a = b.txn("makan", 150_000, desc="belanja pasar", created_at=t0)
        c = b.txn("makan", 150_000, desc="belanja pasar", created_at=t0 + timedelta(minutes=3))
        p = halaman(b)
        self.assertEqual(aturan_di(p, a), ["DAT-03"])
        self.assertEqual(aturan_di(p, c), ["DAT-03"])
        x = p["penanda"][a][0]
        self.assertEqual([k["label"] for k in x["aksi"]], ["Hapus salah satu", "Bukan dobel"])
        self.assertEqual(x["aksi"][0]["payload"]["txn_id"], c)          # saran hapus: yang tercatat belakangan

    def test_dat03_struk_dua_kali_hanya_struk_kedua(self):
        b = normal()
        t0 = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)
        barang = [("Susu (Indomaret)", 20_000), ("Roti (Indomaret)", 15_000)]
        pertama = [b.txn("makan", amt, desc=d, created_at=t0 + timedelta(milliseconds=i * 5))
                   for i, (d, amt) in enumerate(barang)]
        kedua = [b.txn("makan", amt, desc=d, created_at=t0 + timedelta(seconds=40, milliseconds=i * 5))
                 for i, (d, amt) in enumerate(barang)]
        p = halaman(b)
        for tid in pertama:
            self.assertEqual(aturan_di(p, tid), [])
        for tid in kedua:
            self.assertEqual(aturan_di(p, tid), ["DAT-03"])
        self.assertEqual(p["penanda"][kedua[0]][0]["aksi"][0]["label"], "Hapus duplikat (2 barang)")

    def test_dat06_tagihan_dibayar_manual(self):
        b = normal()
        b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
        b.fund("tagihan", 1_000_000, on=b.ps)
        b.recurring("tagihan", 750_000, "Listrik", date(2026, 10, 10), id="listrik")
        tid = b.txn("tagihan", 750_000, on=date(2026, 10, 9), desc="bayar PLN")
        p = halaman(b)
        self.assertEqual(aturan_di(p, tid), ["DAT-06"])
        self.assertEqual([a["kind"] for a in p["penanda"][tid][0]["aksi"]], ["mark_paid", "not_duplicate"])

    def test_tag07_hanya_kemunculan_terakhir(self):
        b = normal()
        ids = [b.txn("makan", 65_000, on=ps + timedelta(days=4), desc="Spotify Family")
               for ps, _ in b.snap.periods[-5:]]
        p = halaman(b)
        self.assertEqual(aturan_di(p, ids[-1]), ["TAG-07"])
        for tid in ids[:-1]:
            self.assertEqual(aturan_di(p, tid), [])
        self.assertEqual(p["penanda"][ids[-1]][0]["aksi"][0]["kind"], "make_recurring")

    def test_dismiss_menyembunyikan_penanda(self):
        b = normal(dana=6_000_000)
        kulkas = b.txn("makan", 2_000_000, desc="kulkas")
        kunci = halaman(b)["penanda"][kulkas][0]["id"]
        p = halaman(b, dismiss={kunci: {"pilihan": "nanti", "tone": "info", "rupiah": "0"}})
        self.assertNotIn(kulkas, p["penanda"])

    def test_tanpa_temuan(self):
        p = halaman(normal())
        self.assertEqual(p["penanda"], {})
        self.assertIsNone(p["banner"])
        self.assertEqual(p["hari_ini"], "2026-10-15")
        json.dumps(p)                                                    # siap dikirim sebagai JSON


class BannerTests(unittest.TestCase):
    def test_filter_hari_ini_sama_dengan_chip_jatah(self):
        b = normal(dana=6_000_000)
        b.txn("makan", 2_000_000, desc="kulkas")
        p = halaman(b, tanggal=TODAY)
        self.assertEqual(p["banner"]["aturan"], "HAR-03")
        self.assertIsNone(halaman(b, tanggal=TODAY - timedelta(days=1))["banner"])   # hari lain: tanpa banner

    def test_filter_amplop_memakai_amp(self):
        b = normal(dana=1_000_000)                                       # Makan minus → AMP-01
        p = halaman(b, amplop="makan")
        self.assertEqual(p["banner"]["aturan"], "AMP-01")
        p2 = halaman(b, amplop="makan", tanggal=TODAY)                   # amplop lebih sempit: menang
        self.assertEqual(p2["banner"]["aturan"], "AMP-01")

    def test_filter_amplop_tak_dikenal(self):
        self.assertIsNone(halaman(normal(dana=1_000_000), amplop="bukan-amplop")["banner"])


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class HalamanIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction, User,
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
            rina = User(name="Rina", payday_day=1, timezone="Asia/Jakarta")
            hh = Household(name="Rumah")
            db.add_all([me, rina, hh])
            await db.flush()
            self.hid = hh.id
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member)])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="Kado Rahasia", owner_id=rina.id, budget_amount=D("0"))
            db.add_all([makan, rahasia])
            await db.flush()
            for user, env in ((me, makan), (rina, rahasia)):
                inc = Income(household_id=hh.id, user_id=user.id, amount=D("500000"), description="Gaji",
                             income_date=today)
                db.add(inc)
                await db.flush()
                db.add(Allocation(income_id=inc.id, envelope_id=env.id, amount=D("500000")))
            # Rina mencatat dobel di amplop pribadinya: tidak boleh terlihat oleh viewer lain.
            t0 = datetime.now(timezone.utc).replace(tzinfo=None)
            for i in range(2):
                db.add(Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("150000"),
                                   description="kado jam", transaction_date=today,
                                   created_at=t0 + timedelta(minutes=i)))
            db.add(AppSetting(key="advisor_v2_users", value=str(me.id)))
            await db.commit()
            self.me, self.rina, self.rahasia, self.today = me, rina, rahasia, today

    async def page(self, user, **kw):
        from app.api.routes import advisor as advisor_routes
        async with self.Session() as db:
            return await advisor_routes.advisor_page_transaksi(user=user, db=db, hid=self.hid, **kw)

    async def test_flag_mati(self):
        self.assertEqual(await self.page(self.rina), {"enabled": False})

    async def test_amplop_pribadi_anggota_lain_tidak_bocor(self):
        p = await self.page(self.me, tanggal=self.today, amplop=self.rahasia.id)
        self.assertTrue(p["enabled"])
        self.assertIsNone(p["banner"])
        self.assertEqual(p["penanda"], {})
        self.assertNotIn("Kado", json.dumps(p))
        self.assertNotIn("kado", json.dumps(p))

    async def test_pemilik_amplop_melihat_penandanya(self):
        """Kontrol positif: pasangan yang sama memang terdeteksi bila dilihat pemiliknya."""
        with patch("app.services.advisor.page_transaksi.flag_aktif", return_value=True):
            p = await self.page(self.rina, amplop=self.rahasia.id)
        self.assertEqual(sorted(x["aturan"] for xs in p["penanda"].values() for x in xs), ["DAT-03", "DAT-03"])


if __name__ == "__main__":
    unittest.main()
