"""Aturan G. Kebersihan data — DAT-01..06 (02-aturan.md §6G). Fungsi murni `(Konteks) → [Insight]`.

Angka dari metrics.py (K1–K3, M13) dan sinyal S4/S4b (dobel), S15 (lupa catat), S19
(tagihan dibayar manual).

Keputusan kecil S4 (juga di SESI-LOG.md):
- DAT-01 menghitung transaksi (semua anggota, amplop terlihat, tanpa penyesuaian) sesudah
  tanggal cocokkan terakhir. Belum pernah cocokkan → tidak menyala.
- DAT-02 tanpa CTA (§6G), jadi hanya tampil di halaman Analitik.
- DAT-03 S4: satu insight per grup, CTA hapus kiriman berikutnya (`hapus_saran`); S4b: satu
  insight per grup struk, CTA hapus seluruh rantai kedua (`txn_ids`). "Bukan dobel" = dismiss
  `bukan_dobel` untuk kunci insight itu: permanen, tanpa TTL (#93).
- DAT-06 "Bukan pembayaran tagihan" = dismiss `bukan_tagihan` sampai akhir periode (#93; kunci
  per langganan, jadi tidak permanen). M4 belum membaca pilihan ini (perlu status di snapshot,
  berlaku untuk household) — #107.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.advisor.insight import Insight, Konteks

ZERO = Decimal("0")


def dat_01_02(ctx: Konteks) -> list[Insight]:
    m, k, snap = ctx.m, ctx.k, ctx.snap
    out = []
    chk = snap.last_balance_check
    if chk is not None and m.hari_sejak_cocokkan is not None and m.hari_sejak_cocokkan > k.cocokkan_lama_hari:
        n = sum(1 for x in snap.transactions if x.transaction_date > chk.created_on and not x.is_adjustment)
        if n >= k.cocokkan_lama_txn:
            out.append(Insight(
                aturan="DAT-01", entitas=chk.created_on.isoformat(), tone="info", slot=("daftar", "amplop"),
                data={"hari": m.hari_sejak_cocokkan, "n": n},
                aksi=[{"kind": "balance", "kode": "cocokkan_saldo", "payload": {}}],
            ))
    if chk is not None and m.selisih_terakhir is not None and m.dana_belanja > 0 \
            and abs(m.selisih_terakhir) > m.dana_belanja * k.selisih_besar:
        out.append(Insight(
            aturan="DAT-02", entitas=chk.created_on.isoformat(), tone="info", slot=("analitik",),
            data={"selisih": m.selisih_terakhir, "tanggal": chk.created_on},
        ))
    return out


def dat_03(ctx: Konteks) -> list[Insight]:
    k, s = ctx.k, ctx.s
    by_id = {x.id: x for x in ctx.snap.transactions}
    out = []
    for g in s.dobel:
        first = by_id.get(g["txn_ids"][0])
        total = g["jumlah"] * len(g["hapus_saran"])
        ins = Insight(
            aturan="DAT-03", entitas=g["txn_ids"][0], tone="warn",
            slot=("transaksi", "daftar") if total >= k.dobel_daftar_min else ("transaksi",),
            data={"jenis": "dobel", "deskripsi": first.description if first else "", "jumlah": g["jumlah"],
                  "n": len(g["txn_ids"]), "total": total, "amplop_id": g["envelope_id"],
                  "amplop": ctx.nama.get(g["envelope_id"], ""), "txn_ids": g["txn_ids"],
                  "tanggal": first.transaction_date if first else None},
            rupiah=total, urgensi=Decimal("1"), amplop_id=g["envelope_id"],
        )
        ins.aksi = [{"kind": "delete_txn", "kode": "hapus_salah_satu",
                     "payload": {"txn_id": g["hapus_saran"][0], "txn_ids": list(g["hapus_saran"])}},
                    {"kind": "not_duplicate", "kode": "bukan_dobel",
                     "payload": {"kunci": ins.id, "pilihan": "bukan_dobel"}}]
        out.append(ins)
    for g in s.struk_dobel:
        first = by_id.get(g["txn_ids"][0])
        eid = first.envelope_id if first else None
        ins = Insight(
            aturan="DAT-03", entitas=g["struk_ids"][1], tone="warn",
            slot=("transaksi", "daftar") if g["total"] >= k.dobel_daftar_min else ("transaksi",),
            data={"jenis": "struk", "toko": g["toko"], "n": g["n_barang"], "total": g["total"],
                  "jumlah": g["total"], "txn_ids": g["txn_ids"], "amplop_id": eid,
                  "tanggal": first.transaction_date if first else None},
            rupiah=g["total"], urgensi=Decimal("1"), amplop_id=eid,
        )
        ins.aksi = [{"kind": "delete_txn", "kode": "hapus_duplikat",
                     "payload": {"txn_id": g["txn_ids"][0], "txn_ids": list(g["txn_ids"])}},
                    {"kind": "not_duplicate", "kode": "bukan_dobel",
                     "payload": {"kunci": ins.id, "pilihan": "bukan_dobel"}}]
        out.append(ins)
    return out


def dat_04(ctx: Konteks) -> list[Insight]:
    s = ctx.s
    if not s.lupa_catat:
        return []
    return [Insight(
        aturan="DAT-04", entitas=ctx.m.today.isoformat(), tone="info", slot=("daftar",),
        data={"hari": s.lupa_catat["hari_tanpa_catatan"], "aktif": s.lupa_catat["hari_mencatat"]},
        aksi=[{"kind": "expense", "kode": "catat", "payload": {}}],
    )]


def dat_05(ctx: Konteks) -> list[Insight]:
    m = ctx.m
    kosong = [e for e in ctx.snap.envelopes
              if e.id in m.amplop and m.amplop[e.id].kelompok == "belanja" and not e.classification]
    if not kosong:
        return []
    return [Insight(
        aturan="DAT-05", entitas="klasifikasi", tone="info", slot=("daftar", "amplop"),
        data={"n": len(kosong), "nama": [e.name for e in kosong]},
        aksi=[{"kind": "route", "kode": "klasifikasikan", "payload": {"path": "/envelopes"}}],
    )]


def dat_06(ctx: Konteks) -> list[Insight]:
    nama = {r.id: r.description for r in ctx.snap.recurring}
    by_id = {x.id: x for x in ctx.snap.transactions}
    out = []
    for x in ctx.s.dibayar_manual:
        txn = by_id.get(x["txn_id"])
        ins = Insight(
            aturan="DAT-06", entitas=x["recurring_id"], tone="warn",
            slot=("daftar", "kpi:tagihan", "langganan", "transaksi"),
            data={"recurring_id": x["recurring_id"], "nama": nama.get(x["recurring_id"], ""),
                  "jumlah": x["jumlah"], "txn_id": x["txn_id"], "deskripsi": txn.description if txn else "",
                  "amplop_id": x["envelope_id"]},
            rupiah=x["jumlah"], urgensi=Decimal("0.8"), amplop_id=x["envelope_id"],
        )
        ins.aksi = [{"kind": "mark_paid", "kode": "tandai_lunas", "payload": {"recurring_id": x["recurring_id"]}},
                    {"kind": "not_duplicate", "kode": "bukan_tagihan",
                     "payload": {"kunci": ins.id, "pilihan": "bukan_tagihan"}}]
        out.append(ins)
    return out


def dat_07(ctx: Konteks) -> list[Insight]:
    """DAT-07 (Fase 5): amplop harian yang polanya bulanan — ≤ 3 transaksi per periode (berjalan &
    lalu), median nominal ≥ 25% dana, dana ≥ Rp500 rb — saldonya keliru masuk jatah harian."""
    m, k, snap = ctx.m, ctx.k, ctx.snap
    if len(snap.periods) < 2:
        return []
    (ps0, pe0), (ps1, pe1) = snap.periods[-2], snap.periods[-1]
    out = []
    for e in snap.envelopes:
        a = m.amplop.get(e.id)
        if a is None or a.kelompok != "belanja" or a.jenis != "harian" or a.dana < k.bulanan_dana_min:
            continue
        txns = [x for x in snap.transactions if x.envelope_id == e.id and not x.is_adjustment]
        cur = [x.amount for x in txns if ps1 <= x.transaction_date <= pe1]
        lalu = [x.amount for x in txns if ps0 <= x.transaction_date <= pe0]
        if not cur or not lalu or len(cur) > k.bulanan_txn_maks or len(lalu) > k.bulanan_txn_maks:
            continue
        semua = sorted(cur + lalu)
        median = semua[len(semua) // 2]
        if median < a.dana * k.bulanan_median_porsi:
            continue
        out.append(Insight(
            aturan="DAT-07", entitas=e.id, tone="info", slot=("daftar", "amplop"),
            data={"amplop_id": e.id, "amplop": e.name, "bebas": a.bebas, "dana": a.dana,
                  "n_txn": len(cur), "median": median},
            aksi=[{"kind": "route", "kode": "atur_jenis_grup", "payload": {"path": "/envelopes"}}],
            amplop_id=e.id, rupiah=max(a.bebas, ZERO), urgensi=Decimal("0.3"),
        ))
    return out


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*dat_01_02(ctx), *dat_03(ctx), *dat_04(ctx), *dat_05(ctx), *dat_06(ctx), *dat_07(ctx)]
