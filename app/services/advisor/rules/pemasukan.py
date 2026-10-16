"""Aturan E. Pemasukan — INC-01..06 (02-aturan.md §6E). Fungsi murni `(Konteks) → [Insight]`.

Angka dari metrics.py (P1–P6) dan sinyal S12 (terlambat), S13 (lebih kecil), S14 (belum
dijatah), S18 (gajian bergeser).

Keputusan kecil S4 (juga di SESI-LOG.md):
- INC-02 menyebut anggota yang paling banyak mengisi amplop bersama periode ini, dengan
  jumlah yang masuk ke amplop bersama saja (bukan total pemasukan pribadinya, §2 privasi).
  Bila tidak ada yang masuk ke amplop bersama, nama pencatat pemasukan terbesar tanpa angka.
- INC-05 selalu ada sebagai cadangan chip Income: ok bila P6 ≥ 10%, info bila turun ≥ 5 poin
  dari median 3 periode lalu atau di bawah 10%; tanpa pemasukan sama sekali → "Belum ada
  pemasukan" (info).
- INC-03 keyakinan sedang (pola lintas periode, median ≤ 3 periode).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.services.advisor.formatting import _median_decimal
from app.services.advisor.insight import Insight, Konteks
from app.services.advisor.metrics import rupiah, saving_rate_riwayat

ZERO = Decimal("0")


def _catat(jumlah=None, kode="catat_pemasukan") -> dict:
    return {"kind": "income", "kode": kode, "payload": {"jumlah": rupiah(jumlah)} if jumlah else {}}


def inc_01(ctx: Konteks) -> list[Insight]:
    m, s = ctx.m, ctx.s
    if not s.pemasukan_terlambat:
        return []
    ins = Insight(
        aturan="INC-01", entitas=m.period_start.isoformat(), tone="danger" if m.sisa_bebas < 0 else "warn",
        slot=("daftar", "kpi:income"),
        data={"hari_biasa": s.pemasukan_terlambat["hari_biasa"], "telat": s.pemasukan_terlambat["telat_hari"],
              "biasa": m.pemasukan_biasa},
        rupiah=m.pemasukan_biasa or ZERO, urgensi=Decimal("0.8"),
    )
    ins.aksi = [_catat(m.pemasukan_biasa),
                {"kind": "dismiss", "kode": "ingatkan_besok", "payload": {"kunci": ins.id, "pilihan": "nanti"}}]
    return [ins]


def inc_02(ctx: Konteks) -> list[Insight]:
    m, snap = ctx.m, ctx.snap
    if m.pemasukan_saya != 0 or m.pemasukan_rumah_tangga <= 0:
        return []
    lain = {uid: v for uid, v in m.pemasukan_per_anggota_bersama.items() if uid != snap.viewer_id and v > 0}
    if lain:
        uid = max(lain, key=lambda u: (lain[u], u))
        jumlah = lain[uid]
    else:
        incs = [i for i in snap.incomes if i.amount > 0 and not i.is_adjustment and i.user_id != snap.viewer_id
                and m.period_start <= i.income_date <= m.period_end]
        uid = max(incs, key=lambda i: (i.amount, i.id)).user_id if incs else None
        jumlah = None
    return [Insight(
        aturan="INC-02", entitas=m.period_start.isoformat(), tone="info", slot=("kpi:income",),
        data={"nama": snap.member_names.get(uid, "anggota lain") if uid else "anggota lain", "jumlah": jumlah},
        aksi=[_catat(kode="catat_pemasukanku")],
    )]


def inc_03(ctx: Konteks) -> list[Insight]:
    m, s = ctx.m, ctx.s
    if not s.pemasukan_kecil:
        return []
    x = s.pemasukan_kecil
    return [Insight(
        aturan="INC-03", entitas=m.period_start.isoformat(), tone="warn", slot=("daftar", "kpi:income", "alokasi"),
        data={"pemasukan": x["pemasukan"], "biasa": x["biasa"], "kurang": x["kurang"],
              "persen": x["kurang"] / x["biasa"] if x["biasa"] else None},
        aksi=[{"kind": "route", "kode": "sesuaikan_alokasi", "payload": {"path": "/allocate?new=1"}}],
        rupiah=x["kurang"], urgensi=Decimal("0.4"), keyakinan="sedang",
    )]


def inc_04(ctx: Konteks) -> list[Insight]:
    m, s = ctx.m, ctx.s
    if not s.belum_dijatah:
        return []
    total = sum((x["sisa"] for x in s.belum_dijatah), ZERO)
    return [Insight(
        aturan="INC-04", entitas=m.period_start.isoformat(), tone="warn", slot=("daftar", "kpi:income", "alokasi"),
        data={"jumlah": total, "n": len(s.belum_dijatah)},
        aksi=[{"kind": "route", "kode": "bagi_sekarang",
               "payload": {"path": f"/allocate?new=1&amount={rupiah(total)}"}}],
        rupiah=total, urgensi=Decimal("0.6"),
    )]


def inc_05(ctx: Konteks) -> list[Insight]:
    m, k = ctx.m, ctx.k
    p6 = m.saving_rate
    if p6 is None:
        return [Insight(aturan="INC-05", entitas=m.period_start.isoformat(), tone="info", slot=("kpi:income",),
                        data={"kosong": m.pemasukan_rumah_tangga <= 0, "rate": None},
                        aksi=[_catat()])]
    hist = saving_rate_riwayat(ctx.snap, m)
    median = _median_decimal(hist) if hist else None
    turun = median is not None and p6 <= median - k.saving_rate_turun
    return [Insight(
        aturan="INC-05", entitas=m.period_start.isoformat(),
        tone="ok" if p6 >= k.saving_rate_ok and not turun else "info", slot=("kpi:income",),
        data={"kosong": False, "rate": p6, "median": median, "turun": turun, "pemasukan": m.pemasukan_saya},
    )]


def inc_06(ctx: Konteks) -> list[Insight]:
    m, s = ctx.m, ctx.s
    if not s.gajian_bergeser:
        return []
    x = s.gajian_bergeser
    biasa = (m.period_start + timedelta(days=x["median_selisih"])).day
    return [Insight(
        aturan="INC-06", entitas="payday", tone="info", slot=("daftar", "kpi:income"),
        data={"payday_day": x["payday_day"], "tanggal": biasa, "selisih": x["selisih_hari"]},
        aksi=[{"kind": "route", "kode": "ubah_tanggal_gajian", "payload": {"path": "/settings"}}],
        keyakinan="sedang",
    )]


def evaluasi(ctx: Konteks) -> list[Insight]:
    return [*inc_01(ctx), *inc_02(ctx), *inc_03(ctx), *inc_04(ctx), *inc_05(ctx), *inc_06(ctx)]
