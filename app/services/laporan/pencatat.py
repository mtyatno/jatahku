"""Pencatat di laporan beku (Ruling R15): satu-satunya penulis ulang `reports.data` setelah terbit.

Laporan beku penerima memuat nama dan teks catatan anggota lain yang mencatat di amplop bersama (`terbesar[]`,
`langganan.terbayar[]`, `mutasi[]`; baris-baris itu membawa `pencatat_id`, lihat docstring `susun.py`). Janji hapus
akun (`account_deletion`): catatan anggota yang menghapus akun dianonimkan menjadi "Mantan anggota", nominal tetap.
Satu-satunya pengecualian yang disetujui untuk "beku" (spec bagian 2e) ada di sini:

- `anonimkan_pencatat` (hapus akun): di laporan milik user LAIN, persis baris yang `pencatat_id`-nya akun itu ditulis
  ulang seperti catatan hidupnya: `pencatat` -> nama pengganti, `pencatat_id` -> id pengganti, teks catatan
  (`keterangan`, atau `nama` tagihan terbayar) -> teks pengganti pengeluaran (baris `masuk`: teks pengganti pemasukan).
  Teks yang sudah tersamar "Transaksi privat" dibiarkan: aplikasi pun tetap menampilkan catatan privat yang sudah
  dianonimkan sebagai "Transaksi privat" kepada anggota lain. Laporan milik akun itu sendiri tidak disentuh (ikut
  terhapus bersama akunnya).
- `alihkan_pencatat` (gabung akun): `pencatat_id` sumber -> target di semua laporan; nama dan teks tetap seperti saat
  terbit. Tanpa ini baris yang dicatat sumber menunjuk akun yang sudah tidak ada, dan hapus akun target kelak tidak
  bisa menganonimkannya.

Angka, tanggal, amplop, dan kunci lain tidak pernah berubah. Laporan dicari dengan penyaring murah (teks JSON `data`
memuat id itu: `CAST(data AS TEXT) LIKE`, jalan di JSONB PostgreSQL dan JSON SQLite) lalu baris yang ditulis ulang
ditentukan `pencatat_id` di Python. Hasilnya ditulis sebagai objek baru (UPDATE), bukan diubah di tempat, supaya
kolom JSON benar-benar tersimpan. Berjalan di transaksi pemanggil; pemanggil yang commit.
"""
import copy
import uuid

from sqlalchemy import Text, cast, select, update

from app.models.models import Report
from app.services.visibility import PRIVATE_PLACEHOLDER

# Kunci teks catatan di baris yang membawa `pencatat_id`: `keterangan` (`terbesar[]`, `mutasi[]`) dan `nama`
# (`langganan.terbayar[]`, dari keterangan pembayaran tagihan).
KUNCI_TEKS = ("keterangan", "nama")


def _baris_berpencatat(nilai):
    """Setiap kamus di dalam `nilai` (menelusuri kamus dan daftar) yang membawa `pencatat_id`."""
    if isinstance(nilai, dict):
        if "pencatat_id" in nilai:
            yield nilai
        for isi in nilai.values():
            yield from _baris_berpencatat(isi)
    elif isinstance(nilai, list):
        for isi in nilai:
            yield from _baris_berpencatat(isi)


def anonimkan_data(data: dict, user_id: str, *, id_pengganti: str, nama_pengganti: str, teks_pengeluaran: str,
                   teks_pemasukan: str) -> dict | None:
    """Salinan `data` dengan setiap baris yang dicatat `user_id` (teks) dianonimkan (aturan: docstring modul), atau
    None bila tak satu baris pun dicatat `user_id`. `data` tidak diubah."""
    baru = copy.deepcopy(data)
    berubah = False
    for baris in _baris_berpencatat(baru):
        if baris["pencatat_id"] != user_id:
            continue
        berubah = True
        baris["pencatat_id"] = id_pengganti
        if "pencatat" in baris:
            baris["pencatat"] = nama_pengganti
        pengganti = teks_pemasukan if baris.get("arah") == "masuk" else teks_pengeluaran
        for kunci in KUNCI_TEKS:
            if kunci in baris and baris[kunci] != PRIVATE_PLACEHOLDER:
                baris[kunci] = pengganti
    return baru if berubah else None


def alihkan_data(data: dict, dari: str, ke: str) -> dict | None:
    """Salinan `data` dengan `pencatat_id` `dari` menjadi `ke` (teks), atau None bila tak ada baris `dari`. Hanya id;
    nama dan teks tetap. `data` tidak diubah."""
    baru = copy.deepcopy(data)
    berubah = False
    for baris in _baris_berpencatat(baru):
        if baris["pencatat_id"] == dari:
            baris["pencatat_id"] = ke
            berubah = True
    return baru if berubah else None


def _teks_id(user_id) -> str:
    """Id user dalam bentuk yang dibekukan pemuat (`str(uuid)`: huruf kecil, bertanda hubung), dari UUID atau teks."""
    return str(uuid.UUID(str(user_id)))


async def _tulis_ulang(db, user_id: str, ubah, *, kecuali_milik=None) -> int:
    """Terapkan `ubah(data) -> data baru | None` pada laporan yang teks `data`-nya memuat `user_id`; laporan milik
    `kecuali_milik` dilewati. Mengembalikan jumlah laporan yang ditulis ulang."""
    syarat = [cast(Report.data, Text).contains(user_id, autoescape=True)]
    if kecuali_milik is not None:
        syarat.append(Report.user_id != kecuali_milik)
    jumlah = 0
    for report_id, data in (await db.execute(select(Report.id, Report.data).where(*syarat))).all():
        baru = ubah(data)
        if baru is not None:
            await db.execute(
                update(Report).where(Report.id == report_id).values(data=baru)
                .execution_options(synchronize_session=False)
            )
            jumlah += 1
    return jumlah


async def anonimkan_pencatat(db, user_id, *, id_pengganti: str, nama_pengganti: str, teks_pengeluaran: str,
                             teks_pemasukan: str) -> int:
    """Hapus akun `user_id`: anonimkan catatannya di laporan beku milik user lain (aturan: docstring modul).
    Mengembalikan jumlah laporan yang ditulis ulang."""
    uid = _teks_id(user_id)
    return await _tulis_ulang(
        db, uid,
        lambda data: anonimkan_data(data, uid, id_pengganti=id_pengganti, nama_pengganti=nama_pengganti,
                                    teks_pengeluaran=teks_pengeluaran, teks_pemasukan=teks_pemasukan),
        kecuali_milik=uuid.UUID(uid),
    )


async def alihkan_pencatat(db, dari, ke) -> int:
    """Gabung akun: `pencatat_id` `dari` menjadi `ke` di semua laporan. Mengembalikan jumlah laporan yang ditulis
    ulang."""
    sumber, target = _teks_id(dari), _teks_id(ke)
    return await _tulis_ulang(db, sumber, lambda data: alihkan_data(data, sumber, target))
