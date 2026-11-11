"""Registry kartu Beranda (Plugin B1, docs/plugin/01-kajian.md "Tiga konsep inti", ADR-P8).

Definisi kartu hidup di kode. Satu definisi = satu `key` (mis. `core.kpi.jatah`) dengan judul,
ukuran yang didukung, sumber data, dan validator pengaturan. Penyedia data didaftarkan dengan
key yang sama di `providers.py`. Kartu plugin (titik `cards`, H2) tidak masuk `REGISTRY`: definisinya
dibuat per ruang dan per user dari manifest plugin yang aktif (`app/plugins/host/titik.kartu_ruang`) dan
diteruskan sebagai `plugin=` ke `get`, tata letak, dan batch.

Teks yang tampil ke user (judul, deskripsi) dirakit di sini, satu tempat, supaya web, aplikasi,
dan permukaan lain memakai kalimat yang sama (AGENTS.md "Plugin dan ruang" aturan 7).

Peran (R6): setiap kartu menyatakan `untuk`. Kartu `umum` (semua kartu inti) untuk semua peran kecuali
karyawan ruang usaha; kartu `karyawan` hanya untuk karyawan (peran `member` di ruang usaha). Server yang
menyaring katalog, template, tata letak, dan data (`boleh`); frontend hanya menggambar yang dikirim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

SIZES = ("S", "M", "L", "XL")
DEVICES = ("all", "wide", "narrow")
SHAPES = ("kpi", "progress", "list", "table", "series", "alert", "inti")
SURFACES = ("beranda",)
UNTUK = ("umum", "karyawan")
SCHEMA_VERSION = 1
MAX_ITEMS = 40
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class PengaturanTidakSah(ValueError):
    """Pengaturan instans tidak cocok dengan skema kartu; pesannya siap tampil."""


def _tanpa_pengaturan(settings: dict) -> dict:
    if settings:
        raise PengaturanTidakSah("Kartu ini tidak punya pengaturan.")
    return {}


def _pengaturan_transaksi(settings: dict) -> dict:
    asing = set(settings) - {"limit"}
    if asing:
        raise PengaturanTidakSah(f"Pengaturan tidak dikenal: {', '.join(sorted(asing))}.")
    limit = settings.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise PengaturanTidakSah("Jumlah baris harus 1–50.")
    return {"limit": limit}


@dataclass(frozen=True)
class CardDef:
    key: str
    judul: str
    deskripsi: str
    size_bawaan: str
    sizes: tuple[str, ...]
    shape: str
    supports_period: bool
    asal: str = "inti"                  # inti | <plugin_id>
    multi_instance: bool = False
    refresh_on: tuple[str, ...] = ()
    validasi: Callable[[dict], dict] = field(default=_tanpa_pengaturan, compare=False)
    untuk: str = "umum"                 # umum | karyawan (R6)
    sumber: str | None = None           # U4: nama Fitur Tambahan asal kartu (penanda sumber); None untuk kartu inti

    def __post_init__(self):
        if self.untuk not in UNTUK:
            raise ValueError(f"{self.key}: untuk={self.untuk!r} bukan salah satu {UNTUK}")

    def katalog(self) -> dict:
        """Satu baris `GET /dashboard/cards` (04-kontrak-api.md §4)."""
        return {
            "key": self.key, "judul": self.judul, "deskripsi": self.deskripsi, "asal": self.asal,
            "sizes": list(self.sizes), "size_bawaan": self.size_bawaan, "shape": self.shape,
            "supports_period": self.supports_period, "multi_instance": self.multi_instance,
            "refresh_on": list(self.refresh_on), "hak": "ok", "baru": False, "sumber": self.sumber,
        }


TXN = ("jatahku:txn-added",)
TXN_ENV = ("jatahku:txn-added", "jatahku:envelope-updated")
ADV = ("jatahku:txn-added", "jatahku:envelope-updated", "jatahku:advisor-dismissed",
       "jatahku:advisor-undismissed")

# Urutan = urutan Beranda sekarang (01-kajian.md, "Kartu bawaan yang menjadi isi galeri").
CORE: tuple[CardDef, ...] = (
    CardDef("core.kpi.jatah", "Jatah hari ini", "Belanja hari ini dibanding jatah aman per hari.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.kpi.sisa_bebas", "Sisa bebas", "Dana harian yang masih bebas dipakai sampai akhir periode.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.kpi.terpakai", "Terpakai periode ini", "Belanja periode ini dibanding dana amplop belanja.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.kpi.income", "Income periode ini", "Pemasukan rumah tangga periode ini.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.kpi.tagihan", "Tagihan belum dibayar", "Tagihan bulanan periode ini yang belum dibayar.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.kpi.tabungan", "Tabungan", "Saldo amplop tabungan dan sinking fund beserta targetnya.",
            "S", ("S", "M"), "kpi", True, refresh_on=ADV),
    CardDef("core.cocokkan_saldo", "Cocokkan saldo", "Kapan saldo terakhir dicocokkan dengan uang sungguhan.",
            "S", ("S",), "inti", False, refresh_on=TXN),
    CardDef("core.pengeluaran_harian", "Pengeluaran harian", "Belanja per hari di periode ini.",
            "L", ("L", "XL"), "series", True, refresh_on=ADV),
    CardDef("core.advisor", "AI Advisor", "Saran dari AI Advisor untuk periode berjalan.",
            "S", ("S", "M"), "inti", False, refresh_on=ADV),
    CardDef("core.ke_mana_uangmu", "Ke mana uangmu", "Belanja periode ini per amplop.",
            "XL", ("XL", "L"), "inti", True, refresh_on=TXN),
    CardDef("core.amplop_pengeluaran", "Amplop pengeluaran", "Saldo dan pemakaian amplop belanja.",
            "L", ("L", "XL"), "inti", True, refresh_on=TXN_ENV),
    CardDef("core.target_tabungan", "Target tabungan", "Kemajuan amplop tabungan menuju targetnya.",
            "S", ("S", "M"), "progress", True, refresh_on=TXN_ENV),
    CardDef("core.transaksi_terbaru", "Transaksi terbaru", "Catatan terakhir di periode ini.",
            "L", ("L", "M", "XL"), "list", True, refresh_on=TXN, validasi=_pengaturan_transaksi),
    CardDef("core.langganan", "Langganan", "Tagihan dan langganan rutin.",
            "S", ("S", "M"), "list", False, refresh_on=TXN),
    CardDef("core.papan_disiplin", "Papan disiplin", "Streak mencatat anggota rumah tangga.",
            "S", ("S", "M"), "list", False, refresh_on=TXN),
)

DRAF = ("jatahku:txn-added", "jatahku:draf-baru")

# Kartu karyawan (R6, 05-desain-buku-usaha.md B4.3, artboard "Karyawan: Beranda di ruang usaha"). Hanya data
# milik karyawan itu sendiri dan batasan dari admin: tanpa laba, kas, omzet, atau saldo amplop (ADR-P3, P4).
KARYAWAN: tuple[CardDef, ...] = (
    CardDef("core.karyawan.catat", "Catat", "Catat pengeluaran atau penjualan di ruang ini.",
            "M", ("M", "L"), "inti", False, untuk="karyawan"),
    CardDef("core.karyawan.hari_ini", "Hari ini", "Jumlah pengeluaran dan penjualan yang kamu catat hari ini.",
            "M", ("M", "L"), "inti", False, refresh_on=TXN, untuk="karyawan"),
    CardDef("core.karyawan.menunggu", "Menunggu persetujuan",
            "Catatanmu di atas batas nominal yang menunggu admin, dan keputusan 14 hari terakhir.",
            "M", ("M", "L"), "list", False, refresh_on=DRAF, untuk="karyawan"),
    CardDef("core.karyawan.catatan_hari_ini", "Catatanku hari ini", "Catatan yang kamu buat hari ini di ruang ini.",
            "M", ("M", "L"), "list", False, refresh_on=TXN, untuk="karyawan"),
    CardDef("core.karyawan.batasan", "Batasan dari admin", "Jenis catatan, amplop, dan batas yang diatur admin.",
            "M", ("M", "L"), "inti", False, untuk="karyawan"),
    CardDef("core.karyawan.ruang_terpisah", "Ruang keluargamu terpisah",
            "Pengingat bahwa catatan pribadi tetap di ruang keluargamu.",
            "M", ("M", "L", "XL"), "alert", False, untuk="karyawan"),
)

REGISTRY: dict[str, CardDef] = {c.key: c for c in CORE + KARYAWAN}


def _template(keys: tuple[str, ...]) -> tuple[dict, ...]:
    return tuple(
        {"id": f"a{i}", "card": key, "size": REGISTRY[key].size_bawaan, "hidden": False, "devices": "all"}
        for i, key in enumerate(keys, start=1)
    )


# Template Beranda ruang keluarga = Beranda sekarang. `devices` mengikuti tampilan sekarang:
# Papan disiplin hanya di katalog (sekarang tampil di sidebar dan header HP, bukan kartu grid).
TEMPLATE_BERANDA: tuple[dict, ...] = _template((
    "core.kpi.jatah", "core.kpi.sisa_bebas", "core.kpi.terpakai", "core.kpi.income",
    "core.kpi.tagihan", "core.kpi.tabungan", "core.cocokkan_saldo", "core.pengeluaran_harian",
    "core.advisor", "core.ke_mana_uangmu", "core.amplop_pengeluaran", "core.target_tabungan",
    "core.transaksi_terbaru", "core.langganan",
))

# Template "Karyawan" (R6): Beranda karyawan di ruang usaha. Urutan = urutan baca di HP.
TEMPLATE_KARYAWAN: tuple[dict, ...] = _template(tuple(c.key for c in KARYAWAN))


def get(key: str, plugin: dict[str, CardDef] | None = None) -> CardDef | None:
    """Definisi kartu inti, atau kartu plugin yang aktif di ruang ini (`plugin` = `titik.kartu_ruang`, H2)."""
    return REGISTRY.get(key) or (plugin or {}).get(key)


def boleh(definisi: CardDef | None, karyawan: bool) -> bool:
    """Kartu ini boleh untuk peran ini: kartu karyawan hanya untuk karyawan, kartu umum untuk selain karyawan."""
    return definisi is not None and (definisi.untuk == "karyawan") == bool(karyawan)


# `karyawan` tanpa nilai bawaan (review keamanan PR #185 temuan 2): pemanggil yang lupa menyebut peran gagal keras,
# bukan diam-diam mendapat kartu umum.
def katalog(karyawan: bool, plugin: dict | None = None) -> list[dict]:
    """`GET /dashboard/cards`: kartu inti untuk peran ini, lalu kartu plugin yang aktif di ruang ini (H3, `plugin` =
    `titik.kartu_ruang`). Kartu plugin disaring `boleh` seperti kartu inti (U4): karyawan hanya kartu plugin
    `untuk="karyawan"`."""
    return [c.katalog() for c in (*REGISTRY.values(), *(plugin or {}).values()) if boleh(c, karyawan)]


def template(surface: str, karyawan: bool) -> list[dict]:
    """Salinan baru template bawaan (dokumen bisa diubah pemanggil)."""
    if surface != "beranda":
        return []
    return [dict(item) for item in (TEMPLATE_KARYAWAN if karyawan else TEMPLATE_BERANDA)]
