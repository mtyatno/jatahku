"""Aturan A. Hari ini — HAR-01..05 (02-aturan.md §6A). Fungsi murni `(Konteks) → [Insight]`.

Angka dari metrics.py (T5 belanja variabel hari ini, J0, J1), penyumbang dari sinyal
S1 (struk) dan `variabel_hari_ini_per_amplop`. Tanpa teks: render.py merakit kalimat.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.advisor.insight import Insight, Konteks
from app.services.advisor.metrics import variabel_hari_ini_per_amplop
from app.services.advisor.signals import biasa_mencatat

ZERO = Decimal("0")


def _route_hari_ini(ctx: Konteks, amplop_id: str | None = None) -> dict:
    path = f"/transactions?date={ctx.m.today.isoformat()}"
    if amplop_id:
        path += f"&envelope={amplop_id}"
    return {"kind": "route", "kode": "lihat_transaksi_hari_ini", "payload": {"path": path}}


def _penyumbang(ctx: Konteks, per_amplop: dict) -> tuple[dict | None, tuple[str, Decimal] | None]:
    """(penyumbang untuk isi, amplop terbesar). Penyumbang = struk terbesar bila ≥ 40% T5."""
    m, s = ctx.m, ctx.s
    t5 = m.belanja_hari_ini
    terbesar = max(per_amplop.items(), key=lambda kv: (kv[1], kv[0])) if per_amplop else None
    by_id = {x.id: x for x in ctx.snap.transactions}
    best = None
    for st in s.struk:
        jumlah = sum(
            (by_id[i].amount for i in st.txn_ids
             if i in by_id and by_id[i].transaction_date == m.today and m.jenis_transaksi.get(i) == "variabel"),
            ZERO,
        )
        if jumlah > 0 and (best is None or jumlah > best[1]):
            best = (st, jumlah)
    if best is not None and t5 > 0 and best[1] >= t5 * ctx.k.penyumbang_struk:
        return {"jenis": "struk", "nama": best[0].toko, "jumlah": best[1], "porsi": best[1] / t5}, terbesar
    if terbesar is not None and t5 > 0:
        return {"jenis": "amplop", "nama": ctx.nama.get(terbesar[0], ""), "amplop_id": terbesar[0],
                "jumlah": terbesar[1], "porsi": terbesar[1] / t5}, terbesar
    return None, terbesar


def har_01_02_04(ctx: Konteks) -> list[Insight]:
    """HAR-01 lewat jatah · HAR-02 mendekati jatah · HAR-04 hari ini aman (salah satu)."""
    m, k = ctx.m, ctx.k
    t5, j0 = m.belanja_hari_ini, m.j0
    hari = m.today.isoformat()
    if t5 > j0:
        rasio = t5 / j0 if j0 > 0 else None
        danger = rasio is None or rasio >= k.danger_lewat_jatah
        per_amplop = variabel_hari_ini_per_amplop(ctx.snap, m)
        penyumbang, terbesar = _penyumbang(ctx, per_amplop)
        aksi = [_route_hari_ini(ctx)]
        batas_id = None
        if terbesar is not None and terbesar[1] >= t5 * k.penyumbang_amplop_cta:
            batas_id = terbesar[0]
            if k.cta_batas_harian:
                aksi.append({"kind": "daily_limit", "kode": "batas_harian", "payload": {"amplop_id": batas_id}})
        aksi.append({"kind": "chat", "kode": "tanya_hari_ini", "payload": {}})
        return [Insight(
            aturan="HAR-01", entitas=hari, tone="danger" if danger else "warn",
            slot=("kpi:jatah", "daftar") if danger else ("kpi:jatah",),
            data={"t5": t5, "j0": j0, "j1": m.j1, "r": m.sisa_hari, "rasio": rasio, "lebih": t5 - j0,
                  "penyumbang": penyumbang,
                  "terbesar": ({"amplop_id": terbesar[0], "nama": ctx.nama.get(terbesar[0], ""),
                                "jumlah": terbesar[1], "porsi": terbesar[1] / t5} if terbesar else None),
                  "batas_amplop_id": batas_id},
            aksi=aksi, rupiah=t5 - j0, urgensi=Decimal("1"),
        )]
    if j0 > 0 and t5 >= j0 * k.mendekati_jatah:
        return [Insight(
            aturan="HAR-02", entitas=hari, tone="warn", slot=("kpi:jatah",),
            data={"t5": t5, "j0": j0, "sisa": j0 - t5, "j1": m.j1, "r": m.sisa_hari},
            aksi=[_route_hari_ini(ctx)],
        )]
    return [Insight(
        aturan="HAR-04", entitas=hari, tone="ok" if j0 > 0 else "info", slot=("kpi:jatah",),
        data={"t5": t5, "j0": j0, "sisa": max(j0 - t5, ZERO), "j1": m.j1, "r": m.sisa_hari},
    )]


def har_03(ctx: Konteks) -> list[Insight]:
    """HAR-03 belanja besar satu kali: outlier (S2) hari ini. Satu insight per transaksi."""
    m = ctx.m
    out = []
    for o in ctx.s.outlier:
        if not o["hari_ini"]:
            continue
        out.append(Insight(
            aturan="HAR-03", entitas=o["txn_id"], tone="info", slot=("kpi:jatah", "transaksi"),
            data={"jumlah": o["jumlah"], "amplop_id": o["envelope_id"],
                  "amplop": ctx.nama.get(o["envelope_id"], ""), "j1": m.j1, "r": m.sisa_hari,
                  "txn_id": o["txn_id"]},
            aksi=[_route_hari_ini(ctx, o["envelope_id"])],
            amplop_id=o["envelope_id"],
        ))
    return out


def har_05(ctx: Konteks) -> list[Insight]:
    """HAR-05 belum ada catatan hari ini: jam ≥ 20.00, viewer belum mencatat, biasanya mencatat tiap hari."""
    snap, m = ctx.snap, ctx.m
    if ctx.jam < ctx.k.jam_belum_catat:
        return []
    if any(x.user_id == snap.viewer_id and x.transaction_date == m.today for x in snap.transactions):
        return []
    if not biasa_mencatat(snap):
        return []
    return [Insight(
        aturan="HAR-05", entitas=m.today.isoformat(), tone="info", slot=("kpi:jatah",),
        data={}, aksi=[{"kind": "expense", "kode": "catat", "payload": {}}],
    )]


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*har_01_02_04(ctx), *har_03(ctx), *har_05(ctx)]
