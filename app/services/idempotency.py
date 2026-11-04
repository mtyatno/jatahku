"""Idempotensi pencatatan transaksi dari web (client_ref).

Web mengirim `client_ref` unik per transaksi. Kalau respons hilang/gagal di
tengah jalan dan klien mengirim ulang, transaksi yang sudah tercatat tidak
dibuat dua kali: server mengembalikan transaksi yang sudah ada.

Alur per transaksi: lookup → (cek aturan) → reserve (SET NX "pending") →
buat & commit → store (ref → id transaksi). Gagal sebelum commit → release.
Redis mati → fail open (perilaku lama, tanpa dedup), kecuali pemanggil meminta `strict=True`:
galat Redis dilempar sebagai `RedisTidakTersedia` (dipakai prive, yang tidak bisa dibatalkan).

`scope` memisahkan ruang nama kunci per jenis catatan (`txnref` transaksi dan advisor, `priveref`
prive), supaya `client_ref` yang sama di dua jenis tidak saling membaca atau menghapus.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("jatahku.idempotency")

TTL_SECONDS = 2 * 24 * 3600  # cukup untuk antrean offline & percobaan ulang
PENDING_TTL = 120
PENDING = "pending"
SCOPE_TXN = "txnref"


class RedisTidakTersedia(Exception):
    """Redis tidak terjangkau pada pemanggilan `strict=True`."""


def _key(user_id, ref: str, scope: str = SCOPE_TXN) -> str:
    return f"{scope}:{user_id}:{ref}"


def _gagal(op: str, exc: Exception, strict: bool):
    logger.warning("idempotency %s gagal: %s", op, exc)
    if strict:
        raise RedisTidakTersedia(str(exc)) from exc


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def lookup(user_id, ref: str | None, *, scope: str = SCOPE_TXN, strict: bool = False) -> str | None:
    """ID transaksi yang sudah tercatat untuk ref ini, "pending", atau None."""
    if not ref:
        return None
    try:
        r = _redis()
        try:
            val = await r.get(_key(user_id, ref, scope))
        finally:
            await r.aclose()
        return val.decode() if isinstance(val, bytes) else val
    except Exception as exc:
        _gagal("lookup", exc, strict)
        return None


async def reserve(user_id, ref: str | None, *, scope: str = SCOPE_TXN, strict: bool = False) -> bool:
    """True = boleh membuat transaksi (ref belum dipakai). Tanpa ref / Redis mati → True."""
    if not ref:
        return True
    try:
        r = _redis()
        try:
            return bool(await r.set(_key(user_id, ref, scope), PENDING, nx=True, ex=PENDING_TTL))
        finally:
            await r.aclose()
    except Exception as exc:
        _gagal("reserve", exc, strict)
        return True


async def store(user_id, ref: str | None, txn_id, *, scope: str = SCOPE_TXN, strict: bool = False) -> None:
    if not ref:
        return
    try:
        r = _redis()
        try:
            await r.set(_key(user_id, ref, scope), str(txn_id), ex=TTL_SECONDS)
        finally:
            await r.aclose()
    except Exception as exc:
        _gagal("store", exc, strict)


async def release(user_id, ref: str | None, *, scope: str = SCOPE_TXN, strict: bool = False) -> None:
    """Lepas reservasi "pending" (gagal sebelum tercatat) supaya bisa dicoba lagi."""
    if not ref:
        return
    try:
        r = _redis()
        try:
            key = _key(user_id, ref, scope)
            if (await r.get(key)) in (PENDING, PENDING.encode()):
                await r.delete(key)
        finally:
            await r.aclose()
    except Exception as exc:
        _gagal("release", exc, strict)


async def forget(user_id, ref: str | None, *, scope: str = SCOPE_TXN, strict: bool = False) -> None:
    """Hapus kunci yang menunjuk transaksi yang sudah tidak ada (dihapus/digabung)."""
    if not ref:
        return
    try:
        r = _redis()
        try:
            await r.delete(_key(user_id, ref, scope))
        finally:
            await r.aclose()
    except Exception as exc:
        _gagal("forget", exc, strict)
