"""Aturan C. Amplop — AMP-01..11 (02-aturan.md §6C). Fungsi murni `(Konteks) → [Insight]`.

Angka dari metrics.py (M1–M13, riwayat) dan sinyal (S5 lonjakan, S7 menganggur, S8/S9
kronis, S17 tren). Tanpa teks: render.py merakit kalimat.

Keputusan kecil S4 (juga di SESI-LOG.md):
- AMP-01 untuk semua amplop terlihat yang sisa(e) < 0 (belanja dan tabungan); amplop
  tagihan diserap TAG-01/02 di select.py (penekanan 3).
- AMP-02 "habis" = bebas(e) ≤ 0 dan sisa(e) ≥ 0: dananya habis atau tinggal yang sudah
  tersisih untuk tagihan. Kebutuhan geser = laju × r − bebas.
- AMP-02/03 butuh laju (d ≥ 3); keyakinan memakai §5 proyeksi dengan transaksi variabel
  amplop itu di jendela laju.
- AMP-04 tanpa laju (d < 3) tidak memberi CTA naikkan jatah (kebutuhan per periode belum ada).
- AMP-06 memakai kind `raise_budget` juga untuk menurunkan jatah (payload jumlah baru).
- AMP-10 hanya untuk amplop yang punya `daily_limit`; CTA penyesuaian ikut flag
  `cta_batas_harian` (§2). "Biarkan" = sembunyikan periode ini.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

from app.services.advisor.insight import Insight, Konteks, keyakinan_proyeksi
from app.services.advisor.metrics import (
    batas_harian, ceil10rb, jumlah_transaksi_laju_amplop, rupiah, variabel_harian_amplop,
)
from app.services.advisor.rules.periode import _kekurangan_menyala

ZERO = Decimal("0")


def _env(ctx: Konteks, eid: str):
    return next((e for e in ctx.snap.envelopes if e.id == eid), None)


def _route_amplop(eid: str, kode: str = "lihat_transaksi_amplop") -> dict:
    return {"kind": "route", "kode": kode, "payload": {"path": f"/transactions?envelope={eid}"}}


def _habis(ctx: Konteks, a) -> tuple:
    """(tanggal habis, hari sampai habis) dari bebas(e) ÷ laju(e); (None, None) bila tidak habis."""
    if a.laju is None or a.laju <= 0:
        return None, None
    if a.bebas <= 0:
        return ctx.m.today, 0
    hari = int((a.bebas / a.laju).to_integral_value(rounding=ROUND_FLOOR)) + 1
    return ctx.m.today + timedelta(days=hari), hari


def kekurangan_amplop(ctx: Konteks) -> dict[str, dict]:
    """Amplop belanja yang minus / AMP-02 (habis) / AMP-03 (akan habis), dengan kekurangan
    sisa periode laju × r − bebas. Dipakai AMP-02/03 dan AMP-04 ("habis/akan habis sekarang")."""
    m = ctx.m
    out = {}
    if m.sisa_hari <= 0:
        return out
    for a in m.amplop.values():
        if a.kelompok != "belanja" or a.laju is None or a.laju <= 0:
            continue
        perlu = a.laju * m.sisa_hari
        if a.sisa < 0:      # minus: AMP-01 yang tampil, tapi AMP-04 tetap menghitungnya "habis sekarang"
            out[a.id] = {"aturan": "AMP-01", "perlu": perlu, "kurang": perlu - a.bebas}
        elif a.bebas <= 0 <= a.sisa:
            out[a.id] = {"aturan": "AMP-02", "perlu": perlu, "kurang": perlu - a.bebas}
        elif a.bebas > 0 and perlu > a.bebas:
            out[a.id] = {"aturan": "AMP-03", "perlu": perlu, "kurang": perlu - a.bebas}
    return out


def amp_01(ctx: Konteks) -> list[Insight]:
    out = []
    for a in ctx.m.amplop.values():
        if a.sisa >= 0:
            continue
        out.append(Insight(
            aturan="AMP-01", entitas=a.id, tone="danger", slot=("daftar", "amplop"),
            data={"amplop_id": a.id, "nama": a.nama, "minus": -a.sisa, "dana": a.dana, "terpakai": a.terpakai,
                  "tambalan_n": a.tambalan_n},
            aksi=[{"kind": "plan", "kode": "tutup_minus_amplop",
                   "payload": {"kebutuhan": [{"tujuan_id": a.id, "jumlah": rupiah(-a.sisa)}]}}],
            rupiah=-a.sisa, urgensi=Decimal("1"), amplop_id=a.id,
        ))
    return out


def amp_02_03(ctx: Konteks, kurang: dict) -> list[Insight]:
    m, k = ctx.m, ctx.k
    out = []
    for eid, kb in kurang.items():
        if kb["aturan"] == "AMP-01":
            continue
        a = m.amplop[eid]
        habis, hari = _habis(ctx, a)
        dekat = hari is not None and hari <= k.danger_habis_hari
        yakin = keyakinan_proyeksi(m.hari_ke, jumlah_transaksi_laju_amplop(ctx.snap, m, eid), k)
        geser = {"kind": "plan", "kode": "geser_amplop",
                 "payload": {"kebutuhan": [{"tujuan_id": eid, "jumlah": rupiah(kb["kurang"])}]}}
        data = {"amplop_id": eid, "nama": a.nama, "bebas": a.bebas, "laju": a.laju, "r": m.sisa_hari,
                "pe": m.period_end, "perlu": kb["perlu"], "kurang": kb["kurang"], "habis": habis,
                "batas_amplop_id": eid, "batas": batas_harian(a.bebas, m)}
        if kb["aturan"] == "AMP-02":
            out.append(Insight(
                aturan="AMP-02", entitas=eid, tone="warn", slot=("daftar", "amplop"), data=data,
                aksi=[geser], rupiah=kb["kurang"], urgensi=Decimal("0.8"),
                keyakinan=yakin, dasar_hari=m.hari_ke, amplop_id=eid,
            ))
            continue
        aksi = []
        if k.cta_batas_harian:
            aksi.append({"kind": "daily_limit", "kode": "batas_harian", "payload": {"amplop_id": eid}})
        aksi.append(geser)
        out.append(Insight(
            aturan="AMP-03", entitas=eid, tone="danger" if dekat else "warn", slot=("daftar", "amplop"),
            data=data, aksi=aksi, rupiah=kb["kurang"], urgensi=Decimal("0.8") if dekat else Decimal("0.4"),
            keyakinan=yakin, dasar_hari=m.hari_ke, amplop_id=eid,
        ))
    return out


def amp_04(ctx: Konteks, kurang: dict) -> list[Insight]:
    m, k = ctx.m, ctx.k
    per01 = _kekurangan_menyala(m)
    out = []
    for a in m.amplop.values():
        if a.kelompok != "belanja" or a.tambalan_n < k.ditambal_berulang:
            continue
        kb = kurang.get(a.id)
        sumber = sorted(
            ({"amplop_id": sid, "nama": m.amplop[sid].nama if sid in m.amplop else None, "jumlah": jml,
              "menipis": sid in kurang} for sid, jml in a.tambalan_sumber.items()),
            key=lambda x: (-x["jumlah"], x["amplop_id"] or ""),
        )
        kebutuhan = a.laju * m.hari_total if a.laju is not None else None
        aksi = []
        if kebutuhan is not None and kebutuhan > 0:
            aksi.append({"kind": "raise_budget", "kode": "naikkan_jatah",
                         "payload": {"amplop_id": a.id, "jumlah": rupiah(ceil10rb(kebutuhan))}})
        if kb and not per01:
            aksi.append({"kind": "plan", "kode": "geser_sisa_periode",
                         "payload": {"kebutuhan": [{"tujuan_id": a.id, "jumlah": rupiah(kb["kurang"])}]}})
        out.append(Insight(
            aturan="AMP-04", entitas=a.id,
            tone="warn" if kb and kb["aturan"] != "AMP-01" and not per01 else "info",
            slot=("daftar", "amplop", "alokasi"),
            data={"amplop_id": a.id, "nama": a.nama, "n": a.tambalan_n, "total": a.tambalan_total,
                  "jatah_awal": a.dana - a.tambalan_total, "kebutuhan": kebutuhan,
                  "saran": ceil10rb(kebutuhan) if kebutuhan else None, "sumber": sumber,
                  "mulai": m.period_end + timedelta(days=1)},
            aksi=aksi, rupiah=a.tambalan_total + (kb["kurang"] if kb else ZERO),
            urgensi=Decimal("0.4") if kb else Decimal("0.2"), amplop_id=a.id,
        ))
    return out


def amp_05(ctx: Konteks) -> list[Insight]:
    out = []
    for x in ctx.s.kurang_kronis:
        eid = x["envelope_id"]
        saran = ceil10rb(x["median_terpakai"])
        out.append(Insight(
            aturan="AMP-05", entitas=eid, tone="info", slot=("daftar", "amplop", "alokasi"),
            data={"amplop_id": eid, "nama": ctx.nama.get(eid, ""), "median": x["median_terpakai"],
                  "jatah": x["jatah"], "alasan": x["alasan"], "periode_ditambal": x["periode_ditambal"],
                  "saran": saran},
            aksi=[{"kind": "raise_budget", "kode": "naikkan_jatah",
                   "payload": {"amplop_id": eid, "jumlah": rupiah(saran)}}],
            rupiah=abs(x["median_terpakai"] - x["jatah"]), amplop_id=eid, keyakinan="sedang",
        ))
    return out


def amp_06(ctx: Konteks) -> list[Insight]:
    from app.services.advisor.rules.periode import _tabungan_tujuan
    out = []
    tujuan = _tabungan_tujuan(ctx)
    for x in ctx.s.lebih_kronis:
        eid = x["envelope_id"]
        saran = ceil10rb(x["median_terpakai"] * Decimal("1.1"))
        if saran >= x["jatah"]:
            continue
        out.append(Insight(
            aturan="AMP-06", entitas=eid, tone="info", slot=("daftar", "amplop", "alokasi"),
            data={"amplop_id": eid, "nama": ctx.nama.get(eid, ""), "median": x["median_terpakai"],
                  "jatah": x["jatah"], "porsi": x["median_terpakai"] / x["jatah"], "saran": saran,
                  "tabungan": ctx.nama.get(tujuan, "") if tujuan else ""},
            aksi=[{"kind": "raise_budget", "kode": "turunkan_jatah",
                   "payload": {"amplop_id": eid, "jumlah": rupiah(saran)}}],
            rupiah=x["kelebihan"], amplop_id=eid, keyakinan="sedang",
        ))
    return out


def amp_07(ctx: Konteks) -> list[Insight]:
    return [Insight(
        aturan="AMP-07", entitas=x["envelope_id"], tone="info", slot=("amplop", "analitik"),
        data={"amplop_id": x["envelope_id"], "nama": ctx.nama.get(x["envelope_id"], ""), "dana": x["dana"],
              "terpakai": x["terpakai"], "bebas": x["bebas"]},
        amplop_id=x["envelope_id"],
    ) for x in ctx.s.menganggur]


def amp_08(ctx: Konteks) -> list[Insight]:
    out = []
    for x in ctx.s.lonjakan:
        eid = x["envelope_id"]
        out.append(Insight(
            aturan="AMP-08", entitas=eid, tone="warn", slot=("daftar", "kpi:terpakai", "amplop", "analitik"),
            data={"amplop_id": eid, "nama": ctx.nama.get(eid, ""), "v7": x["variabel_7h"], "median": x["median_7h"],
                  "kali": x["variabel_7h"] / x["median_7h"] if x["median_7h"] > 0 else None},
            aksi=[_route_amplop(eid)], rupiah=x["selisih"], urgensi=Decimal("0.6"), amplop_id=eid,
        ))
    return out


def amp_09(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    if m.hari_ke < k.hari_min_belum_didanai:
        return []
    ada_tagihan = {r.envelope_id for r in ctx.snap.recurring}
    out = []
    for a in m.amplop.values():
        e = _env(ctx, a.id)
        if a.kelompok != "belanja" or not a.kebutuhan or a.dana != 0 or e is None or e.budget_amount <= 0:
            continue
        out.append(Insight(
            aturan="AMP-09", entitas=a.id, tone="warn" if a.id in ada_tagihan else "info",
            slot=("daftar", "amplop", "alokasi"),
            data={"amplop_id": a.id, "nama": a.nama, "jatah": e.budget_amount, "tagihan": a.id in ada_tagihan},
            aksi=[{"kind": "route", "kode": "alokasikan",
                   "payload": {"path": f"/allocate?new=1&amount={rupiah(e.budget_amount)}"}}],
            rupiah=e.budget_amount, urgensi=Decimal("0.4"), amplop_id=a.id,
        ))
    return out


def amp_10(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    out = []
    for e in ctx.snap.envelopes:
        a = m.amplop.get(e.id)
        if a is None or a.kelompok != "belanja" or not e.daily_limit or e.daily_limit <= 0:
            continue
        hari = variabel_harian_amplop(ctx.snap, m, e.id, 7)
        lewat = [v for _, v in hari if v > e.daily_limit]
        if len(lewat) < k.batas_terlewat_n:
            continue
        ins = Insight(
            aturan="AMP-10", entitas=e.id, tone="info", slot=("amplop",),
            data={"amplop_id": e.id, "nama": a.nama, "batas_lama": e.daily_limit, "n": len(lewat),
                  "hari": len(hari), "rata": sum((v for _, v in hari), ZERO) / len(hari),
                  "batas_amplop_id": e.id},
            amplop_id=e.id,
        )
        if k.cta_batas_harian:
            ins.aksi.append({"kind": "daily_limit", "kode": "sesuaikan_batas", "payload": {"amplop_id": e.id}})
        ins.aksi.append({"kind": "dismiss", "kode": "biarkan", "payload": {"kunci": ins.id, "pilihan": "periode"}})
        out.append(ins)
    return out


def amp_11(ctx: Konteks) -> list[Insight]:
    return [Insight(
        aturan="AMP-11", entitas=x["envelope_id"], tone="info", slot=("amplop", "analitik"),
        data={"amplop_id": x["envelope_id"], "nama": ctx.nama.get(x["envelope_id"], ""),
              "persen": x["persen"], "arah": x["arah"], "terpakai": x["terpakai"], "lalu": x["terpakai_lalu"]},
        amplop_id=x["envelope_id"],
    ) for x in ctx.s.tren]


def evaluasi(ctx: Konteks) -> list[Insight]:
    kurang = kekurangan_amplop(ctx)
    return [*amp_01(ctx), *amp_02_03(ctx, kurang), *amp_04(ctx, kurang), *amp_05(ctx), *amp_06(ctx),
            *amp_07(ctx), *amp_08(ctx), *amp_09(ctx), *amp_10(ctx), *amp_11(ctx)]
