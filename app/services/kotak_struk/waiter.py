"""Kabar selesai Kotak Struk lewat Redis pub/sub (spec 2026-10-26 bagian 1) dan penunggu hasilnya.

Worker mem-publish status akhir ke kanal `kotak:done:{item_id}`; bot dan API menunggu kanal itu
dengan `wait_for_item`. Redis hanya jalur cepat: database tetap sumber kebenaran, jadi Redis mati
atau pesan hilang tidak membuat penunggu macet.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable

from app.core.config import get_settings
from app.models.models import ReceiptScan
from app.services.kotak_struk.config import ST_DITERIMA, ST_DIPROSES

log = logging.getLogger(__name__)

CHANNEL = "kotak:done:{item_id}"
WAITING = {ST_DITERIMA, ST_DIPROSES}
PUBLISH_TIMEOUT_S = 3.0    # Redis menggantung tidak boleh menahan worker
REDIS_RECHECK_S = 5.0      # jaring pengaman: tetap cek DB sesekali walau Redis sehat (pesan bisa hilang)


def _default_redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


async def _close(resource) -> None:
    """Tutup klien/pubsub Redis; versi lama hanya punya `close()`. Galat saat menutup diabaikan."""
    if resource is None:
        return
    try:
        closer = getattr(resource, "aclose", None) or resource.close
        await closer()
    except Exception:
        pass


async def publish_done(item_id: uuid.UUID, status: str, *, redis_factory: Callable | None = None) -> None:
    """`PUBLISH kotak:done:{item_id} status`. Galat apa pun (Redis mati, waktu habis) hanya dicatat:
    penunggu tetap menemukan hasilnya lewat database."""
    client = None
    try:
        client = (redis_factory or _default_redis)()
        await asyncio.wait_for(client.publish(CHANNEL.format(item_id=item_id), status), PUBLISH_TIMEOUT_S)
    except Exception as exc:
        log.warning("kabar selesai Kotak Struk %s tidak terkirim (Redis): %s", item_id, exc)
    finally:
        await _close(client)


async def _load(factory, item_id: uuid.UUID) -> ReceiptScan | None:
    async with factory() as db:
        return await db.get(ReceiptScan, item_id)


def _settled(item: ReceiptScan | None) -> bool:
    return item is None or item.status not in WAITING


async def wait_for_item(item_id: uuid.UUID, timeout_s: float, *, session_factory=None, poll_s: float = 0.5,
                        redis_factory: Callable | None = None) -> ReceiptScan | None:
    """Tunggu sampai item selesai dibaca (status bukan `diterima`/`diproses`), paling lama `timeout_s`.

    Cek DB dulu; lalu berlangganan kanal Redis dan cek DB sekali lagi (selesai tepat di antara
    keduanya tidak ada pesan yang menunggu). Redis gagal -> cek DB tiap `poll_s`. Habis waktu -> item
    terakhir dari DB (status masih `diterima`/`diproses`); `None` bila item tidak ada."""
    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    item = await _load(session_factory, item_id)
    if _settled(item) or timeout_s <= 0:
        return item

    client = pubsub = None
    try:
        try:
            client = (redis_factory or _default_redis)()
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL.format(item_id=item_id))
        except Exception as exc:
            log.warning("penunggu Kotak Struk %s memakai cek database (Redis): %s", item_id, exc)
            await _close(pubsub)
            await _close(client)
            pubsub = client = None

        item = await _load(session_factory, item_id)  # selesai sebelum langganan aktif: tidak ada pesan
        while not _settled(item):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            if pubsub is not None:
                try:
                    await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, REDIS_RECHECK_S))
                except Exception as exc:
                    log.warning("penunggu Kotak Struk %s beralih ke cek database (Redis): %s", item_id, exc)
                    await _close(pubsub)
                    await _close(client)
                    pubsub = client = None
                    continue
            else:
                await asyncio.sleep(min(poll_s, remaining))
            item = await _load(session_factory, item_id)
        return item
    finally:
        await _close(pubsub)
        await _close(client)
