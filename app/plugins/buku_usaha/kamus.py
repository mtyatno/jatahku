"""Kamus Catat cepat Buku Usaha (Plugin U5; 05-desain-buku-usaha.md B3.2 butir 3–4).

Tiga bagian, dua di antaranya cukup data di `manifest.json`:

- `nlp_kamus`: kata → amplop bawaan (Bahan, Operasional), dicoba host sesudah kata user dan kamus ruang (R7).
- `nlp_jenis`: kata atau frasa utuh → jenis catatan (penjualan, modal, pinjaman).
- **Kontak** (modul ini): pelanggan atau pemasok yang disebut di teks. Fungsi murni; daftar kontaknya dibaca
  `@plugin.kontak_catatan` di `__init__.py` lewat `ctx.data()` (hanya ruang konteks, hanya pemilik dan admin).

Satuan ("40 kg", "50 pax") tetap bagian keterangan: nominal diurai di perangkat (`parseAmount.js`) dan token satuan
sudah dibuang inti sebelum kata masuk kamus ruang (`txn_nlp.kata_kamus`), jadi tidak perlu kamus tersendiri.
"""
from __future__ import annotations

import re

BATAS_KONTAK = 500              # kontak terbaru yang dicocokkan per peran
PANJANG_MIN = 4                 # huruf minimal sebuah sebutan, supaya "cv" atau "ani" di dalam kata lain tidak cocok
# Awalan badan usaha dan sapaan: orang jarang mengetiknya ("sumber unggas" untuk "UD Sumber Unggas").
AWALAN = frozenset({
    "pt", "cv", "ud", "pd", "fa", "tb", "rm", "toko", "warung", "kedai", "depot", "koperasi",
    "pak", "bapak", "bu", "ibu", "mas", "mbak", "kak", "haji", "hj",
})
_KATA = r"[a-z0-9]+"


def _kata(teks) -> list[str]:
    return re.findall(_KATA, teks.lower()) if isinstance(teks, str) else []


def _inti(kata: list[str]) -> list[str]:
    """Nama tanpa awalan di depan; nama yang seluruhnya awalan dibiarkan."""
    i = 0
    while i < len(kata) - 1 and kata[i] in AWALAN:
        i += 1
    return kata[i:]


def _memuat(teks: list[str], urutan: list[str]) -> bool:
    """`urutan` muncul berurutan dan utuh di `teks` (per kata, bukan potongan kata)."""
    n = len(urutan)
    return n > 0 and any(teks[i:i + n] == urutan for i in range(len(teks) - n + 1))


def _cukup(urutan: list[str]) -> bool:
    return sum(len(k) for k in urutan) >= PANJANG_MIN


def _skor(teks: list[str], nama: str) -> tuple[int, int]:
    """(tingkat, banyak kata yang cocok): 3 = nama lengkap, 2 = nama tanpa awalan, 1 = kata pertama nama."""
    penuh = _kata(nama)
    inti = _inti(penuh)
    if _cukup(penuh) and _memuat(teks, penuh):
        return 3, len(penuh)
    if _cukup(inti) and _memuat(teks, inti):
        return 2, len(inti)
    if len(inti) > 1 and len(inti[0]) >= PANJANG_MIN and inti[0] in teks:
        return 1, 1
    return 0, 0


def cocok_kontak(teks, daftar) -> dict | None:
    """Kontak di `daftar` (baris `{"id", "nama", "peran"}`) yang disebut di `teks`: yang paling lengkap disebut
    menang; bila dua kontak sama kuat (mis. sama-sama hanya kata pertamanya), tidak menebak."""
    kata = _kata(teks)
    if not kata:
        return None
    terbaik, skor_terbaik, seri = None, (0, 0), False
    for k in daftar:
        skor = _skor(kata, k.get("nama") or "")
        if skor[0] == 0:
            continue
        if skor > skor_terbaik:
            terbaik, skor_terbaik, seri = k, skor, False
        elif skor == skor_terbaik:
            seri = True
    return None if seri else terbaik
