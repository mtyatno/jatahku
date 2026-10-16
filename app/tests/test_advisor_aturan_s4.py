"""AI Advisor v2 S4 — aturan Amplop, Tagihan, Pemasukan, Tabungan, Data (02-aturan.md §6C–G, §7, §13).

Fungsi murni dengan fixture `SnapshotBuilder` (tanpa DB). Skenario emas §13: 4, 5, 14, 15, 19;
ditambah contoh §12 (chip Tagihan/Tabungan/Income, skor TAG-01 dan TAB-01), tiap aturan, dan
penekanan yang menyangkut aturan S4 (3, 4, 7, PER-02 menyerap AMP-01).
Run: python -m unittest app.tests.test_advisor_aturan_s4 -v
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
from app.services.advisor.dashboard import analisa, susun_dashboard
from app.services.advisor.insight import DEFAULT as KA
from app.services.advisor.metrics import ceil10rb
from app.tests.advisor_v2_fixtures import PARTNER, SnapshotBuilder, contoh_15_okt

JKT = ZoneInfo("Asia/Jakarta")
TODAY = date(2026, 10, 15)


def run(b: SnapshotBuilder, h=12, ka=KA):
    snap = b.build()
    t = snap.today
    return analisa(snap, now_local=datetime(t.year, t.month, t.day, h, tzinfo=JKT), ka=ka)


def semua(sel, aturan):
    return [i for i in sel.semua if i.aturan == aturan]


def satu(sel, aturan):
    xs = semua(sel, aturan)
    assert len(xs) == 1, f"{aturan}: {[i.id for i in xs]}"
    return xs[0]


def kinds(ins):
    return [a["kind"] for a in ins.aksi]


def normal(today=TODAY, dana=3_500_000, harian=100_000, hari_ini=50_000) -> SnapshotBuilder:
    """Periode 1–31 Okt, satu amplop belanja needs, aman sampai akhir periode."""
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


def periode_lalu(b: SnapshotBuilder, n=3):
    """(awal, akhir) n periode sebelum periode berjalan, terlama dulu."""
    return b.snap.periods[-1 - n:-1]


def contoh_lengkap() -> SnapshotBuilder:
    """§12 dengan amplop Tagihan & Cicilan minus Rp408.174, target darurat Rp35 jt, pemasukan dari Rina."""
    b = contoh_15_okt()
    b.snap.incomes = [dataclasses.replace(i, user_id=PARTNER) for i in b.snap.incomes]
    b.txn("tagihan", 2_008_174, on=date(2026, 10, 1), desc="cicilan motor")
    b.goal("darurat", "Dana Darurat", 35_000_000)
    return b


# ── contoh §12 ────────────────────────────────────────────────────────────
class Contoh15OktS4Tests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.sel = run(contoh_lengkap(), h=6)

    def test_chip_tagihan_tabungan_income(self):
        kpi = {k: render.render_insight(v, self.ctx, kpi=k) for k, v in self.sel.kpi.items()}
        self.assertEqual(kpi["tagihan"]["aturan"], "TAG-01")
        self.assertEqual(kpi["tagihan"]["chip"], "KPR Rumah telat 9 hari")
        self.assertEqual(kpi["tabungan"]["aturan"], "TAB-01")
        self.assertEqual(kpi["tabungan"]["chip"], "Darurat 3%")
        self.assertEqual(kpi["income"]["aturan"], "INC-02")
        self.assertEqual(kpi["income"]["chip"], "Terisi dari Rina")
        self.assertTrue(self.sel.redam)

    def test_tag01_geser_bayar(self):
        tag = satu(self.sel, "TAG-01")
        self.assertEqual(tag.tone, "danger")
        self.assertAlmostEqual(float(tag.skor), 100.0, places=1)
        self.assertEqual(kinds(tag), ["plan", "pay"])
        self.assertEqual(tag.aksi[0]["payload"]["kebutuhan"],
                         [{"tujuan_id": "tagihan", "jumlah": 2_008_174, "bayar_recurring_id": "kpr"}])
        r = render.render_insight(tag, self.ctx)
        self.assertEqual(r["judul"], "Lunasi KPR Rumah — telat 9 hari")
        self.assertIn("Amplop Tagihan & Cicilan minus Rp408.174, jadi perlu Rp2.008.174.", r["isi"])
        self.assertEqual([a["label"] for a in r["aksi"]], ["Geser & bayar KPR Rumah", "Bayar saja"])

    def test_tag01_menyerap_amp01(self):  # penekanan 3
        tag = satu(self.sel, "TAG-01")
        self.assertIn("AMP-01", [r.aturan for r in tag.rincian])
        self.assertNotIn("AMP-01:tagihan", [i.id for i in self.sel.daftar + self.sel.sisa])
        self.assertEqual(self.sel.daftar[0].aturan, "TAG-01")

    def test_tab01_rencanakan_skor_23(self):  # skenario 19
        tab = satu(self.sel, "TAB-01")
        self.assertEqual(tab.tone, "info")
        self.assertEqual(tab.rupiah, 0)
        self.assertEqual([a["kode"] for a in tab.aksi], ["rencanakan_alokasi"])
        self.assertAlmostEqual(float(tab.skor), 23.0, places=1)
        r = render.render_insight(tab, self.ctx)
        self.assertIn("setoran dijadwalkan periode depan", r["isi"])
        self.assertEqual(r["aksi"][0]["label"], "Rencanakan di alokasi berikutnya")

    def test_rencana_tidak_dobel_minus(self):
        # AMP-01 Tagihan diserap TAG-01: kebutuhan rencana bersama hanya dari TAG-01 (bukan + minus lagi)
        r = self.sel.rencana
        total = sum(sum(b.ke.values()) for b in r.baris) + r.kurang
        self.assertEqual(total, 2_008_174)

    def test_payload_dashboard_lengkap(self):
        snap = contoh_lengkap().build()
        payload, _ = susun_dashboard(snap, now_local=datetime(2026, 10, 15, 6, tzinfo=JKT))
        for k in ("income", "tagihan", "tabungan"):
            self.assertIsNotNone(payload["kpi"][k], k)


# ── skenario emas §13 ────────────────────────────────────────────────────
class SkenarioS4Tests(unittest.TestCase):
    def test_4_tagihan_hari_pertama_bukan_laju(self):
        b = normal()
        b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
        b.fund("tagihan", 1_000_000, on=b.ps)
        b.recurring("tagihan", 1_000_000, "Kos", date(2026, 11, 1))   # next_run sudah maju: dibayar
        b.txn("tagihan", 1_000_000, on=b.ps, desc="🔄 Kos")
        ctx, sel = run(b)
        self.assertEqual(ctx.m.laju_total, run(normal())[0].m.laju_total)   # pembayaran Kos tidak masuk laju
        self.assertEqual([i.id for i in sel.semua if i.tone in ("danger", "warn")], [])
        self.assertEqual(sel.kpi["tagihan"].aturan, "TAG-09")
        self.assertEqual(render.teks(sel.kpi["tagihan"], ctx, "tagihan")["chip"], "Lunas semua")

    def test_5_pemasukan_dicatat_pasangan(self):
        b = SnapshotBuilder(TODAY, payday_day=1)
        b.envelope("makan", "Makan", classification="needs")
        b.envelope("pribadi", "Pribadi Rina", owner_id=None)
        b.income(5_000_000, on=b.ps, user=PARTNER, alloc={"makan": 3_000_000, None: 2_000_000})
        ctx, sel = run(b)
        self.assertEqual(sel.kpi["income"].aturan, "INC-02")
        self.assertEqual(semua(sel, "INC-01"), [])
        r = render.render_insight(sel.kpi["income"], ctx, kpi="income")
        self.assertEqual(r["chip"], "Terisi dari Rina")
        self.assertIn("Tidak perlu dicatat ulang", r["isi"])
        # hanya dana yang masuk ke amplop bersama, bukan total pemasukan Rina
        self.assertEqual(r["fakta"][0]["nilai"], "Rp3.000.000")
        self.assertNotIn("5.000.000", str(r))

    def test_14_tagihan_dibayar_manual(self):
        b = normal()
        b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
        b.fund("tagihan", 1_000_000, on=b.ps)
        b.recurring("tagihan", 750_000, "Listrik", date(2026, 10, 10), id="listrik")
        tid = b.txn("tagihan", 750_000, on=date(2026, 10, 9), desc="bayar PLN")
        ctx, sel = run(b)
        self.assertEqual(ctx.m.amplop["tagihan"].tagihan_sisa, 0)        # M4 lunas: tidak hitung ganda di T3
        self.assertEqual(semua(sel, "TAG-01"), [])
        dat = satu(sel, "DAT-06")
        self.assertEqual(dat.tone, "warn")
        self.assertEqual(dat.aksi[0], {"kind": "mark_paid", "kode": "tandai_lunas",
                                       "payload": {"recurring_id": "listrik"}})
        self.assertEqual(dat.data["txn_id"], tid)
        self.assertEqual(sel.kpi["tagihan"].aturan, "DAT-06")
        r = render.render_insight(dat, ctx)
        self.assertIn("Transaksi bayar PLN Rp750.000 nominalnya sama dengan tagihan Listrik", r["isi"])
        self.assertEqual([a["label"] for a in r["aksi"]], ["Tandai lunas", "Bukan pembayaran tagihan"])

    def test_15_struk_kembar_vs_struk_terkirim_dua_kali(self):
        b = normal()
        t0 = datetime(2026, 10, 15, 5, 0, 0, tzinfo=timezone.utc)
        for i, (desc, amt) in enumerate([("Susu (Indomaret)", 20_000), ("Susu (Indomaret)", 20_000),
                                         ("Roti (Indomaret)", 15_000)]):
            b.txn("makan", amt, desc=desc, created_at=t0 + timedelta(milliseconds=i * 5))
        ctx, sel = run(b)
        self.assertEqual(semua(sel, "DAT-03"), [])                       # barang kembar dalam satu struk
        t1 = t0 + timedelta(seconds=40)
        ids = [b.txn("makan", amt, desc=desc, created_at=t1 + timedelta(milliseconds=i * 5))
               for i, (desc, amt) in enumerate([("Susu (Indomaret)", 20_000), ("Susu (Indomaret)", 20_000),
                                                ("Roti (Indomaret)", 15_000)])]
        ctx, sel = run(b)
        dat = satu(sel, "DAT-03")
        self.assertEqual(dat.data["jenis"], "struk")
        self.assertEqual(dat.aksi[0]["payload"]["txn_ids"], ids)
        self.assertEqual(dat.slot, ("transaksi",))                       # < Rp100 rb: tidak masuk daftar
        r = render.render_insight(dat, ctx)
        self.assertEqual(r["judul"], "Struk Indomaret sepertinya tercatat dua kali (3 barang)")
        self.assertEqual([a["label"] for a in r["aksi"]], ["Hapus duplikat (3 barang)", "Bukan dobel"])
        self.assertEqual(r["aksi"][1]["payload"], {"kunci": dat.id})

    def test_19_setor_saat_tidak_defisit(self):
        b = normal()
        b.envelope("darurat", "Dana Darurat", purpose="saving", is_emergency=True)
        b.lifetime("darurat", 1_000_000)
        ctx, sel = run(b)
        tab = satu(sel, "TAB-01")
        self.assertEqual(kinds(tab), ["plan"])
        saran = tab.aksi[0]["payload"]["kebutuhan"][0]["jumlah"]
        self.assertGreater(saran, 0)
        self.assertEqual(tab.rupiah, tab.data["saran"])
        self.assertEqual(render.render_insight(tab, ctx)["aksi"][0]["label"][:5], "Setor")


# ── C. Amplop ────────────────────────────────────────────────────────────
class AmplopTests(unittest.TestCase):
    def test_amp01_diserap_per02(self):
        ctx, sel = run(normal(dana=1_000_000))
        amp = satu(sel, "AMP-01")
        per = satu(sel, "PER-02")
        self.assertIn(amp, per.rincian)
        self.assertNotIn(amp.id, [i.id for i in sel.daftar + sel.sisa])

    def _dua_amplop(self, jajan_dana, jajan_harian):
        b = normal(dana=6_000_000)
        b.envelope("jajan", "Jajan", classification="wants")
        b.fund("jajan", jajan_dana, on=b.ps)
        d = b.ps
        while d <= TODAY:
            b.txn("jajan", jajan_harian, on=d, desc=f"kopi {d.day}")
            d += timedelta(days=1)
        return b

    def test_amp03_akan_habis(self):
        ctx, sel = run(self._dua_amplop(700_000, 40_000))   # bebas 100rb, laju 40rb × 16 hari
        amp = satu(sel, "AMP-03")
        self.assertEqual(amp.tone, "danger")                 # habis ≤ 3 hari lagi
        self.assertEqual(amp.data["kurang"], D("540000"))
        self.assertEqual(amp.aksi[-1]["payload"]["kebutuhan"], [{"tujuan_id": "jajan", "jumlah": 540_000}])
        r = render.render_insight(amp, ctx)
        self.assertEqual(r["chip"], "Habis ±18 Okt")
        self.assertEqual(r["judul"], "Jajan: maksimal Rp6 rb/hari")   # floor100(100.000 ÷ 16)

    def test_amp02_habis(self):
        ctx, sel = run(self._dua_amplop(600_000, 40_000))
        amp = satu(sel, "AMP-02")
        self.assertEqual(amp.tone, "warn")
        self.assertEqual(amp.data["kurang"], D("640000"))
        self.assertEqual(render.teks(amp, ctx)["chip"], "Habis")

    def test_amp04_ditambal(self):
        b = self._dua_amplop(100_000, 40_000)
        for i in range(4):
            b.transfer("makan", "jajan", 150_000, on=b.ps + timedelta(days=i * 3))
        ctx, sel = run(b)
        amp = satu(sel, "AMP-04")
        self.assertEqual(amp.data["n"], 4)
        self.assertEqual(amp.aksi[0]["payload"], {"amplop_id": "jajan", "jumlah": 1_240_000})  # ceil10rb(40rb × 31)
        r = render.render_insight(amp, ctx)
        self.assertEqual(r["judul"], "Jajan ditambal 4× — jatahnya kekecilan")
        self.assertIn("Total tambalan Rp600.000 (4×), semuanya dari Makan.", r["isi"])
        self.assertEqual(r["aksi"][0]["label"], "Naikkan jatah jadi Rp1,24 jt mulai 1 Nov")

    def _riwayat(self, terpakai_lalu, budget, dana_lalu=None):
        b = normal()
        b.snap.envelopes[0].budget_amount = D(budget)
        for ps, pe in periode_lalu(b):
            b.fund("makan", dana_lalu or budget, on=ps)
            b.txn("makan", terpakai_lalu, on=ps + timedelta(days=5), desc="belanja bulanan")
        return b

    def test_amp05_kekurangan_kronis(self):
        ctx, sel = run(self._riwayat(4_000_000, 3_000_000))
        amp = satu(sel, "AMP-05")
        self.assertEqual(amp.aksi[0]["payload"], {"amplop_id": "makan", "jumlah": 4_000_000})

    def test_amp06_kelebihan_kronis(self):
        b = self._riwayat(1_000_000, 3_000_000)
        b.envelope("tab", "Tabungan", purpose="saving")
        ctx, sel = run(b)
        amp = satu(sel, "AMP-06")
        self.assertEqual(amp.aksi[0]["payload"]["jumlah"], int(ceil10rb(D("1100000"))))
        r = render.render_insight(amp, ctx)
        self.assertIn("rata-rata 33% dari jatah", r["isi"])
        self.assertIn("sisanya ke Tabungan", r["judul"])

    def test_amp08_lonjakan(self):
        b = normal(harian=10_000, hari_ini=0)
        for ps, pe in periode_lalu(b):
            b.fund("makan", 3_500_000, on=ps)
            b.txn("makan", 300_000, on=ps + timedelta(days=3), desc="belanja")
        b.txn("makan", 400_000, on=TODAY - timedelta(days=1), desc="belanja besar")
        b.txn("makan", 300_000, on=TODAY, desc="belanja lagi")
        ctx, sel = run(b)
        amp = satu(sel, "AMP-08")
        self.assertEqual(amp.tone, "warn")
        self.assertEqual(amp.aksi[0]["payload"], {"path": "/transactions?envelope=makan"})
        self.assertIn("biasanya", render.teks(amp, ctx)["chip"])

    def test_amp09_belum_didanai(self):
        b = normal()
        b.envelope("listrik", "Listrik", classification="needs", budget_amount=D(500_000))
        ctx, sel = run(b)
        amp = satu(sel, "AMP-09")
        self.assertEqual(amp.tone, "info")
        self.assertEqual(amp.aksi[0]["payload"], {"path": "/allocate?new=1&amount=500000"})

    def test_amp10_batas_sering_terlewat(self):
        b = normal()
        b.snap.envelopes[0].daily_limit = D(80_000)
        ctx, sel = run(b)
        amp = satu(sel, "AMP-10")
        self.assertEqual(kinds(amp), ["dismiss"])                    # CTA batas mati sampai Pikir-Pikir (§2)
        ctx, sel = run(b, ka=dataclasses.replace(KA, cta_batas_harian=True))
        amp = satu(sel, "AMP-10")
        self.assertEqual(kinds(amp), ["daily_limit", "dismiss"])
        self.assertGreater(amp.aksi[0]["payload"]["jumlah"], 0)

    def test_amp11_tren(self):
        b = normal()
        ps, pe = b.snap.periods[-2]
        b.fund("makan", 3_500_000, on=ps)
        b.txn("makan", 500_000, on=ps + timedelta(days=2), desc="belanja")
        ctx, sel = run(b)
        amp = satu(sel, "AMP-11")
        self.assertEqual(amp.data["arah"], "naik")
        self.assertEqual(amp.slot, ("amplop", "analitik"))


# ── D. Tagihan ───────────────────────────────────────────────────────────
class TagihanTests(unittest.TestCase):
    def _tagihan(self, dana, jatuh_tempo, nominal=500_000, frequency="monthly"):
        b = normal()
        b.envelope("tagihan", "Tagihan", purpose="debt", classification="needs")
        if dana:
            b.fund("tagihan", dana, on=b.ps)
        rid = b.recurring("tagihan", nominal, "Internet", jatuh_tempo, frequency=frequency, id="net")
        return b, rid

    def test_tag02_hari_ini_danger(self):
        b, rid = self._tagihan(200_000, TODAY)
        ctx, sel = run(b)
        tag = satu(sel, "TAG-02")
        self.assertEqual(tag.tone, "danger")
        self.assertEqual(tag.aksi[0]["payload"]["kebutuhan"],
                         [{"tujuan_id": "tagihan", "jumlah": 300_000, "bayar_recurring_id": "net"}])
        self.assertEqual(render.teks(tag, ctx)["chip"], "Internet hari ini")

    def test_tag02_dua_hari_lagi_warn(self):
        b, _ = self._tagihan(200_000, TODAY + timedelta(days=2))
        ctx, sel = run(b)
        self.assertEqual(satu(sel, "TAG-02").tone, "warn")
        self.assertEqual(sel.kpi["tagihan"].aturan, "TAG-02")

    def test_tag03_dana_cukup(self):
        b, _ = self._tagihan(600_000, TODAY + timedelta(days=3))
        ctx, sel = run(b)
        tag = satu(sel, "TAG-03")
        self.assertEqual(kinds(tag), ["pay"])
        self.assertEqual(render.render_insight(tag, ctx)["aksi"][0]["label"], "Bayar sekarang")

    def test_tag09_berikutnya(self):
        b, _ = self._tagihan(600_000, date(2026, 10, 25))
        ctx, sel = run(b)
        self.assertEqual(sel.kpi["tagihan"].aturan, "TAG-09")
        self.assertEqual(render.teks(sel.kpi["tagihan"], ctx, "tagihan")["chip"], "Berikutnya Internet 25 Okt")

    def test_tag04_tahunan(self):
        b, _ = self._tagihan(400_000, date(2026, 12, 1), nominal=1_200_000, frequency="yearly")
        ctx, sel = run(b)
        tag = satu(sel, "TAG-04")
        self.assertEqual(tag.data["kurang"], D("800000"))
        self.assertIn("Sisihkan Rp400.000/bulan", render.teks(tag, ctx)["isi"])

    def test_tag05_beban_tinggi(self):
        b, _ = self._tagihan(3_000_000, date(2026, 10, 25), nominal=3_000_000)
        ctx, sel = run(b)
        tag = satu(sel, "TAG-05")
        self.assertIn("dari dana belanja", render.teks(tag, ctx)["isi"])

    def test_tag06_nominal_berubah(self):
        b, _ = self._tagihan(600_000, date(2026, 11, 3))
        b.txn("tagihan", 550_000, on=date(2026, 10, 3), desc="🔄 Internet")
        ctx, sel = run(b)
        tag = satu(sel, "TAG-06")
        self.assertEqual(tag.data["selisih"], D("50000"))
        self.assertEqual(render.teks(tag, ctx)["judul"], "Perbarui nominal Internet jadi Rp550 rb")

    def test_tag07_pola_rutin(self):
        b = normal()
        for ps, _ in b.snap.periods[-5:]:
            b.txn("makan", 65_000, on=ps + timedelta(days=4), desc="Spotify Family")
        ctx, sel = run(b)
        tag = satu(sel, "TAG-07")
        self.assertEqual(tag.aksi[0]["kind"], "make_recurring")
        p = tag.aksi[0]["payload"]
        self.assertEqual((p["deskripsi"], p["jumlah"], p["frekuensi"], p["amplop_id"]),
                         ("Spotify Family", 65_000, "monthly", "makan"))
        self.assertIn("transaksi", tag.slot)

    def test_tag08_langganan_ganda(self):
        b, _ = self._tagihan(2_000_000, date(2026, 10, 25), nominal=100_000)
        b.recurring("tagihan", 100_000, "Internet", date(2026, 10, 27))
        ctx, sel = run(b)
        self.assertEqual(len(semua(sel, "TAG-08")), 1)


# ── E. Pemasukan ─────────────────────────────────────────────────────────
class PemasukanTests(unittest.TestCase):
    def _riwayat_gaji(self, b, hari=0, jumlah=5_000_000):
        for ps, _ in periode_lalu(b):
            b.income(jumlah, on=ps + timedelta(days=hari), alloc={"makan": jumlah})

    def test_inc01_belum_masuk_dan_penekanan_4(self):
        b = SnapshotBuilder(TODAY, payday_day=1)
        b.envelope("makan", "Makan", classification="needs")
        self._riwayat_gaji(b)
        b.txn("makan", 100_000, on=b.ps, desc="makan")                   # amplop minus → PER-02 & AMP-01
        ctx, sel = run(b)
        inc = satu(sel, "INC-01")
        self.assertEqual(inc.tone, "danger")                              # T3 < 0
        self.assertEqual(inc.aksi[0]["payload"], {"jumlah": 5_000_000})
        self.assertEqual(kinds(inc), ["income", "dismiss"])
        self.assertEqual(sel.kpi["income"].aturan, "INC-01")
        self.assertEqual(render.teks(inc, ctx)["isi"], "Biasanya masuk sekitar tgl 1, ±Rp5 jt.")
        per = satu(sel, "PER-02")
        self.assertEqual(per.aksi[0]["kind"], "income")                   # penekanan 4: catat pemasukan pertama
        self.assertEqual(per.aksi[0]["payload"], {"jumlah": 5_000_000})

    def test_inc03_lebih_kecil(self):
        b = normal(dana=3_000_000)
        self._riwayat_gaji(b)
        ctx, sel = run(b)
        inc = satu(sel, "INC-03")
        self.assertEqual(inc.data["kurang"], D("2000000"))
        self.assertEqual(render.teks(inc, ctx)["chip"], "–40% dari biasa")

    def test_inc04_belum_dibagi(self):
        b = normal()
        b.income(1_000_000, on=TODAY - timedelta(days=3), alloc={"makan": 400_000},
                 created_at=datetime(2026, 10, 12, 3, tzinfo=timezone.utc))
        ctx, sel = run(b)
        inc = satu(sel, "INC-04")
        self.assertEqual(inc.rupiah, D("600000"))
        self.assertEqual(render.teks(inc, ctx)["chip"], "Rp600 rb belum dibagi")
        self.assertEqual(sel.kpi["income"].aturan, "INC-04")

    def test_inc05_saving_rate(self):
        b = normal()
        b.envelope("tab", "Tabungan", purpose="saving")
        b.income(1_000_000, on=b.ps, alloc={"tab": 1_000_000})
        ctx, sel = run(b)
        inc = satu(sel, "INC-05")
        self.assertEqual(inc.tone, "ok")
        self.assertEqual(render.teks(inc, ctx)["chip"], "Saving rate 22%")   # 1 jt ÷ 4,5 jt

    def test_inc06_gajian_bergeser(self):
        b = normal()
        self._riwayat_gaji(b, hari=5)
        b.snap.incomes[0] = dataclasses.replace(b.snap.incomes[0], amount=D(5_000_000))
        ctx, sel = run(b)
        inc = satu(sel, "INC-06")
        self.assertEqual(inc.data["tanggal"], 6)
        self.assertEqual(render.teks(inc, ctx)["judul"], "Ubah Tanggal Gajian ke tgl 6?")


# ── F. Tabungan ──────────────────────────────────────────────────────────
class TabunganTests(unittest.TestCase):
    def _tab(self, saldo, target, target_date=None, setoran_lalu=None):
        b = normal()
        b.envelope("tab", "Liburan", purpose="saving")
        b.lifetime("tab", saldo)
        b.goal("tab", "Liburan", target, target_date)
        for (ps, _), jml in zip(periode_lalu(b), setoran_lalu or []):
            if jml:
                b.fund("tab", jml, on=ps)
        return b

    def test_tab02_tertinggal_dekat(self):
        b = self._tab(1_000_000, 10_000_000, date(2026, 12, 31), setoran_lalu=[500_000, 500_000, 500_000])
        ctx, sel = run(b)
        tab = satu(sel, "TAB-02")
        self.assertEqual(tab.tone, "warn")
        self.assertEqual(tab.aksi[0]["kind"], "plan")
        self.assertEqual(render.teks(tab, ctx)["chip"], "Liburan tertinggal")
        self.assertEqual(sel.kpi["tabungan"].aturan, "TAB-02")

    def test_tab02_tenggat_jauh_saat_defisit_ditunda(self):
        b = self._tab(1_000_000, 10_000_000, date(2027, 6, 30), setoran_lalu=[100_000, 100_000, 100_000])
        b.txn("makan", 3_000_000, on=TODAY - timedelta(days=1), desc="servis")  # defisit
        ctx, sel = run(b)
        tab = satu(sel, "TAB-02")
        self.assertEqual(tab.aksi[0]["kode"], "rencanakan_alokasi")
        self.assertEqual(tab.rupiah, 0)

    def test_tab03_tanpa_setoran(self):
        b = self._tab(1_000_000, 10_000_000, setoran_lalu=[500_000, 0, 0])
        ctx, sel = run(b)
        tab = satu(sel, "TAB-03")
        self.assertEqual(tab.aksi[0]["kind"], "plan")

    def test_tab04_hampir_tab05_tercapai(self):
        ctx, sel = run(self._tab(9_500_000, 10_000_000))
        self.assertEqual(render.teks(satu(sel, "TAB-04"), ctx)["chip"], "Kurang Rp500 rb")
        ctx, sel = run(self._tab(10_000_000, 10_000_000))
        self.assertEqual(satu(sel, "TAB-05").tone, "ok")
        self.assertEqual(sel.kpi["tabungan"].aturan, "TAB-05")

    def test_tab06_target_paralel(self):
        b = normal()
        for i in range(5):
            b.envelope(f"t{i}", f"Target {i}", purpose="saving")
            b.lifetime(f"t{i}", 100_000)
            b.goal(f"t{i}", f"Target {i}", 10_000_000)
        ctx, sel = run(b)
        self.assertEqual(satu(sel, "TAB-06").data["n"], 5)

    def test_tab07_cadangan_chip(self):
        b = normal()
        b.envelope("tab", "Tabungan", purpose="saving")
        b.fund("tab", 250_000, on=b.ps)
        b.lifetime("tab", 250_000)
        ctx, sel = run(b)
        self.assertEqual(sel.kpi["tabungan"].aturan, "TAB-07")
        self.assertEqual(render.teks(sel.kpi["tabungan"], ctx, "tabungan")["chip"], "+Rp250 rb periode ini")


# ── G. Kebersihan data ───────────────────────────────────────────────────
class DataTests(unittest.TestCase):
    def test_dat01_dat02_cocokkan(self):
        b = normal()
        b.balance_check(TODAY - timedelta(days=20), 400_000)
        for i in range(5):                                   # 26–30 Sep + 15 hari Oktober = 20 transaksi
            b.txn("makan", 10_000, on=date(2026, 9, 26 + i), desc=f"jajan {i}")
        ctx, sel = run(b)
        dat = satu(sel, "DAT-01")
        self.assertEqual(dat.aksi[0]["kind"], "balance")
        self.assertGreaterEqual(dat.data["n"], 20)
        self.assertEqual(satu(sel, "DAT-02").slot, ("analitik",))

    def test_dat03_dobel_masuk_daftar(self):
        b = normal()
        t0 = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)
        first = b.txn("makan", 150_000, desc="belanja pasar", created_at=t0)
        second = b.txn("makan", 150_000, desc="belanja pasar", created_at=t0 + timedelta(minutes=3))
        ctx, sel = run(b)
        dat = satu(sel, "DAT-03")
        self.assertEqual(dat.entitas, first)
        self.assertEqual(dat.aksi[0]["payload"], {"txn_id": second, "txn_ids": [second]})
        self.assertIn("daftar", dat.slot)
        self.assertIn(dat.id, [i.id for i in sel.daftar])

    def test_dat04_lupa_catat(self):
        b = SnapshotBuilder(TODAY, payday_day=1)
        b.envelope("makan", "Makan", classification="needs")
        b.fund("makan", 5_000_000, on=b.ps)
        for i in range(2, 14):
            b.txn("makan", 50_000, on=TODAY - timedelta(days=i), desc=f"makan {i}")
        b.snap.last_viewer_txn_date = TODAY - timedelta(days=2)
        ctx, sel = run(b)
        self.assertEqual(satu(sel, "DAT-04").aksi[0]["kind"], "expense")

    def test_dat05_belum_diklasifikasi(self):
        b = normal()
        b.envelope("lain", "Lain-lain")
        ctx, sel = run(b)
        dat = satu(sel, "DAT-05")
        self.assertEqual(dat.data["nama"], ["Lain-lain"])


class RenderSemuaTests(unittest.TestCase):
    """Setiap insight S4 punya template: chip, judul, isi, label aksi tanpa error, dengan chip KPI."""

    def test_render_semua(self):
        b = contoh_lengkap()
        b.envelope("transport", "Transport", classification="needs", daily_limit=D(10_000))
        b.fund("transport", 59_000, on=b.ps)
        for i in range(7):
            b.transfer("belanja", "transport", 55_000, on=b.ps + timedelta(days=i * 2))
        for i in range(19):
            b.txn("transport", 23_711, on=b.ps + timedelta(days=i), desc=f"ojek {i}")
        b.recurring("belanja", 50_000, "Spotify", date(2026, 10, 17))
        b.recurring("belanja", 1_200_000, "Asuransi", date(2026, 11, 20), frequency="yearly")
        b.balance_check(date(2026, 9, 1), 900_000)
        for ka in (KA, dataclasses.replace(KA, cta_batas_harian=True)):
            ctx, sel = run(b, h=21, ka=ka)
            aturan = set()
            for ins in sel.semua:
                r = render.render_insight(ins, ctx)
                aturan.add(ins.aturan)
                for key in ("chip", "judul", "isi"):
                    self.assertIsInstance(r[key], str, ins.id)
                    self.assertNotIn("None", r[key], ins.id)
                self.assertTrue(all(a["label"] for a in r["aksi"]), ins.id)
            for kartu, ins in sel.kpi.items():
                self.assertIsNotNone(ins, kartu)
                self.assertTrue(render.render_insight(ins, ctx, kpi=kartu)["chip"])
            self.assertTrue({"AMP-04", "AMP-10", "TAG-01", "TAG-03", "TAB-01", "DAT-01", "DAT-05"} <= aturan, aturan)


if __name__ == "__main__":
    unittest.main()
