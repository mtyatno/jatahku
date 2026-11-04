"""Perhitungan murni laporan berkala (spec 2026-11-01-laporan-berkala-design): status amplop dan "tidak pernah
lewat batas" (bagian 2d), judul (bagian 3), nama berkas PDF (bagian 4), sorotan (bagian 2c dan 6b).

Tanpa database, setelan, atau I/O: pembangun `data` laporan memanggil fungsi di sini, dan semuanya bisa diuji
dengan angka tulis tangan. Uang selalu `Decimal` dan tanggal selalu `datetime.date`. Persen dibulatkan
ROUND_HALF_UP ke bilangan bulat (langsung bisa masuk JSON); uang keluar sebagai teks dua desimal karena
`reports.data` menyimpan uang sebagai string desimal, bukan float.
"""
import calendar
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

# Indeks 1-12 dengan string kosong di indeks 0, supaya BULAN[tanggal.month] bisa dipakai langsung.
BULAN = (
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)
BLN = ("", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")

# Amplop hampir habis bila terpakai >= 70% dari saldo awal (ambang yang sama dengan bar amplop di Beranda).
AMBANG_HAMPIR_HABIS = Decimal("0.7")

_TUJUAN_TABUNGAN = ("saving", "sinking_fund")
_BERUNTUN_SOROTAN = 7          # catat beruntun sepanjang ini cukup jadi sorotan utama
_PEMISAH_RENTANG = " – "       # en dash U+2013 dengan spasi di kedua sisi, bukan tanda hubung "-"
_NOL = Decimal(0)
_SATU = Decimal(1)
_SEN = Decimal("0.01")


def adalah_bulan_kalender(ps: date, pe: date) -> bool:
    """True bila periode persis satu bulan kalender: tanggal 1 sampai hari terakhir bulan yang sama."""
    hari_terakhir = calendar.monthrange(ps.year, ps.month)[1]
    return ps.day == 1 and pe == date(ps.year, ps.month, hari_terakhir)


def judul_bulanan(ps: date, pe: date) -> str:
    """Judul laporan satu periode: "Laporan Oktober 2026" untuk bulan kalender; selain itu rentang tanggal
    dengan singkatan bulan ("Laporan 25 Sep – 24 Okt 2026"), dan tahun ditulis di kedua ujung bila berbeda."""
    if adalah_bulan_kalender(ps, pe):
        return f"Laporan {BULAN[ps.month]} {ps.year}"
    awal = f"{ps.day} {BLN[ps.month]}"
    akhir = f"{pe.day} {BLN[pe.month]}"
    if ps.year == pe.year:
        return f"Laporan {awal}{_PEMISAH_RENTANG}{akhir} {ps.year}"
    return f"Laporan {awal} {ps.year}{_PEMISAH_RENTANG}{akhir} {pe.year}"


def nama_file_pdf(jenis: str, ps: date, pe: date) -> str:
    """Nama berkas PDF: `jatahku-laporan-YYYY-MM.pdf` untuk bulan kalender, selain itu memuat tanggal awal
    (`jatahku-laporan-YYYY-MM-DD.pdf`). Hanya jenis `bulanan` yang dikenal (tahap 3 menambah); jenis lain
    `ValueError`, bukan nama karangan."""
    if jenis != "bulanan":
        raise ValueError(f"jenis laporan tidak dikenal: {jenis!r}")
    if adalah_bulan_kalender(ps, pe):
        return f"jatahku-laporan-{ps.year:04d}-{ps.month:02d}.pdf"
    return f"jatahku-laporan-{ps.isoformat()}.pdf"


def adalah_tabungan(tujuan: str) -> bool:
    """True bila `tujuan` amplop adalah tabungan (`saving` atau `sinking_fund`): saldonya sengaja ditumpuk, bukan
    jatah yang dihabiskan. Satu-satunya daftar tujuan tabungan di paket laporan: `status_amplop` dan penyusun `data`
    (persen terpakai tanpa tabungan) sama-sama memakainya."""
    return tujuan in _TUJUAN_TABUNGAN


def status_amplop(tujuan: str, awal: Decimal, terpakai: Decimal, akhir: Decimal) -> str:
    """Status satu amplop di akhir periode; aturan dicek berurutan dan yang pertama cocok menang:
    tabungan (`adalah_tabungan`: `saving`/`sinking_fund`), lewat_batas (akhir < 0), kosong (awal <= 0),
    hampir_habis (terpakai >= AMBANG_HAMPIR_HABIS * awal), selain itu aman."""
    if adalah_tabungan(tujuan):
        return "tabungan"
    if akhir < 0:
        return "lewat_batas"
    if awal <= 0:
        return "kosong"
    if terpakai >= AMBANG_HAMPIR_HABIS * awal:
        return "hampir_habis"
    return "aman"


def pernah_lewat_batas(
    rollover_masuk: Decimal,
    alokasi_per_hari: dict[date, Decimal],
    belanja_per_hari: dict[date, Decimal],
    ps: date,
    pe: date,
) -> bool:
    """True bila saldo amplop pernah di bawah nol pada akhir hari mana pun di periode.

    Saldo mulai dari `rollover_masuk` (bisa negatif: rollover membawa kekurangan juga); tiap hari dari `ps`
    sampai `pe`, keduanya ikut, ditambah alokasi hari itu dan dikurangi belanja hari itu. Alokasi dan belanja
    di hari yang sama diperhitungkan bersama (yang diukur saldo akhir hari). Isi kamus di luar `ps`..`pe`
    diabaikan: yang sebelum `ps` sudah ada di `rollover_masuk`."""
    saldo = rollover_masuk
    for n in range((pe - ps).days + 1):
        hari = ps + timedelta(days=n)
        saldo += alokasi_per_hari.get(hari, _NOL) - belanja_per_hari.get(hari, _NOL)
        if saldo < 0:
            return True
    return False


def beruntun_terpanjang(tanggal: Iterable[date]) -> int:
    """Rentetan hari kalender berurutan terpanjang di `tanggal`. Urutan masukan bebas dan beberapa catatan di
    hari yang sama dihitung sekali. Kosong: 0."""
    hari = sorted({t.toordinal() for t in tanggal})
    terpanjang = panjang = 0
    for i, h in enumerate(hari):
        panjang = panjang + 1 if i and h - hari[i - 1] == 1 else 1
        terpanjang = max(terpanjang, panjang)
    return terpanjang


def _persen_bulat(nilai: Decimal) -> int:
    return int(nilai.quantize(_SATU, rounding=ROUND_HALF_UP))


def persen(bagian: Decimal, total: Decimal) -> int | None:
    """`bagian` sebagai persen dari `total`, bilangan bulat ROUND_HALF_UP (12,5 jadi 13; `round()` memberi 12).
    None bila `total` <= 0 (tidak ada dasar). Tidak dibatasi 100."""
    if total <= 0:
        return None
    return _persen_bulat(bagian * 100 / total)


def persen_perubahan(sekarang: Decimal, lalu: Decimal | None) -> int | None:
    """Perubahan `sekarang` terhadap `lalu` dalam persen bulat ROUND_HALF_UP menjauhi nol; turun bernilai negatif
    (88 dari 100 jadi -12). None bila tidak ada pembanding yang berarti: `lalu` None (periode tanpa angka),
    nol, atau negatif."""
    if lalu is None or lalu <= 0:
        return None
    return _persen_bulat((sekarang - lalu) * 100 / lalu)


def rata_rata(nilai: list[Decimal | None]) -> Decimal | None:
    """Rata-rata nilai yang ada. None (periode tanpa angka) dilewati dan tidak masuk pembagi; nol adalah nilai
    nyata dan ikut dihitung. None bila tidak ada nilai sama sekali. Tidak dibulatkan: bulatkan sekali, di `uang()`."""
    ada = [n for n in nilai if n is not None]
    if not ada:
        return None
    return sum(ada, _NOL) / len(ada)


def uang(x: Decimal) -> str:
    """Teks uang dua desimal, ROUND_HALF_UP (Decimal("1.005") jadi "1.01"; float memberi 1.00). Hasil pembulatan
    yang nol negatif ("-0.00") ditulis "0.00": laporan yang terbit tidak pernah diubah lagi."""
    hasil = x.quantize(_SEN, rounding=ROUND_HALF_UP)
    if not hasil:
        hasil = hasil.copy_abs()
    return str(hasil)


def teks_sorotan(beruntun: int, amplop_aman: int, hari_mencatat: int) -> str:
    """Satu kalimat sorotan; yang pertama cocok menang: catat beruntun sepanjang 7 hari atau lebih, ada amplop
    yang tidak pernah lewat batas, ada hari mencatat, selain itu ajakan periode berikutnya."""
    if beruntun >= _BERUNTUN_SOROTAN:
        return f"Mencatat {beruntun} hari berturut-turut"
    if amplop_aman >= 1:
        return f"{amplop_aman} amplop tidak pernah lewat batas"
    if hari_mencatat >= 1:
        return f"Mencatat di {hari_mencatat} hari"
    return "Siap untuk periode berikutnya"
