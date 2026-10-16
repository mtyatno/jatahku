"""Cache Redis AI Advisor v2 + status dismiss (02-aturan.md §9, §14).

Cache dashboard: kunci `advisor:{household_id}:{viewer_id}` (isi berbeda per viewer karena
amplop pribadi), TTL 90 detik. Perubahan data oleh anggota MANA PUN menghapus semua kunci
household itu (`invalidate(hid)` → `advisor:{hid}:*`).

Siapa yang memanggil `invalidate`: hook sesi SQLAlchemy (`install()`, dipasang sekali di
`main.py`) — setiap commit yang menulis/menghapus transaksi, pemasukan, alokasi, transfer,
amplop, langganan, target, snapshot rollover, atau cocokkan saldo, dari route web, chat web,
bot Telegram, maupun scheduler, menghapus cache household yang tersentuh sesudah commit.
Satu titik ini menggantikan panggilan manual di puluhan tempat commit (route + bot), jadi
jalur baru otomatis ikut. Pemanggilan langsung tetap boleh (mis. dari skrip).

Dismiss: `advisor:dismiss:{viewer}:{kunci}` → JSON {"pilihan", "tone", "rupiah"} dengan
TTL sesuai pilihan (Nanti s/d besok 05.00 waktu user, Periode s/d akhir periode,
Tidak relevan 90 hari). Redis mati → fail open (tanpa cache, tanpa dismiss).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta
from itertools import chain

from app.core.config import get_settings

logger = logging.getLogger("jatahku.advisor.cache")

TTL_DASHBOARD = 90
TTL_TIDAK_RELEVAN = 90 * 24 * 3600
PILIHAN = ("nanti", "periode", "tidak_relevan")

_tasks: set = set()
_installed = False


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


def kunci_dashboard(hid, viewer) -> str:
    return f"advisor:{hid}:{viewer}"


def kunci_dismiss(viewer, kunci: str) -> str:
    return f"advisor:dismiss:{viewer}:{kunci}"


# ── dashboard ───────────────────────────────────────────────────────────
async def ambil(hid, viewer) -> dict | None:
    try:
        r = _redis()
        try:
            raw = await r.get(kunci_dashboard(hid, viewer))
        finally:
            await r.aclose()
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("advisor cache get gagal: %s", exc)
        return None


async def simpan(hid, viewer, data: dict) -> None:
    try:
        r = _redis()
        try:
            await r.set(kunci_dashboard(hid, viewer), json.dumps(data), ex=TTL_DASHBOARD)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("advisor cache set gagal: %s", exc)


async def invalidate(hid) -> None:
    """Hapus cache dashboard semua anggota household `hid`."""
    if not hid:
        return
    try:
        r = _redis()
        try:
            keys = [k async for k in r.scan_iter(match=f"advisor:{hid}:*", count=100)]
            if keys:
                await r.delete(*keys)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("advisor cache invalidate gagal: %s", exc)


async def invalidate_many(hids) -> None:
    for hid in hids:
        await invalidate(hid)


async def invalidate_viewer(hid, viewer) -> None:
    try:
        r = _redis()
        try:
            await r.delete(kunci_dashboard(hid, viewer))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("advisor cache invalidate viewer gagal: %s", exc)


# ── dismiss (§9) ────────────────────────────────────────────────────────
def ttl_dismiss(pilihan: str, now_local: datetime, period_end: date) -> int:
    """Detik sampai dismiss kedaluwarsa. `now_local` = waktu user (aware)."""
    if pilihan == "tidak_relevan":
        return TTL_TIDAK_RELEVAN
    if pilihan == "periode":
        sampai = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=now_local.tzinfo)
    else:  # nanti: besok pukul 05.00 waktu user
        sampai = datetime.combine(now_local.date() + timedelta(days=1), time(5), tzinfo=now_local.tzinfo)
    return max(int((sampai - now_local).total_seconds()), 60)


async def simpan_dismiss(viewer, kunci: str, pilihan: str, tone: str | None, rupiah, ttl: int) -> None:
    try:
        r = _redis()
        try:
            await r.set(kunci_dismiss(viewer, kunci),
                        json.dumps({"pilihan": pilihan, "tone": tone, "rupiah": str(rupiah or 0)}), ex=ttl)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("advisor dismiss set gagal: %s", exc)


async def muat_dismiss(viewer) -> dict:
    """{kunci insight: {"pilihan", "tone", "rupiah"}} yang masih berlaku."""
    prefix = kunci_dismiss(viewer, "")
    try:
        r = _redis()
        try:
            keys = [k async for k in r.scan_iter(match=prefix + "*", count=200)]
            vals = await r.mget(keys) if keys else []
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("advisor dismiss load gagal: %s", exc)
        return {}
    out = {}
    for k, v in zip(keys, vals):
        if not v:
            continue
        k = k.decode() if isinstance(k, bytes) else k
        try:
            out[k[len(prefix):]] = json.loads(v)
        except ValueError:
            continue
    return out


# ── hook sesi: commit yang menyentuh data keuangan → invalidate(hid) ─────
def _loaded(obj, attr):
    from sqlalchemy import inspect
    return inspect(obj).dict.get(attr)


def kumpulkan_household(session) -> set[str]:
    """Household yang datanya ikut ditulis di flush ini (dipanggil di after_flush)."""
    from sqlalchemy import select
    from app.models.models import (
        Allocation, BalanceCheck, Envelope, Goal, Income, MonthlySnapshot, RecurringTransaction, Transaction,
    )
    hids: set = set()
    env_ids: set = set()
    inc_ids: set = set()
    for obj in chain(session.new, session.dirty, session.deleted):
        if isinstance(obj, (Income, Envelope, BalanceCheck)):
            hid = _loaded(obj, "household_id")
            if hid:
                hids.add(hid)
        elif isinstance(obj, (Transaction, RecurringTransaction, Goal, MonthlySnapshot)):
            eid = _loaded(obj, "envelope_id")
            if eid:
                env_ids.add(eid)
        elif isinstance(obj, Allocation):
            iid = _loaded(obj, "income_id")
            if iid:
                inc_ids.add(iid)
    conn = None
    if env_ids or inc_ids:
        conn = session.connection()
    if env_ids:
        hids.update(conn.execute(select(Envelope.household_id).where(Envelope.id.in_(env_ids))).scalars())
    if inc_ids:
        hids.update(conn.execute(select(Income.household_id).where(Income.id.in_(inc_ids))).scalars())
    return {str(h) for h in hids if h}


def _after_flush(session, flush_context):
    try:
        hids = kumpulkan_household(session)
    except Exception as exc:  # cache bukan alasan menggagalkan tulis data
        logger.warning("advisor cache: gagal membaca household dari flush: %s", exc)
        return
    if hids:
        session.info.setdefault("advisor_hids", set()).update(hids)


def _after_commit(session):
    hids = session.info.pop("advisor_hids", None)
    if not hids:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(invalidate_many(sorted(hids)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _after_rollback(session):
    session.info.pop("advisor_hids", None)


def install() -> None:
    """Pasang hook di semua sesi SQLAlchemy (sekali; dipanggil saat app mulai)."""
    global _installed
    if _installed:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _installed = True


def uninstall() -> None:
    """Untuk tes."""
    global _installed
    if not _installed:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    event.remove(Session, "after_flush", _after_flush)
    event.remove(Session, "after_commit", _after_commit)
    event.remove(Session, "after_rollback", _after_rollback)
    _installed = False
