"""Masuk/daftar dengan Google: verifikasi token & alur /auth/google, /auth/google/link, /auth/google/unlink.

Run: python -m unittest app.tests.test_google_auth -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.routes import auth as route
from app.models.models import User, Household, HouseholdMember
from app.services.google_auth import verify_google_credential
from app.tests.fakes import FakeResult, db_with

CLIENT_ID = "123.apps.googleusercontent.com"
CLAIMS = {"sub": "g-1", "email": "budi@example.com", "name": "Budi"}


class FakeHttp:
    def __init__(self, status=200, body=None):
        self.status, self.body = status, body or {}

    async def get(self, url, params=None):
        return SimpleNamespace(status_code=self.status, json=lambda: self.body)


def tokeninfo(**over):
    body = {"aud": CLIENT_ID, "iss": "https://accounts.google.com", "sub": "g-1",
            "email": "Budi@Example.com", "email_verified": "true", "name": "Budi"}
    body.update(over)
    return body


class VerifyCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_returns_normalized_claims(self):
        claims = await verify_google_credential("tok", CLIENT_ID, FakeHttp(body=tokeninfo()))
        self.assertEqual(claims, {"sub": "g-1", "email": "budi@example.com", "name": "Budi"})

    async def test_rejects_token_for_other_client(self):
        self.assertIsNone(await verify_google_credential("tok", CLIENT_ID, FakeHttp(body=tokeninfo(aud="other"))))

    async def test_rejects_unverified_email(self):
        self.assertIsNone(await verify_google_credential("tok", CLIENT_ID, FakeHttp(body=tokeninfo(email_verified="false"))))

    async def test_rejects_wrong_issuer(self):
        self.assertIsNone(await verify_google_credential("tok", CLIENT_ID, FakeHttp(body=tokeninfo(iss="evil.com"))))

    async def test_rejects_when_google_says_invalid(self):
        self.assertIsNone(await verify_google_credential("tok", CLIENT_ID, FakeHttp(status=400)))

    async def test_name_falls_back_to_email_prefix(self):
        claims = await verify_google_credential("tok", CLIENT_ID, FakeHttp(body=tokeninfo(name=None)))
        self.assertEqual(claims["name"], "Budi")


def settings(client_id=CLIENT_ID):
    return SimpleNamespace(GOOGLE_CLIENT_ID=client_id, TELEGRAM_BOT_TOKEN="", ADMIN_TELEGRAM_ID="")


def request():
    return MagicMock()


class GoogleLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        p1 = patch.object(route, "get_settings", return_value=settings())
        p2 = patch.object(route, "verify_google_credential", AsyncMock(return_value=dict(CLAIMS)))
        self.verify = p2.start()
        p1.start()
        self.addCleanup(patch.stopall)

    async def call(self, db):
        return await route.google_login.__wrapped__(request(), route.GoogleCredentialRequest(credential="tok"), db)

    async def test_known_google_account_logs_in(self):
        user = SimpleNamespace(id=uuid.uuid4(), google_id="g-1")
        db = db_with(FakeResult(user))
        res = await self.call(db)
        self.assertTrue(res.access_token)
        self.assertIsNotNone(user.last_login)
        db.commit.assert_awaited_once()

    async def test_existing_email_account_gets_linked(self):
        user = SimpleNamespace(id=uuid.uuid4(), google_id=None, email="budi@example.com")
        db = db_with(FakeResult(None), FakeResult(user))
        await self.call(db)
        self.assertEqual(user.google_id, "g-1")
        db.commit.assert_awaited_once()

    async def test_new_user_gets_account_and_household(self):
        db = db_with(FakeResult(None), FakeResult(None))

        def add(obj):
            if getattr(obj, "id", None) is None and not isinstance(obj, HouseholdMember):
                obj.id = uuid.uuid4()
        db.add.side_effect = add
        await self.call(db)

        added = [c.args[0] for c in db.add.call_args_list]
        user = next(o for o in added if isinstance(o, User))
        self.assertEqual((user.email, user.name, user.google_id, user.password_hash),
                         ("budi@example.com", "Budi", "g-1", None))
        self.assertTrue(any(isinstance(o, Household) for o in added))
        member = next(o for o in added if isinstance(o, HouseholdMember))
        self.assertEqual(member.user_id, user.id)
        db.commit.assert_awaited_once()

    async def test_disabled_without_client_id(self):
        with patch.object(route, "get_settings", return_value=settings("")):
            with self.assertRaises(HTTPException) as e:
                await self.call(db_with())
        self.assertEqual(e.exception.status_code, 503)
        self.verify.assert_not_awaited()

    async def test_invalid_credential_is_401(self):
        self.verify.return_value = None
        with self.assertRaises(HTTPException) as e:
            await self.call(db_with())
        self.assertEqual(e.exception.status_code, 401)


class GoogleLinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patch.object(route, "get_settings", return_value=settings()).start()
        patch.object(route, "verify_google_credential", AsyncMock(return_value=dict(CLAIMS))).start()
        self.addCleanup(patch.stopall)

    async def link(self, user, db):
        return await route.google_link.__wrapped__(request(), route.GoogleCredentialRequest(credential="tok"), user, db)

    async def test_links_and_fills_missing_email_for_bot_user(self):
        user = SimpleNamespace(id=uuid.uuid4(), email=None, google_id=None)
        db = db_with(FakeResult(None), FakeResult(None))
        res = await self.link(user, db)
        self.assertEqual((user.google_id, user.email), ("g-1", "budi@example.com"))
        self.assertEqual(res["status"], "linked")

    async def test_keeps_email_when_another_account_owns_it(self):
        user = SimpleNamespace(id=uuid.uuid4(), email=None, google_id=None)
        other = SimpleNamespace(id=uuid.uuid4())
        db = db_with(FakeResult(None), FakeResult(other))
        await self.link(user, db)
        self.assertEqual((user.google_id, user.email), ("g-1", None))

    async def test_rejects_google_account_owned_by_someone_else(self):
        user = SimpleNamespace(id=uuid.uuid4(), email="a@x.com", google_id=None)
        db = db_with(FakeResult(SimpleNamespace(id=uuid.uuid4())))
        with self.assertRaises(HTTPException) as e:
            await self.link(user, db)
        self.assertEqual(e.exception.status_code, 400)
        self.assertIsNone(user.google_id)

    async def test_unlink_requires_another_way_in(self):
        user = SimpleNamespace(google_id="g-1", password_hash=None, telegram_id=None)
        with self.assertRaises(HTTPException):
            await route.google_unlink(user, db_with())
        self.assertEqual(user.google_id, "g-1")

    async def test_unlink_with_password(self):
        user = SimpleNamespace(google_id="g-1", password_hash="x", telegram_id=None)
        db = db_with()
        await route.google_unlink(user, db)
        self.assertIsNone(user.google_id)


class RegisterPromoRemovedTests(unittest.TestCase):
    def test_register_ignores_promo_code(self):
        req = route.RegisterRequest(email="a@b.co", password="secret1", name="A", promo_code="EARLY100")
        self.assertFalse(hasattr(req, "promo_code"))


if __name__ == "__main__":
    unittest.main()
