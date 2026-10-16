"""Skema insight AI Advisor v2 (02-aturan.md §5) — data saja, tanpa teks.

Aturan (`rules/hari.py`, `rules/periode.py`, dan aturan S4) mengembalikan `Insight`:
kode aturan, entitas, tone, slot, variabel template (`data`), aksi tanpa label,
rupiah terdampak, urgensi, dan keyakinan. `select.py` menghitung skor, menjalankan
penekanan, dan memilih isi tiap slot; `render.py` merakit kalimat (AGENTS.md
"AI Advisor v2" #2: teks insight hanya di render.py).

Slot:
- `daftar` — kartu AI Advisor di Beranda (§7 "Kartu AI Advisor");
- `kpi:jatah`, `kpi:sisa_bebas`, `kpi:terpakai`, `kpi:income`, `kpi:tagihan`, `kpi:tabungan` — chip KPI;
- `transaksi` — penanda baris / banner di halaman Transaksi (S13).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")

TONE_URUT = {"danger": 0, "warn": 1, "info": 2, "ok": 3}
KEYAKINAN_K = {"tinggi": Decimal("1"), "sedang": Decimal("0.8"), "rendah": Decimal("0.6")}

# A (§5): 1,0 CTA satu langkah · 0,7 CTA membuka form/halaman · 0,4 tanpa CTA.
AKSI_SATU_LANGKAH = {"plan", "fund", "pay", "mark_paid", "daily_limit", "raise_budget", "delete_txn",
                     "not_duplicate"}
AKSI_FORM = {"income", "make_recurring", "route", "chat", "expense", "envelope", "langganan", "balance"}
AKSI_PEMINDAH_DANA = {"plan", "fund"}

KPI = ("jatah", "sisa_bebas", "terpakai", "income", "tagihan", "tabungan")


@dataclass(frozen=True)
class KonstantaAturan:
    """02-aturan.md §11 untuk aturan & seleksi — nilai default; ditimpa AppSetting `advisor_konstanta`."""
    danger_lewat_jatah: Decimal = Decimal("1.5")      # HAR-01
    mendekati_jatah: Decimal = Decimal("0.8")         # HAR-02 / HAR-04
    penyumbang_struk: Decimal = Decimal("0.4")        # HAR-01: struk ≥ 40% T5
    penyumbang_amplop_cta: Decimal = Decimal("0.5")   # HAR-01: CTA batas harian bila satu amplop ≥ 50% T5
    jam_belum_catat: int = 20                         # HAR-05
    danger_kekurangan: Decimal = Decimal("0.5")       # PER-01: T9 ≥ 50% sisa bebas → danger
    danger_habis_hari: int = 3                        # PER-01: habis ≤ t + 3 → danger
    lebih_cepat_poin: Decimal = Decimal("0.15")       # PER-03
    laju_membaik: Decimal = Decimal("0.85")           # PER-04
    akhir_periode_hari: int = 3                       # PER-06
    akhir_periode_sisa_min: Decimal = Decimal("50000")  # PER-06
    awal_periode_hari: int = 2                        # PER-07
    yakin_tinggi_hari: int = 7                        # keyakinan proyeksi §5
    yakin_tinggi_txn: int = 10
    yakin_sedang_txn: int = 5
    daftar_maks: int = 3                              # §7 kartu AI Advisor
    daftar_per_domain: int = 2
    redam_danger: int = 1                             # §7 peredaman chip
    redam_warn: int = 2
    # §2: CTA "Batas harian" baru dirilis setelah Pikir-Pikir Fase 1 menjadikan limit harian
    # peringatan. Sampai itu angka "maksimal/hari" tetap tampil sebagai fakta, tanpa tombol.
    cta_batas_harian: bool = False


DEFAULT = KonstantaAturan()


@dataclass
class Insight:
    aturan: str                    # "PER-01"
    entitas: str                   # bagian id sesudah ":" (stabil, dipakai dismiss)
    tone: str                      # danger | warn | info | ok
    slot: tuple[str, ...]
    data: dict = field(default_factory=dict)       # variabel template untuk render.py
    aksi: list[dict] = field(default_factory=list)  # [{"kind", "kode", "payload"}]; label dari render.py
    rupiah: Decimal = ZERO         # rupiah_terdampak (§5 tabel)
    urgensi: Decimal = Decimal("0.2")
    keyakinan: str = "tinggi"      # tinggi | sedang | rendah
    dasar_hari: int | None = None  # "Dari {n} hari data"
    amplop_id: str | None = None   # batas "1 per amplop" di daftar
    rincian: list["Insight"] = field(default_factory=list)  # insight lain yang diserap (penekanan)
    skor: Decimal = ZERO

    @property
    def id(self) -> str:
        return f"{self.aturan}:{self.entitas}"

    @property
    def domain(self) -> str:
        return self.aturan.split("-")[0]

    def di_slot(self, slot: str) -> bool:
        return slot in self.slot

    def punya_aksi(self) -> bool:
        return bool(self.aksi)


def nilai_aksi(aksi: list[dict]) -> Decimal:
    if any(a["kind"] in AKSI_SATU_LANGKAH for a in aksi):
        return Decimal("1")
    if aksi:
        return Decimal("0.7")
    return Decimal("0.4")


def keyakinan_proyeksi(hari_ke: int, n_txn: int, k: KonstantaAturan = DEFAULT) -> str:
    """§5 Keyakinan proyeksi periode berjalan."""
    if hari_ke >= k.yakin_tinggi_hari and n_txn >= k.yakin_tinggi_txn:
        return "tinggi"
    if hari_ke >= 3 and n_txn >= k.yakin_sedang_txn:
        return "sedang"
    return "rendah"


def terapkan_keyakinan(ins: Insight) -> Insight:
    """§5 Efek keyakinan rendah: tone maksimal warn, tanpa CTA pemindah dana
    (kata "kemungkinan" dipasang render.py)."""
    if ins.keyakinan == "rendah":
        if ins.tone == "danger":
            ins.tone = "warn"
        ins.aksi = [a for a in ins.aksi if a["kind"] not in AKSI_PEMINDAH_DANA]
    return ins


def hitung_skor(ins: Insight, dana_belanja: Decimal) -> Decimal:
    """skor = 100 × K × (0,45 U + 0,35 I + 0,20 A), I = min(1, rupiah ÷ 10% dana belanja)."""
    batas = dana_belanja * Decimal("0.1")
    if batas > 0:
        dampak = min(Decimal("1"), max(ins.rupiah, ZERO) / batas)
    else:
        dampak = Decimal("1") if ins.rupiah > 0 else ZERO
    k = KEYAKINAN_K.get(ins.keyakinan, Decimal("1"))
    return 100 * k * (Decimal("0.45") * ins.urgensi + Decimal("0.35") * dampak
                      + Decimal("0.2") * nilai_aksi(ins.aksi))


def kunci_urut(ins: Insight) -> tuple:
    """Kelompok tone dulu, skor di dalamnya; seri: rupiah terdampak, lalu id (§5)."""
    return (TONE_URUT.get(ins.tone, 9), -ins.skor, -ins.rupiah, ins.id)


@dataclass
class Konteks:
    """Masukan aturan: snapshot (nama, kelompok amplop), metrik, sinyal, jam lokal user.
    Aturan tetap fungsi murni — tidak ada DB atau jam sistem di dalamnya."""
    snap: object                   # Snapshot
    m: object                      # Metrics
    s: object                      # Signals
    jam: int = 12                  # jam lokal user 0–23 (HAR-05)
    k: KonstantaAturan = DEFAULT
    batas: dict = field(default_factory=dict)   # amplop → maksimal/hari setelah rencana (select.py)

    @property
    def nama(self) -> dict:
        return {eid: a.nama for eid, a in self.m.amplop.items()}
