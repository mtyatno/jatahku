"""Aturan D. Tagihan & langganan — TAG-01..09 (02-aturan.md §6D). Fungsi murni `(Konteks) → [Insight]`.

Status tagihan dari metrics.py (`m.tagihan`: M4/M5/M13, telat, jatuh tempo), K4 beban
tagihan, dan sinyal S3 (pola rutin), S10 (nominal berubah), S11 (langganan ganda).

Keputusan kecil S4 (juga di SESI-LOG.md):
- "Dana kurang" (TAG-01/02) diukur dengan sisa(e) amplop tagihan, berurutan menurut jatuh
  tempo: perlu = Σ nominal tagihan belum dibayar s/d tagihan ini − sisa(e), dibatasi
  0..(nominal + minus). Contoh §12: KPR Rp1,6 jt, amplop minus Rp408.174 → perlu Rp2.008.174.
- Tagihan mingguan: yang dinilai hanya kemunculan berikutnya (nominal satu kali).
- TAG-04 "terkumpul" = sisa(e) amplop tagihan tahunan (dibatasi 0..nominal).
- TAG-06 dan TAG-08 membuka halaman Langganan (belum ada kind "ubah langganan").
- TAG-09 selalu ada sebagai cadangan chip Tagihan: "Lunas semua", "Berikutnya {nama} {tgl}",
  atau "Tidak ada tagihan".
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.advisor.insight import Insight, Konteks
from app.services.advisor.metrics import rupiah

ZERO = Decimal("0")
LANGGANAN = {"kind": "route", "kode": "lihat_langganan", "payload": {"path": "/langganan"}}


def _nama_tagihan(ctx: Konteks) -> dict:
    return {r.id: r.description for r in ctx.snap.recurring}


def _perlu_per_tagihan(ctx: Konteks) -> dict[str, Decimal]:
    """Kekurangan dana amplop untuk tiap tagihan belum dibayar (lihat docstring modul)."""
    m = ctx.m
    out: dict[str, Decimal] = {}
    per_env: dict[str, list] = {}
    for b in m.tagihan:
        if b.sisa > 0:
            per_env.setdefault(b.envelope_id, []).append(b)
    for eid, bills in per_env.items():
        sisa = m.amplop[eid].sisa if eid in m.amplop else ZERO
        bills.sort(key=lambda b: (b.jatuh_tempo, b.recurring_id))
        kumulatif, sebelumnya = ZERO, ZERO
        for b in bills:
            kumulatif += b.nominal
            butuh = max(kumulatif - sisa, ZERO)
            out[b.recurring_id] = butuh - sebelumnya
            sebelumnya = butuh
    return out


def _aksi_bayar(b, perlu: Decimal) -> list[dict]:
    bayar = {"kind": "pay", "kode": "bayar", "payload": {"recurring_id": b.recurring_id}}
    if perlu <= 0:
        return [bayar]
    return [{"kind": "plan", "kode": "geser_bayar", "payload": {"kebutuhan": [
        {"tujuan_id": b.envelope_id, "jumlah": rupiah(perlu), "bayar_recurring_id": b.recurring_id}]}},
        {**bayar, "kode": "bayar_saja"}]


def tag_01_02_03(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    nama = _nama_tagihan(ctx)
    perlu_map = _perlu_per_tagihan(ctx)
    out = []
    for b in sorted(m.tagihan, key=lambda b: (b.jatuh_tempo, b.recurring_id)):
        if b.sisa <= 0:
            continue
        a = m.amplop.get(b.envelope_id)
        perlu = perlu_map.get(b.recurring_id, ZERO)
        minus = max(-a.sisa, ZERO) if a else ZERO
        lagi = (b.jatuh_tempo - m.today).days
        data = {"recurring_id": b.recurring_id, "nama": nama.get(b.recurring_id, ""), "nominal": b.nominal,
                "jatuh_tempo": b.jatuh_tempo, "telat": b.telat_hari, "lagi": lagi, "perlu": perlu,
                "amplop_id": b.envelope_id, "amplop": a.nama if a else "", "sisa_amplop": a.sisa if a else ZERO}
        if b.telat_hari > 0:
            out.append(Insight(
                aturan="TAG-01", entitas=b.recurring_id, tone="danger",
                slot=("daftar", "kpi:tagihan", "langganan", "amplop"), data=data,
                aksi=_aksi_bayar(b, perlu), rupiah=b.nominal + minus, urgensi=Decimal("1"),
                amplop_id=b.envelope_id,
            ))
        elif 0 <= lagi <= k.jatuh_tempo_dekat and perlu > 0:
            out.append(Insight(
                aturan="TAG-02", entitas=b.recurring_id, tone="danger" if lagi == 0 else "warn",
                slot=("daftar", "kpi:tagihan", "langganan", "amplop"), data=data,
                aksi=_aksi_bayar(b, perlu), rupiah=b.nominal + minus, urgensi=Decimal("0.8"),
                amplop_id=b.envelope_id,
            ))
        elif 0 <= lagi <= k.jatuh_tempo_dekat:
            out.append(Insight(
                aturan="TAG-03", entitas=b.recurring_id, tone="info",
                slot=("daftar", "kpi:tagihan", "langganan"), data=data,
                aksi=_aksi_bayar(b, ZERO), rupiah=ZERO, urgensi=Decimal("0.8"), amplop_id=b.envelope_id,
            ))
    return out


def tag_04(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    nama = _nama_tagihan(ctx)
    out = []
    for b in m.tagihan:
        if b.frekuensi != "yearly" or (b.jatuh_tempo - m.today).days > k.tahunan_dilihat_hari:
            continue
        a = m.amplop.get(b.envelope_id)
        terkumpul = min(max(a.sisa if a else ZERO, ZERO), b.nominal)
        kurang = b.nominal - terkumpul
        if kurang <= 0:
            continue
        bulan = max((b.jatuh_tempo.year - m.today.year) * 12 + b.jatuh_tempo.month - m.today.month, 1)
        out.append(Insight(
            aturan="TAG-04", entitas=b.recurring_id, tone="warn",
            slot=("daftar", "kpi:tagihan", "langganan", "amplop"),
            data={"recurring_id": b.recurring_id, "nama": nama.get(b.recurring_id, ""), "nominal": b.nominal,
                  "jatuh_tempo": b.jatuh_tempo, "terkumpul": terkumpul, "kurang": kurang,
                  "per_bulan": kurang / bulan, "amplop_id": b.envelope_id},
            aksi=[{"kind": "plan", "kode": "geser_sekarang",
                   "payload": {"kebutuhan": [{"tujuan_id": b.envelope_id, "jumlah": rupiah(kurang)}]}},
                  {**LANGGANAN, "kode": "atur_sisihan"}],
            rupiah=kurang, urgensi=Decimal("0.6"), amplop_id=b.envelope_id,
        ))
    return out


def tag_05(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    if m.beban_tagihan is None or m.beban_tagihan <= k.beban_tagihan_tinggi:
        return []
    return [Insight(
        aturan="TAG-05", entitas=m.period_start.isoformat(), tone="info", slot=("daftar", "langganan"),
        data={"beban": m.beban_tagihan, "per_bulan": m.beban_tagihan * m.dana_belanja, "dana": m.dana_belanja},
        aksi=[{**LANGGANAN, "kode": "tinjau_langganan"}],
    )]


def tag_06(ctx: Konteks) -> list[Insight]:
    nama = _nama_tagihan(ctx)
    return [Insight(
        aturan="TAG-06", entitas=x["recurring_id"], tone="info", slot=("langganan", "transaksi"),
        data={"recurring_id": x["recurring_id"], "nama": nama.get(x["recurring_id"], ""), "nominal": x["nominal"],
              "dibayar": x["dibayar"], "selisih": x["selisih"], "txn_id": x["txn_id"]},
        aksi=[{**LANGGANAN, "kode": "perbarui_nominal"}], rupiah=abs(x["selisih"]),
    ) for x in ctx.s.tagihan_berubah]


def tag_07(ctx: Konteks) -> list[Insight]:
    by_id = {x.id: x for x in ctx.snap.transactions}
    out = []
    for x in ctx.s.rutin:
        if x["keyakinan"] not in ("medium", "high"):
            continue
        contoh = by_id.get(x["contoh_txn_id"])
        deskripsi = contoh.description if contoh else x["kunci"]
        frek = x["frekuensi"] if x["frekuensi"] in ("weekly", "monthly", "yearly") else "monthly"
        berikut = date.fromisoformat(x["berikutnya"]) if x.get("berikutnya") else None
        out.append(Insight(
            aturan="TAG-07", entitas=f"{x['envelope_id']}:{x['kunci']}", tone="info",
            slot=("transaksi", "langganan"),
            data={"amplop_id": x["envelope_id"], "amplop": ctx.nama.get(x["envelope_id"], ""),
                  "deskripsi": deskripsi, "nominal": x["nominal"], "frekuensi": x["frekuensi"],
                  "kemunculan": x["kemunculan"], "berikutnya": berikut, "txn_ids": x["txn_ids"]},
            aksi=[{"kind": "make_recurring", "kode": "jadikan_langganan", "payload": {
                "deskripsi": deskripsi, "jumlah": rupiah(x["nominal"]), "frekuensi": frek,
                "amplop_id": x["envelope_id"],
                **({"next_run": berikut.isoformat()} if berikut else {})}}],
            keyakinan="tinggi" if x["keyakinan"] == "high" else "sedang", amplop_id=x["envelope_id"],
        ))
    return out


def tag_08(ctx: Konteks) -> list[Insight]:
    nama = _nama_tagihan(ctx)
    return [Insight(
        aturan="TAG-08", entitas="+".join(x["recurring_ids"]), tone="info", slot=("daftar", "langganan"),
        data={"nama": [nama.get(r, "") for r in x["recurring_ids"]], "jumlah": x["jumlah"]},
        aksi=[{**LANGGANAN, "kode": "lihat_keduanya"}],
    ) for x in ctx.s.langganan_ganda]


def tag_09(ctx: Konteks) -> list[Insight]:
    m = ctx.m
    nama = _nama_tagihan(ctx)
    belum = sorted((b for b in m.tagihan if b.sisa > 0), key=lambda b: (b.jatuh_tempo, b.recurring_id))
    lunas = [b for b in m.tagihan if b.lunas_oleh]
    berikut = belum[0] if belum else None
    return [Insight(
        aturan="TAG-09", entitas=m.period_start.isoformat(), tone="ok", slot=("kpi:tagihan", "langganan"),
        data={"ada": bool(m.tagihan), "belum": len(belum), "lunas": len(lunas),
              "berikut": {"nama": nama.get(berikut.recurring_id, ""), "tanggal": berikut.jatuh_tempo,
                          "nominal": berikut.nominal} if berikut else None,
              "sisa": m.tagihan_sisa, "pe": m.period_end},
    )]


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*tag_01_02_03(ctx), *tag_04(ctx), *tag_05(ctx), *tag_06(ctx), *tag_07(ctx), *tag_08(ctx),
            *tag_09(ctx)]
