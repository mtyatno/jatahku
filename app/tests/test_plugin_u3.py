"""Plugin U3 — laba rugi dan laporan (03-workflow.md baris U3; 04-kontrak-api.md §5 "Baca agregat", "Berkas laporan",
§6 "Laba rugi", "Laporan"; AGENTS.md "Plugin dan ruang" aturan 4, 6, 7, 9; ADR-P3, P9).

1. Angka murni (`buku_usaha/metrics.py`): periode, omzet hanya dari penjualan (+ pemasukan tanpa jenis, dilaporkan
   terpisah), modal/pinjaman/lain/prive di luar laba rugi, prive = −alokasi, transfer diabaikan, beban per akun dengan
   "Belum berakun" terakhir, margin dan perubahan; data contoh kanvas (Dapur Nusa Oktober/September).
2. Teks (`teks.py`): persen, rupiah, bulan; templat tanpa `str.format`.
3. Berkas host (`host/berkas.py`): bentuk `Laporan` diperiksa (jenis sel, batas); CSV anti formula-injection (PR #136);
   PDF berupa teks PDF dengan karakter di luar font dibuang; nama berkas dirapikan.
4. Baca agregat (`host/ringkas.py` lewat `PluginContext`): ruang konteks saja, amplop pribadi tidak (hanya_bersama),
   transaksi terhapus tidak, meta terhapus tidak, kelompok pendamping transaksi privat orang lain tersamar, `per` hanya
   kelompok yang sah, karyawan `khusus_admin`, izin.
5. `GET /p/buku_usaha/laba-rugi`: angka dari data nyata dua bulan; periode salah 422; karyawan 403; izin baru 403
   sebelum disetujui; ruang lain tidak terbaca.
6. `GET /p/buku_usaha/laporan`: lampiran PDF/CSV dengan header aman, escape, audit tanpa angka; format salah 422;
   karyawan 403.

Run: python -m unittest app.tests.test_plugin_u3 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import csv
import importlib.util
import io
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal as D

from app.plugins.buku_usaha import laporan as lap_bu
from app.plugins.buku_usaha import metrics, teks
from app.plugins.host import berkas
from app.plugins.sdk import Laporan, NilaiTidakSah, PemasukanView, RingkasanView, TabelLaporan, TransaksiView

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def R(kunci, jumlah, banyak=1, dialokasikan=D(0)):
    return RingkasanView(kunci=kunci, jumlah=D(jumlah), banyak=banyak, dialokasikan=D(dialokasikan))


# ── 1. angka murni ───────────────────────────────────────────────────────
class PeriodeTests(unittest.TestCase):
    HARI = date(2026, 11, 10)

    def test_periode(self):
        self.assertEqual(metrics.periode(None, self.HARI), (2026, 11))
        self.assertEqual(metrics.periode("", self.HARI), (2026, 11))
        self.assertEqual(metrics.periode("2026-10", self.HARI), (2026, 10))
        self.assertEqual(metrics.periode("2025-12", self.HARI), (2025, 12))
        for salah in ("2026-13", "2026-00", "26-10", "2026-1", "2026/10", "2026-12", "2027-01", "1999-12",
                      " 2026-10", 202610):
            with self.assertRaises(NilaiTidakSah, msg=salah):
                metrics.periode(salah, self.HARI)

    def test_rentang_dan_bulan_lalu(self):
        self.assertEqual(metrics.rentang(2026, 2), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(metrics.rentang(2028, 2)[1], date(2028, 2, 29))
        self.assertEqual(metrics.bulan_lalu(2026, 1), (2025, 12))
        self.assertEqual(metrics.bulan_lalu(2026, 10), (2026, 9))


class HitungTests(unittest.TestCase):
    def test_aturan_omzet_dan_di_luar(self):
        pemasukan = [
            R(("2026-10", "pemasukan", "penjualan"), "1000000", 3),
            R(("2026-10", "pemasukan", None), "200000", 2),          # tanpa jenis (penjualan karyawan)
            R(("2026-10", "top-up", None), "50000", 1),              # tanpa jenis juga
            R(("2026-10", "pemasukan", "modal"), "5000000", 1),
            R(("2026-10", "pemasukan", "pinjaman"), "2000000", 1),
            R(("2026-10", "pemasukan", "lain"), "10000", 1),
            R(("2026-10", "prive", None), "0", 2, dialokasikan="-600000"),
            R(("2026-10", "transfer", None), "0", 4, dialokasikan="0"),
            R(("2026-10", "penyesuaian", None), "75000", 1),
            R(("2026-09", "pemasukan", "penjualan"), "999", 1),     # bulan lain
        ]
        transaksi = [
            R(("2026-10", "Bahan baku"), "300000", 4),
            R(("2026-10", None), "50000", 2),
            R(("2026-10", "Sewa"), "300000", 1),
            R(("2026-10", "Gaji"), "400000", 1),
            R(("2026-09", "Gaji"), "1", 1),
        ]
        h = metrics.hitung_bulan("2026-10", transaksi, pemasukan)
        self.assertEqual(h["omzet"], D("1250000"))
        self.assertEqual(h["jumlah_penjualan"], 6)
        self.assertEqual(h["omzet_tanpa_jenis"], {"jumlah": D("250000"), "banyak": 3})
        self.assertEqual({x["jenis"]: (x["jumlah"], x["banyak"]) for x in h["di_luar_laba_rugi"]},
                         {"prive": (D("600000"), 2), "modal": (D("5000000"), 1), "pinjaman": (D("2000000"), 1),
                          "lain": (D("10000"), 1)})
        self.assertEqual([(b["akun"], b["jumlah"]) for b in h["beban"]],
                         [("Gaji", D("400000")), ("Bahan baku", D("300000")), ("Sewa", D("300000")),
                          (metrics.BELUM_BERAKUN, D("50000"))])
        self.assertEqual(h["beban_total"], D("1050000"))
        self.assertEqual(h["laba"], D("200000"))
        self.assertEqual(h["margin"], D("0.1600"))
        self.assertEqual(sum(b["porsi"] for b in h["beban"]), D("1.0000"))

    def test_kosong_dan_rugi(self):
        h = metrics.hitung_bulan("2026-10", [], [])
        self.assertEqual((h["omzet"], h["beban_total"], h["laba"], h["margin"], h["beban"]), (0, 0, 0, None, []))
        h = metrics.hitung_bulan("2026-10", [R(("2026-10", "Sewa"), "500")], [R(("2026-10", "pemasukan", "penjualan"), "400")])
        self.assertEqual((h["laba"], h["margin"]), (D("-100"), D("-0.2500")))

    def test_data_contoh_kanvas(self):
        """05-desain-buku-usaha.md A3: Oktober omzet 48,65 jt, beban 36,3 jt, laba 12,35 jt (25,4%); September 44,6 /
        34,95 / 9,65 (21,6%); prive 6 jt (49% dari laba)."""
        pemasukan = [R(("2026-10", "pemasukan", "penjualan"), "48650000", 112),
                     R(("2026-10", "prive", None), "0", 1, dialokasikan="-6000000"),
                     R(("2026-09", "pemasukan", "penjualan"), "44600000", 101)]
        transaksi = [R(("2026-10", "Bahan baku"), "21800000"), R(("2026-10", "Gaji"), "9000000"),
                     R(("2026-10", "Sewa"), "5500000"), R(("2026-09", "Bahan baku"), "34950000")]
        lr = metrics.susun(2026, 10, metrics.hitung_bulan("2026-10", transaksi, pemasukan),
                           metrics.hitung_bulan("2026-09", transaksi, pemasukan), date(2026, 11, 2))
        self.assertEqual((lr["omzet"], lr["beban_total"], lr["laba"]), (D("48650000"), D("36300000"), D("12350000")))
        self.assertEqual(teks.persen(lr["margin"]), "25,4%")
        self.assertEqual(lr["banding"]["laba"], D("9650000"))
        self.assertEqual(teks.persen(lr["banding"]["margin"]), "21,6%")
        self.assertEqual(teks.persen(lr["prive_dari_laba"]), "48,6%")
        self.assertEqual(lr["perubahan"]["omzet"], D("0.0908"))
        self.assertEqual(lr["perubahan"]["laba"], D("0.2798"))
        self.assertEqual((lr["periode"], lr["mulai"], lr["akhir"], lr["berjalan"]),
                         ("2026-10", date(2026, 10, 1), date(2026, 10, 31), False))

    def test_perubahan_dari_nol_dan_rugi(self):
        self.assertIsNone(metrics.perubahan(D(100), D(0)))
        self.assertEqual(metrics.perubahan(D(50), D(-100)), D("1.5000"))     # rugi mengecil = naik
        kosong = metrics.hitung_bulan("x", [], [])
        lr = metrics.susun(2026, 11, kosong, kosong, date(2026, 11, 10))
        self.assertTrue(lr["berjalan"])
        self.assertIsNone(lr["prive_dari_laba"])
        self.assertEqual(lr["perubahan"], {"omzet": None, "beban_total": None, "laba": None})


# ── 2. teks ──────────────────────────────────────────────────────────────
class TeksTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(teks.persen(D("0.2539")), "25,4%")
        self.assertEqual(teks.persen(D("0.25")), "25%")
        self.assertEqual(teks.persen(D("-0.00004")), "0%")
        self.assertEqual(teks.persen(None), "\N{EM DASH}")
        self.assertEqual(teks.rupiah(D("1234567.5")), "Rp1.234.568")
        self.assertEqual(teks.rupiah(D("-12000")), "-Rp12.000")
        self.assertEqual(teks.nama_bulan("2026-10"), "Oktober 2026")
        self.assertEqual(teks.tanggal(date(2026, 10, 3)), "3 Okt 2026")
        self.assertEqual(teks.t("judul_laba_rugi", bulan="Oktober 2026"), "Laba rugi Oktober 2026")
        # Isian bukan templat: kurung kurawal di nilai tidak diisi ulang.
        self.assertEqual(teks.t("judul_laba_rugi", bulan="{ruang}"), "Laba rugi {ruang}")


# ── 3. berkas host ───────────────────────────────────────────────────────
def _lap(fmt="csv", **kw):
    isi = dict(format=fmt, nama_berkas="Buku Usaha/Laba Rugi 2026-10", judul="Laba rugi Oktober 2026",
               subjudul="Dapur Nusa · 1 Okt 2026–31 Okt 2026", ringkasan=(("Omzet", D("48650000")), ("Penjualan", 112)),
               tabel=(TabelLaporan(judul="Penjualan", kolom=("Tanggal", "Keterangan", "Jumlah"),
                                   baris=((date(2026, 10, 1), "=HYPERLINK(\"http://x\")", D("1000")),
                                          (date(2026, 10, 2), "Nasi box 🍱 <b>bu</b>\nSari", D("-5")),
                                          (date(2026, 10, 3), None, D("0.50"))),
                                   total=("Total", None, D("995.50"))),),
               catatan=("Catatan @penting",))
    isi.update(kw)
    return Laporan(**isi)


class BerkasTests(unittest.TestCase):
    def test_periksa_menolak_bentuk_salah(self):
        berkas.periksa(_lap())
        t = TabelLaporan(judul="x", kolom=("a",), baris=(("ok",),))
        for salah in (
            _lap(fmt="xlsx"),
            _lap(tabel=(TabelLaporan(judul="x", kolom=("a",), baris=((1.5,),)),)),            # float
            _lap(tabel=(TabelLaporan(judul="x", kolom=("a",), baris=((True,),)),)),           # bool
            _lap(tabel=(TabelLaporan(judul="x", kolom=("a",), baris=((datetime.now(),),)),)),  # datetime
            _lap(tabel=(TabelLaporan(judul="x", kolom=("a", "b"), baris=(("1",),)),)),        # panjang beda
            _lap(tabel=(TabelLaporan(judul="x", kolom=(), baris=()),)),
            _lap(tabel=(TabelLaporan(judul="x", kolom=tuple("abcdefghi"), baris=()),)),       # 9 kolom
            _lap(tabel=(t,) * (berkas.MAKS_TABEL + 1)),
            _lap(tabel=(TabelLaporan(judul="x", kolom=("a",), baris=(("1",),) * (berkas.MAKS_BARIS + 1)),)),
            _lap(tabel=({"judul": "x"},)),
            _lap(ringkasan=(("a", 1.0),)),
            _lap(judul=None),
        ):
            with self.assertRaises((TypeError, ValueError)):
                berkas.periksa(salah)
        with self.assertRaises(TypeError):
            berkas.periksa({"format": "csv"})

    def test_nama_berkas(self):
        self.assertEqual(berkas.nama_berkas("Buku Usaha/Laba Rugi 2026-10", "pdf"),
                         "jatahku-buku-usaha-laba-rugi-2026-10.pdf")
        self.assertEqual(berkas.nama_berkas('../"; x=1', "csv"), "jatahku-x-1.csv")
        self.assertEqual(berkas.nama_berkas("🍱", "csv"), "jatahku-laporan.csv")

    def test_csv_anti_formula(self):
        isi = berkas.render_csv(_lap(), ruang="=Dapur Nusa").decode("utf-8")
        self.assertTrue(isi.startswith("﻿"))
        baris = list(csv.reader(io.StringIO(isi.lstrip("﻿"))))
        datar = [sel for b in baris for sel in b]
        self.assertIn("'=Dapur Nusa", datar)
        self.assertIn("'=HYPERLINK(\"http://x\")", datar)
        self.assertIn("Catatan @penting", datar)            # tidak diawali karakter rumus: dibiarkan
        self.assertIn("-5", datar)                           # angka negatif tetap angka, bukan teks berkutip
        self.assertIn("0.50", datar)
        self.assertIn("2026-10-01", datar)
        self.assertIn("Nasi box 🍱 <b>bu</b> Sari", datar)    # baris baru dirapatkan
        self.assertNotIn(None, datar)

    def test_pdf_teks_pdf(self):
        isi = berkas.render_pdf(_lap("pdf"), ruang="Dapur Nusa", dibuat=datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.assertTrue(isi.startswith(b"%PDF-"))
        self.assertGreater(len(isi), 2000)
        self.assertNotIn(b"<b>bu</b>", isi)     # teks tertanam sebagai glyph subset, bukan markup

    def test_pdf_tabel_kosong_dan_banyak_halaman(self):
        banyak = TabelLaporan(judul="P", kolom=("Tanggal", "Keterangan", "Jumlah"),
                              baris=tuple((date(2026, 10, 1), f"Catatan {i}", D(i)) for i in range(300)))
        kosong = TabelLaporan(judul="K", kolom=("A", "B"), baris=())
        isi = berkas.render_pdf(_lap("pdf", tabel=(kosong, banyak)), ruang="R", dibuat=datetime(2026, 11, 1))
        self.assertTrue(isi.startswith(b"%PDF-"))


# ── isi laporan Buku Usaha (murni) ───────────────────────────────────────
class SusunLaporanTests(unittest.TestCase):
    def _lr(self, **ubah):
        p = [R(("2026-10", "pemasukan", "penjualan"), "300000", 1), R(("2026-10", "pemasukan", None), "50000", 1),
             R(("2026-10", "prive", None), "0", 1, dialokasikan="-100000")]
        t = [R(("2026-10", "Bahan baku"), "120000", 1), R(("2026-10", None), "30000", 1)]
        lr = metrics.susun(2026, 10, metrics.hitung_bulan("2026-10", t, p), metrics.hitung_bulan("2026-09", t, p),
                           date(2026, 10, 20))
        lr.update(ubah)
        return lr

    def test_isi(self):
        from uuid import uuid4
        u, e = uuid4(), uuid4()
        k = uuid4()
        pem = [PemasukanView(id=uuid4(), user_id=u, jumlah=D("50000"), deskripsi="kopi titip", tanggal=date(2026, 10, 9),
                             jenis="pemasukan"),
               PemasukanView(id=uuid4(), user_id=u, jumlah=D("0"), deskripsi="Prive", tanggal=date(2026, 10, 8),
                             jenis="prive"),
               PemasukanView(id=uuid4(), user_id=u, jumlah=D("1000000"), deskripsi="setor", tanggal=date(2026, 10, 7),
                             jenis="pemasukan", meta={"jenis": "modal", "kontak_id": None}),
               PemasukanView(id=uuid4(), user_id=u, jumlah=D("300000"), deskripsi="Penjualan · Bu Sari",
                             tanggal=date(2026, 10, 2), jenis="pemasukan", meta={"jenis": "penjualan", "kontak_id": k})]
        trx = [TransaksiView(id=uuid4(), amplop_id=uuid4(), user_id=u, jumlah=D("30000"), deskripsi="🔒 Pribadi",
                             tanggal=date(2026, 10, 5), sumber="webapp", milik_sendiri=False),
               TransaksiView(id=uuid4(), amplop_id=e, user_id=u, jumlah=D("120000"), deskripsi="ayam",
                             tanggal=date(2026, 10, 1), sumber="webapp", milik_sendiri=True,
                             meta={"akun": "Bahan baku", "kontak_id": k, "proyek": None})]
        lap = lap_bu.susun(self._lr(), pem, trx, {str(e): "Bahan"}, {str(k): "Bu Sari"}, ruang="Dapur Nusa", fmt="csv")
        berkas.periksa(lap)
        self.assertEqual(lap.nama_berkas, "buku-usaha-laba-rugi-2026-10")
        self.assertEqual(lap.judul, "Laba rugi Oktober 2026")
        self.assertIn("Dapur Nusa", lap.subjudul)
        tabel = {t.judul: t for t in lap.tabel}
        self.assertEqual([t.judul for t in lap.tabel],
                         ["Laba rugi", "Beban per akun", "Di luar laba rugi", "Penjualan", "Pengeluaran"])
        # Penjualan: urut tanggal naik; modal dan prive tidak ikut; tanpa jenis ditandai.
        self.assertEqual([(b[1], b[2], b[3]) for b in tabel["Penjualan"].baris],
                         [("Penjualan · Bu Sari", "Bu Sari", "Penjualan"), ("kopi titip", None, "Tanpa jenis")])
        self.assertEqual(tabel["Penjualan"].total[-1], D("350000"))
        self.assertEqual([(b[2], b[3], b[4]) for b in tabel["Pengeluaran"].baris],
                         [("Bahan", "Bahan baku", "Bu Sari"), ("Amplop diarsipkan", metrics.BELUM_BERAKUN, None)])
        self.assertEqual(tabel["Di luar laba rugi"].baris[0][2], D("100000"))       # prive
        self.assertTrue(any("tanpa jenis" in c for c in lap.catatan))
        self.assertTrue(any("Belum berakun" in c for c in lap.catatan))
        self.assertFalse(any("terbaru dari" in c for c in lap.catatan))

    def test_terpotong_dikatakan(self):
        lap = lap_bu.susun(self._lr(jumlah_penjualan=1500), [], [], {}, {}, ruang="R", fmt="pdf")
        self.assertTrue(any("0 catatan terbaru dari 1500" in c for c in lap.catatan))
        self.assertTrue(any(c.startswith("Daftar pengeluaran") for c in lap.catatan))
        self.assertIsNone({t.judul: t for t in lap.tabel}["Penjualan"].total)


# ── 4–6. SQLite ──────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    from sqlalchemy import select

    from app.models.models import (
        Allocation, BukuUsahaIncomeMeta, BukuUsahaKontak, BukuUsahaTxnMeta, Envelope, Income, PluginAuditLog,
        PluginInstallation, Transaction,
    )
    from app.plugins.host import ringkas
    from app.plugins.sdk import IzinDitolak
    # Modulnya, bukan kelasnya: kelas tes di namespace modul ini akan ikut dijalankan lagi oleh unittest.
    from app.tests import test_plugin_u2 as u2
    MANIFEST_BU = u2.MANIFEST_BU


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class U3DbTests(unittest.IsolatedAsyncioTestCase):
    """Memakai penyiapan U2 (ruang usaha Dapur Nusa dengan 5 amplop bawaan + amplop pribadi pemilik, ruang usaha kedua,
    ruang keluarga, pemilik/admin/karyawan; modal awal Rp3 jt hari ini tanpa jenis)."""
    if HAS_AIOSQLITE:
        asyncSetUp = u2.U2DbTests.asyncSetUp
        hdr, aksi, pasang_aktif, p, kode, kontak, atur_a3, hitung, katalog, _ctx = (
            u2.U2DbTests.hdr, u2.U2DbTests.aksi, u2.U2DbTests.pasang_aktif, u2.U2DbTests.p, u2.U2DbTests.kode,
            u2.U2DbTests.kontak, u2.U2DbTests.atur_a3, u2.U2DbTests.hitung, u2.U2DbTests.katalog, u2.U2DbTests._ctx)

    # ── data contoh dua bulan (bulan lalu = B, sebelumnya = A) ──
    def bulan(self):
        b = metrics.bulan_lalu(self.today.year, self.today.month)
        return b, metrics.bulan_lalu(*b)

    async def isi_dua_bulan(self):
        (bth, bbl), (ath, abl) = self.bulan()
        B, A = (lambda d: date(bth, bbl, d)), (lambda d: date(ath, abl, d))
        async with self.Session() as db:
            sari = BukuUsahaKontak(household_id=self.usaha, nama="=Bu Sari", peran="pelanggan")
            unggas = BukuUsahaKontak(household_id=self.usaha, nama="UD Sumber Unggas", peran="pemasok")
            db.add_all([sari, unggas])
            await db.flush()

            async def inc(hid, jumlah, tgl, *, kind="pemasukan", jenis=None, kontak=None, alok=(), meta_hapus=False,
                          ket="pemasukan"):
                i = Income(household_id=hid, user_id=self.pemilik.id, amount=D(jumlah), description=ket,
                           income_date=tgl, kind=kind)
                db.add(i)
                await db.flush()
                for env, x in alok:
                    db.add(Allocation(income_id=i.id, envelope_id=env, amount=D(x)))
                if jenis:
                    db.add(BukuUsahaIncomeMeta(household_id=hid, income_id=i.id, jenis=jenis, kontak_id=kontak,
                                               deleted_at=datetime.now(timezone.utc) if meta_hapus else None))
                return i

            async def trx(env, jumlah, tgl, *, user=None, akun=None, pemasok=None, privat=False, hapus=False,
                          meta_hapus=False, ket="belanja"):
                t = Transaction(envelope_id=env, user_id=(user or self.pemilik).id, amount=D(jumlah), description=ket,
                                transaction_date=tgl, is_private=privat, is_deleted=hapus)
                db.add(t)
                await db.flush()
                if akun or pemasok:
                    hid = (await db.get(Envelope, env)).household_id
                    db.add(BukuUsahaTxnMeta(household_id=hid, transaction_id=t.id, akun=akun, kontak_id=pemasok,
                                            deleted_at=datetime.now(timezone.utc) if meta_hapus else None))
                return t

            bahan, op, prive = self.env["Bahan"], self.env["Operasional"], self.env["Prive"]
            # Bulan B: penjualan 1 jt (Bu Sari) + 500 rb; tanpa jenis 200 rb; modal 5 jt; pinjaman 2 jt; prive 300 rb;
            # transfer (diabaikan).
            await inc(self.usaha, "1000000", B(2), jenis="penjualan", kontak=sari.id, alok=[(bahan, "1000000")],
                      ket="Penjualan · =Bu Sari")
            await inc(self.usaha, "500000", B(3), jenis="penjualan", alok=[(bahan, "500000")], ket="Penjualan")
            await inc(self.usaha, "200000", B(4), alok=[(bahan, "200000")], ket="titip kasir")
            await inc(self.usaha, "5000000", B(5), jenis="modal", alok=[(bahan, "5000000")])
            await inc(self.usaha, "2000000", B(6), jenis="pinjaman", alok=[(bahan, "2000000")])
            await inc(self.usaha, "0", B(7), kind="prive", alok=[(prive, "-300000")], ket="Prive ke ruang keluarga")
            await inc(self.usaha, "0", B(8), kind="transfer", alok=[(bahan, "-50000"), (op, "50000")])
            # Meta terhapus = tanpa jenis (ikut omzet tanpa jenis).
            await inc(self.usaha, "70000", B(9), jenis="penjualan", meta_hapus=True, alok=[(bahan, "70000")])
            # Ruang lain dan ruang keluarga tidak ikut.
            await inc(self.usaha2, "9000000", B(2), jenis="penjualan")
            await inc(self.rumah, "8000000", B(2))
            # Beban bulan B: bahan baku 400 rb (pemasok), gaji 300 rb, tanpa akun 50 rb, privat admin 25 rb
            # (akun tersamar), meta terhapus 10 rb (tanpa akun), terhapus (tidak), amplop pribadi (tidak), ruang lain.
            await trx(bahan, "400000", B(2), akun="Bahan baku", pemasok=unggas.id, ket="ayam =cmd")
            await trx(op, "300000", B(3), akun="Gaji")
            await trx(op, "50000", B(4))
            await trx(op, "25000", B(5), user=self.admin, akun="Transport", privat=True, ket="rahasia admin")
            await trx(op, "10000", B(6), akun="Sewa", meta_hapus=True)
            await trx(op, "999999", B(7), akun="Sewa", hapus=True)
            await trx(self.pribadi, "777777", B(8))
            await trx(self.env_lain, "888888", B(9), akun="Gaji")
            # Bulan A: penjualan 1 jt, beban 600 rb.
            await inc(self.usaha, "1000000", A(10), jenis="penjualan", alok=[(bahan, "1000000")])
            await trx(bahan, "600000", A(11), akun="Bahan baku")
            await db.commit()
        return f"{bth:04d}-{bbl:02d}", f"{ath:04d}-{abl:02d}"

    # ── 4. baca agregat ──
    async def test_ringkas_lewat_konteks(self):
        await self.isi_dua_bulan()
        (bth, bbl), _ = self.bulan()
        mulai, akhir = metrics.rentang(bth, bbl)
        izin = ("envelopes:read", "transactions:read", "incomes:read")
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=izin, boleh_tulis=False, jenis="rute")
            t = await ctx.ringkas_transaksi(mulai, akhir, per=("txn_meta.akun",), hanya_bersama=True)
            self.assertEqual({r.kunci[0]: r.jumlah for r in t},
                             {"Bahan baku": D("400000"), "Gaji": D("300000"), None: D("85000")})
            # Tanpa hanya_bersama: amplop pribadi viewer ikut.
            semua = await ctx.ringkas_transaksi(mulai, akhir)
            self.assertEqual(semua[0].jumlah, D("785000") + D("777777"))
            # Viewer admin: transaksi privatnya sendiri terbaca akunnya.
            ctx_admin = await self._ctx(db, izin=izin, boleh_tulis=False, user=self.admin, peran="admin")
            t = await ctx_admin.ringkas_transaksi(mulai, akhir, per=("txn_meta.akun",), hanya_bersama=True)
            self.assertEqual({r.kunci[0]: r.jumlah for r in t}["Transport"], D("25000"))
            # Pemasukan: kind + jenis meta, dialokasikan untuk prive.
            p = await ctx.ringkas_pemasukan(mulai, akhir, per=("jenis", "income_meta.jenis"))
            d = {r.kunci: (r.jumlah, r.banyak, r.dialokasikan) for r in p}
            self.assertEqual(d[("prive", None)], (D("0"), 1, D("-300000")))
            self.assertEqual(d[("pemasukan", "penjualan")][:2], (D("1500000"), 2))
            self.assertEqual(d[("pemasukan", None)][:2], (D("270000"), 2))
            self.assertNotIn(D("9000000"), [x[0] for x in d.values()])
            # Baris + meta: privat orang lain tanpa meta; meta terhapus = None.
            rows = await ctx.transactions(mulai, akhir, pendamping="txn_meta", hanya_bersama=True)
            meta = {r.deskripsi: r.meta for r in rows}
            self.assertEqual(meta["ayam =cmd"]["akun"], "Bahan baku")
            self.assertNotIn("transaction_id", meta["ayam =cmd"])
            self.assertNotIn("household_id", meta["ayam =cmd"])
            self.assertNotIn("rahasia admin", meta)
            self.assertTrue(all(m is None for k, m in meta.items() if k not in ("ayam =cmd", "belanja")))
            pem = await ctx.incomes(mulai, akhir, pendamping="income_meta")
            self.assertEqual(sorted((x.meta or {}).get("jenis") or "-" for x in pem),
                             sorted(["penjualan", "penjualan", "-", "modal", "pinjaman", "-", "-", "-"]))

    async def test_ringkas_dijaga(self):
        (bth, bbl), _ = self.bulan()
        mulai, akhir = metrics.rentang(bth, bbl)
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=("envelopes:read",), boleh_tulis=False)
            for panggil in (ctx.ringkas_transaksi(mulai, akhir), ctx.ringkas_pemasukan(mulai, akhir)):
                with self.assertRaises(IzinDitolak) as cm:
                    await panggil
                self.assertEqual(cm.exception.alasan, "tanpa_izin")
            izin = ("transactions:read", "incomes:read")
            ctx = await self._ctx(db, izin=izin, boleh_tulis=False, user=self.karyawan, peran="member")
            with self.assertRaises(IzinDitolak) as cm:
                await ctx.ringkas_transaksi(mulai, akhir)
            self.assertEqual(cm.exception.alasan, "khusus_admin")
            ctx = await self._ctx(db, izin=izin, boleh_tulis=False)
            for per in (("kontak.nama",), ("txn_meta.household_id",), ("txn_meta.transaction_id",),
                        ("txn_meta.deleted_at",), ("income_meta.jenis",), ("p_lain_x.y",), ("tidak",),
                        ("bulan", "amplop", "txn_meta.akun", "txn_meta.kontak_id"), ("bulan", "bulan")):
                with self.assertRaises(ValueError, msg=per):
                    await ctx.ringkas_transaksi(mulai, akhir, per=per)
            for per in (("txn_meta.akun",), ("amplop",), ("income_meta.income_id",)):
                with self.assertRaises(ValueError, msg=per):
                    await ctx.ringkas_pemasukan(mulai, akhir, per=per)
            with self.assertRaises(ValueError):
                await ctx.ringkas_transaksi(akhir, mulai)
            with self.assertRaises(ValueError):
                await ctx.transactions(mulai, akhir, pendamping="kontak")
            with self.assertRaises(ValueError):
                await ctx.incomes(mulai, akhir, pendamping="txn_meta")
            # Batas kelompok: lebih dari MAKS_KELOMPOK gagal, tidak memotong.
            lama = ringkas.MAKS_KELOMPOK
            ringkas.MAKS_KELOMPOK = 1
            try:
                await self.isi_dua_bulan()
                with self.assertRaises(ValueError):
                    await ctx.ringkas_transaksi(mulai, akhir, per=("txn_meta.akun",))
            finally:
                ringkas.MAKS_KELOMPOK = lama

    # ── 5. laba rugi ──
    async def test_laba_rugi_dari_data(self):
        await self.pasang_aktif()
        b, a = await self.isi_dua_bulan()
        r = await self.p("GET", f"/laba-rugi?periode={b}", status=200)
        lr = r.json()
        self.assertEqual(lr["periode"], b)
        self.assertFalse(lr["berjalan"])
        self.assertEqual(lr["omzet"], "1770000.00")                     # 1,5 jt penjualan + 270 rb tanpa jenis
        self.assertEqual(lr["jumlah_penjualan"], 4)
        self.assertEqual(lr["omzet_tanpa_jenis"], {"jumlah": "270000.00", "banyak": 2})
        self.assertEqual([(x["akun"], x["jumlah"], x["banyak"]) for x in lr["beban"]],
                         [("Bahan baku", "400000.00", 1), ("Gaji", "300000.00", 1),
                          (metrics.BELUM_BERAKUN, "85000.00", 3)])
        self.assertEqual(lr["beban_total"], "785000.00")
        self.assertEqual(lr["laba"], "985000.00")
        self.assertEqual(lr["margin"], "0.5565")
        self.assertEqual({x["jenis"]: x["jumlah"] for x in lr["di_luar_laba_rugi"]},
                         {"prive": "300000.00", "modal": "5000000.00", "pinjaman": "2000000.00", "lain": "0"})
        self.assertEqual(lr["banding"], {"periode": a, "omzet": "1000000.00", "beban_total": "600000.00",
                                         "laba": "400000.00", "margin": "0.4000"})
        self.assertEqual(lr["perubahan"], {"omzet": "0.7700", "beban_total": "0.3083", "laba": "1.4625"})
        self.assertEqual(lr["prive_dari_laba"], "0.3046")

        # Bulan ini (bawaan): modal awal U2 tanpa jenis = omzet tanpa jenis; penjualan baru lewat form ikut.
        await self.atur_a3()
        await self.p("POST", "/penjualan", status=201, json={"jumlah": 250000})
        now = (await self.p("GET", "/laba-rugi", status=200)).json()
        self.assertTrue(now["berjalan"])
        self.assertEqual(now["omzet"], "3250000.00")
        self.assertEqual(now["omzet_tanpa_jenis"]["jumlah"], "3000000.00")
        self.assertEqual(now["banding"]["periode"], b)

    async def test_laba_rugi_dijaga(self):
        await self.pasang_aktif()
        for salah in ("2026-13", "kemarin", "2999-01"):
            r = await self.p("GET", f"/laba-rugi?periode={salah}", status=422)
            self.assertEqual(self.kode(r), "nilai_tidak_sah")
        self.current = self.karyawan
        r = await self.p("GET", "/laba-rugi", status=403)
        self.assertEqual(self.kode(r), "khusus_admin")
        r = await self.p("GET", "/laporan?format=csv", status=403)
        self.assertEqual(self.kode(r), "khusus_admin")
        self.current = self.admin
        await self.p("GET", "/laba-rugi", status=200)
        self.current = self.pemilik
        # Ruang usaha kedua tanpa Buku Usaha: 404, bukan angka ruang pertama.
        r = await self.p("GET", "/laba-rugi", hid=self.usaha2, status=404)
        self.assertEqual(self.kode(r), "plugin_tidak_aktif")

    async def test_izin_baca_baru_tidak_diberikan_diam_diam(self):
        await self.pasang_aktif()
        async with self.Session() as db:      # instalasi U2: tanpa izin baca transaksi/pemasukan
            inst = (await db.execute(select(PluginInstallation))).scalar_one()
            inst.granted_permissions = ["envelopes:read", "incomes:write"]
            await db.commit()
        self.assertEqual((await self.katalog())["buku_usaha"]["izin_baru"], ["transactions:read", "incomes:read"])
        for path in ("/laba-rugi", "/laporan?format=pdf"):
            r = await self.p("GET", path, status=403)
            self.assertEqual(self.kode(r), "tanpa_izin")
        await self.p("GET", "/alokasi", status=200)          # yang lama tetap jalan
        await self.aksi("izin", body={"izin": MANIFEST_BU["permissions"]})
        await self.p("GET", "/laba-rugi", status=200)

    # ── 6. laporan ──
    async def test_laporan_csv_aman_dan_diaudit(self):
        await self.pasang_aktif()
        b, _ = await self.isi_dua_bulan()
        r = await self.p("GET", f"/laporan?periode={b}&format=csv", status=200)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertEqual(r.headers["content-disposition"],
                         f'attachment; filename="jatahku-buku-usaha-laba-rugi-{b}.csv"')
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertIn("sandbox", r.headers["content-security-policy"])
        sel = [x for row in csv.reader(io.StringIO(r.content.decode("utf-8").lstrip("﻿"))) for x in row]
        self.assertIn("'=Bu Sari", sel)                         # nama pelanggan berawalan rumus
        self.assertIn("Penjualan · =Bu Sari", sel)              # tidak diawali karakter rumus: apa adanya
        self.assertIn("ayam =cmd", sel)
        self.assertNotIn("=Bu Sari", sel)
        self.assertNotIn("rahasia admin", sel)                   # privat admin tersamar
        self.assertNotIn("Transport", sel)                       # akunnya juga
        self.assertNotIn("777777.00", sel)                       # amplop pribadi
        self.assertIn("1770000.00", sel)
        async with self.Session() as db:
            log = (await db.execute(select(PluginAuditLog).where(PluginAuditLog.action == "laporan"))).scalars().all()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].detail, {"format": "csv", "rute": "/laporan"})
        self.assertEqual(log[0].actor_id, self.pemilik.id)

    async def test_laporan_pdf_dan_format(self):
        await self.pasang_aktif()
        b, _ = await self.isi_dua_bulan()
        r = await self.p("GET", f"/laporan?periode={b}", status=200)      # bawaan pdf
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF-"))
        self.assertIn(f"laba-rugi-{b}.pdf", r.headers["content-disposition"])
        r = await self.p("GET", "/laporan?format=xlsx", status=422)
        self.assertEqual(self.kode(r), "format_tidak_dikenal")
        r = await self.p("GET", "/laporan?periode=2026-99", status=422)
        self.assertEqual(self.kode(r), "nilai_tidak_sah")


if __name__ == "__main__":
    unittest.main()
