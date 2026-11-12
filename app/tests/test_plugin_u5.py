"""Plugin U5 — Catat cepat versi usaha dan AI Advisor (03-workflow.md baris U5; 04-kontrak-api.md §3 "Catat cepat",
§5 "Deteksi catatan", §6 "Saran AI Advisor"; AGENTS.md "Plugin dan ruang" aturan 3, 4, 6, 7, 8; ADR-P3, P5, P14).

1. Angka aturan BU-* (`buku_usaha/metrics.py`): kebutuhan dua minggu, kas cukup berapa hari, bulan prive.
2. Aturan BU-01/02/03 (`buku_usaha/aturan.py`): fungsi murni angka → `Saran`, teks dari templat.
3. Saran lewat host: pemilik mendapatnya dari data nyata, karyawan dan ruang lain tidak; paling banyak satu saran
   Buku Usaha di kartu AI Advisor.
4. Deteksi catatan (Plugin API 1.6): manifest `nlp_jenis` + `nlp_kontak`, kata utuh, keluaran `@plugin.kontak_catatan`
   diperiksa host.
5. Kamus Buku Usaha (`buku_usaha/kamus.py`): pencocokan nama kontak (fungsi murni).
6. `POST /transactions/suggest-envelope`: `jenis_catatan` dan `kontak`; karyawan hanya jenis yang diizinkan dan tidak
   pernah kontak; ruang lain, ruang keluarga, dan plugin dijeda tidak mendapat apa pun.

Run: python -m unittest app.tests.test_plugin_u5 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.plugins.buku_usaha import aturan, kamus, metrics
from app.plugins.host import manifest as mf
from app.plugins.host import titik
from app.plugins.sdk import AmplopView, KontakCatatan, Saran

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    from app.models.models import AppSetting, BukuUsahaKontak, RuangBatasan
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

    async def test_aturan_tidak_dijalankan_untuk_karyawan(self):
        """Lapis pertama (host): aturan BU-* tidak dipanggil sama sekali untuk karyawan; `ctx` yang menolak baca
        keuangan untuk karyawan (`khusus_admin`) hanya lapis kedua."""
        from unittest.mock import patch
        await self.isi()
        asli, dipanggil = titik.panggil, []

        async def catat(ctx, fn, *args):
            dipanggil.append(ctx.peran)
            return await asli(ctx, fn, *args)

        with patch.object(titik, "panggil", catat):
            self.assertEqual(await self.kode(self.karyawan), [])
            self.assertEqual(dipanggil, [])
            await self.kode(self.admin)
            self.assertEqual(dipanggil, ["admin"] * 3)             # BU-01, BU-02, BU-03

    async def test_plugin_dijeda_tidak_meninggalkan_saran(self):
        await self.isi()
        await self.aksi("jeda")
        self.assertEqual(await self.kode(self.pemilik), [])

    async def test_kartu_advisor_paling_banyak_satu_saran_buku_usaha(self):
        """Batas insight plugin per slot (H2 `daftar_per_plugin`): dua saran Buku Usaha yang sama-sama layak tampil
        (BU-01 merah, BU-02 kuning) → satu di daftar utama, satu di "lainnya". Daftar utama dilonggarkan
        (`daftar_maks` 10 lewat `advisor_konstanta`) supaya yang menahan BU-02 memang batas per plugin, bukan tiga
        slot yang sudah terisi saran inti."""
        import json
        from app.services.advisor import dashboard as adv
        await self.isi()
        async with self.Session() as db:
            # Prive Rp500 rb di bulan yang dinilai BU-02 (R8: nominal 0, alokasi negatif); labanya ≤ 0.
            awal = metrics.rentang(*metrics.bulan_prive(self.today))[0]
            await self.inc(db, "0", awal, kind="prive", alok=[(self.env["Prive"], "-500000")])
            db.add(AppSetting(key=adv.FLAG_KEY, value="*"))
            db.add(AppSetting(key=adv.KONSTANTA_KEY, value=json.dumps({"daftar_maks": 10})))
            await db.commit()
            self.assertEqual(sorted(i.aturan for i in await titik.saran_advisor(db, self.pemilik, self.usaha)),
                             ["BU-01", "BU-02", "BU-03"])
            out = await adv.get_dashboard(self.pemilik, db, household_id=self.usaha)
        tampil = [i["aturan"] for i in out["advisor"]["items"] if i["aturan"].startswith("BU-")]
        sisa = [s["id"].split(":")[0] for s in out["advisor"]["sisa"] if s["id"].startswith("BU-")]
        self.assertLess(len(out["advisor"]["items"]), 10)         # masih ada tempat: bukan `daftar_maks` yang menahan
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


# ── 4. deteksi catatan: manifest dan host ────────────────────────────────
class ManifestDeteksiTests(unittest.TestCase):
    def _kontribusi(self, **isi):
        return mf.Kontribusi.model_validate(isi)

    def test_nlp_jenis_dan_nlp_kontak_diterima(self):
        c = self._kontribusi(nlp_jenis={"modal": ["setor modal"], "penjualan": ["jual", "terima pembayaran"]},
                             nlp_kontak=True)
        self.assertEqual(list(c.nlp_jenis), ["modal", "penjualan"])           # urutan manifest = urutan periksa
        self.assertTrue(c.nlp_kontak)
        kosong = self._kontribusi()
        self.assertEqual((kosong.nlp_jenis, kosong.nlp_kontak), ({}, False))

    def test_jenis_di_luar_daftar_ditolak(self):
        for jenis in ("pengeluaran", "prive", "lain", "Penjualan"):
            with self.assertRaises(ValueError, msg=jenis):
                self._kontribusi(nlp_jenis={jenis: ["jual"]})

    def test_kata_harus_huruf_kecil_dan_tidak_kosong(self):
        for kata in ([], ["Jual"], ["j"], ["jual!"], ["x" * 41]):
            with self.assertRaises(ValueError, msg=kata):
                self._kontribusi(nlp_jenis={"penjualan": kata})

    def test_kontak_catatan_tidak_boleh_meminta_izin_inti(self):
        """`@plugin.kontak_catatan` hanya membaca tabel plugin sendiri: izin baca inti pun ditolak saat memuat."""
        from app.plugins.host import kode
        from app.plugins.sdk import Plugin
        m = mf.Manifest.model_validate({
            "id": "contoh", "name": "Contoh", "version": "1.0.0", "publisher": "Jatahku", "description": "Uji U5",
            "engines": {"plugin_api": ">=1.6 <2.0"}, "space_types": ["usaha"],
            "permissions": ["transactions:read"], "contributes": {"nlp_kontak": True}})
        self.assertEqual(kode.IZIN_PER_JENIS["kontak_catatan"], frozenset())
        bersih = Plugin("contoh")
        bersih.kontak_catatan()(lambda ctx, teks, peran: None)
        self.assertEqual(kode.cocokkan(m, bersih), [])
        serakah = Plugin("contoh")
        serakah.kontak_catatan(izin=["transactions:read"])(lambda ctx, teks, peran: None)
        self.assertEqual(kode.cocokkan(m, serakah), [
            "kontak_catatan 'kontak' meminta izin yang tidak boleh untuk kontak_catatan: transactions:read "
            "(hanya baca; kirim hanya dari job)"])

    def test_versi_plugin_api(self):
        self.assertGreaterEqual(mf.PLUGIN_API_VERSION[:2], (1, 6))
        self.assertTrue(mf.cocok_rentang(">=1.6 <2.0"))


class TebakJenisTests(unittest.TestCase):
    KAMUS = [("modal", ["setor modal"]), ("pinjaman", ["terima pinjaman"]), ("penjualan", ["jual", "terima pembayaran"])]

    def test_kata_dan_frasa_utuh(self):
        self.assertEqual(titik.tebak_jenis(self.KAMUS, "Jual nasi box 30 pax 900rb"), "penjualan")
        self.assertEqual(titik.tebak_jenis(self.KAMUS, "terima  pembayaran pt arunika"), "penjualan")
        self.assertEqual(titik.tebak_jenis(self.KAMUS, "setor modal 5jt"), "modal")

    def test_potongan_kata_tidak_cocok(self):
        for teks in ("jualan gorengan", "dijual", "bayar cicilan pinjaman 500rb", "", None):
            self.assertIsNone(titik.tebak_jenis(self.KAMUS, teks), teks)

    def test_urutan_manifest_menang(self):
        self.assertEqual(titik.tebak_jenis(self.KAMUS, "setor modal dari hasil jual motor"), "modal")


class KeluaranKontakTests(unittest.TestCase):
    def test_kontak_dirapikan(self):
        k = KontakCatatan(id="7b1c2d3e-0000-4000-8000-000000000001", nama="  UD Sumber   Unggas ", peran="pemasok")
        self.assertEqual(titik.rapikan_kontak(k, "pemasok"),
                         {"id": "7b1c2d3e-0000-4000-8000-000000000001", "nama": "UD Sumber Unggas", "peran": "pemasok"})
        self.assertIsNone(titik.rapikan_kontak(None, "pemasok"))

    def test_keluaran_tidak_sah_ditolak(self):
        ok = dict(id="a1", nama="Bu Sari", peran="pelanggan")
        for salah in ({"id": "a1", "nama": "Bu Sari", "peran": "pelanggan"},           # bukan KontakCatatan
                      KontakCatatan(**{**ok, "peran": "pemasok"}),                     # peran lain dari yang diminta
                      KontakCatatan(**{**ok, "id": "../x"}), KontakCatatan(**{**ok, "id": ""}),
                      KontakCatatan(**{**ok, "nama": ""}), KontakCatatan(**{**ok, "nama": "x" * 121}),
                      KontakCatatan(**{**ok, "nama": 7})):
            with self.assertRaises(titik.KeluaranTidakSah, msg=salah):
                titik.rapikan_kontak(salah, "pelanggan")


# ── 5. kamus Buku Usaha (murni) ──────────────────────────────────────────
def K(id_, nama, peran="pemasok"):
    return {"id": id_, "nama": nama, "peran": peran}


class CocokKontakTests(unittest.TestCase):
    def test_nama_lengkap_tanpa_awalan_badan_usaha(self):
        daftar = [K("a", "UD Sumber Unggas"), K("b", "Toko Sumber Rejeki")]
        self.assertEqual(kamus.cocok_kontak("ayam potong 40kg 1,64jt ud sumber unggas", daftar)["id"], "a")
        self.assertEqual(kamus.cocok_kontak("gula 10kg sumber rejeki", daftar)["id"], "b")

    def test_kata_pertama_nama(self):
        daftar = [K("a", "PT Arunika Data", "pelanggan"), K("b", "Bu Sari", "pelanggan")]
        self.assertEqual(kamus.cocok_kontak("nasi box arunika 30 pax", daftar)["id"], "a")
        self.assertEqual(kamus.cocok_kontak("pesanan bu sari 20 porsi", daftar)["id"], "b")

    def test_kata_pertama_yang_sama_tidak_ditebak(self):
        daftar = [K("a", "UD Sumber Unggas"), K("b", "Toko Sumber Rejeki")]
        self.assertIsNone(kamus.cocok_kontak("belanja di sumber", daftar))

    def test_nama_lengkap_menang_atas_kata_pertama(self):
        daftar = [K("a", "Sumber"), K("b", "Sumber Unggas")]
        self.assertEqual(kamus.cocok_kontak("ayam sumber unggas", daftar)["id"], "b")

    def test_potongan_kata_dan_nama_pendek_tidak_cocok(self):
        daftar = [K("a", "PT Arunika Data"), K("b", "Bu Ani"), K("c", "CV")]
        for teks in ("arunikadata 30 pax", "mani pedi", "cv 200rb", "", "125rb 50 pcs"):
            self.assertIsNone(kamus.cocok_kontak(teks, daftar), teks)

    def test_nama_pendek_cocok_bila_ditulis_lengkap(self):
        self.assertEqual(kamus.cocok_kontak("pesanan bu ani 5 box", [K("b", "Bu Ani")])["id"], "b")


# ── 6. saran Catat cepat lewat HTTP ──────────────────────────────────────
@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DeteksiCatatanTests(u4.U4DbDasar if HAS_AIOSQLITE else unittest.TestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from app.api.routes.transactions import limiter
        limiter.reset()
        await self.pasang_aktif()
        self.unggas = await self.kontak("UD Sumber Unggas", "pemasok")
        self.arunika = await self.kontak("PT Arunika Data", "pelanggan")

    async def saran(self, teks, *, user=None, hid="usaha", status=200, **isi):
        self.current = user or self.pemilik
        hdr = {} if hid is None else self.hdr(self.usaha if hid == "usaha" else hid)
        r = await self.client.post("/transactions/suggest-envelope", headers=hdr, json={"description": teks, **isi})
        self.current = self.pemilik
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    async def test_pengeluaran_dengan_pemasok(self):
        s = await self.saran("ayam potong 40kg ud sumber unggas", amount=1640000)
        self.assertIsNone(s["jenis_catatan"])
        self.assertEqual(s["kontak"], {"id": self.unggas["id"], "nama": "UD Sumber Unggas", "peran": "pemasok",
                                       "plugin": "buku_usaha"})
        self.assertEqual((s["envelope_name"], s["sumber"]), ("Bahan", {"jenis": "kamus_plugin"}))

    async def test_kamus_usaha_menebak_amplop_bawaan(self):
        for teks, amplop in (("kardus 50 pcs", "Operasional"), ("elpiji 3 tabung", "Operasional"),
                             ("beras 25 kg", "Bahan")):
            s = await self.saran(teks)
            self.assertEqual((s["envelope_name"], s["sumber"]), (amplop, {"jenis": "kamus_plugin"}), teks)

    async def test_penjualan_dengan_pelanggan(self):
        s = await self.saran("jual nasi box arunika 30 pax")
        self.assertEqual(s["jenis_catatan"], "penjualan")
        self.assertEqual(s["kontak"], {"id": self.arunika["id"], "nama": "PT Arunika Data", "peran": "pelanggan",
                                       "plugin": "buku_usaha"})

    async def test_jenis_pilihan_user_menentukan_peran_kontak(self):
        tanpa = await self.saran("arunika 30 pax")
        self.assertEqual((tanpa["jenis_catatan"], tanpa["kontak"]), (None, None))      # pengeluaran: cari pemasok
        s = await self.saran("arunika 30 pax", jenis="penjualan")
        self.assertEqual((s["jenis_catatan"], s["kontak"]["nama"]), (None, "PT Arunika Data"))
        # User memilih pengeluaran: kata "jual" tetap dilaporkan, tetapi kontak yang dicari pemasok.
        s = await self.saran("jual arunika", jenis="pengeluaran")
        self.assertEqual((s["jenis_catatan"], s["kontak"]), ("penjualan", None))
        await self.saran("x", jenis="prive", status=422)

    async def test_modal_dan_pinjaman_tanpa_kontak(self):
        s = await self.saran("setor modal 5jt arunika")
        self.assertEqual((s["jenis_catatan"], s["kontak"]), ("modal", None))
        s = await self.saran("terima pinjaman bank 10jt")
        self.assertEqual((s["jenis_catatan"], s["kontak"]), ("pinjaman", None))

    async def test_teks_kosong_tetap_punya_kunci(self):
        s = await self.saran("", amount=5000)
        self.assertEqual((s["jenis_catatan"], s["kontak"], s["envelope_id"]), (None, None, None))

    async def test_karyawan_hanya_jenis_tidak_pernah_kontak(self):
        s = await self.saran("jual nasi box arunika 30 pax", user=self.karyawan)
        self.assertEqual((s["jenis_catatan"], s["kontak"]), ("penjualan", None))
        s = await self.saran("ayam ud sumber unggas", user=self.karyawan)
        self.assertEqual((s["jenis_catatan"], s["kontak"]), (None, None))
        s = await self.saran("arunika", user=self.karyawan, jenis="penjualan")
        self.assertIsNone(s["kontak"])
        # Modal dan pinjaman bukan catatan karyawan.
        s = await self.saran("setor modal 5jt", user=self.karyawan)
        self.assertIsNone(s["jenis_catatan"])

    async def test_host_tidak_memberi_karyawan_jenis_modal_atau_pinjaman(self):
        """Lapis pertama (host, `JENIS_KARYAWAN`): tanpa saringan batasan di route pun karyawan hanya mendapat
        penjualan."""
        async with self.Session() as db:
            async def jenis(user, teks):
                return (await titik.deteksi_catatan(db, user, self.usaha, teks))["jenis_catatan"]
            self.assertEqual(await jenis(self.karyawan, "jual nasi box 30 pax"), "penjualan")
            self.assertIsNone(await jenis(self.karyawan, "setor modal 5jt"))
            self.assertIsNone(await jenis(self.karyawan, "pinjaman cair 10jt"))
            self.assertEqual(await jenis(self.pemilik, "setor modal 5jt"), "modal")
            self.assertEqual(await jenis(self.pemilik, "pinjaman cair 10jt"), "pinjaman")

    async def test_fungsi_kontak_tidak_dipanggil_untuk_karyawan(self):
        """Lapis pertama (host): fungsi plugin tidak dijalankan sama sekali untuk karyawan; `ctx.data()` yang menolak
        karyawan (`khusus_admin`) hanya lapis kedua."""
        from unittest.mock import patch
        asli, dipanggil = titik.panggil, []

        async def catat(ctx, fn, *args):
            dipanggil.append(ctx.peran)
            return await asli(ctx, fn, *args)

        with patch.object(titik, "panggil", catat):
            await self.saran("ayam ud sumber unggas", user=self.karyawan)
            await self.saran("jual arunika", user=self.karyawan, jenis="penjualan")
            self.assertEqual(dipanggil, [])
            await self.saran("ayam ud sumber unggas", user=self.admin)
            self.assertEqual(dipanggil, ["admin"])

    async def test_karyawan_tanpa_izin_penjualan_tidak_mendapat_jenis(self):
        async with self.Session() as db:
            db.add(RuangBatasan(household_id=self.usaha, user_id=self.karyawan.id, jenis_catatan=["pengeluaran"]))
            await db.commit()
        s = await self.saran("jual nasi box 30 pax", user=self.karyawan)
        self.assertEqual((s["jenis_catatan"], s["kontak"]), (None, None))

    async def test_admin_mendapat_kontak(self):
        s = await self.saran("ayam ud sumber unggas", user=self.admin)
        self.assertEqual(s["kontak"]["id"], self.unggas["id"])

    async def test_ruang_lain_dan_ruang_keluarga_tidak_memakai_kamus_ini(self):
        for hid in (self.usaha2, None):                       # plugin tidak terpasang · ruang keluarga
            s = await self.saran("jual ayam ud sumber unggas", hid=hid)
            self.assertEqual((s["jenis_catatan"], s["kontak"]), (None, None), hid)

    async def test_kontak_ruang_lain_tidak_pernah_cocok(self):
        await self.pasang_aktif(self.usaha2)
        async with self.Session() as db:
            db.add(BukuUsahaKontak(household_id=self.usaha2, nama="CV Tirta Kemasan", peran="pemasok"))
            await db.commit()
        s = await self.saran("kardus tirta kemasan")
        self.assertIsNone(s["kontak"])
        s = await self.saran("kardus tirta kemasan", hid=self.usaha2)
        self.assertEqual(s["kontak"]["nama"], "CV Tirta Kemasan")
        self.assertIsNone((await self.saran("ayam ud sumber unggas", hid=self.usaha2))["kontak"])

    async def test_kontak_terhapus_tidak_cocok(self):
        await self.p("DELETE", f"/kontak/{self.unggas['id']}", status=204)
        self.assertIsNone((await self.saran("ayam ud sumber unggas"))["kontak"])

    async def test_plugin_dijeda_tidak_mendeteksi(self):
        await self.aksi("jeda")
        s = await self.saran("jual ayam ud sumber unggas")
        self.assertEqual((s["jenis_catatan"], s["kontak"]), (None, None))
        self.assertNotEqual(s["sumber"], {"jenis": "kamus_plugin"})

    async def test_fungsi_plugin_gagal_tidak_merusak_saran(self):
        from unittest.mock import patch
        with patch.object(kamus, "cocok_kontak", side_effect=RuntimeError("bug plugin")):
            s = await self.saran("ayam ud sumber unggas")
        self.assertEqual((s["kontak"], s["envelope_name"]), (None, "Bahan"))

    async def test_saran_banyak_tidak_berubah_bentuk(self):
        r = await self.client.post("/transactions/suggest-envelopes", headers=self.hdr(),
                                   json={"descriptions": ["jual ayam ud sumber unggas"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(set(r.json()["results"][0]), {"index", "envelope_id", "envelope_name", "confident", "sumber"})


if __name__ == "__main__":
    unittest.main()
