"""Idempotensi pencatatan transaksi dari web (client_ref).

Web mengirim `client_ref` unik per transaksi. Kalau respons hilang/gagal di
tengah jalan dan klien mengirim ulang, transaksi yang sudah tercatat tidak
dibuat dua kali: server mengembalikan transaksi yang sudah ada.

Alur per transaksi: lookup → (cek aturan) → reserve (SET NX "pending") →
buat & commit → store (ref → id transaksi). Gagal sebelum commit → release.
Redis mati → fail open (perilaku lama, tanpa dedup).
"""
from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("jatahku.idempotency")

TTL_SECONDS = 2 * 24 * 3600  # cukup untuk antrean offline & percobaan ulang
PENDING_TTL = 120
PENDING = "pending"


def _key(user_id, ref: str) -> str:
    return f"txnref:{user_id}:{ref}"


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def lookup(user_id, ref: str | None) -> str | None:
    """ID transaksi yang sudah tercatat untuk ref ini, "pending", atau None."""
    if not ref:
        return None
    try:
        r = _redis()
        try:
            val = await r.get(_key(user_id, ref))
        finally:
            await r.aclose()
        return val.decode() if isinstance(val, bytes) else val
    except Exception as exc:
        logger.warning("idempotency lookup gagal: %s", exc)
        return None


async def reserve(user_id, ref: str | None) -> bool:
    """True = boleh membuat transaksi (ref belum dipakai). Tanpa ref / Redis mati → True."""
    if not ref:
        return True
    try:
        r = _redis()
        try:
            return bool(await r.set(_key(user_id, ref), PENDING, nx=True, ex=PENDING_TTL))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("idempotency reserve gagal: %s", exc)
        return True


async def store(user_id, ref: str | None, txn_id) -> None:
    if not ref:
        return
    try:
        r = _redis()
        try:
            await r.set(_key(user_id, ref), str(txn_id), ex=TTL_SECONDS)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("idempotency store gagal: %s", exc)


async def release(user_id, ref: str | None) -> None:
    """Lepas reservasi "pending" (gagal sebelum tercatat) supaya bisa dicoba lagi."""
    if not ref:
        return
    try:
        r = _redis()
        try:
            key = _key(user_id, ref)
            if (await r.get(key)) in (PENDING, PENDING.encode()):
                await r.delete(key)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("idempotency release gagal: %s", exc)
