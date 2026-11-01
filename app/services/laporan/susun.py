"""Penyusun `data` v1 laporan bulanan (spec 2026-11-01-laporan-berkala-design, bagian 2c): bahan biasa (dataclass)
menjadi kamus JSON yang dibekukan di `reports.data`.

Murni: tanpa database, setelan, atau I/O. `muat.py` (Task 4) satu-satunya pembaca DB dan yang mengisi
`BahanLaporan`; halaman, PDF, dan email hanya membaca kunci yang dihasilkan di sini dan tidak menghitung ulang.
Semua angka berasal dari bahan itu dan dari `hitung.py`; tidak ada rumus advisor baru ("satu sumber angka").

Syarat bahan (pemuat yang menjamin; di sini hanya dicek yang bila salah membuat `data` keliru tanpa terlihat):
- transaksi dan alokasi sudah berada di jendela `periode_mulai`..`periode_akhir`, keterangan sudah disamarkan
  (`visibility.masked_description`), amplop terbatas pada lingkup penerima;
- uang selalu `Decimal` (`uang()` menolak int) dan `tujuan` nilai mentahnya (`"saving"`, bukan `str(enum)`);
- `terpakai_lalu` tiap amplop berisi tepat tiga nilai (terlama dulu), `None` untuk periode tanpa snapshot;
- `terpakai_lalu_total` berisi tepat tiga nilai (terlama dulu): total terpakai semua amplop lingkup penerima yang
  punya snapshot periode itu, juga yang bukan baris di `amplop` (sudah ditutup atau dihapus); `None` bila tak satu
  pun punya. Total pembanding di `banding` berasal dari sini, tidak dijumlahkan dari baris; angka per amplop di
  `banding.amplop[]` tetap dari `terpakai_lalu` baris masing-masing;
- setiap transaksi dan target menunjuk amplop yang ada di `bahan.amplop`; tagihan periode berikut boleh menunjuk
  amplop di luar bahan (amplop yang dibuat sesudah periode tidak punya baris), namanya lalu `null`.
Pelanggaran syarat `terpakai_lalu`, `terpakai_lalu_total`, atau syarat amplop transaksi dan target adalah bug
pemuat: `ValueError`, tidak ditambal, karena laporan yang terbit tidak pernah diubah lagi.

Bentuk keluaran: uang teks dua desimal (`uang()`), tanggal ISO, persen `int`, tanpa float. Jumlah uang di
`ringkasan` meliputi semua baris, tetapi `ringkasan.persen_terpakai` (dan `email.persen_terpakai`) hanya atas amplop
selain tabungan (`hitung.adalah_tabungan`), di pembilang dan penyebut. `sorotan.amplop_aman` berisi nama amplop yang
statusnya bukan tabungan, kosong, atau lewat_batas dan saldo hariannya tak pernah di bawah nol; `email.amplop_aman`
hanya hitungan amplop berstatus `aman`.
Bisa `null`:
- `ringkasan.persen_terpakai`, `email.persen_terpakai`: jumlah saldo awal amplop selain tabungan nol atau negatif
  (juga bila tak ada amplop selain tabungan);
- `banding.terpakai_lalu`: bila `terpakai_lalu_total` periode p-1 `None`; `banding.terpakai_rata3`: hanya bila ketiga
  total `None` (total `None` dilewati dan tidak masuk pembagi, nol adalah angka dan ikut dihitung);
- `banding.persen_perubahan`, `email.tren_persen`: bila total p-1 `None`, nol, atau negatif;
- `banding.amplop[].terpakai_lalu`: bila baris itu tanpa angka p-1; `banding.amplop[].terpakai_rata3`: hanya bila
  ketiga angka baris itu `None`;
- `hari_terboros` (tak ada hari di atas nol), `mutasi[].amplop` (baris `masuk`), `langganan.jatuh_tempo[].amplop`
  (amplop di luar bahan), `sorotan.target[].persen` (target nol).
Urutan: `amplop` dan `banding.amplop` menurut bahan; `harian` menurut tanggal; `terbesar` menurut jumlah;
`terbayar`, `jatuh_tempo`, dan `mutasi` menurut tanggal. Seri selalu menurut urutan masukan (pengurutan stabil);
di hari yang sama baris `masuk` mendahului baris `keluar` di `mutasi`.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.laporan.hitung import (
    adalah_tabungan, beruntun_terpanjang, judul_bulanan, pernah_lewat_batas, persen, persen_perubahan, rata_rata,
    status_amplop, teks_sorotan, uang,
)

VERSI = 1
JENIS = "bulanan"
JUMLAH_TERBESAR = 5
JUMLAH_PERIODE_BANDING = 3
# Awalan keterangan transaksi yang dibuat tombol Bayar langganan. Nilainya sama dengan
# `advisor.snapshot.BILL_MARKER` (dijaga tes); tidak diimpor dari sana supaya modul ini tetap hanya
# bergantung pada `hitung.py`.
PENANDA_TAGIHAN = "🔄 "

_NOL = Decimal(0)
_STATUS_BUKAN_AMAN = ("tabungan", "kosong", "lewat_batas")


@dataclass(frozen=True)
class AmplopPeriode:
    """Satu amplop dalam lingkup penerima dengan angka akhir periode. Dari snapshot: `awal` = rollover masuk +
    `alokasi` periode, `akhir` = `awal` - `terpakai`, `rollover` = yang dibawa ke periode berikut.
    `alokasi_per_hari`: alokasi menurut tanggal pemasukan (untuk "pernah lewat batas"). `terpakai_lalu`: terpakai
    tiga periode sebelumnya, terlama dulu (p-3, p-2, p-1); `None` bila periode itu tanpa snapshot."""
    id: str
    nama: str
    emoji: str
    pribadi: bool
    tujuan: str
    awal: Decimal
    alokasi: Decimal
    terpakai: Decimal
    akhir: Decimal
    rollover: Decimal
    ditutup: bool
    alokasi_per_hari: dict[date, Decimal]
    terpakai_lalu: list[Decimal | None]


@dataclass(frozen=True)
class TransaksiPeriode:
    """Satu pengeluaran di jendela laporan. `keterangan` sudah tersamar; `milik_penerima`: dicatat penerima
    sendiri; `penyesuaian`: baris cocokkan saldo; `tagihan`: dibuat tombol Bayar langganan."""
    id: str
    amplop_id: str
    tanggal: date
    jumlah: Decimal
    keterangan: str
    pencatat: str
    milik_penerima: bool
    penyesuaian: bool
    tagihan: bool


@dataclass(frozen=True)
class PemasukanPeriode:
    """Satu pemasukan yang dicatat penerima di jendela laporan."""
    tanggal: date
    jumlah: Decimal
    keterangan: str


@dataclass(frozen=True)
class TagihanBerikut:
    """Langganan aktif yang jatuh tempo di periode berikutnya."""
    tanggal: date
    nama: str
    amplop_id: str
    jumlah: Decimal


@dataclass(frozen=True)
class TargetTabungan:
    """Target tabungan milik satu amplop; yang terkumpul adalah saldo akhir amplopnya."""
    nama: str
    amplop_id: str
    target: Decimal


@dataclass(frozen=True)
class BahanLaporan:
    """Semua masukan `susun_bulanan` untuk satu penerima dan satu periode; `angka_per` = tanggal terbit.
    `terpakai_lalu_total`: total terpakai tiga periode sebelumnya, terlama dulu (p-3, p-2, p-1), atas SEMUA amplop
    lingkup penerima yang punya snapshot periode itu, termasuk amplop yang bukan baris di `amplop` (sudah ditutup
    atau dihapus); `None` bila tak satu pun amplop lingkup punya snapshot periode itu. Wajib, tanpa nilai bawaan."""
    penerima_nama: str
    rumah_nama: str
    periode_mulai: date
    periode_akhir: date
    payday: int
    angka_per: date
    amplop: list[AmplopPeriode]
    transaksi: list[TransaksiPeriode]
    pemasukan: list[PemasukanPeriode]
    tagihan_berikut: list[TagihanBerikut]
    target: list[TargetTabungan]
    streak_saat_ini: int
    terpakai_lalu_total: list[Decimal | None]


def ada_aktivitas(bahan: BahanLaporan) -> bool:
    """True bila ada amplop dengan alokasi di atas nol atau ada transaksi. Pemasukan saja tidak cukup: tanpa
    alokasi dan tanpa pengeluaran tidak ada yang bisa dilaporkan (spec bagian 3: tidak ada laporan kosong)."""
    return bool(bahan.transaksi) or any(a.alokasi > 0 for a in bahan.amplop)


def susun_bulanan(bahan: BahanLaporan) -> dict:
    """`data` v1 laporan bulanan dari `bahan` (kunci dan definisinya: spec bagian 2c, rencana tahap 1 Task 3, dan
    docstring modul). Tidak mengubah `bahan`; hasilnya hanya str, int, bool, None, list, dan dict, jadi langsung
    bisa jadi JSON."""
    per_id = _periksa(bahan)
    ps, pe = bahan.periode_mulai, bahan.periode_akhir
    belanja = _belanja_per_amplop_hari(bahan.transaksi)
    status = [status_amplop(a.tujuan, a.awal, a.terpakai, a.akhir) for a in bahan.amplop]
    lewat = [
        pernah_lewat_batas(a.awal - a.alokasi, a.alokasi_per_hari, belanja.get(a.id, {}), ps, pe)
        for a in bahan.amplop
    ]
    total_terpakai = _jumlah(a.terpakai for a in bahan.amplop)
    ringkasan = _ringkasan(bahan, total_terpakai)
    banding = _banding(bahan.amplop, bahan.terpakai_lalu_total, total_terpakai)
    harian, hari_terboros = _harian(bahan)
    sorotan = _sorotan(bahan, per_id, status, lewat)
    return {
        "versi": VERSI,
        "jenis": JENIS,
        "judul": judul_bulanan(ps, pe),
        "periode": {"mulai": ps.isoformat(), "akhir": pe.isoformat(), "gajian": bahan.payday},
        "angka_per": bahan.angka_per.isoformat(),
        "penerima": {"nama": bahan.penerima_nama, "rumah": bahan.rumah_nama},
        "ringkasan": ringkasan,
        "amplop": [_baris_amplop(a, s, lw) for a, s, lw in zip(bahan.amplop, status, lewat)],
        "banding": banding,
        "harian": harian,
        "hari_terboros": hari_terboros,
        "terbesar": _terbesar(bahan, per_id),
        "langganan": _langganan(bahan, per_id),
        "sorotan": sorotan,
        "mutasi": _mutasi(bahan, per_id),
        "email": {
            "persen_terpakai": ringkasan["persen_terpakai"],
            "amplop_aman": status.count("aman"),
            "amplop_lewat_batas": status.count("lewat_batas"),
            "tren_persen": banding["persen_perubahan"],
            "sorotan": teks_sorotan(
                sorotan["beruntun_terpanjang"], len(sorotan["amplop_aman"]), sorotan["hari_mencatat"]
            ),
        },
    }


def _periksa(bahan: BahanLaporan) -> dict[str, AmplopPeriode]:
    """Memeriksa syarat bahan yang bila dilanggar membuat `data` keliru tanpa terlihat (periode pembanding
    bergeser) atau gagal dengan `KeyError` yang tidak menjelaskan apa-apa; mengembalikan amplop menurut id."""
    per_id = {a.id: a for a in bahan.amplop}
    if len(bahan.terpakai_lalu_total) != JUMLAH_PERIODE_BANDING:
        raise ValueError(
            f"terpakai_lalu_total harus berisi {JUMLAH_PERIODE_BANDING} periode, "
            f"bukan {len(bahan.terpakai_lalu_total)}"
        )
    for a in bahan.amplop:
        if len(a.terpakai_lalu) != JUMLAH_PERIODE_BANDING:
            raise ValueError(
                f"amplop {a.id}: terpakai_lalu harus berisi {JUMLAH_PERIODE_BANDING} periode, "
                f"bukan {len(a.terpakai_lalu)}"
            )
    for t in bahan.transaksi:
        if t.amplop_id not in per_id:
            raise ValueError(f"transaksi {t.id} menunjuk amplop {t.amplop_id} yang tidak ada di bahan")
    for g in bahan.target:
        if g.amplop_id not in per_id:
            raise ValueError(f"target {g.nama!r} menunjuk amplop {g.amplop_id} yang tidak ada di bahan")
    return per_id


def _jumlah(nilai) -> Decimal:
    """Jumlah `Decimal`; mulai dari `Decimal(0)` karena `sum([])` adalah int 0 dan `uang(0)` menolaknya."""
    return sum(nilai, _NOL)


def _uang_atau_none(nilai: Decimal | None) -> str | None:
    return None if nilai is None else uang(nilai)


def _belanja_per_amplop_hari(transaksi: list[TransaksiPeriode]) -> dict[str, dict[date, Decimal]]:
    """Belanja per amplop per tanggal, semua transaksi termasuk penyesuaian (himpunan yang sama dengan `terpakai`)."""
    hasil: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for t in transaksi:
        per_hari = hasil[t.amplop_id]
        per_hari[t.tanggal] = per_hari.get(t.tanggal, _NOL) + t.jumlah
    return hasil


def _ringkasan(bahan: BahanLaporan, total_terpakai: Decimal) -> dict:
    """Jumlah uang (`pemasukan`, `dialokasikan`, `terpakai`, `sisa`, `dibawa`) atas semua baris. `persen_terpakai`
    hanya atas amplop selain tabungan, di pembilang dan penyebut: saldo tabungan yang besar dan tak dibelanjakan
    bukan jatah yang dihabiskan, dan tanpa pengecualian ini ia menenggelamkan persen amplop belanja."""
    amplop = bahan.amplop
    belanja = [a for a in amplop if not adalah_tabungan(a.tujuan)]
    return {
        "pemasukan": uang(_jumlah(p.jumlah for p in bahan.pemasukan)),
        "dialokasikan": uang(_jumlah(a.alokasi for a in amplop)),
        "terpakai": uang(total_terpakai),
        "sisa": uang(_jumlah(a.akhir for a in amplop)),
        "dibawa": uang(_jumlah(a.rollover for a in amplop)),
        "persen_terpakai": persen(_jumlah(a.terpakai for a in belanja), _jumlah(a.awal for a in belanja)),
    }


def _baris_amplop(a: AmplopPeriode, status: str, lewat: bool) -> dict:
    return {
        "id": a.id,
        "nama": a.nama,
        "emoji": a.emoji,
        "jenis": "pribadi" if a.pribadi else "bersama",
        "tujuan": a.tujuan,
        "awal": uang(a.awal),
        "alokasi": uang(a.alokasi),
        "terpakai": uang(a.terpakai),
        "akhir": uang(a.akhir),
        "rollover": uang(a.rollover),
        "status": status,
        "pernah_lewat_batas": lewat,
        "ditutup": bool(a.ditutup),
    }


def _banding(amplop: list[AmplopPeriode], total_lalu: list[Decimal | None], terpakai_sekarang: Decimal) -> dict:
    """Pembanding dengan periode lalu (p-1) dan rata-rata tiga periode. Total (`terpakai_lalu`, `terpakai_rata3`,
    dasar `persen_perubahan`) dari `total_lalu` = `bahan.terpakai_lalu_total`, yang meliputi semua amplop lingkup
    dan bukan hanya baris; rata-rata = rata-rata ketiga total itu (periode `None` tidak masuk pembagi), bukan
    jumlah rata-rata per amplop. `terpakai_sekarang` = jumlah `terpakai` baris. Angka per amplop dari
    `terpakai_lalu` barisnya sendiri."""
    lalu = total_lalu[-1]
    return {
        "terpakai_lalu": _uang_atau_none(lalu),
        "terpakai_rata3": _uang_atau_none(rata_rata(total_lalu)),
        "persen_perubahan": persen_perubahan(terpakai_sekarang, lalu),
        "amplop": [
            {
                "id": a.id,
                "terpakai_lalu": _uang_atau_none(a.terpakai_lalu[-1]),
                "terpakai_rata3": _uang_atau_none(rata_rata(a.terpakai_lalu)),
            }
            for a in amplop
        ],
    }


def _harian(bahan: BahanLaporan) -> tuple[list[dict], dict | None]:
    """Terpakai per hari untuk setiap hari di jendela (nol pun ditulis) dan hari terboros. Semua transaksi ikut,
    penyesuaian juga, sehingga jumlah harian = jumlah `terpakai` baris amplop."""
    per_hari: dict[date, Decimal] = {}
    for t in bahan.transaksi:
        per_hari[t.tanggal] = per_hari.get(t.tanggal, _NOL) + t.jumlah
    harian: list[dict] = []
    terboros: tuple[date, Decimal] | None = None
    for n in range((bahan.periode_akhir - bahan.periode_mulai).days + 1):
        hari = bahan.periode_mulai + timedelta(days=n)
        jumlah = per_hari.get(hari, _NOL)
        harian.append({"tanggal": hari.isoformat(), "terpakai": uang(jumlah)})
        # `>` ketat: hari bertotal sama yang lebih awal tetap menang; hari bertotal nol atau minus tak pernah boros.
        if jumlah > 0 and (terboros is None or jumlah > terboros[1]):
            terboros = (hari, jumlah)
    if terboros is None:
        return harian, None
    return harian, {"tanggal": terboros[0].isoformat(), "terpakai": uang(terboros[1])}


def _terbesar(bahan: BahanLaporan, per_id: dict[str, AmplopPeriode]) -> list[dict]:
    """Lima pengeluaran terbesar, penyesuaian tidak ikut; jumlah sama menurut urutan masukan (`reverse=True`
    pada `sorted` tetap stabil)."""
    biasa = [t for t in bahan.transaksi if not t.penyesuaian]
    terbesar = sorted(biasa, key=lambda t: t.jumlah, reverse=True)[:JUMLAH_TERBESAR]
    return [
        {
            "tanggal": t.tanggal.isoformat(),
            "amplop": per_id[t.amplop_id].nama,
            "keterangan": t.keterangan,
            "jumlah": uang(t.jumlah),
            "pencatat": t.pencatat,
        }
        for t in terbesar
    ]


def _nama_tagihan(keterangan: str) -> str:
    """Keterangan tanpa penanda tombol Bayar di awalnya; keterangan tersamar atau tanpa penanda dipakai apa adanya."""
    if keterangan.startswith(PENANDA_TAGIHAN):
        return keterangan[len(PENANDA_TAGIHAN):]
    return keterangan


def _langganan(bahan: BahanLaporan, per_id: dict[str, AmplopPeriode]) -> dict:
    """`terbayar`: transaksi bertanda `tagihan` (bukan tebakan dari teks), menurut tanggal. `jatuh_tempo`: tagihan
    periode berikutnya menurut tanggal; amplop di luar bahan tetap tampil dengan nama amplop null."""
    terbayar = sorted((t for t in bahan.transaksi if t.tagihan), key=lambda t: t.tanggal)
    jatuh_tempo = sorted(bahan.tagihan_berikut, key=lambda b: b.tanggal)
    return {
        "terbayar": [
            {
                "tanggal": t.tanggal.isoformat(),
                "nama": _nama_tagihan(t.keterangan),
                "amplop": per_id[t.amplop_id].nama,
                "jumlah": uang(t.jumlah),
            }
            for t in terbayar
        ],
        "jatuh_tempo": [
            {
                "tanggal": b.tanggal.isoformat(),
                "nama": b.nama,
                "amplop": per_id[b.amplop_id].nama if b.amplop_id in per_id else None,
                "jumlah": uang(b.jumlah),
            }
            for b in jatuh_tempo
        ],
    }


def _sorotan(bahan: BahanLaporan, per_id: dict[str, AmplopPeriode], status: list[str], lewat: list[bool]) -> dict:
    """Hari mencatat dan beruntun dihitung dari catatan penerima sendiri (bukan anggota lain, bukan penyesuaian).
    `amplop_aman`: nama amplop yang statusnya bukan tabungan, kosong, atau lewat_batas dan saldo hariannya tak
    pernah di bawah nol. Status lewat_batas dikeluarkan juga walau saldo hariannya tak pernah negatif: itu hanya
    terjadi pada bahan yang tidak konsisten, dan amplop yang berakhir negatif tak boleh dipuji."""
    catatan = [t.tanggal for t in bahan.transaksi if t.milik_penerima and not t.penyesuaian]
    return {
        "hari_mencatat": len(set(catatan)),
        "beruntun_terpanjang": beruntun_terpanjang(catatan),
        "streak_saat_ini": bahan.streak_saat_ini,
        "amplop_aman": [
            a.nama for a, s, lw in zip(bahan.amplop, status, lewat) if s not in _STATUS_BUKAN_AMAN and not lw
        ],
        "target": [
            {
                "nama": g.nama,
                "target": uang(g.target),
                "terkumpul": uang(per_id[g.amplop_id].akhir),
                "persen": persen(per_id[g.amplop_id].akhir, g.target),
            }
            for g in bahan.target
        ],
    }


def _mutasi(bahan: BahanLaporan, per_id: dict[str, AmplopPeriode]) -> list[dict]:
    """Pemasukan (`masuk`, tanpa amplop, pencatat = penerima) lalu transaksi (`keluar`), diurutkan stabil menurut
    tanggal: di hari yang sama pemasukan lebih dulu, lalu transaksi menurut urutan masukan."""
    baris = [
        (p.tanggal, {
            "tanggal": p.tanggal.isoformat(),
            "arah": "masuk",
            "amplop": None,
            "keterangan": p.keterangan,
            "jumlah": uang(p.jumlah),
            "pencatat": bahan.penerima_nama,
            "penyesuaian": False,
        })
        for p in bahan.pemasukan
    ] + [
        (t.tanggal, {
            "tanggal": t.tanggal.isoformat(),
            "arah": "keluar",
            "amplop": per_id[t.amplop_id].nama,
            "keterangan": t.keterangan,
            "jumlah": uang(t.jumlah),
            "pencatat": t.pencatat,
            "penyesuaian": bool(t.penyesuaian),
        })
        for t in bahan.transaksi
    ]
    baris.sort(key=lambda b: b[0])
    return [b[1] for b in baris]
