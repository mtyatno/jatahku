"""Ruang usaha tanpa pengeluaran privat (keputusan pemilik produk 11 Nov 2026; catatan U3 di docs/plugin/SESI-LOG.md).

Pengeluaran usaha harus terbuka bagi pemilik dan admin, jadi tanda privat tidak berlaku di ruang usaha, untuk semua
peran. Server menolaknya (422 `privat_tidak_tersedia`, tidak diam-diam dicatat terbuka); web tidak menampilkan
pilihannya (`lib/privateToggle.js`).

Dikunci:
1. `POST /transactions/` bertanda privat di ruang usaha → 422 untuk pemilik, admin, dan karyawan; tidak ada transaksi,
   draf, atau kunci idempotensi yang tertinggal (kirim ulang tanpa tanda privat tercatat sekali).
2. Karyawan di atas batas nominal tetap ditolak lebih dulu (tidak menjadi draf privat).
3. `POST /transactions/batch` (antrean offline): baris privat di ruang usaha gagal per baris dengan kode yang sama;
   baris lain di kiriman itu tetap tercatat.
4. Ruang keluarga tidak berubah: tanda privat tetap tersimpan.
5. Draf lama bertanda privat (data uji coba) disetujui sebagai pengeluaran biasa.

Memakai penyiapan `test_ruang_peran.RuangPeranTests` (Saya owner Dapur Nusa, Ani admin, Dewi karyawan).
Run: python -m unittest app.tests.test_privat_ruang_usaha -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from decimal import Decimal as D

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    from sqlalchemy import select

    # Modulnya, bukan kelasnya: kelas tes di namespace modul ini akan ikut dijalankan lagi oleh unittest.
    from app.tests import test_ruang_peran as r5
    from app.models.models import RuangDraf, Transaction

KODE = "privat_tidak_tersedia"


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class PrivatRuangUsahaTests(unittest.IsolatedAsyncioTestCase):
    if HAS_AIOSQLITE:
        asyncSetUp = r5.RuangPeranTests.asyncSetUp
        _isi, _req, _batasan, _hitung = (r5.RuangPeranTests._isi, r5.RuangPeranTests._req,
                                         r5.RuangPeranTests._batasan, r5.RuangPeranTests._hitung)

    def body(self, env, ket, privat=True, **kw):
        return {"envelope_id": str(env), "amount": "25000", "description": ket, "is_private": privat, **kw}

    async def test_tunggal_ditolak_untuk_semua_peran(self):
        for user in (self.me, self.ani, self.dewi):
            r = await self._req("POST", "/transactions/", self.body(self.op_id, f"bensin {user.name}",
                                                                    client_ref=f"ref-{user.name}"), user=user)
            self.assertEqual((r.status_code, r.json().get("kode")), (422, KODE), r.text)
            self.assertIn("tidak bisa privat", r.json()["detail"])
        self.assertEqual(await self._hitung(Transaction, Transaction.description.like("bensin %")), 0)
        self.assertEqual(await self._hitung(RuangDraf), 0)
        # Kunci idempotensi tidak tertahan: kirim ulang tanpa tanda privat tercatat sekali, terbuka.
        for _ in range(2):
            r = await self._req("POST", "/transactions/", self.body(self.op_id, "bensin Dewi", privat=False,
                                                                    client_ref="ref-Dewi"), user=self.dewi)
            self.assertIn(r.status_code, (200, 201), r.text)
        async with self.Session() as db:
            rows = (await db.execute(select(Transaction).where(Transaction.description == "bensin Dewi"))).scalars().all()
        self.assertEqual([t.is_private for t in rows], [False])

    async def test_karyawan_di_atas_batas_tidak_menjadi_draf_privat(self):
        await self._batasan(batas_nominal=10000)
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "bensin besar", client_ref="ref-besar"),
                            user=self.dewi)
        self.assertEqual((r.status_code, r.json().get("kode")), (422, KODE), r.text)
        self.assertEqual(await self._hitung(RuangDraf), 0)
        r = await self._req("POST", "/transactions/", self.body(self.op_id, "bensin besar", privat=False,
                                                                client_ref="ref-besar"), user=self.dewi)
        self.assertEqual((r.status_code, r.json().get("kode")), (202, "perlu_persetujuan"), r.text)
        async with self.Session() as db:
            self.assertEqual([d.is_private for d in (await db.execute(select(RuangDraf))).scalars()], [False])

    async def test_batch_ditolak_per_baris(self):
        items = [self.body(self.op_id, "privat usaha", client_ref="b1"),
                 self.body(self.op_id, "terbuka usaha", privat=False, client_ref="b2"),
                 self.body(self.k["env"], "kado rahasia", client_ref="b3")]      # ruang keluarga Saya
        r = await self._req("POST", "/transactions/batch", {"items": items}, user=self.me)
        self.assertEqual(r.status_code, 200, r.text)
        hasil = r.json()
        self.assertEqual((hasil[0]["ok"], hasil[0]["kode"]), (False, KODE))
        self.assertTrue(hasil[1]["ok"], hasil[1])
        self.assertTrue(hasil[2]["ok"], hasil[2])
        async with self.Session() as db:
            rows = {t.description: t.is_private for t in (await db.execute(
                select(Transaction).where(Transaction.description.in_(["privat usaha", "terbuka usaha",
                                                                         "kado rahasia"])))).scalars()}
        self.assertEqual(rows, {"terbuka usaha": False, "kado rahasia": True})
        # Karyawan lewat antrean offline: sama.
        r = await self._req("POST", "/transactions/batch", {"items": [self.body(self.op_id, "x", client_ref="b4")]},
                            user=self.dewi)
        self.assertEqual(r.json()[0]["kode"], KODE)

    async def test_ruang_keluarga_tetap_boleh_privat(self):
        r = await self._req("POST", "/transactions/", self.body(self.k["env"], "kado ulang tahun"), user=self.me)
        self.assertIn(r.status_code, (200, 201), r.text)
        async with self.Session() as db:
            t = (await db.execute(select(Transaction).where(Transaction.description == "kado ulang tahun"))).scalar_one()
        self.assertTrue(t.is_private)

    async def test_draf_lama_privat_disetujui_terbuka(self):
        async with self.Session() as db:
            d = RuangDraf(household_id=self.nusa_id, user_id=self.dewi.id, jenis="pengeluaran",
                          envelope_id=self.op_id, amount=D("40000"), description="draf lama privat",
                          is_private=True, status="menunggu")
            db.add(d)
            await db.commit()
            draf_id = d.id
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{draf_id}/setujui", user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            t = (await db.execute(select(Transaction).where(Transaction.description == "draf lama privat"))).scalar_one()
        self.assertFalse(t.is_private)
        self.assertEqual(t.user_id, self.dewi.id)


if __name__ == "__main__":
    unittest.main()
