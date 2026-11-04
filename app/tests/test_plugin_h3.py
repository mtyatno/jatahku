"""Plugin H3 — host di frontend: kontribusi per ruang, persetujuan izin, kartu plugin di katalog Beranda
(03-workflow.md baris H3; 04-kontrak-api.md §4, §5; ADR-P4, P9, P10, P11, P15).

1. `siklus.kontribusi` (murni): menu hanya dari halaman ber-`nav`, aksi cepat, kartu hanya yang punya kode, field form.
2. `GET /plugins/contributions`: hanya plugin aktif di ruang header untuk user ini; karyawan 403; dijeda, wizard,
   saklar darurat, flag dicabut, ruang lain → kosong / ditolak.
3. Persetujuan izin di `pasang`: daftar izin yang dilihat user harus sama dengan manifest sekarang (409 `izin_berubah`),
   juga saat memulihkan; klien tanpa field tetap jalan; tidak membocorkan plugin di luar flag.
4. `GET /dashboard/cards`: kartu plugin aktif ikut katalog pengelola, tidak pernah untuk karyawan.

Run: python -m unittest app.tests.test_plugin_h3 -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import importlib.util
import unittest

from app.plugins.host import siklus
from app.plugins.host.manifest import Manifest
from app.plugins.host.registry import Registry, pakai_registry
from app.tests import test_plugin_sdk as sdk_uji

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

# Plugin "contoh" dari tes H2 (kode server: kartu `contoh.kas` dan `contoh.rusak`) ditambah halaman dan aksi cepat.
HALAMAN = {
    "pages": [{"route": "/p/contoh", "title": "Contoh", "nav": "usaha"},
              {"route": "/p/contoh/laporan", "title": "Laporan contoh", "nav": "lainnya"},
              {"route": "/p/contoh/detail", "title": "Detail"}],            # tanpa nav: rute saja
    "quick_actions": [{"key": "contoh.penjualan", "label": "Penjualan"}],
}

# Plugin tanpa kode (hanya manifest) untuk siklus pasang: kartunya tidak pernah ditawarkan.
UJI = {
    "id": "uji", "name": "Uji", "version": "1.0.0", "publisher": "Jatahku", "description": "Plugin uji H3",
    "engines": {"plugin_api": ">=1.0 <2.0"}, "space_types": ["usaha"],
    "permissions": ["incomes:read", "transactions:read"],
    "contributes": {"cards": [{"key": "uji.omzet", "title": "Omzet", "shape": "kpi", "sizes": ["S"], "default": True}],
                    "pages": [{"route": "/p/uji", "title": "Uji", "nav": "usaha"}]},
}


def manifest_contoh() -> Manifest:
    return Manifest.model_validate(sdk_uji.mf(contributes=HALAMAN))


def manifest_uji(**ubah) -> Manifest:
    d = copy.deepcopy(UJI)
    d.update(ubah)
    return Manifest.model_validate(d)


def registry_h3(**uji) -> Registry:
    return Registry(plugins={"contoh": manifest_contoh(), "uji": manifest_uji(**uji)}, kode={"contoh": sdk_uji.plugin})


# ── 1. murni ────────────────────────────────────────────────────────────
class KontribusiMurniTests(unittest.TestCase):
    def test_bentuk_dan_sumber(self):
        from app.plugins.host.titik import _definisi
        m = manifest_contoh()
        kartu = {k.key: _definisi(m, k) for k in m.contributes.cards}
        out = siklus.kontribusi([m], kartu)
        self.assertEqual(out["plugins"], [{"id": "contoh", "nama": "Contoh", "ikon": "puzzle"}])
        self.assertEqual(out["nav"], [
            {"plugin": "contoh", "grup": "usaha", "label": "Contoh", "route": "/p/contoh", "ikon": "puzzle"},
            {"plugin": "contoh", "grup": "lainnya", "label": "Laporan contoh", "route": "/p/contoh/laporan",
             "ikon": "puzzle"},
        ])
        self.assertEqual([p["route"] for p in out["pages"]], ["/p/contoh", "/p/contoh/laporan", "/p/contoh/detail"])
        self.assertEqual(out["quick_actions"],
                         [{"plugin": "contoh", "key": "contoh.penjualan", "label": "Penjualan", "ikon": "puzzle"}])
        self.assertEqual(out["cards"][0], {"key": "contoh.kas", "plugin": "contoh", "judul": "Kas", "shape": "kpi",
                                           "sizes": ["S", "M"], "size_bawaan": "S", "bawaan": False})
        self.assertEqual(out["form_fields"], [{"plugin": "contoh", "target": "transaction", "key": "proyek",
                                               "type": "text", "label": "Proyek"}])

    def test_kartu_tanpa_kode_tidak_ditawarkan(self):
        out = siklus.kontribusi([manifest_uji()], {})
        self.assertEqual(out["cards"], [])
        self.assertEqual([n["route"] for n in out["nav"]], ["/p/uji"])

    def test_tanpa_plugin_kosong(self):
        self.assertEqual(siklus.kontribusi([], {}), {"plugins": [], "nav": [], "quick_actions": [], "pages": [],
                                                     "cards": [], "form_fields": []})


# ── 2–4. HTTP ───────────────────────────────────────────────────────────
if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import func, select

    from app.api.routes import dashboard as dashboard_route
    from app.api.routes import plugins as plugins_route
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        AppSetting, Household, HouseholdMember, HouseholdRole, HouseholdType, PluginAuditLog, PluginInstallation, User,
    )
    from app.plugins.host.keadaan import pakai_sesi
    from app.services import ruang


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class H3HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        for ctx in (pakai_registry(registry_h3()), pakai_sesi(self.Session)):
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
                AppSetting(key="plugin_contoh_users", value="*"),
                AppSetting(key="plugin_uji_users", value="*"),
                AppSetting(key=ruang.FLAG_RUANG_USAHA, value="*"),
            ])
            for hid in (usaha.id, asing.id):
                db.add(PluginInstallation(household_id=hid, plugin_id="contoh", status="active",
                                          installed_by=pemilik.id, granted_permissions=list(sdk_uji.IZIN),
                                          settings={}))
            await db.commit()
        self.pemilik, self.admin, self.karyawan, self.orang = pemilik, admin, karyawan, orang
        self.usaha, self.usaha2, self.rumah, self.asing = usaha.id, usaha2.id, rumah.id, asing.id

        self.current = pemilik
        app = FastAPI()
        ruang.install(app)
        app.include_router(plugins_route.router, prefix="/plugins")
        app.include_router(plugins_route.ruang_router, prefix="/ruang")
        app.include_router(dashboard_route.router, prefix="/dashboard")

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

    async def kontribusi(self, hid=None, status=200):
        r = await self.client.get("/plugins/contributions", headers=self.hdr(hid) if hid is not False else {})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    async def set_setting(self, key, value):
        async with self.Session() as db:
            ada = await db.get(AppSetting, key)
            if ada:
                ada.value = value
            else:
                db.add(AppSetting(key=key, value=value))
            await db.commit()

    async def set_status(self, status, hid=None, plugin="contoh"):
        async with self.Session() as db:
            inst = (await db.execute(select(PluginInstallation).where(
                PluginInstallation.household_id == (hid or self.usaha),
                PluginInstallation.plugin_id == plugin))).scalar_one()
            inst.status = status
            await db.commit()

    async def pasang(self, izin=..., plugin="uji", hid=None):
        body = {} if izin is ... else {"izin": izin}
        return await self.client.post(f"/ruang/{hid or self.usaha}/plugins/{plugin}/pasang", json=body)

    async def instalasi(self, plugin="uji", hid=None):
        async with self.Session() as db:
            return (await db.execute(select(PluginInstallation).where(
                PluginInstallation.household_id == (hid or self.usaha),
                PluginInstallation.plugin_id == plugin))).scalar_one_or_none()

    async def audit(self, plugin="uji"):
        async with self.Session() as db:
            return [(a.action, a.detail) for a in (await db.execute(
                select(PluginAuditLog).where(PluginAuditLog.plugin_id == plugin)
                .order_by(PluginAuditLog.created_at))).scalars()]

    def kosong(self, out):
        self.assertEqual({k: v for k, v in out.items() if v}, {}, out)

    # ── 2. kontribusi ──
    async def test_kontribusi_pengelola(self):
        for user in (self.pemilik, self.admin):
            self.current = user
            out = await self.kontribusi()
            self.assertEqual([p["id"] for p in out["plugins"]], ["contoh"])
            self.assertEqual([(n["grup"], n["route"]) for n in out["nav"]],
                             [("usaha", "/p/contoh"), ("lainnya", "/p/contoh/laporan")])
            self.assertEqual([a["key"] for a in out["quick_actions"]], ["contoh.penjualan"])
            self.assertEqual([c["key"] for c in out["cards"]], ["contoh.kas", "contoh.rusak"])
            self.assertEqual(len(out["pages"]), 3)
            self.assertEqual([f["key"] for f in out["form_fields"]], ["proyek"])

    async def test_kontribusi_karyawan_ditolak(self):
        """Keputusan H3 B: karyawan tidak mendapat kontribusi plugin; route di luar `KARYAWAN_BOLEH`."""
        self.current = self.karyawan
        r = await self.client.get("/plugins/contributions", headers=self.hdr())
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["kode"], "khusus_admin")

    async def test_kontribusi_per_ruang(self):
        # Ruang keluarga (tanpa header) dan ruang usaha lain milik user yang sama tidak membawa plugin Dapur Nusa.
        self.kosong(await self.kontribusi(hid=False))
        self.kosong(await self.kontribusi(hid=self.rumah))
        self.kosong(await self.kontribusi(hid=self.usaha2))
        # Ruang orang lain lewat header: ditolak resolver, tidak pernah kontribusi ruang itu.
        r = await self.client.get("/plugins/contributions", headers=self.hdr(self.asing))
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["kode"], "ruang_tidak_diizinkan")

    async def test_kontribusi_hilang_saat_tidak_aktif(self):
        for status in ("paused", "installed", "uninstalled"):
            await self.set_status(status)
            self.kosong(await self.kontribusi())
        await self.set_status("active")
        self.assertTrue((await self.kontribusi())["nav"])
        await self.set_setting("plugin_saklar_darurat", "CONTOH")
        self.kosong(await self.kontribusi())
        await self.set_setting("plugin_saklar_darurat", "")
        await self.set_setting("plugin_contoh_users", str(self.admin.id))      # flag dicabut untuk pemilik
        self.kosong(await self.kontribusi())
        self.current = self.admin
        self.assertTrue((await self.kontribusi())["nav"])

    async def test_kontribusi_ruang_usaha_di_luar_flag(self):
        await self.set_setting(ruang.FLAG_RUANG_USAHA, "")
        r = await self.client.get("/plugins/contributions", headers=self.hdr())
        self.assertEqual(r.status_code, 403, r.text)

    # ── 3. persetujuan izin ──
    async def test_pasang_izin_sama_urutan_bebas(self):
        r = await self.pasang(["transactions:read", "incomes:read"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "aktif")
        self.assertEqual(sorted(r.json()["izin_diberikan"]), ["incomes:read", "transactions:read"])

    async def test_pasang_izin_berubah_ditolak(self):
        for izin in (["incomes:read"], ["incomes:read", "transactions:read", "envelopes:read"], []):
            r = await self.pasang(izin)
            self.assertEqual(r.status_code, 409, r.text)
            self.assertEqual(r.json()["kode"], "izin_berubah")
            self.assertIn("Muat ulang", r.json()["detail"])
        self.assertIsNone(await self.instalasi())
        self.assertEqual(await self.audit(), [])

    async def test_pasang_tanpa_field_izin_tetap_jalan(self):
        """Klien lama (API hanya bertambah): tanpa `izin`, izin manifest dicatat seperti H1."""
        r = await self.client.post(f"/ruang/{self.usaha}/plugins/uji/pasang")
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.pasang(plugin="uji", hid=self.usaha2)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_pulihkan_butuh_izin_terbaru(self):
        self.assertEqual((await self.pasang(["incomes:read", "transactions:read"])).status_code, 200)
        r = await self.client.post(f"/ruang/{self.usaha}/plugins/uji/copot")
        self.assertEqual(r.json()["status"], "arsip")
        # Rilis baru menambah izin; layar user masih menampilkan daftar lama.
        with pakai_registry(registry_h3(permissions=["incomes:read", "transactions:read", "envelopes:read"])):
            r = await self.pasang(["incomes:read", "transactions:read"])
            self.assertEqual(r.status_code, 409, r.text)
            self.assertEqual(r.json()["kode"], "izin_berubah")
            self.assertEqual((await self.instalasi()).status, "uninstalled")
            r = await self.pasang(["envelopes:read", "incomes:read", "transactions:read"])
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["status"], "aktif")
        aksi = [a for a, _ in await self.audit()]
        self.assertEqual(aksi, ["pasang", "copot", "pulihkan"])

    async def test_pasang_ulang_yang_aktif_tetap_idempoten(self):
        self.assertEqual((await self.pasang(["incomes:read", "transactions:read"])).status_code, 200)
        r = await self.pasang(["incomes:read"])        # sudah aktif: tidak ada persetujuan baru, tidak ada audit
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(await self.audit()), 1)

    async def test_izin_tidak_membocorkan_plugin_di_luar_flag(self):
        await self.set_setting("plugin_uji_users", "")
        r = await self.pasang(["salah"])
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(r.json()["kode"], "plugin_tidak_ada")

    async def test_izin_body_dibatasi(self):
        r = await self.pasang(["incomes:read"] * 41)
        self.assertEqual(r.status_code, 422, r.text)
        r = await self.pasang(["x" * 61])
        self.assertEqual(r.status_code, 422, r.text)
        async with self.Session() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(PluginInstallation)
                                               .where(PluginInstallation.plugin_id == "uji"))).scalar_one(), 0)

    async def test_karyawan_tidak_bisa_pasang(self):
        self.current = self.karyawan
        r = await self.pasang(["incomes:read", "transactions:read"])
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["kode"], "khusus_admin")

    # ── 4. katalog kartu Beranda ──
    async def kartu(self, hid=None, status=200):
        r = await self.client.get("/dashboard/cards", headers=self.hdr(hid) if hid is not False else {})
        self.assertEqual(r.status_code, status, r.text)
        return {c["key"]: c for c in r.json()}

    async def test_katalog_kartu_plugin(self):
        k = await self.kartu()
        self.assertEqual(k["contoh.kas"]["asal"], "contoh")
        self.assertEqual(k["contoh.kas"]["shape"], "kpi")
        self.assertIn("core.kpi.jatah", k)
        self.assertNotIn("uji.omzet", k)                     # tanpa kode kartu
        self.assertFalse(any(key.startswith("contoh.") for key in await self.kartu(hid=False)))
        self.assertFalse(any(key.startswith("contoh.") for key in await self.kartu(hid=self.usaha2)))

    async def test_katalog_kartu_karyawan_tanpa_plugin(self):
        self.current = self.karyawan
        k = await self.kartu()
        self.assertTrue(k)
        self.assertTrue(all(key.startswith("core.karyawan.") for key in k), sorted(k))

    async def test_katalog_kartu_plugin_dijeda(self):
        await self.set_status("paused")
        self.assertFalse(any(key.startswith("contoh.") for key in await self.kartu()))


if __name__ == "__main__":
    unittest.main()
