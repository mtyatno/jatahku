"""AI Advisor Fase 5 — kolam harian & pagar ritme (02-aturan.md §2, §3 "Kolam harian dan pagar
ritme", §6 HAR-06 / PER-08 / DAT-07, §13 tes #21–26).

Run: python -m unittest app.tests.test_advisor_fase5 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.services.advisor import render
from app.services.advisor.metrics import compute_metrics, floor100
from app.services.advisor.snapshot import EnvelopeSnap
from app.tests.advisor_v2_fixtures import SnapshotBuilder
from app.tests.test_advisor_insight_v2 import run

# Kasus 23 Okt 2026 (02-aturan §3): periode 27 Sep – 26 Okt, H-3, pemasukan Rp7,6 jt dialokasikan.
TODAY = date(2026, 10, 23)


def kasus_23_okt(jenis_rumah: str | None = "bulanan") -> SnapshotBuilder:
    b = SnapshotBuilder(TODAY, payday_day=27)
    b.envelope("makan", "Makan & Jajan", jenis_grup="harian")
    b.envelope("transport", "Transport", jenis_grup="harian")
    b.envelope("rumah", "Kebutuhan Rumah", jenis_grup=jenis_rumah)
    b.envelope("pendidikan", "Pendidikan", jenis_grup="bulanan")
    b.envelope("hutang", "Tagihan Hutang", purpose="debt")           # otomatis bulanan
    b.envelope("tabungan", "Tabungan", purpose="saving")
    # Awal periode: dana harian 4,32 jt + 0,34 jt; belanja ritme ±Rp160 rb/hari selama 26 hari.
    b.fund("makan", 4_320_000, on=b.ps)
    b.fund("transport", 340_000, on=b.ps)
    b.fund("rumah", 300_000, on=b.ps)
    for i in range(26):
        b.txn("makan", 148_000, on=b.ps + timedelta(days=i), desc=f"makan {i}")
        if i % 2 == 0:
            b.txn("transport", 25_000, on=b.ps + timedelta(days=i), desc=f"bensin {i}")
    b.txn("makan", 116_000, on=TODAY, desc="makan siang")
    # H-3: pemasukan di luar gaji Rp7,6 jt, 100% dialokasikan ke 5 amplop.
    b.income(7_600_000, on=TODAY, alloc={"makan": 1_756_700, "transport": 215_200, "rumah": 235_800,
                                         "pendidikan": 3_194_600, "hutang": 2_197_700})
    return b


class KolamHarianTests(unittest.TestCase):
    def test_21_saldo_bulanan_tidak_masuk_jatah(self):
        m = compute_metrics(kasus_23_okt().build())
        self.assertEqual(m.amplop["pendidikan"].jenis, "bulanan")
        self.assertEqual(m.amplop["hutang"].jenis, "bulanan")       # purpose debt → otomatis bulanan
        self.assertEqual(m.amplop["rumah"].jenis, "bulanan")
        self.assertEqual(m.amplop["makan"].jenis, "harian")
        self.assertEqual(m.amplop["tabungan"].jenis, "-")
        self.assertEqual(m.sisa_bebas, m.sisa_bebas_harian + m.cadangan_bulanan)
        self.assertEqual(m.cadangan_bulanan, D("3194600") + D("2197700") + D("300000") + D("235800"))
        # J0/J1/T9/T10 hanya dari amplop harian.
        tanpa = compute_metrics(kasus_23_okt().build())
        b = kasus_23_okt()
        b.fund("pendidikan", 10_000_000, on=TODAY)                    # tambah dana bulanan
        dengan = compute_metrics(b.build())
        for f in ("j0", "j1", "kekurangan", "tanggal_habis", "sisa_bebas_harian", "surplus_harian"):
            self.assertEqual(getattr(dengan, f), getattr(tanpa, f), f)
        self.assertEqual(dengan.cadangan_bulanan, tanpa.cadangan_bulanan + D("10000000"))

    def test_21b_grup_tanpa_jenis_otomatis(self):
        self.assertEqual(EnvelopeSnap(id="a", name="a", purpose="expense").jenis, "harian")
        self.assertEqual(EnvelopeSnap(id="a", name="a", purpose="debt").jenis, "bulanan")
        self.assertEqual(EnvelopeSnap(id="a", name="a", purpose="debt", jenis_grup="harian").jenis, "harian")
        self.assertEqual(EnvelopeSnap(id="a", name="a", purpose="expense", jenis_grup="bulanan").jenis, "bulanan")
        self.assertEqual(EnvelopeSnap(id="a", name="a", purpose="expense", jenis_grup="aneh").jenis, "harian")

    def test_22_pagar_ideal_top_up_h3(self):
        m = compute_metrics(kasus_23_okt().build())
        dana_harian = m.amplop["makan"].dana + m.amplop["transport"].dana
        self.assertEqual(m.jatah_ideal, floor100(dana_harian / 30))
        self.assertEqual(m.j0, m.jatah_ideal)                        # pagar menahan, bukan sisa ÷ 4
        self.assertEqual(m.j1, m.jatah_ideal)
        self.assertLess(m.j0, D("300000"))                           # bukan lagi Rp2,1 jt/hari
        self.assertGreater(m.sisa_bebas_harian / 4, m.j0 * 2)        # sisa ÷ hari jauh di atas pagar
        # Top-up tambahan ke amplop harian hanya menaikkan J0 sebesar top-up ÷ D.
        b = kasus_23_okt()
        b.fund("makan", 3_000_000, on=TODAY)
        m2 = compute_metrics(b.build())
        self.assertEqual(m2.j0, floor100((dana_harian + D("3000000")) / 30))
        self.assertGreater(m2.surplus_harian, m.surplus_harian)

    def test_22b_pendapatan_harian_mingguan_tanpa_pagar(self):
        for tipe in ("daily", "weekly"):
            b = SnapshotBuilder(TODAY, payday_day=27, income_type=tipe)
            b.envelope("makan", "Makan")
            b.fund("makan", 500_000, on=TODAY)
            m = compute_metrics(b.build())
            self.assertIsNone(m.jatah_ideal, tipe)
            self.assertEqual(m.surplus_harian, D("0"), tipe)
            self.assertGreater(m.j0, D("0"), tipe)

    def test_23_asimetri_uang_menipis(self):
        b = SnapshotBuilder(TODAY, payday_day=27)
        b.envelope("makan", "Makan", jenis_grup="harian")
        b.fund("makan", 4_500_000, on=b.ps)
        for i in range(26):
            b.txn("makan", 160_000, on=b.ps + timedelta(days=i), desc=f"makan {i}")
        m = compute_metrics(b.build())                               # sisa 340 rb untuk 4 hari
        self.assertLess(m.sisa_bebas_harian / m.horizon_awal, m.jatah_ideal)
        self.assertEqual(m.j0, floor100(m.sisa_bebas_harian / m.horizon_awal))   # sisa ÷ hari menang
        self.assertEqual(m.surplus_harian, D("0"))

    def test_24_kasus_23_okt_insight(self):
        ctx, sel = run(kasus_23_okt())
        m = ctx.m
        self.assertNotIn("PER-01", [i.aturan for i in sel.semua])
        per08 = next(i for i in sel.semua if i.aturan == "PER-08")
        self.assertEqual(sel.kpi["sisa_bebas"].aturan, "PER-08")
        self.assertEqual(per08.tone, "info")                         # ≥ Rp500 rb → kandidat daftar
        self.assertIn(per08.id, [i.id for i in sel.daftar])
        self.assertGreater(m.surplus_harian, D("1000000"))
        r = render.render_insight(per08, ctx)
        self.assertTrue(r["chip"].startswith("Surplus +"))
        self.assertIn("ke periode 27 Okt", r["judul"])
        self.assertIn("Dicadangkan", r["isi"])
        self.assertEqual(r["aksi"][0]["kind"], "plan")
        self.assertTrue(r["aksi"][0]["label"].startswith("Setor "))
        self.assertEqual(r["aksi"][0]["payload"]["kebutuhan"][0]["tujuan_id"], "tabungan")
        # Kartu Jatah: belanja Rp116.000 dari jatah berpagar → HAR-04 "Sisa … hari ini" yang masuk akal.
        jatah = sel.kpi["jatah"]
        self.assertEqual(jatah.aturan, "HAR-04")
        self.assertEqual(jatah.data["sisa"], m.j0 - D("116000"))

    def test_24b_dicadangkan_tidak_menutup_kekurangan_harian(self):
        b = kasus_23_okt()
        for i in range(20, 26):
            b.txn("makan", 700_000, on=b.ps + timedelta(days=i), desc=f"boros {i}")   # laju naik
        ctx, sel = run(b)
        m = ctx.m
        self.assertGreater(m.cadangan_bulanan, D("5000000"))
        if m.kekurangan and m.kekurangan > 0:
            per01 = next(i for i in sel.semua if i.aturan == "PER-01")
            self.assertEqual(per01.data["t3"], m.sisa_bebas_harian)
            self.assertEqual(per01.data["t3b"], m.cadangan_bulanan)

    def test_25_har06_di_atas_ritme(self):
        b = kasus_23_okt()
        b.txn("makan", 100_000, on=TODAY, desc="ngopi")              # hari ini 216 rb vs ritme ±163 rb
        ctx, sel = run(b)
        m = ctx.m
        self.assertIsNotNone(m.ritme)
        self.assertLessEqual(m.belanja_hari_ini, m.j0)
        har06 = next(i for i in sel.semua if i.aturan == "HAR-06")
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-02")         # ≥ 80% jatah: HAR-02 tetap didahulukan
        r = render.render_insight(har06, ctx)
        self.assertIn("ritme biasa", r["chip"])
        self.assertIn("surplus", r["isi"])
        # Ritme jauh di bawah jatah: HAR-06 jadi chip (didahulukan dari HAR-04).
        b = SnapshotBuilder(TODAY, payday_day=27)
        b.envelope("makan", "Makan"); b.fund("makan", 6_000_000, on=b.ps)
        for i in range(26):
            b.txn("makan", 100_000, on=b.ps + timedelta(days=i), desc=f"makan {i}")
        b.txn("makan", 150_000, on=TODAY, desc="ngopi")              # J0 = 200 rb; 150 < 160 (80%) dan ≥ 1,3× ritme
        ctx, sel = run(b)
        self.assertEqual(ctx.m.j0, D("200000"))
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-06")
        self.assertEqual(render.teks(sel.kpi["jatah"], ctx)["chip"], "1,5× ritme biasa")
        # Belum 7 hari → ritme None → HAR-06 tidak menyala.
        b = SnapshotBuilder(date(2026, 10, 2), payday_day=1)
        b.envelope("makan", "Makan"); b.fund("makan", 3_000_000, on=b.ps)
        b.txn("makan", 90_000, on=date(2026, 10, 1)); b.txn("makan", 400_000, on=date(2026, 10, 2))
        ctx, sel = run(b)
        self.assertIsNone(ctx.m.ritme)
        self.assertNotIn("HAR-06", [i.aturan for i in sel.semua])
        # Lewat jatah → HAR-01 yang tampil, bukan HAR-06.
        b = kasus_23_okt()
        b.txn("makan", 200_000, on=TODAY, desc="makan malam")
        ctx, sel = run(b)
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-01")
        self.assertNotIn("HAR-06", [i.aturan for i in sel.semua])

    def test_26_dat07_amplop_sepertinya_bulanan(self):
        b = kasus_23_okt(jenis_rumah=None)                           # Kebutuhan Rumah masih harian
        ps0 = b.snap.periods[-2][0]
        b.fund("rumah", 300_000, on=ps0)
        b.txn("rumah", 290_000, on=ps0 + timedelta(days=3), desc="listrik")
        b.txn("rumah", 285_000, on=b.ps + timedelta(days=3), desc="listrik")
        ctx, sel = run(b)
        dat = next(i for i in sel.semua if i.aturan == "DAT-07")
        self.assertEqual(dat.entitas, "rumah")
        r = render.render_insight(dat, ctx)
        self.assertEqual(r["judul"], "Kebutuhan Rumah sepertinya pengeluaran bulanan")
        self.assertEqual(r["aksi"][0]["payload"]["path"], "/envelopes")
        # Grup sudah bulanan → tidak menyala; amplop harian dengan banyak transaksi → tidak menyala.
        ctx, sel = run(kasus_23_okt())
        self.assertNotIn("DAT-07", [i.aturan for i in sel.semua])

    def test_outlier_memotong_jatah_hari_itu(self):           # skenario 3 & 13 (revisi 23 Okt)
        base = compute_metrics(kasus_23_okt().build())
        b = kasus_23_okt()
        b.txn("makan", 2_500_000, on=TODAY, desc="kulkas")
        m = compute_metrics(b.build())
        self.assertEqual(m.jenis_transaksi[[x.id for x in b.snap.transactions if x.description == "kulkas"][0]], "outlier")
        self.assertLess(m.j0, base.j0)
        self.assertEqual(m.harian[-1]["jatah"], m.j0)
        ctx, sel = run(b)
        har03 = next(i for i in sel.semua if i.aturan == "HAR-03")
        self.assertIn(f"hari ini jadi {render.rp_penuh(m.j0)}", render.render_insight(har03, ctx)["isi"])

    def test_to_api_field_baru(self):
        m = compute_metrics(kasus_23_okt().build()).to_api()
        for key in ("sisa_bebas_harian", "cadangan_bulanan", "jatah_ideal", "ritme", "surplus_harian"):
            self.assertIn(key, m)
        self.assertEqual(m["sisa_bebas"], m["sisa_bebas_harian"] + m["cadangan_bulanan"])


if __name__ == "__main__":
    unittest.main()


# ── /envelopes/groups: jenis (SQLite in-memory, Redis dipalsukan) ─────────────────────────────
import importlib.util
from unittest.mock import patch

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class GroupJenisRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.database import Base
        from app.models.models import Envelope, Household, HouseholdMember, HouseholdRole, User
        from app.tests.test_advisor_dashboard_integration import FakeRedis
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.redis = FakeRedis()
        p = patch("redis.asyncio.from_url", return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)
        async with self.Session() as db:
            me = User(name="Saya", payday_day=27, timezone="Asia/Jakarta")
            hh = Household(name="Rumah")
            db.add_all([me, hh])
            await db.flush()
            db.add(HouseholdMember(user_id=me.id, household_id=hh.id, role=HouseholdRole.owner))
            db.add(Envelope(household_id=hh.id, name="Pendidikan", classification="needs", budget_amount=D("0")))
            await db.commit()
            self.me, self.hid = me, hh.id

    async def test_buat_ubah_jenis_dan_snapshot_membacanya(self):
        from app.api.routes import envelopes as routes
        from app.models.models import Envelope
        from app.services.advisor import advisor_cache
        from app.services.advisor.snapshot import load_snapshot
        from sqlalchemy import select, update
        async with self.Session() as db:
            g = await routes.create_group(routes.EnvelopeGroupCreate(name="Pengeluaran bulanan"), user=self.me, db=db)
            self.assertIsNone(g.jenis)
            await db.execute(update(Envelope).where(Envelope.household_id == self.hid).values(group_id=g.id))
            await db.commit()
        async with self.Session() as db:
            snap = await load_snapshot(self.me, db, today=TODAY)
            self.assertEqual(snap.envelopes[0].jenis, "harian")             # grup tanpa jenis → otomatis
        self.redis.store[advisor_cache.kunci_dashboard(self.hid, self.me.id)] = "{}"
        async with self.Session() as db:
            g2 = await routes.update_group(g.id, routes.EnvelopeGroupUpdate(jenis="bulanan"), user=self.me, db=db)
            self.assertEqual((g2.name, g2.jenis), ("Pengeluaran bulanan", "bulanan"))
        self.assertNotIn(advisor_cache.kunci_dashboard(self.hid, self.me.id), self.redis.store)  # cache dihapus
        async with self.Session() as db:
            snap = await load_snapshot(self.me, db, today=TODAY)
            self.assertEqual(snap.envelopes[0].jenis, "bulanan")
            rows = await routes.list_groups(user=self.me, db=db)
            self.assertEqual([(r.name, r.jenis) for r in rows], [("Pengeluaran bulanan", "bulanan")])
        async with self.Session() as db:   # ganti nama saja: jenis tidak berubah; jenis=null → otomatis lagi
            g3 = await routes.update_group(g.id, routes.EnvelopeGroupUpdate(name="Bulanan"), user=self.me, db=db)
            self.assertEqual((g3.name, g3.jenis), ("Bulanan", "bulanan"))
            g4 = await routes.update_group(g.id, routes.EnvelopeGroupUpdate(jenis=None), user=self.me, db=db)
            self.assertIsNone(g4.jenis)

    async def test_jenis_tidak_dikenal_ditolak(self):
        from pydantic import ValidationError
        from app.api.routes import envelopes as routes
        with self.assertRaises(ValidationError):
            routes.EnvelopeGroupUpdate(jenis="mingguan")
        with self.assertRaises(ValidationError):
            routes.EnvelopeGroupUpdate(nama="x")   # extra = forbid
