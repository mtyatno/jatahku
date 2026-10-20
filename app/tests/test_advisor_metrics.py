"""AI Advisor v2 — metrics.py (02-aturan.md §3, §12, §13). Fungsi murni, fixture tanpa DB.

Run: python -m unittest app.tests.test_advisor_metrics -v
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.services.advisor.metrics import (
    compute_metrics, floor100, horizons, is_emergency_name, weekly_occurrences,
)
from app.tests.advisor_v2_fixtures import LAST7, PARTNER, SnapshotBuilder, contoh_15_okt


class Contoh15OktTests(unittest.TestCase):
    """Angka §12 harus keluar persis."""

    def setUp(self):
        self.b = contoh_15_okt()
        self.m = compute_metrics(self.b.build())

    def test_periode(self):
        m = self.m
        self.assertEqual((m.period_start, m.period_end), (date(2026, 9, 27), date(2026, 10, 26)))
        self.assertEqual((m.hari_total, m.hari_ke, m.sisa_hari), (30, 19, 11))
        self.assertEqual((m.horizon, m.horizon_awal), (11, 12))

    def test_total_belanja(self):
        m = self.m
        self.assertEqual(m.dana_belanja, D("11285200"))      # T1: tabungan tidak ikut
        self.assertEqual(m.terpakai_belanja, D("8000000"))   # T2
        self.assertEqual(m.tagihan_sisa, D("1600000"))       # Σ M4
        self.assertEqual(m.sisa_bebas, D("1685200"))         # T3
        self.assertEqual(round(m.persen_dana * 100), 71)
        self.assertEqual(round(m.persen_waktu * 100), 63)

    def test_jatah(self):
        self.assertEqual(self.m.belanja_hari_ini, D("297100"))  # T5
        self.assertEqual(self.m.keluar_hari_ini, D("297100"))   # T5b
        self.assertEqual(self.m.j0, D("165100"))
        self.assertEqual(self.m.j1, D("153200"))

    def test_laju_proyeksi(self):
        api = self.m.to_api()
        self.assertEqual(api["laju7"], 201014)
        self.assertEqual(api["kekurangan"], 525957)
        self.assertEqual(api["proyeksi_akhir"], 11811157)
        self.assertEqual(api["tanggal_habis"], "2026-10-24")
        self.assertEqual(self.m.cukup_sampai, date(2026, 10, 23))

    def test_kpr_telat_9_hari(self):
        (kpr,) = self.m.tagihan
        self.assertEqual((kpr.sisa, kpr.telat_hari, kpr.lunas_oleh), (D("1600000"), 9, None))
        self.assertEqual(self.m.amplop["tagihan"].bebas, D("0"))

    def test_t4_sama_dengan_7_batang_terakhir(self):  # skenario 20
        last7 = [h["variabel"] for h in self.m.harian[-7:]]
        self.assertEqual(last7, [D(v) for v in LAST7])
        self.assertEqual(self.m.laju_total, sum(last7) / 7)
        self.assertEqual(self.m.harian[-1]["jatah"], self.m.j0)
        self.assertTrue(self.m.harian[-1]["lewat"])          # 297.100 > 165.100

    def test_porsi_7h_sama_dengan_t4(self):
        self.assertEqual(self.m.amplop["belanja"].porsi_7h, self.m.laju_total * 7)
        self.assertEqual(self.m.amplop["belanja"].porsi_7h_bagian, D("1"))

    def test_cakupan_darurat(self):
        self.assertEqual(self.m.amplop_darurat, ["darurat"])
        # belum ada riwayat → G7 = T1
        self.assertEqual(self.m.belanja_bulanan, D("11285200"))
        self.assertAlmostEqual(float(self.m.cakupan_darurat), 1_210_000 / 11_285_200, places=6)

    def test_kontrak_api(self):
        api = self.m.to_api()
        for key in ("dana_belanja", "terpakai", "tagihan_sisa", "sisa_bebas", "j0", "j1", "laju7",
                    "belanja_hari_ini", "proyeksi_akhir", "kekurangan", "tanggal_habis", "hari_ke",
                    "hari_total", "sisa_hari", "pemasukan_saya", "pemasukan_rumah_tangga", "harian"):
            self.assertIn(key, api)
        self.assertEqual(len(api["harian"]), 19)
        self.assertEqual(set(api["harian"][0]),
                         {"tanggal", "variabel", "tagihan", "penyesuaian", "outlier", "jatah", "lewat"})


class InvarianJ0Tests(unittest.TestCase):
    """Skenario 13: belanja, outlier, dan tagihan hari ini tidak mengubah J0; dana masuk dan
    penyesuaian cocokkan saldo hari ini (dua arah) mengubahnya (revisi 20 Okt 2026)."""

    def j0(self, mutate=None):
        b = contoh_15_okt()
        if mutate:
            mutate(b)
        return compute_metrics(b.build()).j0

    def test_outlier_hari_ini(self):
        self.assertEqual(self.j0(lambda b: b.txn("belanja", 5_000_000)), D("165100"))

    def test_penyesuaian_keluar_menurunkan(self):
        # Cocokkan saldo menemukan uang kurang Rp250 rb: (1.685.200 − 250.000 + 297.100) ÷ 12.
        self.assertEqual(self.j0(lambda b: b.txn("belanja", 250_000, desc="Tak tercatat", adjustment=True)),
                         D("144300"))

    def test_penyesuaian_masuk_menaikkan(self):
        # +300.000 ÷ 12 = +25.000
        self.assertEqual(self.j0(lambda b: b.income(300_000, on=b.snap.today, alloc={"belanja": 300_000},
                                                    adjustment=True)), D("190100"))

    def test_penyesuaian_besar_tidak_melebihi_saldo(self):
        # Kasus 20 Okt: cocokkan saldo memotong hampir semua sisa bebas. J0 tidak boleh lagi
        # dihitung dari saldo pagi (dulu ±4× jatah aman), jadi J0 ≤ (sisa bebas + belanja hari ini) ÷ H0.
        b = contoh_15_okt()
        b.txn("belanja", 1_500_000, desc="Penyesuaian saldo", adjustment=True)
        m = compute_metrics(b.build())
        self.assertEqual(m.j0, floor100((m.sisa_bebas + m.belanja_hari_ini) / m.horizon_awal))
        self.assertEqual(m.harian[-1]["jatah"], m.j0)

    def test_penyesuaian_hari_lalu_di_deret_harian(self):
        # Penyesuaian kemarin memotong jatah kemarin di grafik, sama dengan aturan hari ini.
        def jatah_kemarin(mutate=None):
            b = contoh_15_okt()
            if mutate:
                mutate(b)
            return compute_metrics(b.build()).harian[-2]["jatah"]
        kemarin = contoh_15_okt().snap.today - timedelta(days=1)
        self.assertLess(jatah_kemarin(lambda b: b.txn("belanja", 600_000, on=kemarin, desc="Penyesuaian",
                                                      adjustment=True)), jatah_kemarin())

    def test_bayar_tagihan_manual(self):
        self.assertEqual(self.j0(lambda b: b.txn("tagihan", 1_600_000, desc="bayar kpr")), D("165100"))

    def test_bayar_tagihan_lewat_tombol(self):
        def bayar(b):
            b.snap.recurring[0].next_run = date(2026, 11, 6)
            b.txn("tagihan", 1_600_000, desc="🔄 KPR Rumah")
        self.assertEqual(self.j0(bayar), D("165100"))

    def test_belanja_biasa(self):
        self.assertEqual(self.j0(lambda b: b.txn("belanja", 50_000)), D("165100"))

    def test_alokasi_hari_ini_mengubah(self):
        # +1.200.000 / 12 = +100.000
        self.assertEqual(self.j0(lambda b: b.fund("belanja", 1_200_000, on=b.snap.today)), D("265100"))

    def test_transfer_masuk_hari_ini_mengubah(self):
        self.assertEqual(self.j0(lambda b: b.transfer("darurat", "belanja", 120_000, on=b.snap.today)),
                         D("175100"))


class TagihanTests(unittest.TestCase):
    def test_dibayar_manual_nominal_persis(self):  # skenario 14
        b = contoh_15_okt()
        b.snap.recurring[0].next_run = date(2026, 10, 20)   # jatuh tempo periode ini, belum maju
        before = compute_metrics(b.build()).sisa_bebas
        tid = b.txn("tagihan", 1_600_000, desc="bayar kpr")
        m = compute_metrics(b.build())
        self.assertEqual(m.tagihan_sisa, D("0"))
        self.assertEqual(m.sisa_bebas, before)               # tidak dihitung ganda
        self.assertEqual(m.amplop["tagihan"].dibayar_manual,
                         [{"recurring_id": "kpr", "txn_id": tid, "jumlah": D("1600000")}])
        self.assertEqual(m.jenis_transaksi[tid], "tagihan")

    def test_nominal_mirip_tidak_melunasi(self):
        b = contoh_15_okt()
        b.snap.recurring[0].next_run = date(2026, 10, 20)
        b.txn("tagihan", 1_599_000)
        self.assertEqual(compute_metrics(b.build()).tagihan_sisa, D("1600000"))

    def test_telat_dari_periode_lalu_tidak_dicocokkan(self):
        b = contoh_15_okt()
        b.snap.recurring[0].next_run = date(2026, 9, 6)
        b.txn("tagihan", 1_600_000)
        self.assertEqual(compute_metrics(b.build()).tagihan_sisa, D("1600000"))

    def test_bayar_lewat_tombol_tidak_melunasi_tagihan_lain(self):
        b = contoh_15_okt()
        b.snap.recurring[0].next_run = date(2026, 11, 6)       # KPR sudah dibayar lewat Bayar
        b.txn("tagihan", 1_600_000, desc="🔄 KPR Rumah")
        b.recurring("tagihan", 1_600_000, "Sewa Gudang", date(2026, 10, 20), id="gudang")
        m = compute_metrics(b.build())
        by_id = {x.recurring_id: x for x in m.tagihan}
        self.assertEqual(by_id["kpr"].lunas_oleh, "bayar")
        self.assertEqual(by_id["gudang"].sisa, D("1600000"))
        self.assertEqual(m.amplop["tagihan"].dibayar_manual, [])

    def test_mingguan_dan_tahunan(self):
        b = contoh_15_okt()
        b.recurring("belanja", 100_000, "Galon", date(2026, 10, 16), frequency="weekly")
        b.recurring("belanja", 1_200_000, "Asuransi", date(2027, 3, 1), frequency="yearly")
        m = compute_metrics(b.build())
        # mingguan: 16, 23 Okt (≤ 26 Okt) → 2×; tahunan: 1.200.000 / 12
        self.assertEqual(m.amplop["belanja"].tagihan_sisa, D("200000"))
        self.assertEqual(m.amplop["belanja"].sisihan, D("100000"))
        self.assertEqual(m.sisa_bebas, D("1685200") - D("300000"))

    def test_pembayaran_langganan_bukan_laju(self):  # skenario 4
        b = SnapshotBuilder(date(2026, 10, 10))
        b.envelope("rumah", "Rumah")
        b.fund("rumah", 3_000_000)
        b.recurring("rumah", 1_500_000, "Sewa", date(2026, 11, 1))
        b.txn("rumah", 1_500_000, on=date(2026, 10, 1), desc="🔄 Sewa")
        b.txn("rumah", 1_480_000, on=date(2026, 10, 2), desc="sewa parkir+listrik")  # ±10% → tagihan
        for day in range(3, 11):
            b.txn("rumah", 20_000, on=date(2026, 10, day))
        m = compute_metrics(b.build())
        self.assertEqual(m.laju_total, D("20000"))      # 4–10 Okt × 20.000 ÷ 7


class HorizonTests(unittest.TestCase):
    def test_horizons(self):  # skenario 8
        self.assertEqual(horizons("monthly", 11), (11, 12))
        self.assertEqual(horizons("irregular", 11), (11, 12))
        self.assertEqual(horizons("daily", 11), (1, 1))
        self.assertEqual(horizons("weekly", 11), (7, 7))
        self.assertEqual(horizons("weekly", 3), (3, 4))
        self.assertEqual(horizons("daily", 0), (0, 1))

    def test_pendapatan_harian(self):
        b = contoh_15_okt()
        b.snap.income_type = "daily"
        m = compute_metrics(b.build())
        self.assertEqual(m.j0, floor100(D("1685200") + D("297100")))
        self.assertEqual(m.j1, D("1685200"))

    def test_hari_terakhir_tidak_crash(self):  # skenario 6
        b = SnapshotBuilder(date(2026, 10, 31))
        b.envelope("makan")
        b.fund("makan", 1_000_000)
        b.txn("makan", 30_000, on=date(2026, 10, 3))
        b.txn("makan", 70_000)
        m = compute_metrics(b.build())
        self.assertEqual(m.sisa_hari, 0)
        self.assertIsNone(m.j1)
        self.assertEqual(m.j0, D("970000"))                  # J0 = T3 + T5
        self.assertEqual(m.kekurangan, D("0"))

    def test_hari_1_2_tanpa_proyeksi(self):  # skenario 2
        b = SnapshotBuilder(date(2026, 10, 2))
        b.envelope("makan")
        b.fund("makan", 1_000_000)
        b.txn("makan", 400_000)
        m = compute_metrics(b.build())
        self.assertFalse(m.proyeksi_valid)
        self.assertIsNone(m.amplop["makan"].laju)
        self.assertIsNone(m.proyeksi_akhir)
        self.assertIsNone(m.kekurangan)
        self.assertIsNone(m.tanggal_habis)

    def test_jendela_kurang_dari_7_hari_pakai_rata_rata_periode(self):
        b = SnapshotBuilder(date(2026, 10, 4))
        b.envelope("makan")
        b.fund("makan", 1_000_000)
        b.txn("makan", 40_000, on=date(2026, 9, 30))           # periode lalu, tidak ikut
        b.txn("makan", 60_000, on=date(2026, 10, 2))
        m = compute_metrics(b.build())
        self.assertEqual(m.laju_total, D("15000"))           # 60.000 ÷ 4

    def test_jendela_7_hari_jarang_belanja_fallback(self):
        b = SnapshotBuilder(date(2026, 10, 20))
        b.envelope("makan")
        b.fund("makan", 2_000_000)
        b.txn("makan", 200_000, on=date(2026, 10, 1))
        b.txn("makan", 100_000, on=date(2026, 10, 18))         # hanya 1 hari di jendela
        self.assertEqual(compute_metrics(b.build()).laju_total, D("300000") / 20)


class JenisTransaksiTests(unittest.TestCase):
    def test_outlier_tidak_masuk_laju_tapi_masuk_t5b(self):  # skenario 3
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan")
        b.fund("makan", 3_000_000)
        for day in range(1, 15):
            b.txn("makan", 50_000, on=date(2026, 10, day))
        big = b.txn("makan", 1_200_000)
        m = compute_metrics(b.build())
        self.assertEqual(m.jenis_transaksi[big], "outlier")
        self.assertEqual(m.belanja_hari_ini, D("0"))
        self.assertEqual(m.keluar_hari_ini, D("1200000"))
        self.assertEqual(m.laju_total, D("50000") * 6 / 7)
        self.assertEqual(m.harian[-1]["outlier"], D("1200000"))

    def test_penyesuaian_tidak_masuk_laju(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan")
        b.fund("makan", 3_000_000)
        adj = b.txn("makan", 300_000, adjustment=True)
        m = compute_metrics(b.build())
        self.assertEqual(m.jenis_transaksi[adj], "penyesuaian")
        self.assertEqual(m.belanja_hari_ini, D("0"))
        self.assertEqual(m.terpakai_belanja, D("300000"))    # M2 tetap menghitungnya


class KelompokTests(unittest.TestCase):
    def test_belanja_expense_debt_tabungan_tidak(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan").envelope("cicilan", purpose="debt")
        b.envelope("tab", purpose="saving").envelope("sf", purpose="sinking_fund")
        b.income(4_000_000, alloc={"makan": 1_000_000, "cicilan": 1_000_000, "tab": 1_000_000, "sf": 1_000_000})
        m = compute_metrics(b.build())
        self.assertEqual(m.dana_belanja, D("2000000"))
        self.assertEqual(m.amplop["tab"].kelompok, "tabungan")
        self.assertEqual(m.amplop["cicilan"].kelompok, "belanja")

    def test_kebutuhan_default_needs(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("a").envelope("b", classification="wants").envelope("c", classification="needs")
        m = compute_metrics(b.build())
        self.assertEqual([m.amplop[x].kebutuhan for x in "abc"], [True, False, True])

    def test_rollover_hanya_bila_is_rollover(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("roll", is_rollover=True).envelope("reset", is_rollover=False)
        b.snap.rollover[("roll", 2026, 9)] = D("50000")
        b.snap.rollover[("reset", 2026, 9)] = D("70000")
        m = compute_metrics(b.build())
        self.assertEqual(m.amplop["roll"].dana, D("50000"))
        self.assertEqual(m.amplop["reset"].dana, D("0"))


class PerAmplopTests(unittest.TestCase):
    def test_tambalan_dari_semua_anggota(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("transport").envelope("pakaian").envelope("hiburan")
        b.income(3_000_000, alloc={"transport": 100_000, "pakaian": 1_000_000, "hiburan": 1_000_000})
        b.transfer("pakaian", "transport", 200_000, on=date(2026, 10, 5))
        b.transfer("hiburan", "transport", 100_000, on=date(2026, 10, 8), user=PARTNER)
        b.income(0, on=date(2026, 10, 9), user=PARTNER, alloc={None: -50_000, "transport": 50_000})
        m = compute_metrics(b.build()).amplop["transport"]
        self.assertEqual((m.tambalan_n, m.tambalan_total), (3, D("350000")))
        self.assertEqual(m.tambalan_sumber, {"pakaian": D("200000"), "hiburan": D("100000"), None: D("50000")})
        self.assertEqual(m.dana, D("450000"))

    def test_laju_butuh_surplus(self):
        b = SnapshotBuilder(date(2026, 10, 21))              # d = 21, r = 10
        b.envelope("makan")
        b.fund("makan", 2_000_000)
        for day in range(15, 22):
            b.txn("makan", 70_000, on=date(2026, 10, day))
        m = compute_metrics(b.build()).amplop["makan"]
        self.assertEqual(m.laju, D("70000"))
        self.assertEqual(m.bebas, D("1510000"))
        self.assertEqual(m.butuh_sisa, D("700000"))
        self.assertEqual(m.surplus, D("1510000") - D("770000"))


class PemasukanTests(unittest.TestCase):
    def test_dicatat_pasangan(self):  # skenario 5
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan").envelope("rahasia", owner_id=PARTNER)
        b.income(7_500_000, user=PARTNER, alloc={"makan": 2_000_000, None: 5_000_000})
        m = compute_metrics(b.build())
        self.assertEqual(m.pemasukan_saya, D("0"))
        self.assertEqual(m.pemasukan_rumah_tangga, D("7500000"))
        self.assertEqual(m.pemasukan_per_anggota_bersama, {PARTNER: D("2000000")})

    def test_transfer_dan_penyesuaian_bukan_pemasukan(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("a").envelope("b")
        b.fund("a", 1_000_000)
        b.transfer("a", "b", 100_000)
        b.income(50_000, alloc={"a": 50_000}, adjustment=True)
        m = compute_metrics(b.build())
        self.assertEqual(m.pemasukan_saya, D("1000000"))

    def test_belum_dijatah(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("a")
        iid = b.income(1_000_000, alloc={"a": 700_000})
        b.income(500_000, user=PARTNER)                       # milik anggota lain: tidak dihitung
        m = compute_metrics(b.build())
        self.assertEqual(m.belum_dijatah, D("300000"))
        self.assertEqual(m.belum_dijatah_rincian[0]["income_id"], iid)

    def test_pemasukan_biasa_dan_hari_biasa(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("a")
        b.income(5_000_000, on=date(2026, 7, 3))
        b.income(6_000_000, on=date(2026, 8, 5))
        b.income(200_000, on=date(2026, 8, 20))
        b.income(7_000_000, on=date(2026, 9, 4))
        m = compute_metrics(b.build())
        self.assertEqual(m.pemasukan_biasa, D("6200000"))     # median(5 jt, 6,2 jt, 7 jt)
        self.assertEqual(m.hari_biasa_masuk, 3)               # median(2, 4, 3)

    def test_saving_rate(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("a").envelope("tab", purpose="saving")
        b.income(4_000_000, alloc={"a": 3_000_000, "tab": 1_000_000})
        b.income(4_000_000, user=PARTNER, alloc={"a": 4_000_000})
        b.transfer("a", "tab", 500_000)                       # bukan dari P1
        m = compute_metrics(b.build())
        self.assertEqual(m.saving_rate, D("0.25"))
        self.assertEqual(m.saving_rate_rumah_tangga, D("0.125"))


class TabunganTests(unittest.TestCase):
    def test_target_dan_setoran(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("hp", purpose="saving").envelope("liburan", purpose="saving")
        for month in (7, 8, 9):
            b.fund("hp", 500_000, on=date(2026, month, 2))
        b.fund("hp", 300_000, on=date(2026, 10, 2))
        b.lifetime("hp", 2_000_000).lifetime("liburan", 0)
        b.goal("hp", "HP baru", 5_000_000, target_date=date(2027, 4, 1))
        b.goal("liburan", "Liburan", 2_400_000)
        m = compute_metrics(b.build())
        self.assertEqual(m.setoran["hp"][-4:], [D("500000")] * 3 + [D("300000")])
        self.assertEqual(m.setoran_biasa["hp"], D("500000"))
        hp, liburan = m.target
        self.assertEqual(hp["progres"], D("0.4"))
        self.assertEqual(hp["butuh_per_bulan"], D("500000"))   # 3 jt ÷ 6 bulan
        self.assertEqual(hp["perkiraan_bulan"], D("6"))
        self.assertTrue(liburan["tanpa_tenggat"])
        self.assertEqual(liburan["butuh_per_bulan"], D("100000"))  # 2,4 jt ÷ 24
        self.assertIsNone(liburan["perkiraan_bulan"])

    def test_belanja_bulanan_median_riwayat(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan").envelope("dd", "Dana Darurat", purpose="saving", is_emergency=True)
        for month, amt in ((7, 3_000_000), (8, 4_000_000), (9, 5_000_000)):
            b.txn("makan", amt, on=date(2026, month, 10))
        b.lifetime("dd", 8_000_000)
        m = compute_metrics(b.build())
        self.assertEqual(m.belanja_bulanan, D("4000000"))
        self.assertEqual(m.cakupan_darurat, D("2"))

    def test_tanpa_amplop_darurat(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("tab", "Tabungan Darurat", purpose="saving")  # nama saja tidak cukup: ikut flag
        self.assertIsNone(compute_metrics(b.build()).cakupan_darurat)


class LainLainTests(unittest.TestCase):
    def test_k1_k4(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        b.envelope("makan").envelope("tab", purpose="saving")
        b.fund("makan", 2_000_000)
        b.recurring("makan", 300_000, "Internet", date(2026, 10, 20))
        b.recurring("makan", 1_200_000, "Asuransi", date(2027, 1, 1), frequency="yearly")
        b.recurring("tab", 999_000, "Bukan belanja", date(2026, 10, 20))
        b.balance_check(date(2026, 9, 25), -150_000)
        b.snap.last_viewer_txn_date = date(2026, 10, 12)
        m = compute_metrics(b.build())
        self.assertEqual((m.hari_sejak_cocokkan, m.selisih_terakhir), (20, D("-150000")))
        self.assertEqual(m.hari_tanpa_catatan, 3)
        self.assertEqual(m.beban_tagihan, D("400000") / D("2000000"))

    def test_snapshot_kosong(self):
        b = SnapshotBuilder(date(2026, 10, 15))
        m = compute_metrics(b.build())
        self.assertEqual(m.sisa_bebas, D("0"))
        self.assertIsNone(m.persen_dana)
        self.assertIsNone(m.beban_tagihan)
        self.assertEqual(m.j0, D("0"))


class PembantuTests(unittest.TestCase):
    def test_floor100(self):
        self.assertEqual(floor100(D("165191.66")), D("165100"))
        self.assertEqual(floor100(D("-50")), D("-100"))

    def test_weekly_occurrences(self):
        self.assertEqual(weekly_occurrences(date(2026, 10, 16), date(2026, 10, 26)), 2)
        self.assertEqual(weekly_occurrences(date(2026, 10, 27), date(2026, 10, 26)), 0)
        self.assertEqual(weekly_occurrences(date(2026, 10, 26), date(2026, 10, 26)), 1)

    def test_is_emergency_name(self):
        self.assertTrue(is_emergency_name("Dana Darurat"))
        self.assertTrue(is_emergency_name("Emergency Fund"))
        self.assertFalse(is_emergency_name("Tabungan"))
        self.assertFalse(is_emergency_name(None))


class DeterministikTests(unittest.TestCase):
    def test_snapshot_sama_hasil_sama(self):
        a = compute_metrics(contoh_15_okt().build()).to_api()
        b = compute_metrics(contoh_15_okt().build()).to_api()
        self.assertEqual(a, b)

    def test_urutan_transaksi_tidak_mempengaruhi(self):
        b = contoh_15_okt()
        b.snap.transactions.reverse()
        self.assertEqual(compute_metrics(b.build()).to_api(), compute_metrics(contoh_15_okt().build()).to_api())


if __name__ == "__main__":
    unittest.main()
