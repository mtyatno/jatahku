"""Sinyal AI Advisor v2 — deteksi pola S1–S19 (02-aturan.md §4, konstanta §11).

Fungsi murni `compute_signals(snapshot, metrics) -> Signals`: tanpa DB, tanpa jam
sistem (hari ini = `snapshot.today`, "sekarang" = `snapshot.now`). Sinyal hanya
MEMBACA angka dari `metrics.py` (jenis transaksi, deret harian, M4/M13, riwayat
per periode) dan tidak menghitung ulang dana/terpakai/laju (AGENTS.md #1).
Sinyal bukan insight: tidak ada teks di sini; aturan (S3/S4) yang memakainya.

Keputusan kecil S2 (dicatat juga di SESI-LOG.md):
- S1/S4/S4b hanya untuk transaksi periode berjalan; S1 hanya milik viewer, S4
  hanya pasangan dari pencatat yang sama dan deskripsinya terlihat (deskripsi
  privat anggota lain disamarkan, jadi tidak bisa dibandingkan).
- S4b butuh rantai ≥ 2 barang; struk satu barang yang terkirim dua kali = S4.
  Pasangan S4 yang sudah tercakup grup S4b tidak dilaporkan lagi.
- S3: kelompok (amplop, deskripsi ternormalisasi), ≥ 2 kemunculan, interval
  `detect_interval` dengan keyakinan ≥ medium, nominal exact/stable_range, dan
  kemunculan terakhir belum lewat 2× interval.
- S5: "median variabel per 7 hari" = median dari (variabel periode × 7 ÷ D periode)
  untuk ≤ 3 periode lalu yang punya dana/terpakai; butuh ≥ 2 periode.
- S8/S9 butuh 3 periode lalu yang punya dana/terpakai (kronis = 3 periode).
- S12/S13/S18 hanya untuk Jenis Pendapatan bulanan (harian/mingguan/tidak tentu
  tidak punya "hari biasa gajian").
- S15 dibaca harfiah: 14 hari terakhir = t−13..t.
- S17 membandingkan terpakai s/d hari ini dengan periode lalu s/d hari ke-d;
  periode lalu terpakai 0 tidak dibandingkan (amplop baru).
- S18: selisih tanggal pemasukan terbesar ke awal periode terdekat (periodenya
  sendiri atau periode berikutnya), jadi gaji yang masuk lebih awal ikut terbaca.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.services.advisor.formatting import _median_decimal
from app.services.advisor.metrics import BELANJA_PURPOSES, Metrics
from app.services.advisor.sinking import (
    _amount_stability, _next_expected_date, _token_overlap, detect_interval, normalize_description,
)
from app.services.advisor.snapshot import Snapshot

ZERO = Decimal("0")
_STRUK_RE = re.compile(r"^(?P<barang>.+?)\s*\((?P<toko>[^()]+)\)\s*$")


@dataclass(frozen=True)
class KonstantaSinyal:
    """02-aturan.md §11 — nilai default; kelak bisa ditimpa AppSetting."""
    struk_jeda_detik: int = 10                       # S1
    dobel_menit: int = 10                            # S4
    dobel_token: float = 0.8                         # S4
    struk_dobel_menit: int = 30                      # S4b
    struk_dobel_porsi: Decimal = Decimal("0.8")      # S4b
    lonjakan_kali: Decimal = Decimal("2")            # S5
    lonjakan_min: Decimal = Decimal("100000")        # S5
    lonjakan_periode: int = 3                        # S5 (median ≤ 3 periode lalu)
    lonjakan_periode_min: int = 2                    # S5
    menganggur_porsi: Decimal = Decimal("0.1")       # S7
    menganggur_waktu: Decimal = Decimal("0.5")       # S7
    kronis_periode: int = 3                          # S8, S9
    kurang_kronis: Decimal = Decimal("1.15")         # S8
    tambal_kronis_n: int = 3                         # S8 (ditambal berulang)
    tambal_kronis_periode: int = 2                   # S8
    lebih_kronis: Decimal = Decimal("0.6")           # S9
    tagihan_berubah: Decimal = Decimal("0.05")       # S10
    ganda_token: float = 0.6                         # S11
    ganda_nominal: Decimal = Decimal("0.1")          # S11
    rutin_token: float = 0.5                         # S3 vs langganan aktif
    rutin_nominal: Decimal = Decimal("0.15")         # S3 vs langganan aktif
    pemasukan_telat_hari: int = 3                    # S12, S13
    pemasukan_kecil: Decimal = Decimal("0.8")        # S13
    belum_dijatah_min: Decimal = Decimal("10000")    # S14
    belum_dijatah_jam: int = 24                      # S14
    lupa_catat_hari: int = 2                         # S15
    lupa_catat_jendela: int = 14                     # S15
    lupa_catat_aktif: int = 10                       # S15
    non_rollover_hari: int = 3                       # S16
    tren_porsi: Decimal = Decimal("0.25")            # S17
    tren_min: Decimal = Decimal("100000")            # S17
    gajian_geser_hari: int = 3                       # S18
    gajian_geser_n: int = 2                          # S18 (dari 3 periode)


DEFAULT = KonstantaSinyal()


# ── hasil ───────────────────────────────────────────────────────────────
@dataclass
class Struk:                       # S1
    id: str                        # "struk:{txn pertama}"
    toko: str
    txn_ids: list[str]
    total: Decimal
    mulai: datetime
    selesai: datetime


@dataclass
class Signals:
    struk: list[Struk] = field(default_factory=list)                   # S1
    outlier: list[dict] = field(default_factory=list)                  # S2
    rutin: list[dict] = field(default_factory=list)                    # S3
    dobel: list[dict] = field(default_factory=list)                    # S4
    struk_dobel: list[dict] = field(default_factory=list)              # S4b
    lonjakan: list[dict] = field(default_factory=list)                 # S5
    lewat_jatah: list[dict] = field(default_factory=list)              # S6
    menganggur: list[dict] = field(default_factory=list)               # S7
    kurang_kronis: list[dict] = field(default_factory=list)            # S8
    lebih_kronis: list[dict] = field(default_factory=list)             # S9
    tagihan_berubah: list[dict] = field(default_factory=list)          # S10
    langganan_ganda: list[dict] = field(default_factory=list)          # S11
    pemasukan_terlambat: dict | None = None                            # S12
    pemasukan_kecil: dict | None = None                                # S13
    belum_dijatah: list[dict] = field(default_factory=list)            # S14
    lupa_catat: dict | None = None                                     # S15
    sisa_non_rollover: list[dict] = field(default_factory=list)        # S16
    tren: list[dict] = field(default_factory=list)                     # S17
    gajian_bergeser: dict | None = None                                # S18
    dibayar_manual: list[dict] = field(default_factory=list)           # S19

    _KODE = (
        ("S1", "struk"), ("S2", "outlier"), ("S3", "rutin"), ("S4", "dobel"), ("S4b", "struk_dobel"),
        ("S5", "lonjakan"), ("S6", "lewat_jatah"), ("S7", "menganggur"), ("S8", "kurang_kronis"),
        ("S9", "lebih_kronis"), ("S10", "tagihan_berubah"), ("S11", "langganan_ganda"),
        ("S12", "pemasukan_terlambat"), ("S13", "pemasukan_kecil"), ("S14", "belum_dijatah"),
        ("S15", "lupa_catat"), ("S16", "sisa_non_rollover"), ("S17", "tren"),
        ("S18", "gajian_bergeser"), ("S19", "dibayar_manual"),
    )

    def aktif(self) -> list[str]:
        """Kode sinyal yang menyala, urut S1..S19."""
        return [kode for kode, attr in self._KODE if getattr(self, attr)]


# ── pembantu ────────────────────────────────────────────────────────────
def parse_struk(description: str | None) -> tuple[str, str] | None:
    """"NAMA (Toko)" → (nama, toko); format item struk dari `receiptSplit.js`."""
    m = _STRUK_RE.match(description or "")
    if not m:
        return None
    return m.group("barang").strip(), m.group("toko").strip()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _norm(desc: str) -> str:
    return " ".join((desc or "").lower().split())


def _description_visible(x, viewer_id: str) -> bool:
    return x.user_id == viewer_id or not x.is_private


def chains(txns, jeda_detik: int) -> list[Struk]:
    """S1: rantai transaksi struk per toko, jeda berurutan ≤ `jeda_detik`."""
    by_toko: dict[str, list] = {}
    for x in txns:
        parsed = parse_struk(x.description)
        if parsed is None or x.created_at is None:
            continue
        by_toko.setdefault(parsed[1].lower(), []).append((parsed[1], x))
    out: list[Struk] = []
    for key in sorted(by_toko):
        items = sorted(by_toko[key], key=lambda p: (_aware(p[1].created_at), p[1].id))
        cur: list = []
        for toko, x in items:
            if cur and (_aware(x.created_at) - _aware(cur[-1][1].created_at)).total_seconds() > jeda_detik:
                out.append(_make_struk(cur))
                cur = []
            cur.append((toko, x))
        if cur:
            out.append(_make_struk(cur))
    out.sort(key=lambda s: (s.mulai, s.id))
    return out


def _make_struk(items) -> Struk:
    xs = [x for _, x in items]
    return Struk(
        id=f"struk:{xs[0].id}", toko=items[0][0], txn_ids=[x.id for x in xs],
        total=sum((x.amount for x in xs), ZERO),
        mulai=_aware(xs[0].created_at), selesai=_aware(xs[-1].created_at),
    )


def _pair_ratio(a: list[tuple], b: list[tuple]) -> Decimal:
    """Porsi pasangan (nominal, deskripsi) identik antara dua multiset."""
    pool = list(b)
    hit = 0
    for item in a:
        if item in pool:
            pool.remove(item)
            hit += 1
    return Decimal(hit) / Decimal(max(len(a), len(b)))


# ── utama ───────────────────────────────────────────────────────────────
def compute_signals(snap: Snapshot, m: Metrics, k: KonstantaSinyal = DEFAULT) -> Signals:
    s = Signals()
    t = snap.today
    ps, pe = m.period_start, m.period_end
    viewer = snap.viewer_id
    envs = {e.id: e for e in snap.envelopes}
    belanja = [e.id for e in snap.envelopes if e.purpose in BELANJA_PURPOSES]
    txn_by_id = {x.id: x for x in snap.transactions if x.envelope_id in envs}
    cur = [x for x in txn_by_id.values() if ps <= x.transaction_date <= pe]
    cur.sort(key=lambda x: (_aware(x.created_at) if x.created_at else datetime.min.replace(tzinfo=timezone.utc), x.id))

    # S1 struk (viewer, periode berjalan)
    s.struk = chains([x for x in cur if x.user_id == viewer and not x.is_adjustment], k.struk_jeda_detik)
    chain_of = {tid: st.id for st in s.struk for tid in st.txn_ids}

    # S4b struk terkirim dua kali
    covered: set[frozenset] = set()
    for i, a in enumerate(s.struk):
        if len(a.txn_ids) < 2:
            continue
        for b in s.struk[i + 1:]:
            if len(b.txn_ids) < 2 or b.toko.lower() != a.toko.lower():
                continue
            if (b.mulai - a.selesai).total_seconds() > k.struk_dobel_menit * 60:
                continue
            ia = [(txn_by_id[x].amount, _norm(txn_by_id[x].description)) for x in a.txn_ids]
            ib = [(txn_by_id[x].amount, _norm(txn_by_id[x].description)) for x in b.txn_ids]
            if _pair_ratio(ia, ib) >= k.struk_dobel_porsi:
                s.struk_dobel.append({
                    "toko": a.toko, "struk_ids": [a.id, b.id], "n_barang": len(b.txn_ids),
                    "txn_ids": list(b.txn_ids), "total": b.total,
                })
                covered.add(frozenset((a.id, b.id)))

    # S4 kemungkinan dobel
    groups: list[list] = []
    for x in cur:
        if x.is_adjustment or x.created_at is None or not _description_visible(x, viewer):
            continue
        nx = normalize_description(x.description)
        if not nx:
            continue
        for g in groups:
            first, last = g[0], g[-1]
            if (first.envelope_id, first.user_id, first.amount) != (x.envelope_id, x.user_id, x.amount):
                continue
            if (_aware(x.created_at) - _aware(last.created_at)).total_seconds() > k.dobel_menit * 60:
                continue
            if _token_overlap(normalize_description(first.description), nx) < k.dobel_token:
                continue
            cx = chain_of.get(x.id)
            if cx is not None and any(chain_of.get(y.id) == cx for y in g):
                continue  # barang kembar dalam satu struk
            if cx is not None and all(
                frozenset((chain_of.get(y.id), cx)) in covered for y in g
            ):
                continue  # sudah ditandai S4b
            g.append(x)
            break
        else:
            groups.append([x])
    for g in groups:
        if len(g) >= 2:
            s.dobel.append({
                "envelope_id": g[0].envelope_id, "jumlah": g[0].amount,
                "txn_ids": [y.id for y in g], "hapus_saran": [y.id for y in g[1:]],
            })

    # S2 outlier (periode berjalan, dari metrics.jenis_transaksi)
    for x in sorted(cur, key=lambda x: (x.transaction_date, x.id)):
        if x.transaction_date <= t and m.jenis_transaksi.get(x.id) == "outlier":
            s.outlier.append({
                "txn_id": x.id, "envelope_id": x.envelope_id, "jumlah": x.amount,
                "tanggal": x.transaction_date, "hari_ini": x.transaction_date == t,
            })

    # S3 pola rutin
    s.rutin = _pola_rutin(snap, envs, t, k)

    # S5 lonjakan, S8/S9 kronis, S17 tren (dari riwayat metrics)
    D_per = [(p_e - p_s).days + 1 for p_s, p_e in m.periode]
    for eid in belanja:
        rw = m.riwayat.get(eid)
        em = m.amplop[eid]
        if rw is None:
            continue
        past = [i for i in range(len(m.periode) - 1) if rw.dana[i] != 0 or rw.terpakai[i] != 0]

        # S5
        hist = past[-k.lonjakan_periode:]
        if len(hist) >= k.lonjakan_periode_min:
            med7 = _median_decimal([rw.variabel[i] * 7 / D_per[i] for i in hist])
            v7 = em.porsi_7h
            if v7 > med7 * k.lonjakan_kali and v7 - med7 >= k.lonjakan_min:
                s.lonjakan.append({"envelope_id": eid, "variabel_7h": v7, "median_7h": med7,
                                   "selisih": v7 - med7})

        # S8 / S9
        hist = past[-k.kronis_periode:]
        if len(hist) >= k.kronis_periode:
            med_terpakai = _median_decimal([rw.terpakai[i] for i in hist])
            budget = envs[eid].budget_amount or ZERO
            jatah = budget if budget > 0 else _median_decimal([rw.alokasi_utama[i] for i in hist])
            ditambal = sum(1 for i in hist if rw.tambalan_n[i] >= k.tambal_kronis_n)
            lewat = jatah > 0 and med_terpakai > jatah * k.kurang_kronis
            if lewat or ditambal >= k.tambal_kronis_periode:
                s.kurang_kronis.append({
                    "envelope_id": eid, "median_terpakai": med_terpakai, "jatah": jatah,
                    "periode_ditambal": ditambal, "alasan": "terpakai" if lewat else "tambalan",
                })
            elif (jatah > 0 and med_terpakai <= jatah * k.lebih_kronis
                  and all(rw.tambalan_n[i] == 0 for i in hist) and rw.tambalan_n[-1] == 0):
                s.lebih_kronis.append({"envelope_id": eid, "median_terpakai": med_terpakai, "jatah": jatah,
                                       "kelebihan": jatah - med_terpakai})

        # S17 tren
        lalu, ini = rw.terpakai_lalu_sd_hari_ke, rw.terpakai_sd_hari_ini
        if lalu is not None and lalu > 0:
            selisih = ini - lalu
            if abs(selisih) >= lalu * k.tren_porsi and abs(selisih) >= k.tren_min:
                s.tren.append({"envelope_id": eid, "terpakai": ini, "terpakai_lalu": lalu,
                               "selisih": selisih, "arah": "naik" if selisih > 0 else "turun",
                               "persen": selisih / lalu})

    # S6 hari lewat jatah
    s.lewat_jatah = [
        {"tanggal": h["tanggal"], "variabel": h["variabel"], "jatah": h["jatah"], "hari_ini": h["tanggal"] == t}
        for h in m.harian if h["lewat"]
    ]

    # S7 amplop menganggur
    if Decimal(m.hari_ke) >= Decimal(m.hari_total) * k.menganggur_waktu:
        for eid in belanja:
            em = m.amplop[eid]
            if em.dana > 0 and em.terpakai <= em.dana * k.menganggur_porsi and em.tagihan_sisa == 0:
                s.menganggur.append({"envelope_id": eid, "dana": em.dana, "terpakai": em.terpakai,
                                     "bebas": em.bebas})

    # S10 nominal tagihan berubah, S11 langganan ganda
    recs = sorted(snap.recurring, key=lambda r: r.id)
    for x in sorted(cur, key=lambda x: (x.transaction_date, x.id)):
        if x.bill_desc is None:
            continue
        for rec in recs:
            if rec.envelope_id == x.envelope_id and rec.description == x.bill_desc and rec.amount > 0:
                if abs(x.amount - rec.amount) > rec.amount * k.tagihan_berubah:
                    s.tagihan_berubah.append({
                        "recurring_id": rec.id, "txn_id": x.id, "nominal": rec.amount,
                        "dibayar": x.amount, "selisih": x.amount - rec.amount,
                    })
                break
    for i, a in enumerate(recs):
        na = normalize_description(a.description)
        for b in recs[i + 1:]:
            if (_token_overlap(na, normalize_description(b.description)) >= k.ganda_token
                    and a.amount > 0 and abs(a.amount - b.amount) <= a.amount * k.ganda_nominal):
                s.langganan_ganda.append({"recurring_ids": [a.id, b.id], "jumlah": [a.amount, b.amount]})

    # S12 / S13 / S18 pemasukan (hanya Jenis Pendapatan bulanan)
    if snap.income_type == "monthly" and m.hari_biasa_masuk is not None:
        hari_biasa = ps + timedelta(days=m.hari_biasa_masuk)
        if t > hari_biasa + timedelta(days=k.pemasukan_telat_hari):
            if m.pemasukan_rumah_tangga == 0:
                s.pemasukan_terlambat = {"hari_biasa": hari_biasa, "telat_hari": (t - hari_biasa).days}
            elif m.pemasukan_biasa and m.pemasukan_rumah_tangga < m.pemasukan_biasa * k.pemasukan_kecil:
                s.pemasukan_kecil = {"pemasukan": m.pemasukan_rumah_tangga, "biasa": m.pemasukan_biasa,
                                     "kurang": m.pemasukan_biasa - m.pemasukan_rumah_tangga}
    if snap.income_type == "monthly":
        s.gajian_bergeser = _gajian_bergeser(snap, m, k)

    # S14 belum dijatah
    now = _aware(snap.now) if snap.now else datetime.combine(t, time.max, tzinfo=timezone.utc)
    inc_by_id = {i.id: i for i in snap.incomes}
    for b in m.belum_dijatah_rincian:
        dicatat = b.get("dicatat")
        if dicatat is None:
            inc = inc_by_id.get(b["income_id"])
            dicatat = datetime.combine(inc.income_date, time.min, tzinfo=timezone.utc) if inc else None
        if dicatat is None or b["sisa"] <= k.belum_dijatah_min:
            continue
        if (now - _aware(dicatat)).total_seconds() > k.belum_dijatah_jam * 3600:
            s.belum_dijatah.append({"income_id": b["income_id"], "sisa": b["sisa"]})

    # S15 lupa catat
    if m.hari_tanpa_catatan is not None and m.hari_tanpa_catatan >= k.lupa_catat_hari:
        mulai = t - timedelta(days=k.lupa_catat_jendela - 1)
        hari = {x.transaction_date for x in snap.transactions
                if x.user_id == viewer and not x.is_adjustment and mulai <= x.transaction_date <= t}
        if len(hari) >= k.lupa_catat_aktif:
            s.lupa_catat = {"hari_tanpa_catatan": m.hari_tanpa_catatan, "hari_mencatat": len(hari)}

    # S16 sisa amplop non-rollover
    if m.sisa_hari <= k.non_rollover_hari:
        for e in snap.envelopes:
            em = m.amplop.get(e.id)
            if em is not None and not e.is_rollover and em.bebas > 0:
                s.sisa_non_rollover.append({"envelope_id": e.id, "bebas": em.bebas})

    # S19 tagihan dibayar manual (M13)
    for e in snap.envelopes:
        for row in m.amplop[e.id].dibayar_manual:
            s.dibayar_manual.append({"envelope_id": e.id, **row})

    return s


def _pola_rutin(snap: Snapshot, envs, t: date, k: KonstantaSinyal) -> list[dict]:
    """S3: transaksi berulang yang belum jadi langganan aktif."""
    groups: dict[tuple[str, str], list] = {}
    for x in snap.transactions:
        if (x.envelope_id not in envs or x.is_adjustment or x.bill_desc is not None
                or x.transaction_date > t or not _description_visible(x, snap.viewer_id)):
            continue
        key = normalize_description(x.description)
        if key:
            groups.setdefault((x.envelope_id, key), []).append(x)
    out = []
    for (eid, key), xs in sorted(groups.items()):
        dates = [x.transaction_date for x in xs]
        if len(set(dates)) < 2:
            continue
        interval = detect_interval(dates, key)
        if interval["frequency"] == "unknown" or interval["confidence"] == "low":
            continue
        stab = _amount_stability([x.amount for x in xs])
        if stab["kind"] not in ("exact", "stable_range"):
            continue
        if (t - max(dates)).days > 2 * interval["median_days"]:
            continue  # pola sudah berhenti
        nominal = stab["suggested_amount"]
        if any(
            _token_overlap(key, normalize_description(r.description)) >= k.rutin_token
            and r.amount > 0 and abs(nominal - r.amount) <= r.amount * k.rutin_nominal
            for r in snap.recurring
        ):
            continue
        xs_sorted = sorted(xs, key=lambda x: (x.transaction_date, x.id))
        out.append({
            "envelope_id": eid, "kunci": key, "frekuensi": interval["frequency"],
            "keyakinan": interval["confidence"], "nominal": nominal, "nominal_jenis": stab["kind"],
            "kemunculan": len(set(dates)), "terakhir": max(dates),
            "berikutnya": _next_expected_date(dates, interval),
            "contoh_txn_id": xs_sorted[-1].id, "txn_ids": [x.id for x in xs_sorted],
        })
    return out


def _gajian_bergeser(snap: Snapshot, m: Metrics, k: KonstantaSinyal) -> dict | None:
    """S18: pemasukan terbesar di ≥ 2 dari 3 periode lalu masuk ≥ 3 hari dari awal periode."""
    periods = m.periode
    past = []
    for idx in range(len(periods) - 1):
        p_s, p_e = periods[idx]
        inc = [i for i in snap.incomes if i.amount > 0 and not i.is_adjustment and p_s <= i.income_date <= p_e]
        if inc:
            past.append((idx, max(inc, key=lambda i: (i.amount, i.income_date))))
    past = past[-3:]
    if len(past) < k.gajian_geser_n:
        return None
    offsets = []
    for idx, inc in past:
        own = (inc.income_date - periods[idx][0]).days
        nxt = (inc.income_date - periods[idx + 1][0]).days
        offsets.append(own if abs(own) <= abs(nxt) else nxt)
    geser = [o for o in offsets if abs(o) >= k.gajian_geser_hari]
    if len(geser) < k.gajian_geser_n:
        return None
    return {"payday_day": snap.payday_day, "selisih_hari": offsets,
            "median_selisih": int(_median_decimal([Decimal(o) for o in geser]))}
