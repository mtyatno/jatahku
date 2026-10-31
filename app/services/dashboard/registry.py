"""Registry kartu Beranda (Plugin B1, docs/plugin/01-kajian.md "Tiga konsep inti", ADR-P8).

Definisi kartu hidup di kode. Satu definisi = satu `key` (mis. `core.kpi.jatah`) dengan judul,
ukuran yang didukung, sumber data, dan validator pengaturan. Penyedia data didaftarkan dengan
key yang sama di `providers.py`. Kartu plugin akan mendaftar lewat titik ekstensi `cards` (H2).

Teks yang tampil ke user (judul, deskripsi) dirakit di sini, satu tempat, supaya web, aplikasi,
dan permukaan lain memakai kalimat yang sama (AGENTS.md "Plugin dan ruang" aturan 7).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

SIZES = ("S", "M", "L", "XL")
DEVICES = ("all", "wide", "narrow")
SHAPES = ("kpi", "progress", "list", "table", "series", "alert", "inti")
SURFACES = ("beranda",)
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

    def katalog(self) -> dict:
        """Satu baris `GET /dashboard/cards` (04-kontrak-api.md §4)."""
        return {
            "key": self.key, "judul": self.judul, "deskripsi": self.deskripsi, "asal": self.asal,
            "sizes": list(self.sizes), "size_bawaan": self.size_bawaan, "shape": self.shape,
            "supports_period": self.supports_period, "multi_instance": self.multi_instance,
            "refresh_on": list(self.refresh_on), "hak": "ok", "baru": False,
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

REGISTRY: dict[str, CardDef] = {c.key: c for c in CORE}

# Template Beranda ruang keluarga = Beranda sekarang. `devices` mengikuti tampilan sekarang:
# Papan disiplin hanya di katalog (sekarang tampil di sidebar dan header HP, bukan kartu grid).
TEMPLATE_BERANDA: tuple[dict, ...] = tuple(
    {"id": f"a{i}", "card": key, "size": REGISTRY[key].size_bawaan, "hidden": False, "devices": "all"}
    for i, key in enumerate((
        "core.kpi.jatah", "core.kpi.sisa_bebas", "core.kpi.terpakai", "core.kpi.income",
        "core.kpi.tagihan", "core.kpi.tabungan", "core.cocokkan_saldo", "core.pengeluaran_harian",
        "core.advisor", "core.ke_mana_uangmu", "core.amplop_pengeluaran", "core.target_tabungan",
        "core.transaksi_terbaru", "core.langganan",
    ), start=1)
)


def get(key: str) -> CardDef | None:
    return REGISTRY.get(key)


def katalog() -> list[dict]:
    return [c.katalog() for c in REGISTRY.values()]


def template(surface: str) -> list[dict]:
    """Salinan baru template bawaan (dokumen bisa diubah pemanggil)."""
    return [dict(item) for item in TEMPLATE_BERANDA] if surface == "beranda" else []
