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
    # U4: kartu Beranda. Angka dari `metrics.py`; kalimatnya dari sini.
    "kartu_banyak_penjualan": "{banyak} penjualan",
    "kartu_omzet_kaki": "{bulan} · bulan lalu {lalu}",
    "kartu_margin": "margin {margin}",
    "kartu_laba_kaki": "{bulan} · omzet {omzet} − beban {beban}",
    "kartu_kas_amplop": "{banyak} amplop",
    "kartu_kas_kaki": "Sisa semua amplop bersama saat ini",
    "kartu_kas_minus": "Sisa semua amplop bersama saat ini · {minus} amplop minus",
    "kartu_alokasi_label": "{nama} · {persen}",
    "kartu_masuk": "Masuk",
    "kartu_keluar": "Keluar",
    "kartu_kontak_terhapus": "Kontak terhapus",
    "kartu_saya_kaki": "{bulan} · penjualan yang kamu catat sendiri",
    # U5: saran AI Advisor BU-*. Angka dari `metrics.py`, syarat dari `aturan.py`.
    "bu01_chip": "Kas usaha",
    "bu01_judul": "Kas usaha cukup ±{hari} hari",
    "bu01_judul_habis": "Kas usaha habis",
    "bu01_isi": ("Kas {kas}, sedangkan kebutuhan dua minggu sekitar {butuh} "
                 "(rata-rata pengeluaran 28 hari terakhir)."),
    "bu01_fakta_kas": "Kas usaha",
    "bu01_fakta_butuh": "Kebutuhan 2 minggu",
    "bu02_chip": "Prive",
    "bu02_judul": "Prive {bulan} melebihi laba",
    "bu02_isi": "Prive {prive} lebih besar dari laba {laba}; selisih {selisih} mengurangi modal usaha.",
    "bu02_fakta_prive": "Prive",
    "bu02_fakta_laba": "Laba",
    "bu03_chip": "Pajak",
    "bu03_judul": "Amplop Pajak masih kosong",
    "bu03_isi": "Omzet {bulan} sudah {omzet}, tetapi amplop Pajak belum terisi. Sisihkan lewat alokasi omzet.",
    "aksi_laba_rugi": "Lihat laba rugi",
    "aksi_alokasi": "Atur alokasi omzet",
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


def hari_bulan(d: date) -> str:
    """Label pendek sumbu grafik: "9 Nov"."""
    return f"{d.day} {BLN[d.month]}"


def perubahan(r: Decimal | None) -> str:
    """Rasio perubahan → "+9,1%" / "-12,5%" / "0%"; None (tidak ada pembanding) → ""."""
    if r is None:
        return ""
    p = persen(r)
    return p if p.startswith("-") or p == "0%" else f"+{p}"


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
