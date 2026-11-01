"""AI Advisor v2 S11 — halaman Amplop: `GET /advisor/page/amplop` (02-aturan.md §6C, §7 "Halaman lain").

- Satu insight terbaik per kartu dari AMP-*, TAG-* amplop itu, TAB-* untuk tabungan;
  urutan tone dulu, skor di dalamnya (§5).
- AMP-01 amplop tagihan diserap TAG-01/02 (penekanan 3) → yang tampil TAG.
- Kosong → baris dasar: "Aman, ±{rp}/hari" (angka sama dengan batas chip), "terpakai semua",
  atau saldo tabungan ("Setor" disembunyikan saat defisit, penekanan 7).
- Dismiss viewer: jatuh ke calon berikutnya; semua di-dismiss → tanpa strip.
- Route: flag `advisor_v2_users`, end-to-end SQLite.

Run: python -m unittest app.tests.test_advisor_page_amplop -v
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

from sqlalchemy.orm import configure_mappers

from app.services.advisor.dashboard import analisa, susun_dashboard
from app.services.advisor.halaman import susun_amplop, susun_halaman_amplop
from app.tests.advisor_v2_fixtures import SnapshotBuilder, contoh_15_okt

configure_mappers()  # jangan jatuh di event loop tes (asyncio debug: "took 0.5 seconds")
JKT = ZoneInfo("Asia/Jakarta")
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def jam(t: date, h=8) -> datetime:
    return datetime(t.year, t.month, t.day, h, tzinfo=JKT)


def halaman(b: SnapshotBuilder, dismiss=None) -> dict:
    snap = b.build()
    return susun_halaman_amplop(snap, now_local=jam(snap.today), dismiss=dismiss)["amplop"]


def aman_sederhana(today=date(2026, 10, 10)) -> SnapshotBuilder:
    """Periode 1–31 Okt, Makan 3 jt, belanja kecil tiap hari → tidak ada aturan amplop."""
    b = SnapshotBuilder(today)
    b.envelope("makan", "Makan", classification="needs")
    b.income(3_000_000, alloc={"makan": 3_000_000})
    for i in range((today - b.ps).days + 1):
        b.txn("makan", 50_000, on=b.ps + timedelta(days=i))
    return b


class PilihPerKartuTests(unittest.TestCase):
    def test_contoh_12(self):
        p = halaman(contoh_15_okt())
        self.assertEqual(set(p), {"belanja", "tagihan", "darurat"})
        self.assertEqual(p["belanja"]["aturan"], "AMP-03")
        self.assertEqual(p["belanja"]["judul"], "Makan & Jajan: maksimal Rp153 rb/hari")
        self.assertEqual(p["tagihan"]["aturan"], "TAG-01")
        self.assertEqual(p["tagihan"]["tone"], "danger")
        self.assertEqual(p["darurat"]["aturan"], "TAB-01")
        # Bentuk sama dengan item Beranda: id, aksi berlabel, dismiss.
        self.assertEqual(p["tagihan"]["dismiss"]["kunci"], p["tagihan"]["id"])
        self.assertTrue(all(a["label"] for a in p["belanja"]["aksi"]))

    def test_amp03_tetap_tampil_walau_diserap_per01_di_beranda(self):
        b = contoh_15_okt()
        snap = b.build()
        dash, _ = susun_dashboard(snap, now_local=jam(snap.today))
        self.assertNotIn("AMP-03:belanja", [i["id"] for i in dash["advisor"]["items"]])
        self.assertEqual(halaman(contoh_15_okt())["belanja"]["id"], "AMP-03:belanja")

    def test_tag_menyerap_amp01_amplop_yang_sama(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan", "Makan", classification="needs")
        b.envelope("tagihan", "Tagihan", purpose="debt")
        b.income(3_000_000, alloc={"makan": 2_900_000, "tagihan": 100_000})
        b.txn("tagihan", 300_000, desc="servis", on=date(2026, 10, 3))
        b.recurring("tagihan", 500_000, "Listrik", date(2026, 10, 5), id="listrik")
        p = halaman(b)
        self.assertIn(p["tagihan"]["aturan"], ("TAG-01", "TAG-02"))
        self.assertIn("AMP-01:tagihan", [r["id"] for r in p["tagihan"].get("rincian", [])])

    def test_tone_dulu_baru_skor(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan", "Makan", classification="needs")
        b.income(1_000_000, alloc={"makan": 1_000_000})
        b.txn("makan", 1_200_000, on=date(2026, 10, 2))
        self.assertEqual(halaman(b)["makan"]["aturan"], "AMP-01")   # danger

    def test_tab_hanya_untuk_tabungan_dan_amp_tag_tidak_dari_amplop_lain(self):
        p = halaman(contoh_15_okt())
        for eid, item in p.items():
            if item and item["aturan"]:
                self.assertFalse(item["aturan"].startswith(("PER", "HAR", "INC", "DAT")), item["aturan"])
        self.assertTrue(p["darurat"]["aturan"].startswith(("TAB", "AMP")))


class BarisDasarTests(unittest.TestCase):
    def test_aman_per_hari_sama_dengan_batas_chip(self):
        b = aman_sederhana()
        snap = b.build()
        ctx, sel = analisa(snap, now_local=jam(snap.today))
        item = susun_amplop(ctx, sel)["makan"]
        self.assertIsNone(item["aturan"])
        self.assertEqual(item["tone"], "ok")
        self.assertIsNone(item["dismiss"])
        bebas = ctx.m.amplop["makan"].bebas
        self.assertEqual(bebas, D("2500000"))
        self.assertEqual(ctx.batas["makan"], D("119000"))   # floor100(2.500.000 ÷ H 21)
        self.assertEqual(item["judul"], "Aman, ±Rp119 rb/hari tersedia")

    def test_hari_terakhir(self):
        item = halaman(aman_sederhana(date(2026, 10, 31)))["makan"]
        self.assertEqual(item["judul"], "Aman, Rp1,45 jt tersedia hari ini")

    def test_terpakai_semua_tanpa_laju(self):
        b = SnapshotBuilder(date(2026, 10, 2))
        b.envelope("makan", "Makan", classification="needs")
        b.income(100_000, alloc={"makan": 100_000})
        b.txn("makan", 100_000, on=date(2026, 10, 1))
        item = halaman(b)["makan"]
        self.assertEqual(item["tone"], "info")
        self.assertEqual(item["chip"], "Terpakai semua")
        self.assertEqual(item["aksi"], [{"kind": "fund", "label": "Isi dana", "payload": {"amplop_id": "makan"}}])

    def test_tabungan_tanpa_target(self):
        b = aman_sederhana()
        b.envelope("liburan", "Liburan", purpose="saving")
        b.lifetime("liburan", 750_000)
        item = halaman(b)["liburan"]
        self.assertEqual(item["chip"], "Saldo Rp750 rb")
        self.assertEqual(item["isi"], "Tambahkan target biar terarah.")
        self.assertEqual([a["label"] for a in item["aksi"]], ["Setor"])

    def test_tabungan_tanpa_setor_saat_defisit(self):
        b = aman_sederhana()
        b.envelope("liburan", "Liburan", purpose="saving")
        b.lifetime("liburan", 750_000)
        b.txn("makan", 3_000_000, desc="laptop")   # sisa bebas < 0
        self.assertEqual(halaman(b)["liburan"]["aksi"], [])


class DismissTests(unittest.TestCase):
    def test_jatuh_ke_calon_berikutnya_lalu_tanpa_strip(self):
        p = halaman(contoh_15_okt())
        kunci = p["tagihan"]["id"]
        p2 = halaman(contoh_15_okt(), dismiss={kunci: {"pilihan": "nanti", "tone": "danger", "rupiah": "0"}})
        self.assertIsNone(p2["tagihan"])   # TAG-01 satu-satunya calon: masalah masih ada, tanpa "Aman"
        kunci_b = p["belanja"]["id"]
        p3 = halaman(contoh_15_okt(), dismiss={kunci_b: {"pilihan": "nanti", "tone": "warn", "rupiah": "999999999"}})
        self.assertNotEqual((p3["belanja"] or {}).get("id"), kunci_b)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RouteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, User,
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
            rina = User(name="Rina", payday_day=1)
            hh = Household(name="Rumah")
            db.add_all([me, rina, hh])
            await db.flush()
            self.hid = hh.id
            db.add_all([HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner),
                        HouseholdMember(user_id=rina.id, household_id=hh.id, role=HouseholdRole.member)])
            makan = Envelope(household_id=hh.id, name="Makan", classification="needs", budget_amount=D("0"))
            rahasia = Envelope(household_id=hh.id, name="Hadiah Kejutan", classification="wants",
                               budget_amount=D("0"), owner_id=rina.id)
            db.add_all([makan, rahasia])
            await db.flush()
            gaji = Income(household_id=hh.id, user_id=me.id, amount=D("3000000"), description="Gaji",
                          income_date=today)
            db.add(gaji)
            await db.flush()
            db.add(Allocation(income_id=gaji.id, envelope_id=makan.id, amount=D("3000000")))
            db.add(AppSetting(key="advisor_v2_users", value=str(me.id)))
            await db.commit()
        self.me, self.rina, self.makan, self.rahasia = me, rina, makan, rahasia

    async def page(self, user):
        from app.api.routes import advisor as advisor_routes
        async with self.Session() as db:
            return await advisor_routes.advisor_page_amplop(user=user, db=db, hid=self.hid)

    async def test_flag_dan_privasi(self):
        self.assertEqual(await self.page(self.rina), {"enabled": False})
        data = await self.page(self.me)
        self.assertTrue(data["enabled"])
        self.assertIn(str(self.makan.id), data["amplop"])
        self.assertNotIn(str(self.rahasia.id), data["amplop"])   # amplop pribadi anggota lain
        self.assertNotIn("Hadiah Kejutan", str(data))


if __name__ == "__main__":
    unittest.main()
