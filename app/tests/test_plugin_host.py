"""Plugin H1 — host inti (03-workflow.md baris H1; 04-kontrak-api.md §5; ADR-P9, P11, P14, P15).

1. Manifest: aturan T1 ditegakkan skema (penerbit, izin terlarang, awalan tabel/kunci, perintah bot baca saja).
2. Registry dan validator CI: aturan antarplugin, mode ketat vs mode start, kode keluar validator.
3. HTTP: katalog, pasang/lanjut/jeda/copot/pulihkan, idempotensi, audit; ruang dari path (IDOR → 404),
   peran (member → 403 `khusus_admin`), jenis ruang, requires/conflicts, saklar darurat, flag, hak, pembersih.

Run: python -m unittest app.tests.test_plugin_host -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.plugins.host.manifest import Manifest, cocok_rentang
from app.plugins.host.registry import ManifestTidakSah, Registry, muat, pakai_registry

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

DASAR = {
    "id": "uji",
    "name": "Uji",
    "version": "1.0.0",
    "publisher": "Jatahku",
    "description": "Plugin uji host",
    "engines": {"plugin_api": ">=1.0 <2.0"},
    "space_types": ["usaha"],
    "permissions": ["incomes:read", "incomes:write"],
    "entities": ["p_uji_catatan"],
    "contributes": {
        "cards": [{"key": "uji.omzet", "title": "Omzet", "shape": "kpi", "sizes": ["S", "M"], "default": True}],
        "pages": [{"route": "/p/uji", "title": "Uji", "nav": "usaha"}],
        "quick_actions": [{"key": "uji.baru", "label": "Baru"}],
        "bot_commands": [{"command": "uji", "help": "Cek uji", "kind": "read", "audience": "admin"}],
        "bot_callbacks": [{"prefix": "uj_"}],
        "advisor_rules": ["UJ-01"],
        "notifications": ["uji.pengingat"],
    },
    "entitlement": {"sku": "bundle.usaha", "trial_days": 14},
}


KOSONG = {"cards": [], "pages": [], "quick_actions": [], "bot_commands": [], "bot_callbacks": [],
          "advisor_rules": [], "notifications": []}


def mf(**ubah) -> dict:
    d = copy.deepcopy(DASAR)
    for k, v in ubah.items():
        if k == "contributes":
            d["contributes"].update(v)
        else:
            d[k] = v
    return d


def manifest(**ubah) -> Manifest:
    return Manifest.model_validate(mf(**ubah))


# ── 1. manifest ─────────────────────────────────────────────────────────
class ManifestTests(unittest.TestCase):
    def test_manifest_sah(self):
        m = manifest()
        self.assertEqual(m.flag_key, "plugin_uji_users")
        self.assertEqual(m.izin_tampil()[1], {"kode": "incomes:write", "teks": "Mencatat pemasukan"})

    def _gagal(self, pesan_bagian=None, **ubah):
        with self.assertRaises(ValidationError) as cm:
            manifest(**ubah)
        if pesan_bagian:
            self.assertIn(pesan_bagian, str(cm.exception))

    def test_hanya_penerbit_jatahku(self):
        self._gagal("ADR-P9", publisher="Mitra")

    def test_izin_terlarang_t1(self):
        self._gagal("ADR-P14", permissions=["ai:analyze"])
        self._gagal("ADR-P14", permissions=["network:api.contoh.com"])
        self._gagal("tidak dikenal", permissions=["users:delete"])
        self._gagal("ganda", permissions=["incomes:read", "incomes:read"])

    def test_awalan_wajib(self):
        self._gagal("p_uji_", entities=["transactions"])
        self._gagal("'uji.'", contributes={"cards": [{"key": "omzet", "title": "O", "shape": "kpi", "sizes": ["S"]}]})
        self._gagal("/p/uji", contributes={"pages": [{"route": "/p/lain", "title": "L"}]})
        self._gagal("'uji.'", contributes={"notifications": ["pengingat"]})
        self._gagal("di luar plugin", contributes={"form_fields": [
            {"target": "income", "key": "xx", "type": "reference", "label": "X", "entity": "p_lain_x"}]})

    def test_bot_hanya_baca_dan_audience_wajib(self):
        self._gagal(contributes={"bot_commands": [{"command": "uji", "help": "h", "kind": "write", "audience": "admin"}]})
        self._gagal(contributes={"bot_commands": [{"command": "uji", "help": "h", "kind": "read"}]})
        self._gagal(contributes={"bot_callbacks": [{"prefix": "panjangsekali_"}]})

    def test_batas_lain(self):
        aksi = [{"key": f"uji.a{i}", "label": "A"} for i in range(3)]
        self._gagal(contributes={"quick_actions": aksi})                       # maksimal 2
        self._gagal(data_lifecycle={"on_uninstall": "delete_now"})             # ADR-P15
        self._gagal(scope="pribadi")                                           # ADR-P11
        self._gagal("tidak cocok", engines={"plugin_api": ">=2.0"})
        self._gagal(id="host")
        self._gagal(id="Uji")
        self._gagal(extra_field=1)                                             # kunci asing ditolak
        self._gagal("dirinya", requires=["uji"])

    def test_rentang_plugin_api(self):
        self.assertTrue(cocok_rentang(">=1.0 <2.0", (1, 4, 0)))
        self.assertFalse(cocok_rentang(">=1.0 <2.0", (2, 0, 0)))
        self.assertTrue(cocok_rentang("==1.0.0", (1, 0, 0)))
        with self.assertRaises(ValueError):
            cocok_rentang("~1.0")


# ── 2. registry dan validator ───────────────────────────────────────────
class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def tulis(self, folder, data):
        (self.dir / folder).mkdir()
        (self.dir / folder / "manifest.json").write_text(
            data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_folder_bukan_plugin_dilewati(self):
        for nama in ("host", "sdk", "_contoh"):
            (self.dir / nama).mkdir()
        self.tulis("uji", mf())
        self.assertEqual(list(muat(self.dir, ketat=True).plugins), ["uji"])

    def test_galat_antarplugin(self):
        self.tulis("uji", mf())
        self.tulis("beda_nama", mf(id="lain", entities=[], contributes=KOSONG))
        self.tulis("kembar", mf(id="kembar", requires=["tidak_ada"], entities=[],
                                contributes={**KOSONG, "bot_callbacks": [{"prefix": "uj_"}], "advisor_rules": ["UJ-01"]}))
        self.tulis("rusak", "{ini bukan json")
        with self.assertRaises(ManifestTidakSah) as cm:
            muat(self.dir, ketat=True)
        teks = "\n".join(cm.exception.galat)
        self.assertIn("beda_nama: id 'lain' harus sama dengan nama folder", teks)
        self.assertIn("kembar: requires 'tidak_ada' tidak ada", teks)
        # Tabrakan dilaporkan pada plugin yang namanya lebih akhir menurut abjad.
        self.assertIn("uji: prefix callback 'uj_' sudah dipakai plugin 'kembar'", teks)
        self.assertIn("uji: aturan advisor 'UJ-01' sudah dipakai plugin 'kembar'", teks)
        self.assertIn("rusak: manifest.json bukan JSON sah", teks)

    def test_requires_melingkar_dan_jenis_ruang(self):
        self.tulis("aa", mf(id="aa", requires=["bb"], entities=[], contributes=KOSONG))
        self.tulis("bb", mf(id="bb", requires=["aa"], entities=[], contributes=KOSONG))
        self.tulis("cc", mf(id="cc", requires=["aa"], space_types=["usaha", "rumah_tangga"], entities=[],
                            contributes=KOSONG))
        with self.assertRaises(ManifestTidakSah) as cm:
            muat(self.dir, ketat=True)
        teks = "\n".join(cm.exception.galat)
        self.assertIn("aa: requires melingkar", teks)
        self.assertIn("cc: requires 'aa' tidak mendukung semua jenis ruang", teks)

    def test_mode_start_melewati_yang_rusak_dan_pemakainya(self):
        self.tulis("uji", mf(publisher="Mitra"))                       # skema salah
        self.tulis("anak", mf(id="anak", requires=["uji"], entities=[], contributes=KOSONG))
        self.tulis("baik", mf(id="baik", entities=[], contributes=KOSONG))
        with self.assertLogs("jatahku.plugins", level="ERROR"):
            reg = muat(self.dir)
        self.assertEqual(list(reg.plugins), ["baik"])
        self.assertTrue(any("anak: requires 'uji' tidak ada" in g for g in reg.galat))

    def test_validator_kode_keluar(self):
        from app.plugins.host.validator import main
        self.tulis("uji", mf())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(self.dir)]), 0)
        self.assertIn("OK: 1 plugin sah", out.getvalue())
        self.tulis("salah", mf(id="salah", publisher="Mitra"))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(self.dir)]), 1)
        self.assertIn("GALAT salah: publisher", out.getvalue())

    def test_semua_plugin_di_repo_sah(self):
        """Sama dengan langkah CI `python -m app.plugins.host.validator`."""
        muat(ketat=True)


# ── 3. HTTP ─────────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import func, select

    from app.api.routes import plugins
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        AppSetting, Entitlement, Household, HouseholdMember, HouseholdRole, PluginAuditLog, PluginInstallation, User,
    )
    from app.plugins.host import siklus
    from app.services import ruang

    def _registry_uji() -> Registry:
        ms = [
            manifest(),
            manifest(id="uji_wizard", entities=[], contributes={**KOSONG, "setup": True}, entitlement=None),
            manifest(id="uji_dep", requires=["uji"], entities=[], contributes=KOSONG),
            manifest(id="uji_kel", space_types=["rumah_tangga"], entities=[], contributes=KOSONG),
            manifest(id="uji_bentrok", conflicts=["uji"], entities=[], contributes=KOSONG),
            manifest(id="uji_rahasia", entities=[], contributes=KOSONG),      # tanpa flag
        ]
        return Registry(plugins={m.id: m for m in ms})


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class HostHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        ctx = pakai_registry(_registry_uji())
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

        async with self.Session() as db:
            pemilik, admin, karyawan, orang = (User(name=n) for n in ("Pemilik", "Admin", "Karyawan", "Orang"))
            usaha = Household(name="Dapur Nusa", type="usaha")
            rumah = Household(name="Rumah", type="rumah_tangga")
            asing = Household(name="Usaha orang", type="usaha")
            db.add_all([pemilik, admin, karyawan, orang, usaha, rumah, asing])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=pemilik.id, household_id=usaha.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=admin.id, household_id=usaha.id, role=HouseholdRole.admin),
                HouseholdMember(user_id=karyawan.id, household_id=usaha.id, role=HouseholdRole.member),
                HouseholdMember(user_id=pemilik.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=orang.id, household_id=asing.id, role=HouseholdRole.owner),
            ])
            for key in ("plugin_uji_users", "plugin_uji_wizard_users", "plugin_uji_dep_users",
                        "plugin_uji_kel_users", "plugin_uji_bentrok_users"):
                db.add(AppSetting(key=key, value="*"))
            await db.commit()
        self.pemilik, self.admin, self.karyawan, self.orang = pemilik, admin, karyawan, orang
        self.usaha, self.rumah, self.asing = usaha.id, rumah.id, asing.id

        self.current = pemilik
        app = FastAPI()
        ruang.install(app)
        app.include_router(plugins.router, prefix="/plugins")
        app.include_router(plugins.ruang_router, prefix="/ruang")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    # ── pembantu ──
    async def aksi(self, aksi, plugin="uji", ruang_id=None, **kw):
        return await self.client.post(f"/ruang/{ruang_id or self.usaha}/plugins/{plugin}/{aksi}", **kw)

    async def katalog(self, ruang_id=None):
        r = await self.client.get("/plugins", headers={"X-Jatahku-Ruang": str(ruang_id or self.usaha)})
        self.assertEqual(r.status_code, 200, r.text)
        return {p["id"]: p for p in r.json()}

    async def audit(self, plugin="uji"):
        async with self.Session() as db:
            return [a.action for a in (await db.execute(
                select(PluginAuditLog).where(PluginAuditLog.plugin_id == plugin).order_by(PluginAuditLog.created_at)
            )).scalars()]

    async def jumlah_instalasi(self):
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(PluginInstallation))).scalar_one()

    def galat(self, r, status, kode):
        self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(r.json()["kode"], kode, r.text)
        self.assertTrue(r.json()["detail"])

    async def set_setting(self, key, value):
        async with self.Session() as db:
            ada = await db.get(AppSetting, key)
            if ada:
                ada.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            await db.commit()

    # ── katalog ──
    async def test_katalog_ruang_usaha(self):
        k = await self.katalog()
        self.assertEqual(sorted(k), ["uji", "uji_bentrok", "uji_dep", "uji_wizard"])   # tanpa _kel, _rahasia
        p = k["uji"]
        self.assertEqual(p["status"], "tersedia")
        self.assertEqual(p["izin"][0], {"kode": "incomes:read", "teks": "Melihat pemasukan"})
        self.assertEqual(p["kartu"], [{"key": "uji.omzet", "judul": "Omzet", "bawaan": True}])
        self.assertEqual(p["hak"], {"status": "uji_coba", "sampai": None})
        self.assertEqual(k["uji_wizard"]["hak"], {"status": "gratis", "sampai": None})
        self.assertFalse(p["diperbaiki"])
        self.assertTrue(p["boleh_kelola"])
        self.current = self.karyawan
        self.assertFalse((await self.katalog())["uji"]["boleh_kelola"])

    async def test_katalog_ruang_keluarga_dan_header_asing(self):
        self.assertEqual(sorted(await self.katalog(self.rumah)), ["uji_kel"])
        r = await self.client.get("/plugins", headers={"X-Jatahku-Ruang": str(self.asing)})
        self.galat(r, 403, "ruang_tidak_diizinkan")

    async def test_hak_aktif_dari_entitlements(self):
        async with self.Session() as db:
            db.add(Entitlement(household_id=self.usaha, sku="bundle.usaha", source="promo",
                               ends_at=datetime(2030, 1, 31, tzinfo=timezone.utc)))
            await db.commit()
        self.assertEqual((await self.katalog())["uji"]["hak"], {"status": "aktif", "sampai": "2030-01-31"})

    # ── siklus ──
    async def test_pasang_jeda_lanjut_copot_pulihkan(self):
        r = await self.aksi("pasang")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"plugin": "uji", "status": "aktif", "arsip_sampai": None,
                                    "izin_diberikan": ["incomes:read", "incomes:write"]})
        self.assertEqual((await self.aksi("pasang")).json()["status"], "aktif")       # idempoten
        self.assertEqual((await self.katalog())["uji"]["status"], "aktif")

        self.assertEqual((await self.aksi("jeda")).json()["status"], "dijeda")
        self.assertEqual((await self.aksi("jeda")).json()["status"], "dijeda")
        self.assertEqual((await self.aksi("lanjut")).json()["status"], "aktif")

        r = await self.aksi("copot")
        body = r.json()
        self.assertEqual((body["status"], body["ekspor"], body["izin_diberikan"]), ("arsip", None, []))
        sampai = datetime.fromisoformat(body["arsip_sampai"]).date()
        self.assertEqual(sampai, (datetime.now(timezone.utc) + timedelta(days=90)).date())
        self.assertEqual((await self.aksi("copot")).json()["status"], "arsip")
        self.galat(await self.aksi("jeda"), 404, "plugin_tidak_aktif")
        self.galat(await self.aksi("lanjut"), 404, "plugin_tidak_aktif")

        async with self.Session() as db:
            id_lama = (await siklus.instalasi(db, self.usaha, "uji")).id
        r = await self.aksi("pasang")                                                  # pulihkan
        self.assertEqual(r.json()["status"], "aktif")
        async with self.Session() as db:
            inst = await siklus.instalasi(db, self.usaha, "uji")
        self.assertEqual(inst.id, id_lama)                                             # baris (dan data) yang sama
        self.assertIsNone(inst.purge_after)
        self.assertEqual(await self.audit(), ["pasang", "jeda", "lanjut", "copot", "pulihkan"])
        async with self.Session() as db:
            a = (await db.execute(select(PluginAuditLog).where(PluginAuditLog.action == "jeda"))).scalar_one()
        self.assertEqual((a.actor_id, a.household_id, a.detail), (self.pemilik.id, self.usaha,
                                                                    {"dari": "active", "ke": "paused"}))

    async def test_wizard_terpasang_dulu(self):
        self.assertEqual((await self.aksi("pasang", "uji_wizard")).json()["status"], "terpasang")
        self.assertEqual((await self.aksi("lanjut", "uji_wizard")).json()["status"], "aktif")

    async def test_jeda_dari_terpasang_lalu_copot(self):
        await self.aksi("pasang", "uji_wizard")
        self.assertEqual((await self.aksi("jeda", "uji_wizard")).json()["status"], "dijeda")
        self.assertEqual((await self.aksi("copot", "uji_wizard")).json()["status"], "arsip")

    # ── keamanan: ruang dari path dan peran ──
    async def test_bukan_anggota_404_tanpa_baris(self):
        self.current = self.orang
        for aksi in ("pasang", "lanjut", "jeda", "copot"):
            self.galat(await self.aksi(aksi), 404, "ruang_tidak_ada")
        self.galat(await self.aksi("pasang", ruang_id="bukan-uuid"), 404, "ruang_tidak_ada")
        self.galat(await self.aksi("pasang", ruang_id="00000000-0000-0000-0000-000000000000"), 404, "ruang_tidak_ada")
        self.assertEqual(await self.jumlah_instalasi(), 0)
        self.assertEqual(await self.audit(), [])

    async def test_karyawan_403_admin_boleh(self):
        self.current = self.karyawan
        for aksi in ("pasang", "lanjut", "jeda", "copot"):
            self.galat(await self.aksi(aksi), 403, "khusus_admin")
        self.assertEqual(await self.jumlah_instalasi(), 0)
        self.current = self.admin
        self.assertEqual((await self.aksi("pasang")).json()["status"], "aktif")
        self.current = self.karyawan
        self.galat(await self.aksi("copot"), 403, "khusus_admin")                     # karyawan tidak bisa mencopot
        self.assertEqual((await self.katalog())["uji"]["status"], "aktif")

    async def test_header_tidak_menentukan_ruang_tulis(self):
        """Ruang tulis hanya dari path: header ruang lain diabaikan untuk pasang."""
        r = await self.client.post(f"/ruang/{self.usaha}/plugins/uji/pasang",
                                   headers={"X-Jatahku-Ruang": str(self.rumah)})
        self.assertEqual(r.json()["status"], "aktif")
        async with self.Session() as db:
            self.assertIsNotNone(await siklus.instalasi(db, self.usaha, "uji"))
            self.assertIsNone(await siklus.instalasi(db, self.rumah, "uji"))

    # ── aturan plugin ──
    async def test_plugin_tidak_ada_atau_tanpa_flag(self):
        self.galat(await self.aksi("pasang", "tidak_ada"), 404, "plugin_tidak_ada")
        self.galat(await self.aksi("pasang", "uji_rahasia"), 404, "plugin_tidak_ada")
        r = await self.aksi("pasang", "Bukan-ID")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(await self.jumlah_instalasi(), 0)

    async def test_flag_dicabut_masih_bisa_dicopot(self):
        await self.aksi("pasang")
        await self.set_setting("plugin_uji_users", "")
        self.assertEqual((await self.katalog())["uji"]["status"], "aktif")             # tetap tampil untuk dikelola
        self.assertEqual((await self.aksi("copot")).json()["status"], "arsip")
        self.galat(await self.aksi("pasang"), 404, "plugin_tidak_ada")                 # tapi tidak bisa dipulihkan

    async def test_jenis_ruang(self):
        self.galat(await self.aksi("pasang", "uji_kel"), 422, "jenis_ruang_tidak_cocok")
        self.galat(await self.aksi("pasang", "uji", ruang_id=self.rumah), 422, "jenis_ruang_tidak_cocok")

    async def test_requires(self):
        self.galat(await self.aksi("pasang", "uji_dep"), 409, "butuh_plugin")
        await self.aksi("pasang")
        self.assertEqual((await self.aksi("pasang", "uji_dep")).json()["status"], "aktif")
        self.galat(await self.aksi("jeda"), 409, "dibutuhkan_plugin_lain")
        self.galat(await self.aksi("copot"), 409, "dibutuhkan_plugin_lain")
        await self.aksi("jeda", "uji_dep")
        self.assertEqual((await self.aksi("jeda")).json()["status"], "dijeda")         # pemakai dijeda → boleh
        self.galat(await self.aksi("copot"), 409, "dibutuhkan_plugin_lain")            # datanya masih dipakai
        self.galat(await self.aksi("lanjut", "uji_dep"), 409, "butuh_plugin")
        await self.aksi("copot", "uji_dep")
        self.assertEqual((await self.aksi("copot")).json()["status"], "arsip")

    async def test_conflicts_dua_arah(self):
        await self.aksi("pasang")
        self.galat(await self.aksi("pasang", "uji_bentrok"), 409, "bentrok_plugin")
        await self.aksi("copot")
        await self.aksi("pasang", "uji_bentrok")
        self.galat(await self.aksi("pasang"), 409, "bentrok_plugin")

    async def test_pengaturan_belum_diterima(self):
        self.galat(await self.aksi("pasang", json={"pengaturan": {"a": 1}}), 422, "pengaturan_tidak_sah")
        self.assertEqual((await self.aksi("pasang", json={"pengaturan": {}})).status_code, 200)

    # ── saklar darurat ──
    async def test_saklar_darurat(self):
        await self.aksi("pasang")
        await self.aksi("pasang", "uji_wizard")
        await self.aksi("lanjut", "uji_wizard")
        async with self.Session() as db:
            self.assertEqual([m.id for m in await siklus.aktif_di_ruang(db, self.usaha, self.pemilik.id)],
                             ["uji", "uji_wizard"])

        await self.set_setting("plugin_saklar_darurat", "uji")
        async with self.Session() as db:
            self.assertEqual([m.id for m in await siklus.aktif_di_ruang(db, self.usaha, self.pemilik.id)],
                             ["uji_wizard"])
            self.assertEqual((await siklus.instalasi(db, self.usaha, "uji")).status, "active")  # status ruang utuh
        k = await self.katalog()
        self.assertTrue(k["uji"]["diperbaiki"])
        self.assertEqual(k["uji"]["status"], "aktif")
        self.assertEqual((await self.aksi("jeda")).json()["status"], "dijeda")         # arah aman tetap boleh
        self.galat(await self.aksi("lanjut"), 503, "plugin_diperbaiki")
        await self.aksi("copot")
        self.galat(await self.aksi("pasang"), 503, "plugin_diperbaiki")

        await self.set_setting("plugin_saklar_darurat", "")
        self.assertEqual((await self.aksi("pasang")).json()["status"], "aktif")

    async def test_aktif_di_ruang_hanya_status_aktif_dan_flag_user(self):
        await self.aksi("pasang")
        await self.aksi("pasang", "uji_wizard")                                         # masih terpasang
        await self.set_setting("plugin_uji_users", str(self.pemilik.id))
        async with self.Session() as db:
            self.assertEqual([m.id for m in await siklus.aktif_di_ruang(db, self.usaha, self.pemilik.id)], ["uji"])
            self.assertEqual(await siklus.aktif_di_ruang(db, self.usaha, self.karyawan.id), [])
            self.assertEqual(await siklus.aktif_di_ruang(db, self.asing, self.pemilik.id), [])
        await self.aksi("jeda")
        async with self.Session() as db:
            self.assertEqual(await siklus.aktif_di_ruang(db, self.usaha, self.pemilik.id), [])

    # ── pembersih arsip ──
    async def test_bersihkan_kedaluwarsa(self):
        await self.aksi("pasang")
        await self.aksi("copot")
        await self.aksi("pasang", "uji_wizard")
        await self.aksi("copot", "uji_wizard")
        async with self.Session() as db:
            sekarang = datetime.now(timezone.utc)
            self.assertEqual(await siklus.bersihkan_kedaluwarsa(db, sekarang + timedelta(days=89)), [])
            inst = await siklus.instalasi(db, self.usaha, "uji_wizard")
            inst.purge_after = sekarang + timedelta(days=200)
            await db.flush()
            hasil = await siklus.bersihkan_kedaluwarsa(db, sekarang + timedelta(days=91))
            await db.commit()
        self.assertEqual(hasil, [(self.usaha, "uji")])
        self.assertEqual(await self.jumlah_instalasi(), 1)
        self.assertEqual(await self.audit(), ["pasang", "copot", "bersihkan"])
        self.assertEqual((await self.katalog())["uji"]["status"], "tersedia")
        self.assertEqual((await self.aksi("pasang")).json()["status"], "aktif")       # pasang baru setelah dibersihkan

    async def test_keunikan_instalasi_per_ruang(self):
        from sqlalchemy.exc import IntegrityError
        async with self.Session() as db:
            for _ in range(2):
                db.add(PluginInstallation(household_id=self.usaha, plugin_id="uji", status="active",
                                          granted_permissions=[], settings={}))
            with self.assertRaises(IntegrityError):
                await db.flush()


if __name__ == "__main__":
    unittest.main()
