"""Perencana dana AI Advisor v2 (02-aturan.md §8) — fungsi murni, tanpa DB.

`susun_rencana(snapshot, metrics, kebutuhan, kecuali, sertakan) -> Rencana` dipakai
semua CTA "Geser", "Geser & bayar", "Tutup minus", dan "Pindahkan ke tabungan"
(`POST /advisor/plan`), dan dihitung ulang di dalam kunci household oleh
`POST /advisor/execute` (execute.py). Angka surplus berasal dari metrics.py
(`surplus_rencana`); modul ini hanya memilih, mengurutkan, dan membagi.

Langkah (§8):
1. Kebutuhan diurutkan: tagihan telat/jatuh tempo → amplop minus → amplop habis
   yang punya tagihan → lainnya (stabil).
2. Sumber sah: amplop belanja yang boleh diubah viewer (bersama / pribadi miliknya),
   tidak terkunci, bukan tujuan mana pun, tanpa tagihan tersisa (M4 = 0), surplus > 0.
3. Tingkat: (a) keinginan, (b) kebutuhan dengan riwayat (surplus memakai median
   belanja sisa periode 3 periode lalu bila lebih besar), (c) kebutuhan tanpa
   riwayat — hanya bila (a)+(b) tidak cukup. (d) tabungan umum dan (e) dana
   darurat TIDAK PERNAH otomatis: hanya bila user memilihnya (`sertakan`).
   Dalam satu tingkat, surplus terbesar dulu.
4. Alokasi global: satu sumber boleh dipakai beberapa kebutuhan sampai surplusnya habis.
5. Pembulatan: tiap ambilan dibulatkan ke bawah ke Rp1.000; ambilan yang menutup
   kebutuhan memakai sisanya persis.
7. Centang: (a)(b)(d)(e) tercentang. (c) tercentang hanya bila dipakai kebutuhan
   ber-tone danger (tagihan telat, amplop minus).
8. bebas_setelah_rencana(e) = bebas(e) − dana yang direncanakan keluar dari e.

Keputusan kecil S5 (dicatat juga di SESI-LOG.md):
- Satu baris rencana per sumber (`dari_id` unik, frontend menyalakan/mematikan per
  sumber); rinciannya per tujuan di `ke`.
- Sumber (c) tetap "memakan" surplus walau tidak tercentang, supaya baris itu sah
  bila user mencentangnya; `kurang` hanya menghitung baris tercentang.
- Baris (c) yang dipakai kebutuhan danger dan non-danger sekaligus: tercentang.
- `bayar` hanya diisi bila kebutuhan pemiliknya tertutup penuh oleh baris
  tercentang; selain itu user diarahkan ke Catat pemasukan / Bayar saja.
- Teks `alasan` sementara dirakit di sini (`ALASAN`); pindahkan ke render.py saat S3 ada.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.services.advisor.formatting import _fmt_rp, _to_decimal
from app.services.advisor.metrics import (
    BELANJA_PURPOSES, SAVING_PURPOSES, Metrics, batas_harian, belanja_sisa_riwayat, rupiah,
    surplus_rencana,
)
from app.services.advisor.snapshot import Snapshot

ZERO = Decimal("0")
SERIBU = Decimal("1000")
MAX_KEBUTUHAN = 10

URUTAN_TINGKAT = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}

# TODO(S3): pindahkan ke render.py (aturan kerja #2).
ALASAN = {
    "a": "Amplop keinginan, masih lebih Rp{surplus} sampai akhir periode",
    "b": "Kebutuhan, masih lebih Rp{surplus} menurut belanja periode lalu",
    "c": "Cek dulu: belum ada riwayat belanja, perkiraan lebih Rp{surplus}",
    "d": "Tabungan, dipakai karena kamu memilihnya",
    "e": "Dana darurat, dipakai karena kamu memilihnya",
}


class PlanInputError(ValueError):
    """Kebutuhan tidak sah (400)."""


def floor1000(value: Decimal) -> Decimal:
    return (value / SERIBU).to_integral_value(rounding=ROUND_FLOOR) * SERIBU


def _rp_int(value) -> Decimal:
    return _to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass
class Kebutuhan:
    tujuan_id: str
    jumlah: Decimal
    bayar_recurring_id: str | None = None
    prioritas: int = 3
    danger: bool = False


@dataclass
class Sumber:
    id: str
    nama: str
    tingkat: str
    surplus: Decimal               # kapasitas awal (sebelum dipakai)
    sisa_kapasitas: Decimal


@dataclass
class Baris:
    dari_id: str
    dari_nama: str
    tingkat: str
    surplus: Decimal
    ke: dict = field(default_factory=dict)   # tujuan_id → jumlah
    danger: bool = False                      # dipakai kebutuhan danger

    @property
    def jumlah(self) -> Decimal:
        return sum(self.ke.values(), ZERO)

    @property
    def tercentang(self) -> bool:
        return self.tingkat != "c" or self.danger


@dataclass
class Rencana:
    kebutuhan: list[Kebutuhan]
    baris: list[Baris]
    kurang: Decimal
    bayar: list[dict]                         # [{"recurring_id", "jumlah"}]
    kecuali: list[str]
    sertakan: list[str]
    opsi_tabungan: list[dict]                 # CTA terpisah "Pakai tabungan" (d, e)
    nama: dict[str, str]

    def keluar(self) -> dict[str, Decimal]:
        """Dana tercentang yang direncanakan keluar per amplop sumber."""
        out = defaultdict(lambda: ZERO)
        for b in self.baris:
            if b.tercentang:
                out[b.dari_id] += b.jumlah
        return dict(out)

    def to_api(self, saldo_versi: str) -> dict:
        return {
            "rencana": [
                {
                    "dari_id": b.dari_id, "dari_nama": b.dari_nama, "jumlah": rupiah(b.jumlah),
                    "alasan": ALASAN[b.tingkat].format(surplus=_fmt_rp(b.surplus)),
                    "tingkat": b.tingkat, "tercentang": b.tercentang,
                    "ke": [{"tujuan_id": t, "tujuan_nama": self.nama.get(t, ""), "jumlah": rupiah(j)}
                           for t, j in b.ke.items()],
                }
                for b in self.baris
            ],
            "kurang": rupiah(self.kurang),
            "bayar": [{"recurring_id": x["recurring_id"], "jumlah": rupiah(x["jumlah"])} for x in self.bayar],
            "saldo_versi": saldo_versi,
            "kebutuhan": [
                {"tujuan_id": k.tujuan_id, "jumlah": rupiah(k.jumlah),
                 **({"bayar_recurring_id": k.bayar_recurring_id} if k.bayar_recurring_id else {})}
                for k in self.kebutuhan
            ],
            "kecuali": list(self.kecuali),
            "sertakan": list(self.sertakan),
            "opsi_tabungan": [
                {**o, "saldo": rupiah(o["saldo"])} for o in self.opsi_tabungan
            ],
        }


# ── versi saldo ─────────────────────────────────────────────────────────
def saldo_versi(snap: Snapshot, m: Metrics) -> str:
    """Sidik jari angka yang dipakai rencana: hari ini, sisa/bebas/tagihan tiap amplop
    terlihat, kunci amplop, dan jatuh tempo langganan. Berubah → execute 409."""
    locked = {e.id: e.is_locked for e in snap.envelopes}
    data = {
        "t": m.today.isoformat(),
        "e": sorted(
            [eid, str(rupiah(a.sisa)), str(rupiah(a.bebas)), str(rupiah(a.tagihan_sisa)), locked.get(eid, False)]
            for eid, a in m.amplop.items()
        ),
        "r": sorted([b.recurring_id, b.jatuh_tempo.isoformat(), str(rupiah(b.sisa))] for b in m.tagihan),
    }
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


# ── kebutuhan ───────────────────────────────────────────────────────────
def normalisasi_kebutuhan(snap: Snapshot, m: Metrics, items: list[dict]) -> list[Kebutuhan]:
    """Validasi + prioritas (§8.1). `items` = [{"tujuan_id", "jumlah", "bayar_recurring_id"?}]."""
    if not items:
        raise PlanInputError("Kebutuhan kosong")
    if len(items) > MAX_KEBUTUHAN:
        raise PlanInputError(f"Maksimal {MAX_KEBUTUHAN} kebutuhan")
    bills = {b.recurring_id: b for b in m.tagihan}
    out = []
    for it in items:
        tid = str(it["tujuan_id"])
        if tid not in m.amplop:
            raise PlanInputError("Amplop tidak ditemukan")
        jumlah = _rp_int(it["jumlah"])
        if jumlah <= 0:
            raise PlanInputError("Jumlah harus lebih dari 0")
        rid = it.get("bayar_recurring_id")
        rid = str(rid) if rid else None
        if rid is not None:
            bill = bills.get(rid)
            if bill is None or bill.envelope_id != tid:
                raise PlanInputError("Langganan tidak ditemukan di amplop tujuan")
        e = m.amplop[tid]
        env_bills = [b for b in m.tagihan if b.envelope_id == tid and b.sisa > 0]
        telat = any(b.telat_hari > 0 for b in env_bills)
        jatuh_tempo = rid is not None or any(b.jatuh_tempo <= m.today for b in env_bills)
        minus = e.sisa < 0
        if jatuh_tempo:
            prio = 0
        elif minus:
            prio = 1
        elif e.bebas <= 0 and e.tagihan_sisa > 0:
            prio = 2
        else:
            prio = 3
        out.append(Kebutuhan(tujuan_id=tid, jumlah=jumlah, bayar_recurring_id=rid,
                             prioritas=prio, danger=telat or minus))
    return sorted(out, key=lambda k: k.prioritas)  # sorted() stabil


# ── sumber ──────────────────────────────────────────────────────────────
def kandidat_sumber(snap: Snapshot, m: Metrics, tujuan: set[str], kecuali: set[str]) -> list[Sumber]:
    """Sumber otomatis (a)(b)(c), urut tingkat lalu surplus terbesar (§8.2–8.3)."""
    out = []
    for e in snap.envelopes:
        if e.purpose not in BELANJA_PURPOSES or e.id in tujuan or e.id in kecuali or e.is_locked:
            continue
        if e.owner_id is not None and e.owner_id != snap.viewer_id:
            continue  # amplop pribadi anggota lain tidak pernah dipakai (skenario 7, 10)
        a = m.amplop.get(e.id)
        if a is None or a.tagihan_sisa > 0:
            continue
        if not a.kebutuhan:
            tingkat, riwayat = "a", False
        else:
            riwayat = belanja_sisa_riwayat(snap, m, e.id) is not None
            tingkat = "b" if riwayat else "c"
        surplus = surplus_rencana(snap, m, e.id, pakai_riwayat=riwayat)
        if surplus <= 0:
            continue
        out.append(Sumber(id=e.id, nama=e.name, tingkat=tingkat, surplus=surplus, sisa_kapasitas=surplus))
    out.sort(key=lambda s: (URUTAN_TINGKAT[s.tingkat], -s.surplus, s.id))
    return out


def sumber_tabungan(snap: Snapshot, m: Metrics, tujuan: set[str], kecuali: set[str]) -> list[Sumber]:
    """Tabungan (d) lalu dana darurat (e) yang bisa dipakai bila user memilihnya. Kapasitas =
    sisa amplop (aturan transfer biasa: jumlah ≤ sisa sumber)."""
    out = []
    for e in snap.envelopes:
        if e.purpose not in SAVING_PURPOSES or e.id in tujuan or e.id in kecuali or e.is_locked:
            continue
        if e.owner_id is not None and e.owner_id != snap.viewer_id:
            continue
        a = m.amplop.get(e.id)
        if a is None or a.sisa <= 0:
            continue
        out.append(Sumber(id=e.id, nama=e.name, tingkat="e" if e.is_emergency else "d",
                          surplus=a.sisa, sisa_kapasitas=a.sisa))
    out.sort(key=lambda s: (URUTAN_TINGKAT[s.tingkat], -s.surplus, s.id))
    return out


# ── utama ───────────────────────────────────────────────────────────────
def susun_rencana(snap: Snapshot, m: Metrics, kebutuhan: list[dict],
                  kecuali: list[str] | None = None, sertakan: list[str] | None = None) -> Rencana:
    keb = normalisasi_kebutuhan(snap, m, kebutuhan)
    kecuali_set = {str(x) for x in (kecuali or [])}
    tujuan = {k.tujuan_id for k in keb}
    otomatis = kandidat_sumber(snap, m, tujuan, kecuali_set)
    tabungan = sumber_tabungan(snap, m, tujuan, kecuali_set)
    sertakan_set = {str(x) for x in (sertakan or [])}
    dipilih = [s for s in tabungan if s.id in sertakan_set]   # d/e hanya atas pilihan user

    baris: dict[str, Baris] = {}
    tertutup: dict[int, Decimal] = {}

    def ambil(k: Kebutuhan, s: Sumber, kurang: Decimal) -> Decimal:
        if kurang <= 0 or s.sisa_kapasitas <= 0:
            return ZERO
        take = kurang if s.sisa_kapasitas >= kurang else floor1000(s.sisa_kapasitas)
        if take <= 0:
            return ZERO
        s.sisa_kapasitas -= take
        b = baris.get(s.id)
        if b is None:
            b = baris[s.id] = Baris(dari_id=s.id, dari_nama=s.nama, tingkat=s.tingkat, surplus=s.surplus)
        b.ke[k.tujuan_id] = b.ke.get(k.tujuan_id, ZERO) + take
        if k.danger:
            b.danger = True
        return take

    for idx, k in enumerate(keb):
        kurang = k.jumlah
        tercentang = ZERO
        for tier_set in (("a", "b"), ("c",)):
            for s in otomatis:
                if s.tingkat in tier_set:
                    t = ambil(k, s, kurang)
                    kurang -= t
                    if s.tingkat != "c" or k.danger:
                        tercentang += t
        for s in dipilih:
            t = ambil(k, s, kurang)
            kurang -= t
            tercentang += t
        tertutup[idx] = tercentang

    rows = sorted(baris.values(), key=lambda b: (URUTAN_TINGKAT[b.tingkat], -b.jumlah, b.dari_id))
    total = sum((k.jumlah for k in keb), ZERO)
    dicentang = sum((b.jumlah for b in rows if b.tercentang), ZERO)
    kurang_total = max(total - dicentang, ZERO)

    bills = {b.recurring_id: b for b in m.tagihan}
    bayar = []
    for idx, k in enumerate(keb):
        if k.bayar_recurring_id and tertutup[idx] >= k.jumlah:
            bayar.append({"recurring_id": k.bayar_recurring_id, "jumlah": bills[k.bayar_recurring_id].nominal})

    opsi = [] if kurang_total <= 0 else [
        {"amplop_id": s.id, "nama": s.nama, "saldo": s.surplus, "darurat": s.tingkat == "e"}
        for s in tabungan if s.id not in sertakan_set
    ]
    nama = {e.id: e.name for e in snap.envelopes}
    return Rencana(kebutuhan=keb, baris=rows, kurang=kurang_total, bayar=bayar,
                   kecuali=sorted(kecuali_set), sertakan=sorted(sertakan_set & {s.id for s in tabungan}),
                   opsi_tabungan=opsi, nama=nama)


def bebas_setelah_rencana(m: Metrics, rencana: Rencana | None) -> dict[str, Decimal]:
    """bebas(e) − dana tercentang yang direncanakan keluar dari e (§8.8, penekanan 8)."""
    keluar = rencana.keluar() if rencana else {}
    return {eid: a.bebas - keluar.get(eid, ZERO) for eid, a in m.amplop.items()}


def batas_harian_setelah_rencana(m: Metrics, rencana: Rencana | None) -> dict[str, Decimal]:
    """Angka "maksimal/hari" tiap amplop yang menghormati rencana dana (skenario 18)."""
    return {eid: batas_harian(v, m) for eid, v in bebas_setelah_rencana(m, rencana).items()}
