"""AI Advisor v2 S3 — aturan HAR-*/PER-*, seleksi, render (02-aturan.md §5–§7, §9, §10, §12, §13).

Fungsi murni dengan fixture `SnapshotBuilder` (tanpa DB). Skenario emas §13: 1, 2, 3, 6, 11,
13, 16, 17; ditambah contoh §12 (chip & skor), dismiss, batas daftar, rencana bersama.
Run: python -m unittest app.tests.test_advisor_insight_v2 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import dataclasses
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from app.services.advisor import render
from app.services.advisor.dashboard import analisa, bangun_konstanta, flag_aktif, susun_dashboard
from app.services.advisor.advisor_cache import ttl_dismiss
from app.services.advisor.insight import DEFAULT as KA, Insight, hitung_skor
from app.services.advisor.metrics import floor100
from app.services.advisor.select import kebutuhan_bersama, pilih, pilih_daftar, tersembunyi
from app.tests.advisor_v2_fixtures import SnapshotBuilder, contoh_15_okt

JKT = ZoneInfo("Asia/Jakarta")
KA_CTA = dataclasses.replace(KA, cta_batas_harian=True)


def jam(t: date, h=12) -> datetime:
    return datetime(t.year, t.month, t.day, h, tzinfo=JKT)


def run(b: SnapshotBuilder, h=12, dismiss=None, ka=KA):
    snap = b.build()
    ctx, sel = analisa(snap, now_local=jam(snap.today, h), dismiss=dismiss, ka=ka)
    return ctx, sel


def ids(insights):
    return [i.aturan for i in insights]


def normal(today=date(2026, 10, 15), dana=3_500_000, hari_ini=50_000, harian=100_000) -> SnapshotBuilder:
    """Periode 1–31 Okt; belanja harian tetap, hari ini lebih kecil (skenario 1)."""
    b = SnapshotBuilder(today, payday_day=1)
    b.envelope("makan", "Makan", classification="needs")
    b.fund("makan", dana, on=b.ps)
    d = b.ps
    while d < today:
        b.txn("makan", harian, on=d, desc=f"makan {d.day}")
        d += timedelta(days=1)
    if hari_ini:
        b.txn("makan", hari_ini, on=today, desc="makan siang")
    return b


def split_window(b: SnapshotBuilder, mulai: date) -> SnapshotBuilder:
    """Pecah tiap transaksi di jendela laju jadi dua (angka sama, keyakinan proyeksi tinggi)."""
    out = []
    for x in b.snap.transactions:
        if x.transaction_date >= mulai and x.bill_desc is None:
            half = (x.amount / 2).quantize(D("1"))
            out.append(dataclasses.replace(x, amount=half))
            out.append(dataclasses.replace(x, id=x.id + "b", amount=x.amount - half,
                                           created_at=x.created_at + timedelta(minutes=30)))
        else:
            out.append(x)
    b.snap.transactions = out
    return b


class Contoh15OktTests(unittest.TestCase):
    """02-aturan.md §12."""

    def setUp(self):
        b = split_window(contoh_15_okt(), date(2026, 10, 9))
        self.ctx, self.sel = run(b, h=6, ka=KA_CTA)
        self.by = {i.aturan: i for i in self.sel.semua}

    def test_chip_kpi(self):
        kpi = self.sel.kpi
        self.assertEqual((kpi["jatah"].aturan, kpi["jatah"].tone), ("HAR-01", "danger"))
        self.assertEqual(render.teks(kpi["jatah"], self.ctx, "jatah")["chip"], "1,8× jatah")
        self.assertEqual((kpi["sisa_bebas"].aturan, kpi["sisa_bebas"].tone), ("PER-01", "warn"))
        self.assertEqual(render.teks(kpi["sisa_bebas"], self.ctx, "sisa_bebas")["chip"], "Habis ±24 Okt")
        self.assertEqual(render.teks(kpi["terpakai"], self.ctx, "terpakai")["chip"], "Lewat ±Rp525 rb")
        self.assertTrue(self.sel.redam)

    def test_skor_contoh(self):
        # HAR-01 berdiri sendiri 69,1; PER-01 54,3 (U 0,4; I 0,466; A 1; keyakinan tinggi).
        self.assertEqual(self.by["PER-01"].keyakinan, "tinggi")
        self.assertAlmostEqual(float(self.by["HAR-01"].skor), 69.1, places=1)
        self.assertAlmostEqual(float(self.by["PER-01"].skor), 54.3, places=1)

    def test_har01_menyatu_ke_per01(self):  # skenario 17a, penekanan 6
        self.assertNotIn("HAR-01", ids(self.sel.daftar))
        self.assertIn("PER-01", ids(self.sel.daftar))
        per = render.render_insight(self.by["PER-01"], self.ctx)
        self.assertTrue(per["isi"].startswith("Hari ini 1,8× jatah; 4 dari 7 hari terakhir lewat jatah."))
        self.assertIn("±Rp525 rb", per["isi"])
        self.assertEqual(per["judul"], "Rem belanja harian ke Rp153 rb")
        # S4: AMP-03 Makan & Jajan ikut masuk Rincian PER-01 (penekanan 2, contoh §12)
        self.assertEqual([r["aturan"] for r in per["rincian"]], ["HAR-01", "AMP-03"])

    def test_cta_batas_harian_dari_rencana(self):
        batas = next(a for a in self.by["PER-01"].aksi if a["kind"] == "daily_limit")
        self.assertEqual(batas["payload"], {"amplop_id": "belanja", "jumlah": 153_200})

    def test_cta_batas_harian_mati_secara_default(self):
        ctx, sel = run(contoh_15_okt(), h=6)
        per = next(i for i in sel.semua if i.aturan == "PER-01")
        self.assertNotIn("daily_limit", [a["kind"] for a in per.aksi])
        self.assertEqual(per.data["batas"], D("153200"))  # angka tetap tampil sebagai fakta


class SkenarioTests(unittest.TestCase):
    def test_1_periode_normal_tanpa_danger_warn(self):
        ctx, sel = run(normal())
        self.assertEqual([i.id for i in sel.semua if i.tone in ("danger", "warn")], [])
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-04")
        self.assertEqual(sel.kpi["sisa_bebas"].aturan, "PER-05")
        self.assertEqual(render.teks(sel.kpi["terpakai"], ctx, "terpakai")["chip"], "Sesuai jalur")
        self.assertEqual(sel.daftar, [])
        self.assertIsNotNone(sel.aman)   # "Semua aman" + satu kabar baik
        self.assertFalse(sel.redam)

    def test_2_hari_1_2_tanpa_proyeksi(self):
        for today in (date(2026, 10, 1), date(2026, 10, 2)):
            ctx, sel = run(normal(today=today, hari_ini=500_000))
            self.assertIsNone(ctx.m.proyeksi_akhir)
            self.assertFalse({"PER-01", "PER-03", "PER-04", "PER-05", "PER-06"} & set(ids(sel.semua)))
            self.assertEqual(sel.kpi["sisa_bebas"].aturan, "PER-07")
            self.assertEqual(sel.kpi["terpakai"].aturan, "PER-07")

    def test_3_belanja_besar_satu_kali(self):
        b = normal(dana=6_000_000)
        b.txn("makan", 2_000_000, on=b.snap.today, desc="kulkas")
        ctx, sel = run(b)
        aturan = ids(sel.semua)
        self.assertIn("HAR-03", aturan)
        self.assertNotIn("HAR-01", aturan)
        self.assertNotIn("PER-01", aturan)
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-03")
        chip = render.teks(sel.kpi["jatah"], ctx, "jatah")["chip"]
        self.assertEqual(chip, "Belanja besar Rp2 jt")

    def test_6_hari_terakhir(self):
        b = normal(today=date(2026, 10, 31))
        payload, _ = susun_dashboard(b.build(), now_local=jam(date(2026, 10, 31)))
        m = payload["metrics"]
        self.assertEqual(m["sisa_hari"], 0)
        self.assertIsNone(m["j1"])
        self.assertEqual(m["j0"], int(floor100(D(m["sisa_bebas"]) + D(m["belanja_hari_ini"]))))
        self.assertIsNotNone(payload["kpi"]["jatah"])
        self.assertNotIn("PER-01", [i["aturan"] for i in payload["advisor"]["items"]])

    def test_13_invarian_j0(self):
        def j0(b):
            return susun_dashboard(b.build(), now_local=jam(b.snap.today))[0]["metrics"]["j0"]
        base = j0(normal(dana=6_000_000))
        b = normal(dana=6_000_000)
        b.txn("makan", 2_000_000, desc="kulkas")                   # outlier
        b.txn("makan", 30_000, desc="penyesuaian", adjustment=True)  # penyesuaian saldo
        self.assertEqual(j0(b), base)
        b = normal(dana=6_000_000)
        b.recurring("makan", 250_000, "Langganan", date(2026, 10, 20))
        belum_bayar = j0(b)
        b = normal(dana=6_000_000)
        b.recurring("makan", 250_000, "Langganan", date(2026, 11, 20))  # Bayar: next_run maju
        b.txn("makan", 250_000, desc="🔄 Langganan")
        self.assertEqual(j0(b), belum_bayar)
        b = normal(dana=6_000_000)
        b.fund("makan", 340_000, on=b.snap.today)                   # alokasi hari ini mengubah J0
        self.assertGreater(j0(b), base)

    def test_17b_har01_jadi_item_saat_periode_aman(self):
        ctx, sel = run(normal(dana=4_500_000, hari_ini=300_000))
        self.assertNotIn("PER-01", ids(sel.semua))
        har = next(i for i in sel.semua if i.aturan == "HAR-01")
        self.assertEqual(har.tone, "danger")
        self.assertIn("HAR-01", ids(sel.daftar))

    def test_har01_warn_tidak_masuk_daftar(self):
        ctx, sel = run(normal(dana=4_500_000, hari_ini=200_000))
        har = next(i for i in sel.semua if i.aturan == "HAR-01")
        self.assertEqual(har.tone, "warn")
        self.assertNotIn("HAR-01", ids(sel.daftar))
        self.assertEqual(render.teks(har, ctx, "jatah")["chip"], "Lewat Rp17 rb")


def _ins(aturan, tone, skor=0, amplop=None, entitas="x", aksi=True, rupiah=0):
    i = Insight(aturan=aturan, entitas=entitas, tone=tone, slot=("daftar",),
                aksi=[{"kind": "route", "kode": "x", "payload": {"path": "/"}}] if aksi else [],
                rupiah=D(rupiah), amplop_id=amplop)
    i.skor = D(skor)
    return i


class SeleksiTests(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = run(normal())

    def test_16_kelompok_tone_dulu(self):
        tampil, _ = pilih_daftar([_ins("TAB-01", "info", 90), _ins("PER-01", "warn", 40)], self.ctx)
        self.assertEqual(ids(tampil), ["PER-01", "TAB-01"])

    def test_info_hanya_bila_danger_warn_kurang_dari_3(self):
        xs = [_ins("TAG-01", "danger", 50, entitas="a"), _ins("PER-01", "warn", 40),
              _ins("AMP-03", "warn", 30, amplop="e1"), _ins("TAB-01", "info", 90)]
        tampil, sisa = pilih_daftar(xs, self.ctx)
        self.assertEqual(ids(tampil), ["TAG-01", "PER-01", "AMP-03"])
        self.assertEqual(sisa, [])

    def test_batas_domain_dan_amplop(self):
        xs = [_ins("AMP-02", "warn", 50, amplop="e1", entitas="1"), _ins("AMP-08", "warn", 40, amplop="e1", entitas="2"),
              _ins("AMP-03", "warn", 30, amplop="e2", entitas="3"), _ins("AMP-01", "danger", 20, amplop="e3", entitas="4"),
              _ins("TAG-02", "warn", 10, amplop="e1", entitas="5")]
        tampil, sisa = pilih_daftar(xs, self.ctx)
        # AMP-01 danger dulu; AMP-08 & TAG-02 (amplop e1 sudah ada) dan AMP-03 (domain AMP penuh) ke sisa.
        self.assertEqual([i.id for i in tampil], ["AMP-01:4", "AMP-02:1"])
        self.assertEqual({i.id for i in sisa}, {"AMP-08:2", "AMP-03:3", "TAG-02:5"})

    def test_11_kekurangan_total_menyerap_amplop(self):
        ctx, sel = run(contoh_15_okt(), h=6)
        amp2 = Insight(aturan="AMP-02", entitas="e1", tone="warn", slot=("daftar",),
                       aksi=[{"kind": "plan", "kode": "geser", "payload": {"kebutuhan": []}}], amplop_id="belanja")
        amp3 = Insight(aturan="AMP-03", entitas="e2", tone="danger", slot=("daftar",),
                       aksi=[{"kind": "route", "kode": "x", "payload": {}}], amplop_id="tagihan")
        from app.services.advisor.dashboard import EVALUATOR
        insights = [i for ev in EVALUATOR for i in ev(ctx)] + [amp2, amp3]
        sel = pilih(ctx, insights)
        self.assertNotIn("AMP-02", ids(sel.daftar))
        self.assertNotIn("AMP-03", ids(sel.daftar))
        per = next(i for i in sel.semua if i.aturan == "PER-01")
        self.assertEqual(ids(per.rincian), ["HAR-01", "AMP-03", "AMP-02", "AMP-03"])  # + AMP-03 asli (S4)
        self.assertEqual(per.tone, "warn")    # penyerapan kekurangan tidak menaikkan tone

    def test_tagihan_menyerap_amp01(self):
        tag = Insight(aturan="TAG-02", entitas="r", tone="warn", slot=("daftar",), amplop_id="makan",
                      aksi=[{"kind": "pay", "kode": "bayar", "payload": {}}])
        amp = Insight(aturan="AMP-01", entitas="makan", tone="danger", slot=("daftar",), amplop_id="makan",
                      aksi=[{"kind": "plan", "kode": "x", "payload": {"kebutuhan": []}}], rupiah=D(1))
        sel = pilih(self.ctx, [tag, amp])
        self.assertEqual(ids(sel.daftar), ["TAG-02"])
        self.assertEqual(sel.daftar[0].tone, "danger")

    def test_dismiss_dan_muncul_lagi(self):
        per = _ins("PER-01", "warn", rupiah=100_000)
        self.assertTrue(tersembunyi(per, {per.id: {"tone": "warn", "rupiah": "100000"}}))
        self.assertFalse(tersembunyi(per, {per.id: {"tone": "info", "rupiah": "100000"}}))  # tone naik
        self.assertFalse(tersembunyi(per, {per.id: {"tone": "warn", "rupiah": "60000"}}))   # rupiah +66%
        self.assertTrue(tersembunyi(per, {per.id: {"tone": "warn", "rupiah": "80000"}}))    # +25% saja

    def test_dismiss_menyembunyikan_dari_daftar_dan_chip(self):
        _, sel0 = run(contoh_15_okt(), h=6)
        per = next(i for i in sel0.semua if i.aturan == "PER-01")
        _, sel = run(contoh_15_okt(), h=6, dismiss={per.id: {"tone": per.tone, "rupiah": str(per.rupiah)}})
        self.assertNotIn("PER-01", ids(sel.daftar))
        self.assertNotEqual(getattr(sel.kpi["terpakai"], "aturan", None), "PER-01")
        self.assertIn(per.id, sel.disembunyikan)

    def test_rencana_bersama_dan_batas_harian(self):
        b = normal(dana=4_000_000)
        b.envelope("hobi", "Hobi", classification="wants")
        b.envelope("tab", "Tabungan", purpose="saving")
        b.fund("hobi", 1_000_000, on=b.ps)
        ctx, _ = run(b)
        plan = Insight(aturan="PER-06", entitas="p", tone="info", slot=("daftar",), aksi=[
            {"kind": "plan", "kode": "pindah_tabungan", "payload": {"kebutuhan": [{"tujuan_id": "tab", "jumlah": 400_000}]}}])
        batas = Insight(aturan="HAR-01", entitas="h", tone="warn", slot=("kpi:jatah",), data={"batas_amplop_id": "hobi"},
                        aksi=[{"kind": "daily_limit", "kode": "batas_harian", "payload": {"amplop_id": "hobi"}}])
        sel = pilih(ctx, [plan, batas])
        keluar = sel.rencana.keluar()
        self.assertEqual(keluar.get("hobi"), D("400000"))
        harapan = floor100((ctx.m.amplop["hobi"].bebas - D("400000")) / ctx.m.horizon)
        self.assertEqual(batas.aksi[0]["payload"]["jumlah"], int(harapan))
        self.assertEqual(batas.data["batas"], harapan)

    def test_kebutuhan_bersama_digabung(self):
        a = _ins("PER-02", "danger")
        a.aksi = [{"kind": "plan", "payload": {"kebutuhan": [{"tujuan_id": "x", "jumlah": 100}]}}]
        b = _ins("PER-06", "info")
        b.aksi = [{"kind": "plan", "payload": {"kebutuhan": [{"tujuan_id": "x", "jumlah": 300}, {"tujuan_id": "y", "jumlah": 5}]}}]
        self.assertEqual(kebutuhan_bersama([b, a]), [{"tujuan_id": "x", "jumlah": 300}, {"tujuan_id": "y", "jumlah": 5}])


class AturanTests(unittest.TestCase):
    def test_har02_mendekati(self):
        ctx, sel = run(normal(hari_ini=110_000))
        self.assertEqual(sel.kpi["jatah"].aturan, "HAR-02")
        self.assertEqual(sel.kpi["jatah"].tone, "warn")

    def test_har01_penyumbang_struk(self):
        b = normal(dana=4_500_000, hari_ini=100_000)
        t0 = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
        b.txn("makan", 120_000, desc="Susu (Indomaret)", created_at=t0)
        b.txn("makan", 80_000, desc="Roti (Indomaret)", created_at=t0 + timedelta(seconds=1))
        ctx, sel = run(b)
        har = next(i for i in sel.semua if i.aturan == "HAR-01")
        self.assertEqual(har.data["penyumbang"]["jenis"], "struk")
        self.assertIn("Struk Indomaret menyumbang 67%.", render.teks(har, ctx)["isi"])

    def test_har05_belum_ada_catatan_malam(self):
        b = normal(hari_ini=0)
        self.assertEqual(run(b, h=21)[1].kpi["jatah"].aturan, "HAR-05")
        self.assertEqual(run(normal(hari_ini=0), h=19)[1].kpi["jatah"].aturan, "HAR-04")

    def test_per01_keyakinan_rendah(self):
        b = SnapshotBuilder(date(2026, 10, 4), payday_day=1)
        b.envelope("makan", "Makan")
        b.fund("makan", 400_000, on=b.ps)
        b.txn("makan", 300_000, on=b.ps, desc="belanja bulanan")
        ctx, sel = run(b)
        per = next(i for i in sel.semua if i.aturan == "PER-01")
        self.assertEqual((per.keyakinan, per.tone), ("rendah", "warn"))   # danger dibatasi warn
        self.assertTrue(render.teks(per, ctx)["isi"].startswith("Kemungkinan: "))

    def test_per02_minus(self):
        b = normal(dana=1_000_000)
        ctx, sel = run(b)
        per = next(i for i in sel.semua if i.aturan == "PER-02")
        self.assertEqual(per.tone, "danger")
        self.assertEqual([a["kind"] for a in per.aksi], ["income", "plan"])
        self.assertEqual(per.aksi[1]["payload"]["kebutuhan"], [{"tujuan_id": "makan", "jumlah": 450_000}])
        self.assertEqual(sel.kpi["sisa_bebas"].aturan, "PER-02")
        self.assertEqual(render.teks(per, ctx)["chip"], "Minus Rp450 rb")
        self.assertEqual(sel.daftar[0].aturan, "PER-02")

    def test_per03_lebih_cepat(self):
        ctx, sel = run(normal(dana=2_000_000, harian=100_000, hari_ini=50_000))
        per3 = next(i for i in sel.semua if i.aturan == "PER-03")
        self.assertEqual(render.teks(per3, ctx)["chip"], "73% dana, 48% waktu")
        self.assertEqual(per3.tone, "warn")    # PER-01 juga menyala

    def test_per06_akhir_periode_non_rollover(self):
        b = normal(today=date(2026, 10, 30), dana=5_000_000)
        b.envelope("jajan", "Jajan", classification="wants", is_rollover=False)
        b.envelope("tab", "Tabungan", purpose="saving")
        b.fund("jajan", 200_000, on=b.ps)
        ctx, sel = run(b)
        per = next(i for i in sel.semua if i.aturan == "PER-06")
        self.assertEqual(per.data["hangus"], D("200000"))
        self.assertEqual(per.aksi[0]["payload"]["kebutuhan"], [{"tujuan_id": "tab", "jumlah": 200_000}])
        r = render.render_insight(per, ctx)
        self.assertEqual(r["judul"], "Sisa ±Rp200 rb — pindahkan ke tabungan?")
        self.assertEqual(r["aksi"][0]["label"], "Pindahkan ke Tabungan")
        self.assertEqual(r["isi"], "Rp200.000 di Jajan akan kembali ke 0 saat periode berganti.")

    def test_per07_ringkasan_periode_lalu(self):
        b = SnapshotBuilder(date(2026, 10, 1), payday_day=1)
        b.envelope("makan", "Makan")
        b.envelope("jalan", "Transport")
        prev = date(2026, 9, 1)
        b.fund("makan", 1_000_000, on=prev)
        b.fund("jalan", 100_000, on=prev)
        b.transfer("makan", "jalan", 50_000, on=date(2026, 9, 10))
        b.txn("makan", 900_000, on=date(2026, 9, 5))
        b.txn("jalan", 200_000, on=date(2026, 9, 6))
        ctx, sel = run(b)
        per = next(i for i in sel.semua if i.aturan == "PER-07")
        self.assertEqual(render.teks(per, ctx)["judul"], "Periode baru: 1 amplop minus, ditambal 1×, terbesar Makan")
        self.assertIn("PER-07", ids(sel.daftar))

    def test_per04_laju_membaik(self):
        b = SnapshotBuilder(date(2026, 10, 20), payday_day=1)
        b.envelope("makan", "Makan")
        b.fund("makan", 5_000_000, on=b.ps)
        for i in range(13):
            b.txn("makan", 200_000, on=b.ps + timedelta(days=i))
        for i in range(13, 20):
            b.txn("makan", 50_000, on=b.ps + timedelta(days=i))
        ctx, sel = run(b)
        self.assertEqual(sel.kpi["sisa_bebas"].aturan, "PER-04")
        self.assertEqual(render.teks(sel.kpi["sisa_bebas"], ctx)["chip"], "Laju turun 66%")


class RenderTests(unittest.TestCase):
    def test_format_angka(self):
        self.assertEqual(render.rp_ringkas(1_685_200), "Rp1,68 jt")
        self.assertEqual(render.rp_ringkas(1_600_000), "Rp1,6 jt")
        self.assertEqual(render.rp_ringkas(525_957), "Rp525 rb")
        self.assertEqual(render.rp_ringkas(800), "Rp800")
        self.assertEqual(render.rp_ringkas(-408_174), "–Rp408 rb")
        self.assertEqual(render.rp_penuh(2_008_174), "Rp2.008.174")
        self.assertEqual(render.rp_penuh(D("-408174")), "–Rp408.174")
        self.assertEqual(render.rasio(D("1.7995")), "1,8×")
        self.assertEqual(render.tgl(date(2026, 10, 24)), "24 Okt")
        self.assertEqual(render.hari_tgl(date(2026, 10, 15)), "Kamis 15 Okt")
        self.assertEqual(render.persen(D("0.456")), "46%")

    def test_alasan_rencana_di_render(self):
        self.assertEqual(render.alasan_rencana("a", D("453894")),
                         "Amplop keinginan, masih lebih Rp453.894 sampai akhir periode")

    def test_teks_telegram(self):
        self.assertEqual(render.teks_telegram({"tone": "danger", "judul": "A", "isi": "B"}), "🔴 A\nB")

    def test_grafik(self):
        ctx, sel = run(contoh_15_okt(), h=6)
        g = render.teks_grafik(ctx.m, ctx.s)
        self.assertEqual(g["teks"], "4 dari 7 hari terakhir lewat jatah, tertinggi Senin 12 Okt Rp400 rb")
        self.assertEqual(g["aksi"]["payload"]["path"], "/transactions?date=2026-10-12")
        ctx, _ = run(normal())
        self.assertEqual(render.teks_grafik(ctx.m, ctx.s)["teks"], "Semua hari dalam jatah minggu ini")

    def test_payload_kontrak(self):
        payload, meta = susun_dashboard(contoh_15_okt().build(), now_local=jam(date(2026, 10, 15), 6))
        self.assertEqual(set(payload), {"enabled", "generated_at", "metrics", "kpi", "grafik", "advisor", "redam_chip"})
        self.assertEqual(set(payload["kpi"]), {"jatah", "sisa_bebas", "terpakai", "income", "tagihan", "tabungan"})
        item = payload["advisor"]["items"][0]
        for key in ("id", "aturan", "tone", "chip", "judul", "isi", "fakta", "aksi", "dasar", "dismiss"):
            self.assertIn(key, item)
        self.assertEqual(item["dismiss"], {"kunci": item["id"], "pilihan": ["nanti", "periode", "tidak_relevan"]})
        self.assertEqual(payload["generated_at"], "2026-10-15T06:00:00+07:00")
        self.assertIn(item["id"], meta)


class PengaturanTests(unittest.TestCase):
    def test_flag(self):
        self.assertTrue(flag_aktif("*", "u1"))
        self.assertTrue(flag_aktif(" u1 , u2", "u2"))
        self.assertFalse(flag_aktif("u1", "u2"))
        self.assertFalse(flag_aktif(None, "u1"))

    def test_konstanta_dari_appsetting(self):
        with self.assertLogs("jatahku.advisor.dashboard", "WARNING"):
            km, ks, ka = bangun_konstanta('{"cta_batas_harian": true, "hari_min_proyeksi": 4, '
                                          '"lonjakan_min": "50000", "asing": 1, "daftar_maks": "x"}')
        self.assertTrue(ka.cta_batas_harian)
        self.assertEqual(km.hari_min_proyeksi, 4)
        self.assertEqual(ks.lonjakan_min, D("50000"))
        self.assertEqual(ka.daftar_maks, 3)    # nilai tidak sah diabaikan
        with self.assertLogs("jatahku.advisor.dashboard", "WARNING"):
            self.assertEqual(bangun_konstanta("bukan json")[2], KA)

    def test_ttl_dismiss(self):
        now = datetime(2026, 10, 15, 22, 0, tzinfo=JKT)
        self.assertEqual(ttl_dismiss("nanti", now, date(2026, 10, 26)), 7 * 3600)
        self.assertEqual(ttl_dismiss("periode", now, date(2026, 10, 26)), (11 * 24 + 2) * 3600)
        self.assertEqual(ttl_dismiss("tidak_relevan", now, date(2026, 10, 26)), 90 * 24 * 3600)

    def test_skor(self):
        i = _ins("X-1", "warn", aksi=False, rupiah=0)
        i.urgensi = D("0.2")
        self.assertEqual(hitung_skor(i, D("1000000")), D("100") * (D("0.45") * D("0.2") + D("0.2") * D("0.4")))


if __name__ == "__main__":
    unittest.main()
