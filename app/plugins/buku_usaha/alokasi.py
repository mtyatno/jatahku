"""Pembantu murni alokasi omzet dan penjualan Buku Usaha (Plugin U2). Tanpa akses data: dipakai rute di `__init__.py`
dan tes. Nominal selalu `Decimal`, tidak pernah float."""
from datetime import date
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from app.plugins.sdk import NilaiTidakSah

# Jenis pemasukan usaha (05-desain-buku-usaha.md; 01-kajian "Buku Usaha"). Hanya `penjualan` dihitung omzet (U3) dan
# dibagi menurut aturan alokasi; jenis lain masuk satu amplop pilihan user (bawaan Laba ditahan).
JENIS = ("penjualan", "modal", "pinjaman", "lain")
LABEL_JENIS = {"penjualan": "Penjualan", "modal": "Modal pemilik", "pinjaman": "Pinjaman", "lain": "Lain-lain"}
AMPLOP_BAWAAN_NON_PENJUALAN = "Laba ditahan"
# Saran pertama tab Alokasi omzet untuk amplop bawaan (05-desain-buku-usaha.md A3).
SARAN_PERSEN = {"Bahan": 45, "Operasional": 30, "Prive": 15, "Laba ditahan": 9, "Pajak": 1}
MAKS_ATURAN = 10
SERATUS = Decimal("100")
SATU_RUPIAH = Decimal("1")
SEN = Decimal("0.01")
MAKS_NOMINAL = Decimal("9999999999999.99")


def angka(v, nama: str, *, tempat: int = 2) -> Decimal:
    """Angka dari body JSON (int, teks, atau pecahan dari `json.loads`) → Decimal dengan maksimal `tempat` desimal.
    Pecahan JSON dibaca lewat teksnya (`str`), jadi 45.5 tetap 45.5, bukan pecahan biner."""
    if isinstance(v, bool) or v is None or not isinstance(v, (int, float, str, Decimal)):
        raise NilaiTidakSah(f"{nama} harus angka.")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise NilaiTidakSah(f"{nama} harus angka.")
    if not d.is_finite():
        raise NilaiTidakSah(f"{nama} harus angka.")
    if d.adjusted() > 15:      # di atas Numeric(15, 2); juga mencegah `quantize` melempar (review #201 temuan T2)
        raise NilaiTidakSah(f"{nama} terlalu besar.")
    if d != d.quantize(Decimal(1).scaleb(-tempat)):
        raise NilaiTidakSah(f"{nama} paling banyak {tempat} angka di belakang koma.")
    return d


def jumlah_uang(v) -> Decimal:
    d = angka(v, "Jumlah")
    if d <= 0 or d > MAKS_NOMINAL:
        raise NilaiTidakSah("Jumlah harus lebih dari nol.")
    return d


def tanggal(v) -> date | None:
    if v is None or v == "":
        return None
    if not isinstance(v, str) or len(v) != 10:
        raise NilaiTidakSah("Tanggal harus berbentuk YYYY-MM-DD.")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise NilaiTidakSah("Tanggal harus berbentuk YYYY-MM-DD.")


def rapikan_aturan(isian) -> list[tuple[str, Decimal]]:
    """Body `PUT /alokasi` → [(envelope_id teks, persen)], tanpa memeriksa amplopnya (itu tugas rute). Total harus
    tepat 100; persen 0 < p ≤ 100 dengan maksimal dua desimal; amplop tidak boleh ganda."""
    if not isinstance(isian, list) or not isian:
        raise NilaiTidakSah("Aturan alokasi wajib diisi.")
    if len(isian) > MAKS_ATURAN:
        raise NilaiTidakSah(f"Paling banyak {MAKS_ATURAN} amplop.")
    out, lihat = [], set()
    for a in isian:
        if not isinstance(a, dict) or set(a) - {"envelope_id", "persen"}:
            raise NilaiTidakSah("Aturan alokasi tidak terbaca.")
        eid = a.get("envelope_id")
        if not isinstance(eid, str) or not eid or len(eid) > 64:
            raise NilaiTidakSah("Amplop tidak dikenali.")
        if eid in lihat:
            raise NilaiTidakSah("Amplop yang sama muncul dua kali.")
        lihat.add(eid)
        p = angka(a.get("persen"), "Persen")
        if p <= 0 or p > SERATUS:
            raise NilaiTidakSah("Persen harus lebih dari 0 dan paling banyak 100.")
        out.append((eid, p))
    return out


def total_persen(aturan) -> Decimal:
    return sum((Decimal(p) for _, p in aturan), Decimal("0"))


def bagi(jumlah: Decimal, aturan) -> list[Decimal]:
    """Bagi `jumlah` menurut persen [(kunci, persen)], total persen 100. Setiap bagian dibulatkan ke bawah per rupiah;
    sisa pembulatan (termasuk sen) masuk ke bagian dengan persen terbesar (yang pertama bila sama), jadi jumlah
    bagian selalu persis sama dengan `jumlah` dan tidak ada sisa yang lari ke amplop lain."""
    if not aturan:
        return []
    if total_persen(aturan) != SERATUS:
        raise ValueError("total persen harus 100")
    bagian = [(jumlah * Decimal(p) / SERATUS).quantize(SATU_RUPIAH, rounding=ROUND_DOWN) for _, p in aturan]
    sisa = jumlah - sum(bagian, Decimal("0"))
    terbesar = max(range(len(aturan)), key=lambda i: (Decimal(aturan[i][1]), -i))
    bagian[terbesar] += sisa
    return [b.quantize(SEN) for b in bagian]


def keterangan(jenis: str, isian, nama_kontak: str | None) -> str:
    """Keterangan pemasukan: isian user bila ada, selain itu label jenis (+ nama pelanggan untuk penjualan)."""
    if isian is not None and not isinstance(isian, str):
        raise NilaiTidakSah("Keterangan tidak terbaca.")
    teks = " ".join((isian or "").split())
    if len(teks) > 200:
        raise NilaiTidakSah("Keterangan paling banyak 200 karakter.")
    if teks:
        return teks
    dasar = LABEL_JENIS[jenis]
    return f"{dasar} · {nama_kontak}" if nama_kontak else dasar
