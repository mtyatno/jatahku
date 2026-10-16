"""Aturan F. Tabungan & target — TAB-01..07 (02-aturan.md §6F). Fungsi murni `(Konteks) → [Insight]`.

Angka dari metrics.py (G1–G8: saldo, setoran, setoran biasa, target, cakupan darurat).

Penekanan 7 (tidak menyarankan menabung saat defisit) diterapkan di sini: bila PER-01 atau
PER-02 menyala (kekurangan proyeksi > 0 atau sisa bebas < 0), CTA "Setor" diganti
"Rencanakan di alokasi berikutnya" dan rupiah terdampak = 0; TAB-02 bertenggat ≤ 1 bulan
dikecualikan.

Keputusan kecil S4 (juga di SESI-LOG.md):
- TAB-01 target dana darurat = Σ target goal di amplop darurat; tanpa goal = 3 × belanja
  bulanan (G7), ambang "cukup". Setoran saran = (target − saldo) ÷ bulan tersisa (÷ 24 tanpa
  tenggat, G5) dikurangi setoran periode ini.
- TAB-01 U = 0,2 di semua tingkat cakupan (contoh §12: skor 23 dengan cakupan 0,11 bulan).
- TAB-03 "dua periode berturut-turut" = periode lalu dan periode berjalan tanpa setoran, dan
  target pernah disetori sebelumnya atau sudah punya saldo (target baru tidak langsung ditegur).
- TAB-05 tercapai tampil sebagai chip ok; "tampil sekali lalu diam" lewat dismiss.
- TAB-07 selalu ada sebagai cadangan chip Tabungan (setoran periode ini, bisa Rp0).
"""
from __future__ import annotations

from decimal import Decimal

from app.services.advisor.formatting import _median_decimal
from app.services.advisor.insight import Insight, Konteks
from app.services.advisor.metrics import rupiah
from app.services.advisor.rules.periode import _kekurangan_menyala

ZERO = Decimal("0")
RENCANAKAN = {"kind": "route", "kode": "rencanakan_alokasi", "payload": {"path": "/allocate?new=1"}}
LIHAT_TARGET = {"kind": "route", "kode": "lihat_target", "payload": {"path": "/envelopes"}}


def defisit(ctx: Konteks) -> bool:
    """PER-01 atau PER-02 menyala (penekanan 7)."""
    return _kekurangan_menyala(ctx.m) or ctx.m.sisa_bebas < 0


def _bulan_lagi(ctx: Konteks, tanggal) -> int:
    t = ctx.m.today
    return (tanggal.year - t.year) * 12 + tanggal.month - t.month


def _setor(ctx: Konteks, eid: str, jumlah: Decimal, kode: str = "setor") -> dict:
    return {"kind": "plan", "kode": kode, "payload": {"kebutuhan": [{"tujuan_id": eid, "jumlah": rupiah(jumlah)}]}}


def _aksi_setor(ctx: Konteks, eid: str, jumlah: Decimal, tunda: bool, kode: str = "setor") -> tuple[list, Decimal]:
    """(aksi, rupiah terdampak) dengan penekanan 7."""
    if tunda:
        return [RENCANAKAN], ZERO
    if rupiah(jumlah) and rupiah(jumlah) > 0:
        return [_setor(ctx, eid, jumlah, kode)], jumlah
    return [], ZERO


def tab_01(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    if not m.amplop_darurat or m.cakupan_darurat is None:
        return []
    darurat = set(m.amplop_darurat)
    eid = m.amplop_darurat[0]
    saldo = sum((m.saldo_tabungan.get(e, ZERO) for e in darurat), ZERO)
    goals = [g for g in m.target if g["envelope_id"] in darurat]
    if goals:
        target = sum((g["target"] for g in goals), ZERO)
        saran = sum((g["butuh_per_bulan"] for g in goals), ZERO)
    else:
        target = m.belanja_bulanan * k.darurat_cukup_bulan
        saran = max(target - saldo, ZERO) / 24
    saran = max(saran - sum((m.setoran[e][-1] for e in darurat if e in m.setoran), ZERO), ZERO)
    g8 = m.cakupan_darurat
    tone = "ok" if g8 >= k.darurat_cukup_bulan else "info"
    tunda = defisit(ctx)
    aksi, rp = ([], ZERO) if tone == "ok" else _aksi_setor(ctx, eid, saran, tunda, "setor_darurat")
    return [Insight(
        aturan="TAB-01", entitas=eid, tone=tone,
        slot=("kpi:tabungan", "amplop") if tone == "ok" else ("daftar", "kpi:tabungan", "amplop"),
        data={"amplop_id": eid, "nama": ctx.nama.get(eid, ""), "saldo": saldo, "target": target,
              "ada_target": bool(goals), "progres": saldo / target if target > 0 else None, "cakupan": g8,
              "saran": saran, "tunda": tunda},
        aksi=aksi, rupiah=rp, amplop_id=eid,
    )]


def tab_02(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    goals = {g.id: g for g in ctx.snap.goals}
    tunda_umum = defisit(ctx)
    out = []
    for g in m.target:
        gs = goals.get(g["goal_id"])
        if g["tanpa_tenggat"] or gs is None or gs.target_date is None or (g["progres"] or ZERO) >= 1:
            continue
        g3 = m.setoran_biasa.get(g["envelope_id"], ZERO)
        g5 = g["butuh_per_bulan"]
        if g5 <= g3 * k.target_tertinggal:
            continue
        bulan = _bulan_lagi(ctx, gs.target_date)
        ini = m.setoran.get(g["envelope_id"], [ZERO])[-1]
        kurang = max(g5 - ini, ZERO)
        tunda = tunda_umum and bulan > k.tenggat_nyata_bulan
        aksi, rp = _aksi_setor(ctx, g["envelope_id"], kurang, tunda)
        aksi.append({**LIHAT_TARGET, "kode": "mundurkan_tenggat"})
        dekat = bulan <= k.tenggat_dekat_bulan
        out.append(Insight(
            aturan="TAB-02", entitas=g["goal_id"], tone="warn" if dekat else "info",
            slot=("daftar", "kpi:tabungan", "amplop", "alokasi"),
            data={"amplop_id": g["envelope_id"], "nama": g["nama"], "butuh": g5, "biasa": g3,
                  "tenggat": gs.target_date, "kurang": kurang, "tunda": tunda},
            aksi=aksi, rupiah=rp, urgensi=Decimal("0.6") if dekat else Decimal("0.2"),
            amplop_id=g["envelope_id"],
        ))
    return out


def tab_03(ctx: Konteks) -> list[Insight]:
    m = ctx.m
    tunda = defisit(ctx)
    out = []
    for g in m.target:
        if (g["progres"] or ZERO) >= 1:
            continue
        setoran = m.setoran.get(g["envelope_id"], [])
        if len(setoran) < 2 or setoran[-1] > 0 or setoran[-2] > 0:
            continue
        if not (any(v > 0 for v in setoran[:-2]) or g["saldo"] > 0):
            continue
        aksi, rp = _aksi_setor(ctx, g["envelope_id"], g["butuh_per_bulan"], tunda)
        out.append(Insight(
            aturan="TAB-03", entitas=g["goal_id"], tone="info", slot=("daftar", "kpi:tabungan", "amplop"),
            data={"amplop_id": g["envelope_id"], "nama": g["nama"], "saran": g["butuh_per_bulan"],
                  "saldo": g["saldo"], "target": g["target"], "tunda": tunda},
            aksi=aksi, rupiah=rp, amplop_id=g["envelope_id"],
        ))
    return out


def tab_04_05(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    tunda = defisit(ctx)
    out = []
    for g in m.target:
        p = g["progres"]
        if p is None or p < k.hampir_tercapai:
            continue
        data = {"amplop_id": g["envelope_id"], "nama": g["nama"], "saldo": g["saldo"], "target": g["target"],
                "kurang": max(g["target"] - g["saldo"], ZERO), "progres": p, "tunda": tunda}
        if p >= 1:
            out.append(Insight(aturan="TAB-05", entitas=g["goal_id"], tone="ok", slot=("kpi:tabungan", "amplop"),
                               data=data, aksi=[LIHAT_TARGET], amplop_id=g["envelope_id"]))
            continue
        aksi, _ = _aksi_setor(ctx, g["envelope_id"], data["kurang"], tunda, "setor_sisanya")
        out.append(Insight(aturan="TAB-04", entitas=g["goal_id"], tone="ok", slot=("kpi:tabungan", "amplop"),
                           data=data, aksi=aksi, amplop_id=g["envelope_id"]))
    return out


def tab_06(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    aktif = [g for g in m.target if g["progres"] is not None and g["progres"] < 1]
    if len(aktif) < k.target_paralel_n:
        return []
    median = _median_decimal([g["progres"] for g in aktif])
    if median >= k.target_paralel_progres:
        return []
    return [Insight(
        aturan="TAB-06", entitas=m.period_start.isoformat(), tone="info", slot=("daftar", "kpi:tabungan"),
        data={"n": len(aktif), "median": median},
        aksi=[{**LIHAT_TARGET, "kode": "atur_prioritas"}],
    )]


def tab_07(ctx: Konteks) -> list[Insight]:
    m = ctx.m
    if not m.saldo_tabungan:
        return []
    setoran = sum((v[-1] for v in m.setoran.values()), ZERO)
    return [Insight(
        aturan="TAB-07", entitas=m.period_start.isoformat(), tone="ok", slot=("kpi:tabungan",),
        data={"setoran": setoran, "saldo": sum(m.saldo_tabungan.values(), ZERO)},
    )]


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*tab_01(ctx), *tab_02(ctx), *tab_03(ctx), *tab_04_05(ctx), *tab_06(ctx), *tab_07(ctx)]
