"""Plugin U4 — kartu Beranda Buku Usaha dan arus kas (03-workflow.md baris U4; 04-kontrak-api.md §4, §5 "Baca untuk
kartu", §6 "Kartu Beranda"; AGENTS.md "Plugin dan ruang" aturan 3, 4, 6, 7; ADR-P3, P8).

1. Host/SDK (Plugin API 1.5): kelompok `tanggal` di baca agregat; saldo amplop (`envelopes(saldo=True)`);
   `ringkas_pemasukan_saya` (hanya catatan milik viewer, satu-satunya baca keuangan yang terbuka untuk karyawan);
   kartu manifest `untuk`.
2. Angka murni kartu (`buku_usaha/metrics.py`): bulan kartu, minggu arus kas, alokasi omzet, pelanggan teratas.
3. Kartu lewat `/dashboard/*`: delapan kartu dari data nyata; karyawan hanya `penjualan_saya` dan hanya catatannya
   sendiri; pemilik tidak memuat kartu karyawan; plugin dijeda = kartu hilang; ruang lain tidak terbaca.
4. Anggaran waktu: setiap penyedia ≤ 150 ms dengan data 12 bulan.

Run: python -m unittest app.tests.test_plugin_u4 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from app.plugins.buku_usaha import kartu as kartu_bu
from app.plugins.buku_usaha import metrics, teks
from app.plugins.host import manifest as mf
from app.plugins.host import titik
from app.plugins.sdk import AmplopView, IzinDitolak, PeriodeView, RingkasanView

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    from app.models.models import (
        Allocation, BukuUsahaIncomeMeta, BukuUsahaKontak, BukuUsahaTxnMeta, Envelope, Income, Transaction,
    )
    from app.plugins.host import keadaan
    from app.tests import test_plugin_u2 as u2

BACA = ("envelopes:read", "transactions:read", "incomes:read")


def R(kunci, jumlah, banyak=1, dialokasikan=D(0)):
    return RingkasanView(kunci=kunci, jumlah=D(jumlah), banyak=banyak, dialokasikan=D(dialokasikan))


def A(id_, nama, sisa, *, pribadi=False, tujuan="expense"):
    return AmplopView(id=id_, nama=nama, emoji="", tujuan=tujuan, anggaran=D(0), pribadi=pribadi, dikunci=False,
                      sisa=None if sisa is None else D(sisa))


# ── 2. angka murni kartu ─────────────────────────────────────────────────
class BulanKartuTests(unittest.TestCase):
    def test_periode_berjalan_memakai_bulan_ini(self):
        p = PeriodeView(start=date(2026, 10, 27), end=date(2026, 11, 26), berjalan=True)
        self.assertEqual(metrics.bulan_kartu(p, date(2026, 11, 12)), (2026, 11))
        self.assertEqual(metrics.bulan_kartu(p, date(2026, 10, 30)), (2026, 10))

    def test_periode_lampau_memakai_bulan_tanggal_akhirnya(self):
        p = PeriodeView(start=date(2026, 9, 1), end=date(2026, 9, 30), berjalan=False)
        self.assertEqual(metrics.bulan_kartu(p, date(2026, 11, 12)), (2026, 9))

    def test_periode_di_depan_tidak_melewati_bulan_ini(self):
        p = PeriodeView(start=date(2026, 11, 27), end=date(2026, 12, 26), berjalan=False)
        self.assertEqual(metrics.bulan_kartu(p, date(2026, 11, 12)), (2026, 11))


class ArusKasTests(unittest.TestCase):
    def test_tiga_belas_minggu_senin_sampai_minggu(self):
        m = metrics.minggu(date(2026, 11, 12))                    # Kamis
        self.assertEqual(len(m), 13)
        self.assertEqual(m[-1], (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(m[0], (date(2026, 8, 17), date(2026, 8, 23)))
        self.assertTrue(all(a.weekday() == 0 and (b - a).days == 6 for a, b in m))
        self.assertEqual(metrics.minggu(date(2026, 11, 9))[-1][0], date(2026, 11, 9))     # Senin
        self.assertEqual(metrics.minggu(date(2026, 11, 15))[-1][0], date(2026, 11, 9))    # Minggu

    def test_masuk_semua_pemasukan_keluar_belanja_dan_prive(self):
        m = metrics.minggu(date(2026, 11, 12))
        transaksi = [R((date(2026, 11, 9),), "300000", 2), R((date(2026, 11, 15),), "50000"),
                     R((date(2026, 11, 2),), "70000"), R((date(2026, 8, 16),), "999")]           # di luar rentang
        pemasukan = [R((date(2026, 11, 10), "pemasukan"), "1000000", 3),                          # penjualan, modal, …
                     R((date(2026, 11, 10), "top-up"), "200000"),
                     R((date(2026, 11, 11), "prive"), "0", 1, dialokasikan="-400000"),            # prive = keluar
                     R((date(2026, 11, 11), "transfer"), "0", 1),
                     R((date(2026, 11, 11), "penyesuaian"), "75000"),                             # bukan arus kas
                     R((date(2026, 11, 3), "pemasukan"), "10000")]
        a = metrics.arus_kas(m, transaksi, pemasukan)
        self.assertEqual(len(a), 13)
        self.assertEqual((a[-1]["mulai"], a[-1]["masuk"], a[-1]["keluar"]),
                         (date(2026, 11, 9), D("1200000"), D("750000")))
        self.assertEqual((a[-2]["masuk"], a[-2]["keluar"]), (D("10000"), D("70000")))
        self.assertEqual((a[0]["masuk"], a[0]["keluar"]), (D(0), D(0)))
        self.assertEqual(sum(x["keluar"] for x in a), D("820000"))                                # 999 tidak ikut


class AngkaKartuTests(unittest.TestCase):
    def test_kas_hanya_amplop_bersama(self):
        k = metrics.kas([A(1, "Bahan", "5000000"), A(2, "Operasional", "-305000"), A(3, "Pajak", "0"),
                         A(4, "Pribadi", "999", pribadi=True)])
        self.assertEqual(k, {"jumlah": D("4695000"), "amplop": 3, "minus": 1})

    def test_alokasi_jatah_persis_dan_lewat(self):
        aturan = [{"envelope_id": "b", "nama": "Bahan", "persen": D(45), "tujuan": "expense"},
                  {"envelope_id": "o", "nama": "Operasional", "persen": D(30), "tujuan": "expense"},
                  {"envelope_id": "p", "nama": "Prive", "persen": D(15), "tujuan": "saving"},
                  {"envelope_id": "l", "nama": "Laba ditahan", "persen": D(9), "tujuan": "saving"},
                  {"envelope_id": "x", "nama": "Pajak", "persen": D(1), "tujuan": "saving"}]
        h = metrics.alokasi_omzet(aturan, D("48650000"), {"b": D("21000000"), "o": D("14900000")})
        self.assertEqual(sum(x["jatah"] for x in h), D("48650000"))
        self.assertEqual([(x["nama"], x["jatah"], x["terpakai"], x["lewat"]) for x in h[:2]],
                         [("Bahan", D("21892500"), D("21000000"), D(0)),
                          ("Operasional", D("14595000"), D("14900000"), D("305000"))])
        self.assertEqual((h[2]["terpakai"], h[2]["lewat"]), (D(0), D(0)))

    def test_alokasi_tanpa_aturan_atau_bukan_100(self):
        self.assertEqual(metrics.alokasi_omzet([], D("100"), {}), [])
        self.assertEqual(metrics.alokasi_omzet([{"envelope_id": "b", "nama": "Bahan", "persen": D(45),
                                                 "tujuan": "expense"}], D("100"), {}), [])

    def test_pelanggan_teratas(self):
        baris = [R(("penjualan", "k1"), "300000", 2), R(("penjualan", "k2"), "900000", 1),
                 R(("penjualan", None), "5000000", 9),          # tanpa pelanggan: tidak ikut
                 R(("modal", "k3"), "9999999"),                 # bukan penjualan
                 R((None, None), "123"),
                 R(("penjualan", "k4"), "300000", 5), R(("penjualan", "k5"), "1"), R(("penjualan", "k6"), "2"),
                 R(("penjualan", "k7"), "3")]
        h = metrics.pelanggan_teratas(baris)
        self.assertEqual([(x["kontak_id"], x["jumlah"], x["banyak"]) for x in h],
                         [("k2", D("900000"), 1), ("k4", D("300000"), 5), ("k1", D("300000"), 2),
                          ("k7", D("3"), 1), ("k6", D("2"), 1)])

    def test_penjualan_saya_tanpa_modal_dan_prive(self):
        baris = [R(("pemasukan", "penjualan"), "50000", 1), R(("pemasukan", None), "150000", 2),
                 R(("top-up", None), "10000", 1), R(("pemasukan", "modal"), "9000000", 1),
                 R(("prive", None), "0", 1, dialokasikan="-100"), R(("transfer", None), "0", 1)]
        self.assertEqual(metrics.penjualan_saya(baris), {"jumlah": D("210000"), "banyak": 4})


class BentukKartuTests(unittest.TestCase):
    """Bentuk yang keluar dari `kartu.py` lolos pemeriksa host (`titik.rapikan_kartu`), dengan data contoh kanvas."""
    LR = None

    def setUp(self):
        pemasukan = [R(("2026-10", "pemasukan", "penjualan"), "48650000", 112),
                     R(("2026-09", "pemasukan", "penjualan"), "44600000", 101)]
        transaksi = [R(("2026-10", "Bahan baku"), "21800000"), R(("2026-10", "Gaji"), "9000000"),
                     R(("2026-10", None), "5500000"), R(("2026-09", "Bahan baku"), "34950000")]
        self.lr = metrics.susun(2026, 10, metrics.hitung_bulan("2026-10", transaksi, pemasukan),
                                metrics.hitung_bulan("2026-09", transaksi, pemasukan), date(2026, 11, 2))

    def sah(self, shape, data):
        return titik.rapikan_kartu(shape, data, "buku_usaha")

    def test_omzet(self):
        d = self.sah("kpi", kartu_bu.omzet(self.lr))
        self.assertEqual((d["value"], d["unit"], d["suffix"], d["chip"]), ("48650000", "rp", "112 penjualan", "+9,1%"))
        self.assertIn("Oktober 2026", d["footer"])

    def test_laba_dan_rugi(self):
        d = self.sah("kpi", kartu_bu.laba(self.lr))
        self.assertEqual((d["value"], d["suffix"], d["chip"], d["tone"]), ("12350000", "margin 25,4%", "+28%", None))
        rugi = metrics.susun(2026, 10, metrics.hitung_bulan("2026-10", [R(("2026-10", "Sewa"), "500")], []),
                             metrics.hitung_bulan("2026-09", [], []), date(2026, 11, 2))
        d = self.sah("kpi", kartu_bu.laba(rugi))
        self.assertEqual((d["value"], d["tone"], d["chip"], d["suffix"]), ("-500", "danger", "", ""))

    def test_kas(self):
        d = self.sah("kpi", kartu_bu.kas({"jumlah": D("13755000"), "amplop": 5, "minus": 0}))
        self.assertEqual((d["value"], d["suffix"], d["tone"]), ("13755000", "5 amplop", None))
        d = self.sah("kpi", kartu_bu.kas({"jumlah": D("-1"), "amplop": 2, "minus": 1}))
        self.assertEqual(d["tone"], "danger")
        self.assertIn("1 amplop minus", d["footer"])

    def test_arus_kas_seri(self):
        m = metrics.minggu(date(2026, 11, 12))
        d = self.sah("series", kartu_bu.arus_kas(metrics.arus_kas(
            m, [R((date(2026, 11, 9),), "300000")], [R((date(2026, 11, 10), "pemasukan"), "1000000")])))
        self.assertEqual(len(d["x"]), 13)
        self.assertEqual((d["x"][0], d["x"][-1]), ("17 Agu", "9 Nov"))
        self.assertEqual([s["nama"] for s in d["series"]], ["Masuk", "Keluar"])
        self.assertEqual((d["series"][0]["values"][-1], d["series"][1]["values"][-1]), ("1000000", "300000"))

    def test_alokasi(self):
        baris = [{"nama": "Bahan", "persen": D(45), "tujuan": "expense", "jatah": D("450"), "terpakai": D("100"),
                  "lewat": D(0)},
                 {"nama": "Operasional", "persen": D("30.5"), "tujuan": "expense", "jatah": D("300"),
                  "terpakai": D("400"), "lewat": D("100")},
                 {"nama": "Pajak", "persen": D(1), "tujuan": "saving", "jatah": D("10"), "terpakai": D(0),
                  "lewat": D(0)}]
        d = self.sah("progress", kartu_bu.alokasi(baris))
        self.assertEqual([(i["label"], i["value"], i["target"], i["tone"]) for i in d["items"]],
                         [("Bahan · 45%", "100", "450", None), ("Operasional · 30,5%", "400", "300", "danger"),
                          ("Pajak · 1%", "10", None, None)])
        self.assertEqual(self.sah("progress", kartu_bu.alokasi([])), {"shape": "progress", "items": []})

    def test_beban_per_akun(self):
        d = self.sah("progress", kartu_bu.beban(self.lr))
        self.assertEqual([(i["label"], i["value"], i["target"]) for i in d["items"]],
                         [("Bahan baku", "21800000", "36300000"), ("Gaji", "9000000", "36300000"),
                          (metrics.BELUM_BERAKUN, "5500000", "36300000")])

    def test_pelanggan(self):
        d = self.sah("list", kartu_bu.pelanggan(
            [{"kontak_id": "k1", "jumlah": D("900000"), "banyak": 3}, {"kontak_id": "k2", "jumlah": D("5"), "banyak": 1}],
            {"k1": "PT Arunika Data"}))
        self.assertEqual([(i["judul"], i["subjudul"], i["nominal"]) for i in d["items"]],
                         [("PT Arunika Data", "3 penjualan", "900000"), ("Kontak terhapus", "1 penjualan", "5")])

    def test_penjualan_saya(self):
        d = self.sah("kpi", kartu_bu.penjualan_saya({"jumlah": D("210000"), "banyak": 4}, "2026-11"))
        self.assertEqual((d["value"], d["unit"], d["suffix"]), ("210000", "rp", "4 penjualan"))
        self.assertIn("November 2026", d["footer"])

    def test_bulan_berjalan_tanpa_chip_banding(self):
        """Bulan berjalan belum utuh: membandingkannya dengan bulan lalu yang utuh selalu tampak anjlok. Chip hanya
        untuk bulan yang sudah selesai; angka bulan lalu tetap ada di kaki kartu."""
        berjalan = {**self.lr, "berjalan": True}
        self.assertEqual(self.sah("kpi", kartu_bu.omzet(berjalan))["chip"], "")
        self.assertEqual(self.sah("kpi", kartu_bu.laba(berjalan))["chip"], "")
        self.assertIn("bulan lalu Rp44.600.000", self.sah("kpi", kartu_bu.omzet(berjalan))["footer"])

    def test_teks_perubahan(self):
        self.assertEqual([teks.perubahan(v) for v in (D("0.0908"), D("-0.125"), D("0"), None)],
                         ["+9,1%", "-12,5%", "0%", ""])


# ── 1a. manifest ─────────────────────────────────────────────────────────
class ManifestKartuTests(unittest.TestCase):
    def _kartu(self, **isi):
        return mf.Kartu(key="x.satu", title="Satu", shape="kpi", sizes=["S"], **isi)

    def test_untuk_bawaan_umum(self):
        self.assertEqual(self._kartu().untuk, "umum")

    def test_untuk_karyawan_diterima(self):
        self.assertEqual(self._kartu(untuk="karyawan").untuk, "karyawan")

    def test_untuk_lain_ditolak(self):
        with self.assertRaises(ValueError):
            self._kartu(untuk="admin")

    def test_plugin_api_1_5(self):
        self.assertEqual(mf.PLUGIN_API_VERSION[:2], (1, 5))


# ── 1b. host/SDK dengan database ─────────────────────────────────────────
@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class U4DbDasar(unittest.IsolatedAsyncioTestCase):
    """Penyiapan U2: ruang usaha Dapur Nusa (5 amplop bawaan + amplop pribadi pemilik), ruang usaha kedua, ruang
    keluarga, pemilik/admin/karyawan; modal awal Rp3 jt hari ini (pemilik, tanpa jenis) ke amplop Bahan."""
    if HAS_AIOSQLITE:
        hdr, aksi, pasang_aktif, p, kode, kontak, atur_a3, hitung, katalog, _ctx = (
            u2.U2DbTests.hdr, u2.U2DbTests.aksi, u2.U2DbTests.pasang_aktif, u2.U2DbTests.p, u2.U2DbTests.kode,
            u2.U2DbTests.kontak, u2.U2DbTests.atur_a3, u2.U2DbTests.hitung, u2.U2DbTests.katalog, u2.U2DbTests._ctx)

    async def asyncSetUp(self):
        await u2.U2DbTests.asyncSetUp(self)

    async def inc(self, db, jumlah, tgl, *, user=None, hid=None, kind="pemasukan", jenis=None, kontak=None, alok=()):
        hid = hid or self.usaha
        i = Income(household_id=hid, user_id=(user or self.pemilik).id, amount=D(jumlah), description="masuk",
                   income_date=tgl, kind=kind)
        db.add(i)
        await db.flush()
        for env, x in alok:
            db.add(Allocation(income_id=i.id, envelope_id=env, amount=D(x)))
        if jenis:
            db.add(BukuUsahaIncomeMeta(household_id=hid, income_id=i.id, jenis=jenis, kontak_id=kontak))
        return i

    async def trx(self, db, env, jumlah, tgl, *, user=None, akun=None, privat=False, hapus=False):
        t = Transaction(envelope_id=env, user_id=(user or self.pemilik).id, amount=D(jumlah), description="belanja",
                        transaction_date=tgl, is_private=privat, is_deleted=hapus)
        db.add(t)
        await db.flush()
        if akun:
            hid = (await db.get(Envelope, env)).household_id
            db.add(BukuUsahaTxnMeta(household_id=hid, transaction_id=t.id, akun=akun))
        return t


class HostU4Tests(U4DbDasar):
    async def test_ringkas_per_tanggal(self):
        h = self.today
        k = h - timedelta(days=1)
        async with self.Session() as db:
            await self.trx(db, self.env["Bahan"], "100000", h)
            await self.trx(db, self.env["Operasional"], "25000", h)
            await self.trx(db, self.env["Bahan"], "40000", k)
            await self.trx(db, self.env["Bahan"], "999", k, hapus=True)
            await self.inc(db, "500000", k, jenis="penjualan")
            await db.commit()
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=BACA, jenis="kartu")
            t = await ctx.ringkas_transaksi(k, h, per=("tanggal",), hanya_bersama=True)
            self.assertEqual([(r.kunci, r.jumlah, r.banyak) for r in t],
                             [((k,), D("40000"), 1), ((h,), D("125000"), 2)])
            self.assertIsInstance(t[0].kunci[0], date)
            p = await ctx.ringkas_pemasukan(k, h, per=("tanggal", "jenis"))
            self.assertEqual([(r.kunci, r.jumlah) for r in p],
                             [((k, "pemasukan"), D("500000")), ((h, "pemasukan"), D("3000000"))])

    async def test_envelopes_saldo(self):
        async with self.Session() as db:
            await self.trx(db, self.env["Bahan"], "250000", self.today)
            await self.trx(db, self.env_lain, "777", self.today)
            await db.commit()
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=BACA, jenis="kartu")
            tanpa = {a.nama: a for a in await ctx.envelopes()}
            self.assertIsNone(tanpa["Bahan"].sisa)
            dengan = {a.nama: a for a in await ctx.envelopes(saldo=True)}
            self.assertEqual(dengan["Bahan"].sisa, D("2750000"))       # modal 3 jt − 250 rb
            self.assertEqual(dengan["Operasional"].sisa, D("0"))
            self.assertEqual(set(dengan), set(tanpa))                   # amplop yang sama, ruang ini saja
            self.assertTrue(dengan["Pribadi pemilik"].pribadi)

    async def test_envelopes_saldo_karyawan_ditolak(self):
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=BACA, jenis="kartu", user=self.karyawan, peran="member")
            with self.assertRaises(IzinDitolak) as e:
                await ctx.envelopes(saldo=True)
            self.assertEqual(e.exception.alasan, "khusus_admin")

    async def test_pemasukan_saya_hanya_milik_viewer(self):
        h = self.today
        async with self.Session() as db:
            await self.inc(db, "150000", h, user=self.karyawan)                       # penjualan karyawan (Catat cepat)
            await self.inc(db, "50000", h, user=self.karyawan, jenis="penjualan")
            await self.inc(db, "700000", h, user=self.admin, jenis="penjualan")       # milik admin
            await self.inc(db, "9000000", h, user=self.karyawan, hid=self.usaha2)     # ruang lain
            await db.commit()
        async with self.Session() as db:
            ctx = await self._ctx(db, izin=BACA, jenis="kartu", user=self.karyawan, peran="member")
            saya = await ctx.ringkas_pemasukan_saya(h, h, per=("jenis", "income_meta.jenis"))
            self.assertEqual({r.kunci: (r.jumlah, r.banyak) for r in saya},
                             {("pemasukan", None): (D("150000"), 1), ("pemasukan", "penjualan"): (D("50000"), 1)})
        async with self.Session() as db:      # pemilik: hanya miliknya juga (modal awal 3 jt), bukan seluruh ruang
            ctx = await self._ctx(db, izin=BACA, jenis="kartu")
            saya = await ctx.ringkas_pemasukan_saya(h, h)
            self.assertEqual([(r.jumlah, r.banyak) for r in saya], [(D("3000000"), 1)])

    async def test_karyawan_tetap_tidak_membaca_data_ruang(self):
        """`ringkas_pemasukan_saya` tidak membuka baca keuangan lain untuk karyawan."""
        h = self.today
        for panggil in (lambda c: c.ringkas_pemasukan(h, h), lambda c: c.incomes(h, h), lambda c: c.envelopes(),
                        lambda c: c.ringkas_transaksi(h, h), lambda c: c.transactions(h, h)):
            async with self.Session() as db:
                ctx = await self._ctx(db, izin=BACA, jenis="kartu", user=self.karyawan, peran="member")
                with self.assertRaises(IzinDitolak) as e:
                    await panggil(ctx)
                self.assertEqual(e.exception.alasan, "khusus_admin")

    async def test_pemasukan_saya_butuh_izin_dan_user(self):
        h = self.today
        async with self.Session() as db:      # tanpa incomes:read
            ctx = await self._ctx(db, izin=("envelopes:read",), jenis="kartu", user=self.karyawan, peran="member")
            with self.assertRaises(IzinDitolak) as e:
                await ctx.ringkas_pemasukan_saya(h, h)
            self.assertEqual(e.exception.alasan, "tanpa_izin")
        async with self.Session() as db:      # job (tanpa user): tidak ada "saya"
            m = self.reg.get("buku_usaha")
            from app.models.models import Household, PluginInstallation
            from app.plugins.host import titik
            from app.plugins.sdk.plugin import Pendaftaran
            inst = PluginInstallation(household_id=self.usaha, plugin_id="buku_usaha", status="active",
                                      granted_permissions=list(BACA))
            ctx = titik.konteks(db, m, inst, await db.get(Household, self.usaha),
                                Pendaftaran("job", "uji", lambda *a: None, BACA), viewer=None, sumber="uji")
            with self.assertRaises(IzinDitolak) as e:
                await ctx.ringkas_pemasukan_saya(h, h)
            self.assertEqual(e.exception.alasan, "bukan_user")
            keadaan.tutup(ctx)


# ── 3. kartu lewat /dashboard/* ──────────────────────────────────────────
KUNCI_UMUM = ["buku_usaha.omzet", "buku_usaha.laba", "buku_usaha.kas", "buku_usaha.arus_kas_13",
              "buku_usaha.alokasi_omzet", "buku_usaha.beban_akun", "buku_usaha.pelanggan_teratas"]
KUNCI_KARYAWAN = "buku_usaha.penjualan_saya"


class KartuBerandaTests(U4DbDasar):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from app.api.routes import dashboard as dashboard_route
        self.client._transport.app.include_router(dashboard_route.router, prefix="/dashboard")
        self.awal = self.today.replace(day=1)

    async def isi(self):
        """Bulan ini: penjualan 1 jt (Bu Sari, pemilik) + 500 rb (Pak Budi, admin) + 300 rb tanpa pelanggan (admin);
        karyawan: 150 rb tanpa jenis + 50 rb penjualan; modal awal 3 jt (penyiapan, tanpa jenis). Beban: bahan baku
        400 rb, gaji 300 rb, tanpa akun 50 rb. Ruang lain dan ruang keluarga punya angka sendiri yang tidak boleh ikut."""
        await self.pasang_aktif()
        await self.atur_a3()
        h = self.today
        bahan, op = self.env["Bahan"], self.env["Operasional"]
        async with self.Session() as db:
            sari = BukuUsahaKontak(household_id=self.usaha, nama="Bu Sari", peran="pelanggan")
            budi = BukuUsahaKontak(household_id=self.usaha, nama="Pak Budi", peran="pelanggan")
            db.add_all([sari, budi])
            await db.flush()
            await self.inc(db, "1000000", h, jenis="penjualan", kontak=sari.id, alok=[(bahan, "1000000")])
            await self.inc(db, "500000", h, user=self.admin, jenis="penjualan", kontak=budi.id, alok=[(op, "500000")])
            await self.inc(db, "300000", h, user=self.admin, jenis="penjualan", alok=[(op, "300000")])
            await self.inc(db, "150000", h, user=self.karyawan, alok=[(op, "150000")])
            await self.inc(db, "50000", h, user=self.karyawan, jenis="penjualan", alok=[(op, "50000")])
            await self.inc(db, "7000000", h, hid=self.usaha2, jenis="penjualan")
            await self.inc(db, "6000000", h, user=self.karyawan, hid=self.usaha2)
            await self.trx(db, bahan, "400000", h, akun="Bahan baku")
            await self.trx(db, op, "300000", h, user=self.admin, akun="Gaji")
            await self.trx(db, op, "50000", h, user=self.karyawan)
            await self.trx(db, self.pribadi, "777777", h)
            await self.trx(db, self.env_lain, "888888", h, akun="Gaji")
            await db.commit()

    async def data(self, kunci, hid=None):
        items = [{"id": f"k{i}", "card": k} for i, k in enumerate(kunci)]
        r = await self.client.post("/dashboard/data", headers=self.hdr(hid), json={"periode": None, "items": items})
        self.assertEqual(r.status_code, 200, r.text)
        return {k: r.json()["data"][f"k{i}"] for i, k in enumerate(kunci)}

    async def kartu(self, hid=None):
        r = await self.client.get("/dashboard/cards", headers=self.hdr(hid))
        self.assertEqual(r.status_code, 200, r.text)
        return {c["key"]: c for c in r.json()}

    async def tata_letak(self):
        r = await self.client.get("/dashboard/layout", headers=self.hdr())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def test_katalog_per_peran_dan_tawaran(self):
        await self.pasang_aktif()
        umum = await self.kartu()
        self.assertEqual([k for k in umum if k.startswith("buku_usaha.")], KUNCI_UMUM)
        self.assertEqual({umum[k]["shape"] for k in KUNCI_UMUM}, {"kpi", "series", "progress", "list"})
        self.assertEqual(umum["buku_usaha.omzet"]["asal"], "buku_usaha")
        # Tawaran kartu saat pasang dan kontribusi web: hanya kartu umum; empat dicentang (keputusan F).
        tawaran = (await self.katalog())["buku_usaha"]["kartu"]
        self.assertEqual([k["key"] for k in tawaran], KUNCI_UMUM)
        self.assertEqual([k["key"] for k in tawaran if k["bawaan"]], KUNCI_UMUM[:4])
        r = await self.client.get("/plugins/contributions", headers=self.hdr())
        self.assertEqual([c["key"] for c in r.json()["cards"]], KUNCI_UMUM)
        self.current = self.karyawan
        karyawan = await self.kartu()
        self.assertEqual([k for k in karyawan if not k.startswith("core.karyawan.")], [KUNCI_KARYAWAN])
        self.assertEqual(karyawan[KUNCI_KARYAWAN]["asal"], "buku_usaha")
        # Nama Fitur Tambahan asal kartu ikut katalog (penanda sumber di Beranda karyawan); kartu inti tanpa sumber.
        self.assertEqual((karyawan[KUNCI_KARYAWAN]["sumber"], umum["buku_usaha.omzet"]["sumber"]),
                         ("Buku Usaha", "Buku Usaha"))
        self.assertIsNone(karyawan["core.karyawan.catat"]["sumber"])

    async def test_kartu_pemilik_dari_data(self):
        await self.isi()
        d = await self.data(KUNCI_UMUM)
        self.assertEqual([d[k].get("shape") for k in KUNCI_UMUM],
                         ["kpi", "kpi", "kpi", "series", "progress", "progress", "list"], d)
        # Omzet = penjualan 1,85 jt + tanpa jenis 3,15 jt (modal awal penyiapan + titipan karyawan); 6 catatan.
        self.assertEqual((d["buku_usaha.omzet"]["value"], d["buku_usaha.omzet"]["suffix"]),
                         ("5000000.00", "6 penjualan"))
        self.assertEqual(D(d["buku_usaha.laba"]["value"]), D("4250000"))
        # Kas = sisa amplop bersama: Bahan 3 jt + 1 jt − 400 rb; Operasional 1 jt − 350 rb. Amplop pribadi tidak.
        self.assertEqual((D(d["buku_usaha.kas"]["value"]), d["buku_usaha.kas"]["suffix"]), (D("4250000"), "5 amplop"))
        seri = d["buku_usaha.arus_kas_13"]
        self.assertEqual(len(seri["x"]), 13)
        self.assertEqual((D(seri["series"][0]["values"][-1]), D(seri["series"][1]["values"][-1])),
                         (D("5000000"), D("750000")))
        alok = {i["label"]: i for i in d["buku_usaha.alokasi_omzet"]["items"]}
        self.assertEqual((D(alok["Bahan · 45%"]["value"]), D(alok["Bahan · 45%"]["target"])),
                         (D("400000"), D("832500")))                    # jatah 45% × penjualan 1,85 jt
        self.assertEqual(alok["Operasional · 30%"]["tone"], None)       # 350 rb dari jatah 555 rb
        self.assertEqual((D(alok["Pajak · 1%"]["value"]), alok["Pajak · 1%"]["target"]), (D("18500"), None))
        self.assertEqual([(i["label"], D(i["value"])) for i in d["buku_usaha.beban_akun"]["items"]],
                         [("Bahan baku", D("400000")), ("Gaji", D("300000")), ("Belum berakun", D("50000"))])
        self.assertEqual([(i["judul"], D(i["nominal"]), i["subjudul"]) for i in d["buku_usaha.pelanggan_teratas"]["items"]],
                         [("Bu Sari", D("1000000"), "1 penjualan"), ("Pak Budi", D("500000"), "1 penjualan")])

    async def test_admin_melihat_angka_yang_sama(self):
        await self.isi()
        pemilik = await self.data(KUNCI_UMUM)
        self.current = self.admin
        admin = await self.data(KUNCI_UMUM)
        self.assertEqual(admin["buku_usaha.omzet"], pemilik["buku_usaha.omzet"])
        self.assertEqual(admin["buku_usaha.laba"], pemilik["buku_usaha.laba"])
        self.assertEqual(admin["buku_usaha.kas"], pemilik["buku_usaha.kas"])      # amplop pribadi pemilik tidak ikut

    async def test_karyawan_hanya_penjualannya_sendiri(self):
        await self.isi()
        self.current = self.karyawan
        letak = await self.tata_letak()
        kartu = [i["card"] for i in letak["items"]]
        self.assertEqual(kartu[kartu.index("core.karyawan.hari_ini") + 1], KUNCI_KARYAWAN)
        saya = next(i for i in letak["items"] if i["card"] == KUNCI_KARYAWAN)
        self.assertTrue(saya["visible"])
        d = await self.data([KUNCI_KARYAWAN] + KUNCI_UMUM)
        self.assertEqual((d[KUNCI_KARYAWAN]["shape"], d[KUNCI_KARYAWAN]["value"], d[KUNCI_KARYAWAN]["suffix"]),
                         ("kpi", "200000.00", "2 penjualan"))              # 150 rb + 50 rb; bukan 5 jt ruang
        for k in KUNCI_UMUM:                                                # laba, kas, omzet ruang: tanpa data
            self.assertEqual(d[k], {"error": {"kode": "khusus_admin", "detail": d[k]["error"]["detail"]}}, k)

    async def test_pengelola_tidak_memuat_kartu_karyawan(self):
        await self.isi()
        for user in (self.pemilik, self.admin):
            self.current = user
            self.assertNotIn(KUNCI_KARYAWAN, [i["card"] for i in (await self.tata_letak())["items"]])
            d = await self.data([KUNCI_KARYAWAN])
            self.assertEqual(d[KUNCI_KARYAWAN]["error"]["kode"], "kartu_tidak_dikenal")

    async def test_jeda_menghilangkan_semua_kartu(self):
        await self.isi()
        await self.aksi("jeda")
        self.assertEqual([k for k in await self.kartu() if k.startswith("buku_usaha.")], [])
        d = await self.data(KUNCI_UMUM[:1])
        self.assertEqual(d[KUNCI_UMUM[0]]["error"]["kode"], "kartu_tidak_dikenal")
        self.current = self.karyawan
        self.assertEqual([k for k in await self.kartu() if k.startswith("buku_usaha.")], [])
        letak = await self.tata_letak()
        self.assertNotIn(KUNCI_KARYAWAN, [i["card"] for i in letak["items"] + letak["parked"]])
        d = await self.data([KUNCI_KARYAWAN])
        self.assertEqual(d[KUNCI_KARYAWAN]["error"]["kode"], "kartu_tidak_dikenal")

    async def test_ruang_tanpa_plugin_tidak_berubah(self):
        """Ruang usaha kedua (plugin tidak dipasang) dan ruang keluarga: tidak ada kartu Buku Usaha."""
        await self.isi()
        for hid in (self.usaha2, self.rumah):
            self.assertEqual([k for k in await self.kartu(hid) if k.startswith("buku_usaha.")], [])
            d = await self.data(KUNCI_UMUM[:1], hid)
            self.assertEqual(d[KUNCI_UMUM[0]]["error"]["kode"], "kartu_tidak_dikenal")

    async def test_karyawan_di_luar_flag_tidak_mendapat_kartu(self):
        await self.isi()
        from sqlalchemy import update
        from app.models.models import AppSetting
        async with self.Session() as db:
            await db.execute(update(AppSetting).where(AppSetting.key == "plugin_buku_usaha_users")
                             .values(value=str(self.pemilik.id)))
            await db.commit()
        self.current = self.karyawan
        self.assertNotIn(KUNCI_KARYAWAN, [i["card"] for i in (await self.tata_letak())["items"]])


# ── 4. anggaran waktu penyedia ───────────────────────────────────────────
class AnggaranKartuTests(U4DbDasar):
    """03-workflow.md baris U4: maksimal 150 ms per penyedia, dengan data 12 bulan (01-kajian.md "Tes kinerja
    penyedia"). Diukur pada fungsi host yang dipakai `POST /dashboard/data` (`titik.data_kartu`), terbaik dari tiga."""
    BULAN, TRX_PER_BULAN, INC_PER_BULAN, KONTAK = 12, 250, 150, 40

    async def test_setiap_penyedia_di_bawah_150_ms(self):
        import time
        await self.pasang_aktif()
        await self.atur_a3()
        akun = ("Bahan baku", "Gaji", "Sewa", "Listrik & air", "Transport", None)
        async with self.Session() as db:
            kontak = [BukuUsahaKontak(household_id=self.usaha, nama=f"Pelanggan {i}", peran="pelanggan")
                      for i in range(self.KONTAK)]
            db.add_all(kontak)
            await db.flush()
            env = [self.env["Bahan"], self.env["Operasional"]]
            pencatat = [self.pemilik, self.admin, self.karyawan]
            for b in range(self.BULAN):
                for i in range(self.TRX_PER_BULAN):
                    t = Transaction(envelope_id=env[i % 2], user_id=pencatat[i % 3].id, amount=D(10000 + i),
                                    description="belanja", transaction_date=self.today - timedelta(days=b * 30 + i % 28))
                    db.add(t)
                    await db.flush()
                    if akun[i % 6]:
                        db.add(BukuUsahaTxnMeta(household_id=self.usaha, transaction_id=t.id, akun=akun[i % 6]))
                for i in range(self.INC_PER_BULAN):
                    inc = Income(household_id=self.usaha, user_id=pencatat[i % 3].id, amount=D(50000 + i),
                                 description="jual", income_date=self.today - timedelta(days=b * 30 + i % 28),
                                 kind="pemasukan")
                    db.add(inc)
                    await db.flush()
                    db.add(Allocation(income_id=inc.id, envelope_id=env[i % 2], amount=D(50000 + i)))
                    if i % 5:
                        db.add(BukuUsahaIncomeMeta(household_id=self.usaha, income_id=inc.id, jenis="penjualan",
                                                   kontak_id=kontak[i % self.KONTAK].id))
            await db.commit()
        periode = PeriodeView(start=self.today.replace(day=1), end=self.today, berjalan=True)
        lambat = {}
        for user in (self.pemilik, self.karyawan):
            async with self.Session() as db:
                definisi = await titik.kartu_ruang(db, user, self.usaha)
                karyawan = user is self.karyawan
                for kunci, d in definisi.items():
                    if (d.untuk == "karyawan") != karyawan:
                        continue
                    terbaik = None
                    for _ in range(3):
                        mulai = time.perf_counter()
                        data = await titik.data_kartu(db, user, self.usaha, d, {}, periode)
                        ms = (time.perf_counter() - mulai) * 1000
                        terbaik = ms if terbaik is None else min(terbaik, ms)
                    self.assertEqual(data["shape"], d.shape)
                    if terbaik > titik.ANGGARAN_MS:
                        lambat[kunci] = round(terbaik)
        self.assertEqual(lambat, {}, "penyedia melewati anggaran 150 ms")


if __name__ == "__main__":
    unittest.main()
