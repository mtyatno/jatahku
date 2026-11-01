"""`GET /advisor/page/transaksi` — banner & penanda baris halaman Transaksi (S13, 02-aturan.md §7).

- Banner = insight yang relevan dengan filter aktif: filter amplop → AMP-* amplop itu (terbaik
  menurut tone lalu skor); filter tanggal hari ini → isi chip KPI Jatah (HAR-*), sama dengan
  Beranda. Filter amplop menang bila keduanya aktif (lebih sempit). Tanpa filter → null.
- Penanda baris = insight ber-slot `transaksi` (HAR-03, DAT-03 S4/S4b, DAT-06, TAG-06, TAG-07),
  dipetakan ke id transaksi yang ditandai:
  HAR-03/DAT-06/TAG-06 → `txn_id`; DAT-03 dobel → semua anggota pasangan; DAT-03 struk →
  barang di struk kedua; TAG-07 → kemunculan terakhir pola itu.
- Insight yang sedang di-dismiss viewer tidak ditampilkan (dismiss sama dengan Beranda, §9).

Murni sampai `susun_halaman`; `get_halaman_transaksi` mengurus flag, jam, dan DB. Teks tetap
dari `render.py`; tidak ada angka baru (semua dari metrics/signals lewat `analisa`).
"""
from __future__ import annotations

from datetime import date, datetime

from app.services.advisor import advisor_cache
from app.services.advisor.dashboard import (
    FLAG_KEY, KONSTANTA_KEY, KA_DEFAULT, KM_DEFAULT, KS_DEFAULT, _tz, analisa, bangun_konstanta, flag_aktif,
    muat_pengaturan,
)
from app.services.advisor.insight import Insight, kunci_urut
from app.services.advisor.render import render_insight


def txn_ditandai(ins: Insight) -> list[str]:
    """Id transaksi yang diberi penanda untuk satu insight ber-slot `transaksi`."""
    d = ins.data
    if ins.aturan == "DAT-03":
        return list(d.get("txn_ids") or [])
    if ins.aturan == "TAG-07":
        return list(d.get("txn_ids") or [])[-1:]      # urut tanggal: kemunculan terakhir
    return [d["txn_id"]] if d.get("txn_id") else []


def pilih_banner(ctx, sel, *, tanggal: date | None, amplop: str | None) -> Insight | None:
    terlihat = [i for i in sel.semua if i.id not in sel.disembunyikan]
    if amplop:
        calon = [i for i in terlihat if i.domain == "AMP" and str(i.amplop_id) == amplop]
        return min(calon, key=kunci_urut) if calon else None
    if tanggal == ctx.m.today:
        return sel.kpi.get("jatah")
    return None


def susun_halaman(snap, *, now_local: datetime, tanggal: date | None = None, amplop: str | None = None,
                  dismiss: dict | None = None, km=KM_DEFAULT, ks=KS_DEFAULT, ka=KA_DEFAULT) -> dict:
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    banner = pilih_banner(ctx, sel, tanggal=tanggal, amplop=amplop)
    penanda: dict[str, list[dict]] = {}
    for ins in sorted((i for i in sel.semua if i.di_slot("transaksi") and i.id not in sel.disembunyikan),
                      key=kunci_urut):
        ids = txn_ditandai(ins)
        if not ids:
            continue
        r = render_insight(ins, ctx)
        for tid in ids:
            penanda.setdefault(str(tid), []).append(r)
    return {
        "enabled": True,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "hari_ini": ctx.m.today.isoformat(),
        "banner": render_insight(banner, ctx) if banner else None,
        "penanda": penanda,
    }


async def get_halaman_transaksi(user, db, *, tanggal: date | None = None, amplop: str | None = None,
                                now: datetime | None = None, household_id) -> dict:
    from app.services.advisor.snapshot import load_snapshot
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    return susun_halaman(snap, now_local=now_local, tanggal=tanggal, amplop=amplop, dismiss=dismiss,
                         km=km, ks=ks, ka=ka)
