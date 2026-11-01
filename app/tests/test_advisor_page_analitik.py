"""AI Advisor v2 S15 — halaman Analitik: `GET /advisor/page/analitik` (02-aturan.md §7 "Halaman lain").

- Ringkasan ≤ 3 poin dari PER-03/04, AMP-08/11, hari terboros (S6), TAB-06: satu terbaik per
  kelompok, urut tone lalu kelompok; kurang dari 3 → AMP-08/11 amplop lain mengisi.
- Hari terboros = belanja variabel tertinggi periode ini vs jatah J0 hari itu; tidak bisa di-dismiss.
- Insight yang di-dismiss viewer tidak tampil.
- `harian` + `grafik` sama persis dengan Beranda (satu sumber angka).
- `/analytics/daily-spending` tidak menghitung amplop pribadi anggota lain.
- Sinking fund: CTA memakai kind pipa CTA (S8) + "Abaikan" lewat dismiss `SNK:<id>`.

Run: python -m unittest app.tests.test_advisor_page_analitik -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy.orm import configure_mappers

from app.services.advisor.dashboard import analisa, susun_dashboard
from app.services.advisor.insight import Insight
from app.services.advisor.page_analitik import hari_terboros, pilih_ringkasan, susun_halaman
from app.services.advisor.sinking import kunci_sinking, sinking_actions
from app.tests.advisor_v2_fixtures import SnapshotBuilder, contoh_15_okt
from app.tests.test_advisor_aturan_s4 import TODAY, normal, periode_lalu

configure_mappers()
JKT = ZoneInfo("Asia/Jakarta")
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def jam(t: date, h=12) -> datetime:
    return datetime(t.year, t.month, t.day, h, tzinfo=JKT)


def halaman(b: SnapshotBuilder, dismiss=None) -> dict:
    snap = b.build()
    return susun_halaman(snap, now_local=jam(snap.today), dismiss=dismiss)


def aturan(p: dict) -> list:
    return [r["aturan"] for r in p["ringkasan"]]


def lonjakan() -> SnapshotBuilder:
    """AMP-08 Makan (pola tes S4) + hari terboros kemarin."""
    b = normal(harian=10_000, hari_ini=0)
    for ps, _ in periode_lalu(b):
        b.fund("makan", 3_500_000, on=ps)
        b.txn("makan", 300_000, on=ps + timedelta(days=3), desc="belanja")
    b.txn("makan", 400_000, on=TODAY - timedelta(days=1), desc="belanja besar")
    b.txn("makan", 300_000, on=TODAY, desc="belanja lagi")
    return b


class RingkasanTests(unittest.TestCase):
    def test_lonjakan_dan_hari_terboros(self):
        p = halaman(lonjakan())
        self.assertIn("AMP-08", aturan(p))
        terboros = next(r for r in p["ringkasan"] if r["aturan"] is None)
        self.assertEqual(terboros["aksi"][0]["payload"]["path"],
                         f"/transactions?date={(TODAY - timedelta(days=1)).isoformat()}")
        self.assertIsNone(terboros["dismiss"])
        self.assertLessEqual(len(p["ringkasan"]), 3)

    def test_per03_lebih_cepat_tone_dulu(self):
        p = halaman(normal(dana=2_000_000, harian=100_000, hari_ini=50_000))
        self.assertEqual(p["ringkasan"][0]["aturan"], "PER-03")          # warn (PER-01 menyala)
        self.assertEqual(p["ringkasan"][0]["chip"], "73% dana, 48% waktu")

    def test_per04_laju_membaik(self):
        b = SnapshotBuilder(date(2026, 10, 20), payday_day=1)
        b.envelope("makan", "Makan")
        b.fund("makan", 5_000_000, on=b.ps)
        for i in range(13):
            b.txn("makan", 200_000, on=b.ps + timedelta(days=i))
        for i in range(13, 20):
            b.txn("makan", 50_000, on=b.ps + timedelta(days=i))
        p = halaman(b)
        self.assertIn("PER-04", aturan(p))

    def test_tab06_target_paralel(self):
        b = normal()
        for i in range(5):
            b.envelope(f"t{i}", f"Target {i}", purpose="saving")
            b.lifetime(f"t{i}", 100_000)
            b.goal(f"t{i}", f"Target {i}", 10_000_000)
        self.assertIn("TAB-06", aturan(halaman(b)))

    def test_dismiss_tidak_tampil(self):
        b = normal(dana=2_000_000, harian=100_000, hari_ini=50_000)
        kunci = halaman(b)["ringkasan"][0]["id"]
        self.assertTrue(kunci.startswith("PER-03:"))
        p = halaman(b, dismiss={kunci: {"pilihan": "nanti", "tone": "warn", "rupiah": "0"}})
        self.assertNotIn("PER-03", aturan(p))

    def test_tanpa_belanja_kosong(self):
        b = SnapshotBuilder(date(2026, 10, 2), payday_day=1)
        b.envelope("makan", "Makan")
        b.fund("makan", 3_000_000, on=b.ps)
        p = halaman(b)
        self.assertEqual(p["ringkasan"], [])
        self.assertEqual(len(p["harian"]), 2)

    def test_contoh_12(self):
        p = halaman(contoh_15_okt())
        r = p["ringkasan"][0]
        self.assertEqual(r["judul"], "Hari terboros: Kamis 8 Okt Rp549 rb")
        self.assertEqual(r["tone"], "warn")
        self.assertIn("16 dari 19 hari periode ini lewat jatah", r["isi"])


class PilihSintetisTests(unittest.TestCase):
    """Seleksi dengan insight buatan: satu per kelompok, urut tone, isi dari cadangan amplop."""

    def setUp(self):
        snap = normal().build()
        self.ctx, _ = analisa(snap, now_local=jam(snap.today))

    def amp(self, kode, tone, skor, eid):
        data = {"amplop_id": eid, "nama": eid, "v7": D(1), "median": D(1), "kali": D(2),
                "persen": D("0.3"), "arah": "naik", "terpakai": D(1), "lalu": D(1)}
        return Insight(aturan=kode, entitas=eid, tone=tone, slot=("analitik",), data=data, amplop_id=eid,
                       skor=D(skor))

    def tab06(self):
        return Insight(aturan="TAB-06", entitas="p", tone="info", slot=("analitik",),
                       data={"n": 5, "median": D("0.1")}, skor=D(1))

    def pilih(self, xs, hidden=()):
        with patch("app.services.advisor.page_analitik.hari_terboros", return_value=None):
            return pilih_ringkasan(self.ctx, SimpleNamespace(semua=xs, disembunyikan=list(hidden)))

    def test_isi_dari_cadangan_amplop(self):
        xs = [self.amp("AMP-11", "info", 10, "a"), self.amp("AMP-08", "warn", 5, "b"),
              self.amp("AMP-11", "info", 30, "c")]
        out = self.pilih(xs)
        self.assertEqual([r["id"] for r in out], ["AMP-08:b", "AMP-11:c", "AMP-11:a"])

    def test_maks_tiga_dan_tone_dulu(self):
        xs = [self.tab06(), self.amp("AMP-08", "warn", 5, "b"), self.amp("AMP-11", "info", 30, "c"),
              self.amp("AMP-11", "info", 20, "d")]
        out = self.pilih(xs)
        self.assertEqual([r["id"] for r in out], ["AMP-08:b", "TAB-06:p", "AMP-11:c"])

    def test_aturan_lain_dan_tersembunyi_diabaikan(self):
        lain = Insight(aturan="AMP-07", entitas="x", tone="info", slot=("analitik",), amplop_id="x")
        out = self.pilih([lain, self.tab06()], hidden=["TAB-06:p"])
        self.assertEqual(out, [])


class GrafikTests(unittest.TestCase):
    def test_harian_dan_grafik_sama_dengan_beranda(self):
        snap = contoh_15_okt().build()
        p = susun_halaman(snap, now_local=jam(snap.today))
        dash, _ = susun_dashboard(snap, now_local=jam(snap.today))
        self.assertEqual(p["harian"], dash["metrics"]["harian"])
        self.assertEqual(p["grafik"], dash["grafik"])
        self.assertEqual((p["period_start"], p["period_end"]), ("2026-09-27", "2026-10-26"))

    def test_hari_terboros_seri_ambil_terakhir(self):
        b = SnapshotBuilder(date(2026, 10, 5), payday_day=1)
        b.envelope("makan", "Makan")
        b.fund("makan", 3_000_000, on=b.ps)
        b.txn("makan", 80_000, on=date(2026, 10, 2))
        b.txn("makan", 80_000, on=date(2026, 10, 4))
        snap = b.build()
        ctx, _ = analisa(snap, now_local=jam(snap.today))
        h = hari_terboros(ctx.m, ctx.s)
        self.assertEqual(h["tanggal"], date(2026, 10, 4))
        self.assertEqual(h["n_lewat"], 0)
        terboros = halaman(b)["ringkasan"][0]
        self.assertEqual(terboros["tone"], "ok")                          # tidak ada hari lewat jatah
        self.assertEqual(terboros["judul"], "Semua hari dalam jatah periode ini")
        self.assertEqual(terboros["isi"], "Belanja tertinggi Minggu 4 Okt Rp80.000, jatah hari itu "
                                          f"{terboros['fakta'][1]['nilai']}.")


class SinkingActionTests(unittest.TestCase):
    def kw(self, **x):
        return {"envelope_id": "e1", "amount": 54000, "description": "Netflix", "next_run": "2026-11-03", **x}

    def test_bulanan_jadi_langganan(self):
        a = sinking_actions("r1", "create_recurring", "monthly", **self.kw())
        self.assertEqual(a[0], {"kind": "make_recurring", "label": "Jadikan langganan", "payload": {
            "deskripsi": "Netflix", "jumlah": 54000, "frekuensi": "monthly", "amplop_id": "e1",
            "next_run": "2026-11-03"}})
        self.assertEqual(a[1], {"kind": "dismiss", "label": "Abaikan",
                                "payload": {"kunci": "SNK:r1", "pilihan": "tidak_relevan"}})

    def test_triwulanan_review_dan_sesuaikan(self):
        lihat = {"kind": "route", "label": "Lihat transaksi", "payload": {"path": "/transactions?envelope=e1"}}
        self.assertEqual(sinking_actions("r", "create_recurring", "quarterly", **self.kw())[0], lihat)
        self.assertEqual(sinking_actions("r", "review", "unknown", **self.kw())[0], lihat)
        self.assertEqual(sinking_actions("r", "adjust_recurring", "monthly", **self.kw())[0]["payload"],
                         {"path": "/langganan"})
        tahunan = sinking_actions("r", "annualize", "yearly", **self.kw(next_run=None))[0]
        self.assertEqual(tahunan["kind"], "make_recurring")
        self.assertNotIn("next_run", tahunan["payload"])

    def test_kunci(self):
        self.assertEqual(kunci_sinking("abc"), "SNK:abc")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RouteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import (
            Allocation, AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, Income, Transaction,
            User,
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
        self.today = today
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
            db.add_all([
                Transaction(envelope_id=makan.id, user_id=me.id, amount=D("50000"), description="makan",
                            transaction_date=today),
                Transaction(envelope_id=rahasia.id, user_id=rina.id, amount=D("700000"), description="kado",
                            transaction_date=today),
            ])
            db.add(AppSetting(key="advisor_v2_users", value=str(me.id)))
            await db.commit()
        self.me, self.rina = me, rina

    async def test_flag_dan_privasi(self):
        from app.api.routes import advisor as advisor_routes
        async with self.Session() as db:
            self.assertEqual(await advisor_routes.advisor_page_analitik(user=self.rina, db=db, hid=self.hid), {"enabled": False})
            data = await advisor_routes.advisor_page_analitik(user=self.me, db=db, hid=self.hid)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["harian"][-1]["variabel"], 50000)            # kado Rina tidak ikut
        self.assertNotIn("Hadiah Kejutan", str(data))

    async def test_daily_spending_tanpa_amplop_pribadi_anggota_lain(self):
        from app.api.routes import analytics
        async with self.Session() as db:
            saya = await analytics.daily_spending(period_start=self.today, period_end=self.today, user=self.me, db=db, hid=self.hid)
            rina = await analytics.daily_spending(period_start=self.today, period_end=self.today, user=self.rina, db=db, hid=self.hid)
        self.assertEqual(saya, [{"date": str(self.today), "total": 50000.0, "count": 1}])
        self.assertEqual(rina, [{"date": str(self.today), "total": 750000.0, "count": 2}])


if __name__ == "__main__":
    unittest.main()
