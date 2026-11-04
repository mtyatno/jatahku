"""Plugin R6 — halaman Anggota dan batasan, Beranda karyawan (03-workflow.md baris R6; gerbang "Karyawan tidak melihat
laporan"; 04-kontrak-api.md §2, §4; ADR-P3, P4, P8).

Pelaku sama dengan `test_ruang_peran.py`: Saya (owner Dapur Nusa), Ani (admin), Dewi (karyawan), Rina (anggota ruang
keluarga Saya), Orang (tidak terkait).

Dikunci:
1. `/dashboard/*` untuk karyawan hanya kartu karyawan: kartu umum (laba, kas, saldo) dijawab `khusus_admin` per kartu
   tanpa memuat datanya; katalog dan template ikut peran; menyimpan tata letak dengan kartu umum ditolak.
2. Kartu karyawan hanya memuat catatan miliknya sendiri, drafnya, dan batasannya; tidak untuk peran lain.
3. Ganti peran membuang tata letak lama di ruang itu.
4. Undangan: daftar dan cabut (kode yang dicabut ditolak saat bergabung). Ganti nama ruang. Nama di log audit.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_r6 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.tests import test_ruang_peran as r5
from app.tests.test_ruang_peran import HAS_AIOSQLITE, JKT

from app.services import peran
from app.services.dashboard import registry, sources

if HAS_AIOSQLITE:
    from sqlalchemy import select

    from app.models.models import DashboardLayout, Household, RuangAudit, RuangUndangan

KARTU_KARYAWAN = [c.key for c in registry.KARYAWAN]
KARTU_UMUM = [c.key for c in registry.CORE]


def _items(keys):
    return [{"id": f"k{i}", "card": k, "settings": {"limit": 10} if k == "core.transaksi_terbaru" else {}}
            for i, k in enumerate(keys)]


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangR6Tests(unittest.IsolatedAsyncioTestCase):
    # Fixture dan pembantu yang sama dengan R5 (tanpa mewarisi tes R5, supaya tidak berjalan dua kali).
    asyncSetUp = r5.RuangPeranTests.asyncSetUp
    _isi = r5.RuangPeranTests._isi
    _req = r5.RuangPeranTests._req
    _batasan = r5.RuangPeranTests._batasan
    _hitung = r5.RuangPeranTests._hitung
    _kode = r5.RuangPeranTests._kode

    async def _simpan_satu(self, user):
        """Simpan tata letak berisi satu kartu karyawan (template lainnya disebut di `removed`)."""
        lain = [i["id"] for i in registry.template("beranda", karyawan=True) if i["id"] != "a2"]
        return await self._req("PUT", "/dashboard/layout", {"if_version": 0, "items": [
            {"id": "a2", "card": "core.karyawan.hari_ini", "size": "M"}], "removed": lain},
            header=self.nusa_id, user=user)

    async def _data(self, keys, user, header):
        r = await self._req("POST", "/dashboard/data", {"items": _items(keys)}, header=header, user=user)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]

    # 1. Beranda karyawan: template, katalog, tolak kartu umum ---------------------------
    async def test_template_dan_katalog_ikut_peran(self):
        r = await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["untuk"], body["enabled"], body["version"]), ("karyawan", True, 0))
        self.assertEqual([i["card"] for i in body["items"]], KARTU_KARYAWAN)
        r = await self._req("GET", "/dashboard/cards", header=self.nusa_id, user=self.dewi)
        self.assertEqual([c["key"] for c in r.json()], KARTU_KARYAWAN)

        for user, header in ((self.me, self.nusa_id), (self.ani, self.nusa_id), (self.me, None), (self.rina, None)):
            r = await self._req("GET", "/dashboard/layout", header=header, user=user)
            self.assertEqual(r.json()["untuk"], "umum")
            self.assertEqual([i["card"] for i in r.json()["items"]], [i["card"] for i in registry.template("beranda")])
            r = await self._req("GET", "/dashboard/cards", header=header, user=user)
            self.assertFalse({c["key"] for c in r.json()} & set(KARTU_KARYAWAN))

    async def test_karyawan_tidak_menerima_data_kartu_umum(self):
        """Gerbang "Karyawan tidak melihat laporan": setiap kartu umum → `khusus_admin`, penyedianya tidak dipanggil,
        dan tidak ada angka ruang usaha di jawaban."""
        await self._batasan(lihat_saldo=True)   # walau boleh melihat saldo amplop, laporan tetap tertutup
        dimuat = []
        asli = sources.Sumber._muat

        async def catat(sumber, nama, *a, **kw):
            dimuat.append(nama)
            return await asli(sumber, nama, *a, **kw)
        with patch.object(sources.Sumber, "_muat", catat):
            data = await self._data(KARTU_UMUM, self.dewi, self.nusa_id)
        self.assertEqual({k: v.get("error", {}).get("kode") for k, v in data.items()},
                         {f"k{i}": "khusus_admin" for i in range(len(KARTU_UMUM))})
        self.assertEqual(dimuat, [])
        teks = str(data)
        for angka in ("2000000", "5000000", "6000000"):
            self.assertNotIn(angka, teks)

        # Satu instans dari tata letak tersimpan pun tidak bisa memuat kartu umum.
        r = await self._req("GET", "/dashboard/data/a1", header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.json()["shape"], "inti")   # a1 template karyawan = Catat

    async def test_karyawan_tidak_bisa_menyimpan_kartu_umum(self):
        r = await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)
        items = [{k: i[k] for k in ("id", "card", "size", "hidden", "devices")} for i in r.json()["items"]]
        bocor = items + [{"id": "x1", "card": "core.kpi.sisa_bebas", "size": "S"}]
        r = await self._req("PUT", "/dashboard/layout", {"if_version": 0, "items": bocor}, header=self.nusa_id,
                            user=self.dewi)
        self.assertEqual(self._kode(r), (422, "kartu_tidak_dikenal"))
        r = await self._req("PUT", "/dashboard/layout", {"if_version": 0, "items": items[1:], "removed": ["a1"]},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["layout"]["items"][0]["card"], "core.karyawan.hari_ini")
        # Pemilik tidak bisa menaruh kartu karyawan di Berandanya.
        r = await self._req("PUT", "/dashboard/layout", {"if_version": 0, "items": [
            {"id": "z1", "card": "core.karyawan.batasan", "size": "M"}]}, header=self.nusa_id, user=self.me)
        self.assertEqual(self._kode(r), (422, "kartu_tidak_dikenal"))

    async def test_kartu_karyawan_tidak_untuk_peran_lain(self):
        for user, header in ((self.me, self.nusa_id), (self.ani, self.nusa_id), (self.me, None), (self.dewi, None)):
            data = await self._data(KARTU_KARYAWAN, user, header)
            self.assertEqual({v["error"]["kode"] for v in data.values()}, {"kartu_tidak_dikenal"}, (user.name, header))

    async def test_di_luar_jam_kerja_beranda_tertutup(self):
        sekarang = datetime.now(JKT)
        mulai = (sekarang + timedelta(hours=2)).strftime("%H:%M")
        selesai = (sekarang + timedelta(hours=3)).strftime("%H:%M")
        await self._batasan(jam_kerja={"mulai": mulai, "selesai": selesai, "hari": [1, 2, 3, 4, 5, 6, 7],
                                       "zona": "Asia/Jakarta"})
        r = await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)
        self.assertEqual(self._kode(r), (403, "di_luar_jam_kerja"))

    # 2. Isi kartu karyawan ---------------------------------------------------------------
    async def test_isi_kartu_karyawan_hanya_miliknya(self):
        await self._batasan(batas_nominal=1000000, amplop_ids=[str(self.u["env"])], jendela_ubah="hari_sama")
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "50000",
                                                      "description": "kardus"}, user=self.dewi)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/incomes/", {"amount": "100000", "source": "nasi box", "allocations": [
            {"envelope_id": str(self.u["env"]), "amount": "100000"}]}, header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "2500000",
                                                      "description": "ayam 40kg", "client_ref": "r6"}, user=self.dewi)
        self.assertEqual(r.status_code, 202, r.text)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.u["env"]), "amount": "70000",
                                                      "description": "belanja pemilik"}, user=self.me)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/transactions/", {"envelope_id": str(self.kd["env"]), "amount": "15000",
                                                      "description": "sarapan pribadi"}, user=self.dewi)
        self.assertEqual(r.status_code, 201, r.text)   # ruang keluarga Dewi: tidak ikut kartu ruang usaha

        data = await self._data(KARTU_KARYAWAN, self.dewi, self.nusa_id)
        catat, hari, menunggu, catatan, batasan, terpisah = (data[f"k{i}"] for i in range(6))
        self.assertEqual(catat["jenis_catatan"], ["pengeluaran", "penjualan"])
        self.assertEqual([a["nama"] for a in catat["amplop"]], ["Bahan"])
        self.assertEqual((hari["pengeluaran"], hari["penjualan"]),
                         ({"jumlah": 1, "total": 50000}, {"jumlah": 1, "total": 100000}))
        self.assertEqual((menunggu["menunggu"], [(d["judul"], d["nominal"], d["status"]) for d in menunggu["items"]]),
                         (1, [("ayam 40kg", 2500000, "menunggu")]))
        self.assertEqual(sorted((c["judul"], c["jenis"], c["boleh_hapus"]) for c in catatan["items"]),
                         [("kardus", "pengeluaran", True), ("nasi box", "penjualan", False)])
        self.assertEqual((batasan["batasan"]["batas_nominal"], [a["nama"] for a in batasan["amplop"]]),
                         (1000000, ["Bahan"]))
        self.assertNotIn("amplop_ids", batasan["batasan"])
        self.assertEqual((terpisah["shape"], terpisah["tone"]), ("alert", "info"))
        teks = str(data)
        for asing in ("belanja pemilik", "sarapan pribadi", "Operasional", "5000000", "budget"):
            self.assertNotIn(asing, teks)

        # Batasan amplop "semua" → kartu menyebut semua amplop tanpa daftar.
        await self._batasan()
        data = await self._data(["core.karyawan.batasan"], self.dewi, self.nusa_id)
        self.assertIsNone(data["k0"]["amplop"])

    # 3. Ganti peran -------------------------------------------------------------------------
    async def test_ganti_peran_membuang_tata_letak(self):
        r = await self._simpan_satu(self.dewi)
        self.assertEqual(r.status_code, 200, r.text)
        r = await self._req("PATCH", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}", {"peran": "admin"}, user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(await self._hitung(DashboardLayout, DashboardLayout.user_id == self.dewi.id), 0)
        r = await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)
        self.assertEqual((r.json()["untuk"], r.json()["version"]), ("umum", 0))
        r = await self._req("PATCH", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}", {"jabatan": "Kasir"},
                            user=self.ani)   # jabatan saja: tata letak tidak disentuh
        self.assertEqual(r.status_code, 200)

    async def test_tata_letak_lama_peran_lain_tidak_tampil(self):
        """Dokumen tersimpan berisi kartu umum (mis. dibuat saat masih admin, sebelum R6 membuangnya) tetap
        dikirim sebagai `visible: false` dan datanya ditolak."""
        async with self.Session() as db:
            db.add(DashboardLayout(user_id=self.dewi.id, household_id=self.nusa_id, surface="beranda", items=[
                {"id": "a1", "card": "core.kpi.sisa_bebas", "size": "S", "hidden": False, "devices": "all"},
                {"id": "a2", "card": "core.karyawan.catat", "size": "M", "hidden": False, "devices": "all"}],
                parked=[], version=3))
            await db.commit()
        r = await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)
        self.assertEqual([(i["card"], i["visible"], i.get("alasan")) for i in r.json()["items"]],
                         [("core.kpi.sisa_bebas", False, "khusus_admin"), ("core.karyawan.catat", True, None)])
        r = await self._req("GET", "/dashboard/data/a1", header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.json()["error"]["kode"], "khusus_admin")
        # Dikirim balik apa adanya saat menyimpan: boleh, supaya instans tidak hilang.
        doc = (await self._req("GET", "/dashboard/layout", header=self.nusa_id, user=self.dewi)).json()
        items = [{k: i[k] for k in ("id", "card", "size", "hidden", "devices")} for i in doc["items"]]
        r = await self._req("PUT", "/dashboard/layout", {"if_version": 3, "items": items}, header=self.nusa_id,
                            user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_keluar_membuang_tata_letak(self):
        r = await self._simpan_satu(self.dewi)
        self.assertEqual(r.status_code, 200)
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/anggota/{self.dewi.id}", user=self.ani)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(await self._hitung(DashboardLayout, DashboardLayout.user_id == self.dewi.id), 0)

    # 4. Undangan, nama ruang, log ------------------------------------------------------------
    async def test_undangan_daftar_dan_cabut(self):
        kode = []
        for p in ("member", "admin"):
            r = await self._req("POST", f"/ruang/{self.nusa_id}/undangan", {"peran": p}, user=self.ani)
            kode.append(r.json()["kode"])
        async with self.Session() as db:
            db.add(RuangUndangan(household_id=self.nusa_id, kode="RUBASI000002", peran="member",
                                 kedaluwarsa=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await db.commit()
        r = await self._req("GET", f"/ruang/{self.nusa_id}/undangan", user=self.me)
        self.assertEqual(r.status_code, 200, r.text)
        daftar = r.json()
        self.assertEqual(sorted((u["kode"], u["peran"], u["dibuat_oleh"]) for u in daftar),
                         sorted([(kode[0], "member", "Ani"), (kode[1], "admin", "Ani")]))
        self.assertEqual(self._kode(await self._req("GET", f"/ruang/{self.nusa_id}/undangan", user=self.dewi)),
                         (403, "khusus_admin"))
        self.assertEqual((await self._req("GET", f"/ruang/{self.nusa_id}/undangan", user=self.orang)).status_code,
                         404)
        self.assertEqual((await self._req("GET", f"/ruang/{self.rumah_id}/undangan", user=self.me)).status_code, 404)

        id_member = next(u["id"] for u in daftar if u["kode"] == kode[0])
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{id_member}", user=self.dewi)
        self.assertEqual(self._kode(r), (403, "khusus_admin"))
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{id_member}", user=self.me)
        self.assertEqual(r.status_code, 204, r.text)
        r = await self._req("POST", "/ruang/gabung", {"kode": kode[0]}, user=self.rina)
        self.assertEqual(r.status_code, 400)
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{id_member}", user=self.me)
        self.assertEqual(r.status_code, 204)   # sudah dicabut: tidak berubah
        self.assertEqual([u["kode"] for u in (await self._req("GET", f"/ruang/{self.nusa_id}/undangan",
                                                              user=self.me)).json()], [kode[1]])
        self.assertEqual(await self._hitung(RuangAudit, RuangAudit.aksi == "undangan_dicabut"), 1)

        # Sudah dipakai → 409; id acak atau milik ruang lain → 404.
        r = await self._req("POST", "/ruang/gabung", {"kode": kode[1]}, user=self.rina)
        self.assertEqual(r.status_code, 200, r.text)
        async with self.Session() as db:
            id_admin = (await db.execute(select(RuangUndangan.id).where(RuangUndangan.kode == kode[1]))).scalar_one()
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{id_admin}", user=self.me)
        self.assertEqual(r.status_code, 409)
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{__import__('uuid').uuid4()}", user=self.me)
        self.assertEqual(r.status_code, 404)
        async with self.Session() as db:
            lain = Household(name="Toko Orang", type="usaha")
            db.add(lain)
            await db.flush()
            u = RuangUndangan(household_id=lain.id, kode="RULAIN000001", peran="member",
                              kedaluwarsa=datetime.now(timezone.utc) + timedelta(days=1))
            db.add(u)
            await db.commit()
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/undangan/{u.id}", user=self.me)
        self.assertEqual(r.status_code, 404)
        async with self.Session() as db:
            self.assertIsNone((await db.get(RuangUndangan, u.id)).dicabut_at)

    async def test_ganti_nama_ruang_dan_nama_di_log(self):
        r = await self._req("PATCH", f"/ruang/{self.nusa_id}", {"nama": "  Dapur   Nusa Jaya "}, user=self.ani)
        self.assertEqual((r.status_code, r.json()["nama"]), (200, "Dapur Nusa Jaya"), r.text)
        r = await self._req("GET", "/ruang", user=self.me)
        self.assertIn("Dapur Nusa Jaya", [x["nama"] for x in r.json()["items"]])
        self.assertEqual(self._kode(await self._req("PATCH", f"/ruang/{self.nusa_id}", {"nama": "x"}, user=self.dewi)),
                         (403, "khusus_admin"))
        self.assertEqual((await self._req("PATCH", f"/ruang/{self.rumah_id}", {"nama": "x"},
                                          user=self.me)).status_code, 404)
        self.assertEqual((await self._req("PATCH", f"/ruang/{self.nusa_id}", {"nama": "   "},
                                          user=self.me)).status_code, 422)
        self.assertEqual((await self._req("PATCH", f"/ruang/{self.nusa_id}", {"nama": "a" * 61},
                                          user=self.me)).status_code, 422)
        r = await self._req("GET", f"/ruang/{self.nusa_id}/audit", user=self.me)
        log = r.json()[0]
        self.assertEqual((log["aksi"], log["oleh_nama"], log["rincian"]["nama"]["ke"]),
                         ("ruang_diubah", "Ani", "Dapur Nusa Jaya"))

    async def test_daftar_ruang_membawa_jenis_catatan_karyawan(self):
        await self._batasan(jenis_catatan=["pengeluaran"])
        r = await self._req("GET", "/ruang", user=self.dewi)
        nusa = next(x for x in r.json()["items"] if x["id"] == str(self.nusa_id))
        self.assertEqual((nusa["peran"], nusa["jenis_catatan"]), ("member", ["pengeluaran"]))
        r = await self._req("GET", "/ruang", user=self.ani)
        self.assertIsNone(next(x for x in r.json()["items"] if x["id"] == str(self.nusa_id))["jenis_catatan"])


class RegistryKaryawanTests(unittest.TestCase):
    def test_kartu_karyawan_terpisah_dari_kartu_umum(self):
        self.assertEqual(peran.DRAF_DIPUTUS_HARI, 14)
        self.assertEqual(registry.TEMPLATE_KARYAWAN[0]["card"], "core.karyawan.catat")
        self.assertTrue(all(c.untuk == "karyawan" for c in registry.KARYAWAN))
        self.assertTrue(all(c.untuk == "umum" for c in registry.CORE))


if __name__ == "__main__":
    unittest.main()
