"""Plugin R7 — Catat cepat dan kamus per ruang (03-workflow.md baris R7; gerbang "Ruang keluarga tetap pribadi";
04-kontrak-api.md §2 kamus, §3 Catat cepat; ADR-P2, P5; AGENTS.md aturan 3 dan 8).

Pelaku sama dengan `test_ruang_peran.py`: Saya (owner Dapur Nusa), Ani (admin), Dewi (karyawan), Rina (anggota ruang
keluarga Saya), Orang (tidak terkait; di sini juga owner ruang usaha lain, Toko Orang).

Dikunci:
1. Belajar: catatan web bukan-privat ke amplop bersama ruang usaha mengajari kamus ruang (juga lewat antrean offline
   dan persetujuan draf, atas nama pencatat). Catatan privat, amplop pribadi, ruang keluarga, dan bot tidak.
2. Urutan cocok: kata user → kamus ruang → kamus kategori; `sumber` di saran. Kamus ruang hanya dibaca di ruang usaha
   yang sedang dicari, tidak pernah di ruang keluarga atau ruang usaha lain.
3. Karyawan: kandidat hanya amplop yang diizinkan (amplop terkunci tidak menutupi tebakan berikutnya); `aturan`
   batasan untuk nominal; owner/admin tanpa `aturan`.
4. Kamus di halaman Anggota: daftar dan hapus hanya owner/admin (karyawan 403 `khusus_admin`, ruang lain atau kata
   ruang lain 404, flag tertutup 404); hapus ikut menghapus kata user yang sama untuk amplop itu, tercatat di log.
5. Hapus akun pengajar: kata tetap milik ruang, nama pengajar dikosongkan.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_r7 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from decimal import Decimal as D

from app.tests import test_ruang_peran as r5
from app.tests.test_ruang_peran import HAS_AIOSQLITE

if HAS_AIOSQLITE:
    from sqlalchemy import func, select

    from app.models.models import (
        Allocation, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, Income, RuangAudit,
        RuangDraf, RuangKamus, Transaction, UserEnvelopeKeyword,
    )
    from app.services import txn_nlp


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangR7Tests(unittest.IsolatedAsyncioTestCase):
    # Fixture dan pembantu R5 (tanpa mewarisi tes R5, supaya tidak berjalan dua kali).
    async def asyncSetUp(self):
        # Batas frekuensi saran (60/menit) di memori proses, kunci = alamat IP di tes: direset per tes.
        from app.api.routes import transactions as rute_transaksi
        rute_transaksi.limiter.reset()
        self.addCleanup(rute_transaksi.limiter.reset)
        await r5.RuangPeranTests.asyncSetUp(self)
        async with self.Session() as db:
            # Ruang usaha kedua milik Orang, dengan kamusnya sendiri (untuk IDOR).
            toko = Household(name="Toko Orang", type=HouseholdType.USAHA)
            db.add(toko)
            await db.flush()
            db.add(HouseholdMember(user_id=self.orang.id, household_id=toko.id, role=HouseholdRole.owner))
            self.t = await self._isi(db, toko.id, self.orang.id, "Kardus Toko")
            kt = RuangKamus(household_id=toko.id, keyword="kardus", envelope_id=self.t["env"], count=50,
                            diajarkan_oleh=self.orang.id)
            db.add(kt)
            await db.commit()
        self.toko_id, self.kamus_toko_id = toko.id, kt.id

    _isi = r5.RuangPeranTests._isi
    _req = r5.RuangPeranTests._req
    _batasan = r5.RuangPeranTests._batasan
    _hitung = r5.RuangPeranTests._hitung
    _kode = r5.RuangPeranTests._kode

    async def _kamus(self, hid=None):
        async with self.Session() as db:
            rows = (await db.execute(select(RuangKamus).where(RuangKamus.household_id == (hid or self.nusa_id))
                                     .order_by(RuangKamus.keyword))).scalars().all()
        return {(k.keyword, k.envelope_id): (k.count, k.diajarkan_oleh) for k in rows}

    async def _ajari(self, kata, envelope_id, count, oleh, hid=None):
        async with self.Session() as db:
            db.add(RuangKamus(household_id=hid or self.nusa_id, keyword=kata, envelope_id=envelope_id, count=count,
                              diajarkan_oleh=oleh))
            await db.commit()

    async def _kata_user(self, user, kata, envelope_id, count=1):
        async with self.Session() as db:
            db.add(UserEnvelopeKeyword(user_id=user.id, keyword=kata, envelope_id=envelope_id, count=count))
            await db.commit()

    async def _saran(self, teks, user, header, amount=None):
        body = {"description": teks}
        if amount is not None:
            body["amount"] = amount
        r = await self._req("POST", "/transactions/suggest-envelope", body, header=header, user=user)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def _catat(self, user, envelope_id, teks, amount="25000", **kw):
        body = {"envelope_id": str(envelope_id), "amount": amount, "description": teks, **kw}
        return await self._req("POST", "/transactions/", body, user=user)

    async def _amplop_makan(self):
        """Amplop "Makan" di Dapur Nusa (nama kategori rumah tangga), berdana."""
        async with self.Session() as db:
            env = Envelope(household_id=self.nusa_id, name="Makan", emoji="🍜", budget_amount=D("100000"))
            db.add(env)
            await db.flush()
            inc = Income(household_id=self.nusa_id, user_id=self.me.id, amount=D("100000"), description="modal",
                         income_date=self.today)
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=env.id, amount=D("100000")))
            await db.commit()
        return env.id

    # 1. Belajar ----------------------------------------------------------
    async def test_catatan_ruang_usaha_mengajari_kamus_ruang(self):
        r = await self._catat(self.dewi, self.op_id, "Kardus 50 pcs")
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._catat(self.ani, self.op_id, "kardus besar")
        self.assertEqual(r.status_code, 201, r.text)
        kamus = await self._kamus()
        # Nominal/satuan bukan kata; pengajar = pencatat terakhir; hitungan bertambah per catatan.
        self.assertEqual(kamus[("kardus", self.op_id)], (2, self.ani.id))
        self.assertEqual(kamus[("besar", self.op_id)], (1, self.ani.id))
        self.assertNotIn(("pcs", self.op_id), kamus)
        self.assertNotIn(("50", self.op_id), kamus)

        # Antrean offline (`/transactions/batch`) mengajari juga.
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.op_id), "amount": "1000", "description": "elpiji", "client_ref": "b-1"}]},
            user=self.dewi)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self._kamus())[("elpiji", self.op_id)], (1, self.dewi.id))

    async def test_tidak_belajar_dari_privat_pribadi_keluarga_dan_bot(self):
        """Gerbang "Ruang keluarga tetap pribadi": kamus ruang terlihat admin, jadi catatan privat dan amplop pribadi
        tidak mengajarinya; ruang keluarga dan bot tidak pernah menulisnya."""
        # Sejak 11 Nov ruang usaha tidak punya pengeluaran privat lewat web (test_privat_ruang_usaha.py). Hook
        # sesudah-simpan tetap tidak mengajari kamus ruang dari catatan privat (lapis kedua, mis. data lama).
        r = await self._catat(self.me, self.op_id, "rahasia pribadi", is_private=True)
        self.assertEqual((r.status_code, r.json().get("kode")), (422, "privat_tidak_tersedia"), r.text)
        async with self.Session() as db:
            from app.api.routes.transactions import _after_saved
            me = await db.get(type(self.me), self.me.id)
            await _after_saved(db, me, None, transaction_id=uuid.uuid4(), envelope_id=self.op_id,
                               description="rahasia pribadi", is_private=True)
        async with self.Session() as db:
            pribadi = Envelope(household_id=self.nusa_id, name="Uang saku Saya", emoji="👛",
                               budget_amount=D("0"), owner_id=self.me.id)
            db.add(pribadi)
            await db.commit()
        async with self.Session() as db:
            self.assertEqual(await txn_nlp.ajari_kamus_ruang(db, self.me.id, "jajan rahasia", pribadi.id), 0)
            self.assertEqual(await txn_nlp.ajari_kamus_ruang(db, self.me.id, "kopi", self.u["tab"]), 0)  # tabungan
        r = await self._catat(self.me, self.k["env"], "kardus rumah")          # ruang keluarga, lewat web
        self.assertEqual(r.status_code, 201, r.text)
        async with self.Session() as db:   # jalur bot: hook yang sama tanpa `kamus_ruang`
            from app.services.expense_rules import after_expense_recorded
            me = await db.get(type(self.me), self.me.id)
            await after_expense_recorded(db, me, self.op_id, "kardus dari bot")
        self.assertEqual(await self._kamus(), {})
        self.assertEqual(await self._kamus(self.rumah_id), {})
        # Kata user sendiri tetap dipelajari seperti sebelum R7.
        self.assertEqual(await self._hitung(UserEnvelopeKeyword, UserEnvelopeKeyword.keyword == "rahasia"), 1)

    async def test_draf_disetujui_mengajari_atas_nama_pencatat(self):
        await self._batasan(batas_nominal=100000)
        r = await self._catat(self.dewi, self.op_id, "kardus jumbo", amount="500000", client_ref="d-1")
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(await self._kamus(), {})                               # draf belum mengajari
        r = await self._req("POST", f"/ruang/{self.nusa_id}/persetujuan/{r.json()['draf_id']}/setujui",
                            user=self.ani)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self._kamus())[("jumbo", self.op_id)], (1, self.dewi.id))

    # 2. Urutan cocok dan sumber ----------------------------------------------
    async def test_urutan_kata_user_kamus_ruang_kamus_kategori(self):
        makan = await self._amplop_makan()
        # Tanpa kamus: kamus kategori ("kopi" → makan).
        s = await self._saran("kopi susu", self.ani, self.nusa_id)
        self.assertEqual((s["envelope_id"], s["sumber"]), (str(makan), {"jenis": "kamus_kategori"}))
        # Kamus ruang mengalahkan kamus kategori, dengan pengajar dan hitungan.
        await self._ajari("kopi", self.op_id, 4, self.dewi.id)
        s = await self._saran("kopi susu", self.ani, self.nusa_id)
        self.assertEqual((s["envelope_id"], s["envelope_name"], s["confident"]), (str(self.op_id), "Operasional", True))
        self.assertEqual(s["sumber"], {"jenis": "kamus_ruang", "kali": 4, "oleh_saya": False,
                                       "diajarkan_oleh": "Dewi"})
        s = await self._saran("kopi susu", self.me, self.nusa_id)          # pemilik: pengajar orang lain
        self.assertEqual(s["sumber"], {"jenis": "kamus_ruang", "kali": 4, "oleh_saya": False,
                                       "diajarkan_oleh": "Dewi"})
        await self._ajari("susu", self.op_id, 1, self.ani.id)
        s = await self._saran("kopi susu", self.ani, self.nusa_id)          # kali = kata terbanyak, bukan jumlah
        self.assertEqual(s["sumber"], {"jenis": "kamus_ruang", "kali": 4, "oleh_saya": False,
                                       "diajarkan_oleh": "Dewi"})
        # Kata user sendiri mengalahkan kamus ruang.
        await self._kata_user(self.ani, "kopi", self.u["env"], count=1)
        s = await self._saran("kopi susu", self.ani, self.nusa_id)
        self.assertEqual((s["envelope_id"], s["sumber"]), (str(self.u["env"]), {"jenis": "kata_saya", "kali": 1}))
        # Field lama tetap ada; `aturan` kosong untuk admin.
        self.assertEqual(s["aturan"], [])

    async def test_kamus_tidak_dibaca_di_ruang_keluarga_atau_ruang_lain(self):
        """Kamus per ruang tidak terbawa (ADR-P5): kata Toko Orang tidak dipakai di Dapur Nusa, dan baris kamus yang
        (secara salah) menunjuk ruang keluarga tidak dibaca karena gerbangnya jenis ruang di kueri."""
        s = await self._saran("kardus", self.me, self.nusa_id)       # Toko Orang punya "kardus" ×50
        self.assertIsNone(s["envelope_id"])
        await self._ajari("kardus", self.k["env"], 9, self.me.id, hid=self.rumah_id)
        s = await self._saran("kardus", self.me, None)                # ruang keluarga
        self.assertIsNone(s["envelope_id"])
        async with self.Session() as db:                              # jalur bot / chat
            env, _ = await txn_nlp.find_best_envelope("kardus", self.rumah_id, db, self.me.id)
        self.assertIsNone(env)
        s = await self._saran("kardus", self.orang, self.toko_id)
        self.assertEqual((s["envelope_id"], s["sumber"]["jenis"]), (str(self.t["env"]), "kamus_ruang"))

    # 3. Karyawan -------------------------------------------------------------
    async def test_karyawan_hanya_amplop_diizinkan_dan_aturan(self):
        await self._ajari("kardus", self.op_id, 9, self.ani.id)
        await self._ajari("kardus", self.u["env"], 1, self.ani.id)
        await self._batasan(amplop_ids=[str(self.u["env"])], foto_nota_di_atas=300000, batas_nominal=1000000)
        s = await self._saran("kardus", self.dewi, self.nusa_id)
        self.assertEqual((s["envelope_id"], s["sumber"]), (str(self.u["env"]), {"jenis": "kamus_ruang"}))
        r = await self._req("POST", "/transactions/suggest-envelopes", {"descriptions": ["kardus"]},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.json()["results"][0]["envelope_id"], str(self.u["env"]))
        s = await self._saran("kardus", self.ani, self.nusa_id)       # admin: tidak dibatasi
        self.assertEqual(s["envelope_id"], str(self.op_id))

        s = await self._saran("kardus", self.dewi, self.nusa_id, amount=2000000)
        self.assertEqual([a["kode"] for a in s["aturan"]], ["foto_nota", "persetujuan"])
        self.assertIn("Rp300.000", s["aturan"][0]["teks"])
        s = await self._saran("kardus", self.dewi, self.nusa_id, amount=500000)
        self.assertEqual([a["kode"] for a in s["aturan"]], ["foto_nota"])
        self.assertEqual((await self._saran("kardus", self.dewi, self.nusa_id, amount=100))["aturan"], [])
        self.assertEqual((await self._saran("kardus", self.dewi, self.nusa_id))["aturan"], [])
        self.assertEqual((await self._saran("kardus", self.ani, self.nusa_id, amount=2000000))["aturan"], [])
        # Aturan juga dijawab saat teks kosong (nominal diketik lebih dulu).
        self.assertEqual(len((await self._saran(" ", self.dewi, self.nusa_id, amount=2000000))["aturan"]), 2)

    async def test_karyawan_tidak_bisa_menebak_catatan_lain_lewat_kamus(self):
        """Review keamanan PR #191 temuan 2 (PoC3), keputusan pemilik produk 5 Nov: tebakan kamus ruang untuk karyawan
        tanpa nama pengajar dan hitungan; pemilik/admin tetap melihatnya. Saran dibatasi panjang dan jumlahnya."""
        for _ in range(3):
            r = await self._catat(self.me, self.op_id, "kasbon bagas")
            self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("GET", "/transactions/", header=self.nusa_id, user=self.dewi)
        self.assertEqual((r.status_code, r.json()), (200, []))
        s = await self._saran("kasbon bagas", self.dewi, self.nusa_id)
        self.assertEqual((s["envelope_id"], s["sumber"]), (str(self.op_id), {"jenis": "kamus_ruang"}))
        r = await self._req("POST", "/transactions/suggest-envelopes", {"descriptions": ["kasbon bagas"]},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.json()["results"][0]["sumber"], {"jenis": "kamus_ruang"})
        s = await self._saran("kasbon bagas", self.ani, self.nusa_id)
        self.assertEqual(s["sumber"], {"jenis": "kamus_ruang", "kali": 3, "oleh_saya": False,
                                       "diajarkan_oleh": "Saya"})
        s = await self._saran("kasbon", self.dewi, self.nusa_id)
        self.assertEqual(s["sumber"], {"jenis": "kamus_ruang"})
        # Kata yang dicatat karyawan sendiri: datanya sendiri (`kata_saya`, dengan hitungan), seperti sebelum R7.
        r = await self._catat(self.dewi, self.op_id, "elpiji")
        self.assertEqual(r.status_code, 201, r.text)
        s = await self._saran("elpiji", self.dewi, self.nusa_id)
        self.assertEqual(s["sumber"], {"jenis": "kata_saya", "kali": 1})

        r = await self._req("POST", "/transactions/suggest-envelopes", {"descriptions": ["x"] * 101},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 422)
        r = await self._req("POST", "/transactions/suggest-envelope", {"description": "x" * 501},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(r.status_code, 422)
        r = await self._req("POST", "/transactions/suggest-envelopes", {"descriptions": ["kardus"] * 100},
                            header=self.nusa_id, user=self.ani)
        self.assertEqual(len(r.json()["results"]), 100)

    # 4. Kamus di halaman Anggota ----------------------------------------------
    async def test_daftar_kamus_untuk_owner_dan_admin_saja(self):
        await self._ajari("kardus", self.op_id, 4, self.dewi.id)
        await self._ajari("elpiji", self.op_id, 6, None)
        await self._ajari("ayam", self.u["env"], 12, self.me.id)
        for user in (self.me, self.ani):
            r = await self._req("GET", f"/ruang/{self.nusa_id}/kamus", user=user)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["total"], 3)
            self.assertEqual([(i["kata"], i["amplop"], i["kali"], i["diajarkan_oleh"]) for i in body["items"]],
                             [("ayam", "Bahan", 12, "Saya"), ("elpiji", "Operasional", 6, None),
                              ("kardus", "Operasional", 4, "Dewi")])
        r = await self._req("GET", f"/ruang/{self.nusa_id}/kamus", params={"q": "ard", "limit": 5}, user=self.me)
        self.assertEqual(([i["kata"] for i in r.json()["items"]], r.json()["total"]), (["kardus"], 3))
        r = await self._req("GET", f"/ruang/{self.nusa_id}/kamus", params={"q": "%"}, user=self.me)
        self.assertEqual(r.json()["items"], [])                         # `%` bukan wildcard

        self.assertEqual(self._kode(await self._req("GET", f"/ruang/{self.nusa_id}/kamus", user=self.dewi)),
                         (403, "khusus_admin"))
        for user, rid in ((self.orang, self.nusa_id), (self.me, self.toko_id), (self.me, self.rumah_id),
                          (self.rina, self.rumah_id)):
            r = await self._req("GET", f"/ruang/{rid}/kamus", user=user)
            self.assertEqual(r.status_code, 404, (user.name, r.text))
        self.flag.value = ""                                            # flag ruang usaha ditutup
        async with self.Session() as db:
            await db.merge(self.flag)
            await db.commit()
        r = await self._req("GET", f"/ruang/{self.nusa_id}/kamus", user=self.me)
        self.assertEqual(r.status_code, 404)

    async def test_hapus_kata_beserta_kata_user_di_ruang_itu(self):
        await self._ajari("kardus", self.op_id, 4, self.dewi.id)
        await self._ajari("kardus", self.u["env"], 2, self.dewi.id)
        await self._kata_user(self.dewi, "kardus", self.op_id)                 # dihapus bersama
        await self._kata_user(self.dewi, "kardus", self.u["env"])               # amplop lain: tetap
        await self._kata_user(self.dewi, "kardus", self.kd["env"])              # ruang keluarga Dewi: tetap
        await self._kata_user(self.ani, "elpiji", self.op_id)                   # kata lain: tetap
        await self._kata_user(self.ani, "kardus pcs 125rb", self.op_id)         # frasa yang sama tanpa satuan: dihapus
        await self._kata_user(self.ani, "kardus besar", self.op_id)             # frasa lain: tetap
        async with self.Session() as db:
            kid = (await db.execute(select(RuangKamus.id).where(
                RuangKamus.keyword == "kardus", RuangKamus.envelope_id == self.op_id))).scalar_one()

        self.assertEqual(self._kode(await self._req("DELETE", f"/ruang/{self.nusa_id}/kamus/{kid}", user=self.dewi)),
                         (403, "khusus_admin"))
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/kamus/{self.kamus_toko_id}", user=self.me)
        self.assertEqual(r.status_code, 404)                                   # kata ruang lain lewat ruang sendiri
        r = await self._req("DELETE", f"/ruang/{self.toko_id}/kamus/{kid}", user=self.me)
        self.assertEqual(r.status_code, 404)                                   # bukan anggota Toko Orang
        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/kamus/{uuid.uuid4()}", user=self.ani)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(await self._kamus()), 2)

        r = await self._req("DELETE", f"/ruang/{self.nusa_id}/kamus/{kid}", user=self.ani)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(set(await self._kamus()), {("kardus", self.u["env"])})
        async with self.Session() as db:
            sisa = set((await db.execute(select(UserEnvelopeKeyword.user_id, UserEnvelopeKeyword.keyword,
                                                UserEnvelopeKeyword.envelope_id))).all())
            log = (await db.execute(select(RuangAudit).where(RuangAudit.aksi == "kata_dihapus"))).scalar_one()
        self.assertEqual(sisa, {(self.dewi.id, "kardus", self.u["env"]), (self.dewi.id, "kardus", self.kd["env"]),
                                (self.ani.id, "elpiji", self.op_id), (self.ani.id, "kardus besar", self.op_id)})
        self.assertEqual((log.household_id, log.actor_id, log.rincian["kata"], log.rincian["amplop"]),
                         (self.nusa_id, self.ani.id, "kardus", "Operasional"))
        self.assertEqual((await self._kamus(self.toko_id))[("kardus", self.t["env"])][0], 50)   # Toko Orang utuh
        # Sesudah dihapus, Dewi tidak lagi mendapat Operasional untuk "kardus".
        s = await self._saran("kardus", self.dewi, self.nusa_id)
        self.assertEqual(s["envelope_id"], str(self.u["env"]))

    async def test_reset_ruang_usaha_menghapus_kamusnya_saja(self):
        await self._ajari("kardus", self.op_id, 4, self.dewi.id)
        await self._ajari("kardus", self.k["env"], 1, self.me.id, hid=self.rumah_id)
        r = await self._req("POST", "/user/reset", {}, header=self.nusa_id, user=self.me)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(await self._kamus(), {})
        self.assertEqual(len(await self._kamus(self.toko_id)), 1)
        self.assertEqual(len(await self._kamus(self.rumah_id)), 1)

    # 6. Review keamanan PR #191 ------------------------------------------------
    async def _transaksi_keluarga_dewi(self):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(Transaction).where(
                Transaction.envelope_id == self.kd["env"], Transaction.description == "pulsa"))).scalar_one()

    async def test_ref_draf_ruang_usaha_tidak_menjawab_catatan_ruang_keluarga(self):
        """Temuan 1, PoC1: draf ruang usaha (di atas batas) lalu kiriman ke amplop ruang keluarga dengan client_ref yang
        sama → 409 `client_ref_bentrok`, bukan 202 draf ruang usaha; tidak ada transaksi ruang keluarga yang hilang
        diam-diam, dan draf tetap menunggu admin. Sama lewat antrean offline."""
        await self._batasan(batas_nominal=100000)
        r = await self._catat(self.dewi, self.op_id, "pulsa", amount="500000", client_ref="ref-1")
        self.assertEqual(r.status_code, 202, r.text)
        draf_id = r.json()["draf_id"]
        r = await self._catat(self.dewi, self.kd["env"], "pulsa", amount="500000", client_ref="ref-1")
        self.assertEqual(self._kode(r), (409, "client_ref_bentrok"))
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.kd["env"]), "amount": "500000", "description": "pulsa", "client_ref": "ref-1"}]},
            user=self.dewi)
        self.assertEqual((r.json()[0]["ok"], r.json()[0]["kode"]), (False, "client_ref_bentrok"))
        self.assertIsNone(r.json()[0].get("draf_id"))
        self.assertEqual(await self._transaksi_keluarga_dewi(), 0)
        async with self.Session() as db:
            d = await db.get(RuangDraf, uuid.UUID(draf_id))
        self.assertEqual(d.status, "menunggu")
        # Amplop ruang usaha lain dengan ref yang sama juga bukan draf itu; kiriman ulang yang sama tetap 202.
        r = await self._catat(self.dewi, self.u["env"], "pulsa", amount="500000", client_ref="ref-1")
        self.assertEqual(self._kode(r), (409, "client_ref_bentrok"))
        r = await self._catat(self.dewi, self.op_id, "pulsa", amount="500000", client_ref="ref-1")
        self.assertEqual((r.status_code, r.json()["draf_id"]), (202, draf_id))
        # Penjualan dengan ref draf pengeluaran: jenis lain → 409, bukan draf pengeluaran.
        r = await self._req("POST", "/incomes/", {"amount": "500000", "source": "jual", "client_ref": "ref-1",
                                                  "allocations": [{"envelope_id": str(self.op_id), "amount": "500000"}]},
                            header=self.nusa_id, user=self.dewi)
        self.assertEqual(self._kode(r), (409, "client_ref_bentrok"))

    def test_cek_ref_draf_tanpa_amplop_tetap_memeriksa_ruang(self):
        """Pembantu `cek_ref_draf` tanpa amplop (pemanggil tanpa alokasi) tetap menolak draf ruang lain."""
        from types import SimpleNamespace
        from app.services import peran
        draf = SimpleNamespace(household_id=self.nusa_id, jenis="penjualan", envelope_id=self.op_id)
        peran.cek_ref_draf(draf, household_id=self.nusa_id, jenis="penjualan")
        for kw in ({"household_id": self.rumah_dewi_id, "jenis": "penjualan"},
                   {"household_id": self.nusa_id, "jenis": "pengeluaran"},
                   {"household_id": self.nusa_id, "jenis": "penjualan", "envelope_id": self.u["env"]}):
            with self.subTest(**{k: str(v) for k, v in kw.items()}), self.assertRaises(peran.PeranDitolak) as cm:
                peran.cek_ref_draf(draf, **kw)
            self.assertEqual((cm.exception.kode, cm.exception.status_code), ("client_ref_bentrok", 409))

    async def test_ref_transaksi_ruang_usaha_tidak_menjawab_catatan_ruang_keluarga(self):
        """Temuan 1, PoC2: catatan ruang usaha tersimpan lalu kiriman ke amplop ruang keluarga dengan client_ref yang
        sama → 409, bukan 201 berisi transaksi Operasional. Kiriman ulang yang sama persis tetap 201 transaksi lama."""
        r = await self._catat(self.dewi, self.op_id, "pulsa", client_ref="ref-2")
        self.assertEqual(r.status_code, 201, r.text)
        txn_id = r.json()["id"]
        r = await self._catat(self.dewi, self.kd["env"], "pulsa", client_ref="ref-2")
        self.assertEqual(self._kode(r), (409, "client_ref_bentrok"))
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.kd["env"]), "amount": "25000", "description": "pulsa", "client_ref": "ref-2"}]},
            user=self.dewi)
        self.assertEqual((r.json()[0]["ok"], r.json()[0]["kode"], r.json()[0].get("id")),
                         (False, "client_ref_bentrok", None))
        self.assertEqual(await self._transaksi_keluarga_dewi(), 0)
        r = await self._catat(self.dewi, self.op_id, "pulsa", client_ref="ref-2")
        self.assertEqual((r.status_code, r.json()["id"]), (201, txn_id))
        r = await self._req("POST", "/transactions/batch", {"items": [
            {"envelope_id": str(self.op_id), "amount": "25000", "description": "pulsa", "client_ref": "ref-2"}]},
            user=self.dewi)
        self.assertEqual((r.json()[0]["ok"], r.json()[0]["id"]), (True, txn_id))
        # Arah sebaliknya: catatan ruang keluarga dulu, lalu ruang usaha dengan ref yang sama.
        r = await self._catat(self.dewi, self.kd["env"], "pulsa", client_ref="ref-3")
        self.assertEqual(r.status_code, 201, r.text)
        r = await self._catat(self.dewi, self.op_id, "pulsa", client_ref="ref-3")
        self.assertEqual(self._kode(r), (409, "client_ref_bentrok"))

    # 5. Hapus akun -----------------------------------------------------------
    async def test_hapus_akun_pengajar_mengosongkan_nama(self):
        await self._ajari("kardus", self.op_id, 4, self.ani.id)
        from app.services.account_deletion import delete_account
        async with self.Session() as db:
            ani = await db.get(type(self.ani), self.ani.id)
            await delete_account(db, ani)
        self.assertEqual(await self._kamus(), {("kardus", self.op_id): (4, None)})
        async with self.Session() as db:
            n = (await db.execute(select(func.count()).select_from(RuangKamus))).scalar_one()
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
