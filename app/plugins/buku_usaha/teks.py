"""Templat teks Buku Usaha (Plugin U3; AGENTS.md "Plugin dan ruang" aturan 7).

Kalimat laporan dirakit dari sini supaya laporan PDF/CSV, chat `/laba` (U6), dan saran BU-* (U5) memakai bunyi dan
format angka yang sama. Angka tidak dihitung di sini; semuanya dari `metrics.py`.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

BULAN = ("", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember")
BLN = ("", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
STRIP = "\N{EM DASH}"
LABEL_DI_LUAR = {"prive": "Prive (diambil pemilik)", "modal": "Modal pemilik", "pinjaman": "Pinjaman",
                 "lain": "Pemasukan lain"}

TEMPLAT = {
    "judul_laba_rugi": "Laba rugi {bulan}",
    "subjudul_laba_rugi": "{ruang} · {mulai}–{akhir}",
    "berjalan": "Bulan berjalan: angka masih bisa berubah sampai akhir bulan.",
    "aturan": ("Omzet hanya dari penjualan. Modal pemilik, pinjaman, pemasukan lain, dan prive tidak masuk laba rugi. "
               "Beban adalah semua pengeluaran dari amplop bersama ruang ini."),
    "tanpa_jenis": ("{banyak} pemasukan tanpa jenis ({jumlah}) ikut dihitung sebagai omzet. Catat penjualan lewat "
                    "Catat › Penjualan supaya jenisnya tercatat."),
    "belum_berakun": ("Pengeluaran tanpa akun beban masuk \"Belum berakun\", termasuk pengeluaran privat anggota "
                      "(dihitung nominalnya saja, tanpa akun dan keterangan)."),
    "terpotong": ("Daftar {apa} memuat {tampil} catatan terbaru dari {total}; angka di ringkasan tetap mencakup "
                  "semuanya."),
    "kosong": "Belum ada catatan di bulan ini.",
}


def t(kunci: str, **isi) -> str:
    """Isi `{nama}` di templat (bukan `str.format`, yang ditolak validator plugin: `kode.py`)."""
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(isi[m.group(1)]), TEMPLAT[kunci])


def nama_bulan(periode: str) -> str:
    """"2026-10" → "Oktober 2026"."""
    th, bl = periode.split("-")
    return f"{BULAN[int(bl)]} {th}"


def tanggal(d: date) -> str:
    return f"{d.day} {BLN[d.month]} {d.year}"


def rupiah(v: Decimal) -> str:
    bulat = Decimal(v).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if not bulat:
        return "Rp0"
    angka = f"{abs(bulat):,}".replace(",", ".")
    return f"-Rp{angka}" if bulat < 0 else f"Rp{angka}"


def persen(r: Decimal | None) -> str:
    """Rasio 4 desimal → "25,4%" (satu desimal, tanpa ",0"); None → "—"."""
    if r is None:
        return STRIP
    p = (Decimal(r) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if not p:
        p = Decimal("0")
    s = f"{p:f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(".", ",") + "%"
