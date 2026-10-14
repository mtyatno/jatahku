"""Izin kuota per input (paket Basic, 50 transaksi/bulan).

Aturan pemilik produk (15 Okt 2026): input pengeluaran yang DIMULAI saat kuota
bulan ini belum habis diselesaikan utuh — walau di tengah jalan melewati batas —
lalu user diberi tahu kuota habis; input berikutnya menunggu reset bulan depan.

Web: satu kiriman batch = satu input. Bila kiriman dimulai dengan kuota masih
ada, setiap client_ref di dalamnya diberi izin (`quotapass:{user}:{ref}`, 2 hari),
jadi kirim ulang bagian yang gagal (mis. sesudah isi dana / naikkan limit) tetap
boleh walau kuota sudah terlewati. Redis mati → tanpa izin (kirim ulang dicek
ulang terhadap kuota; kiriman yang sedang berjalan tetap selesai utuh).

Bot: antrean multi-item menyimpan `quota_pass` di state-nya (bot/batch_cmd.py),
dan langkah lanjutan satu item memakai check_expense(skip_plan_limit=True).
"""
from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("jatahku.quota_pass")

TTL_SECONDS = 2 * 24 * 3600


def _key(user_id, ref: str) -> str:
    return f"quotapass:{user_id}:{ref}"


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def grant(user_id, refs) -> None:
    refs = [r for r in (refs or []) if r]
    if not refs:
        return
    try:
        r = _redis()
        try:
            for ref in refs:
                await r.set(_key(user_id, ref), "1", ex=TTL_SECONDS)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("quota pass grant gagal: %s", exc)


async def held(user_id, refs) -> set[str]:
    """client_ref yang sudah punya izin (bagian dari input yang dimulai saat kuota ada)."""
    refs = [r for r in (refs or []) if r]
    if not refs:
        return set()
    try:
        r = _redis()
        try:
            out = set()
            for ref in refs:
                if await r.get(_key(user_id, ref)):
                    out.add(ref)
            return out
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("quota pass lookup gagal: %s", exc)
        return set()
