"""Plugin R4: daftar dan pembuatan ruang (`GET`/`POST /ruang`), flag `ruang_usaha_users` sebagai saklar.

Kontrak: docs/plugin/04-kontrak-api.md §2. Ruang usaha di luar flag tidak tampil, tidak bisa dibuat,
tidak bisa dibuka lewat header, dan objeknya tidak bisa ditulis. Ruang keluarga tidak terpengaruh.
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

if HAS_AIOSQLITE:
    import httpx
    from fastapi import FastAPI

    from app.api.routes import envelopes, household
    from app.api.routes import ruang as ruang_routes
    from app.core.database import Base, get_db
    from app.core.deps import get_current_user
    from app.models.models import (
        AppSetting, Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, PurposeType, User,
    )
    from app.services import ruang


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class RuangR4Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                          connect_args={"check_same_thread": False})
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.Session() as db:
            me = User(name="Yatno", payday_day=25, timezone="Asia/Jakarta", plan="pro")
            lain = User(name="Lain", payday_day=1, timezone="Asia/Jakarta", plan="pro")
            rumah, rumah_lain = Household(name="Rumah Yatno", payday_day=25), Household(name="Rumah Lain")
            db.add_all([me, lain, rumah, rumah_lain])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=me.id, household_id=rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=lain.id, household_id=rumah_lain.id, role=HouseholdRole.owner),
            ])
            await db.commit()
        self.me, self.lain, self.rumah_id = me, lain, rumah.id

        self.current = me
        app = FastAPI()
        ruang.install(app)
        app.include_router(ruang_routes.router, prefix="/ruang")
        app.include_router(envelopes.router, prefix="/envelopes")
        app.include_router(household.router, prefix="/household")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def _flag(self, value):
        from sqlalchemy import delete
        async with self.Session() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == ruang.FLAG_RUANG_USAHA))
            if value is not None:
                db.add(AppSetting(key=ruang.FLAG_RUANG_USAHA, value=value))
            await db.commit()

    async def _req(self, method, path, json=None, header=None, user=None):
        self.current = user or self.me
        headers = {ruang.RUANG_HEADER: str(header)} if header else {}
        return await self.client.request(method, path, json=json, headers=headers)

    async def _usaha_langsung(self, owner, nama="Dapur Nusa"):
        """Ruang usaha yang sudah ada di database (mis. dibuat saat flag terbuka, lalu flag dicabut)."""
        async with self.Session() as db:
            h = Household(name=nama, type=HouseholdType.USAHA, payday_day=1)
            db.add(h)
            await db.flush()
            db.add(HouseholdMember(user_id=owner.id, household_id=h.id, role=HouseholdRole.owner,
                                   created_at=datetime.now(timezone.utc) - timedelta(days=400)))
            env = Envelope(household_id=h.id, name="Bahan", budget_amount=100000, purpose=PurposeType.expense)
            db.add(env)
            await db.commit()
        return h.id, env.id

    # ── GET /ruang ─────────────────────────────────────────────────────
    async def test_tanpa_flag_hanya_ruang_keluarga(self):
        usaha_id, _ = await self._usaha_langsung(self.me)
        r = await self._req("GET", "/ruang")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["bawaan"], str(self.rumah_id))
        self.assertEqual([x["id"] for x in body["items"]], [str(self.rumah_id)])
        self.assertEqual(body["items"][0], {
            "id": str(self.rumah_id), "nama": "Rumah Yatno", "jenis": "rumah_tangga", "peran": "owner",
            "jumlah_anggota": 1, "paket": None, "jam_kerja": None,
        })
        self.assertFalse(body["boleh_buat_usaha"])
        self.assertNotIn(str(usaha_id), r.text)

    async def test_dengan_flag_ruang_keluarga_di_depan_lalu_usaha(self):
        await self._flag(str(self.me.id))
        usaha_id, _ = await self._usaha_langsung(self.me)   # keanggotaan lebih tua dari ruang keluarga
        body = (await self._req("GET", "/ruang")).json()
        self.assertEqual([(x["id"], x["jenis"]) for x in body["items"]],
                         [(str(self.rumah_id), "rumah_tangga"), (str(usaha_id), "usaha")])
        self.assertTrue(body["boleh_buat_usaha"])
        # Ruang usaha orang lain tidak pernah tampil.
        lain = (await self._req("GET", "/ruang", user=self.lain)).json()
        self.assertNotIn(str(usaha_id), str(lain))

    # ── POST /ruang ────────────────────────────────────────────────────
    async def test_buat_di_luar_flag_ditolak_tanpa_perubahan(self):
        from sqlalchemy import func, select
        r = await self._req("POST", "/ruang", {"nama": "Dapur Nusa"})
        self.assertEqual((r.status_code, r.json()["kode"]), (403, "ruang_usaha_belum_dibuka"))
        await self._flag(str(self.lain.id))   # flag untuk user lain tidak membuka untuk saya
        r = await self._req("POST", "/ruang", {"nama": "Dapur Nusa"})
        self.assertEqual(r.status_code, 403)
        async with self.Session() as db:
            n = (await db.execute(select(func.count(Household.id)).where(Household.type == HouseholdType.USAHA))).scalar()
        self.assertEqual(n, 0)

    async def test_buat_ruang_usaha(self):
        await self._flag("*")
        r = await self._req("POST", "/ruang", {"nama": "  Dapur   Nusa "})
        self.assertEqual(r.status_code, 201, r.text)
        item = r.json()
        self.assertEqual({k: item[k] for k in ("nama", "jenis", "peran", "jumlah_anggota", "paket")},
                         {"nama": "Dapur Nusa", "jenis": "usaha", "peran": "owner", "jumlah_anggota": 1, "paket": None})
        async with self.Session() as db:
            h = await db.get(Household, UUID(item["id"]))
            me = await db.get(User, self.me.id)
            rumah = await db.get(Household, self.rumah_id)
        self.assertEqual(h.type, HouseholdType.USAHA)
        self.assertIsNone(h.invite_code)                        # undangan ruang usaha baru di R5
        self.assertEqual(h.payday_day, 1)                       # bulan kalender (A2 butir 9), bukan gajian owner
        self.assertEqual((me.payday_day, rumah.payday_day), (25, 25))   # siklus ruang keluarga tidak berubah
        # Ruang baru langsung bisa dibuka lewat header, dan isinya kosong (tidak membawa amplop keluarga).
        r = await self._req("GET", "/envelopes/", header=item["id"])
        self.assertEqual((r.status_code, r.json()), (200, []))
        # Tanpa header tetap ruang keluarga.
        self.assertEqual((await self._req("GET", "/ruang")).json()["bawaan"], str(self.rumah_id))

    async def test_nama_divalidasi(self):
        await self._flag("*")
        for nama in ("", "   ", "x" * 61):
            r = await self._req("POST", "/ruang", {"nama": nama})
            self.assertEqual(r.status_code, 422, f"{nama!r}: {r.text}")
        r = await self._req("POST", "/ruang", {"nama": "x" * 60})
        self.assertEqual(r.status_code, 201, r.text)

    async def test_batas_ruang_usaha(self):
        await self._flag("*")
        for i in range(ruang_routes.MAKS_RUANG_USAHA):
            r = await self._req("POST", "/ruang", {"nama": f"Usaha {i}"})
            self.assertEqual(r.status_code, 201, r.text)
        r = await self._req("POST", "/ruang", {"nama": "Satu lagi"})
        self.assertEqual((r.status_code, r.json()["kode"]), (409, "batas_ruang_usaha"))
        self.assertFalse((await self._req("GET", "/ruang")).json()["boleh_buat_usaha"])
        # Batas per pemilik: user lain tetap bisa membuat.
        r = await self._req("POST", "/ruang", {"nama": "Toko Lain"}, user=self.lain)
        self.assertEqual(r.status_code, 201, r.text)

    async def test_undangan_dari_ruang_usaha_ditolak(self):
        await self._flag("*")
        usaha = (await self._req("POST", "/ruang", {"nama": "Dapur Nusa"})).json()["id"]
        r = await self._req("POST", "/household/invite", header=usaha)
        self.assertEqual((r.status_code, r.json().get("kode")), (403, "ruang_tidak_diizinkan"))

    # ── flag sebagai saklar ────────────────────────────────────────────
    async def test_flag_dicabut_ruang_usaha_tertutup(self):
        await self._flag(str(self.me.id))
        usaha_id, env_id = await self._usaha_langsung(self.me)
        r = await self._req("GET", "/envelopes/", header=usaha_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([e["name"] for e in r.json()], ["Bahan"])
        await self._flag(None)
        r = await self._req("GET", "/envelopes/", header=usaha_id)
        self.assertEqual((r.status_code, r.json().get("kode")), (403, "ruang_tidak_diizinkan"))
        r = await self._req("PUT", f"/envelopes/{env_id}", {"name": "Dibajak", "budget_amount": "1"})
        self.assertEqual(r.status_code, 404, r.text)          # tulis dari objek ikut tertutup
        async with self.Session() as db:
            self.assertEqual((await db.get(Envelope, env_id)).name, "Bahan")
        # Ruang keluarga tidak terpengaruh flag.
        r = await self._req("GET", "/envelopes/", header=self.rumah_id)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_hapus_akun_menghapus_ruang_usaha_miliknya_sendiri(self):
        from sqlalchemy import select
        from app.services import account_deletion
        await self._flag("*")
        usaha = (await self._req("POST", "/ruang", {"nama": "Dapur Nusa"})).json()["id"]
        async with self.Session() as db:
            me = await db.get(User, self.me.id)
            await account_deletion.delete_account(db, me)
        async with self.Session() as db:
            sisa = (await db.execute(select(Household.id).where(Household.id == UUID(usaha)))).scalar_one_or_none()
        self.assertIsNone(sisa)


if __name__ == "__main__":
    unittest.main()
