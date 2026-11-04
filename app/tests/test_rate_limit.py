"""Kunci batas frekuensi per user (`app/core/rate_limit.py`).

Dulu kuncinya sha256 dari teks header Authorization, jadi satu user mendapat ember baru dengan mengganti huruf
besar-kecil skema (`HTTPBearer` menerima "bearer" dan "BEARER"), menambah karakter yang diabaikan PyJWT
(`<token>!!!!` tetap lolos verifikasi), atau login ulang (token baru). Sekarang kuncinya user yang terautentikasi:
klaim `sub` dari access token yang sah; tanpa token yang sah, alamat IP.

Di sini: fungsi kuncinya (permintaan sintetis, token asli dari `create_access_token`), pendelegasian
`transactions.transcribe_key_func` dan `bot_chat.chat_key_func`, serta batas `/transactions/transcribe` (20/jam) dan
`/bot/chat/message` (60/menit) lewat HTTP dengan `get_current_user` yang asli (hanya `get_db` diganti).
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
from itertools import cycle, islice
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import configure_mappers
from starlette.requests import Request

from app.api.routes import bot_chat, transactions
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
BATAS_TRANSCRIBE = 20   # per jam: `@limiter.limit("20/hour")` di transactions.py
BATAS_CHAT = 60         # per menit: `@limiter.limit("60/minute")` di bot_chat.py (`/message`)


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
        # Tiap bentuk ini lolos get_current_user sebagai user yang sama.
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

    def test_chat_key_func_memakai_kunci_yang_sama_dengan_awalan_chat(self):
        t = self.token_ani
        for header in (None, f"Bearer {t}", f"bearer {t}!!!!", "Bearer tidak-sah", f"Basic {t}"):
            with self.subTest(header):
                self.assertEqual(
                    bot_chat.chat_key_func(permintaan(header)), "chat:" + kunci_per_user(permintaan(header)),
                )
        self.assertEqual(bot_chat.chat_key_func(permintaan(f"BEARER {t}!!")), f"chat:user:{self.ani}")
        # Tanpa token sah: alamat IP (tetap berawalan "chat:").
        self.assertEqual(bot_chat.chat_key_func(permintaan(None)), f"chat:{IP}")


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")   # diwarisi subkelas
class _BatasHttp(unittest.IsolatedAsyncioTestCase):
    """Dasar tes batas lewat HTTP: SQLite in-memory berisi dua user (Ani dan Budi), `get_current_user` yang asli
    (token asli, user dibaca dari database; hanya `get_db` diganti), limiter rute dikosongkan dan dinyalakan.
    Subkelas mengisi `router`, `prefix`, `limiter` dan mengganti pemroses permintaan di `siapkan_stub`, supaya
    yang diuji hanya autentikasi dan batas."""

    router = None
    prefix = ""
    limiter = None

    def siapkan_stub(self):
        raise NotImplementedError

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
        app.state.limiter = self.limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(self.router, prefix=self.prefix)

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db   # `get_current_user` yang asli: token asli, user dibaca dari database

        limiter = self.limiter
        self.addCleanup(setattr, limiter, "enabled", limiter.enabled)
        self.addCleanup(limiter.reset)
        limiter.reset()
        limiter.enabled = True
        self.siapkan_stub()

        self.klien = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.klien.aclose)


class TranscribeBatasTests(_BatasHttp):
    """`/transactions/transcribe` (20/jam) memakai `transcribe_key_func`."""

    router, prefix, limiter = transactions.router, "/transactions", transactions.limiter

    def siapkan_stub(self):
        proses = patch.object(transactions, "transcribe_audio", AsyncMock(return_value="kopi 35 ribu"))
        proses.start()
        self.addCleanup(proses.stop)

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
        for n in range(BATAS_TRANSCRIBE):
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
        # Ditolak get_current_user (401) sebelum batas diperiksa: tidak memakai ember siapa pun. Tiap bentuk dikirim
        # lebih sering daripada batasnya, jadi bila ada yang dihitung (ember alamat IP atau ember user yang diakui
        # token), panggilan ke-21 menjadi 429, bukan 401.
        sub = str(self.ani.id)
        tak_sah = {
            "tanpa header": None,
            "bukan token": "Bearer bukan-token",
            "refresh token user yang sah": f"Bearer {create_refresh_token(sub)}",
            "ditandatangani rahasia lain, mengaku user yang sah": f"Bearer {_tanda_tangani(_klaim(sub), RAHASIA_LAIN)}",
        }
        for nama, header in tak_sah.items():
            with self.subTest(nama):
                for n in range(BATAS_TRANSCRIBE + 1):
                    r = await self.transkripsi(header)
                    self.assertEqual(r.status_code, 401, f"panggilan ke-{n + 1}: {r.text}")
        # Tidak ada ember yang terpakai oleh semua itu: panggilan sah Ani tetap lolos.
        r = await self.transkripsi(f"Bearer {create_access_token(sub)}")
        self.assertEqual(r.status_code, 200, r.text)


class ChatBatasTests(_BatasHttp):
    """`/bot/chat/message` (60/menit) memakai `chat_key_func`: cacat yang sama dengan `/transcribe` sebelum kunci
    per user. Pemroses pesan (`run_message`) diganti stub."""

    router, prefix, limiter = bot_chat.router, "/bot/chat", bot_chat.limiter

    def siapkan_stub(self):
        self.run_message = AsyncMock(return_value=[])
        proses = patch.object(bot_chat, "run_message", self.run_message)
        proses.start()
        self.addCleanup(proses.stop)

    async def kirim(self, authorization: str | None):
        header = {} if authorization is None else {"Authorization": authorization}
        return await self.klien.post("/bot/chat/message", json={"text": "kopi 35k"}, headers=header)

    async def test_batas_chat_per_user_bukan_per_header(self):
        token = create_access_token(str(self.ani.id))
        async with self.Session() as db:
            login_ulang = (await auth_sessions.start_session(db, self.ani)).access_token
        self.assertNotEqual(login_ulang, token)
        varian = [
            f"Bearer {token}",
            f"bearer {token}",
            f"BEARER {token}",
            f"BeArEr {token}",
            f"Bearer {token}!!!!",          # sisa karakter yang diabaikan PyJWT
            f"Bearer {login_ulang}",         # token kedua user yang sama dari login lain
        ]
        # Satu user bergantian memakai semua bentuk header: tepat 60 jawaban, yang ke-61 ditolak.
        kode = [(await self.kirim(header)).status_code for header in islice(cycle(varian), BATAS_CHAT + 1)]
        self.assertEqual(kode, [200] * BATAS_CHAT + [429])
        self.assertEqual(self.run_message.await_count, BATAS_CHAT)   # yang ditolak tidak sampai ke pemroses pesan
        # User lain, ember sendiri.
        r = await self.kirim(f"Bearer {create_access_token(str(self.budi.id))}")
        self.assertEqual(r.status_code, 200, r.text)


class SaranBatasTests(_BatasHttp):
    """Saran amplop (Plugin R7, review keamanan PR #191 temuan 2): `/transactions/suggest-envelope` 60/menit dan
    `/suggest-envelopes` 20/menit per user, supaya kamus ruang tidak bisa disisir sekaligus. Ani dan Budi tanpa
    household: route menjawab kosong, yang diuji hanya batasnya."""

    router, prefix, limiter = transactions.router, "/transactions", transactions.limiter

    def siapkan_stub(self):
        pass

    async def test_batas_saran_per_user(self):
        ani = {"Authorization": f"Bearer {create_access_token(str(self.ani.id))}"}
        budi = {"Authorization": f"Bearer {create_access_token(str(self.budi.id))}"}
        for path, body, batas in (("/transactions/suggest-envelope", {"description": "kopi"}, 60),
                                  ("/transactions/suggest-envelopes", {"descriptions": ["kopi"]}, 20)):
            with self.subTest(path=path):
                kode = [(await self.klien.post(path, json=body, headers=ani)).status_code for _ in range(batas + 1)]
                self.assertEqual(kode, [200] * batas + [429])
                self.assertEqual((await self.klien.post(path, json=body, headers=budi)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
