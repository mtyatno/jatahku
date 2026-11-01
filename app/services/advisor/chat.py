"""Jawaban bot (Telegram & chat web) dan ringkasan harian/mingguan dari mesin AI Advisor v2 (S9).

02-aturan.md §6H (CHAT, SIM-01), §7 "Chat web & Telegram", §13 Paritas, §14 "Bot dan
ringkasan memanggil metrics dan render langsung, bukan lewat HTTP".

Alur sama dengan `GET /advisor/dashboard`: snapshot → metrik → sinyal → aturan → seleksi
(`dashboard.analisa`), lalu teks dari `render.py`. Karena itu angka `/status`, "sisa", ringkasan
harian, dan KPI Beranda selalu identik (dari `Metrics` yang sama), dan "kenapa …" menampilkan
fakta insight yang sama dengan Rincian di web.

Modul ini hanya MEMILIH (intent → insight/angka mana) — tanpa rumus periode (metrics.py) dan
tanpa kalimat (render.py). `muat` mengurus DB/flag/dismiss; fungsi `jawab_*` murni.

Flag `advisor_v2_users` (03-workflow.md §5): `muat` mengembalikan None untuk user di luar
daftar → bot memakai jawaban lama sampai flag `*` (S10).

Keputusan kecil S9:
- "kenapa boros?" = PER-01 › PER-02 › HAR-01 › PER-03 › PER-04 › PER-05 › PER-07, insight
  pertama yang menyala (walau di-dismiss: user bertanya langsung), dengan fakta + Rincian.
- "kenapa {amplop} habis?" = insight amplop itu (AMP-01/02/03, TAG-01/02 yang menyerapnya,
  AMP-04/08/10/05) urut tone lalu skor, termasuk yang diserap PER-01; tidak ada → angka amplop.
- "kenapa … hari ini …" = HAR-01 › HAR-03 › HAR-02 › HAR-04 › HAR-05.
- SIM-01: amplop dari `find_best_envelope` (pemanggil); tidak yakin → amplop belanja dengan
  porsi 7 hari (M12) terbesar, ditandai "ditebak". Pilihan ganti amplop lewat tombol: S17.
  Di hari terakhir (J1 tidak ada) pembanding "aman/hari" memakai sisa bebas total.

Keputusan kecil S17 (§6H, intent lengkap):
- "tagihan bulan ini" = tagihan periode berjalan dari `m.tagihan` (jatuh tempo di periode,
  telat, atau sudah lunas) + M4/M5/K4 + chip Tagihan + insight TAG pertama yang menyala
  (TAG-01 › TAG-02 › TAG-04 › TAG-03, walau di-dismiss: user bertanya langsung).
- "target {nama}" = satu target (nama target, lalu nama amplop tabungannya) dengan G4/G5/G6
  + insight TAB target itu; tanpa nama → semua target (maks `TARGET_MAKS`) + chip Tabungan.
- SIM-01 "ganti amplop": `pilihan_amplop` = amplop belanja terlihat (urut porsi 7 hari), tombol
  dipasang bot (`advisor_cmd`); pilihan memanggil `jawab_aman_beli` dengan amplop itu.
- Chat tidak menawarkan tombol sembunyikan/munculkan lagi (cek #91): dismiss tetap hanya
  lewat `POST`/`DELETE /advisor/dismiss` di web; `muat` membaca dismiss viewer terbaru.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.services.advisor import render
from app.services.advisor.insight import Konteks, kunci_urut
from app.services.advisor.metrics import (
    DEFAULT as KM_DEFAULT, Konstanta, simulasi_belanja, variabel_hari_ini_per_amplop,
)
from app.services.advisor.select import Seleksi

ZERO = Decimal("0")

KENAPA_BOROS = ("PER-01", "PER-02", "HAR-01", "PER-03", "PER-04", "PER-05", "PER-07")
KENAPA_HARI_INI = ("HAR-01", "HAR-03", "HAR-02", "HAR-04", "HAR-05")
KENAPA_AMPLOP = {"AMP-01", "AMP-02", "AMP-03", "TAG-01", "TAG-02", "AMP-04", "AMP-08", "AMP-10", "AMP-05"}
STRUKTURAL = {"AMP-04", "AMP-05", "AMP-06", "TAB-02"}   # ringkasan mingguan (§7)
SIM_AMAN_RASIO = Decimal("0.9")                          # SIM-01: J1 baru ≥ 90% J1
TRANSAKSI_TERAKHIR = 5
TAGIHAN_UTAMA = ("TAG-01", "TAG-02", "TAG-04", "TAG-03")
TARGET_MAKS = 5
PILIHAN_AMPLOP_MAKS = 6

_HARI_INI_RE = re.compile(r"\bhari\s+ini\b", re.IGNORECASE)
_KATA_RE = re.compile(r"[a-z0-9]+")
# Frasa umum yang bukan nama amplop (chip "Tanya" web: "Kenapa dana belanja kurang?",
# "Kenapa belanja hari ini lewat jatah?"), supaya amplop bernama "Belanja" tidak tertangkap.
_FRASA_UMUM_RE = re.compile(r"\bdana\s+belanja\b|\bbelanja\s+(hari\s+ini|harian)\b", re.IGNORECASE)
_KATA_UMUM = {"kenapa", "habis", "kurang", "boros", "lewat", "jatah", "dana", "uang", "duit", "hari", "minus",
              "belanja", "bulan", "periode", "cepat", "cepet"}


@dataclass
class Analisa:
    ctx: Konteks
    sel: Seleksi
    km: Konstanta = KM_DEFAULT


def analisa_snapshot(snap, *, now_local: datetime, dismiss: dict | None = None, km=None, ks=None,
                     ka=None) -> Analisa:
    from app.services.advisor.dashboard import analisa
    kw = {k: v for k, v in (("km", km), ("ks", ks), ("ka", ka)) if v is not None}
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, **kw)
    return Analisa(ctx=ctx, sel=sel, km=km or KM_DEFAULT)


# ── pembantu ────────────────────────────────────────────────────────────
def _r(a: Analisa, ins, kpi: str | None = None) -> dict | None:
    return render.render_insight(ins, a.ctx, kpi=kpi) if ins is not None else None


def kpi(a: Analisa, kartu: str) -> dict | None:
    return _r(a, a.sel.kpi.get(kartu), kpi=kartu)


def utama(a: Analisa) -> dict | None:
    """Item #1 kartu AI Advisor; kosong → satu kabar baik (§7)."""
    if a.sel.daftar:
        return _r(a, a.sel.daftar[0])
    return _r(a, a.sel.aman)


def _pertama(a: Analisa, urutan) -> object | None:
    for aturan in urutan:
        calon = [i for i in a.sel.semua if i.aturan == aturan]
        if calon:
            return min(calon, key=kunci_urut)
    return None


def _kata(teks: str) -> list[str]:
    return _KATA_RE.findall((teks or "").lower())


def cari_amplop(teks: str, ctx: Konteks) -> str | None:
    """Amplop terlihat yang disebut di teks: nama utuh dulu (terpanjang), lalu kata nama
    ≥ 4 huruf yang bukan kata umum ("kenapa makan habis" → "Makan & Jajan")."""
    kata = _kata(_FRASA_UMUM_RE.sub(" ", teks or ""))
    gabung = " " + " ".join(kata) + " "
    utuh, sebagian = [], []
    for eid, a in ctx.m.amplop.items():
        nama = _kata(a.nama)
        if not nama:
            continue
        if " " + " ".join(nama) + " " in gabung:
            utuh.append((len(" ".join(nama)), eid))
        else:
            cocok = [w for w in nama if len(w) >= 4 and w not in _KATA_UMUM and w in kata]
            if cocok:
                sebagian.append((max(len(w) for w in cocok), eid))
    for kandidat in (utuh, sebagian):
        if kandidat:
            return max(kandidat, key=lambda x: (x[0], x[1]))[1]
    return None


# ── jawaban (murni) ─────────────────────────────────────────────────────
def jawab_status(a: Analisa) -> str:
    """/status: angka KPI + amplop + chip Jatah hari ini + item #1 daftar."""
    return render.chat_status(a.ctx, "📊 Budget", kpi(a, "jatah"), utama(a))


def jawab_sisa(a: Analisa) -> str:
    """"sisa": angka KPI + amplop + chip Sisa bebas."""
    return render.chat_status(a.ctx, "💰 Sisa amplop", kpi(a, "sisa_bebas"), None)


def jawab_limit_harian(a: Analisa) -> str:
    return render.chat_limit_harian(a.ctx, kpi(a, "jatah"))


def jawab_proyeksi(a: Analisa) -> str:
    return render.chat_proyeksi(a.ctx, kpi(a, "sisa_bebas"))


def transaksi_hari_ini(a: Analisa, n: int = TRANSAKSI_TERAKHIR) -> list:
    """n transaksi terakhir hari ini di amplop terlihat (tanpa penyesuaian cocokkan saldo)."""
    ctx = a.ctx
    hari_ini = [x for x in ctx.snap.transactions
                if x.transaction_date == ctx.m.today and x.envelope_id in ctx.m.amplop
                and not x.is_adjustment and x.amount > 0]
    hari_ini.sort(key=lambda x: (x.created_at.timestamp() if x.created_at else 0, x.id), reverse=True)
    return hari_ini[:n]


def jawab_hari_ini(a: Analisa) -> str:
    per = variabel_hari_ini_per_amplop(a.ctx.snap, a.ctx.m)
    return render.chat_hari_ini(a.ctx, per, transaksi_hari_ini(a), kpi(a, "jatah"))


def jawab_kenapa_boros(a: Analisa) -> str:
    ins = _pertama(a, KENAPA_BOROS)
    lain = [i for i in a.sel.daftar if ins is None or i.id != ins.id][:2]
    return render.chat_kenapa(_r(a, ins), [_r(a, i) for i in lain])


def jawab_kenapa_hari_ini(a: Analisa) -> str:
    return render.chat_kenapa(_r(a, _pertama(a, KENAPA_HARI_INI)))


def jawab_kenapa_amplop(a: Analisa, eid: str) -> str:
    calon = sorted((i for i in a.sel.semua if i.amplop_id == eid and i.aturan in KENAPA_AMPLOP), key=kunci_urut)
    if not calon:
        return render.chat_amplop_aman(a.ctx, eid)
    return render.chat_kenapa(_r(a, calon[0]), [_r(a, i) for i in calon[1:3]])


def jawab_kenapa(a: Analisa, teks: str) -> str:
    """"kenapa {amplop} habis?", "kenapa belanja hari ini lewat jatah?", "kenapa boros?"."""
    eid = cari_amplop(teks, a.ctx)
    if eid:
        return jawab_kenapa_amplop(a, eid)
    if _HARI_INI_RE.search(teks or ""):
        return jawab_kenapa_hari_ini(a)
    return jawab_kenapa_boros(a)


# ── SIM-01 "aman beli?" ─────────────────────────────────────────────────
def amplop_tebakan(a: Analisa) -> str | None:
    """Amplop belanja dengan belanja 7 hari (M12) terbesar."""
    belanja = [(x.porsi_7h, x.variabel_periode, x.bebas, eid) for eid, x in a.ctx.m.amplop.items()
               if x.kelompok == "belanja"]
    return max(belanja)[3] if belanja else None


def simulasi(a: Analisa, eid: str, jumlah, ditebak: bool = False) -> dict:
    """T3, J1, T10 dihitung ulang seolah `jumlah` dicatat di `eid` (`metrics.simulasi_belanja`)."""
    m = a.ctx.m
    m2 = simulasi_belanja(a.ctx.snap, eid, jumlah, a.km)
    e1, e2 = m.amplop[eid], m2.amplop[eid]
    if e2.bebas < 0 or m2.sisa_bebas < 0:
        hasil = "kurang"
    else:
        acuan = m.j1 if m.j1 is not None else max(m.sisa_bebas, ZERO)
        acuan2 = m2.j1 if m2.j1 is not None else max(m2.sisa_bebas, ZERO)
        hasil = "aman" if acuan2 >= acuan * SIM_AMAN_RASIO else "turun"
    return {
        "hasil": hasil, "amplop_id": eid, "jumlah": Decimal(str(jumlah)), "ditebak": ditebak,
        "bebas": e1.bebas, "bebas_baru": e2.bebas, "t3": m.sisa_bebas, "t3_baru": m2.sisa_bebas,
        "j1": m.j1, "j1_baru": m2.j1,
        "habis": m.tanggal_habis if m.kekurangan else None,
        "habis_baru": m2.tanggal_habis if m2.kekurangan else None,
        "habis_sekarang": m2.sisa_bebas <= 0 < m.sisa_bebas,
    }


def amplop_simulasi(a: Analisa, eid: str | None, ditebak: bool = False) -> tuple[str | None, bool]:
    """Amplop yang disimulasikan: `eid` bila terlihat, selain itu tebakan (M12) → ditebak."""
    if eid is None or eid not in a.ctx.m.amplop:
        return amplop_tebakan(a), True
    return eid, ditebak


def jawab_aman_beli(a: Analisa, eid: str | None, jumlah, ditebak: bool = False) -> str | None:
    """None bila tidak ada amplop belanja yang bisa disimulasikan."""
    eid, ditebak = amplop_simulasi(a, eid, ditebak)
    if eid is None:
        return None
    return render.chat_aman_beli(a.ctx, simulasi(a, eid, jumlah, ditebak))


def pilihan_amplop(a: Analisa, kecuali: str | None = None, n: int = PILIHAN_AMPLOP_MAKS) -> list[tuple[str, str]]:
    """Amplop belanja terlihat untuk tombol "ganti amplop" SIM-01: (id, nama), porsi 7 hari
    terbesar dulu (urutan yang sama dengan `amplop_tebakan`)."""
    belanja = sorted(((x.porsi_7h, x.variabel_periode, x.bebas, eid) for eid, x in a.ctx.m.amplop.items()
                      if x.kelompok == "belanja" and eid != kecuali), reverse=True)
    return [(eid, a.ctx.nama.get(eid, "")) for *_, eid in belanja[:n]]


# ── "tagihan bulan ini" ─────────────────────────────────────────────────
def tagihan_periode(a: Analisa) -> list:
    """Tagihan periode berjalan: jatuh tempo di periode, telat, atau sudah dilunasi."""
    m = a.ctx.m
    rows = [b for b in m.tagihan
            if b.lunas_oleh or b.telat_hari > 0 or m.period_start <= b.jatuh_tempo <= m.period_end]
    return sorted(rows, key=lambda b: (b.jatuh_tempo, b.recurring_id))


def jawab_tagihan(a: Analisa) -> str:
    return render.chat_tagihan(a.ctx, tagihan_periode(a), kpi(a, "tagihan"), _r(a, _pertama(a, TAGIHAN_UTAMA)))


# ── "target {nama}" ─────────────────────────────────────────────────────
def cari_target(teks: str, ctx: Konteks) -> dict | None:
    """Target (G*) yang disebut di teks: nama target, lalu nama amplop tabungannya."""
    kata = _kata(teks)
    gabung = " " + " ".join(kata) + " "
    calon = []
    for g in ctx.m.target:
        for nama in (g["nama"], ctx.nama.get(g["envelope_id"], "")):
            nk = _kata(nama)
            if not nk:
                continue
            if " " + " ".join(nk) + " " in gabung:
                calon.append((2, len(" ".join(nk)), g["goal_id"], g))
            else:
                cocok = [w for w in nk if len(w) >= 4 and w not in _KATA_UMUM | {"target", "tabungan"} and w in kata]
                if cocok:
                    calon.append((1, max(len(w) for w in cocok), g["goal_id"], g))
    return max(calon, key=lambda x: x[:3])[3] if calon else None


def insight_target(a: Analisa, g: dict) -> dict | None:
    """Insight TAB-* untuk satu target (entitas = goal_id; TAB-01 = amplop daruratnya)."""
    calon = [i for i in a.sel.semua if i.aturan.startswith("TAB-")
             and (i.entitas == g["goal_id"] or (i.aturan == "TAB-01" and i.entitas == g["envelope_id"]))]
    return _r(a, min(calon, key=kunci_urut)) if calon else None


def jawab_target(a: Analisa, teks: str = "") -> str:
    g = cari_target(teks, a.ctx)
    if g is not None:
        return render.chat_target(a.ctx, [g], insight_target(a, g), None)
    return render.chat_target(a.ctx, a.ctx.m.target[:TARGET_MAKS], None, kpi(a, "tabungan"),
                              lebih=max(len(a.ctx.m.target) - TARGET_MAKS, 0))


# ── ringkasan ───────────────────────────────────────────────────────────
def ringkasan_harian(a: Analisa) -> str:
    per = variabel_hari_ini_per_amplop(a.ctx.snap, a.ctx.m)
    return render.ringkasan_harian(a.ctx, per, kpi(a, "jatah"), utama(a))


def struktural(a: Analisa) -> dict | None:
    """Satu aturan struktural untuk ringkasan mingguan: AMP-04/05/06 atau TAB-02, yang tidak di-dismiss."""
    calon = [i for i in a.sel.semua if i.aturan in STRUKTURAL and i.id not in a.sel.disembunyikan]
    return _r(a, min(calon, key=kunci_urut)) if calon else None


def ringkasan_mingguan(a: Analisa, minggu: dict) -> str:
    return render.ringkasan_mingguan(a.ctx, minggu, kpi(a, "sisa_bebas"), struktural(a))


# ── DB + flag ───────────────────────────────────────────────────────────
async def muat(user, db, now: datetime | None = None, pengaturan: dict | None = None, *,
               household_id) -> Analisa | None:
    """Analisa viewer `user`, atau None bila flag `advisor_v2_users` tidak memuat user ini
    (atau belum ada amplop) → pemanggil memakai jawaban lama."""
    from app.services.advisor import advisor_cache
    from app.services.advisor.dashboard import FLAG_KEY, KONSTANTA_KEY, _tz, bangun_konstanta, flag_aktif, \
        muat_pengaturan
    from app.services.advisor.snapshot import load_snapshot
    if pengaturan is None:
        pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return None
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    if not snap.household_id or not snap.envelopes:
        return None
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    return analisa_snapshot(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)


# ── lonceng web (S16) ───────────────────────────────────────────────────
def lonceng_harian(a: Analisa) -> tuple[str, str]:
    """Ringkasan harian untuk lonceng web: isi sama dengan `ringkasan_harian` (chip Jatah + item #1)."""
    return render.lonceng_ringkasan_harian(a.ctx.m, kpi(a, "jatah"), utama(a))


def lonceng_mingguan(a: Analisa, minggu: dict) -> tuple[str, str]:
    return render.lonceng_ringkasan_mingguan(a.ctx.m, minggu, struktural(a))
