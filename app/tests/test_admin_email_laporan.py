"""Worker email laporan, Task 5: GET /admin/email-laporan (spec 2026-11-11-worker-email-laporan bagian 6).
SQLite berkas per tes; Redis dipalsukan (tidak pernah menghubungi jaringan).
Run: python -m unittest app.tests.test_admin_email_laporan -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.orm import configure_mappers

from app.api.routes import admin as admin_routes
from app.core.database import Base
from app.core.deps import require_admin
from app.models.models import Report, User
from app.services.laporan import antrean_email, pantau_email, worker_email

configure_mappers()

KUNCI = {"worker_hidup", "worker_terakhir", "menunggu", "tertua_menit", "mengirim", "terkirim_24_jam",
         "gagal_7_hari", "penerima", "ambang_penerima", "smtp_lokal", "laju_per_detik", "alarm"}
ALAMAT = "rahasia.penerima@contoh.id"


class RedisPalsu:
    def __init__(self, nilai=None):
        self.nilai = nilai
        self.ditutup = False

    async def get(self, kunci):
        return self.nilai

    async def aclose(self):
        self.ditutup = True


class EndpointEmailLaporanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(folder) / 'admin.db'}", poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.enterContext(patch.object(
            pantau_email, "get_settings", return_value=SimpleNamespace(SMTP_HOST="localhost", EMAIL_LAPORAN_PER_DETIK="3")))
        self.enterContext(patch.object(
            admin_routes, "get_settings", return_value=SimpleNamespace(REDIS_URL="redis://tidak-ada:6379/0")))
        # Alarm tidak boleh menyentuh Telegram atau waktu tenang; hanya dibaca.
        async with self.Session() as db:
            u = User(name="U", email=ALAMAT)
            u.email_verified_at = datetime.now(timezone.utc) - timedelta(days=30)
            db.add(u)
            await db.flush()
            db.add(Report(
                user_id=u.id, household_id=None, jenis="bulanan", periode_mulai=datetime(2020, 1, 1).date(),
                periode_akhir=datetime(2020, 1, 31).date(), payday_day=1, data={},
                terbit_at=datetime.now(timezone.utc) - timedelta(hours=7, minutes=5),
                email_status=antrean_email.STATUS_MENUNGGU))
            await db.commit()

    async def panggil(self, redis_dari_url):
        with patch.object(admin_routes.aioredis, "from_url", redis_dari_url):
            async with self.Session() as db:
                return await admin_routes.admin_email_laporan(admin=MagicMock(is_admin=True), db=db)

    async def test_non_admin_ditolak_403(self):
        with self.assertRaises(HTTPException) as ctx:
            await require_admin(user=MagicMock(is_admin=False))
        self.assertEqual(ctx.exception.status_code, 403)
        rute = [r for r in admin_routes.router.routes if getattr(r, "path", "") == "/email-laporan"]
        self.assertEqual(len(rute), 1)
        self.assertIn("GET", rute[0].methods)
        self.assertIn(require_admin, [d.call for d in rute[0].dependant.dependencies])

    async def test_admin_200_semua_kunci_tanpa_alamat(self):
        r = RedisPalsu(datetime.now(timezone.utc).isoformat().encode())
        hasil = await self.panggil(MagicMock(return_value=r))
        self.assertEqual(set(hasil), KUNCI)
        self.assertTrue(hasil["worker_hidup"])
        self.assertEqual(hasil["menunggu"], 1)
        self.assertGreaterEqual(hasil["tertua_menit"], 425)
        self.assertIsInstance(hasil["alarm"], list)
        self.assertIn("antrean_tersendat", hasil["alarm"])
        teks = json.dumps(hasil)
        self.assertNotIn("@", teks)
        self.assertNotIn(ALAMAT, teks)
        self.assertTrue(r.ditutup)

    async def test_redis_mati_tetap_200(self):
        hasil = await self.panggil(MagicMock(side_effect=RuntimeError("redis mati")))
        self.assertEqual(set(hasil), KUNCI)
        self.assertFalse(hasil["worker_hidup"])
        self.assertIsNone(hasil["worker_terakhir"])
        self.assertIn("worker_mati", hasil["alarm"])

    async def test_redis_gagal_dibaca_tetap_200_dan_ditutup(self):
        r = RedisPalsu()
        r.get = AsyncMock(side_effect=ConnectionError("putus"))
        hasil = await self.panggil(MagicMock(return_value=r))
        self.assertFalse(hasil["worker_hidup"])
        self.assertTrue(r.ditutup)


if __name__ == "__main__":
    unittest.main()
