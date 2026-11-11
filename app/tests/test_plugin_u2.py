"""Plugin U2 — penjualan dan alokasi omzet (03-workflow.md baris U2; 04-kontrak-api.md §5, §6; AGENTS.md "Plugin dan
ruang" aturan 1, 3, 4, 5, 8; ADR-P1, P4, P9, P11).

1. Pembantu murni (`buku_usaha/alokasi.py`): pembagian selalu persis (pembulatan per rupiah, sisa ke persen terbesar),
   aturan 100%, angka dari JSON tanpa pecahan biner.
2. Manifest dan host: `incomes:write` hanya untuk rute; `simpan_field` opsional per target; `options` field `select`;
   Plugin API 1.3.
3. Izin baru untuk instalasi yang sudah ada tidak pernah diberikan diam-diam: `izin_baru` di katalog, rute penjualan
   403 `tanpa_izin`, persetujuan lewat `POST …/izin` terikat daftar yang dilihat (409 `izin_berubah`), owner/admin.
4. Alokasi omzet: saran 45/30/15/9/1, validasi 100%, amplop pribadi/ruang lain ditolak, simpan ulang mengganti.
5. Penjualan per jenis: pratinjau = yang dicatat; pemasukan inti + pembagian + `income_meta` dalam SATU commit (gagal di
   tengah = tidak ada apa pun); tanpa sisa ke Tabungan; pelanggan hanya untuk penjualan; tanggal; audit.
6. `ctx.catat_pemasukan` langsung: hanya rute non-GET, owner/admin, izin, amplop ruang konteks, pembagian = jumlah.
7. Pemasok + akun di form pengeluaran (`POST /transactions/` `tambahan`): tersimpan di `txn_meta` bersama transaksi;
   isian salah/karyawan/ruang keluarga 422 tanpa transaksi; gagal simpan membatalkan transaksinya.
8. Isolasi: ruang lain, karyawan, ruang keluarga.

Run: python -m unittest app.tests.test_plugin_u2 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import json
import pathlib
import unittest
from datetime import datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.plugins.buku_usaha import alokasi as al
from app.plugins.host import kode as kode_mod
from app.plugins.host.manifest import PLUGIN_API_VERSION, Manifest
from app.plugins.host.registry import muat, pakai_registry
from app.plugins.sdk import NilaiTidakSah, Plugin

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
FOLDER_BU = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "buku_usaha"
MANIFEST_BU = json.loads((FOLDER_BU / "manifest.json").read_text())
JKT = ZoneInfo("Asia/Jakarta")


# ── 1. pembantu murni ────────────────────────────────────────────────────
class AlokasiMurniTests(unittest.TestCase):
    A3 = [("bahan", D(45)), ("op", D(30)), ("prive", D(15)), ("laba", D(9)), ("pajak", D(1))]

    def test_bagi_selalu_persis(self):
        for jumlah in (D("1000000"), D("1000001"), D("999.99"), D("1"), D("48650000"), D("123457.89")):
            bagian = al.bagi(jumlah, self.A3)
            self.assertEqual(sum(bagian), jumlah, jumlah)
            self.assertTrue(all(b >= 0 for b in bagian))

    def test_sisa_pembulatan_ke_persen_terbesar(self):
        self.assertEqual(al.bagi(D("1000001"), self.A3),
                         [D("450001.00"), D("300000.00"), D("150000.00"), D("90000.00"), D("10000.00")])
        # Persen sama: yang pertama mendapat sisa; sen ikut sisa.
        self.assertEqual(al.bagi(D("100.50"), [("a", D(50)), ("b", D(50))]), [D("50.50"), D("50.00")])
        self.assertEqual(al.bagi(D("10"), [("a", D("33.33")), ("b", D("33.33")), ("c", D("33.34"))]),
                         [D("3.00"), D("3.00"), D("4.00")])

    def test_bagi_butuh_100(self):
        with self.assertRaises(ValueError):
            al.bagi(D("100"), [("a", D(60)), ("b", D(30))])

    def test_rapikan_aturan(self):
        self.assertEqual(al.rapikan_aturan([{"envelope_id": "a", "persen": 45.5}, {"envelope_id": "b", "persen": "54.5"}]),
                         [("a", D("45.5")), ("b", D("54.5"))])
        for salah in ([], None, [{"envelope_id": "a", "persen": 0}], [{"envelope_id": "a", "persen": 101}],
                      [{"envelope_id": "a", "persen": "1.234"}], [{"envelope_id": "a", "persen": True}],
                      [{"envelope_id": "a", "persen": 50}, {"envelope_id": "a", "persen": 50}],
                      [{"envelope_id": "a", "persen": 50, "lain": 1}], [{"envelope_id": 5, "persen": 50}],
                      [{"envelope_id": str(i), "persen": 1} for i in range(11)]):
            with self.assertRaises(NilaiTidakSah, msg=salah):
                al.rapikan_aturan(salah)

    def test_angka_dan_tanggal(self):
        self.assertEqual(al.jumlah_uang(150000), D("150000"))
        self.assertEqual(al.jumlah_uang("150000.5"), D("150000.5"))
        self.assertEqual(al.jumlah_uang(0.1), D("0.1"))       # pecahan JSON lewat teksnya
        for salah in (0, -5, "abc", None, True, "1.001", "NaN", "1e20"):
            with self.assertRaises(NilaiTidakSah, msg=salah):
                al.jumlah_uang(salah)
        self.assertIsNone(al.tanggal(None))
        self.assertEqual(al.tanggal("2026-11-01").isoformat(), "2026-11-01")
        for salah in ("1/11/2026", "2026-13-01", 20261101):
            with self.assertRaises(NilaiTidakSah):
                al.tanggal(salah)

    def test_keterangan(self):
        self.assertEqual(al.keterangan("penjualan", None, "PT Arunika"), "Penjualan · PT Arunika")
        self.assertEqual(al.keterangan("modal", "  setor   modal ", None), "setor modal")
        self.assertEqual(al.keterangan("lain", "", None), "Lain-lain")
        with self.assertRaises(NilaiTidakSah):
            al.keterangan("penjualan", "x" * 201, None)


# ── 2. manifest dan host ─────────────────────────────────────────────────
class ManifestU2Tests(unittest.TestCase):
    def test_manifest_buku_usaha(self):
        reg = muat(FOLDER_BU.parent, ketat=True)
        m = reg.get("buku_usaha")
        self.assertEqual(m.permissions, MANIFEST_BU["permissions"])     # U3 menambah izin baca
        self.assertIn("incomes:write", m.permissions)
        self.assertEqual([a.key for a in m.contributes.quick_actions], ["buku_usaha.penjualan"])
        f = {x.key: x for x in m.contributes.form_fields}
        self.assertEqual(f["pemasok"].entity, "p_buku_usaha_kontak")
        from app.plugins import buku_usaha
        self.assertEqual(tuple(f["akun"].options), buku_usaha.AKUN_BEBAN)
        self.assertGreaterEqual(PLUGIN_API_VERSION, (1, 3, 0))

    def test_incomes_write_hanya_rute(self):
        for jenis, izin in kode_mod.IZIN_PER_JENIS.items():
            self.assertEqual("incomes:write" in izin, jenis == "rute", jenis)
            self.assertNotIn("transactions:write", izin)
            self.assertNotIn("envelopes:write", izin)

    def _mf(self, **contributes):
        return Manifest.model_validate({
            "id": "uji", "name": "Uji", "version": "1.0.0", "publisher": "Jatahku", "description": "Uji U2",
            "engines": {"plugin_api": ">=1.3 <2.0"}, "space_types": ["usaha"],
            "permissions": ["envelopes:read", "incomes:write"], "entities": [], "contributes": contributes})

    def test_options_select(self):
        self._mf(form_fields=[{"target": "transaction", "key": "akun", "type": "select", "label": "A",
                               "options": ["x", "y"]}])
        for salah in ([{"target": "transaction", "key": "akun", "type": "select", "label": "A"}],
                      [{"target": "transaction", "key": "akun", "type": "select", "label": "A", "options": ["x", "x"]}],
                      [{"target": "transaction", "key": "akun", "type": "text", "label": "A", "options": ["x"]}],
                      [{"target": "transaction", "key": "ref", "type": "reference", "label": "R"}]):
            with self.assertRaises(Exception, msg=salah):
                self._mf(form_fields=salah)

    def test_simpan_field_opsional_dan_terikat_manifest(self):
        m = self._mf(form_fields=[{"target": "transaction", "key": "proyek", "type": "text", "label": "P"}],
                     routes=[{"method": "POST", "path": "/x"}, {"method": "GET", "path": "/y"}])
        p = Plugin("uji")

        @p.field_form("transaction", "proyek")
        async def f(ctx, v):
            return v

        @p.rute("POST", "/x", izin=["incomes:write"])
        async def x(ctx, req):
            return {}

        @p.rute("GET", "/y")
        async def y(ctx, req):
            return {}
        self.assertEqual(kode_mod.cocokkan(m, p), [])       # tanpa simpan_field: boleh

        @p.simpan_field("income")
        async def s(ctx, tid, nilai):
            return None

        @p.field_form("transaction", "lain")
        async def g(ctx, v):
            return v
        galat = "\n".join(kode_mod.cocokkan(m, p))
        self.assertIn("simpan_field 'income' didaftarkan di kode tetapi tidak ada di manifest", galat)

        q = Plugin("uji")

        @q.simpan_field("transaction", izin=["incomes:write"])
        async def s2(ctx, tid, nilai):
            return None
        self.assertIn("tidak boleh untuk simpan_field", "\n".join(kode_mod.cocokkan(m, q)))


# ── 3–8. SQLite ──────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import event, func, select

    from app.api.routes import incomes as incomes_route
    from app.api.routes import plugins as plugins_route
    from app.api.routes import transactions as transactions_route
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        Allocation, AppSetting, BukuUsahaIncomeMeta, BukuUsahaTxnMeta, Envelope, Household, HouseholdMember,
        HouseholdRole, HouseholdType, Income, PluginAuditLog, PluginInstallation, PurposeType, Transaction, User,
    )
    from app.plugins.host import data as data_plugin
    from app.plugins.host import inti, keadaan, titik
    from app.plugins.host.keadaan import pakai_sesi
    from app.plugins.sdk import IzinDitolak
    from app.plugins.sdk.plugin import Pendaftaran
    from app.services import ruang
    from app.tests.test_ruang_gerbang import _Redis


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class U2DbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)

        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.reg = muat(FOLDER_BU.parent, ketat=True)
        for ctx in (pakai_registry(self.reg), pakai_sesi(self.Session)):
            ctx.__enter__()
            self.addCleanup(ctx.__exit__, None, None, None)
        p = patch("redis.asyncio.from_url", return_value=_Redis())
        p.start()
        self.addCleanup(p.stop)
        self.today = datetime.now(JKT).date()

        async with self.Session() as db:
            mk = lambda n: User(name=n, plan="pro", timezone="Asia/Jakarta", payday_day=1)  # noqa: E731
            pemilik, admin, karyawan, orang = (mk(n) for n in ("Pemilik", "Admin", "Karyawan", "Orang"))
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            usaha2 = Household(name="Toko Kedua", type=HouseholdType.USAHA)
            rumah = Household(name="Rumah", type=HouseholdType.RUMAH_TANGGA)
            db.add_all([pemilik, admin, karyawan, orang, usaha, usaha2, rumah])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=pemilik.id, household_id=usaha.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=admin.id, household_id=usaha.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=karyawan.id, household_id=usaha.id, role=HouseholdRole.member),
                HouseholdMember(user_id=pemilik.id, household_id=usaha2.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=pemilik.id, household_id=rumah.id, role=HouseholdRole.owner),
                AppSetting(key="plugin_buku_usaha_users", value="*"),
                AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"),
            ])
            self.env = {}
            for nama, tujuan, anggaran in (("Bahan", PurposeType.expense, D("5000000")),
                                           ("Operasional", PurposeType.expense, D("2000000")),
                                           ("Prive", PurposeType.saving, D(0)),
                                           ("Laba ditahan", PurposeType.saving, D(0)),
                                           ("Pajak", PurposeType.saving, D(0))):
                e = Envelope(household_id=usaha.id, name=nama, emoji="•", budget_amount=anggaran, purpose=tujuan)
                db.add(e)
                await db.flush()
                self.env[nama] = e.id
            pribadi = Envelope(household_id=usaha.id, name="Pribadi pemilik", emoji="🔒", budget_amount=0,
                               owner_id=pemilik.id)
            lain = Envelope(household_id=usaha2.id, name="Bahan toko", emoji="•", budget_amount=D("1000000"))
            rumah_env = Envelope(household_id=rumah.id, name="Makan", emoji="•", budget_amount=D("1000000"))
            db.add_all([pribadi, lain, rumah_env])
            await db.flush()
            # Dana awal Bahan (supaya pengeluaran boleh) dan amplop rumah.
            modal = Income(household_id=usaha.id, user_id=pemilik.id, amount=D("3000000"), description="modal awal",
                           income_date=self.today)
            mr = Income(household_id=rumah.id, user_id=pemilik.id, amount=D("1000000"), description="gaji",
                        income_date=self.today)
            db.add_all([modal, mr])
            await db.flush()
            db.add_all([Allocation(income_id=modal.id, envelope_id=self.env["Bahan"], amount=D("3000000")),
                        Allocation(income_id=mr.id, envelope_id=rumah_env.id, amount=D("1000000"))])
            await db.commit()
        self.pemilik, self.admin, self.karyawan, self.orang = pemilik, admin, karyawan, orang
        self.usaha, self.usaha2, self.rumah = usaha.id, usaha2.id, rumah.id
        self.pribadi, self.env_lain, self.env_rumah = pribadi.id, lain.id, rumah_env.id

        self.current = pemilik
        app = FastAPI()
        ruang.install(app)
        app.include_router(plugins_route.router, prefix="/plugins")
        app.include_router(plugins_route.ruang_router, prefix="/ruang")
        app.include_router(plugins_route.p_router, prefix="/p")
        app.include_router(transactions_route.router, prefix="/transactions")
        app.include_router(incomes_route.router, prefix="/incomes")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ──
    def hdr(self, hid=None):
        return {"X-Jatahku-Ruang": str(hid or self.usaha)}

    async def aksi(self, aksi, hid=None, body=None, status=200):
        r = await self.client.post(f"/ruang/{hid or self.usaha}/plugins/buku_usaha/{aksi}", json=body or {})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    async def pasang_aktif(self, hid=None):
        await self.aksi("pasang", hid, {"izin": MANIFEST_BU["permissions"]})
        self.assertEqual((await self.aksi("lanjut", hid))["status"], "aktif")

    async def p(self, metode, path, hid=None, status=None, **kw):
        r = await self.client.request(metode, f"/p/buku_usaha{path}", headers=self.hdr(hid), **kw)
        if status is not None:
            self.assertEqual(r.status_code, status, r.text)
        return r

    def kode(self, r):
        return r.json().get("kode") or r.json().get("detail", {}).get("kode")

    async def kontak(self, nama, peran, hid=None):
        return (await self.p("POST", "/kontak", hid, 201, json={"nama": nama, "peran": peran})).json()

    async def atur_a3(self):
        aturan = [{"envelope_id": str(self.env[n]), "persen": p} for n, p in al.SARAN_PERSEN.items()]
        return (await self.p("PUT", "/alokasi", status=200, json={"aturan": aturan})).json()

    async def hitung(self, model, *where):
        async with self.Session() as db:
            return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar())

    async def katalog(self, hid=None):
        r = await self.client.get("/plugins", headers=self.hdr(hid))
        self.assertEqual(r.status_code, 200, r.text)
        return {x["id"]: x for x in r.json()}

    # ── 3. izin baru ──
    async def test_izin_baru_tidak_diberikan_diam_diam(self):
        await self.pasang_aktif()
        async with self.Session() as db:     # instalasi lama (U1): hanya envelopes:read
            inst = (await db.execute(select(PluginInstallation))).scalar_one()
            inst.granted_permissions = ["envelopes:read"]
            await db.commit()
        await self.atur_a3()
        self.assertEqual((await self.katalog())["buku_usaha"]["izin_baru"],
                         [x for x in MANIFEST_BU["permissions"] if x != "envelopes:read"])
        r = await self.p("POST", "/penjualan", status=403, json={"jumlah": 100000})
        self.assertEqual(self.kode(r), "tanpa_izin")
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 0)
        # Kontak dan alokasi (tanpa izin baru) tetap jalan.
        await self.p("GET", "/alokasi", status=200)

        await self.aksi("izin", body={"izin": ["envelopes:read"]}, status=409)            # bukan yang di manifest
        await self.aksi("izin", body={}, status=422)
        self.current = self.karyawan
        r = await self.client.post(f"/ruang/{self.usaha}/plugins/buku_usaha/izin",
                                   json={"izin": MANIFEST_BU["permissions"]})
        self.assertEqual(r.status_code, 403, r.text)
        self.current = self.admin
        out = await self.aksi("izin", body={"izin": MANIFEST_BU["permissions"]})
        self.assertEqual((out["status"], out["izin_baru"]), ("aktif", []))
        self.current = self.pemilik
        await self.p("POST", "/penjualan", status=201, json={"jumlah": 100000})
        async with self.Session() as db:
            aksi = (await db.execute(select(PluginAuditLog.action).where(PluginAuditLog.action == "izin"))).scalars().all()
        self.assertEqual(aksi, ["izin"])

    async def test_izin_tidak_bisa_untuk_plugin_belum_terpasang(self):
        await self.aksi("izin", body={"izin": MANIFEST_BU["permissions"]}, status=404)
        await self.pasang_aktif()
        await self.aksi("copot")
        await self.aksi("izin", body={"izin": MANIFEST_BU["permissions"]}, status=404)

    # ── 4. alokasi ──
    async def test_alokasi_saran_validasi_dan_ganti(self):
        await self.pasang_aktif()
        out = (await self.p("GET", "/alokasi", status=200)).json()
        self.assertEqual((out["aturan"], out["siap"], out["tersimpan"]), ([], False, False))
        self.assertEqual([(x["nama"], x["persen"]) for x in out["saran"]],
                         [("Bahan", 45), ("Operasional", 30), ("Prive", 15), ("Laba ditahan", 9), ("Pajak", 1)])
        self.assertNotIn(str(self.pribadi), [a["envelope_id"] for a in out["amplop"]])

        def aturan(**persen):
            return {"aturan": [{"envelope_id": str(self.env[n.replace("_", " ").capitalize()]), "persen": p}
                               for n, p in persen.items()]}
        r = await self.p("PUT", "/alokasi", status=422, json=aturan(bahan=60, operasional=39))
        self.assertEqual(self.kode(r), "alokasi_bukan_100")
        for eid in (self.pribadi, self.env_lain, self.env_rumah):
            r = await self.p("PUT", "/alokasi", status=422,
                             json={"aturan": [{"envelope_id": str(eid), "persen": 100}]})
            self.assertEqual(self.kode(r), "amplop_tidak_ada")
        await self.p("PUT", "/alokasi", status=422, json={"aturan": [{"envelope_id": "bukan-uuid", "persen": 100}]})
        await self.p("PUT", "/alokasi", status=422, json={"aturan": "semua"})

        out = await self.atur_a3()
        self.assertTrue(out["siap"])
        self.assertEqual([x["nama"] for x in out["aturan"]], ["Bahan", "Operasional", "Prive", "Laba ditahan", "Pajak"])
        # Ganti: buang Pajak, ubah persen; simpan ulang tidak bentrok dengan indeks unik baris hidup.
        out = (await self.p("PUT", "/alokasi", status=200, json=aturan(bahan=50, operasional=30, prive=20))).json()
        self.assertEqual([(x["nama"], x["persen"]) for x in out["aturan"]],
                         [("Bahan", "50.00"), ("Operasional", "30.00"), ("Prive", "20.00")])
        out = await self.atur_a3()
        self.assertEqual(len(out["aturan"]), 5)
        tampil = (await self.p("GET", "/alokasi", status=200)).json()
        self.assertEqual((tampil["siap"], tampil["saran"]), (True, []))

    async def test_alokasi_tidak_siap_bila_amplop_diarsipkan(self):
        await self.pasang_aktif()
        await self.atur_a3()
        async with self.Session() as db:
            (await db.get(Envelope, self.env["Pajak"])).is_active = False
            await db.commit()
        out = (await self.p("GET", "/alokasi", status=200)).json()
        self.assertFalse(out["siap"])
        r = await self.p("POST", "/penjualan", status=422, json={"jumlah": 100000})
        self.assertEqual(self.kode(r), "alokasi_belum_diatur")

    # ── 5. penjualan ──
    async def test_penjualan_satu_commit_dan_persis(self):
        await self.pasang_aktif()
        r = await self.p("POST", "/penjualan", status=422, json={"jumlah": 100000})
        self.assertEqual(self.kode(r), "alokasi_belum_diatur")
        await self.atur_a3()
        pelanggan = await self.kontak("PT Arunika Data", "pelanggan")

        pra = (await self.p("POST", "/penjualan/pratinjau", status=200, json={"jumlah": "1000001"})).json()
        self.assertEqual([(b["nama"], b["jumlah"]) for b in pra["pembagian"]],
                         [("Bahan", "450001.00"), ("Operasional", "300000.00"), ("Prive", "150000.00"),
                          ("Laba ditahan", "90000.00"), ("Pajak", "10000.00")])
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 1)    # pratinjau tidak menulis

        kemarin = (self.today - timedelta(days=1)).isoformat()
        r = await self.p("POST", "/penjualan", status=201, json={
            "jumlah": "1000001", "kontak_id": pelanggan["id"], "tanggal": kemarin})
        out = r.json()
        self.assertEqual((out["jenis"], out["keterangan"], out["tanggal"], out["kontak"]["nama"]),
                         ("penjualan", "Penjualan · PT Arunika Data", kemarin, "PT Arunika Data"))
        self.assertEqual(out["pembagian"], pra["pembagian"])
        async with self.Session() as db:
            inc = await db.get(Income, __import__("uuid").UUID(out["income_id"]))
            self.assertEqual((inc.amount, inc.kind, inc.income_date.isoformat(), inc.household_id, inc.user_id),
                             (D("1000001"), "pemasukan", kemarin, self.usaha, self.pemilik.id))
            alok = {a.envelope_id: a.amount for a in (await db.execute(
                select(Allocation).where(Allocation.income_id == inc.id))).scalars()}
            meta = (await db.execute(select(BukuUsahaIncomeMeta))).scalar_one()
            tabungan = (await db.execute(select(func.count()).select_from(Envelope)
                                         .where(Envelope.name == "Tabungan"))).scalar()
            audit = (await db.execute(select(PluginAuditLog).where(PluginAuditLog.action == "inti:pemasukan"))).scalars().all()
        self.assertEqual(sum(alok.values()), D("1000001"))
        self.assertEqual(alok[self.env["Bahan"]], D("450001"))
        self.assertEqual(len(alok), 5)
        self.assertEqual(tabungan, 0)                   # tidak ada sisa ke Tabungan
        self.assertEqual((meta.income_id, meta.jenis, str(meta.kontak_id), meta.household_id, meta.created_by),
                         (inc.id, "penjualan", pelanggan["id"], self.usaha, self.pemilik.id))
        self.assertEqual(len(audit), 1)
        self.assertNotIn("1000001", json.dumps(audit[0].detail))       # tanpa nominal

    async def test_jenis_lain_satu_amplop(self):
        await self.pasang_aktif()
        out = (await self.p("POST", "/penjualan", status=201, json={"jumlah": 5000000, "jenis": "modal"})).json()
        self.assertEqual([(b["nama"], b["jumlah"]) for b in out["pembagian"]], [("Laba ditahan", "5000000")])
        self.assertEqual(out["keterangan"], "Modal pemilik")
        out = (await self.p("POST", "/penjualan", status=201, json={
            "jumlah": 2000000, "jenis": "pinjaman", "envelope_id": str(self.env["Bahan"]),
            "keterangan": "KUR BRI"})).json()
        self.assertEqual(([b["nama"] for b in out["pembagian"]], out["keterangan"]), (["Bahan"], "KUR BRI"))
        async with self.Session() as db:
            jenis = sorted((await db.execute(select(BukuUsahaIncomeMeta.jenis))).scalars())
        self.assertEqual(jenis, ["modal", "pinjaman"])
        # Penjualan tidak bisa diarahkan ke satu amplop; jenis lain ke amplop pribadi/ruang lain ditolak.
        await self.atur_a3()
        await self.p("POST", "/penjualan", status=422, json={"jumlah": 1, "envelope_id": str(self.env["Bahan"])})
        for eid in (self.pribadi, self.env_lain):
            r = await self.p("POST", "/penjualan", status=422, json={"jumlah": 1, "jenis": "lain",
                                                                      "envelope_id": str(eid)})
            self.assertEqual(self.kode(r), "amplop_tidak_ada")

    async def test_validasi_penjualan(self):
        await self.pasang_aktif()
        await self.atur_a3()
        pemasok = await self.kontak("UD Sumber Unggas", "pemasok")
        pelanggan = await self.kontak("Bu Sari", "pelanggan")
        besok = (self.today + timedelta(days=2)).isoformat()
        lama = (self.today - timedelta(days=400)).isoformat()
        for body, kode in (({"jumlah": 0}, "nilai_tidak_sah"), ({"jumlah": "abc"}, "nilai_tidak_sah"),
                           ({"jumlah": 1, "jenis": "hibah"}, "jenis_tidak_dikenal"),
                           ({"jumlah": 1, "kontak_id": pemasok["id"]}, "kontak_tidak_ada"),
                           ({"jumlah": 1, "kontak_id": "x"}, "kontak_tidak_ada"),
                           ({"jumlah": 1, "jenis": "modal", "kontak_id": pelanggan["id"]}, "nilai_tidak_sah"),
                           ({"jumlah": 1, "tanggal": besok}, "nilai_tidak_sah"),
                           ({"jumlah": 1, "tanggal": lama}, "nilai_tidak_sah"),
                           ({"jumlah": 1, "tanggal": "kemarin"}, "nilai_tidak_sah"),
                           ({"jumlah": 1, "income_id": "x"}, "nilai_tidak_sah")):
            r = await self.p("POST", "/penjualan", json=body)
            self.assertEqual((r.status_code, self.kode(r)), (422, kode), body)
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 1)
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 0)

    async def test_gagal_di_tengah_tidak_meninggalkan_apa_pun(self):
        await self.pasang_aktif()
        await self.atur_a3()
        asli = data_plugin.tambah

        async def gagal(k, nama, nilai):
            if nama == "income_meta":
                raise RuntimeError("disk penuh")
            return await asli(k, nama, nilai)
        with patch.object(data_plugin, "tambah", gagal):
            r = await self.p("POST", "/penjualan", json={"jumlah": 100000})
        self.assertEqual((r.status_code, self.kode(r)), (500, "plugin_gagal"))
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 1)    # hanya modal awal
        self.assertEqual(await self.hitung(Allocation, Allocation.envelope_id == self.env["Prive"]), 0)

    async def test_isolasi_dan_peran(self):
        await self.pasang_aktif()
        await self.atur_a3()
        self.current = self.karyawan
        r = await self.p("POST", "/penjualan", json={"jumlah": 100000})
        self.assertEqual(r.status_code, 403, r.text)
        r = await self.p("PUT", "/alokasi", json={"aturan": []})
        self.assertEqual(r.status_code, 403, r.text)
        self.current = self.admin
        await self.p("POST", "/penjualan", status=201, json={"jumlah": 100000})
        self.current = self.pemilik
        # Ruang usaha kedua tanpa Buku Usaha / ruang keluarga: plugin tidak aktif.
        for hid in (self.usaha2, self.rumah):
            r = await self.p("POST", "/penjualan", hid=hid, json={"jumlah": 1})
            self.assertEqual(r.status_code, 404, r.text)
        # Ruang kedua dengan Buku Usaha: aturan ruang pertama tidak terbawa, amplopnya tidak bisa dipakai.
        await self.pasang_aktif(self.usaha2)
        out = (await self.p("GET", "/alokasi", hid=self.usaha2, status=200)).json()
        self.assertEqual((out["aturan"], out["saran"]), ([], []))
        r = await self.p("PUT", "/alokasi", hid=self.usaha2, status=422, json={"aturan": [
            {"envelope_id": str(self.env["Bahan"]), "persen": 100}]})
        self.assertEqual(self.kode(r), "amplop_tidak_ada")

    # ── 6. ctx.catat_pemasukan langsung ──
    async def _ctx(self, db, *, boleh_tulis=True, izin=("envelopes:read", "incomes:write"), user=None, peran="owner",
                   jenis="rute", hid=None):
        m = self.reg.get("buku_usaha")
        hid = hid or self.usaha
        inst = PluginInstallation(household_id=hid, plugin_id="buku_usaha", status="active",
                                  granted_permissions=list(izin))
        ruang_obj = await db.get(Household, hid)
        d = Pendaftaran(jenis, "uji", lambda *a: None, tuple(izin))
        return titik.konteks(db, m, inst, ruang_obj, d, viewer=user or self.pemilik, peran=peran, sumber="uji",
                             boleh_tulis=boleh_tulis)

    async def test_ctx_catat_pemasukan_dijaga(self):
        bagian = [(self.env["Bahan"], D("60")), (self.env["Pajak"], D("40"))]
        async with self.Session() as db:
            for kw, alasan in (({"boleh_tulis": False}, "hanya_baca"), ({"izin": ("envelopes:read",)}, "tanpa_izin"),
                               ({"jenis": "kartu"}, "tanpa_izin"),
                               ({"user": self.karyawan, "peran": "member"}, "khusus_admin")):
                ctx = await self._ctx(db, **kw)
                with self.assertRaises(IzinDitolak, msg=kw) as cm:
                    await ctx.catat_pemasukan(jumlah=D("100"), keterangan="x", pembagian=bagian)
                self.assertEqual(cm.exception.alasan, alasan, kw)
            for pembagian, jumlah in (([(self.env["Bahan"], D("60"))], D("100")),             # kurang
                                      ([(self.env_lain, D("100"))], D("100")),                # ruang lain
                                      ([(self.pribadi, D("100"))], D("100")),                 # pribadi viewer: boleh
                                      ([(self.env["Bahan"], D("100")), (self.env["Bahan"], D("0"))], D("100")),
                                      ([(self.env["Bahan"], 100.0)], D("100")),               # float
                                      ([], D("100"))):
                ctx = await self._ctx(db)
                if pembagian and pembagian[0][0] == self.pribadi:
                    out = await ctx.catat_pemasukan(jumlah=jumlah, keterangan="x", pembagian=pembagian)
                    self.assertEqual(out["jumlah"], D("100"))
                    continue
                with self.assertRaises(NilaiTidakSah, msg=pembagian):
                    await ctx.catat_pemasukan(jumlah=jumlah, keterangan="x", pembagian=pembagian)
            ctx = await self._ctx(db)
            with self.assertRaises(NilaiTidakSah):
                await ctx.catat_pemasukan(jumlah=D("100"), keterangan=" ", pembagian=bagian)
            ctx = await self._ctx(db, user=self.admin, peran="admin")
            out = await ctx.catat_pemasukan(jumlah=D("100"), keterangan="x", pembagian=bagian,
                                            tanggal=self.today)
            self.assertEqual([b["nama"] for b in out["pembagian"]], ["Bahan", "Pajak"])
            await db.rollback()
        # Ruang keluarga: amplop ruang usaha tidak terlihat dari konteks ruang keluarga.
        async with self.Session() as db:
            ctx = await self._ctx(db, hid=self.rumah)
            with self.assertRaises(NilaiTidakSah):
                await ctx.catat_pemasukan(jumlah=D("100"), keterangan="x", pembagian=bagian)

    async def test_konteks_tertutup_sesudah_panggilan(self):
        async with self.Session() as db:
            ctx = await self._ctx(db)
            keadaan.tutup(ctx)
            with self.assertRaises(keadaan.KonteksTidakSah):
                await ctx.catat_pemasukan(jumlah=D("1"), keterangan="x", pembagian=[(self.env["Bahan"], D("1"))])

    # ── 7. pemasok + akun di form pengeluaran ──
    async def catat(self, tambahan, user=None, envelope=None, **kw):
        self.current = user or self.pemilik
        body = {"envelope_id": str(envelope or self.env["Bahan"]), "amount": "25000", "description": "ayam potong",
                **kw}
        if tambahan is not None:
            body["tambahan"] = tambahan
        return await self.client.post("/transactions/", json=body)

    async def test_field_pengeluaran_tersimpan_bersama_transaksi(self):
        await self.pasang_aktif()
        kontrib = (await self.client.get("/plugins/contributions", headers=self.hdr())).json()
        ff = {f["key"]: f for f in kontrib["form_fields"]}
        self.assertEqual(ff["akun"]["options"][:2], ["Bahan baku", "Gaji"])
        self.assertNotIn("options", ff["pemasok"])
        self.assertEqual([a["key"] for a in kontrib["quick_actions"]], ["buku_usaha.penjualan"])

        pemasok = await self.kontak("UD Sumber Unggas", "pemasok")
        r = await self.catat({"buku_usaha": {"pemasok": pemasok["id"], "akun": "Bahan baku"}})
        self.assertEqual(r.status_code, 201, r.text)
        async with self.Session() as db:
            meta = (await db.execute(select(BukuUsahaTxnMeta))).scalar_one()
        self.assertEqual((str(meta.transaction_id), str(meta.kontak_id), meta.akun, meta.household_id),
                         (r.json()["id"], pemasok["id"], "Bahan baku", self.usaha))
        # Hanya akun; semua kosong = tanpa meta.
        self.assertEqual((await self.catat({"buku_usaha": {"akun": "Sewa"}})).status_code, 201)
        self.assertEqual((await self.catat({"buku_usaha": {"akun": None, "pemasok": None}})).status_code, 201)
        self.assertEqual((await self.catat(None)).status_code, 201)
        self.assertEqual(await self.hitung(BukuUsahaTxnMeta), 2)

    async def test_field_pengeluaran_salah_tanpa_transaksi(self):
        await self.pasang_aktif()
        pelanggan = await self.kontak("Bu Sari", "pelanggan")
        sebelum = await self.hitung(Transaction)
        for tambahan in ({"buku_usaha": {"akun": "Hiburan"}}, {"buku_usaha": {"pemasok": pelanggan["id"]}},
                         {"buku_usaha": {"pemasok": "bukan-uuid"}}, {"buku_usaha": {"proyek": "x"}},
                         {"lain": {"akun": "Sewa"}}, {"buku_usaha": "Sewa"}, {"buku_usaha": {"akun": 5}}):
            r = await self.catat(tambahan)
            self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"), tambahan)
        self.assertEqual(await self.hitung(Transaction), sebelum)

    async def test_field_karyawan_dan_ruang_keluarga_ditolak(self):
        await self.pasang_aktif()
        async with self.Session() as db:
            from app.models.models import RuangBatasan
            db.add(RuangBatasan(household_id=self.usaha, user_id=self.karyawan.id, jenis_catatan=["pengeluaran"],
                                amplop_ids=[str(self.env["Bahan"])]))
            await db.commit()
        sebelum = await self.hitung(Transaction)
        r = await self.catat({"buku_usaha": {"akun": "Sewa"}}, user=self.karyawan)
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))
        r = await self.catat({"buku_usaha": {"akun": "Sewa"}}, envelope=self.env_rumah)
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))
        self.assertEqual(await self.hitung(Transaction), sebelum)
        # Plugin dijeda: field tidak tersedia lagi.
        self.current = self.pemilik
        await self.aksi("jeda")
        r = await self.catat({"buku_usaha": {"akun": "Sewa"}})
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))

    async def test_gagal_simpan_field_membatalkan_transaksi(self):
        await self.pasang_aktif()
        sebelum = await self.hitung(Transaction)
        asli = data_plugin.tambah

        async def gagal(k, nama, nilai):
            if nama == "txn_meta":
                raise RuntimeError("bug plugin")
            return await asli(k, nama, nilai)
        with patch.object(data_plugin, "tambah", gagal):
            r = await self.catat({"buku_usaha": {"akun": "Sewa"}}, client_ref="ref-gagal-1")
        self.assertEqual((r.status_code, self.kode(r)), (500, "plugin_gagal"))
        self.assertEqual(await self.hitung(Transaction), sebelum)
        # Kunci idempotensi dilepas: kirim ulang dengan ref yang sama berhasil sekali.
        r = await self.catat({"buku_usaha": {"akun": "Sewa"}}, client_ref="ref-gagal-1")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(await self.hitung(BukuUsahaTxnMeta), 1)

    async def test_simpan_field_tidak_menulis_untuk_ruang_lain(self):
        """`txn_meta` selalu ruang konteks (ruang amplop transaksinya), walau plugin aktif di ruang lain user itu."""
        await self.pasang_aktif()
        await self.pasang_aktif(self.usaha2)
        async with self.Session() as db:
            inc = Income(household_id=self.usaha2, user_id=self.pemilik.id, amount=D("100000"), description="m",
                         income_date=self.today)
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=self.env_lain, amount=D("100000")))
            await db.commit()
        r = await self.catat({"buku_usaha": {"akun": "Sewa"}}, envelope=self.env_lain)
        self.assertEqual(r.status_code, 201, r.text)
        async with self.Session() as db:
            meta = (await db.execute(select(BukuUsahaTxnMeta))).scalar_one()
        self.assertEqual(meta.household_id, self.usaha2)
        # Pemasok ruang pertama tidak bisa dipakai di ruang kedua.
        pemasok = await self.kontak("UD Sumber", "pemasok")
        r = await self.catat({"buku_usaha": {"pemasok": pemasok["id"]}}, envelope=self.env_lain)
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))

    async def test_incomes_route_tetap_sama(self):
        """Jalur `/incomes` inti tidak berubah: commit sendiri, sisa ke Tabungan, tanpa meta."""
        self.current = self.pemilik
        r = await self.client.post("/incomes/", headers=self.hdr(self.rumah),
                                   json={"amount": "1000", "source": "gaji", "allocations": [
                                       {"envelope_id": str(self.env_rumah), "amount": "600"}]})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual([a["envelope"] for a in r.json()["allocations"]], ["Makan", "Tabungan"])
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 0)

    # ── review keamanan PR #201 ──
    async def test_review_t1_meta_tidak_kena_batas_baris_ruang(self):
        """T1: tabel pendamping 1:1 (income_meta, txn_meta) tidak menolak catatan sesudah batas per ruang."""
        self.assertTrue(data_plugin.pendamping_inti(BukuUsahaTxnMeta.__table__))
        self.assertTrue(data_plugin.pendamping_inti(BukuUsahaIncomeMeta.__table__))
        from app.models.models import BukuUsahaAlokasi, BukuUsahaKontak
        self.assertFalse(data_plugin.pendamping_inti(BukuUsahaKontak.__table__))
        self.assertFalse(data_plugin.pendamping_inti(BukuUsahaAlokasi.__table__))
        await self.pasang_aktif()
        await self.atur_a3()
        with patch.object(data_plugin, "BATAS_BARIS_RUANG", 2):
            for _ in range(3):
                await self.p("POST", "/penjualan", status=201, json={"jumlah": 1000})
                self.assertEqual((await self.catat({"buku_usaha": {"akun": "Sewa"}})).status_code, 201)
            self.current = self.pemilik
            await self.kontak("A", "pelanggan")
            await self.kontak("B", "pelanggan")
            r = await self.p("POST", "/kontak", json={"nama": "C", "peran": "pelanggan"})
            self.assertEqual(r.status_code, 422, r.text)                   # kontak tetap dibatasi
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 3)
        self.assertEqual(await self.hitung(BukuUsahaTxnMeta), 3)

    async def test_review_t2_angka_raksasa_422(self):
        await self.pasang_aktif()
        await self.atur_a3()
        for metode, path, body in (("POST", "/penjualan", {"jumlah": "1e30"}),
                                   ("POST", "/penjualan", {"jumlah": 1e300}),
                                   ("POST", "/penjualan/pratinjau", {"jumlah": "1e26"}),
                                   ("PUT", "/alokasi", {"aturan": [{"envelope_id": str(self.env["Bahan"]),
                                                                    "persen": "1e30"}]})):
            r = await self.p(metode, path, json=body)
            self.assertEqual((r.status_code, self.kode(r)), (422, "nilai_tidak_sah"), body)
        async with self.Session() as db:
            ctx = await self._ctx(db)
            with self.assertRaises(NilaiTidakSah):
                await ctx.catat_pemasukan(jumlah=D("1e30"), keterangan="x",
                                          pembagian=[(self.env["Bahan"], D("1e30"))])
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 1)

    async def test_review_t3_tanpa_isian_untuk_pengeluaran_pribadi(self):
        await self.pasang_aktif()
        async with self.Session() as db:
            inc = Income(household_id=self.usaha, user_id=self.pemilik.id, amount=D("50000"), description="m",
                         income_date=self.today)
            db.add(inc)
            await db.flush()
            db.add(Allocation(income_id=inc.id, envelope_id=self.pribadi, amount=D("50000")))
            await db.commit()
        sebelum = await self.hitung(Transaction)
        r = await self.catat({"buku_usaha": {"akun": "Lain-lain"}}, envelope=self.pribadi)
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))
        r = await self.catat({"buku_usaha": {"akun": "Lain-lain"}}, is_private=True)
        self.assertEqual((r.status_code, self.kode(r)), (422, "field_tidak_sah"))
        self.assertEqual(await self.hitung(Transaction), sebelum)
        self.assertEqual(await self.hitung(BukuUsahaTxnMeta), 0)
        # Tanpa isian, pengeluaran pribadi tetap seperti biasa.
        self.assertEqual((await self.catat(None, envelope=self.pribadi)).status_code, 201)

    async def test_review_t5_penjualan_idempoten(self):
        await self.pasang_aktif()
        await self.atur_a3()
        pelanggan = await self.kontak("Bu Sari", "pelanggan")
        body = {"jumlah": 250000, "kontak_id": pelanggan["id"], "client_ref": "ref-u2-1"}
        r1 = await self.p("POST", "/penjualan", status=201, json=body)
        self.assertFalse(r1.json()["ulang"])
        r2 = await self.p("POST", "/penjualan", status=200, json=body)
        out = r2.json()
        self.assertTrue(out["ulang"])
        self.assertEqual((out["income_id"], out["jenis"], out["kontak"]["nama"], out["jumlah"]),
                         (r1.json()["income_id"], "penjualan", "Bu Sari", "250000.00"))
        self.assertEqual(sum(D(b["jumlah"]) for b in out["pembagian"]), D("250000"))
        self.assertEqual(await self.hitung(Income, Income.household_id == self.usaha), 2)   # modal awal + satu
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 1)
        async with self.Session() as db:
            self.assertEqual(len((await db.execute(select(PluginAuditLog).where(
                PluginAuditLog.action == "inti:pemasukan"))).scalars().all()), 1)
        # Ref lain = catatan baru; ref tidak sah ditolak.
        await self.p("POST", "/penjualan", status=201, json={**body, "client_ref": "ref-u2-2"})
        for salah in ("", "x" * 65, "ada spasi", 5):
            r = await self.p("POST", "/penjualan", json={**body, "client_ref": salah})
            self.assertEqual((r.status_code, self.kode(r)), (422, "nilai_tidak_sah"), salah)
        # Ref yang sama di ruang lain bukan kiriman ulang.
        await self.pasang_aktif(self.usaha2)
        async with self.Session() as db:
            bahan2 = (await db.execute(select(Envelope).where(Envelope.id == self.env_lain))).scalar_one()
        await self.p("PUT", "/alokasi", hid=self.usaha2, status=200,
                     json={"aturan": [{"envelope_id": str(bahan2.id), "persen": 100}]})
        r = await self.p("POST", "/penjualan", hid=self.usaha2, status=201,
                         json={"jumlah": 1000, "client_ref": "ref-u2-1"})
        self.assertFalse(r.json()["ulang"])

    async def test_review_t5_gagal_melepas_ref_dan_sedang_diproses(self):
        await self.pasang_aktif()
        await self.atur_a3()
        asli = data_plugin.tambah

        async def gagal(k, nama, nilai):
            if nama == "income_meta":
                raise RuntimeError("disk penuh")
            return await asli(k, nama, nilai)
        body = {"jumlah": 100000, "client_ref": "ref-gagal"}
        with patch.object(data_plugin, "tambah", gagal):
            r = await self.p("POST", "/penjualan", json=body)
        self.assertEqual(r.status_code, 500, r.text)
        r = await self.p("POST", "/penjualan", status=201, json=body)       # ref dilepas: kirim ulang tercatat sekali
        self.assertFalse(r.json()["ulang"])
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 1)
        # Kiriman yang masih diproses (kunci "pending") → 409, tanpa menulis.
        from app.services import idempotency
        await idempotency.reserve(self.pemilik.id, "ref-proses", scope=f"pluginref:buku_usaha:{self.usaha}")
        r = await self.p("POST", "/penjualan", json={**body, "client_ref": "ref-proses"})
        self.assertEqual((r.status_code, self.kode(r)), (409, "sedang_diproses"))
        self.assertEqual(await self.hitung(BukuUsahaIncomeMeta), 1)

    async def test_review_t5_ref_pemasukan_terhapus_dicatat_lagi(self):
        await self.pasang_aktif()
        await self.atur_a3()
        body = {"jumlah": 5000, "client_ref": "ref-hapus"}
        iid = (await self.p("POST", "/penjualan", status=201, json=body)).json()["income_id"]
        async with self.Session() as db:
            import uuid as _u
            from sqlalchemy import delete
            await db.execute(delete(Allocation).where(Allocation.income_id == _u.UUID(iid)))
            await db.execute(delete(Income).where(Income.id == _u.UUID(iid)))      # meta ikut (CASCADE)
            await db.commit()
        r = await self.p("POST", "/penjualan", status=201, json=body)
        self.assertNotEqual(r.json()["income_id"], iid)


if __name__ == "__main__":
    unittest.main()
