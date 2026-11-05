"""Plugin U1 — kerangka Buku Usaha dan Kontak; Gerbang H (03-workflow.md baris U1; 04-kontrak-api.md §5, §6;
AGENTS.md "Plugin dan ruang" aturan 1, 3, 4, 5, 8, 9; ADR-P1, P7, P11, P15).

1. Aturan tabel plugin (`host/data.py aturan_tabel`): semua tabel `p_*` di model memenuhinya; pelanggaran terdeteksi;
   manifest dengan entitas tanpa model ditolak validator.
2. Manifest dan SDK: `routes`, `@plugin.rute`, pencocokan kode ↔ manifest, izin rute hanya baca; manifest
   `buku_usaha` di repo sah.
3. `ctx.data()`: tabel sendiri saja; tulis hanya dari rute non-GET (kartu/job → `hanya_baca`); karyawan
   `khusus_admin`; nilai dan rujukan diperiksa; selalu ruang konteks.
4. Gerbang H lewat HTTP (SQLite): pasang (wizard → terpasang, belum ada kontribusi), lanjut → aktif (nav, rute),
   jeda (rute 404, data tetap), lanjut (data kembali), copot (arsip, ekspor tetap), pulihkan (data kembali), saklar
   darurat (rute 404, ekspor tetap), pembersih arsip (baris dan data `p_*` hilang) — semua tanpa sisa.
5. Isolasi: kontak ruang lain tidak terbaca/terubah/terhapus walau tahu ID; ruang orang lain 403; karyawan 403;
   ruang keluarga tanpa plugin; audit tulis tercatat.
6. Kontak: validasi (422), peran, kembar (409), ekspor JSON/CSV (anti formula-injection), hapus akun (data ruang
   tunggal hilang; ruang bersama: pencatat dikosongkan).

Run: python -m unittest app.tests.test_plugin_u1 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import csv
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import sqlalchemy as sa

from app.core.database import Base
from app.plugins.host import data as data_plugin
from app.plugins.host import kode as kode_mod
from app.plugins.host import siklus
from app.plugins.host.manifest import IZIN, Manifest
from app.plugins.host.registry import ManifestTidakSah, muat, pakai_registry
from app.plugins.sdk import Plugin

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
FOLDER_BU = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "buku_usaha"

MF = {
    "id": "uji", "name": "Uji", "version": "1.0.0", "publisher": "Jatahku", "description": "Plugin uji U1",
    "engines": {"plugin_api": ">=1.2 <2.0"}, "space_types": ["usaha"], "permissions": ["envelopes:read"],
    "entities": [], "contributes": {"routes": [{"method": "GET", "path": "/kontak"},
                                               {"method": "POST", "path": "/kontak/{id}"}]},
}


def mf(**ubah) -> dict:
    d = copy.deepcopy(MF)
    for k, v in ubah.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


# ── 1. aturan tabel ──────────────────────────────────────────────────────
class TabelPluginAturanTests(unittest.TestCase):
    def test_semua_tabel_p_memenuhi_aturan(self):
        import app.models.models  # noqa: F401
        tabel = [t for t in Base.metadata.sorted_tables if t.name.startswith("p_")]
        self.assertEqual(sorted(t.name for t in tabel), [
            "p_buku_usaha_alokasi", "p_buku_usaha_income_meta", "p_buku_usaha_kontak", "p_buku_usaha_txn_meta"])
        for t in tabel:
            self.assertEqual(data_plugin.aturan_tabel(t, "buku_usaha"), [], t.name)

    def test_pelanggaran_terdeteksi(self):
        md = sa.MetaData()
        sa.Table("households", md, sa.Column("id", sa.Uuid(), primary_key=True))
        sa.Table("users", md, sa.Column("id", sa.Uuid(), primary_key=True))
        sa.Table("goals", md, sa.Column("id", sa.Uuid(), primary_key=True))
        salah = sa.Table(
            "p_lain_x", md,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id")),           # tanpa CASCADE
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id")),                      # FK di luar inti
            sa.Column("jenis", sa.Enum("a", "b", name="jenis_x")),                           # SAEnum
            sa.Index("ix_salah", "jenis"),                                                   # tidak diawali household_id
        )
        galat = "\n".join(data_plugin.aturan_tabel(salah, "uji"))
        for potongan in ("berawalan p_uji_", "kolom wajib 'created_at'", "kolom wajib 'deleted_at'",
                         "household_id harus FK households ON DELETE CASCADE", "created_by harus FK users ON DELETE SET NULL",
                         "FK ke 'goals' tidak boleh", "enum memakai String", "indeks ix_salah harus diawali household_id"):
            self.assertIn(potongan, galat)

    def test_entitas_tanpa_model_ditolak_validator(self):
        m = Manifest.model_validate(mf(entities=["p_uji_catatan"]))
        self.assertIn("entitas 'p_uji_catatan' tidak ada di app/models", "\n".join(data_plugin.periksa_entitas(m)))
        with tempfile.TemporaryDirectory() as d:
            sub = pathlib.Path(d) / "uji"
            sub.mkdir()
            (sub / "manifest.json").write_text(json.dumps(mf(entities=["p_uji_catatan"], contributes={})))
            with self.assertRaises(ManifestTidakSah) as cm:
                muat(pathlib.Path(d), ketat=True)
            self.assertIn("p_uji_catatan", "\n".join(cm.exception.galat))
        # Entitas milik plugin lain (ada modelnya) juga ditolak: awalan p_<id>_ (manifest).
        with self.assertRaises(Exception):
            Manifest.model_validate(mf(entities=["p_buku_usaha_kontak"]))


# ── 2. manifest dan SDK ──────────────────────────────────────────────────
class RuteManifestTests(unittest.TestCase):
    def test_bentuk_rute(self):
        m = Manifest.model_validate(mf())
        self.assertEqual([r.key for r in m.contributes.routes], ["GET /kontak", "POST /kontak/{id}"])
        for salah in ({"method": "HEAD", "path": "/x"}, {"method": "GET", "path": "x"}, {"method": "GET", "path": "/X"},
                      {"method": "GET", "path": "/a/{1x}"}, {"method": "GET", "path": "/a//b"}):
            with self.assertRaises(Exception, msg=salah):
                Manifest.model_validate(mf(contributes={"routes": [salah]}))
        with self.assertRaises(Exception):
            Manifest.model_validate(mf(contributes={"routes": [{"method": "GET", "path": "/a"}] * 2}))

    def test_cocokkan_rute_dengan_kode(self):
        m = Manifest.model_validate(mf())
        p = Plugin("uji")

        @p.rute("GET", "/kontak")
        async def a(ctx, req):
            return []

        galat = "\n".join(kode_mod.cocokkan(m, p))
        self.assertIn("routes 'POST /kontak/{id}' di manifest tidak punya fungsi", galat)

        @p.rute("POST", "/kontak/{id}")
        async def b(ctx, req):
            return {}

        @p.rute("DELETE", "/lain")
        async def c(ctx, req):
            return {}

        galat = "\n".join(kode_mod.cocokkan(m, p))
        self.assertIn("rute 'DELETE /lain' didaftarkan di kode tetapi tidak ada di manifest", galat)
        with self.assertRaises(ValueError):
            p.rute("HEAD", "/x")

    def test_izin_rute_hanya_baca(self):
        self.assertEqual(kode_mod.IZIN_PER_JENIS["rute"], kode_mod.IZIN_BACA)
        m = Manifest.model_validate(mf(permissions=["envelopes:read", "envelopes:write"]))
        p = Plugin("uji")

        @p.rute("GET", "/kontak", izin=["envelopes:write"])
        async def a(ctx, req):
            return []

        @p.rute("POST", "/kontak/{id}")
        async def b(ctx, req):
            return {}

        self.assertIn("tidak boleh untuk rute", "\n".join(kode_mod.cocokkan(m, p)))

    def test_manifest_buku_usaha_sah(self):
        reg = muat(FOLDER_BU.parent, ketat=True)
        m = reg.get("buku_usaha")
        self.assertIsNotNone(m)
        self.assertTrue(set(m.permissions) <= set(IZIN))
        self.assertEqual(m.space_types, ["usaha"])
        self.assertTrue(m.contributes.setup)
        self.assertEqual(sorted(m.entities), ["p_buku_usaha_alokasi", "p_buku_usaha_income_meta",
                                              "p_buku_usaha_kontak", "p_buku_usaha_txn_meta"])
        self.assertEqual(m.data_lifecycle.export, ["csv", "json"])
        self.assertIsNotNone(reg.kode_plugin("buku_usaha"))
        self.assertEqual(kode_mod.periksa_impor(FOLDER_BU, m), [])
        # Belum ada kartu, cek, saran, bot, job, kamus: titik ekstensi lain tidak bekerja karena plugin ini (U4–U6).
        for jenis in ("kartu", "cek", "aturan_advisor", "perintah_bot", "job", "field_form"):
            self.assertFalse(reg.punya(jenis), jenis)
        self.assertTrue(reg.punya("rute"))

    def test_cocok_pola(self):
        from app.plugins.host.titik import _cocok_pola
        self.assertEqual(_cocok_pola("/kontak/{id}", "/kontak/abc"), {"id": "abc"})
        self.assertEqual(_cocok_pola("/kontak", "/kontak/"), {})
        self.assertIsNone(_cocok_pola("/kontak/{id}", "/kontak"))
        self.assertIsNone(_cocok_pola("/kontak", "/kontakx"))
        self.assertIsNone(_cocok_pola("/kontak/{id}", "/kontak/a/b"))

    def test_json_aman(self):
        from uuid import UUID
        from app.plugins.host.titik import json_aman
        u = UUID("12345678-1234-5678-1234-567812345678")
        self.assertEqual(json_aman({"a": Decimal("12.50"), "b": [u], "c": None, "d": True, "e": 3}),
                         {"a": "12.50", "b": [str(u)], "c": None, "d": True, "e": 3})
        with self.assertRaises(TypeError):
            json_aman({"a": 1.5})
        with self.assertRaises(TypeError):
            json_aman(object())


# ── 3–6. SQLite ──────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import event, select

    from app.api.routes import plugins as plugins_route
    from app.core.database import get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        AppSetting, BukuUsahaKontak, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType,
        PluginAuditLog, PluginInstallation, User,
    )
    from app.plugins.host import keadaan, titik
    from app.plugins.host.keadaan import pakai_sesi
    from app.plugins.sdk import IzinDitolak, NilaiTidakSah
    from app.plugins.sdk.plugin import Pendaftaran
    from app.services import ruang


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class U1DbTests(unittest.IsolatedAsyncioTestCase):
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

        async with self.Session() as db:
            pemilik, admin, karyawan, orang = (User(name=n, plan="pro", timezone="Asia/Jakarta")
                                               for n in ("Pemilik", "Admin", "Karyawan", "Orang"))
            usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            usaha2 = Household(name="Toko Kedua", type=HouseholdType.USAHA)
            rumah = Household(name="Rumah", type=HouseholdType.RUMAH_TANGGA)
            asing = Household(name="Usaha orang", type=HouseholdType.USAHA)
            db.add_all([pemilik, admin, karyawan, orang, usaha, usaha2, rumah, asing])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=pemilik.id, household_id=usaha.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=admin.id, household_id=usaha.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=karyawan.id, household_id=usaha.id, role=HouseholdRole.member),
                HouseholdMember(user_id=pemilik.id, household_id=usaha2.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=pemilik.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=orang.id, household_id=asing.id, role=HouseholdRole.owner),
                AppSetting(key="plugin_buku_usaha_users", value="*"),
                AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"),
                Envelope(household_id=usaha.id, name="Bahan", emoji="🥬", budget_amount=0),
                Envelope(household_id=usaha.id, name="Pribadi pemilik", emoji="🔒", budget_amount=0, owner_id=pemilik.id),
            ])
            await db.commit()
        self.pemilik, self.admin, self.karyawan, self.orang = pemilik, admin, karyawan, orang
        self.usaha, self.usaha2, self.rumah, self.asing = usaha.id, usaha2.id, rumah.id, asing.id

        self.current = pemilik
        app = FastAPI()
        ruang.install(app)
        app.include_router(plugins_route.router, prefix="/plugins")
        app.include_router(plugins_route.ruang_router, prefix="/ruang")
        app.include_router(plugins_route.p_router, prefix="/p")

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
        out = await self.aksi("pasang", hid, {"izin": ["envelopes:read"]})
        self.assertEqual(out["status"], "terpasang")       # wizard
        out = await self.aksi("lanjut", hid)
        self.assertEqual(out["status"], "aktif")

    async def p(self, metode, path, hid=None, status=None, headers=None, **kw):
        headers = {**(self.hdr(hid) if hid is not False else {}), **(headers or {})}
        r = await self.client.request(metode, f"/p/buku_usaha{path}", headers=headers, **kw)
        if status is not None:
            self.assertEqual(r.status_code, status, r.text)
        return r

    async def kontak_baru(self, nama="Bu Sari", peran="pelanggan", hid=None, **lain):
        r = await self.p("POST", "/kontak", hid, 201, json={"nama": nama, "peran": peran, **lain})
        return r.json()

    async def kontribusi(self, hid=None):
        r = await self.client.get("/plugins/contributions", headers=self.hdr(hid))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def set_setting(self, key, value):
        async with self.Session() as db:
            ada = await db.get(AppSetting, key)
            if ada:
                ada.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            await db.commit()

    async def baris_kontak(self, hid=None, termasuk_terhapus=False):
        async with self.Session() as db:
            q = select(BukuUsahaKontak).where(BukuUsahaKontak.household_id == (hid or self.usaha))
            if not termasuk_terhapus:
                q = q.where(BukuUsahaKontak.deleted_at.is_(None))
            return (await db.execute(q.order_by(BukuUsahaKontak.nama))).scalars().all()

    async def audit(self, awalan="data:"):
        async with self.Session() as db:
            return [(a.action, a.detail) for a in (await db.execute(
                select(PluginAuditLog).where(PluginAuditLog.plugin_id == "buku_usaha")
                .order_by(PluginAuditLog.created_at, PluginAuditLog.id))).scalars() if a.action.startswith(awalan)]

    # ── 4. Gerbang H ──
    async def test_gerbang_h_siklus_bersih(self):
        # Katalog: tersedia, ekspor belum ada (belum pernah terpasang → 404).
        r = await self.client.get("/plugins", headers=self.hdr())
        self.assertEqual([(x["id"], x["status"], x["hak"]["status"]) for x in r.json()],
                         [("buku_usaha", "tersedia", "uji_coba")])
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual((r.status_code, r.json()["kode"]), (404, "plugin_tidak_aktif"))

        # Pasang → terpasang (wizard): belum ada kontribusi; rute GET boleh (wizard membaca pengaturan), tulis 404.
        out = await self.aksi("pasang", body={"izin": ["envelopes:read"]})
        self.assertEqual(out["status"], "terpasang")
        self.assertEqual(await self.kontribusi(), siklus.kontribusi([], {}))
        self.assertEqual((await self.p("GET", "/pengaturan", status=200)).json()["jumlah_kontak"],
                         {"pelanggan": 0, "pemasok": 0})
        r = await self.p("POST", "/kontak", status=404, json={"nama": "X", "peran": "pelanggan"})
        self.assertEqual(r.json()["kode"], "plugin_tidak_aktif")

        # Lanjut → aktif: menu Usaha, halaman, rute pengaturan (amplop bawaan: Bahan sudah ada, pribadi tidak dihitung).
        self.assertEqual((await self.aksi("lanjut"))["status"], "aktif")
        k = await self.kontribusi()
        self.assertEqual([(n["grup"], n["route"], n["label"]) for n in k["nav"]], [("usaha", "/p/buku_usaha", "Buku Usaha")])
        self.assertEqual(k["cards"], [])
        peng = (await self.p("GET", "/pengaturan", status=200)).json()
        self.assertEqual(peng["ruang"], "Dapur Nusa")
        self.assertEqual([(a["nama"], a["ada"]) for a in peng["amplop_bawaan"]],
                         [("Bahan", True), ("Operasional", False), ("Prive", False), ("Laba ditahan", False), ("Pajak", False)])
        self.assertIsNotNone(peng["amplop_bawaan"][0]["envelope_id"])
        self.assertEqual(peng["jumlah_kontak"], {"pelanggan": 0, "pemasok": 0})

        k1 = await self.kontak_baru("Bu Sari", telepon="0812-3456-789")
        k2 = await self.kontak_baru("UD Sumber Unggas", "pemasok", catatan="ayam potong")
        self.assertEqual([(x["nama"], x["peran"]) for x in (await self.p("GET", "/kontak", status=200)).json()],
                         [("Bu Sari", "pelanggan"), ("UD Sumber Unggas", "pemasok")])

        # Jeda: kontribusi dan rute hilang, data tetap; lanjut: semuanya kembali.
        self.assertEqual((await self.aksi("jeda"))["status"], "dijeda")
        self.assertEqual(await self.kontribusi(), siklus.kontribusi([], {}))
        self.assertEqual((await self.p("GET", "/kontak", status=404)).json()["kode"], "plugin_tidak_aktif")
        self.assertEqual((await self.p("POST", "/kontak", status=404, json={"nama": "X", "peran": "pelanggan"})).json()["kode"],
                         "plugin_tidak_aktif")
        self.assertEqual(len(await self.baris_kontak()), 2)
        # Dijeda: ekspor tetap bisa (data baca-saja, 01-kajian "Siklus data").
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.aksi("lanjut"))["status"], "aktif")
        self.assertEqual(len((await self.p("GET", "/kontak", status=200)).json()), 2)

        # Saklar darurat: rute dan kontribusi hilang seketika, status per ruang tetap aktif, ekspor dan jeda boleh.
        await self.set_setting("plugin_saklar_darurat", "Buku_Usaha")
        self.assertEqual((await self.p("GET", "/kontak", status=404)).json()["kode"], "plugin_tidak_aktif")
        self.assertEqual(await self.kontribusi(), siklus.kontribusi([], {}))
        r = await self.client.get("/plugins", headers=self.hdr())
        self.assertEqual([(x["status"], x["diperbaiki"]) for x in r.json()], [("aktif", True)])
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual(r.status_code, 200, r.text)
        await self.set_setting("plugin_saklar_darurat", "")
        self.assertEqual(len((await self.p("GET", "/kontak", status=200)).json()), 2)

        # Flag dicabut untuk pemilik: rute 404, admin (masih di flag) tetap bisa.
        await self.set_setting("plugin_buku_usaha_users", str(self.admin.id))
        self.assertEqual((await self.p("GET", "/kontak", status=404)).json()["kode"], "plugin_tidak_aktif")
        self.current = self.admin
        self.assertEqual(len((await self.p("GET", "/kontak", status=200)).json()), 2)
        self.current = self.pemilik
        await self.set_setting("plugin_buku_usaha_users", "*")

        # Copot → arsip: tautan ekspor di jawaban; rute dan kontribusi hilang; data arsip tetap (deleted_at kosong).
        out = await self.aksi("copot")
        self.assertEqual(out["status"], "arsip")
        self.assertEqual(out["ekspor"], {"csv": f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=csv",
                                         "json": f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json"})
        self.assertEqual((await self.p("GET", "/kontak", status=404)).json()["kode"], "plugin_tidak_aktif")
        self.assertEqual(await self.kontribusi(), siklus.kontribusi([], {}))
        self.assertEqual(len(await self.baris_kontak()), 2)
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual([x["nama"] for x in r.json()["data"]["kontak"]], ["Bu Sari", "UD Sumber Unggas"])

        # Pulihkan (pasang pada arsip) → terpasang lagi (wizard), lanjut → data kembali utuh.
        out = await self.aksi("pasang", body={"izin": ["envelopes:read"]})
        self.assertEqual(out["status"], "terpasang")
        self.assertEqual((await self.aksi("lanjut"))["status"], "aktif")
        self.assertEqual([x["id"] for x in (await self.p("GET", "/kontak", status=200)).json()], [k1["id"], k2["id"]])

        # Copot lagi lalu arsip lewat 90 hari: pembersih menghapus baris instalasi DAN semua data p_* ruang itu.
        await self.aksi("copot")
        async with self.Session() as db:
            hapus = await siklus.bersihkan_kedaluwarsa(db, now=datetime.now(timezone.utc) + timedelta(days=91))
            await db.commit()
        self.assertEqual(hapus, [(self.usaha, "buku_usaha")])
        self.assertEqual(await self.baris_kontak(termasuk_terhapus=True), [])
        async with self.Session() as db:
            self.assertIsNone(await siklus.instalasi(db, self.usaha, "buku_usaha"))
            bersih = [a for a in (await db.execute(select(PluginAuditLog).where(PluginAuditLog.action == "bersihkan")))
                      .scalars()]
            self.assertEqual(bersih[0].detail["baris"], 2)
        r = await self.client.get("/plugins", headers=self.hdr())
        self.assertEqual([x["status"] for x in r.json()], ["tersedia"])
        # Pasang ulang sesudah bersih: mulai dari nol.
        await self.pasang_aktif()
        self.assertEqual((await self.p("GET", "/kontak", status=200)).json(), [])

    async def test_pembersih_tidak_menyentuh_ruang_lain(self):
        await self.pasang_aktif()
        await self.pasang_aktif(self.usaha2)
        await self.kontak_baru("A")
        await self.kontak_baru("B", hid=self.usaha2)
        await self.aksi("copot")
        async with self.Session() as db:
            await siklus.bersihkan_kedaluwarsa(db, now=datetime.now(timezone.utc) + timedelta(days=91))
            await db.commit()
        self.assertEqual(await self.baris_kontak(termasuk_terhapus=True), [])
        self.assertEqual([k.nama for k in await self.baris_kontak(self.usaha2)], ["B"])

    # ── 5. isolasi ──
    async def test_isolasi_antar_ruang(self):
        await self.pasang_aktif()
        await self.pasang_aktif(self.usaha2)
        k = await self.kontak_baru("Bu Sari")
        # Ruang usaha lain milik user yang sama: tidak melihat, tidak bisa mengubah/menghapus walau tahu ID.
        self.assertEqual((await self.p("GET", "/kontak", self.usaha2, 200)).json(), [])
        for metode, status in (("PATCH", 404), ("DELETE", 404)):
            r = await self.p(metode, f"/kontak/{k['id']}", self.usaha2, status, json={"nama": "Diubah"})
            self.assertEqual(r.json()["kode"], "kontak_tidak_ada")
        self.assertEqual([x.nama for x in await self.baris_kontak()], ["Bu Sari"])
        # Ruang orang lain lewat header: resolver menolak sebelum plugin.
        r = await self.p("GET", "/kontak", self.asing, 403)
        self.assertEqual(r.json()["kode"], "ruang_tidak_diizinkan")
        # Ruang keluarga (tanpa header / header rumah): plugin tidak terpasang di sana.
        for hid in (False, self.rumah):
            self.assertEqual((await self.p("GET", "/kontak", hid, 404)).json()["kode"], "plugin_tidak_aktif")
        # Tidak ada kueri lintas ruang: pengaturan ruang kedua tidak melihat amplop/kontak Dapur Nusa.
        peng = (await self.p("GET", "/pengaturan", self.usaha2, 200)).json()
        self.assertEqual([a["ada"] for a in peng["amplop_bawaan"]], [False] * 5)
        self.assertEqual(peng["jumlah_kontak"], {"pelanggan": 0, "pemasok": 0})

    async def test_karyawan_dan_orang_luar_ditolak(self):
        await self.pasang_aktif()
        await self.kontak_baru("Bu Sari")
        self.current = self.karyawan
        for metode, path in (("GET", "/kontak"), ("GET", "/pengaturan"), ("POST", "/kontak")):
            r = await self.p(metode, path, status=403, json={"nama": "X", "peran": "pelanggan"})
            self.assertEqual(r.json()["kode"], "khusus_admin", path)
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual((r.status_code, r.json()["kode"]), (403, "khusus_admin"))
        self.current = self.orang
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual((r.status_code, r.json()["kode"]), (404, "ruang_tidak_ada"))
        # Admin boleh semuanya.
        self.current = self.admin
        self.assertEqual(len((await self.p("GET", "/kontak", status=200)).json()), 1)
        await self.kontak_baru("Pak Budi")

    async def test_plugin_dan_rute_tidak_dikenal(self):
        await self.pasang_aktif()
        r = await self.client.get("/p/tidak_ada/kontak", headers=self.hdr())
        self.assertEqual((r.status_code, r.json()["kode"]), (404, "plugin_tidak_ada"))
        for metode, path in (("GET", "/laba"), ("PUT", "/kontak"), ("GET", "/kontak/abc/def")):
            r = await self.p(metode, path, status=404, json={})
            self.assertEqual(r.json()["kode"], "rute_tidak_ada", path)

    async def test_audit_tulis(self):
        await self.pasang_aktif()
        k = await self.kontak_baru("Bu Sari")
        await self.p("PATCH", f"/kontak/{k['id']}", status=200, json={"telepon": "08123456789"})
        await self.p("DELETE", f"/kontak/{k['id']}", status=204)
        aud = {a: d for a, d in await self.audit()}
        self.assertEqual(sorted(aud), ["data:hapus", "data:tambah", "data:ubah"])
        self.assertEqual(aud["data:tambah"], {"tabel": "p_buku_usaha_kontak", "id": k["id"], "kolom": ["nama", "peran"],
                                              "sumber": "rute:POST /kontak"})
        self.assertEqual(aud["data:ubah"]["kolom"], ["telepon"])
        self.assertEqual(aud["data:hapus"]["sumber"], "rute:DELETE /kontak/{id}")
        # Nilai kolom tidak pernah masuk audit.
        self.assertNotIn("Bu Sari", json.dumps(aud))
        # Baca tidak diaudit per panggilan (keputusan H2 A).
        await self.p("GET", "/kontak", status=200)
        self.assertEqual(len(await self.audit()), 3)

    # ── 3. ctx.data() langsung ──
    async def _ctx(self, jenis="rute", kunci="GET /kontak", *, viewer=..., boleh_tulis=False, db=None):
        m = self.reg.get("buku_usaha")
        inst = await siklus.instalasi(db, self.usaha, "buku_usaha")
        ruang_ = (await db.execute(select(Household).where(Household.id == self.usaha))).scalar_one()
        d = Pendaftaran(jenis, kunci, lambda *a: None, ("envelopes:read",))
        user = self.pemilik if viewer is ... else viewer
        peran = "owner" if user is self.pemilik else ("member" if user is self.karyawan else "sistem")
        return titik.konteks(db, m, inst, ruang_, d, viewer=user, peran=peran, sumber="uji", boleh_tulis=boleh_tulis)

    async def test_data_hanya_tulis_dari_rute(self):
        await self.pasang_aktif()
        async with self.Session() as db:
            for jenis, viewer in (("kartu", ...), ("job", None)):
                ctx = await self._ctx(jenis, "x", viewer=viewer, db=db)
                with self.assertRaises(IzinDitolak) as cm:
                    await ctx.data("kontak").tambah({"nama": "A", "peran": "pelanggan"})
                self.assertEqual(cm.exception.alasan, "hanya_baca")
                self.assertEqual(await ctx.data("kontak").cari(), [])       # baca boleh
                keadaan.tutup(ctx)
            # Karyawan: baca pun ditolak.
            ctx = await self._ctx(viewer=self.karyawan, db=db)
            with self.assertRaises(IzinDitolak) as cm:
                await ctx.data("kontak").cari()
            self.assertEqual(cm.exception.alasan, "khusus_admin")
            keadaan.tutup(ctx)
            # Hanya tabel sendiri; kolom wajib dan kolom asing = bug plugin.
            ctx = await self._ctx(boleh_tulis=True, db=db)
            d = ctx.data("kontak")
            with self.assertRaises(ValueError):
                await ctx.data("p_uji_catatan").cari()
            with self.assertRaises(ValueError):
                await ctx.data("ruang_kamus").cari()
            with self.assertRaises(ValueError):
                await ctx.data("p_buku_usaha_kontak; drop").cari()
            with self.assertRaises(ValueError):
                await d.tambah({"nama": "A", "peran": "pelanggan", "household_id": str(self.usaha2)})
            with self.assertRaises(ValueError):
                await d.tambah({"nama": "A", "peran": "pelanggan", "created_by": str(self.orang.id)})
            with self.assertRaises(ValueError):
                await d.cari(saring={"household_id": str(self.usaha2)})
            with self.assertRaises(NilaiTidakSah):
                await d.tambah({"peran": "pelanggan"})                       # nama wajib
            with self.assertRaises(NilaiTidakSah):
                await d.tambah({"nama": "x" * 121, "peran": "pelanggan"})
            baris = await d.tambah({"nama": "A", "peran": "pelanggan"})
            self.assertNotIn("household_id", baris)
            self.assertEqual(baris["created_by"], self.pemilik.id)
            # Rujukan: alokasi ke amplop pribadi orang lain / ruang lain ditolak; amplop bersama ruang ini boleh.
            bahan = (await db.execute(select(Envelope).where(Envelope.name == "Bahan"))).scalar_one()
            pribadi = (await db.execute(select(Envelope).where(Envelope.name == "Pribadi pemilik"))).scalar_one()
            lain = Envelope(household_id=self.usaha2, name="Lain", emoji="x", budget_amount=0)
            db.add(lain)
            await db.flush()
            al = ctx.data("alokasi")
            with self.assertRaises(NilaiTidakSah):
                await al.tambah({"envelope_id": lain.id, "persen": Decimal("10")})
            with self.assertRaises(ValueError):
                await al.tambah({"envelope_id": bahan.id, "persen": 10.5})      # float
            with self.assertRaises(NilaiTidakSah):
                await al.tambah({"envelope_id": bahan.id, "persen": Decimal("1000")})
            self.assertEqual((await al.tambah({"envelope_id": bahan.id, "persen": Decimal("45")}))["persen"], Decimal("45"))
            self.assertEqual((await al.tambah({"envelope_id": pribadi.id, "persen": Decimal("5")}))["persen"], Decimal("5"))
            with self.assertRaises(NilaiTidakSah):
                await ctx.data("income_meta").tambah({"income_id": bahan.id, "jenis": "penjualan"})
            keadaan.tutup(ctx)
            with self.assertRaises(keadaan.KonteksTidakSah):
                await d.cari()                                                # konteks sudah ditutup

    # ── 6. kontak, ekspor, hapus akun ──
    async def test_validasi_kontak(self):
        await self.pasang_aktif()
        for body, kode in (({"nama": " ", "peran": "pelanggan"}, "nilai_tidak_sah"),
                           ({"nama": "A", "peran": "bos"}, "nilai_tidak_sah"),
                           ({"nama": "A", "peran": "pelanggan", "telepon": "abc"}, "nilai_tidak_sah"),
                           ({"nama": "A", "peran": "pelanggan", "lain": 1}, "nilai_tidak_sah"),
                           ({"nama": "A", "peran": "pelanggan", "catatan": "x" * 501}, "nilai_tidak_sah")):
            r = await self.p("POST", "/kontak", status=422, json=body)
            self.assertEqual(r.json()["kode"], kode, body)
        r = await self.p("POST", "/kontak", status=422, content=b"{bukan json", headers={**self.hdr(), "Content-Type": "application/json"})
        self.assertEqual(r.json()["kode"], "body_bukan_json")
        r = await self.p("POST", "/kontak", status=413, content=b" " * (65 * 1024))
        self.assertEqual(r.json()["kode"], "body_terlalu_besar")
        r = await self.p("GET", "/kontak?peran=bos", status=422)
        self.assertEqual(r.json()["kode"], "peran_tidak_dikenal")
        self.assertEqual(await self.audit(), [])

        k = await self.kontak_baru("  Bu   Sari ", telepon=" 0812 3456 ")
        self.assertEqual((k["nama"], k["telepon"], k["catatan"]), ("Bu Sari", "0812 3456", None))
        r = await self.p("POST", "/kontak", status=409, json={"nama": "bu sari", "peran": "pelanggan"})
        self.assertEqual(r.json()["kode"], "kontak_ganda")
        await self.kontak_baru("Bu Sari", "pemasok")              # peran lain boleh
        k2 = await self.kontak_baru("Pak Budi")
        r = await self.p("PATCH", f"/kontak/{k2['id']}", status=409, json={"nama": "BU SARI"})
        self.assertEqual(r.json()["kode"], "kontak_ganda")
        r = await self.p("PATCH", f"/kontak/{k2['id']}", status=200, json={"telepon": None, "catatan": "langganan"})
        self.assertEqual((r.json()["telepon"], r.json()["catatan"]), (None, "langganan"))
        # Saring dan cari.
        self.assertEqual([x["nama"] for x in (await self.p("GET", "/kontak?peran=pemasok", status=200)).json()], ["Bu Sari"])
        self.assertEqual([x["nama"] for x in (await self.p("GET", "/kontak?q=sar", status=200)).json()], ["Bu Sari", "Bu Sari"])
        self.assertEqual([x["nama"] for x in (await self.p("GET", "/kontak?q=%25", status=200)).json()], [])
        # Hapus lunak: hilang dari daftar, baris tetap ada; nama yang sama boleh dibuat lagi.
        await self.p("DELETE", f"/kontak/{k['id']}", status=204)
        self.assertEqual((await self.p("DELETE", f"/kontak/{k['id']}", status=404)).json()["kode"], "kontak_tidak_ada")
        self.assertEqual(len(await self.baris_kontak(termasuk_terhapus=True)), 3)
        self.assertEqual(len(await self.baris_kontak()), 2)
        await self.kontak_baru("Bu Sari")
        self.assertEqual((await self.p("PATCH", "/kontak/bukan-uuid", status=404, json={"nama": "x"})).json()["kode"],
                         "kontak_tidak_ada")

    async def test_ekspor_json_dan_csv(self):
        await self.pasang_aktif()
        await self.kontak_baru("=1+1", catatan="+SUM(A1)")
        await self.kontak_baru("Bu Sari", "pemasok", telepon="+62 812")
        await self.kontak_baru("-Minus", "pemasok")
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=json")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("attachment; filename=\"jatahku-buku_usaha-", r.headers["content-disposition"])
        isi = r.json()
        self.assertEqual((isi["plugin"], isi["ruang_id"]), ("buku_usaha", str(self.usaha)))
        self.assertEqual(sorted(isi["data"]), ["alokasi", "income_meta", "kontak", "txn_meta"])
        self.assertEqual(sorted(k["nama"] for k in isi["data"]["kontak"]), ["-Minus", "=1+1", "Bu Sari"])
        self.assertNotIn("household_id", isi["data"]["kontak"][0])
        self.assertNotIn("deleted_at", isi["data"]["kontak"][0])

        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=csv")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/zip"))
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertEqual(sorted(z.namelist()), ["alokasi.csv", "income_meta.csv", "kontak.csv", "txn_meta.csv"])
        baris = list(csv.reader(io.StringIO(z.read("kontak.csv").decode("utf-8-sig"))))
        self.assertEqual(baris[0], ["id", "nama", "peran", "telepon", "catatan", "created_by", "created_at", "updated_at"])
        nama, catatan, telepon = (baris[0].index(k) for k in ("nama", "catatan", "telepon"))
        per_nama = {b[nama]: b for b in baris[1:]}
        # Anti formula-injection (PR #136): sel teks berawalan = + - @ diberi kutip.
        self.assertEqual(sorted(per_nama), ["'-Minus", "'=1+1", "Bu Sari"])
        self.assertEqual(per_nama["'=1+1"][catatan], "'+SUM(A1)")
        self.assertEqual(per_nama["Bu Sari"][telepon], "'+62 812")
        r = await self.client.get(f"/ruang/{self.usaha}/plugins/buku_usaha/ekspor?format=xml")
        self.assertEqual(r.status_code, 422)
        aud = await self.audit("ekspor")
        self.assertEqual(sorted(a[1]["format"] for a in aud), ["csv", "json"])
        self.assertEqual({a[1]["tabel"]["kontak"] for a in aud}, {3})

    async def test_hapus_akun(self):
        from app.services import account_deletion
        await self.pasang_aktif()
        await self.pasang_aktif(self.usaha2)
        self.current = self.admin
        await self.kontak_baru("Dari admin")
        self.current = self.pemilik
        await self.kontak_baru("Dari pemilik")
        await self.kontak_baru("Toko kedua", hid=self.usaha2)
        # Admin pergi: ruang Dapur Nusa masih punya pemilik → datanya tetap, pencatat dikosongkan.
        async with self.Session() as db:
            await account_deletion.delete_account(db, await db.get(User, self.admin.id))
        kontak = await self.baris_kontak()
        self.assertEqual([(k.nama, k.created_by) for k in kontak],
                         [("Dari admin", None), ("Dari pemilik", self.pemilik.id)])
        # Pemilik pergi: Dapur Nusa dan Toko Kedua ikut terhapus (karyawan masih anggota Dapur Nusa → tidak!).
        async with self.Session() as db:
            await account_deletion.delete_account(db, await db.get(User, self.karyawan.id))
            await account_deletion.delete_account(db, await db.get(User, self.pemilik.id))
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(sa.func.count()).select_from(BukuUsahaKontak))).scalar(), 0)
            self.assertEqual((await db.execute(select(sa.func.count()).select_from(PluginInstallation))).scalar(), 0)


if __name__ == "__main__":
    unittest.main()
