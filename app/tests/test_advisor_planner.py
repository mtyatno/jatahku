"""AI Advisor v2 — perencana dana planner.py (02-aturan.md §8, §12, §13 skenario 10 & 18).
Fungsi murni, fixture tanpa DB.

Run: python -m unittest app.tests.test_advisor_planner -v
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.services.advisor.metrics import batas_harian, belanja_sisa_riwayat, compute_metrics
from app.services.advisor.planner import (
    PlanInputError, bebas_setelah_rencana, batas_harian_setelah_rencana, saldo_versi, susun_rencana,
)
from app.tests.advisor_v2_fixtures import PARTNER, SnapshotBuilder, contoh_15_okt

KPR = 2_008_174


def contoh_rencana_kpr() -> SnapshotBuilder:
    """§12 'Rencana dana KPR': Pakaian (keinginan), Pendidikan & Kebutuhan Rumah (kebutuhan tanpa riwayat)."""
    b = contoh_15_okt()
    b.envelope("pakaian", "Pakaian", classification="wants")
    b.envelope("pendidikan", "Pendidikan", classification="needs")
    b.envelope("rumah", "Kebutuhan Rumah", classification="needs")
    b.fund("pakaian", 503_001)
    b.fund("pendidikan", 1_410_500)
    b.fund("rumah", 300_000)
    # 30.001 di 2 hari awal → < 3 hari berbelanja di 7 hari terakhir → laju = 30.001 ÷ 19 = 1.579
    b.txn("pakaian", 15_000, on=b.ps + timedelta(days=1))
    b.txn("pakaian", 15_001, on=b.ps + timedelta(days=2))
    return b


def plan(b, kebutuhan, **kw):
    snap = b.build()
    m = compute_metrics(snap)
    return snap, m, susun_rencana(snap, m, kebutuhan, **kw)


def rows(r):
    return [(x.dari_id, x.tingkat, x.jumlah, x.tercentang) for x in r.baris]


class Contoh12Tests(unittest.TestCase):
    def setUp(self):
        self.snap, self.m, self.r = plan(
            contoh_rencana_kpr(), [{"tujuan_id": "tagihan", "jumlah": KPR, "bayar_recurring_id": "kpr"}])

    def test_surplus_pakaian_sesuai_spesifikasi(self):
        a = self.m.amplop["pakaian"]
        self.assertEqual(a.bebas, D("473000"))
        self.assertEqual(a.laju, D("30001") / 19)
        self.assertEqual(int(a.surplus), 453_894)   # 473.000 − 1.579 × 11 × 1,1

    def test_rencana_persis_contoh(self):
        self.assertEqual(rows(self.r), [
            ("pakaian", "a", D("453000"), True),       # dibulatkan ke bawah ke Rp1.000
            ("pendidikan", "c", D("1410000"), True),   # cek dulu, tercentang karena danger
            ("rumah", "c", D("145174"), True),         # sumber terakhir menutup persis
        ])
        self.assertEqual(self.r.kurang, 0)
        self.assertEqual(self.r.bayar, [{"recurring_id": "kpr", "jumlah": D("1600000")}])

    def test_tabungan_tidak_otomatis_dan_bukan_opsi_saat_cukup(self):
        self.assertNotIn("darurat", {x.dari_id for x in self.r.baris})
        self.assertEqual(self.r.opsi_tabungan, [])

    def test_to_api_bentuk_kontrak(self):
        api = self.r.to_api(saldo_versi(self.snap, self.m))
        self.assertEqual(set(api), {"rencana", "kurang", "bayar", "saldo_versi", "kebutuhan",
                                    "kecuali", "sertakan", "opsi_tabungan"})
        row = api["rencana"][0]
        self.assertEqual(row["dari_nama"], "Pakaian")
        self.assertEqual(row["jumlah"], 453000)
        self.assertEqual(row["ke"], [{"tujuan_id": "tagihan", "tujuan_nama": "Tagihan & Cicilan", "jumlah": 453000}])
        self.assertIn("Rp453.894", row["alasan"])
        self.assertEqual(sum(x["jumlah"] for x in api["rencana"]), KPR)
        self.assertEqual(api["kebutuhan"], [{"tujuan_id": "tagihan", "jumlah": KPR, "bayar_recurring_id": "kpr"}])
        self.assertEqual(len({x["dari_id"] for x in api["rencana"]}), len(api["rencana"]))  # satu baris per sumber

    def test_kecuali_menghitung_ulang_tanpa_sumber(self):
        _, _, r = plan(contoh_rencana_kpr(), [{"tujuan_id": "tagihan", "jumlah": KPR, "bayar_recurring_id": "kpr"}],
                       kecuali=["pakaian"])
        self.assertEqual(rows(r), [
            ("pendidikan", "c", D("1410000"), True),
            ("rumah", "c", D("300000"), True),
        ])
        self.assertEqual(r.kurang, D(KPR - 1_710_000))
        self.assertEqual(r.bayar, [])  # belum tertutup penuh → tidak dibayar
        self.assertEqual([o["amplop_id"] for o in r.opsi_tabungan], ["darurat"])
        self.assertTrue(r.opsi_tabungan[0]["darurat"])


class SumberTests(unittest.TestCase):
    """Skenario 10: terkunci, milik anggota lain, punya tagihan → bukan sumber; tabungan tidak otomatis."""

    def builder(self):
        b = SnapshotBuilder(date(2026, 10, 15), payday_day=1)
        b.envelope("makan", "Makan", classification="needs")
        b.envelope("hobi", "Hobi", classification="wants", is_locked=True)
        b.envelope("rahasia", "Rahasia Rina", classification="wants", owner_id=PARTNER)
        b.envelope("netflix", "Hiburan", classification="wants")
        b.envelope("jajan", "Jajan Saya", classification="wants", owner_id="u-saya")
        b.envelope("tabungan", "Tabungan", purpose="saving")
        b.envelope("darurat", "Dana Darurat", purpose="saving", is_emergency=True)
        for eid in ("hobi", "rahasia", "netflix", "jajan", "tabungan", "darurat"):
            b.fund(eid, 1_000_000)
        b.fund("makan", 100_000)
        b.txn("makan", 150_000, on=date(2026, 10, 3))   # makan minus 50.000
        b.recurring("netflix", 186_000, "Netflix", date(2026, 10, 20))
        return b

    def test_sumber_terlarang_tidak_dipakai(self):
        _, _, r = plan(self.builder(), [{"tujuan_id": "makan", "jumlah": 50_000}])
        self.assertEqual(rows(r), [("jajan", "a", D("50000"), True)])
        self.assertEqual(r.kurang, 0)

    def test_tabungan_hanya_bila_dipilih(self):
        b = self.builder()
        b.snap.envelopes = [e for e in b.snap.envelopes if e.id != "jajan"]
        _, _, r = plan(b, [{"tujuan_id": "makan", "jumlah": 50_000}])
        self.assertEqual(r.baris, [])
        self.assertEqual(r.kurang, D("50000"))
        self.assertEqual([(o["amplop_id"], o["darurat"]) for o in r.opsi_tabungan],
                         [("tabungan", False), ("darurat", True)])   # tabungan umum dulu, darurat terakhir
        _, _, r = plan(b, [{"tujuan_id": "makan", "jumlah": 50_000}], sertakan=["darurat"])
        self.assertEqual(rows(r), [("darurat", "e", D("50000"), True)])
        self.assertEqual(r.sertakan, ["darurat"])

    def test_c_tidak_tercentang_untuk_kebutuhan_non_danger(self):
        b = SnapshotBuilder(date(2026, 10, 15), payday_day=1)
        b.envelope("transport", "Transport", classification="needs")
        b.envelope("rumah", "Kebutuhan Rumah", classification="needs")
        b.fund("transport", 100_000)
        b.fund("rumah", 500_000)
        _, _, r = plan(b, [{"tujuan_id": "transport", "jumlah": 200_000}])
        self.assertEqual(rows(r), [("rumah", "c", D("200000"), False)])
        self.assertEqual(r.kurang, D("200000"))

    def test_kebutuhan_tidak_sah(self):
        b = self.builder()
        with self.assertRaises(PlanInputError):
            plan(b, [{"tujuan_id": "rahasia-lain", "jumlah": 1000}])
        with self.assertRaises(PlanInputError):
            plan(b, [{"tujuan_id": "makan", "jumlah": 0}])
        rec = b.snap.recurring[0].id
        with self.assertRaises(PlanInputError):  # langganan di amplop lain
            plan(b, [{"tujuan_id": "makan", "jumlah": 1000, "bayar_recurring_id": rec}])


class AlokasiTests(unittest.TestCase):
    def test_global_minus_didahulukan_dan_sumber_dibagi(self):
        b = SnapshotBuilder(date(2026, 10, 15), payday_day=1)
        b.envelope("makan", "Makan")
        b.envelope("transport", "Transport")
        b.envelope("hobi", "Hobi", classification="wants")
        b.fund("makan", 100_000)
        b.txn("makan", 130_000, on=date(2026, 10, 2))     # minus 30.000
        b.fund("transport", 50_000)
        b.fund("hobi", 70_500)
        _, _, r = plan(b, [{"tujuan_id": "transport", "jumlah": 60_000},
                           {"tujuan_id": "makan", "jumlah": 30_000}])
        self.assertEqual([k.tujuan_id for k in r.kebutuhan], ["makan", "transport"])
        hobi = r.baris[0]
        self.assertEqual(hobi.ke, {"makan": D("30000"), "transport": D("40000")})  # 40.500 → 40.000
        self.assertEqual(r.kurang, D("20000"))

    def test_tingkat_b_memakai_median_riwayat(self):
        b = SnapshotBuilder(date(2026, 10, 15), payday_day=1)
        b.envelope("makan", "Makan", classification="needs")
        b.envelope("transport", "Transport", classification="needs")
        b.fund("makan", 1_000_000, on=date(2026, 9, 1))
        for day in (16, 18, 20, 22):                      # sesudah hari ke-15 periode lalu
            b.txn("makan", 100_000, on=date(2026, 9, day))
        b.fund("makan", 500_000)
        b.txn("makan", 9_500, on=date(2026, 10, 1))
        b.txn("makan", 9_500, on=date(2026, 10, 2))
        b.fund("transport", 10_000)
        snap = b.build()
        m = compute_metrics(snap)
        self.assertEqual(belanja_sisa_riwayat(snap, m, "makan"), D("400000"))
        r = susun_rencana(snap, m, [{"tujuan_id": "transport", "jumlah": 100_000}])
        self.assertEqual(rows(r), [("makan", "b", D("41000"), True)])  # 481.000 − 400.000 × 1,1
        self.assertGreater(m.amplop["makan"].surplus, D("41000"))       # M10 saja jauh lebih besar

    def test_awal_periode_tanpa_laju_tetap_bisa_direncanakan(self):
        b = SnapshotBuilder(date(2026, 10, 2), payday_day=1)
        b.envelope("hobi", "Hobi", classification="wants", budget_amount=D("200000"))
        b.envelope("pas", "Pas", classification="wants", budget_amount=D("0"))
        b.envelope("makan", "Makan")
        b.fund("hobi", 310_000)
        b.fund("pas", 310_000)
        b.fund("makan", 10_000)
        _, m, r = plan(b, [{"tujuan_id": "makan", "jumlah": 150_000}])
        self.assertIsNone(m.amplop["hobi"].laju)
        # perkiraan belanja = jatah × r ÷ D = 200.000 × 29 ÷ 31; surplus = 310.000 − itu × 1,1 = 104.193
        # "pas": tanpa jatah → dana × r ÷ D × 1,1 > dana → bukan sumber
        self.assertEqual(rows(r), [("hobi", "a", D("104000"), True)])
        self.assertEqual(r.kurang, D("46000"))


class BebasSetelahRencanaTests(unittest.TestCase):
    """Skenario 18: amplop yang dipakai sumber → batas hariannya turun."""

    def test_batas_harian_turun_untuk_sumber(self):
        snap, m, r = plan(contoh_rencana_kpr(), [{"tujuan_id": "tagihan", "jumlah": KPR, "bayar_recurring_id": "kpr"}])
        bebas = bebas_setelah_rencana(m, r)
        self.assertEqual(bebas["pakaian"], D("20000"))
        self.assertEqual(batas_harian(m.amplop["pakaian"].bebas, m), D("43000"))   # tanpa rencana
        batas = batas_harian_setelah_rencana(m, r)
        self.assertEqual(batas["pakaian"], D("1800"))                              # floor100(20.000 ÷ 11)
        self.assertEqual(batas["belanja"], batas_harian(m.amplop["belanja"].bebas, m))  # bukan sumber: tetap
        self.assertEqual(bebas_setelah_rencana(m, None)["pakaian"], D("473000"))

    def test_sumber_tidak_tercentang_tidak_mengurangi(self):
        b = SnapshotBuilder(date(2026, 10, 15), payday_day=1)
        b.envelope("transport", "Transport")
        b.envelope("rumah", "Rumah")
        b.fund("transport", 100_000)
        b.fund("rumah", 500_000)
        _, m, r = plan(b, [{"tujuan_id": "transport", "jumlah": 200_000}])
        self.assertEqual(bebas_setelah_rencana(m, r)["rumah"], D("500000"))


class SaldoVersiTests(unittest.TestCase):
    def test_berubah_bila_saldo_berubah(self):
        b = contoh_rencana_kpr()
        snap = b.build()
        v1 = saldo_versi(snap, compute_metrics(snap))
        self.assertEqual(v1, saldo_versi(snap, compute_metrics(snap)))
        b.txn("pakaian", 1_000)
        self.assertNotEqual(v1, saldo_versi(snap, compute_metrics(snap)))

    def test_berubah_bila_amplop_dikunci(self):
        snap = contoh_rencana_kpr().build()
        v1 = saldo_versi(snap, compute_metrics(snap))
        next(e for e in snap.envelopes if e.id == "pakaian").is_locked = True
        self.assertNotEqual(v1, saldo_versi(snap, compute_metrics(snap)))


if __name__ == "__main__":
    unittest.main()
