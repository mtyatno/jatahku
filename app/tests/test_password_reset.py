"""Tests for password reset token service (app/services/password_reset.py).

Run from repo root:  python -m unittest app.tests.test_password_reset -v
"""
import unittest

from app.services.password_reset import (
    create_reset_token,
    redeem_reset_token,
    RESET_PREFIX,
    RESET_TTL_SECONDS,
)


class FakeRedis:
    """In-memory stub matching the redis.asyncio methods we use."""

    def __init__(self):
        self.store = {}   # key -> (value, ex)

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def get(self, key):
        item = self.store.get(key)
        if item is None:
            return None
        return item[0].encode() if isinstance(item[0], str) else item[0]

    async def delete(self, key):
        self.store.pop(key, None)


class TestCreateResetToken(unittest.IsolatedAsyncioTestCase):
    async def test_returns_urlsafe_token_and_stores_user_id(self):
        r = FakeRedis()
        token = await create_reset_token(r, "user-123")
        # token_urlsafe(32) → 43 karakter urlsafe
        self.assertGreaterEqual(len(token), 43)
        key = f"{RESET_PREFIX}{token}"
        self.assertIn(key, r.store)
        value, ex = r.store[key]
        self.assertEqual(value, "user-123")
        self.assertEqual(ex, RESET_TTL_SECONDS)

    async def test_tokens_are_unique(self):
        r = FakeRedis()
        t1 = await create_reset_token(r, "u1")
        t2 = await create_reset_token(r, "u1")
        self.assertNotEqual(t1, t2)


class TestRedeemResetToken(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_returns_user_id_and_deletes_key(self):
        r = FakeRedis()
        token = await create_reset_token(r, "user-123")
        user_id = await redeem_reset_token(r, token)
        self.assertEqual(user_id, "user-123")
        self.assertNotIn(f"{RESET_PREFIX}{token}", r.store)

    async def test_second_redeem_returns_none(self):
        r = FakeRedis()
        token = await create_reset_token(r, "user-123")
        await redeem_reset_token(r, token)
        self.assertIsNone(await redeem_reset_token(r, token))

    async def test_unknown_token_returns_none(self):
        r = FakeRedis()
        self.assertIsNone(await redeem_reset_token(r, "tidak-ada"))

    async def test_empty_token_returns_none(self):
        r = FakeRedis()
        self.assertIsNone(await redeem_reset_token(r, ""))


if __name__ == "__main__":
    unittest.main()
