"""Seleksi AI Advisor v2 (02-aturan.md §5 skor & penekanan, §7 seleksi per slot, §9 anti-ganggu).

`pilih(ctx, insights, dismiss) -> Seleksi`, fungsi murni:
1. keyakinan rendah → tone maksimal warn, tanpa CTA pemindah dana (§5);
2. SATU rencana dana untuk semua CTA `plan` (§8.4), lalu batas harian & "maksimal/hari"
   dari bebas_setelah_rencana (penekanan 8);
3. skor (§5) dan penekanan 1–8;
4. dismiss (§9): disembunyikan kecuali tone naik atau rupiah terdampak naik ≥ 50%;
5. chip per kartu KPI (urutan §7) dan daftar kartu AI Advisor (maks 3, 1 per amplop
   kecuali danger, 2 per domain), sisanya "+N saran lain", kosong → satu kabar baik.

Keputusan kecil S3 (juga di SESI-LOG.md):
- Chip mengikuti urutan prioritas kartu; di dalam satu aturan, skor tertinggi.
- Penekanan 6 tidak menaikkan tone PER-01 (contoh §12: PER-01 tetap warn walau HAR-01
  danger); penggabungan entitas yang sama (penekanan 1/3, TAG menyerap AMP-01) mengikuti
  tone & skor tertinggi.
- Insight yang di-dismiss juga tidak dipakai chip; chip jatuh ke aturan berikutnya.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.services.advisor.insight import (
    TONE_URUT, Insight, Konteks, hitung_skor, kunci_urut, terapkan_keyakinan,
)
from app.services.advisor.metrics import rupiah

ZERO = Decimal("0")

URUTAN_KPI: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "jatah": (("HAR-01", "HAR-03", "HAR-02", "HAR-05"), ("HAR-04",)),
    "sisa_bebas": (("PER-02", "PER-01", "PER-06"), ("PER-04", "PER-05", "PER-07")),
    "terpakai": (("PER-01", "PER-03", "AMP-08"), ("PER-05", "PER-07")),
    "income": (("INC-01", "INC-04", "INC-03", "INC-06", "INC-02"), ("INC-05",)),
    "tagihan": (("TAG-01", "TAG-02", "TAG-04", "TAG-03"), ("TAG-09",)),
    "tabungan": (("TAB-02", "TAB-01", "TAB-03", "TAB-06", "TAB-04", "TAB-05"), ("TAB-07",)),
}

DISERAP_KEKURANGAN = {"AMP-02", "AMP-03"}   # penekanan 2
TAGIHAN_PENYERAP = {"TAG-01", "TAG-02"}      # penekanan 3


@dataclass
class Seleksi:
    semua: list[Insight]                       # setelah keyakinan, rencana, skor, penekanan
    kpi: dict[str, Insight | None]
    daftar: list[Insight]
    sisa: list[Insight]
    aman: Insight | None
    redam: bool
    rencana: object | None = None              # planner.Rencana
    batas: dict = field(default_factory=dict)
    disembunyikan: list[str] = field(default_factory=list)


# ── anti-ganggu (§9) ─────────────────────────────────────────────────────
def tersembunyi(ins: Insight, dismiss: dict) -> bool:
    """`dismiss[kunci]` = {"pilihan", "tone", "rupiah"} yang masih berlaku (TTL di Redis).
    Muncul lagi lebih awal bila tone naik atau rupiah terdampak naik ≥ 50%."""
    d = dismiss.get(ins.id)
    if not d:
        return False
    tone_lama = d.get("tone")
    if tone_lama in TONE_URUT and TONE_URUT.get(ins.tone, 9) < TONE_URUT[tone_lama]:
        return False
    rp_lama = Decimal(str(d.get("rupiah") or 0))
    if rp_lama > 0 and ins.rupiah >= rp_lama * Decimal("1.5"):
        return False
    return True


# ── rencana dana bersama (§8.4, penekanan 8) ─────────────────────────────
def kebutuhan_bersama(insights: list[Insight]) -> list[dict]:
    """Kebutuhan semua CTA `plan`, urut tone/skor insight, digabung per (tujuan, tagihan); maks 10."""
    gabung: dict[tuple, dict] = {}
    for ins in sorted(insights, key=kunci_urut):
        for a in ins.aksi:
            if a["kind"] != "plan":
                continue
            for kb in a["payload"].get("kebutuhan", []):
                key = (str(kb["tujuan_id"]), kb.get("bayar_recurring_id"))
                if key in gabung:
                    gabung[key]["jumlah"] = max(gabung[key]["jumlah"], kb["jumlah"])
                else:
                    gabung[key] = dict(kb)
    return list(gabung.values())[:10]


def _rencana(ctx: Konteks, insights: list[Insight]):
    from app.services.advisor.planner import PlanInputError, batas_harian_setelah_rencana, susun_rencana
    keb = kebutuhan_bersama(insights)
    rencana = None
    if keb:
        try:
            rencana = susun_rencana(ctx.snap, ctx.m, keb)
        except PlanInputError:
            rencana = None
    return rencana, batas_harian_setelah_rencana(ctx.m, rencana)


def _isi_batas(insights: list[Insight], batas: dict) -> None:
    for ins in insights:
        eid = ins.data.get("batas_amplop_id")
        if eid is not None:
            ins.data["batas"] = batas.get(eid)
        aksi = []
        for a in ins.aksi:
            if a["kind"] == "daily_limit":
                jumlah = rupiah(batas.get(a["payload"].get("amplop_id"), ZERO))
                if not jumlah or jumlah <= 0:
                    continue
                a = {**a, "payload": {**a["payload"], "jumlah": jumlah}}
            aksi.append(a)
        ins.aksi = aksi


# ── penekanan (§5) ───────────────────────────────────────────────────────
def _serap(induk: Insight, anak: Insight, naikkan: bool) -> None:
    induk.rincian.append(anak)
    if naikkan:
        if TONE_URUT.get(anak.tone, 9) < TONE_URUT.get(induk.tone, 9):
            induk.tone = anak.tone
        induk.skor = max(induk.skor, anak.skor)


def penekanan(insights: list[Insight]) -> set[str]:
    """Jalankan penekanan 2, 3, 6. Kembalikan id insight yang keluar dari daftar
    (tetap boleh tampil di slot lain, mis. HAR-01 di chip Jatah hari ini)."""
    keluar: set[str] = set()
    per01 = next((i for i in insights if i.aturan == "PER-01"), None)
    if per01 is not None:
        for ins in insights:
            if ins.aturan == "HAR-01":                       # penekanan 6
                per01.data["har01"] = {"rasio": ins.data.get("rasio"), "lebih": ins.data.get("lebih")}
                _serap(per01, ins, naikkan=False)
                keluar.add(ins.id)
            elif ins.aturan in DISERAP_KEKURANGAN:           # penekanan 2
                _serap(per01, ins, naikkan=False)
                keluar.add(ins.id)
    for tag in [i for i in insights if i.aturan in TAGIHAN_PENYERAP and i.amplop_id]:
        for ins in insights:                                 # penekanan 3
            if ins.aturan == "AMP-01" and ins.amplop_id == tag.amplop_id and ins.id not in keluar:
                _serap(tag, ins, naikkan=True)
                keluar.add(ins.id)
    return keluar


# ── slot ─────────────────────────────────────────────────────────────────
def pilih_kpi(insights: list[Insight], kartu: str) -> Insight | None:
    urutan, cadangan = URUTAN_KPI[kartu]
    slot = f"kpi:{kartu}"
    for daftar in (urutan, cadangan):
        for aturan in daftar:
            calon = [i for i in insights if i.aturan == aturan and i.di_slot(slot)]
            if calon:
                return max(calon, key=lambda i: (i.skor, i.rupiah, i.id))
    return None


def pilih_daftar(insights: list[Insight], ctx: Konteks) -> tuple[list[Insight], list[Insight]]:
    k = ctx.k
    calon = [i for i in insights if i.di_slot("daftar") and i.punya_aksi() and i.tone in ("danger", "warn")]
    if len(calon) < k.daftar_maks:
        calon += [i for i in insights if i.di_slot("daftar") and i.punya_aksi() and i.tone == "info"]
    calon.sort(key=kunci_urut)
    tampil, sisa = [], []
    per_domain: dict[str, int] = {}
    amplop: set[str] = set()
    for ins in calon:
        if len(tampil) >= k.daftar_maks:
            sisa.append(ins)
            continue
        if ins.amplop_id and ins.tone != "danger" and ins.amplop_id in amplop:
            sisa.append(ins)
            continue
        if per_domain.get(ins.domain, 0) >= k.daftar_per_domain:
            sisa.append(ins)
            continue
        tampil.append(ins)
        per_domain[ins.domain] = per_domain.get(ins.domain, 0) + 1
        if ins.amplop_id:
            amplop.add(ins.amplop_id)
    return tampil, sisa


def redam_chip(kpi: dict[str, Insight | None], ctx: Konteks) -> bool:
    tones = [i.tone for i in kpi.values() if i is not None]
    return tones.count("danger") >= ctx.k.redam_danger or tones.count("warn") >= ctx.k.redam_warn


# ── utama ────────────────────────────────────────────────────────────────
def pilih(ctx: Konteks, insights: list[Insight], dismiss: dict | None = None) -> Seleksi:
    dismiss = dismiss or {}
    for ins in insights:
        terapkan_keyakinan(ins)
    rencana, batas = _rencana(ctx, insights)
    ctx.batas = batas
    _isi_batas(insights, batas)
    for ins in insights:
        ins.skor = hitung_skor(ins, ctx.m.dana_belanja)
    keluar_daftar = penekanan(insights)

    hidden = [i.id for i in insights if tersembunyi(i, dismiss)]
    terlihat = [i for i in insights if i.id not in hidden]
    kpi = {kartu: pilih_kpi(terlihat, kartu) for kartu in URUTAN_KPI}
    daftar, sisa = pilih_daftar([i for i in terlihat if i.id not in keluar_daftar], ctx)
    aman = None
    if not daftar:
        oks = [i for i in terlihat if i.tone == "ok"]
        aman = min(oks, key=kunci_urut) if oks else None
    return Seleksi(semua=insights, kpi=kpi, daftar=daftar, sisa=sisa, aman=aman,
                   redam=redam_chip(kpi, ctx), rencana=rencana, batas=batas, disembunyikan=hidden)
