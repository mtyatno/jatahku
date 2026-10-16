"""AI Advisor v2 — signals.py (02-aturan.md §4, §11, §13 skenario 9 & 15). Fungsi murni, fixture tanpa DB.

Run: python -m unittest app.tests.test_advisor_signals -v
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.services.advisor.metrics import compute_metrics
from app.services.advisor.signals import chains, compute_signals, parse_struk
from app.tests.advisor_v2_fixtures import PARTNER, SnapshotBuilder, contoh_15_okt

TODAY = date(2026, 10, 20)   # payday 1 → periode 1–31 Okt, d = 20, r = 11


def at(h, m=0, s=0, day=TODAY):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=timezone.utc)


def run(b):
    snap = b.build()
    m = compute_metrics(snap)
    return compute_signals(snap, m), m


def base(today=TODAY, **kw):
    b = SnapshotBuilder(today, **kw)
    b.envelope("makan", "Makan")
    b.fund("makan", 3_000_000)
    return b


class StrukTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_struk("Indomie Goreng (Indomaret)"), ("Indomie Goreng", "Indomaret"))
        self.assertIsNone(parse_struk("kopi susu"))

    def test_rantai_dipisah_jeda_lebih_10_detik(self):
        b = base()
        for i, sec in enumerate([0, 1, 2]):          # kiriman pertama
            b.txn("makan", 10_000 + i, desc=f"Barang {i} (Alfamart)", created_at=at(9, 0, sec))
        b.txn("makan", 5_000, desc="Roti (Alfamart)", created_at=at(9, 0, 30))   # kiriman kedua
        b.txn("makan", 7_000, desc="Susu (Indomaret)", created_at=at(9, 0, 3))   # toko lain
        s, _ = run(b)
        by_toko = sorted((st.toko, len(st.txn_ids)) for st in s.struk)
        self.assertEqual(by_toko, [("Alfamart", 1), ("Alfamart", 3), ("Indomaret", 1)])
        (tiga,) = [st for st in s.struk if len(st.txn_ids) == 3]
        self.assertEqual(tiga.total, D("30003"))

    def test_hanya_milik_viewer(self):
        b = base()
        b.txn("makan", 10_000, desc="Roti (Alfamart)", user=PARTNER, created_at=at(9))
        s, _ = run(b)
        self.assertEqual(s.struk, [])

    def test_chains_murni(self):
        b = base()
        b.txn("makan", 1, desc="A (X)", created_at=at(9, 0, 0))
        b.txn("makan", 1, desc="B (x)", created_at=at(9, 0, 10))   # tepat 10 detik, toko beda huruf
        self.assertEqual(len(chains(b.build().transactions, 10)), 1)


class DobelTests(unittest.TestCase):
    def test_kembar_dalam_satu_struk_tidak_dobel(self):  # skenario 9 & 15
        b = base()
        b.txn("makan", 3_500, desc="Aqua 600ml (Indomaret)", created_at=at(9, 0, 0))
        b.txn("makan", 3_500, desc="Aqua 600ml (Indomaret)", created_at=at(9, 0, 0))
        s, _ = run(b)
        self.assertEqual(s.dobel, [])
        self.assertEqual(s.struk_dobel, [])

    def test_struk_dikirim_ulang_40_detik_jadi_s4b(self):  # skenario 15
        b = base()
        items = [(3_500, "Aqua 600ml"), (3_500, "Aqua 600ml"), (12_000, "Roti Tawar")]
        for amt, name in items:
            b.txn("makan", amt, desc=f"{name} (Indomaret)", created_at=at(9, 0, 0))
        for amt, name in items:
            b.txn("makan", amt, desc=f"{name} (Indomaret)", created_at=at(9, 0, 40))
        s, _ = run(b)
        self.assertEqual(len(s.struk), 2)
        (grup,) = s.struk_dobel
        self.assertEqual((grup["toko"], grup["n_barang"], grup["total"]), ("Indomaret", 3, D("19000")))
        self.assertEqual(s.dobel, [])   # satu penanda untuk seluruh grup, bukan per barang
        self.assertIn("S4b", s.aktif())

    def test_struk_berbeda_isinya_bukan_s4b(self):
        b = base()
        b.txn("makan", 3_500, desc="Aqua (Indomaret)", created_at=at(9, 0, 0))
        b.txn("makan", 12_000, desc="Roti (Indomaret)", created_at=at(9, 0, 0))
        b.txn("makan", 8_000, desc="Susu (Indomaret)", created_at=at(9, 10, 0))
        b.txn("makan", 12_000, desc="Roti (Indomaret)", created_at=at(9, 10, 0))
        s, _ = run(b)
        self.assertEqual(s.struk_dobel, [])

    def test_struk_dobel_lewat_30_menit_tidak(self):
        b = base()
        for sec in (0, 1):
            b.txn("makan", 5_000 + sec, desc=f"B{sec} (Indomaret)", created_at=at(9, 0, sec))
            b.txn("makan", 5_000 + sec, desc=f"B{sec} (Indomaret)", created_at=at(9, 31, sec))
        s, _ = run(b)
        self.assertEqual(s.struk_dobel, [])

    def test_catat_biasa_dua_kali(self):
        b = base()
        t1 = b.txn("makan", 35_000, desc="kopi susu", created_at=at(8, 0))
        t2 = b.txn("makan", 35_000, desc="Kopi Susu", created_at=at(8, 4))
        s, _ = run(b)
        (d,) = s.dobel
        self.assertEqual((d["txn_ids"], d["hapus_saran"]), ([t1, t2], [t2]))
        self.assertIn("S4", s.aktif())

    def test_bukan_dobel(self):
        b = base()
        b.txn("makan", 35_000, desc="kopi susu", created_at=at(8, 0))
        b.txn("makan", 35_000, desc="kopi susu", created_at=at(8, 11))        # > 10 menit
        b.txn("makan", 36_000, desc="kopi susu", created_at=at(8, 1))         # nominal beda
        b.txn("makan", 35_000, desc="nasi padang", created_at=at(8, 2))       # deskripsi beda
        b.txn("makan", 35_000, desc="kopi susu", user=PARTNER, created_at=at(8, 3))  # pencatat lain
        s, _ = run(b)
        self.assertEqual(s.dobel, [])

    def test_privat_anggota_lain_tidak_dibandingkan(self):
        b = base()
        b.txn("makan", 50_000, desc="Transaksi privat", user=PARTNER, private=True, created_at=at(8, 0))
        b.txn("makan", 50_000, desc="Transaksi privat", user=PARTNER, private=True, created_at=at(8, 1))
        s, _ = run(b)
        self.assertEqual(s.dobel, [])

    def test_satu_barang_struk_terkirim_dua_kali_jadi_s4(self):
        b = base()
        b.txn("makan", 20_000, desc="Martabak (Martabak Bangka)", created_at=at(19, 0, 0))
        b.txn("makan", 20_000, desc="Martabak (Martabak Bangka)", created_at=at(19, 0, 40))
        s, _ = run(b)
        self.assertEqual(len(s.dobel), 1)
        self.assertEqual(s.struk_dobel, [])


class OutlierHarianTests(unittest.TestCase):
    def test_outlier_dari_metrics(self):
        b = base()
        for i in range(10):
            b.txn("makan", 30_000, on=TODAY - timedelta(days=i + 1))
        big = b.txn("makan", 1_500_000, desc="kulkas")
        s, m = run(b)
        self.assertEqual(m.jenis_transaksi[big], "outlier")
        (o,) = s.outlier
        self.assertEqual((o["txn_id"], o["hari_ini"]), (big, True))

    def test_lewat_jatah_s6(self):
        s, m = run(contoh_15_okt())
        self.assertEqual([h["tanggal"] for h in s.lewat_jatah if h["hari_ini"]], [date(2026, 10, 15)])
        self.assertEqual(len(s.lewat_jatah), sum(1 for h in m.harian if h["lewat"]))

    def test_contoh_15_okt_tanpa_alarm_palsu(self):
        s, _ = run(contoh_15_okt())
        self.assertEqual(s.aktif(), ["S6"])


def riwayat_builder(spent_past, budget=None, spent_now=0, tambal_past=0, today=TODAY):
    """Amplop 'jajan' dengan 3 periode lalu (Jul–Sep) terisi Rp1 jt, terpakai `spent_past`."""
    b = SnapshotBuilder(today)
    b.envelope("jajan", "Jajan", budget_amount=D(budget or 0))
    b.envelope("lain", "Lain")
    for p_s, _ in b.snap.periods[-4:-1]:
        b.fund("jajan", 1_000_000, on=p_s)
        b.fund("lain", 1_000_000, on=p_s)
        for day in range(0, 28, 2):
            b.txn("jajan", spent_past // 14, on=p_s + timedelta(days=day))
        for j in range(tambal_past):
            b.transfer("lain", "jajan", 10_000, on=p_s + timedelta(days=j + 1))
    b.fund("jajan", 1_000_000)
    b.fund("lain", 1_000_000)
    if spent_now:
        b.txn("jajan", spent_now, on=today - timedelta(days=1))
    return b


class LintasPeriodeTests(unittest.TestCase):
    def test_riwayat_metrics(self):
        _, m = run(riwayat_builder(700_000))
        rw = m.riwayat["jajan"]
        self.assertEqual(len(rw.dana), 6)
        self.assertEqual(rw.dana[-4:-1], [D("1000000")] * 3)
        self.assertEqual(rw.terpakai[-4:-1], [D("700000")] * 3)
        self.assertEqual(rw.alokasi_utama[-2], D("1000000"))

    def test_lonjakan(self):
        b = riwayat_builder(700_000)          # ±Rp157 rb per 7 hari
        for i in range(4):
            b.txn("jajan", 120_000, on=TODAY - timedelta(days=i))
        s, _ = run(b)
        (l,) = s.lonjakan
        self.assertEqual(l["envelope_id"], "jajan")
        self.assertEqual(l["variabel_7h"], D("480000"))
        self.assertGreater(l["selisih"], D("100000"))

    def test_tanpa_riwayat_tidak_lonjakan(self):
        b = base()
        for i in range(4):
            b.txn("makan", 200_000, on=TODAY - timedelta(days=i))
        s, _ = run(b)
        self.assertEqual(s.lonjakan, [])

    def test_kurang_kronis_terpakai(self):
        s, _ = run(riwayat_builder(1_200_000, budget=1_000_000))
        (k,) = [x for x in s.kurang_kronis if x["envelope_id"] == "jajan"]
        self.assertEqual(k["alasan"], "terpakai")

    def test_kurang_kronis_tambalan(self):
        s, _ = run(riwayat_builder(700_000, tambal_past=3))
        (k,) = [x for x in s.kurang_kronis if x["envelope_id"] == "jajan"]
        self.assertEqual((k["alasan"], k["periode_ditambal"]), ("tambalan", 3))

    def test_kelebihan_kronis_jatah_dari_median_alokasi(self):
        s, _ = run(riwayat_builder(560_000))
        self.assertIn("jajan", [x["envelope_id"] for x in s.lebih_kronis])
        (k,) = [x for x in s.lebih_kronis if x["envelope_id"] == "jajan"]
        self.assertEqual(k["jatah"], D("1000000"))

    def test_kelebihan_kronis_batal_bila_pernah_ditambal(self):
        s, _ = run(riwayat_builder(560_000, tambal_past=1))
        self.assertNotIn("jajan", [x["envelope_id"] for x in s.lebih_kronis])

    def test_tren_naik(self):
        b = riwayat_builder(700_000, spent_now=900_000)
        s, m = run(b)
        (t,) = [x for x in s.tren if x["envelope_id"] == "jajan"]
        self.assertEqual(t["arah"], "naik")
        self.assertEqual(t["terpakai_lalu"], m.riwayat["jajan"].terpakai_lalu_sd_hari_ke)

    def test_tren_kecil_diabaikan(self):
        b = riwayat_builder(700_000)
        b.txn("jajan", 520_000, on=TODAY - timedelta(days=1))  # periode lalu s/d hari 20 = 500 rb
        s, _ = run(b)
        self.assertEqual([x for x in s.tren if x["envelope_id"] == "jajan"], [])


class AmplopTests(unittest.TestCase):
    def test_menganggur(self):
        b = SnapshotBuilder(TODAY)
        b.envelope("hobi", "Hobi")
        b.envelope("tagihan", "Tagihan", purpose="debt")
        b.envelope("tabungan", "Tabungan", purpose="saving")
        b.fund("hobi", 1_000_000)
        b.fund("tagihan", 500_000)
        b.fund("tabungan", 1_000_000)
        b.txn("hobi", 50_000, on=TODAY - timedelta(days=3))
        b.recurring("tagihan", 500_000, "Listrik", date(2026, 10, 25))
        s, _ = run(b)
        self.assertEqual([x["envelope_id"] for x in s.menganggur], ["hobi"])  # tagihan & tabungan tidak

    def test_menganggur_belum_separuh_periode(self):
        b = SnapshotBuilder(date(2026, 10, 10))
        b.envelope("hobi", "Hobi")
        b.fund("hobi", 1_000_000)
        s, _ = run(b)
        self.assertEqual(s.menganggur, [])

    def test_sisa_non_rollover(self):
        b = SnapshotBuilder(date(2026, 10, 29))   # r = 2
        b.envelope("jajan", "Jajan", is_rollover=False)
        b.envelope("makan", "Makan")
        b.fund("jajan", 500_000)
        b.fund("makan", 500_000)
        s, _ = run(b)
        self.assertEqual([x["envelope_id"] for x in s.sisa_non_rollover], ["jajan"])
        s, _ = run(SnapshotBuilder(TODAY).envelope("jajan", "Jajan", is_rollover=False))
        self.assertEqual(s.sisa_non_rollover, [])


class TagihanTests(unittest.TestCase):
    def test_nominal_tagihan_berubah(self):
        b = base()
        rid = b.recurring("makan", 100_000, "Netflix", date(2026, 11, 5))
        b.txn("makan", 120_000, desc="🔄 Netflix", on=date(2026, 10, 5))
        s, _ = run(b)
        (x,) = s.tagihan_berubah
        self.assertEqual((x["recurring_id"], x["selisih"]), (rid, D("20000")))

    def test_nominal_sama_tidak_berubah(self):
        b = base()
        b.recurring("makan", 100_000, "Netflix", date(2026, 11, 5))
        b.txn("makan", 104_000, desc="🔄 Netflix", on=date(2026, 10, 5))
        s, _ = run(b)
        self.assertEqual(s.tagihan_berubah, [])

    def test_langganan_ganda(self):
        b = base()
        a = b.recurring("makan", 54_000, "Spotify Premium", date(2026, 10, 25))
        c = b.recurring("makan", 55_000, "spotify premium family", date(2026, 10, 28))
        b.recurring("makan", 55_000, "YouTube Premium", date(2026, 10, 28))
        s, _ = run(b)
        self.assertEqual([x["recurring_ids"] for x in s.langganan_ganda], [[a, c]])

    def test_dibayar_manual_s19(self):  # skenario 14 (M13)
        b = base()
        rid = b.recurring("makan", 250_000, "Internet", date(2026, 10, 10))
        tid = b.txn("makan", 250_000, desc="bayar internet", on=date(2026, 10, 11))
        s, _ = run(b)
        (x,) = s.dibayar_manual
        self.assertEqual((x["recurring_id"], x["txn_id"]), (rid, tid))

    def test_pola_rutin(self):
        b = SnapshotBuilder(TODAY)
        b.envelope("rumah", "Rumah")
        for p_s, _ in b.snap.periods[-4:]:
            b.fund("rumah", 3_000_000, on=p_s)
            b.txn("rumah", 150_000, desc="iuran kebersihan", on=p_s + timedelta(days=4))
        s, _ = run(b)
        (r,) = s.rutin
        self.assertEqual((r["frekuensi"], r["nominal"], r["kemunculan"]), ("monthly", D("150000"), 4))

    def test_pola_rutin_sudah_langganan(self):
        b = SnapshotBuilder(TODAY)
        b.envelope("rumah", "Rumah")
        for p_s, _ in b.snap.periods[-4:]:
            b.txn("rumah", 150_000, desc="iuran kebersihan", on=p_s + timedelta(days=4))
        b.recurring("rumah", 160_000, "Iuran kebersihan RT", date(2026, 11, 5))
        s, _ = run(b)
        self.assertEqual(s.rutin, [])

    def test_pola_rutin_nominal_acak_tidak(self):
        b = SnapshotBuilder(TODAY)
        b.envelope("rumah", "Rumah")
        for n, (p_s, _) in enumerate(b.snap.periods[-4:]):
            b.txn("rumah", [50_000, 200_000, 90_000, 400_000][n], desc="belanja pasar", on=p_s + timedelta(days=4))
        s, _ = run(b)
        self.assertEqual(s.rutin, [])


def pemasukan_builder(today, current=None, day_offset=2, past_amount=10_000_000):
    b = SnapshotBuilder(today)
    b.envelope("makan", "Makan")
    for p_s, _ in b.snap.periods[-4:-1]:
        b.income(past_amount, on=p_s + timedelta(days=day_offset), alloc={"makan": past_amount})
    if current is not None:
        b.income(current, on=b.ps + timedelta(days=day_offset), alloc={"makan": current})
    return b


class PemasukanTests(unittest.TestCase):
    def test_pemasukan_terlambat(self):
        s, m = run(pemasukan_builder(date(2026, 10, 7)))   # biasa tgl 3, batas tgl 6
        self.assertEqual(m.hari_biasa_masuk, 2)
        self.assertEqual(s.pemasukan_terlambat, {"hari_biasa": date(2026, 10, 3), "telat_hari": 4})

    def test_belum_lewat_batas(self):
        s, _ = run(pemasukan_builder(date(2026, 10, 6)))
        self.assertIsNone(s.pemasukan_terlambat)

    def test_pemasukan_dicatat_pasangan_bukan_terlambat(self):  # skenario 5
        b = pemasukan_builder(date(2026, 10, 7))
        b.income(9_000_000, on=date(2026, 10, 3), user=PARTNER, alloc={"makan": 9_000_000})
        s, _ = run(b)
        self.assertIsNone(s.pemasukan_terlambat)
        self.assertIsNone(s.pemasukan_kecil)

    def test_pemasukan_lebih_kecil(self):
        s, _ = run(pemasukan_builder(date(2026, 10, 10), current=7_000_000))
        self.assertEqual(s.pemasukan_kecil["kurang"], D("3000000"))
        self.assertIsNone(s.pemasukan_terlambat)

    def test_bukan_bulanan_tidak_dinilai(self):
        b = pemasukan_builder(date(2026, 10, 7))
        b.snap.income_type = "irregular"
        s, _ = run(b)
        self.assertIsNone(s.pemasukan_terlambat)

    def test_gajian_bergeser(self):
        s, _ = run(pemasukan_builder(date(2026, 10, 10), current=10_000_000, day_offset=4))
        self.assertEqual(s.gajian_bergeser["median_selisih"], 4)
        s, _ = run(pemasukan_builder(date(2026, 10, 10), current=10_000_000, day_offset=1))
        self.assertIsNone(s.gajian_bergeser)

    def test_gajian_lebih_awal_terbaca(self):
        b = SnapshotBuilder(date(2026, 10, 10))
        b.envelope("makan", "Makan")
        for p_s, _ in b.snap.periods[-4:-1]:   # masuk 4 hari sebelum tgl 1 → periode sebelumnya
            b.income(10_000_000, on=p_s - timedelta(days=4), alloc={"makan": 10_000_000})
        s, _ = run(b)
        self.assertEqual(s.gajian_bergeser["median_selisih"], -4)

    def test_belum_dijatah(self):
        b = SnapshotBuilder(TODAY)
        b.envelope("makan", "Makan")
        b.snap.now = at(12)
        b.income(1_000_000, on=TODAY - timedelta(days=2), alloc={"makan": 600_000},
                 created_at=at(9, day=TODAY - timedelta(days=2)), id="lama")
        b.income(500_000, on=TODAY, alloc={}, created_at=at(8), id="baru")          # < 24 jam
        b.income(1_005_000, on=TODAY - timedelta(days=3), alloc={"makan": 1_000_000},
                 created_at=at(9, day=TODAY - timedelta(days=3)), id="receh")      # ≤ Rp10 rb
        s, _ = run(b)
        self.assertEqual(s.belum_dijatah, [{"income_id": "lama", "sisa": D("400000")}])


class LupaCatatTests(unittest.TestCase):
    def _b(self, days_active, gap):
        b = base()
        last = TODAY - timedelta(days=gap)
        for i in range(days_active):
            b.txn("makan", 20_000, on=last - timedelta(days=i))
        b.snap.last_viewer_txn_date = last
        return b

    def test_lupa_catat(self):
        s, _ = run(self._b(12, 2))
        self.assertEqual(s.lupa_catat, {"hari_tanpa_catatan": 2, "hari_mencatat": 12})

    def test_jarang_mencatat_tidak(self):
        s, _ = run(self._b(8, 2))
        self.assertIsNone(s.lupa_catat)

    def test_baru_kemarin_tidak(self):
        s, _ = run(self._b(13, 1))
        self.assertIsNone(s.lupa_catat)


class DeterministikTests(unittest.TestCase):
    def test_sama_dua_kali(self):
        b = riwayat_builder(700_000, spent_now=900_000)
        snap = b.build()
        m = compute_metrics(snap)
        self.assertEqual(compute_signals(snap, m), compute_signals(snap, m))


if __name__ == "__main__":
    unittest.main()
