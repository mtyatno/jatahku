"""Plugin U3 — review keamanan PR #204 (03-workflow.md "Keamanan lebih dulu"; AGENTS.md "Plugin dan ruang").

Temuan (tes ini merah sebelum perbaikan di branch `plugin/u3-review-keamanan`):

- **S1 (sedang) laporan menahan koneksi dan tanpa batas frekuensi.** `GET /p/<id>/laporan` menggambar PDF (detik,
  bukan milidetik, untuk ±2.000 baris) di dalam transaksi database permintaan, sambil mengantre semafor PDF dua slot
  milik laporan berkala, tanpa batas frekuensi. Satu owner/admin ruang usaha bisa menghabiskan kolam koneksi (5 + 10)
  seluruh API dan menahan unduhan laporan berkala semua user.
- **S2 (sedang) rumus lewat `;` di CSV.** `_csv_text` (PR #136) hanya melihat huruf pertama sel. Excel dengan pemisah
  daftar `;` (bawaan regional Indonesia) memecah baris berkoma pada `;`, jadi keterangan `ayam;=1+1;` yang ditulis
  karyawan menjadi sel rumus di lembar kerja pemilik.
- **R1 (rendah) angka sel tak terbatas dan galat gambar mentah.** `periksa` meloloskan `Decimal` NaN/Infinity dan
  bereksponen raksasa (`1E+200000` = sel CSV 200 KB; PDF `decimal.InvalidOperation` yang tidak ditangkap, 500 mentah
  tanpa `kode`).

Probe yang lulus sejak awal (dijaga supaya tetap begitu): nama kelompok dan kolom `ringkas_*`, baris pendamping
ruang lain, konteks job, transaksi privat di semua kolom pendamping, karyawan, ruang keluarga, `Laporan` dari rute
non-GET, dan izin baru lewat jeda/lanjut/pasang ulang.

Run: python -m unittest app.tests.test_plugin_u3_review -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import csv
import importlib.util
import io
import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from app.plugins.host import berkas
from app.plugins.sdk import Laporan, TabelLaporan

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
RUMUS = ("=", "+", "-", "@")


def _lap(baris, *, fmt="csv", kolom=("Tanggal", "Keterangan", "Jumlah"), **isi):
    return Laporan(format=fmt, nama_berkas="uji", judul="Laba rugi",
                   tabel=(TabelLaporan(judul="Pengeluaran", kolom=kolom, baris=tuple(baris)),), **isi)


# ── S2, R1: berkas host (murni) ──────────────────────────────────────────
class BerkasReviewTests(unittest.TestCase):
    def test_csv_pemisah_titik_koma_tidak_membuka_rumus(self):
        """Dibaca seperti Excel berpemisah `;`: tidak ada sel yang diawali karakter rumus, dari bagian mana pun."""
        lap = Laporan(
            format="csv", nama_berkas="uji", judul="Laba rugi;=1+1", subjudul="Dapur;=2*3; · 1 Okt 2026",
            ringkasan=(("Omzet;@SUM(A1:A9)", D("1")), ("Margin", "x;-1")),
            tabel=(TabelLaporan(
                judul="Pengeluaran;+1", kolom=("Tanggal", "Keterangan;=9", "Jumlah"),
                baris=((date(2026, 10, 1), "ayam;=1+1;", D("25000")),
                       (date(2026, 10, 2), "x;@SUM(A1:A9);", D("1")),
                       (date(2026, 10, 3), "y; -2+3", D("1")),
                       (date(2026, 10, 4), "z;+cmd|'/c calc'!A1;", D("1")),
                       (date(2026, 10, 5), "a;\t=1+1", D("1")),
                       (date(2026, 10, 6), "b;;=1+1", D("1"))),
                total=("Total;-1", None, D("5")), catatan="catatan;=7"),),
            catatan=("penutup;=8",))
        berkas.periksa(lap)
        teks = berkas.render_csv(lap, ruang="Dapur;=2*3;").decode("utf-8").lstrip("﻿")
        rumus = [sel for baris in csv.reader(io.StringIO(teks), delimiter=";") for sel in baris
                 if sel.lstrip().startswith(RUMUS)]
        self.assertEqual(rumus, [])
        # Dibaca dengan koma (pemisah yang sebenarnya) juga tetap aman, dan teks biasa ber-`;` tidak berubah.
        biasa = _lap([(date(2026, 10, 1), "ayam; bebek; 2 kg", D("1"))])
        sel = [x for b in csv.reader(io.StringIO(berkas.render_csv(biasa, ruang="R").decode("utf-8"))) for x in b]
        self.assertIn("ayam; bebek; 2 kg", sel)

    def test_angka_sel_harus_terhingga_dan_wajar(self):
        """`Decimal`/`int` di sel dibatasi: NaN, Infinity, dan nilai yang teksnya ribuan huruf ditolak `periksa`
        (500 `plugin_gagal`), bukan menjadi sel raksasa atau galat mentah saat digambar."""
        for v in (D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), D("1E+200000"), D("1E-200000"),
                  D("0E-200000"), D("1E+999999999"), D("-1E+999999999"), D("1E+18"), 10 ** 18, -(10 ** 18)):
            for lap in (_lap([(date(2026, 10, 1), "a", v)]), _lap([], ringkasan=(("Omzet", v),))):
                with self.assertRaises((TypeError, ValueError), msg=repr(v)[:40]):
                    berkas.periksa(lap)
        for v in (D("0"), D("9999999999999.99"), D("-9999999999999.99"), D("0.2539"), D("785000.0"), 10 ** 12, -5):
            berkas.periksa(_lap([(date(2026, 10, 1), "a", v)], ringkasan=(("Omzet", v),)))


# ── SQLite ───────────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.routes import plugins as plugins_route
    from app.api.routes.auth import limiter
    from app.models.models import (
        BukuUsahaIncomeMeta, BukuUsahaKontak, BukuUsahaTxnMeta, Household, Income, PluginAuditLog,
        PluginInstallation, Transaction,
    )
    from app.plugins.buku_usaha import metrics
    from app.plugins.host import titik
    from app.plugins.sdk import IzinDitolak
    from app.plugins.sdk.plugin import Pendaftaran
    # Modulnya, bukan kelasnya: kelas tes di namespace modul ini akan ikut dijalankan lagi oleh unittest.
    from app.tests import test_plugin_u2 as u2
    MANIFEST_BU = u2.MANIFEST_BU
    IZIN_BACA = ("envelopes:read", "transactions:read", "incomes:read")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class U3ReviewDbTests(unittest.IsolatedAsyncioTestCase):
    """Penyiapan U2: ruang usaha Dapur Nusa (pemilik, admin, karyawan; 5 amplop bersama + amplop pribadi pemilik),
    ruang usaha kedua, dan ruang keluarga pemilik."""
    if HAS_AIOSQLITE:
        _siap_u2 = u2.U2DbTests.asyncSetUp
        hdr, aksi, pasang_aktif, p, kode, hitung, katalog, _ctx = (
            u2.U2DbTests.hdr, u2.U2DbTests.aksi, u2.U2DbTests.pasang_aktif, u2.U2DbTests.p, u2.U2DbTests.kode,
            u2.U2DbTests.hitung, u2.U2DbTests.katalog, u2.U2DbTests._ctx)

    async def asyncSetUp(self):
        await self._siap_u2()
        # Batas frekuensi memakai penyimpanan bersama proses: tiap tes mulai dan berakhir dengan ember kosong.
        limiter.reset()
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", limiter.enabled)
        limiter.enabled = True
        b = metrics.bulan_lalu(self.today.year, self.today.month)
        self.periode = metrics.kunci(*b)
        self.mulai, self.akhir = metrics.rentang(*b)

    async def audit(self, aksi="laporan"):
        async with self.Session() as db:
            return (await db.execute(select(PluginAuditLog).where(PluginAuditLog.action == aksi))).scalars().all()

    async def trx(self, env, jumlah, *, user=None, privat=False, akun=None, pemasok=None, proyek=None, ket="belanja",
                  meta_hid=None):
        async with self.Session() as db:
            t = Transaction(envelope_id=env, user_id=(user or self.pemilik).id, amount=D(jumlah), description=ket,
                            transaction_date=self.mulai, is_private=privat)
            db.add(t)
            await db.flush()
            if akun or pemasok or proyek:
                db.add(BukuUsahaTxnMeta(household_id=meta_hid or self.usaha, transaction_id=t.id, akun=akun,
                                        kontak_id=pemasok, proyek=proyek))
            await db.commit()
            return t.id

    def ctx_job(self, db, ruang_obj, izin=IZIN_BACA):
        """Konteks tanpa user (job terjadwal), seperti `titik` membuatnya."""
        inst = PluginInstallation(household_id=ruang_obj.id, plugin_id="buku_usaha", status="active",
                                  granted_permissions=list(izin))
        d = Pendaftaran("job", "uji", lambda *a: None, tuple(izin))
        return titik.konteks(db, self.reg.get("buku_usaha"), inst, ruang_obj, d, viewer=None, sumber="uji")

    # ── S1: koneksi database dan batas frekuensi ──
    async def test_laporan_melepas_koneksi_database_sebelum_menggambar(self):
        """Menggambar PDF menunggu giliran semafor (dua slot, bersama laporan berkala) dan makan detik untuk ribuan
        baris; koneksi dari kolam (5 + 10 untuk seluruh API) tidak boleh tertahan selama itu."""
        await self.pasang_aktif()
        urutan = []
        asli_tutup = AsyncSession.close

        async def tutup(sesi):
            urutan.append("tutup")
            return await asli_tutup(sesi)

        def gambar(lap, *, ruang, dibuat):
            urutan.append("gambar")
            return b"%PDF-1.7 palsu"

        with patch.object(AsyncSession, "close", tutup), patch.object(berkas, "render_pdf", gambar):
            r = await self.p("GET", f"/laporan?periode={self.periode}&format=pdf", status=200)
        self.assertEqual(r.content, b"%PDF-1.7 palsu")
        self.assertIn("gambar", urutan)
        self.assertLess(urutan.index("tutup"), urutan.index("gambar"), urutan)
        self.assertEqual(len(await self.audit()), 1)          # unduhan tetap diaudit

    async def test_laporan_dibatasi_per_user(self):
        """Paling banyak 10 berkas laporan per menit per user (PDF dan CSV satu ember); sesudah itu 429 tanpa
        menggambar dan tanpa audit. Rute plugin lain dan user lain tidak ikut terbatas."""
        await self.pasang_aktif()
        digambar = []

        def gambar(lap, *, ruang, dibuat):
            digambar.append(1)
            return b"%PDF-1.7 palsu"

        with patch.object(berkas, "render_pdf", gambar):
            for n in range(10):
                fmt = "pdf" if n % 2 else "csv"
                await self.p("GET", f"/laporan?periode={self.periode}&format={fmt}", status=200)
            for fmt in ("pdf", "csv"):
                r = await self.p("GET", f"/laporan?periode={self.periode}&format={fmt}")
                self.assertEqual(r.status_code, 429, r.text)
                self.assertEqual(self.kode(r), "terlalu_sering")
                self.assertNotIn(b"%PDF", r.content)
            self.assertEqual(len(digambar), 5)
            self.assertEqual(len(await self.audit()), 10)
            await self.p("GET", "/laba-rugi", status=200)             # angka di layar tidak ikut terbatas
            self.current = self.admin                                  # ember per user
            await self.p("GET", f"/laporan?periode={self.periode}&format=pdf", status=200)

    # ── R1: galat saat menggambar ──
    async def test_galat_menggambar_menjadi_plugin_gagal(self):
        """Galat apa pun saat menggambar (fpdf2, aritmetika Decimal) dijawab 500 `plugin_gagal` seperti laporan tidak
        sah lainnya, bukan galat mentah tanpa `kode`."""
        await self.pasang_aktif()

        def gambar(lap, *, ruang, dibuat):
            raise ArithmeticError("fpdf2 gagal")

        with patch.object(berkas, "render_pdf", gambar), self.assertLogs("jatahku.plugins", level="ERROR") as log:
            r = await self.p("GET", f"/laporan?periode={self.periode}&format=pdf")
        self.assertIn("laporan plugin buku_usaha (pdf) gagal digambar", log.output[0])
        self.assertEqual(r.status_code, 500, r.text)
        self.assertTrue(r.headers.get("content-type", "").startswith("application/json"), r.text)
        self.assertEqual(self.kode(r), "plugin_gagal", r.text)
        self.assertNotIn("fpdf2 gagal", r.text)

    # ── probe: Laporan hanya dari rute GET ──
    async def test_probe_laporan_dari_rute_non_get_ditolak_tanpa_menulis(self):
        await self.pasang_aktif()
        asli = titik.panggil

        async def panggil(ctx, fn, *a):
            await asli(ctx, fn, *a)                       # fungsi plugin sungguhan menulis kontak dulu
            return Laporan(format="csv", nama_berkas="x", judul="x")

        with patch.object(titik, "panggil", panggil):
            r = await self.p("POST", "/kontak", json={"nama": "Bu Sari", "peran": "pelanggan"})
        self.assertEqual(r.status_code, 500, r.text)
        self.assertEqual(self.kode(r), "plugin_gagal")
        self.assertNotIn("content-disposition", r.headers)
        self.assertEqual(await self.hitung(BukuUsahaKontak), 0)       # tulisan plugin ikut batal
        self.assertEqual(await self.audit(), [])
        self.assertEqual(await self.audit("data:tambah"), [])

    # ── probe: agregat dan baris pendamping ──
    async def test_probe_ringkas_nama_kelompok_dan_kolom(self):
        """Nama kelompok tidak pernah menjadi SQL: hanya `bulan`, `amplop`/`jenis`, atau entitas pendamping plugin
        sendiri dengan kolom bukan milik host. Selain itu `ValueError`, apa pun bentuknya."""
        await self.trx(self.env["Operasional"], "1000", akun="Gaji")
        buruk_transaksi = (
            "txn_meta.akun; DROP TABLE users", "txn_meta.akun--", "txn_meta.akun OR 1=1", "TXN_META.akun",
            "txn_meta.Akun", "txn_meta.akun ", " txn_meta.akun", "txn_meta.akun.x", "txn_meta.", ".akun", "txn_meta",
            "txn_meta.id", "txn_meta.household_id", "txn_meta.created_by", "txn_meta.created_at",
            "txn_meta.updated_at", "txn_meta.deleted_at", "txn_meta.transaction_id", "txn_meta.__table__",
            "p_buku_usaha_txn_meta.created_by", "p_buku_usaha_kontak.telepon", "kontak.telepon", "alokasi.persen",
            "income_meta.jenis", "transactions.description", "users.email", "envelopes.name", "households.name",
            "p_lain_txn_meta.akun", "jenis", "", 1, None, b"bulan", ("bulan",))
        buruk_pemasukan = (
            "income_meta.income_id", "income_meta.created_by", "income_meta.household_id", "income_meta.jenis'--",
            "txn_meta.akun", "kontak.nama", "incomes.description", "users.email", "amplop", "", 7, None)
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False)
            for per in buruk_transaksi:
                with self.assertRaises(ValueError, msg=repr(per)):
                    await ctx.ringkas_transaksi(self.mulai, self.akhir, per=(per,))
            for per in buruk_pemasukan:
                with self.assertRaises(ValueError, msg=repr(per)):
                    await ctx.ringkas_pemasukan(self.mulai, self.akhir, per=(per,))
            for pendamping in ("kontak", "alokasi", "income_meta", "p_lain_x", "txn_meta; --", "users", 5):
                with self.assertRaises(ValueError, msg=repr(pendamping)):
                    await ctx.transactions(self.mulai, self.akhir, pendamping=pendamping)
            # Yang sah tetap jalan, dan tabel inti utuh sesudah semua percobaan di atas.
            t = await ctx.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun", "p_buku_usaha_txn_meta.proyek"))
            self.assertEqual([(r.kunci, r.jumlah) for r in t], [(("Gaji", None), D("1000"))])
        self.assertEqual(await self.hitung(Transaction), 1)

    async def test_probe_transaksi_privat_tersamar_di_semua_kolom_pendamping(self):
        """Privat milik anggota lain: akun, pemasok, dan proyek tidak terbaca lewat kelompok mana pun maupun `meta`;
        nominal dan amplop tetap (kontrak visibilitas). Pemiliknya sendiri membacanya."""
        async with self.Session() as db:
            pemasok = BukuUsahaKontak(household_id=self.usaha, nama="UD Rahasia", peran="pemasok")
            db.add(pemasok)
            await db.commit()
        op = self.env["Operasional"]
        await self.trx(op, "25000", user=self.admin, privat=True, akun="Transport", pemasok=pemasok.id,
                       proyek="Proyek rahasia", ket="rahasia admin")
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False)                      # pemilik melihat
            for per in (("txn_meta.akun",), ("txn_meta.kontak_id",), ("txn_meta.proyek",),
                        ("txn_meta.akun", "txn_meta.kontak_id", "txn_meta.proyek")):
                t = await ctx.ringkas_transaksi(self.mulai, self.akhir, per=per)
                self.assertEqual([(r.kunci, r.jumlah, r.banyak) for r in t],
                                 [((None,) * len(per), D("25000"), 1)], per)
            t = await ctx.ringkas_transaksi(self.mulai, self.akhir, per=("amplop", "bulan", "txn_meta.proyek"))
            self.assertEqual([r.kunci for r in t], [(op, self.periode, None)])
            baris = await ctx.transactions(self.mulai, self.akhir, pendamping="txn_meta")
            self.assertEqual([(b.deskripsi, b.meta, b.jumlah) for b in baris], [("Transaksi privat", None, D("25000"))])
            admin = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, user=self.admin, peran="admin")
            t = await admin.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun", "txn_meta.proyek"))
            self.assertEqual([r.kunci for r in t], [("Transport", "Proyek rahasia")])
        # Lewat rute: laba rugi dan laporan CSV pemilik tidak memuat akun, pemasok, proyek, atau keterangannya.
        await self.pasang_aktif()
        lr = (await self.p("GET", f"/laba-rugi?periode={self.periode}", status=200)).json()
        self.assertEqual([(x["akun"], x["jumlah"]) for x in lr["beban"]], [(metrics.BELUM_BERAKUN, "25000.00")])
        isi = (await self.p("GET", f"/laporan?periode={self.periode}&format=csv", status=200)).content.decode("utf-8")
        for rahasia in ("Transport", "UD Rahasia", "Proyek rahasia", "rahasia admin"):
            self.assertNotIn(rahasia, isi)
        self.assertIn("Transaksi privat", isi)

    async def test_probe_baris_pendamping_ruang_lain_tidak_terbaca(self):
        """Baris pendamping yang `household_id`-nya bukan ruang konteks tidak pernah tergabung, walau menunjuk
        transaksi ruang konteks (dan sebaliknya); amplop pribadi dan ruang lain tidak terjumlah."""
        op = self.env["Operasional"]
        await self.trx(op, "1000", akun="Gaji", meta_hid=self.usaha2)                # meta ruang lain → transaksi sini
        await self.trx(self.env_lain, "2000", akun="Sewa", meta_hid=self.usaha)      # meta sini → transaksi ruang lain
        await self.trx(self.pribadi, "4000", akun="Listrik & air")                   # amplop pribadi pemilik
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, user=self.admin, peran="admin")
            t = await ctx.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun",))
            self.assertEqual([(r.kunci, r.jumlah) for r in t], [((None,), D("1000"))])   # admin: tanpa amplop pribadi pemilik
            baris = await ctx.transactions(self.mulai, self.akhir, pendamping="txn_meta")
            self.assertEqual([(b.jumlah, b.meta) for b in baris], [(D("1000"), None)])
            lain = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, hid=self.usaha2)
            t = await lain.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun",))
            self.assertEqual([(r.kunci, r.jumlah) for r in t], [((None,), D("2000"))])
            pemilik = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False)
            t = await pemilik.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun",), hanya_bersama=True)
            self.assertEqual(sum(r.jumlah for r in t), D("1000"))                     # hanya_bersama: pribadi tidak

    async def test_probe_konteks_job_dan_ruang_keluarga(self):
        """Job (tanpa user): hanya amplop bersama, semua transaksi privat tersamar, pemasukan ruang keluarga tidak
        terbaca. Ruang keluarga dengan viewer: hanya pemasukan miliknya."""
        op = self.env["Operasional"]
        await self.trx(op, "1000", akun="Gaji")
        await self.trx(op, "2000", privat=True, akun="Sewa")                # privat milik pemilik sekalipun
        await self.trx(self.pribadi, "4000", akun="Listrik & air")
        async with self.Session() as db:
            job = self.ctx_job(db, await db.get(Household, self.usaha))
            t = await job.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun",))
            self.assertEqual({r.kunci[0]: r.jumlah for r in t}, {"Gaji": D("1000"), None: D("2000")})
            baris = await job.transactions(self.mulai, self.akhir, pendamping="txn_meta")
            self.assertEqual(sorted((b.jumlah, (b.meta or {}).get("akun")) for b in baris),
                             [(D("1000"), "Gaji"), (D("2000"), None)])
            self.assertTrue(all(b.deskripsi == "Transaksi privat" for b in baris))
            rumah = self.ctx_job(db, await db.get(Household, self.rumah))
            p = await rumah.ringkas_pemasukan(date(2000, 1, 1), self.today, per=("jenis",))
            self.assertEqual(p, [])
            self.assertEqual(await rumah.incomes(date(2000, 1, 1), self.today, pendamping="income_meta"), [])
            # Ruang keluarga, viewer bukan pencatat pemasukan: tidak ada yang terbaca; pencatatnya membaca miliknya.
            tamu = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, user=self.admin, peran="member", hid=self.rumah)
            p = await tamu.ringkas_pemasukan(date(2000, 1, 1), self.today)
            self.assertEqual([(r.jumlah, r.banyak, r.dialokasikan) for r in p], [(D("0"), 0, D("0"))])
            sendiri = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, hid=self.rumah)
            p = await sendiri.ringkas_pemasukan(date(2000, 1, 1), self.today)
            self.assertEqual([(r.jumlah, r.banyak) for r in p], [(D("1000000"), 1)])

    async def test_probe_karyawan_tidak_membaca_baris_pendamping(self):
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=IZIN_BACA, boleh_tulis=False, user=self.karyawan, peran="member")
            for panggil in (ctx.transactions(self.mulai, self.akhir, pendamping="txn_meta"),
                            ctx.incomes(self.mulai, self.akhir, pendamping="income_meta"),
                            ctx.ringkas_pemasukan(self.mulai, self.akhir, per=("income_meta.jenis",)),
                            ctx.ringkas_transaksi(self.mulai, self.akhir, per=("txn_meta.akun",)),
                            ctx.data("txn_meta").cari(), ctx.data("income_meta").cari()):
                with self.assertRaises(IzinDitolak) as cm:
                    await panggil
                self.assertEqual(cm.exception.alasan, "khusus_admin")
        await self.pasang_aktif()
        self.current = self.karyawan
        for path in ("/laba-rugi", "/laporan", "/laporan?format=csv", f"/laporan?periode={self.periode}&format=pdf"):
            r = await self.p("GET", path, status=403)
            self.assertEqual(self.kode(r), "khusus_admin")
            self.assertNotIn("content-disposition", r.headers)
        self.assertEqual(await self.audit(), [])

    # ── probe: izin baru ──
    async def test_probe_izin_baru_tidak_terbuka_lewat_jeda_lanjut_atau_pasang_ulang(self):
        await self.pasang_aktif()
        lama = ["envelopes:read", "incomes:write"]
        async with self.Session() as db:      # instalasi sebelum U3
            inst = (await db.execute(select(PluginInstallation))).scalar_one()
            inst.granted_permissions = list(lama)
            await db.commit()
        await self.aksi("jeda")
        await self.aksi("lanjut")
        await self.aksi("pasang", body={"izin": MANIFEST_BU["permissions"]})      # sudah terpasang: tidak mengubah izin
        await self.aksi("izin", body={"izin": lama}, status=409)                   # daftar lama ≠ manifest sekarang
        self.assertEqual((await self.katalog())["buku_usaha"]["izin_baru"], ["transactions:read", "incomes:read"])
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(PluginInstallation))).scalar_one().granted_permissions, lama)
        for path in ("/laba-rugi", "/laporan?format=pdf", "/laporan?format=csv"):
            r = await self.p("GET", path, status=403)
            self.assertEqual(self.kode(r), "tanpa_izin")
        self.assertEqual(await self.audit(), [])
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 1)   # hanya modal awal penyiapan
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 0)


if __name__ == "__main__":
    unittest.main()
