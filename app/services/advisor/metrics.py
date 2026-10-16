"""Metrik AI Advisor v2 — SATU sumber angka periode (02-aturan.md §3, AGENTS.md "AI Advisor v2" #1).

Fungsi murni `compute_metrics(snapshot) -> Metrics`: tanpa DB, tanpa jam sistem
(hari ini = `snapshot.today`). Semua angka periode — dana belanja, terpakai,
sisa bebas, J0, J1, laju, proyeksi, deret grafik — dihitung DI SINI saja. Route,
bot, scheduler, dan frontend membaca hasilnya; dilarang menulis rumus pembagi
hari sendiri.

Kode metrik mengikuti spesifikasi: M1–M13 per amplop, T1–T11 total belanja,
P1–P6 pemasukan, G1–G8 tabungan & target, K1–K4 lain-lain, plus `riwayat`
per amplop per periode (ditambah S2 untuk sinyal lintas periode). S2–S5 boleh MENAMBAH
fungsi di sini, tidak mengubah rumus yang ada (03-workflow.md §7 kepemilikan file).

Keputusan kecil S1 (dicatat juga di SESI-LOG.md):
- Jendela laju 7 hari = t−6..t (termasuk hari ini, sama dengan contoh §12). Bila
  d < 7 jendelanya belum utuh di periode ini, jadi T4/M8 = variabel sejak ps ÷ d.
- M8, T8, T9, T10 tidak dihitung bila d < 3 (konstanta "hari minimum proyeksi").
- `tanggal_habis` = hari pertama uang tidak cukup = t + ⌊T3 ÷ T4⌋ + 1 (§12: cukup
  sampai 23 Okt, habis 24 Okt); `cukup_sampai` = t + ⌊T3 ÷ T4⌋.
- J0 tidak boleh negatif (dibatasi 0). Penyesuaian cocokkan saldo yang MENAMBAH
  dana hari ini (Income penyesuaian) juga dikeluarkan dari J0, supaya invarian J0
  berlaku untuk penyesuaian dua arah.
- M4: transaksi "🔄 X" hanya melunasi langganan X (lewat `next_run` yang sudah maju),
  dan tidak ikut kolam nominal-persis tagihan lain. Selebihnya sama dengan `reserved.py`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.services.advisor.formatting import _median_decimal, _to_decimal
from app.services.advisor.snapshot import Snapshot

ZERO = Decimal("0")

BELANJA_PURPOSES = ("expense", "debt")
SAVING_PURPOSES = ("saving", "sinking_fund")
EMERGENCY_KEYWORDS = ("darurat", "emergency")


def is_emergency_name(name: str | None) -> bool:
    """Tebakan dana darurat dari nama (backfill migrasi & amplop baru)."""
    low = (name or "").lower()
    return any(k in low for k in EMERGENCY_KEYWORDS)


@dataclass(frozen=True)
class Konstanta:
    """02-aturan.md §11 — nilai default; kelak bisa ditimpa AppSetting."""
    hari_min_proyeksi: int = 3
    jendela_laju: int = 7
    hari_min_berbelanja: int = 3
    cadangan_surplus: Decimal = Decimal("0.1")
    toleransi_langganan: Decimal = Decimal("0.1")
    outlier_kali_median: Decimal = Decimal("2")
    outlier_porsi_dana: Decimal = Decimal("0.3")
    outlier_hari_median: int = 90
    periode_riwayat: int = 3
    bulan_target_tanpa_tenggat: int = 24


DEFAULT = Konstanta()


# ── pembulatan ──────────────────────────────────────────────────────────
def floor100(value) -> Decimal:
    value = _to_decimal(value)
    return (value / 100).to_integral_value(rounding=ROUND_FLOOR) * 100


def rupiah(value) -> int | None:
    """Decimal → int rupiah (setengah ke atas). None tetap None."""
    if value is None:
        return None
    return int(_to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ── hasil ───────────────────────────────────────────────────────────────
@dataclass
class TagihanStatus:
    """Satu langganan aktif dilihat dari periode berjalan (dasar M4/M5/M13)."""
    recurring_id: str
    envelope_id: str
    frekuensi: str
    nominal: Decimal
    jatuh_tempo: date
    sisa: Decimal                  # kontribusi ke M4 (0 = lunas / tidak jatuh tempo)
    sisihan: Decimal               # kontribusi ke M5 (tahunan)
    telat_hari: int                # > 0 bila jatuh tempo < hari ini dan belum dibayar
    lunas_oleh: str | None = None  # "bayar" (next_run maju + 🔄) | "nominal" (catat manual) | None
    txn_ids: list[str] = field(default_factory=list)


@dataclass
class EnvelopeMetrics:
    id: str
    nama: str
    kelompok: str                  # belanja | tabungan
    kebutuhan: bool                # classification needs (kosong = needs)
    dana: Decimal                  # M1
    terpakai: Decimal              # M2
    sisa: Decimal                  # M3
    tagihan_sisa: Decimal          # M4
    sisihan: Decimal               # M5
    bebas: Decimal                 # M6
    variabel_periode: Decimal      # M7 sejak ps s/d hari ini
    laju: Decimal | None           # M8
    butuh_sisa: Decimal | None     # M9
    surplus: Decimal | None        # M10
    tambalan_n: int                # M11
    tambalan_total: Decimal
    tambalan_sumber: dict          # {env_id | None: jumlah}; None = amplop tak terlihat
    porsi_7h: Decimal              # M12
    porsi_7h_bagian: Decimal       # M12 ÷ Σ M12 belanja (0..1)
    dibayar_manual: list           # M13: [{"recurring_id", "txn_id", "jumlah"}]


@dataclass
class RiwayatAmplop:
    """Angka per periode satu amplop, terlama dulu; indeks terakhir = periode berjalan (S2).

    Dipakai sinyal lintas periode (S5 lonjakan, S8/S9 kronis, S17 tren) supaya
    `signals.py` tidak menghitung ulang dana/terpakai sendiri.
    """
    dana: list[Decimal]            # M1 per periode
    terpakai: list[Decimal]        # M2 per periode
    variabel: list[Decimal]        # M7 per periode (seluruh periode)
    alokasi_utama: list[Decimal]   # alokasi positif dari pemasukan sungguhan (bukan transfer/penyesuaian)
    tambalan_n: list[int]          # M11 per periode
    terpakai_sd_hari_ini: Decimal  # M2 periode berjalan s/d t
    terpakai_lalu_sd_hari_ke: Decimal | None  # M2 periode lalu s/d hari ke-d yang sama


@dataclass
class Metrics:
    today: date
    period_start: date
    period_end: date
    hari_total: int                # D
    hari_ke: int                   # d
    sisa_hari: int                 # r
    horizon: int                   # H
    horizon_awal: int              # H0
    income_type: str
    proyeksi_valid: bool           # d ≥ hari minimum proyeksi
    amplop: dict[str, EnvelopeMetrics]
    tagihan: list[TagihanStatus]
    jenis_transaksi: dict[str, str]  # txn_id → variabel | tagihan | outlier | penyesuaian
    # T1–T11
    dana_belanja: Decimal
    terpakai_belanja: Decimal
    tagihan_sisa: Decimal          # Σ M4 belanja
    sisihan: Decimal               # Σ M5 belanja
    sisa_bebas: Decimal            # T3
    laju_total: Decimal            # T4
    belanja_hari_ini: Decimal      # T5
    keluar_hari_ini: Decimal       # T5b
    j0: Decimal                    # T6
    j1: Decimal | None             # T7
    proyeksi_akhir: Decimal | None  # T8
    kekurangan: Decimal | None     # T9
    tanggal_habis: date | None     # T10
    cukup_sampai: date | None
    persen_dana: Decimal | None    # T11
    persen_waktu: Decimal
    harian: list[dict]
    # P1–P6
    pemasukan_saya: Decimal
    pemasukan_rumah_tangga: Decimal
    pemasukan_per_anggota_bersama: dict[str, Decimal]  # dana masuk ke amplop bersama per anggota
    belum_dijatah: Decimal
    belum_dijatah_rincian: list[dict]
    pemasukan_biasa: Decimal | None
    hari_biasa_masuk: int | None
    saving_rate: Decimal | None
    saving_rate_rumah_tangga: Decimal | None
    # G1–G8
    saldo_tabungan: dict[str, Decimal]
    setoran: dict[str, list[Decimal]]
    setoran_biasa: dict[str, Decimal]
    target: list[dict]
    belanja_bulanan: Decimal
    amplop_darurat: list[str]
    cakupan_darurat: Decimal | None
    # K1–K4
    hari_sejak_cocokkan: int | None
    selisih_terakhir: Decimal | None
    hari_tanpa_catatan: int | None
    beban_tagihan: Decimal | None
    # Riwayat lintas periode (S2)
    periode: list[tuple[date, date]] = field(default_factory=list)
    riwayat: dict[str, RiwayatAmplop] = field(default_factory=dict)

    def to_api(self) -> dict:
        """Bentuk `metrics` di GET /advisor/dashboard (04-kontrak-api.md)."""
        return {
            "dana_belanja": rupiah(self.dana_belanja),
            "terpakai": rupiah(self.terpakai_belanja),
            "tagihan_sisa": rupiah(self.tagihan_sisa),
            "sisa_bebas": rupiah(self.sisa_bebas),
            "j0": rupiah(self.j0),
            "j1": rupiah(self.j1),
            "laju7": rupiah(self.laju_total),
            "belanja_hari_ini": rupiah(self.belanja_hari_ini),
            "proyeksi_akhir": rupiah(self.proyeksi_akhir),
            "kekurangan": rupiah(self.kekurangan),
            "tanggal_habis": self.tanggal_habis.isoformat() if self.tanggal_habis else None,
            "hari_ke": self.hari_ke,
            "hari_total": self.hari_total,
            "sisa_hari": self.sisa_hari,
            "pemasukan_saya": rupiah(self.pemasukan_saya),
            "pemasukan_rumah_tangga": rupiah(self.pemasukan_rumah_tangga),
            "harian": [
                {
                    "tanggal": h["tanggal"].isoformat(),
                    "variabel": rupiah(h["variabel"]),
                    "tagihan": rupiah(h["tagihan"]),
                    "penyesuaian": rupiah(h["penyesuaian"]),
                    "outlier": rupiah(h["outlier"]),
                    "jatah": rupiah(h["jatah"]),
                    "lewat": h["lewat"],
                }
                for h in self.harian
            ],
        }


# ── pembantu murni ──────────────────────────────────────────────────────
def horizons(income_type: str, r: int) -> tuple[int, int]:
    """(H, H0) mengikuti Jenis Pendapatan (§3, PR #20)."""
    if income_type == "daily":
        return min(1, r), 1
    if income_type == "weekly":
        return min(7, r), min(7, r + 1)
    return r, r + 1


def jatah_awal_hari(sisa_bebas_awal: Decimal, h0: int) -> Decimal:
    """J0 = floor100(sisa bebas awal hari ÷ H0), tidak negatif."""
    if h0 <= 0:
        return ZERO
    return floor100(max(sisa_bebas_awal, ZERO) / h0)


def monthly_equivalent(amount: Decimal, frequency: str) -> Decimal:
    if frequency == "weekly":
        return amount * 52 / 12
    if frequency == "yearly":
        return amount / 12
    return amount


def weekly_occurrences(next_run: date, period_end: date) -> int:
    """Jumlah kemunculan mingguan next_run, next_run+7, … yang ≤ period_end."""
    if next_run > period_end:
        return 0
    return (period_end - next_run).days // 7 + 1


def _period_index(d: date, periods) -> int | None:
    for i, (ps, pe) in enumerate(periods):
        if ps <= d <= pe:
            return i
    return None


def _months_until(today: date, target: date) -> int:
    return (target.year - today.year) * 12 + (target.month - today.month)


def _within_tolerance(amount: Decimal, ref: Decimal, tol: Decimal) -> bool:
    return ref > 0 and abs(amount - ref) <= ref * tol


# ── tagihan (M4, M5, M13) ───────────────────────────────────────────────
def compute_bills(recs, txns_by_env, ps: date, pe: date, today: date) -> tuple[list[TagihanStatus], set[str]]:
    """Status tiap langganan aktif + id transaksi yang melunasinya.

    `txns_by_env` = transaksi periode berjalan per amplop. Satu transaksi melunasi
    satu tagihan. Urutan: (1) "🔄 X" untuk X yang next_run-nya sudah maju / mingguan,
    (2) nominal persis untuk tagihan bulanan yang jatuh tempo di periode ini.
    """
    used: set[str] = set()
    out: list[TagihanStatus] = []

    def status(rec, sisa=ZERO, sisihan=ZERO, lunas_oleh=None, txn_ids=None):
        telat = (today - rec.next_run).days if (rec.next_run < today and sisa > 0) else 0
        return TagihanStatus(
            recurring_id=rec.id, envelope_id=rec.envelope_id, frekuensi=rec.frequency,
            nominal=rec.amount, jatuh_tempo=rec.next_run, sisa=sisa, sisihan=sisihan,
            telat_hari=telat, lunas_oleh=lunas_oleh, txn_ids=txn_ids or [],
        )

    def take(env_id, pred):
        for t in txns_by_env.get(env_id, []):
            if t.id not in used and pred(t):
                used.add(t.id)
                return t
        return None

    pending_manual = []
    for rec in recs:
        if rec.frequency == "yearly":
            out.append(status(rec, sisihan=rec.amount / 12))
        elif rec.frequency == "weekly":
            ids = []
            while True:
                t = take(rec.envelope_id, lambda t, d=rec.description: t.bill_desc == d)
                if t is None:
                    break
                ids.append(t.id)
            n = weekly_occurrences(rec.next_run, pe)
            out.append(status(rec, sisa=rec.amount * n, lunas_oleh="bayar" if ids else None, txn_ids=ids))
        elif rec.next_run > pe:  # bulanan, next_run sudah maju: lunas lewat Bayar
            t = take(rec.envelope_id, lambda t, d=rec.description: t.bill_desc == d)
            out.append(status(rec, lunas_oleh="bayar" if t else None, txn_ids=[t.id] if t else []))
        else:
            pending_manual.append(rec)

    for rec in pending_manual:  # bulanan, jatuh tempo ≤ pe
        if ps <= rec.next_run <= pe:
            t = take(rec.envelope_id, lambda t, a=rec.amount: t.bill_desc is None and t.amount == a)
            if t is not None:
                out.append(status(rec, lunas_oleh="nominal", txn_ids=[t.id]))
                continue
        out.append(status(rec, sisa=rec.amount))
    return out, used


# ── utama ───────────────────────────────────────────────────────────────
def compute_metrics(snap: Snapshot, k: Konstanta = DEFAULT) -> Metrics:
    from app.core.period import get_budget_period

    t = snap.today
    periods = snap.periods
    ps, pe = periods[-1]
    D = (pe - ps).days + 1
    d = (t - ps).days + 1
    r = max((pe - t).days, 0)
    H, H0 = horizons(snap.income_type, r)
    proyeksi_valid = d >= k.hari_min_proyeksi
    n_periods = len(periods)

    envs = {e.id: e for e in snap.envelopes}
    belanja_ids = [e.id for e in snap.envelopes if e.purpose in BELANJA_PURPOSES]
    tabungan_ids = [e.id for e in snap.envelopes if e.purpose in SAVING_PURPOSES]
    belanja_set = set(belanja_ids)

    # Rollover per periode: snapshot dari periode SEBELUMNYA (kunci tahun/bulan awal periode itu).
    prev_starts = [get_budget_period(snap.payday_day, p_s - timedelta(days=1))[0] for p_s, _ in periods]

    def rollover(eid: str, i: int) -> Decimal:
        if not envs[eid].is_rollover:
            return ZERO
        p = prev_starts[i]
        return snap.rollover.get((eid, p.year, p.month), ZERO)

    incomes = {i.id: i for i in snap.incomes}

    # Alokasi per amplop per periode (M1, G2), dan transfer masuk periode ini (M11).
    alloc_sum = defaultdict(lambda: [ZERO] * n_periods)
    alloc_pos = defaultdict(lambda: [ZERO] * n_periods)
    allocs_by_income = defaultdict(list)
    for a in snap.allocations:
        allocs_by_income[a.income_id].append(a)
        if a.envelope_id is None or a.envelope_id not in envs:
            continue
        i = _period_index(a.income_date, periods)
        if i is None:
            continue
        alloc_sum[a.envelope_id][i] += a.amount
        if a.amount > 0:
            alloc_pos[a.envelope_id][i] += a.amount

    dana_per = {eid: [alloc_sum[eid][i] + rollover(eid, i) for i in range(n_periods)] for eid in envs}

    # Transaksi per amplop
    txns = [x for x in snap.transactions if x.envelope_id in envs]
    cur_txns_by_env = defaultdict(list)
    spent_per = defaultdict(lambda: [ZERO] * n_periods)
    for x in txns:
        i = _period_index(x.transaction_date, periods)
        if i is None:
            continue
        spent_per[x.envelope_id][i] += x.amount
        if i == n_periods - 1:
            cur_txns_by_env[x.envelope_id].append(x)
    for lst in cur_txns_by_env.values():  # urutan pasti → pencocokan tagihan deterministik
        lst.sort(key=lambda x: (x.transaction_date, x.created_at.timestamp() if x.created_at else 0, x.id))

    # M4/M5/M13
    tagihan, lunas_ids = compute_bills(snap.recurring, cur_txns_by_env, ps, pe, t)
    recs_by_env = defaultdict(list)
    for rec in snap.recurring:
        recs_by_env[rec.envelope_id].append(rec)

    # Jenis transaksi (M7): penyesuaian → tagihan → outlier → variabel
    median_from = t - timedelta(days=k.outlier_hari_median)
    median_amounts = defaultdict(list)
    for x in txns:
        if not x.is_adjustment and median_from <= x.transaction_date <= t:
            median_amounts[x.envelope_id].append(x.amount)
    medians = {eid: _median_decimal(v) for eid, v in median_amounts.items()}

    jenis: dict[str, str] = {}
    for x in txns:
        if x.is_adjustment:
            jenis[x.id] = "penyesuaian"
            continue
        if x.bill_desc is not None or x.id in lunas_ids or any(
            _within_tolerance(x.amount, rec.amount, k.toleransi_langganan) for rec in recs_by_env[x.envelope_id]
        ):
            jenis[x.id] = "tagihan"
            continue
        i = _period_index(x.transaction_date, periods)
        med = medians.get(x.envelope_id, ZERO)
        dana_i = dana_per[x.envelope_id][i] if i is not None else ZERO
        if med > 0 and x.amount > med * k.outlier_kali_median and x.amount > dana_i * k.outlier_porsi_dana:
            jenis[x.id] = "outlier"
            continue
        jenis[x.id] = "variabel"

    # Variabel harian periode berjalan per amplop
    var_day = defaultdict(lambda: defaultdict(lambda: ZERO))     # eid → tanggal → jumlah
    for x in txns:
        if ps <= x.transaction_date <= t and jenis[x.id] == "variabel":
            var_day[x.envelope_id][x.transaction_date] += x.amount

    window_days = [t - timedelta(days=j) for j in range(k.jendela_laju)] if d >= k.jendela_laju else \
        [ps + timedelta(days=j) for j in range(d)]

    def laju_dari(day_totals) -> Decimal:
        since_ps = sum(day_totals.values(), ZERO)
        if d >= k.jendela_laju:
            active = sum(1 for day in window_days if day_totals.get(day, ZERO) > 0)
            if active >= k.hari_min_berbelanja:
                return sum((day_totals.get(day, ZERO) for day in window_days), ZERO) / k.jendela_laju
        return since_ps / d if d > 0 else ZERO

    # M11 tambalan: transfer (Income 0, bukan penyesuaian) masuk ke amplop periode ini
    tambalan = defaultdict(lambda: {"n": 0, "total": ZERO, "sumber": defaultdict(lambda: ZERO)})
    for inc_id, allocs in allocs_by_income.items():
        inc = incomes.get(inc_id)
        if inc is None or inc.is_adjustment or inc.amount != 0 or not (ps <= inc.income_date <= pe):
            continue
        sources = [a for a in allocs if a.amount < 0]
        keluar = -sum((s.amount for s in sources), ZERO)
        for a in allocs:
            if a.amount > 0 and a.envelope_id in envs:
                tb = tambalan[a.envelope_id]
                tb["n"] += 1
                tb["total"] += a.amount
                if not sources:
                    tb["sumber"][None] += a.amount
                for s in sources:  # bagi proporsional bila satu transfer punya beberapa sumber
                    tb["sumber"][s.envelope_id] += a.amount * -s.amount / keluar

    # Riwayat per periode (S2: S5, S8, S9, S17). Rumus sama dengan M1/M2/M7/M11 di atas.
    var_per = defaultdict(lambda: [ZERO] * n_periods)
    for x in txns:
        i = _period_index(x.transaction_date, periods)
        if i is not None and jenis[x.id] == "variabel":
            var_per[x.envelope_id][i] += x.amount
    utama_per = defaultdict(lambda: [ZERO] * n_periods)
    tambal_n_per = defaultdict(lambda: [0] * n_periods)
    for inc_id, allocs in allocs_by_income.items():
        inc = incomes.get(inc_id)
        if inc is None or inc.is_adjustment:
            continue
        i = _period_index(inc.income_date, periods)
        if i is None:
            continue
        for a in allocs:
            if a.amount > 0 and a.envelope_id in envs:
                if inc.amount > 0:
                    utama_per[a.envelope_id][i] += a.amount
                elif inc.amount == 0:
                    tambal_n_per[a.envelope_id][i] += 1
    prev_cut = None
    if n_periods >= 2:
        prev_ps, prev_pe = periods[-2]
        prev_cut = (prev_ps, min(prev_ps + timedelta(days=d - 1), prev_pe))
    riwayat: dict[str, RiwayatAmplop] = {}
    for eid in envs:
        sd_ini = sum((x.amount for x in cur_txns_by_env.get(eid, []) if x.transaction_date <= t), ZERO)
        lalu = None
        if prev_cut is not None:
            lalu = sum((x.amount for x in txns
                        if x.envelope_id == eid and prev_cut[0] <= x.transaction_date <= prev_cut[1]), ZERO)
        riwayat[eid] = RiwayatAmplop(
            dana=list(dana_per[eid]), terpakai=list(spent_per[eid]), variabel=list(var_per[eid]),
            alokasi_utama=list(utama_per[eid]), tambalan_n=list(tambal_n_per[eid]),
            terpakai_sd_hari_ini=sd_ini, terpakai_lalu_sd_hari_ke=lalu,
        )

    # Per amplop
    amplop: dict[str, EnvelopeMetrics] = {}
    porsi_total = ZERO
    for e in snap.envelopes:
        eid = e.id
        dana = dana_per[eid][-1]
        terpakai = spent_per[eid][-1]
        sisa = dana - terpakai
        m4 = sum((b.sisa for b in tagihan if b.envelope_id == eid), ZERO)
        m5 = sum((b.sisihan for b in tagihan if b.envelope_id == eid), ZERO)
        bebas = sisa - m4 - m5
        days = var_day[eid]
        laju = laju_dari(days) if proyeksi_valid else None
        porsi = sum((days.get(day, ZERO) for day in window_days), ZERO)
        if eid in belanja_set:
            porsi_total += porsi
        tb = tambalan.get(eid)
        amplop[eid] = EnvelopeMetrics(
            id=eid, nama=e.name,
            kelompok="belanja" if eid in belanja_set else "tabungan",
            kebutuhan=(e.classification or "needs") != "wants",
            dana=dana, terpakai=terpakai, sisa=sisa, tagihan_sisa=m4, sisihan=m5, bebas=bebas,
            variabel_periode=sum(days.values(), ZERO),
            laju=laju,
            butuh_sisa=None if laju is None else laju * r + m4,
            surplus=None if laju is None else bebas - laju * r * (1 + k.cadangan_surplus),
            tambalan_n=tb["n"] if tb else 0,
            tambalan_total=tb["total"] if tb else ZERO,
            tambalan_sumber=dict(tb["sumber"]) if tb else {},
            porsi_7h=porsi, porsi_7h_bagian=ZERO,
            dibayar_manual=[
                {"recurring_id": b.recurring_id, "txn_id": b.txn_ids[0], "jumlah": b.nominal}
                for b in tagihan if b.envelope_id == eid and b.lunas_oleh == "nominal"
            ],
        )
    for eid in belanja_ids:
        if porsi_total > 0:
            amplop[eid].porsi_7h_bagian = amplop[eid].porsi_7h / porsi_total

    # T1–T11
    bel = [amplop[eid] for eid in belanja_ids]
    T1 = sum((m.dana for m in bel), ZERO)
    T2 = sum((m.terpakai for m in bel), ZERO)
    M4 = sum((m.tagihan_sisa for m in bel), ZERO)
    M5 = sum((m.sisihan for m in bel), ZERO)
    T3 = sum((m.bebas for m in bel), ZERO)
    belanja_days = defaultdict(lambda: ZERO)
    for eid in belanja_ids:
        for day, amt in var_day[eid].items():
            belanja_days[day] += amt
    T4 = laju_dari(belanja_days)
    T5 = belanja_days.get(t, ZERO)

    cur_belanja_txns = [x for eid in belanja_ids for x in cur_txns_by_env.get(eid, [])]
    T5b = sum((x.amount for x in cur_belanja_txns if x.transaction_date == t and x.id not in lunas_ids), ZERO)
    def _is_adj(a) -> bool:
        inc = incomes.get(a.income_id)
        return inc is not None and inc.is_adjustment

    adj_in_today = sum(
        (a.amount for a in snap.allocations if a.envelope_id in belanja_set and a.income_date == t and _is_adj(a)),
        ZERO,
    )
    J0 = jatah_awal_hari(T3 + T5b - adj_in_today, H0)
    J1 = floor100(max(T3, ZERO) / H) if H > 0 else None

    if proyeksi_valid:
        T8 = T2 + M4 + M5 + T4 * r
        T9 = max(ZERO, T4 * r - T3)
        if T3 > 0 and T4 > 0:
            hari = int((T3 / T4).to_integral_value(rounding=ROUND_FLOOR))
            cukup = t + timedelta(days=hari)
            habis = cukup + timedelta(days=1)
        else:
            cukup = habis = None
    else:
        T8 = T9 = cukup = habis = None
    persen_dana = T2 / T1 if T1 > 0 else None
    persen_waktu = Decimal(d) / Decimal(D)

    # Deret harian (grafik + S6): J0 tiap hari dihitung dari sisa bebas awal hari itu.
    roll_bel = sum((rollover(eid, n_periods - 1) for eid in belanja_ids), ZERO)
    lunas_total = sum((x.amount for x in cur_belanja_txns if x.id in lunas_ids), ZERO)
    komitmen = M4 + M5 + lunas_total
    alloc_bel_cur = [
        a for a in snap.allocations
        if a.envelope_id in belanja_set and ps <= a.income_date <= pe
    ]
    harian = []
    day = ps
    while day <= t:
        kind_sum = {"variabel": ZERO, "tagihan": ZERO, "penyesuaian": ZERO, "outlier": ZERO}
        for x in cur_belanja_txns:
            if x.transaction_date == day:
                kind_sum[jenis[x.id]] += x.amount
        if day == t:
            jatah = J0
        else:
            dana_awal = roll_bel + sum(
                (a.amount for a in alloc_bel_cur
                 if a.income_date < day or (a.income_date == day and not _is_adj(a))),
                ZERO,
            )
            keluar_sebelum = sum(
                (x.amount for x in cur_belanja_txns if x.transaction_date < day and x.id not in lunas_ids), ZERO,
            )
            _, h0_day = horizons(snap.income_type, (pe - day).days)
            jatah = jatah_awal_hari(dana_awal - keluar_sebelum - komitmen, h0_day)
        harian.append({**kind_sum, "tanggal": day, "jatah": jatah, "lewat": kind_sum["variabel"] > jatah})
        day += timedelta(days=1)

    # P1–P6
    def is_income(i) -> bool:
        return i.amount > 0 and not i.is_adjustment

    cur_incomes = [i for i in snap.incomes if is_income(i) and ps <= i.income_date <= pe]
    P1 = sum((i.amount for i in cur_incomes if i.user_id == snap.viewer_id), ZERO)
    P2 = sum((i.amount for i in cur_incomes), ZERO)
    shared_ids = {e.id for e in snap.envelopes if e.owner_id is None}
    per_anggota = defaultdict(lambda: ZERO)
    for i in cur_incomes:
        for a in allocs_by_income.get(i.id, []):
            if a.amount > 0 and a.envelope_id in shared_ids:
                per_anggota[i.user_id] += a.amount
    belum_rincian = []
    for i in cur_incomes:
        if i.user_id != snap.viewer_id:
            continue
        dialokasi = sum((a.amount for a in allocs_by_income.get(i.id, []) if a.amount > 0), ZERO)
        if i.amount - dialokasi > 0:
            belum_rincian.append({"income_id": i.id, "sisa": i.amount - dialokasi, "dicatat": i.created_at})
    P3 = sum((b["sisa"] for b in belum_rincian), ZERO)

    hist = list(range(n_periods - 1))  # indeks periode lalu, terlama dulu
    per_period_income = defaultdict(list)
    for i in snap.incomes:
        if is_income(i):
            idx = _period_index(i.income_date, periods)
            if idx is not None and idx < n_periods - 1:
                per_period_income[idx].append(i)
    with_income = [idx for idx in hist if per_period_income[idx]][-k.periode_riwayat:]
    P4 = _median_decimal([sum((i.amount for i in per_period_income[idx]), ZERO) for idx in with_income]) \
        if with_income else None
    P5 = None
    if with_income:
        offs = []
        for idx in with_income:
            biggest = max(per_period_income[idx], key=lambda i: (i.amount, i.income_date))
            offs.append(Decimal((biggest.income_date - periods[idx][0]).days))
        P5 = int(_median_decimal(offs).to_integral_value(rounding=ROUND_HALF_UP))

    tabungan_set = set(tabungan_ids)

    def to_saving(income_list) -> Decimal:
        return sum(
            (a.amount for i in income_list for a in allocs_by_income.get(i.id, [])
             if a.envelope_id in tabungan_set),
            ZERO,
        )

    P6 = to_saving([i for i in cur_incomes if i.user_id == snap.viewer_id]) / P1 if P1 > 0 else None
    P6_rt = to_saving(cur_incomes) / P2 if P2 > 0 else None

    # G1–G8
    saldo_tabungan = {eid: snap.lifetime_balance.get(eid, ZERO) for eid in tabungan_ids}
    setoran = {eid: list(alloc_pos[eid]) for eid in tabungan_ids}
    setoran_biasa = {
        eid: _median_decimal(setoran[eid][:-1][-k.periode_riwayat:]) for eid in tabungan_ids
    }
    target = []
    for g in snap.goals:
        if g.envelope_id not in envs:
            continue
        saldo = snap.lifetime_balance.get(g.envelope_id, ZERO)
        kurang = max(g.target_amount - saldo, ZERO)
        if g.target_date is not None:
            bulan = max(_months_until(t, g.target_date), 1)
            tanpa_tenggat = False
        else:
            bulan = k.bulan_target_tanpa_tenggat
            tanpa_tenggat = True
        biasa = setoran_biasa.get(g.envelope_id, ZERO)
        target.append({
            "goal_id": g.id, "envelope_id": g.envelope_id, "nama": g.name,
            "target": g.target_amount, "saldo": saldo,
            "progres": saldo / g.target_amount if g.target_amount > 0 else None,      # G4
            "butuh_per_bulan": kurang / bulan,                                         # G5
            "tanpa_tenggat": tanpa_tenggat,
            "perkiraan_bulan": (kurang / biasa) if kurang > 0 and biasa > 0 else (ZERO if kurang == 0 else None),  # G6
        })
    t2_hist = [sum((spent_per[eid][idx] for eid in belanja_ids), ZERO) for idx in hist]
    t2_hist = [v for v in t2_hist if v > 0][-k.periode_riwayat:]
    G7 = _median_decimal(t2_hist) if t2_hist else T1
    darurat = [eid for eid in tabungan_ids if envs[eid].is_emergency]
    G8 = (sum((saldo_tabungan[eid] for eid in darurat), ZERO) / G7) if darurat and G7 > 0 else None

    # K1–K4
    chk = snap.last_balance_check
    K1 = (t - chk.created_on).days if chk and chk.created_on else None
    K2 = chk.gap if chk else None
    K3 = (t - snap.last_viewer_txn_date).days if snap.last_viewer_txn_date else None
    beban = sum(
        (monthly_equivalent(rec.amount, rec.frequency) for rec in snap.recurring if rec.envelope_id in belanja_set),
        ZERO,
    )
    K4 = beban / T1 if T1 > 0 else None

    return Metrics(
        today=t, period_start=ps, period_end=pe, hari_total=D, hari_ke=d, sisa_hari=r,
        horizon=H, horizon_awal=H0, income_type=snap.income_type, proyeksi_valid=proyeksi_valid,
        amplop=amplop, tagihan=tagihan, jenis_transaksi=jenis,
        dana_belanja=T1, terpakai_belanja=T2, tagihan_sisa=M4, sisihan=M5, sisa_bebas=T3,
        laju_total=T4, belanja_hari_ini=T5, keluar_hari_ini=T5b, j0=J0, j1=J1,
        proyeksi_akhir=T8, kekurangan=T9, tanggal_habis=habis, cukup_sampai=cukup,
        persen_dana=persen_dana, persen_waktu=persen_waktu, harian=harian,
        pemasukan_saya=P1, pemasukan_rumah_tangga=P2, pemasukan_per_anggota_bersama=dict(per_anggota),
        belum_dijatah=P3, belum_dijatah_rincian=belum_rincian,
        pemasukan_biasa=P4, hari_biasa_masuk=P5, saving_rate=P6, saving_rate_rumah_tangga=P6_rt,
        saldo_tabungan=saldo_tabungan, setoran=setoran, setoran_biasa=setoran_biasa, target=target,
        belanja_bulanan=G7, amplop_darurat=darurat, cakupan_darurat=G8,
        hari_sejak_cocokkan=K1, selisih_terakhir=K2, hari_tanpa_catatan=K3, beban_tagihan=K4,
        periode=list(periods), riwayat=riwayat,
    )


# ── tambahan S5: perkiraan belanja sisa periode untuk perencana dana (§8) ──
def belanja_sisa_riwayat(snap: Snapshot, m: Metrics, eid: str, k: Konstanta = DEFAULT) -> Decimal | None:
    """Median belanja variabel amplop `eid` dari hari ke-d sampai akhir periode, di
    (maks.) 3 periode lalu yang punya transaksi di amplop itu (§8.3b). None = tanpa riwayat.

    Hari ke-d periode lalu = awal periode itu + (d − 1); bila periodenya lebih pendek, 0.
    """
    past = snap.periods[:-1]
    if not past:
        return None
    sums = [ZERO] * len(past)
    ada = [False] * len(past)
    for x in snap.transactions:
        if x.envelope_id != eid:
            continue
        i = _period_index(x.transaction_date, past)
        if i is None:
            continue
        ada[i] = True
        if m.jenis_transaksi.get(x.id) == "variabel" and \
                x.transaction_date >= past[i][0] + timedelta(days=m.hari_ke - 1):
            sums[i] += x.amount
    pilih = [sums[i] for i in range(len(past)) if ada[i]][-k.periode_riwayat:]
    return _median_decimal(pilih) if pilih else None


def perkiraan_belanja_sisa(snap: Snapshot, m: Metrics, eid: str, pakai_riwayat: bool,
                           k: Konstanta = DEFAULT) -> Decimal:
    """Belanja amplop yang diperkirakan masih terjadi s/d akhir periode (dasar surplus §8).

    - laju(e) × r (M8), dinaikkan ke median riwayat bila `pakai_riwayat` dan riwayat lebih besar (§8.3b);
    - bila laju belum bisa dihitung (d < 3): median riwayat, atau jatah × r ÷ D (belanja
      sesuai jatah) bila tanpa riwayat. Jatah = `budget_amount` bila diisi dan lebih kecil
      dari dana(e) (kelebihan dana bisa digeser), selain itu dana(e).
    """
    e = m.amplop[eid]
    r = m.sisa_hari
    hist = belanja_sisa_riwayat(snap, m, eid, k) if (pakai_riwayat or e.laju is None) else None
    if e.laju is not None:
        base = e.laju * r
        if pakai_riwayat and hist is not None and hist > base:
            base = hist
        return base
    if hist is not None:
        return hist
    dana = max(e.dana, ZERO)
    budget = next((x.budget_amount for x in snap.envelopes if x.id == eid), ZERO) or ZERO
    jatah = budget if 0 < budget < dana else dana
    return jatah * r / m.hari_total if m.hari_total > 0 else ZERO


def surplus_rencana(snap: Snapshot, m: Metrics, eid: str, pakai_riwayat: bool,
                    k: Konstanta = DEFAULT) -> Decimal:
    """surplus(e) untuk perencana: bebas(e) − perkiraan belanja sisa × (1 + cadangan 10%).
    Sama dengan M10 bila laju ada dan riwayat tidak lebih besar."""
    e = m.amplop[eid]
    return e.bebas - perkiraan_belanja_sisa(snap, m, eid, pakai_riwayat, k) * (1 + k.cadangan_surplus)


def batas_harian(bebas: Decimal, m: Metrics) -> Decimal:
    """Batas "maksimal/hari" dari sisa bebas amplop: floor100(max(bebas, 0) ÷ H).
    Hari terakhir (H = 0): seluruh sisa bebas. Untuk CTA batas harian, pakai
    bebas_setelah_rencana(e) (penekanan 8, planner.py) sebagai `bebas`."""
    bebas = max(_to_decimal(bebas), ZERO)
    if m.horizon <= 0:
        return floor100(bebas)
    return floor100(bebas / m.horizon)


# ── tambahan S3: angka turunan untuk aturan HAR-*/PER-* (02-aturan.md §5, §6A–B) ──
def variabel_hari_ini_per_amplop(snap: Snapshot, m: Metrics) -> dict[str, Decimal]:
    """Belanja variabel hari ini per amplop belanja (Σ = T5). Penyumbang HAR-01."""
    belanja = {eid for eid, a in m.amplop.items() if a.kelompok == "belanja"}
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for x in snap.transactions:
        if x.envelope_id in belanja and x.transaction_date == m.today \
                and m.jenis_transaksi.get(x.id) == "variabel":
            out[x.envelope_id] += x.amount
    return dict(out)


def laju_periode(m: Metrics) -> Decimal:
    """Rata-rata belanja variabel per hari sejak awal periode (Σ grafik ÷ d). PER-04."""
    total = sum((h["variabel"] for h in m.harian), ZERO)
    return total / m.hari_ke if m.hari_ke > 0 else ZERO


def laju_7_hari(m: Metrics, k: Konstanta = DEFAULT) -> Decimal | None:
    """Σ 7 batang terakhir grafik ÷ 7; None bila periode belum 7 hari. PER-04."""
    if m.hari_ke < k.jendela_laju:
        return None
    return sum((h["variabel"] for h in m.harian[-k.jendela_laju:]), ZERO) / k.jendela_laju


def persen_variabel(m: Metrics) -> Decimal | None:
    """Belanja variabel periode ini ÷ dana belanja (PER-03; tanpa tagihan, outlier, penyesuaian)."""
    if m.dana_belanja <= 0:
        return None
    total = sum((a.variabel_periode for a in m.amplop.values() if a.kelompok == "belanja"), ZERO)
    return total / m.dana_belanja


def perkiraan_sisa(m: Metrics) -> Decimal | None:
    """Perkiraan sisa bebas di akhir periode: T3 − T4 × r (PER-04/05/06). None bila d < 3."""
    if not m.proyeksi_valid:
        return None
    return m.sisa_bebas - m.laju_total * m.sisa_hari


def jumlah_transaksi_laju(snap: Snapshot, m: Metrics, k: Konstanta = DEFAULT) -> int:
    """Jumlah transaksi variabel amplop belanja di jendela laju T4 (dasar keyakinan proyeksi §5)."""
    belanja = {eid for eid, a in m.amplop.items() if a.kelompok == "belanja"}
    mulai = m.today - timedelta(days=k.jendela_laju - 1) if m.hari_ke >= k.jendela_laju else m.period_start
    return sum(
        1 for x in snap.transactions
        if x.envelope_id in belanja and mulai <= x.transaction_date <= m.today
        and m.jenis_transaksi.get(x.id) == "variabel"
    )


def ringkasan_periode_lalu(m: Metrics) -> dict | None:
    """PER-07: amplop belanja minus, jumlah tambalan, dan amplop terpakai terbesar di periode lalu."""
    if len(m.periode) < 2:
        return None
    minus, tambalan, terbesar = 0, 0, None
    for eid, a in m.amplop.items():
        rw = m.riwayat.get(eid)
        if a.kelompok != "belanja" or rw is None:
            continue
        if rw.dana[-2] - rw.terpakai[-2] < 0:
            minus += 1
        tambalan += rw.tambalan_n[-2]
        if rw.terpakai[-2] > 0 and (terbesar is None or rw.terpakai[-2] > terbesar[1]):
            terbesar = (eid, rw.terpakai[-2])
    if terbesar is None and minus == 0 and tambalan == 0:
        return None
    return {"minus": minus, "tambalan": tambalan,
            "terbesar_id": terbesar[0] if terbesar else None,
            "terbesar": terbesar[1] if terbesar else ZERO,
            "mulai": m.periode[-2][0], "akhir": m.periode[-2][1]}


# ── tambahan S4: angka turunan untuk aturan AMP-*/TAG-*/INC-*/TAB-*/DAT-* (02-aturan.md §6C–G) ──
def ceil10rb(value) -> Decimal:
    """Dibulatkan ke atas ke Rp10.000 (saran jatah AMP-04/05/06)."""
    v = _to_decimal(value)
    return (v / 10_000).to_integral_value(rounding=ROUND_CEILING) * 10_000


def jumlah_transaksi_laju_amplop(snap: Snapshot, m: Metrics, eid: str, k: Konstanta = DEFAULT) -> int:
    """Transaksi variabel satu amplop di jendela laju M8 (dasar keyakinan proyeksi AMP-02/03)."""
    mulai = m.today - timedelta(days=k.jendela_laju - 1) if m.hari_ke >= k.jendela_laju else m.period_start
    return sum(
        1 for x in snap.transactions
        if x.envelope_id == eid and mulai <= x.transaction_date <= m.today
        and m.jenis_transaksi.get(x.id) == "variabel"
    )


def variabel_harian_amplop(snap: Snapshot, m: Metrics, eid: str, hari: int = 7) -> list[tuple[date, Decimal]]:
    """Belanja variabel amplop per hari, `hari` hari terakhir s/d t (dalam periode berjalan). AMP-10."""
    mulai = max(m.today - timedelta(days=hari - 1), m.period_start)
    per = defaultdict(lambda: ZERO)
    for x in snap.transactions:
        if x.envelope_id == eid and mulai <= x.transaction_date <= m.today \
                and m.jenis_transaksi.get(x.id) == "variabel":
            per[x.transaction_date] += x.amount
    out, day = [], mulai
    while day <= m.today:
        out.append((day, per.get(day, ZERO)))
        day += timedelta(days=1)
    return out


def saving_rate_riwayat(snap: Snapshot, m: Metrics, k: Konstanta = DEFAULT) -> list[Decimal]:
    """P6 per periode lalu (≤ 3 terakhir yang punya pemasukan viewer), rumus sama dengan P6. INC-05."""
    tabungan = {e.id for e in snap.envelopes if e.purpose in SAVING_PURPOSES}
    past = m.periode[:-1]
    p1 = [ZERO] * len(past)
    ke_tabungan = [ZERO] * len(past)
    idx_income = {}
    for i in snap.incomes:
        if i.amount > 0 and not i.is_adjustment and i.user_id == snap.viewer_id:
            idx = _period_index(i.income_date, past)
            if idx is not None:
                p1[idx] += i.amount
                idx_income[i.id] = idx
    for a in snap.allocations:
        idx = idx_income.get(a.income_id)
        if idx is not None and a.envelope_id in tabungan:
            ke_tabungan[idx] += a.amount
    return [ke_tabungan[i] / p1[i] for i in range(len(past)) if p1[i] > 0][-k.periode_riwayat:]


# ── tambahan S9: simulasi "aman beli?" (02-aturan.md §6H SIM-01) ──
SIMULASI_TXN_ID = "sim:aman-beli"


def simulasi_belanja(snap: Snapshot, eid: str, jumlah, k: Konstanta = DEFAULT) -> Metrics:
    """Metrik seolah `jumlah` dicatat hari ini di amplop `eid` — rumus sama persis dengan
    `compute_metrics` (T3, J1, T10 dihitung ulang, bukan dikurangi dengan tangan).
    Snapshot asli tidak diubah.

    Catatan: bila nominal sama persis dengan tagihan amplop itu yang belum dibayar, transaksi
    simulasi dianggap melunasi tagihan (aturan nominal persis M4) dan T3 tidak turun — sama
    dengan yang terjadi bila belanja itu sungguh dicatat."""
    from dataclasses import replace
    from app.services.advisor.snapshot import TransactionSnap
    txn = TransactionSnap(id=SIMULASI_TXN_ID, envelope_id=eid, user_id=snap.viewer_id,
                          amount=_to_decimal(jumlah), transaction_date=snap.today,
                          description="simulasi", created_at=snap.now)
    return compute_metrics(replace(snap, transactions=[*snap.transactions, txn]), k)
