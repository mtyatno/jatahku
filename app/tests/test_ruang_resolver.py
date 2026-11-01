"""Plugin R2 — penentu ruang (`app/services/ruang.py`).

Mengunci (docs/plugin/04-kontrak-api.md §1, AGENTS.md "Plugin dan ruang" aturan 1–2):
- Tanpa header → ruang keluarga user (household `rumah_tangga`), walau user juga anggota ruang usaha.
- Header UUID ruang milik user → ruang itu (hanya untuk membaca).
- Header ruang orang lain, bukan UUID → 403 `ruang_tidak_diizinkan`; tidak pernah jatuh diam-diam ke ruang lain.
- Menulis (sampai R3): selalu ruang keluarga; header yang menunjuk ruang lain ditolak.

Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_ruang_resolver -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    import httpx
    from fastapi import Depends, FastAPI

    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import Household, HouseholdMember, HouseholdRole, HouseholdType, User
    from app.services import ruang


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangResolverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        lalu = datetime.now(timezone.utc) - timedelta(days=30)
        async with self.Session() as db:
            self.me, self.orang, self.tanpa = User(name="Saya"), User(name="Orang"), User(name="Tanpa")
            self.rumah = Household(name="Rumah")
            self.usaha = Household(name="Dapur Nusa", type=HouseholdType.USAHA)
            self.asing = Household(name="Rumah orang")
            db.add_all([self.me, self.orang, self.tanpa, self.rumah, self.usaha, self.asing])
            await db.flush()
            db.add_all([
                # Keanggotaan usaha dibuat LEBIH DULU: ruang keluarga tidak boleh ditentukan urutan.
                HouseholdMember(user_id=self.me.id, household_id=self.usaha.id, role=HouseholdRole.owner,
                                created_at=lalu),
                HouseholdMember(user_id=self.me.id, household_id=self.rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.orang.id, household_id=self.asing.id, role=HouseholdRole.owner),
            ])
            await db.commit()

        self.current = self.me
        app = FastAPI()
        ruang.install(app)

        @app.get("/baca")
        async def baca(hid=Depends(ruang.ruang_aktif)):
            return {"hid": str(hid) if hid else None}

        @app.post("/tulis")
        async def tulis(hid=Depends(ruang.ruang_tulis)):
            return {"hid": str(hid) if hid else None}

        @app.post("/baca-post")
        async def baca_post(hid=Depends(ruang.ruang_aktif)):
            return {"hid": str(hid) if hid else None}

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def get(self, path="/baca", header=None, method="get"):
        headers = {ruang.RUANG_HEADER: header} if header is not None else {}
        return await getattr(self.client, method)(path, headers=headers)

    # ── fungsi langsung ─────────────────────────────────────────────────
    async def test_ruang_keluarga_abaikan_ruang_usaha(self):
        async with self.Session() as db:
            self.assertEqual(await ruang.ruang_keluarga(self.me, db), self.rumah.id)
            self.assertEqual(await ruang.ruang_keluarga(self.orang, db), self.asing.id)
            self.assertIsNone(await ruang.ruang_keluarga(self.tanpa, db))

    async def test_keanggotaan(self):
        async with self.Session() as db:
            m = await ruang.keanggotaan(db, self.me.id, self.usaha.id)
            self.assertEqual(str(m.role.value if hasattr(m.role, "value") else m.role), "owner")
            self.assertIsNone(await ruang.keanggotaan(db, self.me.id, self.asing.id))

    # ── membaca ─────────────────────────────────────────────────────────
    async def test_tanpa_header_ruang_keluarga(self):
        r = await self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["hid"], str(self.rumah.id))

    async def test_header_kosong_sama_dengan_tanpa_header(self):
        r = await self.get(header="  ")
        self.assertEqual(r.json()["hid"], str(self.rumah.id))

    async def test_header_ruang_sendiri(self):
        for hh in (self.usaha, self.rumah):
            r = await self.get(header=str(hh.id))
            self.assertEqual((r.status_code, r.json()["hid"]), (200, str(hh.id)))

    async def test_header_ruang_orang_lain_403(self):
        r = await self.get(header=str(self.asing.id))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["kode"], "ruang_tidak_diizinkan")
        self.assertIsInstance(r.json()["detail"], str)

    async def test_header_bukan_uuid_403(self):
        for raw in ("bukan-uuid", "1 OR 1=1", "00000000-0000-0000-0000-000000000000"):
            r = await self.get(header=raw)
            self.assertEqual((r.status_code, r.json()["kode"]), (403, "ruang_tidak_diizinkan"), raw)

    async def test_user_tanpa_household(self):
        self.current = self.tanpa
        self.assertEqual((await self.get()).json()["hid"], None)
        r = await self.get(header=str(self.rumah.id))
        self.assertEqual(r.status_code, 403)

    async def test_post_baca_tetap_memakai_header(self):
        # POST yang membaca (mis. /dashboard/data) memakai ruang_aktif, bukan ruang_tulis.
        r = await self.get("/baca-post", header=str(self.usaha.id), method="post")
        self.assertEqual(r.json()["hid"], str(self.usaha.id))

    # ── menulis (sampai R3) ─────────────────────────────────────────────
    async def test_tulis_selalu_ruang_keluarga(self):
        r = await self.get("/tulis", method="post")
        self.assertEqual(r.json()["hid"], str(self.rumah.id))
        r = await self.get("/tulis", header=str(self.rumah.id), method="post")
        self.assertEqual(r.json()["hid"], str(self.rumah.id))

    async def test_tulis_dengan_header_ruang_lain_ditolak(self):
        for raw in (str(self.usaha.id), str(self.asing.id), "bukan-uuid"):
            r = await self.get("/tulis", header=raw, method="post")
            self.assertEqual((r.status_code, r.json()["kode"]), (403, "ruang_tidak_diizinkan"), raw)

    async def test_tanpa_install_tetap_403_teks(self):
        # Aplikasi tanpa handler (mis. app tes lain) tetap menjawab 403 dengan detail teks.
        app = FastAPI()

        @app.get("/baca")
        async def baca(hid=Depends(ruang.ruang_aktif)):
            return {"hid": str(hid)}

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.me
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/baca", headers={ruang.RUANG_HEADER: str(self.asing.id)})
        self.assertEqual(r.status_code, 403)
        self.assertIsInstance(r.json()["detail"], str)


if __name__ == "__main__":
    unittest.main()
