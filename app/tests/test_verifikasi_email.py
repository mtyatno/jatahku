"""Laporan berkala tahap 2, Task 1: penjaga verifikasi email dan token bertujuan.

`users.email_verified_at` dikosongkan oleh event ORM pada `User.email` bila alamat berganti, lewat setiap jalur
penulis yang nyata (route asli, HTTP httpx + SQLite in-memory, token akses asli); Google mengisinya sesudah email
diisi; token bertujuan tidak pernah lolos sebagai access/refresh.
Tes yang memakai database butuh `aiosqlite` dan dilewati bila tidak ada; tes normalisasi, token, dan pagar tetap jalan.
Run: python -m unittest app.tests.test_verifikasi_email -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpx
import jwt
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import configure_mappers

from app.api.routes import admin as admin_route, auth as auth_route, link as link_route, user_settings
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import (
    create_access_token, create_purpose_token, create_refresh_token, decode_purpose_token,
)
from app.models.models import Household, HouseholdMember, HouseholdRole, User, email_normal
from app.services import verifikasi_email as ve

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
TERVERIFIKASI = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)
SANDI = "rahasia123"


def _verify(plain, hashed):
    return hashed == "fake$" + plain


def _hash(plain):
    return "fake$" + plain


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class DasarVerifikasi(unittest.IsolatedAsyncioTestCase):
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
            self.ani = await self.buat(db, "Ani", "ani@example.com", password_hash="fake$" + SANDI)
            self.admin = await self.buat(db, "Admin", "admin@example.com", is_admin=True)
            self.korban = await self.buat(db, "Korban", "korban@example.com")
            await db.commit()

        app = FastAPI()
        app.state.limiter = auth_route.limiter
        app.include_router(auth_route.router, prefix="/auth")
        app.include_router(link_route.router, prefix="/auth")
        app.include_router(user_settings.router, prefix="/user")
        app.include_router(admin_route.router, prefix="/admin")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        limiter = auth_route.limiter
        self.addCleanup(setattr, limiter, "enabled", limiter.enabled)
        limiter.enabled = False
        for mod in (auth_route, user_settings, link_route):
            for nama, palsu in (("verify_password", _verify), ("hash_password", _hash)):
                if hasattr(mod, nama):
                    p = patch.object(mod, nama, palsu)
                    p.start()
                    self.addCleanup(p.stop)
        self.klien = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.klien.aclose)

    async def buat(self, db, nama, email, terverifikasi=True, **kw):
        user = User(name=nama, email=email, **kw)   # tidak pernah email_verified_at di konstruktor
        if email and terverifikasi:
            user.email_verified_at = TERVERIFIKASI
        db.add(user)
        await db.flush()
        db.add(HouseholdMember(user_id=user.id, household_id=(await self._rumah(db, nama)).id,
                               role=HouseholdRole.owner))
        await db.flush()
        return user

    async def _rumah(self, db, nama):
        rumah = Household(name=f"Rumah {nama}")
        db.add(rumah)
        await db.flush()
        return rumah

    async def baca(self, user_id=None, email=None) -> User:
        async with self.Session() as db:
            q = select(User).where(User.id == user_id) if user_id else select(User).where(User.email == email)
            return (await db.execute(q)).scalar_one()

    @staticmethod
    def masuk(user) -> dict:
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


class NormalisasiTests(unittest.TestCase):
    def test_email_normal_dan_sama_email(self):
        self.assertEqual(email_normal("  Ani@X.id "), "ani@x.id")
        self.assertEqual(email_normal(None), "")
        self.assertTrue(ve.sama_email("Ani@X.id", " ani@x.id"))
        self.assertFalse(ve.sama_email(None, "a@x.id"))
        self.assertFalse(ve.sama_email("a@x.id", None))
        self.assertFalse(ve.sama_email("", ""))
        self.assertFalse(ve.sama_email(None, None))
        self.assertFalse(ve.sama_email("a@x.id", "b@x.id"))

    def test_tandai_terverifikasi_hanya_bila_null(self):
        user = SimpleNamespace(email_verified_at=None)
        awal = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ve.tandai_terverifikasi(user, awal)
        ve.tandai_terverifikasi(user, awal + timedelta(days=1))
        self.assertEqual(user.email_verified_at, awal)
        lain = SimpleNamespace(email_verified_at=None)
        ve.tandai_terverifikasi(lain)
        self.assertIsNotNone(lain.email_verified_at)


class EventTests(DasarVerifikasi):
    async def test_ganti_email_mengosongkan_verifikasi(self):
        async with self.Session() as db:
            user = await db.get(User, self.ani.id)
            self.assertIsNotNone(user.email_verified_at)
            user.email = "baru@x.id"
            await db.flush()
            self.assertIsNone(user.email_verified_at)

    async def test_email_sama_beda_huruf_tidak_mengosongkan(self):
        async with self.Session() as db:
            user = User(name="Huruf", email="Ani@X.id")
            db.add(user)
            await db.flush()
            user.email_verified_at = TERVERIFIKASI
            await db.flush()
            user.email = "ani@x.id "
            await db.flush()
            self.assertEqual(user.email_verified_at, TERVERIFIKASI)

    async def test_email_diisi_untuk_akun_tanpa_email_mengosongkan(self):
        async with self.Session() as db:
            user = User(name="Tg", telegram_id="1")
            db.add(user)
            await db.flush()
            user.email_verified_at = TERVERIFIKASI   # sisa yang tidak sah
            user.email = "tg@x.id"
            await db.flush()
            self.assertIsNone(user.email_verified_at)


class JalurPenulisTests(DasarVerifikasi):
    async def test_put_user_email(self):
        r = await self.klien.put("/user/email", json={"new_email": "baru@example.com", "password": SANDI},
                                 headers=self.masuk(self.ani))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(self.ani.id)
        self.assertEqual(user.email, "baru@example.com")
        self.assertIsNone(user.email_verified_at)

    async def test_put_user_email_beda_huruf_saja_tidak_mengosongkan(self):
        r = await self.klien.put("/user/email", json={"new_email": "ANI@example.com", "password": SANDI},
                                 headers=self.masuk(self.ani))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone((await self.baca(self.ani.id)).email_verified_at)

    async def test_reset_data_yang_mengisi_email(self):
        with patch("app.services.email_service.send_data_backup_email", return_value=False):
            r = await self.klien.post("/user/reset", json={"email": "reset@example.com"},
                                      headers=self.masuk(self.ani))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(self.ani.id)
        self.assertEqual(user.email, "reset@example.com")
        self.assertIsNone(user.email_verified_at)

    async def test_telegram_mengisi_email(self):
        async with self.Session() as db:
            tg = User(name="Tg", telegram_id="777")
            db.add(tg)
            await db.flush()
            tg.email_verified_at = TERVERIFIKASI   # sisa yang tidak sah pun harus bersih
            await db.commit()
        redis = MagicMock(get=AsyncMock(return_value=b"777"), delete=AsyncMock(), close=AsyncMock())
        with patch.object(link_route, "_redis", AsyncMock(return_value=redis)):
            r = await self.klien.post("/auth/link/claim-telegram", json={
                "code": "ABC123", "email": "tg@example.com", "password": SANDI,
            })
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(email="tg@example.com")
        self.assertIsNone(user.email_verified_at)

    async def test_admin_larang(self):
        r = await self.klien.post(f"/admin/users/{self.korban.id}/action", json={"action": "ban"},
                                  headers=self.masuk(self.admin))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(self.korban.id)
        self.assertTrue(user.email.startswith("banned_"))
        self.assertIsNone(user.email_verified_at)

    async def test_register_tidak_terverifikasi(self):
        r = await self.klien.post("/auth/register", json={
            "email": "Baru@Example.com", "password": SANDI, "name": "Baru",
        })
        self.assertEqual(r.status_code, 201, r.text)
        user = await self.baca(email="baru@example.com")
        self.assertIsNone(user.email_verified_at)


class GoogleTests(DasarVerifikasi):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for p in (
            patch.object(auth_route, "get_settings", return_value=SimpleNamespace(GOOGLE_CLIENT_ID="cid")),
            patch.object(auth_route, "_notify_admin_new_user", AsyncMock()),
        ):
            p.start()
            self.addCleanup(p.stop)

    def google(self, **klaim):
        isi = {"sub": "g-1", "email": "budi@example.com", "name": "Budi", **klaim}
        return patch.object(auth_route, "verify_google_credential", AsyncMock(return_value=isi))

    async def test_google_daftar_baru_terverifikasi(self):
        with self.google():
            r = await self.klien.post("/auth/google", json={"credential": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone((await self.baca(email="budi@example.com")).email_verified_at)

    async def test_google_email_terdaftar_terverifikasi(self):
        async with self.Session() as db:
            await self.buat(db, "Budi", "budi@example.com", terverifikasi=False)
            await db.commit()
        with self.google(email="Budi@Example.com".lower()):
            r = await self.klien.post("/auth/google", json={"credential": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(email="budi@example.com")
        self.assertEqual(user.google_id, "g-1")
        self.assertIsNotNone(user.email_verified_at)

    async def test_google_id_dengan_email_sama_terverifikasi(self):
        async with self.Session() as db:
            await self.buat(db, "Budi", "budi@example.com", terverifikasi=False, google_id="g-1")
            await db.commit()
        with self.google():
            r = await self.klien.post("/auth/google", json={"credential": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone((await self.baca(email="budi@example.com")).email_verified_at)

    async def test_google_id_dengan_email_beda_tidak_memverifikasi(self):
        async with self.Session() as db:
            await self.buat(db, "Budi", "lama@example.com", terverifikasi=False, google_id="g-1")
            await db.commit()
        with self.google():   # akun Google berganti email: alamat di Jatahku tidak ikut terverifikasi
            r = await self.klien.post("/auth/google", json={"credential": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone((await self.baca(email="lama@example.com")).email_verified_at)

    async def test_google_link_mengisi_email_terverifikasi(self):
        async with self.Session() as db:
            tanpa = User(name="Tanpa", telegram_id="9")
            db.add(tanpa)
            await db.commit()
        with self.google():
            r = await self.klien.post("/auth/google/link", json={"credential": "x"}, headers=self.masuk(tanpa))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(tanpa.id)
        self.assertEqual(user.email, "budi@example.com")
        self.assertIsNotNone(user.email_verified_at)

    async def test_google_link_email_beda_tidak_mengubah(self):
        with self.google():   # Ani sudah punya email lain
            r = await self.klien.post("/auth/google/link", json={"credential": "x"}, headers=self.masuk(self.ani))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(self.ani.id)
        self.assertEqual(user.email, "ani@example.com")
        self.assertEqual(user.email_verified_at, TERVERIFIKASI.replace(tzinfo=None)
                         if user.email_verified_at.tzinfo is None else TERVERIFIKASI)

    async def test_google_link_email_beda_belum_terverifikasi_tetap_tidak(self):
        async with self.Session() as db:
            u = await self.buat(db, "Lama", "lama@example.com", terverifikasi=False)
            await db.commit()
        with self.google():   # Google membawa budi@example.com, akun memegang lama@example.com
            r = await self.klien.post("/auth/google/link", json={"credential": "x"}, headers=self.masuk(u))
        self.assertEqual(r.status_code, 200, r.text)
        user = await self.baca(u.id)
        self.assertEqual(user.email, "lama@example.com")
        self.assertEqual(user.google_id, "g-1")
        self.assertIsNone(user.email_verified_at)

    async def test_google_link_email_sama_belum_terverifikasi_jadi_terverifikasi(self):
        async with self.Session() as db:
            u = await self.buat(db, "Sama", "budi@example.com", terverifikasi=False)
            await db.commit()
        with self.google():
            r = await self.klien.post("/auth/google/link", json={"credential": "x"}, headers=self.masuk(u))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone((await self.baca(u.id)).email_verified_at)


class PagarTests(unittest.TestCase):
    def test_pagar_tanpa_update_core_email(self):
        """UPDATE Core melewati event ORM: tidak boleh ada `.values(` yang memuat `email=` di kode aplikasi."""
        akar = Path(__file__).resolve().parents[1]
        pelanggar = []
        for f in akar.rglob("*.py"):
            if "tests" in f.relative_to(akar).parts:
                continue
            teks = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\.values\(", teks):
                dalam, kedalaman, i = [], 1, m.end()
                while i < len(teks) and kedalaman:
                    kedalaman += {"(": 1, ")": -1}.get(teks[i], 0)
                    i += 1
                if re.search(r"(?<![A-Za-z_])email\s*=", teks[m.end():i]):
                    pelanggar.append(str(f.relative_to(akar)))
        self.assertEqual(pelanggar, [])


UID = "00000000-0000-0000-0000-000000000001"


class TokenTests(unittest.TestCase):
    """Token bertujuan murni (Ruling F-2): tanpa database, jadi juga jalan tanpa `aiosqlite`."""

    def test_token_verifikasi_bolak_balik(self):
        user = SimpleNamespace(id=UID, email=" Ani@X.id ")
        tautan = ve.tautan_verifikasi(user)
        awal = f"{get_settings().API_URL}/auth/verifikasi-email?token="
        self.assertTrue(tautan.startswith(awal))
        hasil = ve.baca_token_verifikasi(tautan[len(awal):])
        self.assertEqual((str(hasil[0]), hasil[1]), (user.id, "ani@x.id"))
        klaim = decode_purpose_token(tautan[len(awal):], ve.TUJUAN_VERIFIKASI)
        self.assertAlmostEqual(klaim["exp"] - datetime.now(timezone.utc).timestamp(), 86400, delta=60)

    def test_token_kedaluwarsa_ditolak(self):
        token = create_purpose_token(UID, ve.TUJUAN_VERIFIKASI, berlaku=timedelta(seconds=-5), email="a@x.id")
        self.assertIsNone(ve.baca_token_verifikasi(token))
        self.assertIsNone(decode_purpose_token(token, ve.TUJUAN_VERIFIKASI))

    def test_token_type_lain_ditolak(self):
        for token in (create_access_token(UID), create_refresh_token(UID),
                      create_purpose_token(UID, "berhenti_email_laporan", berlaku=None)):
            self.assertIsNone(ve.baca_token_verifikasi(token))
            self.assertIsNone(decode_purpose_token(token, ve.TUJUAN_VERIFIKASI))

    def test_token_cacat_ditolak(self):
        secret = get_settings().JWT_SECRET
        tanpa_sub = jwt.encode({"type": ve.TUJUAN_VERIFIKASI, "email": "a@x.id",
                                "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, secret, algorithm="HS256")
        tanpa_exp = create_purpose_token(UID, ve.TUJUAN_VERIFIKASI, berlaku=None, email="a@x.id")
        tanpa_email = create_purpose_token(UID, ve.TUJUAN_VERIFIKASI, berlaku=timedelta(hours=1))
        sub_buruk = create_purpose_token("bukan-uuid", ve.TUJUAN_VERIFIKASI, berlaku=timedelta(hours=1),
                                         email="a@x.id")
        for token in (tanpa_sub, tanpa_exp, tanpa_email, sub_buruk, "bukan.token.jwt", ""):
            self.assertIsNone(ve.baca_token_verifikasi(token))

    def test_tanda_tangan_kunci_lain_ditolak(self):
        # Klaim lengkap dan belum kedaluwarsa: satu-satunya beda dengan token yang sah adalah kunci penandatangannya.
        cfg = get_settings()
        klaim = {"sub": UID, "type": ve.TUJUAN_VERIFIKASI, "email": "a@x.id",
                 "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        sah = jwt.encode(klaim, cfg.JWT_SECRET, algorithm=cfg.JWT_ALGORITHM)
        palsu = jwt.encode(klaim, "kunci-lain", algorithm=cfg.JWT_ALGORITHM)
        self.assertEqual(ve.baca_token_verifikasi(sah), (UUID(UID), "a@x.id"))
        self.assertIsNone(decode_purpose_token(palsu, ve.TUJUAN_VERIFIKASI))
        self.assertIsNone(ve.baca_token_verifikasi(palsu))

    def test_tanpa_exp_bolak_balik(self):
        # `berlaku=None` (bentuk token berhenti berlangganan): tanpa klaim `exp`, tetap terbaca.
        token = create_purpose_token(UID, "berhenti_email_laporan", berlaku=None)
        self.assertNotIn("exp", jwt.decode(token, options={"verify_signature": False}))
        klaim = decode_purpose_token(token, "berhenti_email_laporan")
        self.assertEqual((klaim["sub"], klaim["type"]), (UID, "berhenti_email_laporan"))
        self.assertNotIn("exp", klaim)

    def test_berlaku_wajib_disebut(self):
        # Argumen yang terlupa tidak pernah mencetak token tanpa kedaluwarsa: `berlaku` keyword tanpa bawaan.
        with self.assertRaises(TypeError):
            create_purpose_token(UID, ve.TUJUAN_VERIFIKASI, email="a@x.id")
        with self.assertRaises(TypeError):
            create_purpose_token(UID, ve.TUJUAN_VERIFIKASI, timedelta(hours=1), email="a@x.id")

    def test_tujuan_access_refresh_ditolak(self):
        for tujuan, token_sesi in (("access", create_access_token(UID)), ("refresh", create_refresh_token(UID))):
            with self.subTest(tujuan=tujuan):
                for berlaku in (timedelta(hours=1), None):
                    with self.assertRaises(ValueError):
                        create_purpose_token(UID, tujuan, berlaku=berlaku)
                for token in (token_sesi, ""):
                    with self.assertRaises(ValueError):
                        decode_purpose_token(token, tujuan)

    def test_klaim_tidak_menimpa_sub_type_exp(self):
        token = create_purpose_token("u1", "x", berlaku=timedelta(hours=1), sub="lain", type="access")
        klaim = decode_purpose_token(token, "x")
        self.assertEqual((klaim["sub"], klaim["type"]), ("u1", "x"))
        tanpa_exp = create_purpose_token("u1", "x", berlaku=None, exp=datetime.now(timezone.utc) + timedelta(days=1))
        self.assertNotIn("exp", decode_purpose_token(tanpa_exp, "x"))


class TokenLoginTests(DasarVerifikasi):
    async def test_token_bertujuan_tidak_bisa_login(self):
        for tujuan in (ve.TUJUAN_VERIFIKASI, "berhenti_email_laporan"):
            token = create_purpose_token(str(self.ani.id), tujuan, berlaku=timedelta(hours=1),
                                         email="ani@example.com")
            r = await self.klien.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(r.status_code, 401, tujuan)
            r = await self.klien.post("/auth/refresh", json={"refresh_token": token})
            self.assertEqual(r.status_code, 401, tujuan)
        sah = await self.klien.get("/auth/me", headers=self.masuk(self.ani))
        self.assertEqual(sah.status_code, 200)


if __name__ == "__main__":
    unittest.main()
