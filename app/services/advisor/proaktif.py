"""Notifikasi proaktif AI Advisor (S16, 02-aturan.md §9 "Notifikasi proaktif", §7 ringkasan).

Permukaan proaktif: `telegram`, `web` (lonceng), `chat` (chat web, ditarik saat panel dibuka).
Aturan:
- Maksimal 1 kiriman advisor per hari (item #1 daftar). Kiriman pertama hari itu — peringatan
  danger atau ringkasan harian — "memakai" kuota; permukaan lain hanya boleh mengirim hal yang
  sama.
- Hal yang sama tidak dikirim ke lebih dari 2 permukaan di hari yang sama, dan tidak dikirim
  dua kali ke permukaan yang sama. Tagihan dihitung per langganan: TAG-01/02/03 dan pengingat
  jatuh tempo untuk langganan yang sama = satu hal (`hal`).
- Jam tenang 21.00–07.00 waktu user untuk peringatan; pengingat tagihan jatuh tempo dikirim
  mulai 07.00 (pagi).
- Status dismiss selalu yang terbaru (#91): `chat.muat` membaca `advisor_cache.muat_dismiss`
  setiap kali, jadi yang disembunyikan tidak dikirim dan yang sudah dimunculkan lagi boleh
  dikirim lagi. Modul ini tidak punya jalur dismiss sendiri.

Buku kiriman (Redis hash `advisor:proaktif:{viewer}:{tanggal lokal}`, TTL 2 hari):
field = hal → "telegram,web"; field `_advisor` = hal yang memakai kuota hari itu.
Redis mati → fail closed untuk peringatan & chat (tidak mengirim), ringkasan tetap jalan.

Keputusan kecil S16:
- Ringkasan harian/mingguan dijadwalkan user sendiri, jadi tidak diblokir jam tenang maupun
  kuota; ringkasan harian tetap MENCATAT item #1-nya (memakai kuota bila belum terpakai).
- Peringatan proaktif hanya untuk item #1 bertone danger; chat web menampilkan item hari ini
  (atau item #1 danger/warn) sekali per hari. Info/ok hanya lewat ringkasan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.config import get_settings

logger = logging.getLogger("jatahku.advisor.proaktif")

PERMUKAAN = ("telegram", "web", "chat")
MAKS_PERMUKAAN = 2
JAM_TENANG_MULAI = 21
JAM_TENANG_SELESAI = 7
TTL_BUKU = 2 * 24 * 3600
TTL_TAGIHAN = 400 * 24 * 3600   # pengingat per (langganan, jatuh tempo, user) — cukup untuk tahunan
ADVISOR = "_advisor"


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(get_settings().REDIS_URL)


# ── murni ───────────────────────────────────────────────────────────────
def hal(kunci: str) -> str:
    """Kunci insight → "hal" untuk batas permukaan. Tagihan per langganan (TAG-*:rid → TAG:rid)."""
    aturan, _, entitas = kunci.partition(":")
    return f"TAG:{entitas}" if aturan.startswith("TAG-") else kunci


def hal_tagihan(recurring_id) -> str:
    return f"TAG:{recurring_id}"


def jam_tenang(now_local: datetime) -> bool:
    return now_local.hour >= JAM_TENANG_MULAI or now_local.hour < JAM_TENANG_SELESAI


@dataclass
class Buku:
    tanggal: date
    hal: dict[str, set[str]] = field(default_factory=dict)
    advisor: str | None = None

    def permukaan_bebas(self, kunci: str, diminta) -> list[str]:
        """Permukaan dari `diminta` (urut prioritas) yang masih boleh menerima hal ini."""
        pakai = set(self.hal.get(hal(kunci), ()))
        out = []
        for p in diminta:
            if p in pakai or p in out:
                continue
            if len(pakai) + len(out) >= MAKS_PERMUKAAN:
                break
            out.append(p)
        return out

    def kuota_untuk(self, kunci: str) -> bool:
        """Kuota 1/hari: bebas, atau sudah dipakai hal yang sama."""
        return self.advisor is None or self.advisor == hal(kunci)


def pilih_peringatan(a, buku: Buku):
    """Item #1 daftar bertone danger yang boleh dikirim hari ini, atau None."""
    if not a.sel.daftar:
        return None
    ins = a.sel.daftar[0]
    if ins.tone != "danger" or not buku.kuota_untuk(ins.id):
        return None
    return ins


def pilih_chat(a, buku: Buku):
    """Untuk chat web: hal yang sudah dikirim hari ini bila masih tampil di daftar (belum
    di-dismiss), selain itu item #1 danger/warn bila kuota masih bebas."""
    if buku.advisor:
        for ins in a.sel.daftar:
            if hal(ins.id) == buku.advisor:
                return ins
        return None
    if a.sel.daftar and a.sel.daftar[0].tone in ("danger", "warn"):
        return a.sel.daftar[0]
    return None


# ── buku kiriman (Redis) ────────────────────────────────────────────────
def kunci_buku(viewer, tanggal: date) -> str:
    return f"advisor:proaktif:{viewer}:{tanggal.isoformat()}"


async def muat_buku(viewer, tanggal: date) -> Buku | None:
    """None = Redis gagal (pemanggil tidak mengirim, supaya tidak dobel)."""
    try:
        r = _redis()
        try:
            raw = await r.hgetall(kunci_buku(viewer, tanggal))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("buku proaktif gagal dimuat: %s", exc)
        return None
    buku = Buku(tanggal=tanggal)
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else k
        v = v.decode() if isinstance(v, bytes) else v
        if k == ADVISOR:
            buku.advisor = v or None
        else:
            buku.hal[k] = {p for p in v.split(",") if p}
    return buku


async def catat(viewer, buku: Buku, kunci: str, permukaan, advisor: bool) -> None:
    """Tambah permukaan yang terkirim ke buku (dan Redis). `advisor` = kiriman ini memakai kuota."""
    permukaan = set(permukaan)
    if not permukaan:
        return
    h = hal(kunci)
    buku.hal[h] = buku.hal.get(h, set()) | permukaan
    data = {h: ",".join(sorted(buku.hal[h]))}
    if advisor and buku.advisor is None:
        buku.advisor = h
        data[ADVISOR] = h
    try:
        r = _redis()
        try:
            key = kunci_buku(viewer, buku.tanggal)
            await r.hset(key, mapping=data)
            await r.expire(key, TTL_BUKU)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("buku proaktif gagal dicatat: %s", exc)


async def klaim_pengingat_tagihan(recurring_id, jatuh_tempo: date, user_id) -> bool | None:
    """True sekali per (langganan, jatuh tempo, user) — pengingat tidak berulang tiap hari.
    None = Redis gagal (jangan kirim)."""
    try:
        r = _redis()
        try:
            return bool(await r.set(f"advisor:tagihan:{recurring_id}:{jatuh_tempo.isoformat()}:{user_id}",
                                    "1", ex=TTL_TAGIHAN, nx=True))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("klaim pengingat tagihan gagal: %s", exc)
        return None


# ── alur ────────────────────────────────────────────────────────────────
async def _analisa(user, now_local: datetime):
    """Analisa viewer dengan sesi DB sendiri (gagal → None, pemanggil tidak ikut rusak)."""
    from app.core.database import AsyncSessionLocal
    from app.services.advisor import chat
    try:
        async with AsyncSessionLocal() as adb:
            return await chat.muat(user, adb, now=now_local)
    except Exception as exc:
        logger.error("analisa proaktif gagal untuk %s: %s", user.id, exc)
        return None


async def kirim_peringatan(user, prefs, now_local: datetime) -> set[str]:
    """Peringatan danger (send_budget_warning) untuk item #1, maks 1/hari, di luar jam tenang.
    Dipanggil scheduler tiap jam. Mengembalikan permukaan yang terkirim."""
    from app.services.notification_service import send_budget_warning
    if jam_tenang(now_local):
        return set()
    buku = await muat_buku(user.id, now_local.date())
    # Kuota sudah dipakai dan hal itu sudah di 2 permukaan → tidak perlu menghitung analisa.
    if buku is None or (buku.advisor and len(buku.hal.get(buku.advisor, ())) >= MAKS_PERMUKAAN):
        return set()
    a = await _analisa(user, now_local)
    if a is None:
        return set()
    ins = pilih_peringatan(a, buku)
    if ins is None:
        return set()
    from app.services.advisor.chat import _r
    permukaan = buku.permukaan_bebas(ins.id, ("telegram", "web"))
    terkirim = await send_budget_warning(user, _r(a, ins), prefs, permukaan)
    await catat(user.id, buku, ins.id, terkirim, advisor=True)
    if terkirim:
        logger.info("advisor peringatan %s → %s (%s)", ins.id, user.id, ",".join(sorted(terkirim)))
    return terkirim


async def catat_ringkasan(user, a, tanggal: date, permukaan) -> None:
    """Ringkasan harian terkirim: item #1 tercatat di buku (memakai kuota bila belum)."""
    if not a.sel.daftar or not permukaan:
        return
    buku = await muat_buku(user.id, tanggal)
    if buku is not None:
        await catat(user.id, buku, a.sel.daftar[0].id, permukaan, advisor=True)


async def untuk_chat(user, now: datetime | None = None) -> str | None:
    """Pesan proaktif untuk chat web (HTML), sekali per hari per hal; None bila tidak ada."""
    from app.services.advisor import render
    from app.services.advisor.chat import _r
    from app.services.advisor.dashboard import _tz
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    buku = await muat_buku(user.id, now_local.date())
    if buku is None:
        return None
    if buku.advisor and not buku.permukaan_bebas(buku.advisor, ("chat",)):
        return None   # item hari ini sudah di chat web atau sudah di 2 permukaan: tanpa analisa
    a = await _analisa(user, now_local)
    if a is None:
        return None
    ins = pilih_chat(a, buku)
    if ins is None or not buku.permukaan_bebas(ins.id, ("chat",)):
        return None
    await catat(user.id, buku, ins.id, {"chat"}, advisor=True)
    return render.notifikasi_insight(_r(a, ins))[2]
