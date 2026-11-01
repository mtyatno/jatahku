"""Halaman di luar Beranda (02-aturan.md §7 "Halaman lain"; 04-kontrak-api.md).

Semua halaman memakai analisa yang sama dengan Beranda (`dashboard.analisa`: metrik, sinyal,
semua aturan, rencana bersama, skor, keyakinan, dismiss viewer), lalu memilah insight untuk
halaman itu. Modul ini hanya memilih dan membentuk payload (angka dari metrics.py, kalimat dari
render.py). Fungsi `susun_*` murni (dites dengan fixture). Tanpa cache Redis: halaman ini jarang
dibuka, dan cache Beranda tidak boleh tertimpa.

## Amplop — `GET /advisor/page/amplop` (S11)
Satu insight terbaik per kartu amplop, dari AMP-* dan TAG-* amplop itu, ditambah TAB-* untuk
amplop tabungan. Tidak ada yang menyala → baris dasar ("Aman, ±{rp}/hari tersedia"; tabungan:
saldo).

Keputusan kecil S11 (juga di SESI-LOG.md):
- Urutan per kartu = urutan daftar (§5): kelompok tone dulu, skor di dalamnya.
- Insight yang diserap insight lain di amplop yang sama (AMP-01 oleh TAG-01/02, penekanan 3)
  tidak dipilih; yang diserap insight tingkat periode (AMP-02/03 oleh PER-01, AMP-01 oleh
  PER-02) tetap tampil di kartunya, karena PER-* tidak punya slot amplop.
- Insight yang di-dismiss viewer dilewati; bila semua calon kartu itu di-dismiss, kartu
  tanpa strip (bukan "Aman" — masalahnya masih ada, hanya disembunyikan).
- "Maksimal/hari" baris aman memakai bebas_setelah_rencana (penekanan 8), sama dengan chip.
- Tabungan: "Setor" disembunyikan saat defisit (penekanan 7, `tabungan.defisit`).

## Langganan — `GET /advisor/page/langganan` (S12)
TAG-* + ringkasan K4.

Keputusan kecil S12 (juga di SESI-LOG.md):
- Per baris = satu insight terbaik (urut tone lalu skor) dari TAG-01/02/03/04/06 dan DAT-06
  untuk langganan itu. TAG-07 (pola rutin) → `pola`, TAG-08 (ganda) → `lain` dengan
  `recurring_ids`, TAG-05/TAG-09 → `ringkasan.insight` (TAG-05 bila menyala, selain itu TAG-09).
- Insight yang di-dismiss tidak tampil (sama dengan Beranda) dan masuk `disembunyikan`.
"""
from __future__ import annotations

from datetime import datetime

from app.services.advisor import advisor_cache
from app.services.advisor.dashboard import (
    FLAG_KEY, KONSTANTA_KEY, _tz, analisa, bangun_konstanta, flag_aktif, muat_pengaturan,
)
from app.services.advisor.insight import Insight, Konteks, kunci_urut
from app.services.advisor.metrics import batas_harian, rupiah
from app.services.advisor.render import baris_dasar_amplop, judul_pendek, render_insight
from app.services.advisor.rules.tabungan import defisit


# ── Amplop (S11) ─────────────────────────────────────────────────────────
DOMAIN_AMPLOP = {"AMP", "TAG"}


def calon_amplop(ins: Insight, kelompok: str) -> bool:
    if not ins.di_slot("amplop") or not ins.amplop_id:
        return False
    return ins.domain in DOMAIN_AMPLOP or (ins.domain == "TAB" and kelompok == "tabungan")


def dasar_amplop(ctx: Konteks, eid: str) -> dict:
    """Data baris dasar (tanpa teks) untuk `render.baris_dasar_amplop`."""
    m = ctx.m
    a = m.amplop[eid]
    d = {"amplop_id": eid, "nama": a.nama, "pe": m.period_end}
    if a.kelompok == "tabungan":
        return {**d, "jenis": "tabungan", "saldo": m.saldo_tabungan.get(eid, a.sisa),
                "ada_target": any(g["envelope_id"] == eid for g in m.target), "boleh_setor": not defisit(ctx)}
    if a.bebas <= 0:
        return {**d, "jenis": "terpakai", "bebas": a.bebas}
    batas = ctx.batas.get(eid)
    return {**d, "jenis": "aman", "bebas": a.bebas, "hari_terakhir": m.horizon <= 0,
            "batas": batas if batas is not None else batas_harian(a.bebas, m)}


def susun_amplop(ctx: Konteks, sel) -> dict[str, dict | None]:
    """{amplop_id: insight terpilih (bentuk render_insight) | baris dasar | None (semua di-dismiss)}."""
    hidden = set(sel.disembunyikan)
    per_amplop: dict[str, list[Insight]] = {}
    for ins in sel.semua:
        a = ctx.m.amplop.get(ins.amplop_id)
        if a is not None and calon_amplop(ins, a.kelompok):
            per_amplop.setdefault(ins.amplop_id, []).append(ins)

    out: dict[str, dict | None] = {}
    for eid in ctx.m.amplop:
        calon = per_amplop.get(eid, [])
        diserap = {r.id for i in calon for r in i.rincian}
        terlihat = [i for i in calon if i.id not in diserap and i.id not in hidden]
        if terlihat:
            out[eid] = render_insight(min(terlihat, key=kunci_urut), ctx)
        elif calon:
            out[eid] = None
        else:
            out[eid] = baris_dasar_amplop(dasar_amplop(ctx, eid))
    return out


def susun_halaman_amplop(snap, *, now_local: datetime, dismiss: dict | None = None, km=None, ks=None,
                         ka=None) -> dict:
    kw = {k: v for k, v in (("km", km), ("ks", ks), ("ka", ka)) if v is not None}
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, **kw)
    return {"enabled": True, "generated_at": now_local.isoformat(timespec="seconds"),
            "amplop": susun_amplop(ctx, sel)}


async def get_halaman_amplop(user, db, now: datetime | None = None, *, household_id) -> dict:
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    from app.services.advisor.snapshot import load_snapshot
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    return susun_halaman_amplop(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)


# ── Langganan (S12) ──────────────────────────────────────────────────────
BARIS = {"TAG-01", "TAG-02", "TAG-03", "TAG-04", "TAG-06", "DAT-06"}


def _per_baris(insights: list[Insight]) -> dict[str, Insight]:
    out: dict[str, Insight] = {}
    for ins in sorted(insights, key=kunci_urut):
        rid = ins.data.get("recurring_id")
        if ins.aturan in BARIS and rid and rid not in out:
            out[rid] = ins
    return out


def susun_langganan(ctx, sel, *, now_local: datetime, dismiss: dict | None = None) -> dict:
    m = ctx.m
    hidden = set(sel.disembunyikan)
    halaman = [i for i in sel.semua if i.di_slot("langganan")]
    terlihat = [i for i in halaman if i.id not in hidden]

    tag05 = next((i for i in terlihat if i.aturan == "TAG-05"), None)
    tag09 = next((i for i in terlihat if i.aturan == "TAG-09"), None)
    ringkas = tag05 or tag09
    belum = [b for b in m.tagihan if b.sisa > 0]
    return {
        "enabled": True,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "ringkasan": {
            "beban_bulanan": rupiah(m.beban_tagihan_bulanan),
            "beban_persen": round(float(m.beban_tagihan) * 100) if m.beban_tagihan is not None else None,
            "dana_belanja": rupiah(m.dana_belanja),
            "tagihan_sisa": rupiah(m.tagihan_sisa),
            "belum": len(belum),
            "lunas": len([b for b in m.tagihan if b.lunas_oleh]),
            "insight": render_insight(ringkas, ctx) if ringkas else None,
        },
        "per_langganan": {rid: render_insight(ins, ctx) for rid, ins in _per_baris(terlihat).items()},
        "pola": [render_insight(i, ctx) for i in sorted(terlihat, key=kunci_urut) if i.aturan == "TAG-07"],
        "lain": [{**render_insight(i, ctx), "recurring_ids": i.entitas.split("+")}
                 for i in sorted(terlihat, key=kunci_urut) if i.aturan == "TAG-08"],
        "disembunyikan": [{"kunci": i.id, "judul_pendek": judul_pendek(i, ctx),
                           "pilihan": (dismiss or {}).get(i.id, {}).get("pilihan", "nanti")}
                          for i in sorted((i for i in halaman if i.id in hidden), key=kunci_urut)],
    }


async def get_page_langganan(user, db, now: datetime | None = None, *, household_id) -> dict:
    from app.services.advisor.snapshot import load_snapshot
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    return susun_langganan(ctx, sel, now_local=now_local, dismiss=dismiss)
