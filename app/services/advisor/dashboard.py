"""`GET /advisor/dashboard` dan `POST /advisor/dismiss` (02-aturan.md §1, §7, §9; 04-kontrak-api.md).

Alur: flag `advisor_v2_users` → cache Redis → snapshot (satu kali muat) → metrik → sinyal →
aturan HAR/PER/AMP/TAG/INC/TAB/DAT → seleksi (rencana bersama, skor, penekanan,
dismiss) → render. `susun_dashboard` murni (dites dengan fixture); `get_dashboard`
mengurus DB, Redis, dan jam.

AppSetting:
- `advisor_v2_users`: daftar user_id dipisah koma, atau `*` (03-workflow.md §5).
- `advisor_konstanta`: JSON {nama: nilai} yang menimpa default `Konstanta` (metrics),
  `KonstantaSinyal` (signals), dan `KonstantaAturan` (insight) — tanpa deploy (§11).
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.services.advisor import advisor_cache
from app.services.advisor.insight import DEFAULT as KA_DEFAULT, KonstantaAturan, Konteks, kunci_urut
from app.services.advisor.metrics import DEFAULT as KM_DEFAULT, Konstanta, compute_metrics
from app.services.advisor.render import judul_pendek, render_insight, teks_grafik
from app.services.advisor.rules import amplop, data, hari, pemasukan, periode, tabungan, tagihan
from app.services.advisor.select import pilih
from app.services.advisor.signals import DEFAULT as KS_DEFAULT, KonstantaSinyal, compute_signals

logger = logging.getLogger("jatahku.advisor.dashboard")

FLAG_KEY = "advisor_v2_users"
KONSTANTA_KEY = "advisor_konstanta"

# Aturan per modul (02-aturan.md §6A–G).
EVALUATOR = (hari.evaluasi, periode.evaluasi, amplop.evaluasi, tagihan.evaluasi, pemasukan.evaluasi,
             tabungan.evaluasi, data.evaluasi)


# ── pengaturan ──────────────────────────────────────────────────────────
def flag_aktif(value: str | None, user_id) -> bool:
    if not value:
        return False
    ids = {x.strip() for x in value.split(",") if x.strip()}
    return "*" in ids or str(user_id) in ids


def _timpa(default, raw: dict):
    """dataclass default + nilai dari JSON, dengan tipe field yang sama; kunci asing diabaikan."""
    ubah = {}
    for f in dataclasses.fields(default):
        if f.name not in raw:
            continue
        lama = getattr(default, f.name)
        try:
            if isinstance(lama, bool):
                ubah[f.name] = bool(raw[f.name])
            elif isinstance(lama, Decimal):
                ubah[f.name] = Decimal(str(raw[f.name]))
            elif isinstance(lama, int):
                ubah[f.name] = int(raw[f.name])
            elif isinstance(lama, float):
                ubah[f.name] = float(raw[f.name])
        except (TypeError, ValueError, ArithmeticError):
            logger.warning("advisor_konstanta %s tidak sah: %r", f.name, raw[f.name])
    return dataclasses.replace(default, **ubah)


def bangun_konstanta(raw: str | dict | None) -> tuple[Konstanta, KonstantaSinyal, KonstantaAturan]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            logger.warning("advisor_konstanta bukan JSON")
            raw = None
    if not isinstance(raw, dict):
        return KM_DEFAULT, KS_DEFAULT, KA_DEFAULT
    return _timpa(KM_DEFAULT, raw), _timpa(KS_DEFAULT, raw), _timpa(KA_DEFAULT, raw)


async def muat_pengaturan(db) -> dict[str, str]:
    from sqlalchemy import select
    from app.models.models import AppSetting
    rows = (await db.execute(
        select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_([FLAG_KEY, KONSTANTA_KEY]))
    )).all()
    return {k: v for k, v in rows}


def _tz(user) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        return ZoneInfo("Asia/Jakarta")


# ── susun (murni) ───────────────────────────────────────────────────────
def analisa(snap, *, now_local: datetime, dismiss: dict | None = None,
            km: Konstanta = KM_DEFAULT, ks: KonstantaSinyal = KS_DEFAULT,
            ka: KonstantaAturan = KA_DEFAULT):
    """Snapshot → (Konteks, Seleksi): metrik, sinyal, semua aturan, lalu seleksi."""
    m = compute_metrics(snap, km)
    s = compute_signals(snap, m, ks)
    ctx = Konteks(snap=snap, m=m, s=s, jam=now_local.hour, k=ka)
    insights = [ins for ev in EVALUATOR for ins in ev(ctx)]
    return ctx, pilih(ctx, insights, dismiss)


def susun_dashboard(snap, *, now_local: datetime, dismiss: dict | None = None,
                    km: Konstanta = KM_DEFAULT, ks: KonstantaSinyal = KS_DEFAULT,
                    ka: KonstantaAturan = KA_DEFAULT) -> tuple[dict, dict]:
    """(payload kontrak, meta {id insight: {"tone", "rupiah"}} untuk dismiss)."""
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    m = ctx.m
    payload = {
        "enabled": True,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "metrics": m.to_api(),
        "kpi": {kartu: (render_insight(ins, ctx, kpi=kartu) if ins else None) for kartu, ins in sel.kpi.items()},
        "grafik": teks_grafik(m, ctx.s),
        "advisor": {
            "items": [render_insight(ins, ctx) for ins in sel.daftar],
            "sisa": [{"id": ins.id, "judul_pendek": judul_pendek(ins, ctx)} for ins in sel.sisa],
            "total": len(sel.daftar) + len(sel.sisa),
            "aman": render_insight(sel.aman, ctx) if sel.aman else None,
            # Yang sedang disembunyikan viewer (§9 "Munculkan lagi", #91).
            "disembunyikan": [{"kunci": ins.id, "judul_pendek": judul_pendek(ins, ctx),
                               "pilihan": (dismiss or {}).get(ins.id, {}).get("pilihan", "nanti")}
                              for ins in sorted((i for i in sel.semua if i.id in sel.disembunyikan),
                                                key=kunci_urut)],
        },
        "redam_chip": sel.redam,
    }
    meta = {ins.id: {"tone": ins.tone, "rupiah": str(ins.rupiah)} for ins in sel.semua}
    return payload, meta


# ── DB + Redis ──────────────────────────────────────────────────────────
async def _hitung(user, db, now_local: datetime, pengaturan: dict, *, household_id) -> tuple[dict, dict, object]:
    from app.services.advisor.snapshot import load_snapshot
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    payload, meta = susun_dashboard(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    return payload, meta, snap


async def get_dashboard(user, db, now: datetime | None = None, *, household_id) -> dict:
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    hid = _sid(household_id)
    if hid:
        cached = await advisor_cache.ambil(hid, user.id)
        if cached and cached.get("payload", {}).get("generated_at", "")[:10] == now_local.date().isoformat():
            return cached["payload"]
    sebelum = set(await advisor_cache.muat_dismiss(user.id)) if hid else set()
    payload, meta, snap = await _hitung(user, db, now_local, pengaturan, household_id=household_id)
    # Dismiss/Urungkan yang terjadi selama menghitung (#91): jangan simpan payload basi ke cache,
    # nanti invalidate dari batal_dismiss terlewat dan insight tetap tersembunyi sampai 90 detik.
    if hid and set(await advisor_cache.muat_dismiss(user.id)) == sebelum:
        await advisor_cache.simpan(hid, user.id, {"payload": payload, "meta": meta,
                                                  "period_end": snap.periods[-1][1].isoformat()})
    return payload


def _sid(household_id) -> str | None:
    """Kunci cache advisor memakai id ruang sebagai teks."""
    return str(household_id) if household_id else None


async def dismiss(user, db, kunci: str, pilihan: str, now: datetime | None = None, *, household_id) -> None:
    """Simpan dismiss (§9). Tone & rupiah saat disembunyikan diambil dari dashboard terakhir,
    supaya insight bisa muncul lagi bila tone naik atau rupiah naik ≥ 50% (juga untuk
    `bukan_dobel` yang permanen: transaksi kembar baru masuk grup yang sama). Kecocokan
    pilihan khusus dengan kunci dicek di route (`advisor_cache.pilihan_sah`)."""
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    hid = _sid(household_id)
    cached = await advisor_cache.ambil(hid, user.id) if hid else None
    if cached and "meta" in cached:
        meta, pe = cached["meta"], cached.get("period_end")
        period_end = date.fromisoformat(pe) if pe else now_local.date()
    else:
        _, meta, snap = await _hitung(user, db, now_local, await muat_pengaturan(db), household_id=household_id)
        period_end = snap.periods[-1][1]
    info = meta.get(kunci) or {}
    ttl = advisor_cache.ttl_dismiss(pilihan, now_local, period_end)
    await advisor_cache.simpan_dismiss(user.id, kunci, pilihan, info.get("tone"), info.get("rupiah"), ttl)
    # Dicatat untuk evaluasi aturan (§9); bukan_dobel/bukan_tagihan = salah tanda S4/S4b/S19 (#93).
    if pilihan in ("tidak_relevan", "bukan_dobel", "bukan_tagihan"):
        logger.info("advisor %s user=%s kunci=%s tone=%s", pilihan, user.id, kunci, info.get("tone"))
    if hid:
        await advisor_cache.invalidate_viewer(hid, user.id)


async def batal_dismiss(user, db, kunci: str, *, household_id) -> bool | None:
    """Munculkan lagi insight yang disembunyikan viewer (§9, #91): hapus status dismiss-nya
    lalu cache dashboard viewer, supaya muatan berikutnya langsung menampilkannya.
    None = Redis gagal (route membalas 503)."""
    ada = await advisor_cache.hapus_dismiss(user.id, kunci)
    logger.info("advisor batal_dismiss user=%s kunci=%s ada=%s", user.id, kunci, ada)
    hid = _sid(household_id)
    if hid:
        await advisor_cache.invalidate_viewer(hid, user.id)
    return ada
