"""Plugin U5 — Catat cepat versi usaha dan AI Advisor (03-workflow.md baris U5; 04-kontrak-api.md §3 "Catat cepat",
§5 "Deteksi catatan", §6 "Saran AI Advisor"; AGENTS.md "Plugin dan ruang" aturan 3, 4, 6, 7, 8; ADR-P3, P5, P14).

1. Angka aturan BU-* (`buku_usaha/metrics.py`): kebutuhan dua minggu, kas cukup berapa hari, bulan prive.
2. Aturan BU-01/02/03 (`buku_usaha/aturan.py`): fungsi murni angka → `Saran`, teks dari templat.
3. Saran lewat host: pemilik mendapatnya dari data nyata, karyawan dan ruang lain tidak; paling banyak satu saran
   Buku Usaha di kartu AI Advisor.

Run: python -m unittest app.tests.test_plugin_u5 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.plugins.buku_usaha import aturan, metrics
from app.plugins.host import titik
from app.plugins.sdk import AmplopView, Saran

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    from app.models.models import AppSetting
    from app.tests import test_plugin_u4 as u4


def A(nama, sisa, *, pribadi=False, tujuan="saving"):
    return AmplopView(id=nama, nama=nama, emoji="", tujuan=tujuan, anggaran=D(0), pribadi=pribadi, dikunci=False,
                      sisa=None if sisa is None else D(sisa))


def LR(*, periode="2026-10", omzet="0", laba="0", prive="0", omzet_lalu="0", banding="2026-09"):
    """Bagian jawaban `metrics.laba_rugi` yang dibaca aturan."""
    return {"periode": periode, "omzet": D(omzet), "laba": D(laba),
            "di_luar_laba_rugi": [{"jenis": "prive", "jumlah": D(prive), "banyak": 1},
                                  {"jenis": "modal", "jumlah": D(0), "banyak": 0}],
            "banding": {"periode": banding, "omzet": D(omzet_lalu)}}


# ── 1. angka ─────────────────────────────────────────────────────────────
class AngkaAturanTests(unittest.TestCase):
    def test_kebutuhan_dua_minggu_dari_rata_rata_28_hari(self):
        k = metrics.kebutuhan(D("28000000"))
        self.assertEqual(k, {"harian": D("1000000.00"), "jumlah": D("14000000")})
        # Data contoh A3: beban ±Rp36,3 jt sebulan → kebutuhan dua minggu ±Rp16,39 jt.
        self.assertEqual(metrics.kebutuhan(D("32780000"))["jumlah"], D("16390000"))

    def test_tanpa_pengeluaran_tidak_ada_kebutuhan(self):
        self.assertEqual(metrics.kebutuhan(D(0)), {"harian": D("0.00"), "jumlah": D(0)})

    def test_kas_cukup_berapa_hari_dibulatkan_ke_bawah(self):
        harian = metrics.kebutuhan(D("32780000"))["harian"]
        self.assertEqual(metrics.cukup_hari(D("13755000"), harian), 11)      # A3: "cukup ±11 hari"
        self.assertEqual(metrics.cukup_hari(D("-5000"), harian), 0)
        self.assertEqual(metrics.cukup_hari(D(0), harian), 0)
        self.assertIsNone(metrics.cukup_hari(D("13755000"), D(0)))

    def test_jendela_kebutuhan_28_hari_sampai_kemarin(self):
        self.assertEqual(metrics.jendela_kebutuhan(date(2026, 11, 12)), (date(2026, 10, 15), date(2026, 11, 11)))

    def test_bulan_prive_awal_bulan_memakai_bulan_lalu(self):
        self.assertEqual(metrics.bulan_prive(date(2026, 11, 14)), (2026, 10))
        self.assertEqual(metrics.bulan_prive(date(2026, 11, 15)), (2026, 11))
        self.assertEqual(metrics.bulan_prive(date(2027, 1, 3)), (2026, 12))

    def test_amplop_pajak_hanya_amplop_bersama_bernama_pajak(self):
        pajak = A(" pajak ", "0")
        self.assertIs(metrics.amplop_pajak([A("Bahan", "5"), pajak]), pajak)
        self.assertIsNone(metrics.amplop_pajak([A("Pajak", "0", pribadi=True), A("Pajak kendaraan", "0")]))


# ── 2. aturan murni ──────────────────────────────────────────────────────
class Bu01Tests(unittest.TestCase):
    def test_kas_di_bawah_kebutuhan_dua_minggu(self):
        (s,) = aturan.bu01({"jumlah": D("13755000")}, {"jumlah": D("32780000"), "banyak": 40})
        self.assertIsInstance(s, Saran)
        self.assertEqual((s.entitas, s.tone, s.keyakinan), ("kas", "warn", "tinggi"))
        self.assertEqual(s.judul, "Kas usaha cukup ±11 hari")
        self.assertEqual(s.isi, "Kas Rp13.755.000, sedangkan kebutuhan dua minggu sekitar Rp16.390.000 "
                                "(rata-rata pengeluaran 28 hari terakhir).")
        self.assertEqual(s.fakta, (("Kas usaha", "Rp13.755.000"), ("Kebutuhan 2 minggu", "Rp16.390.000")))
        self.assertEqual(s.rupiah, D("2635000"))
        self.assertEqual([(a.label, a.ke) for a in s.aksi], [("Lihat laba rugi", "/p/buku_usaha/laba-rugi")])
        self.assertTrue(D(0) <= s.urgensi <= D(1))

    def test_kas_cukup_tidak_ada_saran(self):
        self.assertEqual(aturan.bu01({"jumlah": D("16390000")}, {"jumlah": D("32780000"), "banyak": 40}), [])

    def test_belum_ada_pengeluaran_tidak_ada_saran(self):
        self.assertEqual(aturan.bu01({"jumlah": D(0)}, {"jumlah": D(0), "banyak": 0}), [])

    def test_kurang_dari_seminggu_merah(self):
        (s,) = aturan.bu01({"jumlah": D("3000000")}, {"jumlah": D("28000000"), "banyak": 40})
        self.assertEqual((s.tone, s.judul), ("danger", "Kas usaha cukup ±3 hari"))

    def test_kas_habis(self):
        (s,) = aturan.bu01({"jumlah": D("-250000")}, {"jumlah": D("28000000"), "banyak": 40})
        self.assertEqual((s.tone, s.judul), ("danger", "Kas usaha habis"))
        self.assertEqual(s.rupiah, D("14000000"))                 # kekurangan dihitung dari kas 0, bukan kas minus
        self.assertEqual(s.urgensi, D(1))

    def test_catatan_masih_sedikit_keyakinan_sedang(self):
        (s,) = aturan.bu01({"jumlah": D("100000")}, {"jumlah": D("2800000"), "banyak": 3})
        self.assertEqual(s.keyakinan, "sedang")


class Bu02Tests(unittest.TestCase):
    def test_prive_melebihi_laba(self):
        (s,) = aturan.bu02(LR(prive="6000000", laba="4000000"))
        self.assertEqual((s.entitas, s.tone), ("prive-2026-10", "warn"))
        self.assertEqual(s.judul, "Prive Oktober 2026 melebihi laba")
        self.assertEqual(s.isi, "Prive Rp6.000.000 lebih besar dari laba Rp4.000.000; selisih Rp2.000.000 "
                                "mengurangi modal usaha.")
        self.assertEqual(s.fakta, (("Prive", "Rp6.000.000"), ("Laba", "Rp4.000.000")))
        self.assertEqual(s.rupiah, D("2000000"))

    def test_prive_di_bawah_laba_tidak_ada_saran(self):
        self.assertEqual(aturan.bu02(LR(prive="6000000", laba="12350000")), [])       # A3: prive 49% dari laba
        self.assertEqual(aturan.bu02(LR(prive="4000000", laba="4000000")), [])

    def test_tanpa_prive_tidak_ada_saran_walau_rugi(self):
        self.assertEqual(aturan.bu02(LR(prive="0", laba="-500000")), [])

    def test_prive_saat_rugi_seluruhnya_mengurangi_modal(self):
        (s,) = aturan.bu02(LR(prive="1000000", laba="-500000"))
        self.assertEqual(s.rupiah, D("1000000"))
        self.assertIn("laba -Rp500.000; selisih Rp1.000.000", s.isi)


class Bu03Tests(unittest.TestCase):
    def test_ada_omzet_amplop_pajak_kosong(self):
        (s,) = aturan.bu03(A("Pajak", "0"), LR(omzet="48650000"))
        self.assertEqual((s.entitas, s.tone, s.judul), ("pajak", "info", "Amplop Pajak masih kosong"))
        self.assertEqual(s.isi, "Omzet Oktober 2026 sudah Rp48.650.000, tetapi amplop Pajak belum terisi. "
                                "Sisihkan lewat alokasi omzet.")
        self.assertEqual([(a.label, a.ke) for a in s.aksi], [("Atur alokasi omzet", "/p/buku_usaha/alokasi")])

    def test_bulan_ini_belum_ada_omzet_memakai_bulan_lalu(self):
        (s,) = aturan.bu03(A("Pajak", "-1"), LR(periode="2026-11", omzet="0", omzet_lalu="900000", banding="2026-10"))
        self.assertIn("Omzet Oktober 2026 sudah Rp900.000", s.isi)

    def test_tidak_ada_saran(self):
        self.assertEqual(aturan.bu03(A("Pajak", "1"), LR(omzet="48650000")), [], "amplop sudah terisi")
        self.assertEqual(aturan.bu03(None, LR(omzet="48650000")), [], "tidak ada amplop Pajak")
        self.assertEqual(aturan.bu03(A("Pajak", "0"), LR()), [], "belum ada omzet")


# ── 3. lewat host ────────────────────────────────────────────────────────
@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class SaranBukuUsahaTests(u4.U4DbDasar if HAS_AIOSQLITE else unittest.TestCase):
    async def isi(self):
        """Penyiapan U2: kas Rp3 jt di Bahan (modal awal hari ini, tanpa jenis = omzet). Ditambah: pengeluaran
        Rp400 rb sehari selama 10 hari terakhir (Rp4 jt → kebutuhan dua minggu Rp2 jt; kas tinggal −Rp1 jt)."""
        await self.pasang_aktif()
        h = self.today
        async with self.Session() as db:
            for i in range(1, 11):
                await self.trx(db, self.env["Bahan"], "400000", h - timedelta(days=i))
            await self.trx(db, self.env_lain, "99000000", h - timedelta(days=1))        # ruang lain: tidak ikut
            await db.commit()

    async def kode(self, user, hid=None):
        async with self.Session() as db:
            return sorted(i.aturan for i in await titik.saran_advisor(db, user, hid or self.usaha))

    async def test_pemilik_mendapat_saran_dari_data_ruang_ini(self):
        await self.isi()
        async with self.Session() as db:
            saran = {i.aturan: i for i in await titik.saran_advisor(db, self.pemilik, self.usaha)}
        self.assertEqual(sorted(saran), ["BU-01", "BU-03"])
        teks = saran["BU-01"].data["_teks"]
        self.assertEqual(teks["judul"], "Kas usaha habis")
        self.assertEqual(teks["fakta"], [{"label": "Kas usaha", "nilai": "-Rp1.000.000"},
                                         {"label": "Kebutuhan 2 minggu", "nilai": "Rp2.000.000"}])
        self.assertEqual(saran["BU-01"].asal, "buku_usaha")
        self.assertEqual(saran["BU-03"].data["_teks"]["judul"], "Amplop Pajak masih kosong")

    async def test_admin_mendapat_karyawan_dan_ruang_lain_tidak(self):
        await self.isi()
        self.assertEqual(await self.kode(self.admin), ["BU-01", "BU-03"])
        self.assertEqual(await self.kode(self.karyawan), [])
        self.assertEqual(await self.kode(self.pemilik, self.usaha2), [])
        self.assertEqual(await self.kode(self.pemilik, self.rumah), [])

    async def test_plugin_dijeda_tidak_meninggalkan_saran(self):
        await self.isi()
        await self.aksi("jeda")
        self.assertEqual(await self.kode(self.pemilik), [])

    async def test_kartu_advisor_paling_banyak_satu_saran_buku_usaha(self):
        """Batas insight plugin per slot (H2 `daftar_per_plugin`): dua saran Buku Usaha yang sama-sama layak tampil
        (BU-01 merah, BU-02 kuning) → satu di daftar utama, satu di "lainnya"."""
        from app.services.advisor import dashboard as adv
        await self.isi()
        async with self.Session() as db:
            # Prive Rp500 rb di bulan yang dinilai BU-02 (R8: nominal 0, alokasi negatif); labanya ≤ 0.
            awal = metrics.rentang(*metrics.bulan_prive(self.today))[0]
            await self.inc(db, "0", awal, kind="prive", alok=[(self.env["Prive"], "-500000")])
            db.add(AppSetting(key=adv.FLAG_KEY, value="*"))
            await db.commit()
            self.assertEqual(sorted(i.aturan for i in await titik.saran_advisor(db, self.pemilik, self.usaha)),
                             ["BU-01", "BU-02", "BU-03"])
            out = await adv.get_dashboard(self.pemilik, db, household_id=self.usaha)
        tampil = [i["aturan"] for i in out["advisor"]["items"] if i["aturan"].startswith("BU-")]
        sisa = [s["id"].split(":")[0] for s in out["advisor"]["sisa"] if s["id"].startswith("BU-")]
        self.assertEqual(tampil, ["BU-01"])                       # kas habis lebih mendesak daripada prive
        self.assertIn("BU-02", sisa)
        item = next(i for i in out["advisor"]["items"] if i["aturan"] == "BU-01")
        self.assertEqual(item["aksi"], [{"kind": "route", "label": "Lihat laba rugi",
                                         "payload": {"to": "/p/buku_usaha/laba-rugi"}}])

    async def test_karyawan_tidak_melihat_saran_di_kartu_advisor(self):
        from app.services.advisor import dashboard as adv
        await self.isi()
        async with self.Session() as db:
            db.add(AppSetting(key=adv.FLAG_KEY, value="*"))
            await db.commit()
            out = await adv.get_dashboard(self.karyawan, db, household_id=self.usaha)
        adv_k = out.get("advisor") or {}
        semua = [i["aturan"] for i in adv_k.get("items", [])] + [s["id"] for s in adv_k.get("sisa", [])]
        self.assertEqual([k for k in semua if k.startswith("BU-")], [])


if __name__ == "__main__":
    unittest.main()
