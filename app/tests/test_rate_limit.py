"""Kunci batas frekuensi per user (ruling R11, `app/core/rate_limit.py`).

Sebelum R11 kuncinya sha256 dari teks header Authorization, jadi satu user mendapat ember baru dengan mengganti huruf
besar-kecil skema (`HTTPBearer` menerima "bearer" dan "BEARER"), menambah karakter yang diabaikan PyJWT
(`<token>!!!!` tetap lolos verifikasi), atau login ulang (token baru). Sekarang kuncinya user yang terautentikasi:
klaim `sub` dari access token yang sah; tanpa token yang sah, alamat IP.

Di sini: fungsi kuncinya (permintaan sintetis, token asli dari `create_access_token`), pendelegasian
`transactions.transcribe_key_func`, dan batas `/transactions/transcribe` lewat HTTP dengan `get_current_user` yang asli
(hanya `get_db` diganti). Batas laporan: app/tests/test_laporan_api.py (`BatasFrekuensiTests`).
Bagian HTTP butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_rate_limit -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import logging
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import configure_mappers
from starlette.requests import Request

from app.api.routes import transactions
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.rate_limit import kunci_per_user
from app.core.security import create_access_token, create_refresh_token
from app.models.models import User
from app.services import auth_sessions

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
settings = get_settings()

IP = "203.0.113.7"
RAHASIA_LAIN = "rahasia-lain-yang-cukup-panjang-untuk-hs256-32+"   # bukan JWT_SECRET server


def permintaan(authorization: str | None = None, ip: str | None = IP) -> Request:
    """Permintaan sintetis dengan yang dibaca fungsi kunci saja: header Authorization dan alamat klien."""
    header = [] if authorization is None else [(b"authorization", authorization.encode("latin-1"))]
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": header, "client": None if ip is None else (ip, 40000),
    })


def _klaim(sub, jenis="access", **lain) -> dict:
    return {"sub": sub, "type": jenis, "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **lain}


def _tanda_tangani(klaim: dict, rahasia: str | None = None) -> str:
    return jwt.encode(klaim, rahasia or settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class KunciPerUserTests(unittest.TestCase):
    def setUp(self):
        self.ani, self.budi = uuid.uuid4(), uuid.uuid4()
        self.token_ani = create_access_token(str(self.ani))   # tanpa sid (token lama), masih diterima get_current_user
        self.token_budi = create_access_token(str(self.budi))

    def test_access_token_sah_memberi_kunci_user(self):
        self.assertEqual(kunci_per_user(permintaan(f"Bearer {self.token_ani}")), f"user:{self.ani}")
        self.assertEqual(kunci_per_user(permintaan(f"Bearer {self.token_budi}")), f"user:{self.budi}")

    def test_semua_bentuk_header_user_yang_sama_satu_kunci(self):
        # Persis yang dilaporkan review: tiap bentuk ini lolos get_current_user sebagai user yang sama.
        login_ulang = create_access_token(str(self.ani), sid=str(uuid.uuid4()))   # sesi dan token baru
        self.assertNotEqual(login_ulang, self.token_ani)
        t = self.token_ani
        varian = {
            "skema kecil": f"bearer {t}",
            "skema besar": f"BEARER {t}",
            "skema campur": f"BeArEr {t}",
            "sisa karakter yang diabaikan PyJWT": f"Bearer {t}!!!!",
            "token dari login ulang": f"Bearer {login_ulang}",
            "login ulang, skema besar dan sisa": f"BEARER {login_ulang}!!",
        }
        for nama, header in varian.items():
            with self.subTest(nama):
                self.assertEqual(kunci_per_user(permintaan(header)), f"user:{self.ani}")

    def test_user_berbeda_kunci_berbeda_dan_alamat_ip_tidak_menentukan(self):
        header_ani, header_budi = f"Bearer {self.token_ani}", f"Bearer {self.token_budi}"
        self.assertNotEqual(kunci_per_user(permintaan(header_ani)), kunci_per_user(permintaan(header_budi)))
        # Identitas, bukan lokasi: user yang sama dari dua alamat berbagi kunci; dua user dari satu alamat tidak.
        self.assertEqual(
            kunci_per_user(permintaan(header_ani, ip="198.51.100.1")),
            kunci_per_user(permintaan(header_ani, ip="192.0.2.99")),
        )

    def test_tanpa_token_sah_jatuh_ke_alamat_ip(self):
        t = self.token_ani
        sekarang = datetime.now(timezone.utc)
        sub = str(self.ani)
        token_lain = {
            "ditandatangani rahasia lain": _tanda_tangani(_klaim(sub), RAHASIA_LAIN),
            "tanpa tanda tangan (alg none), mengaku user lain": jwt.encode(_klaim(sub), None, algorithm="none"),
            "kedaluwarsa": _tanda_tangani(_klaim(sub, exp=sekarang - timedelta(minutes=1))),
            "belum berlaku": _tanda_tangani(_klaim(sub, nbf=sekarang + timedelta(hours=1))),
            "refresh token": create_refresh_token(sub),
            "tanpa klaim type": _tanda_tangani({"sub": sub, "exp": sekarang + timedelta(minutes=5)}),
            "tanpa klaim sub": _tanda_tangani({"type": "access", "exp": sekarang + timedelta(minutes=5)}),
            "sub kosong": _tanda_tangani(_klaim("")),
        }
        kasus = {
            "tanpa header": None,
            "header kosong": "",
            "hanya skema": "Bearer",
            "skema dan spasi saja": "Bearer ",
            "skema lain": f"Basic {t}",
            "skema tidak dikenal": f"Token {t}",
            "bukan JWT": "Bearer bukan-token",
            "tiga bagian tak sah": "Bearer a.b.c",
            **{nama: f"Bearer {token}" for nama, token in token_lain.items()},
        }
        for nama, header in kasus.items():
            with self.subTest(nama):
                self.assertEqual(kunci_per_user(permintaan(header)), IP)

    def test_alamat_klien_tidak_diketahui_tetap_menghasilkan_kunci_tak_kosong(self):
        # slowapi melewatkan batas bila kuncinya kosong; cadangannya tidak boleh kosong.
        kunci = kunci_per_user(permintaan(None, ip=None))
        self.assertTrue(kunci)

    def test_tidak_mencatat_log_dan_kunci_tidak_memuat_token(self):
        kedaluwarsa = _tanda_tangani(_klaim(str(self.ani), exp=datetime.now(timezone.utc) - timedelta(minutes=1)))
        with self.assertNoLogs(level=logging.DEBUG):
            for token in (self.token_ani, kedaluwarsa, "rahasia-bukan-token"):
                self.assertNotIn(token, kunci_per_user(permintaan(f"Bearer {token}")))

    def test_transcribe_key_func_memakai_kunci_yang_sama(self):
        t = self.token_ani
        for header in (None, f"Bearer {t}", f"bearer {t}!!!!", "Bearer tidak-sah", f"Basic {t}"):
            with self.subTest(header):
                self.assertEqual(
                    transactions.transcribe_key_func(permintaan(header)), kunci_per_user(permintaan(header)),
                )
        self.assertEqual(
            transactions.transcribe_key_func(permintaan(f"BEARER {t}!!")), f"user:{self.ani}",
        )


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class TranscribeBatasTests(unittest.IsolatedAsyncioTestCase):
    """`/transactions/transcribe` (20/jam) memakai `transcribe_key_func`: cacat yang sama ada di sana sebelum R11."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.Session() as db:
            self.ani = User(name="Ani", email="ani@example.com")
            self.budi = User(name="Budi", email="budi@example.com")
            db.add_all([self.ani, self.budi])
            await db.commit()

        app = FastAPI()
        app.state.limiter = transactions.limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(transactions.router, prefix="/transactions")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db   # `get_current_user` yang asli: token asli, user dibaca dari database

        limiter = transactions.limiter
        self.addCleanup(setattr, limiter, "enabled", limiter.enabled)
        self.addCleanup(limiter.reset)
        limiter.reset()
        limiter.enabled = True
        proses = patch.object(transactions, "transcribe_audio", AsyncMock(return_value="kopi 35 ribu"))
        proses.start()
        self.addCleanup(proses.stop)

        self.klien = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.klien.aclose)

    async def transkripsi(self, authorization: str | None):
        header = {} if authorization is None else {"Authorization": authorization}
        return await self.klien.post(
            "/transactions/transcribe", files={"audio": ("rekaman.webm", b"bunyi", "audio/webm")}, headers=header,
        )

    async def test_batas_transcribe_per_user_bukan_per_header(self):
        token = create_access_token(str(self.ani.id))
        async with self.Session() as db:
            login_ulang = (await auth_sessions.start_session(db, self.ani)).access_token
        self.assertNotEqual(login_ulang, token)
        for n in range(20):
            r = await self.transkripsi(f"Bearer {token}")
            self.assertEqual(r.status_code, 200, f"panggilan ke-{n + 1}: {r.text}")
        varian = {
            "skema kecil": f"bearer {token}",
            "skema besar": f"BEARER {token}",
            "sisa karakter yang diabaikan PyJWT": f"Bearer {token}!!!!",
            "token dari login ulang": f"Bearer {login_ulang}",
            "asli lagi": f"Bearer {token}",
        }
        for nama, header in varian.items():
            with self.subTest(nama):
                r = await self.transkripsi(header)
                self.assertEqual(r.status_code, 429, r.text)
        # User lain, ember sendiri.
        r = await self.transkripsi(f"Bearer {create_access_token(str(self.budi.id))}")
        self.assertEqual(r.status_code, 200, r.text)

    async def test_permintaan_tanpa_token_sah_ditolak_sebelum_dihitung(self):
        # Ditolak get_current_user (401) sebelum batas diperiksa: tidak memakai ember siapa pun.
        for header in (None, "Bearer bukan-token", f"Bearer {create_refresh_token(str(self.ani.id))}"):
            with self.subTest(header):
                self.assertEqual((await self.transkripsi(header)).status_code, 401)
        r = await self.transkripsi(f"Bearer {create_access_token(str(self.ani.id))}")
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
