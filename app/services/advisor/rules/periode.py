"""Aturan B. Periode & sisa bebas — PER-01..07 (02-aturan.md §6B). Fungsi murni `(Konteks) → [Insight]`.

Semua angka dari metrics.py (T3, T4, T9, T10, J1, porsi_7h, perkiraan sisa) dan sinyal
(S6 hari lewat jatah, S12 pemasukan terlambat, S16 sisa non-rollover). Tanpa teks.

Keputusan kecil S3 (juga di SESI-LOG.md):
- PER-01 tidak menyala di hari terakhir (r = 0): tidak ada lagi yang diproyeksikan; kalau
  sisa bebas minus, PER-02 yang tampil.
- Penyumbang untuk CTA batas harian = amplop keinginan pertama di 3 penyumbang terbesar
  (porsi_7h), selain itu penyumbang terbesar — supaya amplop keinginan kecil tidak
  mengalahkan penyumbang utama.
- PER-02 "Tutup dari tabungan" = rencana dana untuk amplop belanja yang minus; perencana
  menawarkan tabungan (`opsi_tabungan`) bila sumber belanja tidak cukup.
- PER-06 tujuan = amplop tabungan pertama yang boleh diubah viewer (tabungan umum dulu,
  dana darurat terakhir); jumlah = Σ bebas amplop non-rollover (S16), selain itu perkiraan sisa.
- PER-07 juga mengisi chip Sisa bebas & Terpakai di hari 1–2, karena belum ada proyeksi
  (setiap kartu selalu punya chip, §7).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.services.advisor.insight import Insight, Konteks, keyakinan_proyeksi
from app.services.advisor.metrics import (
    SAVING_PURPOSES, jumlah_transaksi_laju, laju_7_hari, laju_periode, perkiraan_sisa, persen_variabel,
    ringkasan_periode_lalu, rupiah,
)

ZERO = Decimal("0")


def _keyakinan(ctx: Konteks) -> str:
    return keyakinan_proyeksi(ctx.m.hari_ke, jumlah_transaksi_laju(ctx.snap, ctx.m), ctx.k)


def _penyumbang(ctx: Konteks, n: int = 3) -> list[dict]:
    m = ctx.m
    rows = [a for a in m.amplop.values() if a.kelompok == "belanja" and a.porsi_7h > 0]
    rows.sort(key=lambda a: (-a.porsi_7h, a.id))
    return [{"amplop_id": a.id, "nama": a.nama, "jumlah": a.porsi_7h, "porsi": a.porsi_7h_bagian,
             "keinginan": not a.kebutuhan} for a in rows[:n]]


def _amplop_batas(penyumbang: list[dict]) -> str | None:
    for p in penyumbang:
        if p["keinginan"]:
            return p["amplop_id"]
    return penyumbang[0]["amplop_id"] if penyumbang else None


def _kekurangan_menyala(m) -> bool:
    return m.proyeksi_valid and m.sisa_hari > 0 and (m.kekurangan or ZERO) > 0


def per_01(ctx: Konteks) -> list[Insight]:
    m, s, k = ctx.m, ctx.s, ctx.k
    if not _kekurangan_menyala(m):
        return []
    t = m.today
    t9 = m.kekurangan
    habis_dekat = m.tanggal_habis is not None and m.tanggal_habis <= t + timedelta(days=k.danger_habis_hari)
    danger = habis_dekat or t9 >= max(m.sisa_bebas, ZERO) * k.danger_kekurangan
    mulai7 = t - timedelta(days=6)
    lewat7 = sum(1 for h in s.lewat_jatah if mulai7 <= h["tanggal"] <= t)
    penyumbang = _penyumbang(ctx)
    batas_id = _amplop_batas(penyumbang)
    bills = {b.recurring_id: b for b in m.tagihan}
    env_tagihan = {b.envelope_id for b in bills.values()}
    tagihan_minus = [
        {"amplop_id": a.id, "nama": a.nama, "sisa": a.sisa}
        for a in m.amplop.values() if a.kelompok == "belanja" and a.id in env_tagihan and a.sisa < 0
    ]
    aksi = []
    if s.pemasukan_terlambat:
        aksi.append({"kind": "income", "kode": "catat_pemasukan",
                     "payload": {"jumlah": rupiah(m.pemasukan_biasa)} if m.pemasukan_biasa else {}})
    if batas_id and k.cta_batas_harian:
        aksi.append({"kind": "daily_limit", "kode": "batas_harian", "payload": {"amplop_id": batas_id}})
    aksi.append({"kind": "chat", "kode": "tanya_kekurangan", "payload": {}})
    return [Insight(
        aturan="PER-01", entitas=m.period_start.isoformat(), tone="danger" if danger else "warn",
        slot=("daftar", "kpi:sisa_bebas", "kpi:terpakai"),
        data={"t3": m.sisa_bebas, "t4": m.laju_total, "t9": t9, "j1": m.j1, "r": m.sisa_hari,
              "pe": m.period_end, "habis": m.tanggal_habis, "lewat7": lewat7, "penyumbang": penyumbang,
              "tagihan_sisa": m.tagihan_sisa, "tagihan_minus": tagihan_minus, "batas_amplop_id": batas_id,
              "proyeksi_akhir": m.proyeksi_akhir, "dana": m.dana_belanja, "terpakai": m.terpakai_belanja},
        aksi=aksi, rupiah=t9, urgensi=Decimal("0.8") if habis_dekat else Decimal("0.4"),
        keyakinan=_keyakinan(ctx), dasar_hari=m.hari_ke,
    )]


def per_02(ctx: Konteks) -> list[Insight]:
    m = ctx.m
    if m.sisa_bebas >= 0:
        return []
    minus = [a for a in m.amplop.values() if a.kelompok == "belanja" and a.sisa < 0]
    minus.sort(key=lambda a: (a.sisa, a.id))
    aksi = [{"kind": "income", "kode": "catat_pemasukan", "payload": {}}]
    if minus:
        aksi.append({"kind": "plan", "kode": "tutup_minus", "payload": {"kebutuhan": [
            {"tujuan_id": a.id, "jumlah": rupiah(-a.sisa)} for a in minus[:10]
        ]}})
    return [Insight(
        aturan="PER-02", entitas=m.period_start.isoformat(), tone="danger",
        slot=("daftar", "kpi:sisa_bebas"),
        data={"minus": -m.sisa_bebas, "r": m.sisa_hari, "pe": m.period_end,
              "amplop_minus": [{"amplop_id": a.id, "nama": a.nama, "sisa": a.sisa} for a in minus],
              "tagihan_sisa": m.tagihan_sisa},
        aksi=aksi, rupiah=-m.sisa_bebas, urgensi=Decimal("1"),
    )]


def per_03(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    if not m.proyeksi_valid:
        return []
    pv = persen_variabel(m)
    if pv is None or pv - m.persen_waktu < k.lebih_cepat_poin:
        return []
    return [Insight(
        aturan="PER-03", entitas=m.period_start.isoformat(),
        tone="warn" if _kekurangan_menyala(m) else "info", slot=("kpi:terpakai", "analitik"),
        data={"persen_dana": pv, "persen_waktu": m.persen_waktu, "hari_ke": m.hari_ke, "hari_total": m.hari_total},
        dasar_hari=m.hari_ke,
    )]


def per_04_05(ctx: Konteks) -> list[Insight]:
    """PER-04 laju membaik dan PER-05 cukup sampai akhir periode (keduanya ok, T9 = 0)."""
    m, k = ctx.m, ctx.k
    if not m.proyeksi_valid or (m.kekurangan or ZERO) > 0:
        return []
    sisa = perkiraan_sisa(m)
    yakin = _keyakinan(ctx)
    out = []
    l7, lp = laju_7_hari(m), laju_periode(m)
    if l7 is not None and lp > 0 and l7 <= lp * k.laju_membaik:
        out.append(Insight(
            aturan="PER-04", entitas=m.period_start.isoformat(), tone="ok", slot=("kpi:sisa_bebas", "analitik"),
            data={"laju7": l7, "laju_periode": lp, "turun": 1 - l7 / lp, "pe": m.period_end, "sisa": sisa},
            keyakinan=yakin, dasar_hari=m.hari_ke,
        ))
    out.append(Insight(
        aturan="PER-05", entitas=m.period_start.isoformat(), tone="ok",
        slot=("kpi:sisa_bebas", "kpi:terpakai"),
        data={"pe": m.period_end, "sisa": sisa, "t4": m.laju_total, "j1": m.j1, "r": m.sisa_hari,
              "proyeksi_akhir": m.proyeksi_akhir, "dana": m.dana_belanja},
        keyakinan=yakin, dasar_hari=m.hari_ke,
    ))
    return out


def _tabungan_tujuan(ctx: Konteks) -> str | None:
    snap = ctx.snap
    boleh = [e for e in snap.envelopes
             if e.purpose in SAVING_PURPOSES and not e.is_locked
             and (e.owner_id is None or e.owner_id == snap.viewer_id) and e.id in ctx.m.amplop]
    boleh.sort(key=lambda e: (e.is_emergency, e.purpose != "saving"))  # stabil: urutan dibuat
    return boleh[0].id if boleh else None


def per_06(ctx: Konteks) -> list[Insight]:
    m, s, k = ctx.m, ctx.s, ctx.k
    if m.sisa_hari > k.akhir_periode_hari or not m.proyeksi_valid:
        return []
    hangus = sum((x["bebas"] for x in s.sisa_non_rollover), ZERO)
    sisa = perkiraan_sisa(m) or ZERO
    if hangus <= 0 and sisa <= k.akhir_periode_sisa_min:
        return []
    jumlah = hangus if hangus > 0 else sisa
    tujuan = _tabungan_tujuan(ctx)
    aksi = []
    if tujuan and rupiah(jumlah) > 0:
        aksi.append({"kind": "plan", "kode": "pindah_tabungan", "payload": {"kebutuhan": [
            {"tujuan_id": tujuan, "jumlah": rupiah(jumlah)}
        ]}})
    return [Insight(
        aturan="PER-06", entitas=m.period_start.isoformat(), tone="info", slot=("daftar", "kpi:sisa_bebas"),
        data={"jumlah": jumlah, "hangus": hangus, "pe": m.period_end, "tujuan_id": tujuan,
              "tujuan": ctx.nama.get(tujuan, "") if tujuan else "",
              "non_rollover": [{"amplop_id": x["envelope_id"], "nama": ctx.nama.get(x["envelope_id"], ""),
                                "bebas": x["bebas"]} for x in s.sisa_non_rollover]},
        aksi=aksi, rupiah=hangus, urgensi=Decimal("0.8"), keyakinan=_keyakinan(ctx), dasar_hari=m.hari_ke,
    )]


def per_07(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    if m.hari_ke > k.awal_periode_hari:
        return []
    lalu = ringkasan_periode_lalu(m)
    if lalu and lalu["terbesar_id"]:
        lalu["terbesar_nama"] = ctx.nama.get(lalu["terbesar_id"], "")
    return [Insight(
        aturan="PER-07", entitas=m.period_start.isoformat(), tone="info",
        slot=("daftar", "kpi:sisa_bebas", "kpi:terpakai"),
        data={"lalu": lalu, "hari_ke": m.hari_ke, "ps": m.period_start, "pe": m.period_end,
              "j1": m.j1, "r": m.sisa_hari},
        aksi=[{"kind": "route", "kode": "bagi_pemasukan", "payload": {"path": "/allocate?new=1"}},
              {"kind": "route", "kode": "lihat_periode_lalu", "payload": {"path": "/analytics"}}],
    )]


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*per_01(ctx), *per_02(ctx), *per_03(ctx), *per_04_05(ctx), *per_06(ctx), *per_07(ctx)]
