"""Mobile 1.1 — sesi per perangkat (ADR-M7): auth_sessions, rotasi refresh token
dengan deteksi pemakaian ulang + masa tenggang, logout & logout-all yang benar-benar
mencabut, dan token lama (tanpa sid) yang tetap berlaku sampai dicabut.

Route asli lewat HTTP (httpx ASGITransport) di atas SQLite in-memory.
Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_auth_sessions -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.orm import configure_mappers

from app.api.routes import auth as auth_route, user_settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.models import AuthSession, User
from app.services import auth_sessions

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None
PASSWORD = "rahasia123"
# bcrypt 5 tidak cocok dengan passlib 1.7.4 (requirements tidak mem-pin bcrypt), dan
# bcrypt lambat: hash sandi dipalsukan, yang diuji di sini sesi, bukan hash.
PW_HASH = "fake$" + PASSWORD


def _fake_verify(plain, hashed):
    return hashed == "fake$" + plain


def _fake_hash(plain):
    return "fake$" + plain


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AuthSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.Session() as db:
            self.user = User(name="Sari", email="sari@example.com", password_hash=PW_HASH)
            self.other = User(name="Budi", email="budi@example.com", password_hash=PW_HASH)
            db.add_all([self.user, self.other])
            await db.commit()

        app = FastAPI()
        app.state.limiter = auth_route.limiter
        app.include_router(auth_route.router, prefix="/auth")
        app.include_router(user_settings.router, prefix="/user")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        auth_route.limiter.enabled = False
        for mod in (auth_route, user_settings):
            for name, fake in (("verify_password", _fake_verify), ("hash_password", _fake_hash)):
                p = patch.object(mod, name, fake)
                p.start()
                self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        auth_route.limiter.enabled = True
        await self.client.aclose()
        await self.engine.dispose()

    # ── helper ────────────────────────────────────────────────────────────
    async def login(self, email="sari@example.com", client=None):
        headers = {"X-Jatahku-Client": client} if client else {}
        r = await self.client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def me(self, access):
        return (await self.client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code

    async def refresh(self, refresh):
        return await self.client.post("/auth/refresh", json={"refresh_token": refresh})

    async def sessions(self, user_id=None):
        async with self.Session() as db:
            q = select(AuthSession).where(AuthSession.user_id == (user_id or self.user.id))
            return (await db.execute(q)).scalars().all()

    async def age_rotation(self, seconds=60):
        """Mundurkan rotated_at/created_at supaya masa tenggang lewat."""
        past = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        async with self.Session() as db:
            await db.execute(update(AuthSession).values(rotated_at=past, created_at=past))
            await db.commit()

    # ── login & rotasi ────────────────────────────────────────────────────
    async def test_login_creates_device_session_with_sid(self):
        t = await self.login(client="android/1.0.0/7")
        [sess] = await self.sessions()
        self.assertEqual(decode_token(t["access_token"])["sid"], str(sess.id))
        self.assertEqual(decode_token(t["refresh_token"])["jti"], sess.refresh_jti)
        self.assertEqual(sess.client, "android/1.0.0/7")
        self.assertEqual(await self.me(t["access_token"]), 200)

    async def test_web_stays_logged_in_across_rotations(self):
        t = await self.login()
        seen = {decode_token(t["refresh_token"])["jti"]}
        for _ in range(3):
            r = await self.refresh(t["refresh_token"])
            self.assertEqual(r.status_code, 200, r.text)
            t = r.json()
            seen.add(decode_token(t["refresh_token"])["jti"])
            self.assertEqual(await self.me(t["access_token"]), 200)
        self.assertEqual(len(seen), 4)  # tiap refresh merotasi
        self.assertEqual(len(await self.sessions()), 1)  # tetap satu perangkat

    async def test_old_refresh_within_grace_gets_current_token(self):
        """Dua tab / app + widget merefresh bersamaan dengan token yang sama."""
        t = await self.login()
        a = (await self.refresh(t["refresh_token"])).json()
        r = await self.refresh(t["refresh_token"])
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual(decode_token(b["refresh_token"])["jti"], decode_token(a["refresh_token"])["jti"])
        # keduanya tetap bisa lanjut
        self.assertEqual((await self.refresh(a["refresh_token"])).status_code, 200)

    async def test_concurrent_refresh_with_same_token_both_succeed(self):
        t = await self.login()
        r1, r2 = await asyncio.gather(self.refresh(t["refresh_token"]), self.refresh(t["refresh_token"]))
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))

    async def test_reused_old_refresh_after_grace_revokes_session(self):
        t = await self.login()
        new = (await self.refresh(t["refresh_token"])).json()
        await self.age_rotation()
        self.assertEqual((await self.refresh(t["refresh_token"])).status_code, 401)
        [sess] = await self.sessions()
        self.assertEqual(sess.revoked_reason, "reuse")
        # token lama ditolak: refresh & access terbaru pun ikut mati
        self.assertEqual((await self.refresh(new["refresh_token"])).status_code, 401)
        self.assertEqual(await self.me(new["access_token"]), 401)

    async def test_invalid_refresh_tokens_rejected(self):
        t = await self.login()
        self.assertEqual((await self.refresh("bukan-token")).status_code, 401)
        self.assertEqual((await self.refresh(t["access_token"])).status_code, 401)  # tipe access

    async def test_expired_session_rejected(self):
        t = await self.login()
        async with self.Session() as db:
            await db.execute(update(AuthSession).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            await db.commit()
        self.assertEqual((await self.refresh(t["refresh_token"])).status_code, 401)
        self.assertEqual(await self.me(t["access_token"]), 401)

    # ── logout ────────────────────────────────────────────────────────────
    async def test_logout_revokes_only_this_device(self):
        hp = await self.login(client="android/1.0.0/7")
        web = await self.login()
        r = await self.client.post("/auth/logout", json={"refresh_token": hp["refresh_token"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(await self.me(hp["access_token"]), 401)
        self.assertEqual((await self.refresh(hp["refresh_token"])).status_code, 401)
        self.assertEqual(await self.me(web["access_token"]), 200)
        self.assertEqual((await self.refresh(web["refresh_token"])).status_code, 200)

    async def test_logout_with_access_token_only(self):
        t = await self.login()
        r = await self.client.post("/auth/logout", headers={"Authorization": f"Bearer {t['access_token']}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(await self.me(t["access_token"]), 401)

    async def test_logout_is_idempotent_without_tokens(self):
        self.assertEqual((await self.client.post("/auth/logout")).status_code, 200)
        self.assertEqual((await self.client.post("/auth/logout", json={"refresh_token": "x"})).status_code, 200)

    async def test_logout_all_cuts_every_device_and_legacy_tokens(self):
        hp = await self.login(client="android/1.0.0/7")
        web = await self.login()
        legacy_access = create_access_token(str(self.user.id))
        legacy_refresh = create_refresh_token(str(self.user.id))
        other = await self.login("budi@example.com")

        r = await self.client.post("/user/logout-all", headers={"Authorization": f"Bearer {web['access_token']}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "all_sessions_invalidated"})  # respons lama tetap
        for t in (hp, web):
            self.assertEqual(await self.me(t["access_token"]), 401)
            self.assertEqual((await self.refresh(t["refresh_token"])).status_code, 401)
        self.assertEqual(await self.me(legacy_access), 401)
        self.assertEqual((await self.refresh(legacy_refresh)).status_code, 401)
        # user lain tidak terdampak
        self.assertEqual(await self.me(other["access_token"]), 200)
        # login lagi tetap bisa
        self.assertEqual(await self.me((await self.login())["access_token"]), 200)

    # ── token lama (sebelum deploy) ──────────────────────────────────────
    async def test_legacy_access_token_still_works(self):
        self.assertEqual(await self.me(create_access_token(str(self.user.id))), 200)

    async def test_legacy_refresh_upgrades_once(self):
        legacy = create_refresh_token(str(self.user.id))
        r = await self.refresh(legacy)
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()
        self.assertIn("sid", decode_token(t["access_token"]))
        self.assertEqual(await self.me(t["access_token"]), 200)
        # balapan dua tab: token lama yang sama, masih dalam masa tenggang → sesi yang sama
        again = (await self.refresh(legacy)).json()
        self.assertEqual(decode_token(again["access_token"])["sid"], decode_token(t["access_token"])["sid"])
        self.assertEqual(len(await self.sessions()), 1)
        # dipakai ulang setelah masa tenggang → sesi hasil tukarnya dicabut
        await self.age_rotation()
        self.assertEqual((await self.refresh(legacy)).status_code, 401)
        self.assertEqual(await self.me(t["access_token"]), 401)

    # ── daftar & cabut perangkat ──────────────────────────────────────────
    async def test_list_and_revoke_sessions(self):
        hp = await self.login(client="ios/1.0.0/3")
        web = await self.login()
        other = await self.login("budi@example.com")
        auth = {"Authorization": f"Bearer {web['access_token']}"}

        r = await self.client.get("/auth/sessions", headers=auth)
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(x["current"] for x in rows), 1)
        hp_sid = decode_token(hp["access_token"])["sid"]
        self.assertIn("ios/1.0.0/3", [x["client"] for x in rows])

        other_sid = decode_token(other["access_token"])["sid"]
        self.assertEqual((await self.client.delete(f"/auth/sessions/{other_sid}", headers=auth)).status_code, 404)
        self.assertEqual(await self.me(other["access_token"]), 200)

        self.assertEqual((await self.client.delete(f"/auth/sessions/{hp_sid}", headers=auth)).status_code, 200)
        self.assertEqual(await self.me(hp["access_token"]), 401)
        self.assertEqual(len((await self.client.get("/auth/sessions", headers=auth)).json()), 1)

    # ── sandi ─────────────────────────────────────────────────────────────
    async def test_change_password_keeps_this_device_only(self):
        hp = await self.login(client="android/1.0.0/7")
        web = await self.login()
        r = await self.client.put(
            "/user/password", headers={"Authorization": f"Bearer {web['access_token']}"},
            json={"current_password": PASSWORD, "new_password": "sandibaru1"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(await self.me(web["access_token"]), 200)
        self.assertEqual((await self.refresh(web["refresh_token"])).status_code, 200)
        self.assertEqual(await self.me(hp["access_token"]), 401)

    async def test_reset_password_revokes_all_then_logs_in_here(self):
        hp = await self.login(client="android/1.0.0/7")
        redis = MagicMock(close=AsyncMock())
        with patch.object(auth_route.aioredis, "from_url", return_value=redis), \
             patch.object(auth_route, "redeem_reset_token", AsyncMock(return_value=str(self.user.id))), \
             patch.object(auth_route, "send_password_changed_email", MagicMock()):
            r = await self.client.post("/auth/reset-password", json={"token": "x", "new_password": "sandibaru1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(await self.me(hp["access_token"]), 401)
        self.assertEqual(await self.me(r.json()["access_token"]), 200)


class GraceWindowTests(unittest.TestCase):
    def test_grace_is_a_few_seconds(self):
        self.assertLessEqual(auth_sessions.REFRESH_GRACE, timedelta(seconds=60))
        self.assertGreater(auth_sessions.REFRESH_GRACE, timedelta(0))


if __name__ == "__main__":
    unittest.main()
