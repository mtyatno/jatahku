"""Password reset tokens — Redis-backed, single-use, TTL 30 menit.

Pola sama dengan tglogin:{token} di auth.py. Client redis di-inject
supaya logika bisa dites tanpa server Redis.
"""
import secrets

RESET_PREFIX = "pwreset:"
RESET_TTL_SECONDS = 1800  # 30 menit


async def create_reset_token(redis, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(f"{RESET_PREFIX}{token}", user_id, ex=RESET_TTL_SECONDS)
    return token


async def redeem_reset_token(redis, token: str) -> str | None:
    if not token:
        return None
    key = f"{RESET_PREFIX}{token}"
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    return value.decode() if isinstance(value, bytes) else value
