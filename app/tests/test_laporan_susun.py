"""Penyusun `data` v1 laporan bulanan (tahap 1, Task 3; spec bagian 2c): bahan biasa (dataclass) menjadi kamus JSON
yang dibekukan di `reports.data`.

Fungsinya murni (tanpa DB atau I/O), jadi bahan dirakit tangan dan harapan ditulis tangan sebagai literal, tidak
dihitung oleh fungsi yang diuji. Perbandingan antarbagian `data` hanya ada di tes konsistensi (jumlah baris =
ringkasan, mutasi keluar per amplop = terpakai, jumlah harian = terpakai), karena itu yang diminta spec; tes itu
tetap ditambatkan ke literal. Header env dipasang seperti modul tes lain walau modul ini tidak menyentuh DB.
Run: python -m unittest app.tests.test_laporan_susun -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import copy
import dataclasses
import json
import random
import re
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from app.services.laporan import hitung, susun
from app.services.laporan.susun import (
    AmplopPeriode, BahanLaporan, PemasukanPeriode, TagihanBerikut, TargetTabungan, TransaksiPeriode,
    ada_aktivitas, susun_bulanan,
)

D = Decimal
PS, PE = date(2026, 10, 1), date(2026, 10, 31)
UANG = re.compile(r"^-?\d+\.\d{2}$")
# Id user pencatat (Ruling R15: dibekukan bersama baris, tidak pernah ditampilkan). Bentuk UUID seperti yang ditulis
# pemuat (`str(user.id)`), supaya tes PDF bisa memastikan tidak ada id seperti ini yang tercetak.
ID_ANI = "0a0a0a0a-0000-4000-8000-00000000a111"
ID_BUDI = "0b0b0b0b-0000-4000-8000-00000000b222"
ID_CITRA = "0c0c0c0c-0000-4000-8000-00000000c333"
ID_PENCATAT = {"Ani": ID_ANI, "Budi": ID_BUDI, "Citra": ID_CITRA}


def d(n: int) -> date:
    """Tanggal n di Oktober 2026."""
    return date(2026, 10, n)


def amplop(**ubah) -> AmplopPeriode:
    """Amplop "Kebutuhan" (bersama, aman); `ubah` menimpa kolom mana pun."""
    nilai = dict(
        id="env-s", nama="Kebutuhan", emoji="🍜", pribadi=False, tujuan="expense",
        awal=D(1_000_000), alokasi=D(1_000_000), terpakai=D(600_000), akhir=D(400_000), rollover=D(400_000),
        ditutup=False, alokasi_per_hari={d(1): D(1_000_000)},
        terpakai_lalu=[D(400_000), D(500_000), D(700_000)],
    )
    nilai.update(ubah)
    return AmplopPeriode(**nilai)


def amplop_kecil(id: str, nama: str, awal, terpakai, **ubah) -> AmplopPeriode:
    """Amplop konsisten untuk tes terfokus: seluruh saldo awal (rollover masuk nol) dialokasikan 1 Okt,
    akhir = awal - terpakai, rollover = akhir."""
    awal, terpakai = D(awal), D(terpakai)
    return amplop(
        id=id, nama=nama, awal=awal, alokasi=awal, terpakai=terpakai, akhir=awal - terpakai,
        rollover=awal - terpakai, alokasi_per_hari={d(1): awal}, **ubah,
    )


def txn(**ubah) -> TransaksiPeriode:
    """Satu transaksi 10.000 di amplop "env-s" pada 2 Okt yang dicatat penerima; `ubah` menimpa kolom mana pun.
    Tanpa `pencatat_id` di `ubah`, id pencatat diambil dari namanya (`ID_PENCATAT`), seperti pemuat yang membaca
    nama dan id dari baris `users` yang sama."""
    nilai = dict(
        id="t", amplop_id="env-s", tanggal=d(2), jumlah=D(10_000), keterangan="Makan", pencatat="Ani",
        milik_penerima=True, penyesuaian=False, tagihan=False,
    )
    nilai.update(ubah)
    nilai.setdefault("pencatat_id", ID_PENCATAT.get(nilai["pencatat"]))
    return TransaksiPeriode(**nilai)


def _amplop_dasar() -> list[AmplopPeriode]:
    return [
        amplop(),
        amplop(
            id="env-p", nama="Jajan", emoji="🍿", pribadi=True, awal=D(300_000), alokasi=D(250_000),
            terpakai=D(240_000), akhir=D(60_000), rollover=D(0), alokasi_per_hari={d(1): D(250_000)},
            terpakai_lalu=[None, D(200_000), D(300_000)],
        ),
        amplop(
            id="env-t", nama="Dana darurat", emoji="🏦", tujuan="saving", awal=D(500_000), alokasi=D(100_000),
            terpakai=D(0), akhir=D(500_000), rollover=D(500_000), alokasi_per_hari={d(1): D(100_000)},
            terpakai_lalu=[D(0), D(0), D(0)],
        ),
    ]


def _transaksi_dasar() -> list[TransaksiPeriode]:
    return [
        txn(id="t1", amplop_id="env-s", tanggal=d(2), jumlah=D(150_000), keterangan="Belanja bulanan"),
        txn(id="t2", amplop_id="env-s", tanggal=d(3), jumlah=D(50_000), keterangan="Makan siang",
            pencatat="Budi", milik_penerima=False),
        txn(id="t3", amplop_id="env-p", tanggal=d(4), jumlah=D(36_000), keterangan="Kopi"),
        txn(id="t4", amplop_id="env-s", tanggal=d(10), jumlah=D(250_000), keterangan="Belanja mingguan"),
        txn(id="t5", amplop_id="env-s", tanggal=d(12), jumlah=D(100_000), keterangan="Listrik"),
        txn(id="t6", amplop_id="env-p", tanggal=d(12), jumlah=D(54_000), keterangan="🔄 Netflix", tagihan=True),
        txn(id="t7", amplop_id="env-p", tanggal=d(20), jumlah=D(20_000), keterangan="Parkir"),
        txn(id="t8", amplop_id="env-p", tanggal=d(25), jumlah=D(130_000), keterangan="Penyesuaian saldo",
            penyesuaian=True),
        txn(id="t9", amplop_id="env-s", tanggal=d(31), jumlah=D(50_000), keterangan="Makan malam",
            pencatat="Budi", milik_penerima=False),
    ]


def bahan(**ubah) -> BahanLaporan:
    """Bahan dasar, selalu objek baru: Ani, Oktober 2026 (gajian 1, jendela 1-31 Okt), tiga amplop:

        Kebutuhan (bersama)    awal 1.000.000  terpakai 600.000  akhir 400.000  dibawa 400.000  -> aman (60%)
        Jajan (pribadi)        awal   300.000  terpakai 240.000  akhir  60.000  dibawa       0  -> hampir_habis (80%)
        Dana darurat (saving)  awal   500.000  terpakai       0  akhir 500.000  dibawa 500.000  -> tabungan

    Sembilan transaksi yang jumlahnya persis sama dengan `terpakai` tiap amplop (termasuk satu penyesuaian saldo
    130.000 di Jajan), dua pemasukan, dua tagihan periode berikut, satu target tabungan, streak 3, dan total
    lingkup periode lalu `terpakai_lalu_total` 400.000, 700.000, 1.000.000 (= jumlah `terpakai_lalu` ketiga baris,
    karena seluruh lingkup bahan dasar adalah baris; tes pembanding mengisinya sendiri).
    """
    nilai = dict(
        penerima_nama="Ani", penerima_id=ID_ANI, rumah_nama="Rumah Ani", periode_mulai=PS, periode_akhir=PE, payday=1,
        angka_per=date(2026, 11, 1),
        amplop=_amplop_dasar(), transaksi=_transaksi_dasar(),
        pemasukan=[PemasukanPeriode(d(2), D(5_000_000), "Gaji"), PemasukanPeriode(d(15), D(500_000), "Freelance")],
        tagihan_berikut=[
            TagihanBerikut(date(2026, 11, 5), "Listrik", "env-s", D(100_000)),
            TagihanBerikut(date(2026, 11, 12), "Netflix", "env-p", D(54_000)),
        ],
        target=[TargetTabungan("Darurat 6 bulan", "env-t", D(1_000_000))],
        streak_saat_ini=3,
        terpakai_lalu_total=[D(400_000), D(700_000), D(1_000_000)],
    )
    nilai.update(ubah)
    return BahanLaporan(**nilai)


def bahan_kosong(**ubah) -> BahanLaporan:
    """Bahan tanpa amplop, transaksi, pemasukan, tagihan, dan target, dan tanpa angka periode lalu di lingkup."""
    kosong = dict(
        amplop=[], transaksi=[], pemasukan=[], tagihan_berikut=[], target=[], terpakai_lalu_total=[None, None, None],
    )
    return bahan(**{**kosong, **ubah})


def semua_uang(nilai, kecuali: str | None = None) -> list[str]:
    """Semua teks uang (dua desimal) di struktur JSON; `kecuali` melewati satu kunci tingkat atas."""
    if isinstance(nilai, dict):
        return [u for k, v in nilai.items() if k != kecuali for u in semua_uang(v)]
    if isinstance(nilai, list):
        return [u for v in nilai for u in semua_uang(v)]
    return [nilai] if isinstance(nilai, str) and UANG.match(nilai) else []


# ---------------------------------------------------------------------------------------------------------------
# Harapan tulis tangan untuk bahan dasar (angka diturunkan di atas kertas, bukan dari kode):
#   Σ awal 1.800.000; Σ alokasi 1.350.000; Σ terpakai 840.000; Σ akhir 960.000; Σ dibawa 900.000;
#   persen terpakai hanya atas amplop selain tabungan (Dana darurat, saving, keluar dari pembilang dan penyebut):
#   Σ terpakai 840.000 / Σ awal (1.000.000 + 300.000) = 64,6 -> 65 (bila tabungan ikut: 840/1800 = 46,67 -> 47).
#   Terpakai periode lalu (Jul, Agu, Sep) per amplop:
#   Kebutuhan 400/500/700 rb, Jajan -/200/300 rb, Dana darurat 0/0/0. Total lingkup (`terpakai_lalu_total`) 400, 700,
#   1.000 rb: sama dengan jumlah baris karena seluruh lingkup bahan dasar adalah baris;
#   rata-rata 3 periode = (400 + 700 + 1000)/3 = 700 rb; 840 vs 1.000 -> -16%.
# ---------------------------------------------------------------------------------------------------------------
HARIAN_DASAR = {
    2: "150000.00", 3: "50000.00", 4: "36000.00", 10: "250000.00", 12: "154000.00",
    20: "20000.00", 25: "130000.00", 31: "50000.00",
}


def _mutasi(tanggal, arah, amplop_nama, keterangan, jumlah, pencatat, penyesuaian=False) -> dict:
    """Satu baris mutasi; `pencatat_id` = id pencatat menurut namanya (`ID_PENCATAT`)."""
    return {
        "tanggal": tanggal, "arah": arah, "amplop": amplop_nama, "keterangan": keterangan, "jumlah": jumlah,
        "pencatat": pencatat, "pencatat_id": ID_PENCATAT[pencatat], "penyesuaian": penyesuaian,
    }


def data_dasar() -> dict:
    return {
        "versi": 1,
        "jenis": "bulanan",
        "judul": "Laporan Oktober 2026",
        "periode": {"mulai": "2026-10-01", "akhir": "2026-10-31", "gajian": 1},
        "angka_per": "2026-11-01",
        "penerima": {"nama": "Ani", "rumah": "Rumah Ani"},
        "ringkasan": {
            "pemasukan": "5500000.00", "dialokasikan": "1350000.00", "terpakai": "840000.00",
            "sisa": "960000.00", "dibawa": "900000.00", "persen_terpakai": 65,
        },
        "amplop": [
            {"id": "env-s", "nama": "Kebutuhan", "emoji": "🍜", "jenis": "bersama", "tujuan": "expense",
             "awal": "1000000.00", "alokasi": "1000000.00", "terpakai": "600000.00", "akhir": "400000.00",
             "rollover": "400000.00", "status": "aman", "pernah_lewat_batas": False, "ditutup": False},
            {"id": "env-p", "nama": "Jajan", "emoji": "🍿", "jenis": "pribadi", "tujuan": "expense",
             "awal": "300000.00", "alokasi": "250000.00", "terpakai": "240000.00", "akhir": "60000.00",
             "rollover": "0.00", "status": "hampir_habis", "pernah_lewat_batas": False, "ditutup": False},
            {"id": "env-t", "nama": "Dana darurat", "emoji": "🏦", "jenis": "bersama", "tujuan": "saving",
             "awal": "500000.00", "alokasi": "100000.00", "terpakai": "0.00", "akhir": "500000.00",
             "rollover": "500000.00", "status": "tabungan", "pernah_lewat_batas": False, "ditutup": False},
        ],
        "banding": {
            "terpakai_lalu": "1000000.00", "terpakai_rata3": "700000.00", "persen_perubahan": -16,
            "amplop": [
                {"id": "env-s", "terpakai_lalu": "700000.00", "terpakai_rata3": "533333.33"},
                {"id": "env-p", "terpakai_lalu": "300000.00", "terpakai_rata3": "250000.00"},
                {"id": "env-t", "terpakai_lalu": "0.00", "terpakai_rata3": "0.00"},
            ],
        },
        "harian": [{"tanggal": f"2026-10-{n:02d}", "terpakai": HARIAN_DASAR.get(n, "0.00")} for n in range(1, 32)],
        "hari_terboros": {"tanggal": "2026-10-10", "terpakai": "250000.00"},
        "terbesar": [
            {"tanggal": "2026-10-10", "amplop": "Kebutuhan", "keterangan": "Belanja mingguan",
             "jumlah": "250000.00", "pencatat": "Ani", "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-02", "amplop": "Kebutuhan", "keterangan": "Belanja bulanan",
             "jumlah": "150000.00", "pencatat": "Ani", "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-12", "amplop": "Kebutuhan", "keterangan": "Listrik",
             "jumlah": "100000.00", "pencatat": "Ani", "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-12", "amplop": "Jajan", "keterangan": "🔄 Netflix",
             "jumlah": "54000.00", "pencatat": "Ani", "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-03", "amplop": "Kebutuhan", "keterangan": "Makan siang",
             "jumlah": "50000.00", "pencatat": "Budi", "pencatat_id": ID_BUDI},
        ],
        "langganan": {
            "terbayar": [{"tanggal": "2026-10-12", "nama": "Netflix", "amplop": "Jajan", "jumlah": "54000.00",
                          "pencatat_id": ID_ANI}],
            "jatuh_tempo": [
                {"tanggal": "2026-11-05", "nama": "Listrik", "amplop": "Kebutuhan", "jumlah": "100000.00"},
                {"tanggal": "2026-11-12", "nama": "Netflix", "amplop": "Jajan", "jumlah": "54000.00"},
            ],
        },
        "sorotan": {
            "hari_mencatat": 5, "beruntun_terpanjang": 1, "streak_saat_ini": 3,
            "amplop_aman": ["Kebutuhan", "Jajan"],
            "target": [{"nama": "Darurat 6 bulan", "target": "1000000.00", "terkumpul": "500000.00", "persen": 50}],
        },
        "mutasi": [
            _mutasi("2026-10-02", "masuk", None, "Gaji", "5000000.00", "Ani"),
            _mutasi("2026-10-02", "keluar", "Kebutuhan", "Belanja bulanan", "150000.00", "Ani"),
            _mutasi("2026-10-03", "keluar", "Kebutuhan", "Makan siang", "50000.00", "Budi"),
            _mutasi("2026-10-04", "keluar", "Jajan", "Kopi", "36000.00", "Ani"),
            _mutasi("2026-10-10", "keluar", "Kebutuhan", "Belanja mingguan", "250000.00", "Ani"),
            _mutasi("2026-10-12", "keluar", "Kebutuhan", "Listrik", "100000.00", "Ani"),
            _mutasi("2026-10-12", "keluar", "Jajan", "🔄 Netflix", "54000.00", "Ani"),
            _mutasi("2026-10-15", "masuk", None, "Freelance", "500000.00", "Ani"),
            _mutasi("2026-10-20", "keluar", "Jajan", "Parkir", "20000.00", "Ani"),
            _mutasi("2026-10-25", "keluar", "Jajan", "Penyesuaian saldo", "130000.00", "Ani", penyesuaian=True),
            _mutasi("2026-10-31", "keluar", "Kebutuhan", "Makan malam", "50000.00", "Budi"),
        ],
        "email": {
            "persen_terpakai": 65, "amplop_aman": 1, "amplop_lewat_batas": 0, "tren_persen": -16,
            "sorotan": "2 amplop tidak pernah lewat batas",
        },
    }


class BentukDataTests(unittest.TestCase):
    def test_data_bahan_dasar_sama_dengan_harapan_tulis_tangan(self):
        self.assertEqual(susun_bulanan(bahan()), data_dasar())

    def test_kunci_persis_di_setiap_tingkat(self):
        # Halaman, PDF, dan email hanya membaca kunci ini; kunci baru atau hilang harus terlihat di sini.
        data = susun_bulanan(bahan())
        self.assertEqual(set(data), {
            "versi", "jenis", "judul", "periode", "angka_per", "penerima", "ringkasan", "amplop", "banding",
            "harian", "hari_terboros", "terbesar", "langganan", "sorotan", "mutasi", "email",
        })
        self.assertEqual(set(data["periode"]), {"mulai", "akhir", "gajian"})
        self.assertEqual(set(data["penerima"]), {"nama", "rumah"})
        self.assertEqual(
            set(data["ringkasan"]),
            {"pemasukan", "dialokasikan", "terpakai", "sisa", "dibawa", "persen_terpakai"},
        )
        for baris in data["amplop"]:
            self.assertEqual(set(baris), {
                "id", "nama", "emoji", "jenis", "tujuan", "awal", "alokasi", "terpakai", "akhir", "rollover",
                "status", "pernah_lewat_batas", "ditutup",
            })
        self.assertEqual(set(data["banding"]), {"terpakai_lalu", "terpakai_rata3", "persen_perubahan", "amplop"})
        for baris in data["banding"]["amplop"]:
            self.assertEqual(set(baris), {"id", "terpakai_lalu", "terpakai_rata3"})
        for baris in data["harian"]:
            self.assertEqual(set(baris), {"tanggal", "terpakai"})
        self.assertEqual(set(data["hari_terboros"]), {"tanggal", "terpakai"})
        for baris in data["terbesar"]:
            self.assertEqual(set(baris), {"tanggal", "amplop", "keterangan", "jumlah", "pencatat", "pencatat_id"})
        self.assertEqual(set(data["langganan"]), {"terbayar", "jatuh_tempo"})
        # Terbayar = transaksi (punya pencatat, Ruling R15); jatuh tempo = langganan rumah, tanpa pencatat tersimpan.
        for bagian, kunci in [("terbayar", {"tanggal", "nama", "amplop", "jumlah", "pencatat_id"}),
                              ("jatuh_tempo", {"tanggal", "nama", "amplop", "jumlah"})]:
            self.assertTrue(data["langganan"][bagian])
            for baris in data["langganan"][bagian]:
                self.assertEqual(set(baris), kunci)
        self.assertEqual(
            set(data["sorotan"]),
            {"hari_mencatat", "beruntun_terpanjang", "streak_saat_ini", "amplop_aman", "target"},
        )
        for baris in data["sorotan"]["target"]:
            self.assertEqual(set(baris), {"nama", "target", "terkumpul", "persen"})
        for baris in data["mutasi"]:
            self.assertEqual(
                set(baris),
                {"tanggal", "arah", "amplop", "keterangan", "jumlah", "pencatat", "pencatat_id", "penyesuaian"},
            )
        self.assertEqual(
            set(data["email"]),
            {"persen_terpakai", "amplop_aman", "amplop_lewat_batas", "tren_persen", "sorotan"},
        )

    def test_bisa_diserialkan_json(self):
        for nama, isi in [("dasar", bahan()), ("kosong", bahan_kosong())]:
            with self.subTest(nama):
                data = susun_bulanan(isi)
                teks = json.dumps(data, allow_nan=False)
                # Bolak-balik JSON harus sama persis: tuple, set, Decimal, atau date yang lolos akan ketahuan.
                self.assertEqual(json.loads(teks), data)
                self._hanya_tipe_json(data, "data")

    def _hanya_tipe_json(self, nilai, jalur):
        if isinstance(nilai, dict):
            for kunci, isi in nilai.items():
                self.assertIs(type(kunci), str, jalur)
                self._hanya_tipe_json(isi, f"{jalur}.{kunci}")
        elif isinstance(nilai, list):
            for i, isi in enumerate(nilai):
                self._hanya_tipe_json(isi, f"{jalur}[{i}]")
        else:
            # float tidak boleh ada: uang adalah teks desimal, persen adalah int.
            self.assertIn(type(nilai), (str, int, bool, type(None)), jalur)

    def test_versi_jenis_dan_judul(self):
        data = susun_bulanan(bahan())
        self.assertEqual((data["versi"], data["jenis"], data["judul"]), (1, "bulanan", "Laporan Oktober 2026"))
        self.assertIs(type(data["versi"]), int)

    def test_periode_bukan_bulan_kalender_dan_lintas_tahun(self):
        kasus = [
            ("gajian 25", date(2026, 9, 25), d(24), 25, f"Laporan 25 Sep {chr(0x2013)} 24 Okt 2026"),
            ("lintas tahun", date(2026, 12, 25), date(2027, 1, 24), 25,
             f"Laporan 25 Des 2026 {chr(0x2013)} 24 Jan 2027"),
            ("Februari kabisat", date(2028, 2, 1), date(2028, 2, 29), 1, "Laporan Februari 2028"),
            # Gajian 31 jatuh di 28 Feb pada bulan pendek: tanggal gajian rumah (31) bukan hari awal periode (28).
            ("gajian 31 di Februari", date(2026, 2, 28), date(2026, 3, 30), 31,
             f"Laporan 28 Feb {chr(0x2013)} 30 Mar 2026"),
        ]
        for nama, ps, pe, gajian, judul in kasus:
            with self.subTest(nama):
                data = susun_bulanan(bahan_kosong(periode_mulai=ps, periode_akhir=pe, payday=gajian))
                self.assertEqual(data["judul"], judul)
                self.assertEqual(
                    data["periode"], {"mulai": ps.isoformat(), "akhir": pe.isoformat(), "gajian": gajian}
                )
                self.assertIs(type(data["periode"]["gajian"]), int)

    def test_bahan_kosong_menghasilkan_data_sah_tanpa_angka(self):
        data = susun_bulanan(bahan_kosong())
        self.assertEqual(data["ringkasan"], {
            "pemasukan": "0.00", "dialokasikan": "0.00", "terpakai": "0.00", "sisa": "0.00", "dibawa": "0.00",
            "persen_terpakai": None,
        })
        self.assertEqual(data["amplop"], [])
        self.assertEqual(
            data["banding"], {"terpakai_lalu": None, "terpakai_rata3": None, "persen_perubahan": None, "amplop": []}
        )
        self.assertEqual(len(data["harian"]), 31)
        self.assertTrue(all(h["terpakai"] == "0.00" for h in data["harian"]))
        self.assertIsNone(data["hari_terboros"])
        self.assertEqual(data["terbesar"], [])
        self.assertEqual(data["langganan"], {"terbayar": [], "jatuh_tempo": []})
        self.assertEqual(data["sorotan"], {
            "hari_mencatat": 0, "beruntun_terpanjang": 0, "streak_saat_ini": 3, "amplop_aman": [], "target": [],
        })
        self.assertEqual(data["mutasi"], [])
        self.assertEqual(data["email"], {
            "persen_terpakai": None, "amplop_aman": 0, "amplop_lewat_batas": 0, "tren_persen": None,
            "sorotan": "Siap untuk periode berikutnya",
        })


class RingkasanTests(unittest.TestCase):
    def test_ringkasan_sama_dengan_jumlah_baris(self):
        data = susun_bulanan(bahan())
        baris, ringkasan = data["amplop"], data["ringkasan"]
        for kunci_ringkasan, kunci_baris in [
            ("dialokasikan", "alokasi"), ("terpakai", "terpakai"), ("sisa", "akhir"), ("dibawa", "rollover"),
        ]:
            with self.subTest(kunci_ringkasan):
                self.assertEqual(
                    Decimal(ringkasan[kunci_ringkasan]), sum((Decimal(b[kunci_baris]) for b in baris), D(0))
                )
        masuk = sum((Decimal(m["jumlah"]) for m in data["mutasi"] if m["arah"] == "masuk"), D(0))
        self.assertEqual(Decimal(ringkasan["pemasukan"]), masuk)
        # Ditambatkan ke literal tulis tangan supaya dua sisi yang salah bersama tidak lolos.
        self.assertEqual(ringkasan, {
            "pemasukan": "5500000.00", "dialokasikan": "1350000.00", "terpakai": "840000.00",
            "sisa": "960000.00", "dibawa": "900000.00", "persen_terpakai": 65,
        })

    def test_sisa_dan_dibawa_berbeda_bila_ada_amplop_tidak_berguling(self):
        # Jajan tidak berguling: akhir 60.000 tidak dibawa. sisa = Σ akhir, dibawa = Σ rollover.
        ringkasan = susun_bulanan(bahan())["ringkasan"]
        self.assertEqual((ringkasan["sisa"], ringkasan["dibawa"]), ("960000.00", "900000.00"))

    def test_dibawa_ikut_menghitung_rollover_negatif(self):
        isi = bahan(amplop=[
            amplop(id="a", nama="A", rollover=D(400_000)),
            amplop(id="b", nama="B", rollover=D(-50_000)),
        ], transaksi=[], target=[], tagihan_berikut=[])
        self.assertEqual(susun_bulanan(isi)["ringkasan"]["dibawa"], "350000.00")

    def test_persen_terpakai_dibulatkan_setengah_ke_atas_dan_tanpa_dasar_none(self):
        kasus = [
            ("12,5 jadi 13", D(800), D(100), 13),
            ("tidak dibatasi 100", D(100), D(150), 150),
            ("terpakai nol adalah 0, bukan None", D(100), D(0), 0),
            ("tanpa saldo awal tidak ada persen", D(0), D(0), None),
        ]
        for nama, awal, terpakai, diharapkan in kasus:
            with self.subTest(nama):
                isi = bahan_kosong(amplop=[amplop_kecil("env-s", "Kebutuhan", awal, terpakai)])
                data = susun_bulanan(isi)
                self.assertEqual(data["ringkasan"]["persen_terpakai"], diharapkan)
                self.assertEqual(data["email"]["persen_terpakai"], diharapkan)

    def test_persen_terpakai_tidak_menghitung_amplop_tabungan(self):
        # Ruling R5: amplop tabungan (saving, sinking_fund) keluar dari pembilang DAN penyebut. Saldo tabungan yang
        # besar tidak boleh menenggelamkan persen amplop belanja; utang dan pengeluaran biasa tetap dihitung.
        tabungan = amplop_kecil("t", "Dana", 10_000_000, 0, tujuan="saving")
        belanja = amplop_kecil("s", "Belanja", 1_000, 650)
        kasus = [
            ("saving besar di samping amplop belanja", [tabungan, belanja], 65),
            ("urutan baris tidak berpengaruh", [belanja, tabungan], 65),
            ("sinking_fund juga tabungan",
             [amplop_kecil("f", "Servis", 10_000_000, 0, tujuan="sinking_fund"), belanja], 65),
            ("pengeluaran dari tabungan tidak masuk pembilang",
             [amplop_kecil("t", "Dana", 10_000_000, 2_000_000, tujuan="saving"), belanja], 65),
            ("utang bukan tabungan", [tabungan, amplop_kecil("u", "Cicilan", 1_000, 650, tujuan="debt")], 65),
            ("dua tabungan dan dua amplop belanja",
             [amplop_kecil("t", "Dana", 5_000_000, 100, tujuan="saving"),
              amplop_kecil("f", "Servis", 5_000_000, 0, tujuan="sinking_fund"),
              amplop_kecil("a", "A", 400, 100), amplop_kecil("b", "B", 600, 550)], 65),
            ("semua tabungan: tanpa dasar",
             [amplop_kecil("t", "Dana", 100, 0, tujuan="saving"),
              amplop_kecil("f", "Servis", 50, 20, tujuan="sinking_fund")], None),
            ("saldo awal amplop belanja nol walau tabungan besar",
             [amplop_kecil("t", "Dana", 1_000_000, 0, tujuan="saving"), amplop_kecil("k", "Kosong", 0, 0)], None),
        ]
        for nama, baris, diharapkan in kasus:
            with self.subTest(nama):
                data = susun_bulanan(bahan_kosong(amplop=baris))
                self.assertEqual(data["ringkasan"]["persen_terpakai"], diharapkan)
                self.assertEqual(data["email"]["persen_terpakai"], diharapkan)

    def test_jumlah_uang_ringkasan_tetap_atas_semua_baris_termasuk_tabungan(self):
        # R5 hanya mengubah persen_terpakai. Tabungan 10.000.000 (terpakai 2.000.000) tetap masuk semua jumlah uang.
        isi = bahan_kosong(
            amplop=[amplop_kecil("t", "Dana", 10_000_000, 2_000_000, tujuan="saving"),
                    amplop_kecil("s", "Belanja", 1_000, 650)],
            pemasukan=[PemasukanPeriode(d(1), D(500), "Gaji")],
        )
        self.assertEqual(susun_bulanan(isi)["ringkasan"], {
            "pemasukan": "500.00", "dialokasikan": "10001000.00", "terpakai": "2000650.00",
            "sisa": "8000350.00", "dibawa": "8000350.00", "persen_terpakai": 65,
        })

    def test_tabungan_ditentukan_oleh_satu_daftar_tujuan_di_hitung(self):
        # Penyusun tidak punya daftar tujuan tabungan sendiri: ia memakai `hitung.adalah_tabungan`, yang juga dipakai
        # `status_amplop`. Daftar di hitung diganti sementara; status dan persen terpakai harus ikut berubah bersama.
        baris = [
            amplop_kecil("g", "Tujuan", 10_000, 0, tujuan="goal"),
            amplop_kecil("s", "Simpanan", 1_000, 650, tujuan="saving"),
        ]
        with self.subTest("daftar asli: saving tabungan, goal bukan"):
            data = susun_bulanan(bahan_kosong(amplop=baris))
            self.assertEqual([a["status"] for a in data["amplop"]], ["aman", "tabungan"])
            self.assertEqual(data["ringkasan"]["persen_terpakai"], 0)
        with self.subTest("daftar diganti: goal tabungan, saving bukan"):
            with patch.object(hitung, "_TUJUAN_TABUNGAN", ("goal",)):
                data = susun_bulanan(bahan_kosong(amplop=baris))
            self.assertEqual([a["status"] for a in data["amplop"]], ["tabungan", "aman"])
            self.assertEqual(data["ringkasan"]["persen_terpakai"], 65)

    def test_pemasukan_dijumlahkan_dari_pemasukan_bukan_dari_alokasi(self):
        isi = bahan(pemasukan=[
            PemasukanPeriode(d(1), D("1500000.50"), "Gaji"),
            PemasukanPeriode(d(9), D("250000.25"), "Jual barang"),
            PemasukanPeriode(d(9), D("0.01"), "Bunga"),
        ])
        self.assertEqual(susun_bulanan(isi)["ringkasan"]["pemasukan"], "1750000.76")


class AmplopTests(unittest.TestCase):
    def test_jenis_bersama_pribadi(self):
        data = susun_bulanan(bahan())
        self.assertEqual([a["jenis"] for a in data["amplop"]], ["bersama", "pribadi", "bersama"])
        isi = bahan_kosong(amplop=[amplop(pribadi=True), amplop(id="b", nama="B", pribadi=False)])
        self.assertEqual([a["jenis"] for a in susun_bulanan(isi)["amplop"]], ["pribadi", "bersama"])

    def test_urutan_amplop_mengikuti_bahan(self):
        isi = bahan_kosong(amplop=[amplop(id="z", nama="Z"), amplop(id="a", nama="A"), amplop(id="m", nama="M")])
        self.assertEqual([a["id"] for a in susun_bulanan(isi)["amplop"]], ["z", "a", "m"])

    def test_ditutup_dan_tujuan_diteruskan(self):
        isi = bahan_kosong(amplop=[
            amplop(id="a", nama="A", ditutup=True, tujuan="debt"),
            amplop(id="b", nama="B", ditutup=False, tujuan="sinking_fund"),
        ])
        baris = susun_bulanan(isi)["amplop"]
        self.assertEqual([(a["ditutup"], a["tujuan"]) for a in baris], [(True, "debt"), (False, "sinking_fund")])

    def test_status_dan_hitungan_email(self):
        # Saldo awal 100.000 per amplop; belanja 20.000, 70.000, dan 130.000 pada tanggal 3.
        isi = bahan_kosong(amplop=[
            amplop_kecil("a", "Aman", 100_000, 20_000),                        # 20%
            amplop_kecil("h", "Hampir", 100_000, 70_000),                      # tepat 70%
            amplop_kecil("l", "Lewat", 100_000, 130_000),                      # akhir -30.000
            amplop_kecil("t", "Tab", 100_000, 0, tujuan="sinking_fund"),
            amplop_kecil("k", "Kosong", 0, 0),
        ], transaksi=[
            txn(id="1", amplop_id="a", tanggal=d(3), jumlah=D(20_000)),
            txn(id="2", amplop_id="h", tanggal=d(3), jumlah=D(70_000)),
            txn(id="3", amplop_id="l", tanggal=d(3), jumlah=D(130_000)),
        ])
        data = susun_bulanan(isi)
        self.assertEqual(
            [(a["nama"], a["status"], a["pernah_lewat_batas"]) for a in data["amplop"]],
            [("Aman", "aman", False), ("Hampir", "hampir_habis", False), ("Lewat", "lewat_batas", True),
             ("Tab", "tabungan", False), ("Kosong", "kosong", False)],
        )
        self.assertEqual(data["sorotan"]["amplop_aman"], ["Aman", "Hampir"])
        self.assertEqual((data["email"]["amplop_aman"], data["email"]["amplop_lewat_batas"]), (1, 1))

    def test_hitungan_email_per_status(self):
        # Jumlah tiap status sengaja berbeda supaya menghitung status yang salah ketahuan.
        kasus = [
            ("tiga aman", [amplop_kecil(f"a{i}", f"A{i}", 100, 10) for i in range(3)], (3, 0)),
            ("dua lewat batas", [amplop_kecil(f"l{i}", f"L{i}", 100, 150) for i in range(2)], (0, 2)),
            ("hampir habis, tabungan, dan kosong tidak dihitung",
             [amplop_kecil("h", "H", 100, 80), amplop_kecil("t", "T", 100, 0, tujuan="saving"),
              amplop_kecil("k", "K", 0, 0)], (0, 0)),
        ]
        for nama, baris, (aman, lewat_batas) in kasus:
            with self.subTest(nama):
                email = susun_bulanan(bahan_kosong(amplop=baris))["email"]
                self.assertEqual((email["amplop_aman"], email["amplop_lewat_batas"]), (aman, lewat_batas))

    def test_status_dan_persen_memakai_saldo_awal_termasuk_rollover_bukan_alokasi(self):
        # Saldo awal 200.000 = rollover masuk 100.000 + alokasi 100.000. Terpakai 100.000 adalah 50% dari saldo awal
        # (aman) tetapi 100% dari alokasi saja (hampir habis); rollover masuk juga yang menutup belanja di awal.
        isi = bahan_kosong(
            amplop=[amplop(awal=D(200_000), alokasi=D(100_000), terpakai=D(100_000), akhir=D(100_000),
                           alokasi_per_hari={d(10): D(100_000)})],
            transaksi=[txn(tanggal=d(2), jumlah=D(100_000))],
        )
        data = susun_bulanan(isi)
        self.assertEqual(data["amplop"][0]["status"], "aman")
        self.assertIs(data["amplop"][0]["pernah_lewat_batas"], False)
        self.assertEqual(data["ringkasan"]["persen_terpakai"], 50)

    def test_bendera_dipaksa_jadi_bool_agar_json_bersih(self):
        # Pemuat bisa saja menyodorkan 1/0 (mis. dari SQLite mentah); keluaran tetap bool sungguhan.
        isi = bahan_kosong(amplop=[amplop(ditutup=1, pribadi=1)], transaksi=[txn(penyesuaian=1)])
        data = susun_bulanan(isi)
        self.assertIs(data["amplop"][0]["ditutup"], True)
        self.assertEqual(data["amplop"][0]["jenis"], "pribadi")
        self.assertIs(data["mutasi"][0]["penyesuaian"], True)

    def test_pernah_lewat_batas_dihitung_per_amplop_dengan_rollover_masuk_awal_dikurangi_alokasi(self):
        kasus = [
            # (nama, awal, alokasi, alokasi per hari, transaksi (hari, jumlah, penyesuaian), diharapkan)
            ("alokasi tiba sesudah belanja", 100_000, 100_000, {5: 100_000}, [(3, 40_000, False)], True),
            ("belanja sesudah alokasi", 100_000, 100_000, {5: 100_000}, [(7, 40_000, False)], False),
            ("rollover masuk negatif tanpa belanja", 50_000, 100_000, {10: 100_000}, [], True),
            ("rollover masuk negatif tertutup alokasi hari pertama", 50_000, 100_000, {1: 100_000}, [], False),
            ("penyesuaian dihitung sebagai belanja", 100_000, 100_000, {1: 100_000}, [(10, 150_000, True)], True),
            ("habis tepat nol di hari terakhir", 100_000, 100_000, {1: 100_000}, [(31, 100_000, False)], False),
            ("rollover masuk positif menutup belanja", 100_000, 0, {}, [(2, 100_000, False)], False),
        ]
        for nama, awal, alokasi, per_hari, belanja, diharapkan in kasus:
            with self.subTest(nama):
                terpakai = sum(j for _, j, _ in belanja)
                isi = bahan(
                    amplop=[amplop(
                        awal=D(awal), alokasi=D(alokasi), terpakai=D(terpakai), akhir=D(awal - terpakai),
                        alokasi_per_hari={d(h): D(j) for h, j in per_hari.items()},
                    )],
                    transaksi=[txn(id=str(i), tanggal=d(h), jumlah=D(j), penyesuaian=p)
                               for i, (h, j, p) in enumerate(belanja)],
                    target=[], tagihan_berikut=[],
                )
                self.assertIs(susun_bulanan(isi)["amplop"][0]["pernah_lewat_batas"], diharapkan)

    def test_belanja_amplop_lain_tidak_mengurangi_saldo(self):
        # Belanja 150.000 di A melampaui saldo A; B punya saldo yang sama tapi tidak belanja, jadi tetap aman.
        isi = bahan_kosong(
            amplop=[amplop_kecil("a", "A", 100_000, 150_000), amplop_kecil("b", "B", 100_000, 0)],
            transaksi=[txn(amplop_id="a", tanggal=d(10), jumlah=D(150_000))],
        )
        baris = susun_bulanan(isi)["amplop"]
        self.assertEqual([(a["nama"], a["pernah_lewat_batas"]) for a in baris], [("A", True), ("B", False)])

    def test_belanja_sehari_dari_beberapa_transaksi_dijumlahkan(self):
        # Dua belanja 60.000 di hari yang sama: masing-masing di bawah saldo 100.000, bersama-sama melampauinya.
        isi = bahan_kosong(
            amplop=[amplop_kecil("env-s", "Kebutuhan", 100_000, 120_000)],
            transaksi=[txn(id="1", tanggal=d(5), jumlah=D(60_000)), txn(id="2", tanggal=d(5), jumlah=D(60_000))],
        )
        self.assertTrue(susun_bulanan(isi)["amplop"][0]["pernah_lewat_batas"])


class BandingTests(unittest.TestCase):
    """Total pembanding berasal dari `terpakai_lalu_total` (semua amplop lingkup yang punya snapshot periode itu,
    juga yang bukan baris, Ruling R3); angka per amplop tetap dari `terpakai_lalu` tiap baris."""

    def test_banding_dan_tren(self):
        isi = bahan_kosong(
            amplop=[amplop_kecil("env-s", "Kebutuhan", 200, 88, terpakai_lalu=[None, None, D(100)])],
            terpakai_lalu_total=[None, None, D(100)],
        )
        data = susun_bulanan(isi)
        self.assertEqual(data["banding"], {
            "terpakai_lalu": "100.00", "terpakai_rata3": "100.00", "persen_perubahan": -12,
            "amplop": [{"id": "env-s", "terpakai_lalu": "100.00", "terpakai_rata3": "100.00"}],
        })
        self.assertEqual(data["email"]["tren_persen"], -12)

    def test_naik_dan_tetap(self):
        kasus = [
            ("naik 50 persen", D(150), 50), ("tetap", D(100), 0), ("turun separuh", D(50), -50),
            ("turun total", D(0), -100),
        ]
        for nama, sekarang, diharapkan in kasus:
            with self.subTest(nama):
                # Baris membawa angka p-1 lain (700.000, bawaan `amplop`): yang dipakai tren hanya total lingkup 100.
                isi = bahan_kosong(
                    amplop=[amplop_kecil("env-s", "Kebutuhan", 200, sekarang)],
                    terpakai_lalu_total=[None, None, D(100)],
                )
                data = susun_bulanan(isi)
                self.assertEqual(data["banding"]["persen_perubahan"], diharapkan)
                self.assertEqual(data["email"]["tren_persen"], diharapkan)

    def test_total_dari_terpakai_lalu_total_bukan_dari_jumlah_baris(self):
        # Baris hanyalah sebagian lingkup: periode lalu juga punya amplop yang sudah ditutup atau bukan baris lagi.
        # p-1 baris berjumlah 100 (60 + 40) tetapi total lingkup 150; terpakai sekarang 70 + 50 = 120.
        #   dari total:         (120 - 150) / 150 = -20%
        #   dari jumlah baris:  (120 - 100) / 100 = +20%   <- salah
        # Rata-rata tiga periode juga dari total: (100 + 200 + 150) / 3 = 150 (dari jumlah baris: 66,67).
        isi = bahan_kosong(
            amplop=[
                amplop_kecil("a", "A", 500, 70, terpakai_lalu=[D(10), D(20), D(60)]),
                amplop_kecil("b", "B", 500, 50, terpakai_lalu=[D(30), D(40), D(40)]),
            ],
            terpakai_lalu_total=[D(100), D(200), D("150")],
        )
        data = susun_bulanan(isi)
        self.assertEqual(data["banding"]["terpakai_lalu"], "150.00")
        self.assertEqual(data["banding"]["terpakai_rata3"], "150.00")
        self.assertEqual(data["banding"]["persen_perubahan"], -20)
        self.assertEqual(data["email"]["tren_persen"], -20)
        # Per amplop tetap dari baris masing-masing: A 60 dan (10 + 20 + 60) / 3 = 30; B 40 dan 110 / 3 = 36,67.
        self.assertEqual(data["banding"]["amplop"], [
            {"id": "a", "terpakai_lalu": "60.00", "terpakai_rata3": "30.00"},
            {"id": "b", "terpakai_lalu": "40.00", "terpakai_rata3": "36.67"},
        ])

    def test_lingkup_tanpa_baris_tetap_punya_total(self):
        # Seluruh belanja periode lalu terjadi di amplop yang bukan baris lagi: total tetap dilaporkan, sekarang 0
        # (tanpa baris), jadi turun 100%; tidak ada baris per amplop.
        isi = bahan_kosong(terpakai_lalu_total=[D(10), D(20), D(30)])
        banding = susun_bulanan(isi)["banding"]
        self.assertEqual(banding, {
            "terpakai_lalu": "30.00", "terpakai_rata3": "20.00", "persen_perubahan": -100, "amplop": [],
        })

    def test_rata_rata_dari_tiga_total_bukan_jumlah_rata_rata_per_amplop(self):
        # Bahan dasar: total lingkup 400.000, 700.000, 1.000.000 (Jajan tidak punya angka Jul tetapi dua periode lain
        # ada). Rata-rata = 700.000; jumlah rata-rata per amplop (533.333,33 + 250.000 + 0) akan salah: 783.333,33.
        banding = susun_bulanan(bahan())["banding"]
        self.assertEqual(banding["terpakai_rata3"], "700000.00")
        self.assertEqual(banding["terpakai_lalu"], "1000000.00")
        self.assertEqual(
            [(a["terpakai_lalu"], a["terpakai_rata3"]) for a in banding["amplop"]],
            [("700000.00", "533333.33"), ("300000.00", "250000.00"), ("0.00", "0.00")],
        )

    def test_periode_tanpa_satu_pun_angka_adalah_none(self):
        kasus = [
            ("semua None", [None, None, None], None, None, None),
            ("hanya periode tertua", [D(300), None, None], None, "300.00", None),
            ("hanya periode terakhir", [None, None, D(300)], "300.00", "300.00", -67),
            ("periode tengah kosong tidak masuk pembagi", [D(100), None, D(300)], "300.00", "200.00", -67),
        ]
        for nama, total, diharapkan_lalu, diharapkan_rata, diharapkan_persen in kasus:
            with self.subTest(nama):
                isi = bahan_kosong(
                    amplop=[amplop_kecil("env-s", "Kebutuhan", 200, 100, terpakai_lalu=[None, None, None])],
                    terpakai_lalu_total=total,
                )
                data = susun_bulanan(isi)
                self.assertEqual(data["banding"]["terpakai_lalu"], diharapkan_lalu)
                self.assertEqual(data["banding"]["terpakai_rata3"], diharapkan_rata)
                self.assertEqual(data["banding"]["persen_perubahan"], diharapkan_persen)
                self.assertEqual(data["email"]["tren_persen"], diharapkan_persen)

    def test_angka_per_amplop_null_menurut_periodenya_sendiri(self):
        # Kontrak null di docstring modul: terpakai_lalu baris null bila p-1 baris itu kosong; terpakai_rata3 baris null
        # hanya bila ketiga angkanya kosong (nol adalah angka). Tidak bergantung pada terpakai_lalu_total.
        kasus = [
            ("semua None", [None, None, None], None, None),
            ("hanya p-3", [D(300), None, None], None, "300.00"),
            ("hanya p-1", [None, None, D(300)], "300.00", "300.00"),
            ("nol adalah angka", [None, None, D(0)], "0.00", "0.00"),
        ]
        for nama, lalu, diharapkan_lalu, diharapkan_rata in kasus:
            with self.subTest(nama):
                isi = bahan_kosong(amplop=[amplop_kecil("env-s", "Kebutuhan", 200, 88, terpakai_lalu=lalu)])
                baris = susun_bulanan(isi)["banding"]["amplop"][0]
                self.assertEqual((baris["terpakai_lalu"], baris["terpakai_rata3"]), (diharapkan_lalu, diharapkan_rata))

    def test_terpakai_lalu_total_tanpa_angka_membuat_semua_total_null_walau_baris_punya_angka(self):
        # Total tidak pernah diisi dari baris: tanpa satu pun snapshot di lingkup untuk ketiga periode, ketiga total
        # null dan tren null, sedangkan angka per amplop tetap dari barisnya.
        isi = bahan_kosong(
            amplop=[amplop_kecil("env-s", "Kebutuhan", 200, 88, terpakai_lalu=[D(10), D(20), D(30)])],
            terpakai_lalu_total=[None, None, None],
        )
        data = susun_bulanan(isi)
        self.assertEqual(data["banding"], {
            "terpakai_lalu": None, "terpakai_rata3": None, "persen_perubahan": None,
            "amplop": [{"id": "env-s", "terpakai_lalu": "30.00", "terpakai_rata3": "20.00"}],
        })
        self.assertIsNone(data["email"]["tren_persen"])

    def test_periode_lalu_nol_tanpa_persen_dan_tanpa_galat(self):
        # Permintaan peninjau Task 2: total periode lalu Decimal("0.00") adalah angka nyata (uang "0.00") tetapi tidak
        # bisa jadi dasar persen; persen_perubahan dan email.tren_persen None, bukan pengecualian. Yang mengisinya
        # `terpakai_lalu_total[2]` (baris tanpa angka p-1; amplop lain di lingkup yang belanjanya nol).
        for nama, lalu in [("0.00", D("0.00")), ("0", D(0))]:
            with self.subTest(nama):
                isi = bahan_kosong(
                    amplop=[amplop_kecil("env-s", "Kebutuhan", 200, 88, terpakai_lalu=[None, None, None])],
                    terpakai_lalu_total=[None, None, lalu],
                )
                data = susun_bulanan(isi)
                self.assertEqual(data["banding"]["terpakai_lalu"], "0.00")
                self.assertEqual(data["banding"]["terpakai_rata3"], "0.00")
                self.assertIsNone(data["banding"]["persen_perubahan"])
                self.assertIsNone(data["email"]["tren_persen"])

    def test_terpakai_lalu_harus_tiga_periode(self):
        for panjang in (0, 1, 2, 4):
            with self.subTest(panjang):
                isi = bahan_kosong(amplop=[amplop(id="env-s", terpakai_lalu=[D(1)] * panjang)])
                with self.assertRaises(ValueError) as konteks:
                    susun_bulanan(isi)
                self.assertIn("env-s", str(konteks.exception))

    def test_terpakai_lalu_total_harus_tiga_periode(self):
        for panjang in (0, 1, 2, 4):
            with self.subTest(panjang):
                isi = bahan_kosong(terpakai_lalu_total=[D(1)] * panjang)
                with self.assertRaises(ValueError) as konteks:
                    susun_bulanan(isi)
                self.assertIn("terpakai_lalu_total", str(konteks.exception))


class HarianTests(unittest.TestCase):
    def test_harian_mencakup_setiap_hari(self):
        kasus = [
            ("Oktober penuh", PS, PE, 31),
            ("gajian 25", date(2026, 9, 25), d(24), 30),
            ("lintas tahun", date(2026, 12, 25), date(2027, 1, 24), 31),
            ("Februari kabisat", date(2028, 2, 1), date(2028, 2, 29), 29),
            ("satu hari", d(5), d(5), 1),
        ]
        for nama, ps, pe, jumlah_hari in kasus:
            with self.subTest(nama):
                data = susun_bulanan(bahan_kosong(periode_mulai=ps, periode_akhir=pe))
                harian = data["harian"]
                self.assertEqual(len(harian), (pe - ps).days + 1)
                self.assertEqual(len(harian), jumlah_hari)
                self.assertEqual(
                    [h["tanggal"] for h in harian], [(ps + timedelta(days=n)).isoformat() for n in range(jumlah_hari)]
                )
                self.assertTrue(all(h["terpakai"] == "0.00" for h in harian))

    def test_hari_tanpa_transaksi_nol_dan_beberapa_transaksi_sehari_dijumlahkan(self):
        isi = bahan_kosong(amplop=[amplop()], transaksi=[
            txn(id="1", tanggal=d(5), jumlah=D(60_000)), txn(id="2", tanggal=d(5), jumlah=D("40000.50")),
        ])
        harian = {h["tanggal"]: h["terpakai"] for h in susun_bulanan(isi)["harian"]}
        self.assertEqual(harian["2026-10-05"], "100000.50")
        self.assertEqual(harian["2026-10-04"], "0.00")
        self.assertEqual(harian["2026-10-06"], "0.00")

    def test_hari_pertama_dan_terakhir_jendela_ikut(self):
        isi = bahan_kosong(amplop=[amplop()], transaksi=[
            txn(id="1", tanggal=d(1), jumlah=D(10_000)), txn(id="2", tanggal=d(31), jumlah=D(20_000)),
        ])
        harian = susun_bulanan(isi)["harian"]
        self.assertEqual((harian[0]["tanggal"], harian[0]["terpakai"]), ("2026-10-01", "10000.00"))
        self.assertEqual((harian[-1]["tanggal"], harian[-1]["terpakai"]), ("2026-10-31", "20000.00"))

    def test_jumlah_harian_sama_dengan_terpakai_baris_termasuk_penyesuaian(self):
        # Bahan dasar konsisten dan memuat penyesuaian 130.000; harian dan terpakai memakai himpunan yang sama.
        data = susun_bulanan(bahan())
        jumlah_harian = sum((Decimal(h["terpakai"]) for h in data["harian"]), D(0))
        self.assertEqual(jumlah_harian, sum((Decimal(a["terpakai"]) for a in data["amplop"]), D(0)))
        self.assertEqual(jumlah_harian, D("840000"))
        self.assertEqual(
            {h["tanggal"]: h["terpakai"] for h in data["harian"] if h["terpakai"] != "0.00"},
            {f"2026-10-{n:02d}": v for n, v in HARIAN_DASAR.items()},
        )

    def test_hari_terboros(self):
        kasus = [
            ("satu hari terbesar", [(3, 50_000, False), (9, 120_000, False), (20, 80_000, False)],
             ("2026-10-09", "120000.00")),
            ("beberapa transaksi sehari dijumlahkan", [(5, 60_000, False), (5, 50_000, False), (6, 100_000, False)],
             ("2026-10-05", "110000.00")),
            ("seri jatuh ke hari paling awal", [(20, 70_000, False), (4, 70_000, False), (11, 70_000, False)],
             ("2026-10-04", "70000.00")),
            ("penyesuaian ikut dihitung", [(3, 50_000, False), (8, 900_000, True)], ("2026-10-08", "900000.00")),
            ("tanpa transaksi", [], None),
            ("hari bertotal nol atau negatif tidak dianggap boros", [(7, -5_000, True)], None),
        ]
        for nama, belanja, diharapkan in kasus:
            with self.subTest(nama):
                isi = bahan_kosong(amplop=[amplop()], transaksi=[
                    txn(id=str(i), tanggal=d(h), jumlah=D(j), penyesuaian=p) for i, (h, j, p) in enumerate(belanja)
                ])
                hasil = susun_bulanan(isi)["hari_terboros"]
                if diharapkan is None:
                    self.assertIsNone(hasil)
                else:
                    self.assertEqual(hasil, {"tanggal": diharapkan[0], "terpakai": diharapkan[1]})

    def test_hari_negatif_muncul_di_harian_apa_adanya(self):
        isi = bahan_kosong(amplop=[amplop()], transaksi=[txn(tanggal=d(7), jumlah=D(-5_000), penyesuaian=True)])
        harian = {h["tanggal"]: h["terpakai"] for h in susun_bulanan(isi)["harian"]}
        self.assertEqual(harian["2026-10-07"], "-5000.00")


class TerbesarTests(unittest.TestCase):
    def test_terbesar_lima_tanpa_penyesuaian(self):
        belanja = [
            (1, 10_000, False, "a"), (2, 90_000, False, "b"), (3, 30_000, False, "c"), (4, 900_000, True, "d"),
            (5, 70_000, False, "e"), (6, 50_000, False, "f"), (7, 20_000, False, "g"), (8, 80_000, False, "h"),
        ]
        isi = bahan_kosong(amplop=[amplop()], transaksi=[
            txn(id=k, tanggal=d(h), jumlah=D(j), penyesuaian=p, keterangan=k) for h, j, p, k in belanja
        ])
        terbesar = susun_bulanan(isi)["terbesar"]
        self.assertEqual(len(terbesar), 5)
        self.assertEqual([t["keterangan"] for t in terbesar], ["b", "h", "e", "f", "c"])
        self.assertEqual([t["jumlah"] for t in terbesar], ["90000.00", "80000.00", "70000.00", "50000.00", "30000.00"])
        self.assertEqual(terbesar[0], {
            "tanggal": "2026-10-02", "amplop": "Kebutuhan", "keterangan": "b", "jumlah": "90000.00",
            "pencatat": "Ani", "pencatat_id": ID_ANI,
        })

    def test_seri_mengikuti_urutan_masukan(self):
        belanja = [(3, 50_000, "tiga"), (1, 50_000, "satu"), (2, 50_000, "dua"), (5, 70_000, "lima"),
                   (6, 10_000, "enam"), (7, 50_000, "tujuh"), (8, 50_000, "delapan")]
        isi = bahan_kosong(amplop=[amplop()], transaksi=[
            txn(id=k, tanggal=d(h), jumlah=D(j), keterangan=k) for h, j, k in belanja
        ])
        # 70.000 dulu, lalu seri 50.000 menurut urutan masuk (bukan tanggal, bukan terbalik); "delapan" terpotong.
        self.assertEqual(
            [t["keterangan"] for t in susun_bulanan(isi)["terbesar"]], ["lima", "tiga", "satu", "dua", "tujuh"]
        )

    def test_kurang_dari_lima_dan_kosong(self):
        satu = bahan_kosong(amplop=[amplop()], transaksi=[txn(keterangan="x")])
        self.assertEqual([t["keterangan"] for t in susun_bulanan(satu)["terbesar"]], ["x"])
        hanya_penyesuaian = bahan_kosong(amplop=[amplop()], transaksi=[txn(penyesuaian=True)])
        self.assertEqual(susun_bulanan(hanya_penyesuaian)["terbesar"], [])
        self.assertEqual(susun_bulanan(bahan_kosong())["terbesar"], [])

    def test_memuat_nama_amplop_dan_pencatat_dan_keterangan_apa_adanya(self):
        isi = bahan(transaksi=[
            txn(amplop_id="env-p", keterangan="Transaksi privat", pencatat="Budi", milik_penerima=False),
        ])
        self.assertEqual(susun_bulanan(isi)["terbesar"], [{
            "tanggal": "2026-10-02", "amplop": "Jajan", "keterangan": "Transaksi privat",
            "jumlah": "10000.00", "pencatat": "Budi", "pencatat_id": ID_BUDI,
        }])


class LanggananTests(unittest.TestCase):
    def test_langganan_terbayar_tanpa_penanda(self):
        isi = bahan_kosong(
            amplop=[amplop()], transaksi=[txn(keterangan="🔄 Netflix", tagihan=True, jumlah=D(54_000))]
        )
        self.assertEqual(susun_bulanan(isi)["langganan"]["terbayar"], [
            {"tanggal": "2026-10-02", "nama": "Netflix", "amplop": "Kebutuhan", "jumlah": "54000.00",
             "pencatat_id": ID_ANI},
        ])

    def test_terbayar_menurut_penanda_tagihan_bukan_menurut_teks_dan_urut_tanggal(self):
        isi = bahan(transaksi=[
            txn(id="1", amplop_id="env-p", tanggal=d(12), jumlah=D(54_000), keterangan="🔄 Netflix", tagihan=True),
            txn(id="2", amplop_id="env-p", tanggal=d(5), jumlah=D(55_000), keterangan="🔄 Spotify", tagihan=True),
            txn(id="3", amplop_id="env-p", tanggal=d(7), jumlah=D(300_000), keterangan="🔄 Gym", tagihan=False),
            txn(id="4", amplop_id="env-s", tanggal=d(9), jumlah=D(120_000), keterangan="Transaksi privat",
                tagihan=True),
            txn(id="5", amplop_id="env-s", tanggal=d(20), jumlah=D(90_000), keterangan="Bayar 🔄 Hosting",
                tagihan=True, pencatat="Budi", milik_penerima=False),
        ])
        # Tanpa tagihan=True tidak masuk (Gym); keterangan tersamar atau tanpa penanda di awal dipakai apa adanya.
        self.assertEqual(susun_bulanan(isi)["langganan"]["terbayar"], [
            {"tanggal": "2026-10-05", "nama": "Spotify", "amplop": "Jajan", "jumlah": "55000.00",
             "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-09", "nama": "Transaksi privat", "amplop": "Kebutuhan", "jumlah": "120000.00",
             "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-12", "nama": "Netflix", "amplop": "Jajan", "jumlah": "54000.00",
             "pencatat_id": ID_ANI},
            {"tanggal": "2026-10-20", "nama": "Bayar 🔄 Hosting", "amplop": "Kebutuhan", "jumlah": "90000.00",
             "pencatat_id": ID_BUDI},
        ])

    def test_hanya_satu_penanda_di_awal_dibuang(self):
        isi = bahan_kosong(amplop=[amplop()], transaksi=[txn(keterangan="🔄 🔄 Ulang", tagihan=True)])
        self.assertEqual(susun_bulanan(isi)["langganan"]["terbayar"][0]["nama"], "🔄 Ulang")

    def test_penanda_sama_dengan_penanda_advisor_yang_dipakai_tombol_bayar(self):
        from app.services.advisor.snapshot import BILL_MARKER
        self.assertEqual(susun.PENANDA_TAGIHAN, BILL_MARKER)
        self.assertEqual(susun.PENANDA_TAGIHAN, chr(0x1F504) + " ")

    def test_jatuh_tempo_urut_tanggal_dan_amplop_di_luar_bahan_null(self):
        isi = bahan(tagihan_berikut=[
            TagihanBerikut(date(2026, 11, 20), "Asuransi", "env-baru", D(250_000)),
            TagihanBerikut(date(2026, 11, 5), "Listrik", "env-s", D(100_000)),
        ])
        # Amplop baru (dibuat sesudah periode, tanpa snapshot) tidak ada di bahan.amplop: nama amplop null,
        # tagihannya tetap tampil.
        self.assertEqual(susun_bulanan(isi)["langganan"]["jatuh_tempo"], [
            {"tanggal": "2026-11-05", "nama": "Listrik", "amplop": "Kebutuhan", "jumlah": "100000.00"},
            {"tanggal": "2026-11-20", "nama": "Asuransi", "amplop": None, "jumlah": "250000.00"},
        ])

    def test_tanpa_langganan(self):
        data = susun_bulanan(bahan(transaksi=[txn()], tagihan_berikut=[]))
        self.assertEqual(data["langganan"], {"terbayar": [], "jatuh_tempo": []})


class SorotanTests(unittest.TestCase):
    def test_sorotan_hanya_catatan_penerima(self):
        isi = bahan_kosong(amplop=[amplop()], transaksi=[
            txn(id="p4", tanggal=d(4), penyesuaian=True),                       # penyesuaian: tidak dihitung
            txn(id="a5", tanggal=d(5)), txn(id="a6", tanggal=d(6)),
            txn(id="a7", tanggal=d(7)), txn(id="a7b", tanggal=d(7)),            # dua catatan sehari: satu hari
            txn(id="b8", tanggal=d(8), pencatat="Budi", milik_penerima=False),  # anggota lain: tidak dihitung
            txn(id="b9", tanggal=d(9), pencatat="Budi", milik_penerima=False),
            txn(id="a20", tanggal=d(20)),
        ])
        sorotan = susun_bulanan(isi)["sorotan"]
        self.assertEqual(sorotan["hari_mencatat"], 4)
        self.assertEqual(sorotan["beruntun_terpanjang"], 3)

    def test_catatan_beruntun_lintas_batas_bulan(self):
        isi = bahan_kosong(
            amplop=[amplop()], periode_mulai=date(2026, 9, 25), periode_akhir=d(24), payday=25,
            transaksi=[txn(id="1", tanggal=date(2026, 9, 29)), txn(id="2", tanggal=date(2026, 9, 30)),
                       txn(id="3", tanggal=d(1)), txn(id="4", tanggal=d(2))],
        )
        sorotan = susun_bulanan(isi)["sorotan"]
        self.assertEqual((sorotan["hari_mencatat"], sorotan["beruntun_terpanjang"]), (4, 4))

    def test_streak_saat_ini_dari_bahan_apa_adanya(self):
        for streak in (0, 3, 120):
            with self.subTest(streak):
                self.assertEqual(susun_bulanan(bahan(streak_saat_ini=streak))["sorotan"]["streak_saat_ini"], streak)

    def test_target_terkumpul_adalah_akhir_amplopnya(self):
        isi = bahan(target=[
            TargetTabungan("Motor", "env-s", D(1_600_000)),      # akhir Kebutuhan 400.000, bukan awal 1.000.000
            TargetTabungan("Liburan", "env-t", D(1_000_000)),    # 500.000 dari 1.000.000
            TargetTabungan("Tanpa dasar", "env-t", D(0)),        # target 0: tanpa persen
        ])
        self.assertEqual(susun_bulanan(isi)["sorotan"]["target"], [
            {"nama": "Motor", "target": "1600000.00", "terkumpul": "400000.00", "persen": 25},
            {"nama": "Liburan", "target": "1000000.00", "terkumpul": "500000.00", "persen": 50},
            {"nama": "Tanpa dasar", "target": "0.00", "terkumpul": "500000.00", "persen": None},
        ])

    def test_target_persen_dibulatkan_dan_bisa_negatif_atau_lebih_dari_seratus(self):
        isi = bahan(
            amplop=[
                amplop(id="a", nama="A", awal=D(100), alokasi=D(100), terpakai=D(150), akhir=D(-50)),
                amplop(id="b", nama="B", awal=D(100), alokasi=D(100), terpakai=D(0), akhir=D(1)),
                amplop(id="c", nama="C", awal=D(100), alokasi=D(100), terpakai=D(0), akhir=D(300)),
            ],
            transaksi=[],
            target=[
                TargetTabungan("t1", "a", D(200)), TargetTabungan("t2", "b", D(8)), TargetTabungan("t3", "c", D(200)),
            ],
        )
        self.assertEqual([t["persen"] for t in susun_bulanan(isi)["sorotan"]["target"]], [-25, 13, 150])

    def test_target_pada_amplop_di_luar_bahan_ditolak(self):
        isi = bahan(target=[TargetTabungan("Hilang", "env-hilang", D(1))])
        with self.assertRaises(ValueError) as konteks:
            susun_bulanan(isi)
        self.assertIn("env-hilang", str(konteks.exception))


class MutasiTests(unittest.TestCase):
    def test_mutasi_keluar_per_amplop_sama_dengan_terpakai(self):
        data = susun_bulanan(bahan())
        for baris in data["amplop"]:
            with self.subTest(baris["nama"]):
                keluar = sum(
                    (Decimal(m["jumlah"]) for m in data["mutasi"]
                     if m["arah"] == "keluar" and m["amplop"] == baris["nama"]),
                    D(0),
                )
                self.assertEqual(keluar, Decimal(baris["terpakai"]))
        # Ditambatkan ke literal: Kebutuhan 600.000, Jajan 240.000, Dana darurat tanpa mutasi keluar.
        per_nama = {n: sum((Decimal(m["jumlah"]) for m in data["mutasi"] if m["amplop"] == n), D(0))
                    for n in ("Kebutuhan", "Jajan", "Dana darurat")}
        self.assertEqual(per_nama, {"Kebutuhan": D("600000"), "Jajan": D("240000"), "Dana darurat": D(0)})

    def test_mutasi_urut_tanggal_pemasukan_dulu_di_hari_sama_lalu_urutan_masuk(self):
        isi = bahan(
            amplop=[amplop()],
            pemasukan=[PemasukanPeriode(d(5), D(1_000_000), "Bonus"), PemasukanPeriode(d(2), D(5_000_000), "Gaji")],
            transaksi=[txn(id="1", tanggal=d(5), keterangan="B"), txn(id="2", tanggal=d(5), keterangan="A"),
                       txn(id="3", tanggal=d(2), keterangan="C")],
            tagihan_berikut=[], target=[],
        )
        mutasi = susun_bulanan(isi)["mutasi"]
        self.assertEqual([(m["tanggal"], m["keterangan"]) for m in mutasi], [
            ("2026-10-02", "Gaji"), ("2026-10-02", "C"), ("2026-10-05", "Bonus"), ("2026-10-05", "B"),
            ("2026-10-05", "A"),
        ])

    def test_baris_masuk_tanpa_amplop_dengan_pencatat_penerima(self):
        isi = bahan(pemasukan=[PemasukanPeriode(d(2), D("1500000.5"), "Gaji")], penerima_nama="Citra",
                    penerima_id=ID_CITRA, transaksi=[], tagihan_berikut=[], target=[])
        self.assertEqual(
            susun_bulanan(isi)["mutasi"],
            [_mutasi("2026-10-02", "masuk", None, "Gaji", "1500000.50", "Citra", penyesuaian=False)],
        )

    def test_baris_keluar_memuat_pencatat_penyesuaian_dan_nama_amplop(self):
        isi = bahan(transaksi=[
            txn(amplop_id="env-p", pencatat="Budi", penyesuaian=True, jumlah=D(5), keterangan="Cocokkan saldo"),
        ], pemasukan=[], tagihan_berikut=[], target=[])
        self.assertEqual(
            susun_bulanan(isi)["mutasi"],
            [_mutasi("2026-10-02", "keluar", "Jajan", "Cocokkan saldo", "5.00", "Budi", penyesuaian=True)],
        )

    def test_amplop_transaksi_di_luar_bahan_ditolak(self):
        isi = bahan(transaksi=[txn(id="x", amplop_id="env-hilang")])
        with self.assertRaises(ValueError) as konteks:
            susun_bulanan(isi)
        self.assertIn("env-hilang", str(konteks.exception))

    def test_banyak_transaksi(self):
        # Ratusan baris dalam satu periode (review focus 3): semua ikut, urut tanggal, jumlah harian utuh.
        banyak = [txn(id=str(i), tanggal=d(1 + i % 31), jumlah=D("1.00")) for i in range(3000)]
        data = susun_bulanan(bahan_kosong(amplop=[amplop()], transaksi=banyak))
        self.assertEqual(len(data["mutasi"]), 3000)
        # Boolean, bukan assertEqual atas dua daftar 3000 isi: pada kegagalan, selisihnya dihitung kuadratik.
        tanggal = [m["tanggal"] for m in data["mutasi"]]
        self.assertTrue(tanggal == sorted(tanggal), "mutasi tidak urut tanggal")
        self.assertEqual(sum((Decimal(h["terpakai"]) for h in data["harian"]), D(0)), D("3000"))
        self.assertEqual(len(data["terbesar"]), 5)


class PencatatIdTests(unittest.TestCase):
    """Ruling R15: baris yang memuat nama atau teks seorang pencatat membawa `pencatat_id` (id user, teks UUID), supaya
    baris itu bisa dianonimkan di laporan beku penerima lain bila pencatatnya menghapus akun. Nama tidak unik, jadi
    tidak bisa jadi kuncinya. Id tidak pernah ditampilkan (halaman dan PDF membaca kunci yang lain)."""

    def bahan_campur(self):
        """Ani penerima; baris dari Ani dan Budi di setiap jenis baris berpencatat, termasuk tagihan Budi."""
        return bahan(transaksi=[
            *_transaksi_dasar(),
            txn(id="b-tagihan", amplop_id="env-s", tanggal=d(14), jumlah=D(20_000), keterangan="🔄 Spotify",
                pencatat="Budi", milik_penerima=False, tagihan=True),
        ])

    def test_setiap_jenis_baris_berpencatat_membawa_pencatat_id(self):
        data = susun_bulanan(self.bahan_campur())
        keluar = [m for m in data["mutasi"] if m["arah"] == "keluar"]
        jenis = {
            "terbesar": data["terbesar"],
            "langganan.terbayar": data["langganan"]["terbayar"],
            "mutasi masuk": [m for m in data["mutasi"] if m["arah"] == "masuk"],
            "mutasi keluar": keluar,
        }
        for nama, baris in jenis.items():
            with self.subTest(nama):
                self.assertTrue(baris)  # fixture memuat jenis baris ini
                for b in baris:
                    self.assertIn("pencatat_id", b)
        # Nilainya id pencatat transaksi itu; baris masuk = penerima (pemasukan yang dicatatnya sendiri).
        self.assertEqual([t["pencatat_id"] for t in data["terbesar"]], [ID_ANI] * 4 + [ID_BUDI])
        self.assertEqual([(t["nama"], t["pencatat_id"]) for t in data["langganan"]["terbayar"]],
                         [("Netflix", ID_ANI), ("Spotify", ID_BUDI)])
        self.assertEqual({m["pencatat_id"] for m in jenis["mutasi masuk"]}, {ID_ANI})
        self.assertEqual({(m["pencatat"], m["pencatat_id"]) for m in keluar}, {("Ani", ID_ANI), ("Budi", ID_BUDI)})

    def test_tidak_ada_nama_atau_teks_catatan_tanpa_pencatat_id(self):
        # Pagar untuk baris baru: setiap kamus yang memuat `pencatat` atau `keterangan` (nama atau teks pencatat)
        # membawa `pencatat_id`, di mana pun letaknya di `data`.
        def kamus(nilai, jalur):
            if isinstance(nilai, dict):
                yield jalur, nilai
                for k, v in nilai.items():
                    yield from kamus(v, f"{jalur}.{k}")
            elif isinstance(nilai, list):
                for i, v in enumerate(nilai):
                    yield from kamus(v, f"{jalur}[{i}]")

        diperiksa = 0
        for jalur, isi in kamus(susun_bulanan(self.bahan_campur()), "data"):
            if {"pencatat", "keterangan"} & set(isi):
                diperiksa += 1
                self.assertIn("pencatat_id", isi, jalur)
        self.assertGreater(diperiksa, 10)

    def test_baris_benda_rumah_tanpa_pencatat_id(self):
        # Amplop, target, dan langganan (jatuh tempo) tidak menyimpan siapa pembuatnya; hapus akun di aplikasi juga
        # membiarkan nama amplop bersama, target, dan langganan rumah. Tanpa pencatat, tanpa `pencatat_id`.
        data = susun_bulanan(self.bahan_campur())
        for jalur, baris in [("amplop", data["amplop"]), ("jatuh_tempo", data["langganan"]["jatuh_tempo"]),
                             ("target", data["sorotan"]["target"])]:
            with self.subTest(jalur):
                self.assertTrue(baris)
                for b in baris:
                    self.assertNotIn("pencatat_id", b)


class EmailTests(unittest.TestCase):
    def test_email_tanpa_nominal(self):
        data = susun_bulanan(bahan())
        nilai_uang = semua_uang(data, kecuali="email")
        self.assertGreater(len(set(nilai_uang)), 20)       # tes ini bermakna hanya bila ada banyak nominal untuk dicari
        teks = json.dumps(data["email"], ensure_ascii=False)
        for nilai in nilai_uang:
            self.assertNotIn(nilai, teks)
        self.assertNotIn("Rp", teks)
        self.assertIsNone(re.search(r"\d\.\d", teks), teks)  # tidak ada angka berdesimal sama sekali
        # Hanya persen/hitungan bulat, None, dan satu kalimat sorotan.
        for kunci, nilai in data["email"].items():
            self.assertIn(type(nilai), (int, str, type(None)), kunci)

    def test_email_tanpa_nominal_pada_bahan_yang_lain(self):
        tanpa_pembanding = bahan_kosong(amplop=[amplop(terpakai_lalu=[None, None, None])])
        for nama, isi in [("kosong", bahan_kosong()), ("tanpa pembanding", tanpa_pembanding)]:
            with self.subTest(nama):
                data = susun_bulanan(isi)
                teks = json.dumps(data["email"])
                for nilai in semua_uang(data, kecuali="email"):
                    self.assertNotIn(nilai, teks)

    def test_hitungan_email_berbeda_dari_daftar_sorotan(self):
        # email.amplop_aman = jumlah amplop berstatus aman (Kebutuhan saja: 1); sorotan.amplop_aman = nama amplop
        # yang tidak pernah lewat batas dan bukan tabungan/kosong (Kebutuhan dan Jajan: 2).
        data = susun_bulanan(bahan())
        self.assertEqual(data["email"]["amplop_aman"], 1)
        self.assertEqual(data["sorotan"]["amplop_aman"], ["Kebutuhan", "Jajan"])

    def test_amplop_aman_yang_pernah_lewat_batas_dihitung_status_tapi_bukan_sorotan(self):
        # Saldo awal 100.000 baru tiba tanggal 5, belanja 40.000 tanggal 3: akhir 60.000 berstatus aman (40%),
        # tetapi saldo harian sempat di bawah nol.
        isi = bahan(
            amplop=[amplop(awal=D(100_000), alokasi=D(100_000), terpakai=D(40_000), akhir=D(60_000),
                           alokasi_per_hari={d(5): D(100_000)})],
            transaksi=[txn(tanggal=d(3), jumlah=D(40_000))], target=[], tagihan_berikut=[],
        )
        data = susun_bulanan(isi)
        self.assertEqual(data["amplop"][0]["status"], "aman")
        self.assertTrue(data["amplop"][0]["pernah_lewat_batas"])
        self.assertEqual(data["email"]["amplop_aman"], 1)
        self.assertEqual(data["email"]["amplop_lewat_batas"], 0)    # pernah lewat batas bukan status lewat_batas
        self.assertEqual(data["sorotan"]["amplop_aman"], [])

    def test_amplop_berstatus_lewat_batas_bukan_amplop_aman_walau_saldo_harian_tak_pernah_negatif(self):
        # Ruling R6, penjagaan atas bahan yang tidak konsisten: akhir -10 padahal alokasi 100 tiba di hari pertama dan
        # tak ada belanja, jadi tak ada hari bersaldo negatif. Pemuat yang benar tidak menghasilkannya, tetapi amplop
        # berstatus lewat_batas tidak boleh dipuji "tidak pernah lewat batas" di sorotan maupun kalimat email.
        lewat = amplop(id="l", nama="Lewat", awal=D(100), alokasi=D(100), terpakai=D(50), akhir=D(-10),
                       rollover=D(-10), alokasi_per_hari={d(1): D(100)})
        kasus = [
            ("sendirian", [lewat], [], "Siap untuk periode berikutnya", (0, 1)),
            ("bersama amplop yang aman", [lewat, amplop_kecil("a", "Aman", 100, 10)], ["Aman"],
             "1 amplop tidak pernah lewat batas", (1, 1)),
        ]
        for nama, baris, diharapkan, kalimat, (aman, lewat_batas) in kasus:
            with self.subTest(nama):
                data = susun_bulanan(bahan_kosong(amplop=baris))
                self.assertEqual(data["amplop"][0]["status"], "lewat_batas")
                self.assertIs(data["amplop"][0]["pernah_lewat_batas"], False)
                self.assertEqual(data["sorotan"]["amplop_aman"], diharapkan)
                self.assertEqual(data["email"]["sorotan"], kalimat)
                self.assertEqual((data["email"]["amplop_aman"], data["email"]["amplop_lewat_batas"]),
                                 (aman, lewat_batas))

    def test_sorotan_email_memakai_beruntun_amplop_aman_dan_hari_mencatat(self):
        tujuh_hari = [txn(id=str(n), tanggal=d(n)) for n in range(1, 8)]
        kasus = [
            ("beruntun 7 hari menang", bahan(transaksi=tujuh_hari), "Mencatat 7 hari berturut-turut"),
            ("enam hari berturut dengan dua amplop tidak pernah lewat batas",
             bahan(transaksi=tujuh_hari[:6]), "2 amplop tidak pernah lewat batas"),
            ("tanpa amplop yang aman: hari mencatat",
             bahan_kosong(amplop=[amplop(tujuan="saving")],
                          transaksi=[txn(id="1", tanggal=d(3)), txn(id="2", tanggal=d(9))]),
             "Mencatat di 2 hari"),
            ("tanpa apa pun", bahan_kosong(), "Siap untuk periode berikutnya"),
        ]
        for nama, isi, diharapkan in kasus:
            with self.subTest(nama):
                self.assertEqual(susun_bulanan(isi)["email"]["sorotan"], diharapkan)


class AktivitasTests(unittest.TestCase):
    def test_ada_aktivitas_false_untuk_bahan_kosong(self):
        self.assertIs(ada_aktivitas(bahan_kosong()), False)

    def test_ada_aktivitas_menurut_alokasi_atau_transaksi(self):
        kasus = [
            ("alokasi positif tanpa transaksi", bahan_kosong(amplop=[amplop()]), True),
            ("alokasi hanya di salah satu amplop",
             bahan_kosong(amplop=[amplop(alokasi=D(0)), amplop(id="b", nama="B", alokasi=D("0.01"))]), True),
            ("transaksi tanpa alokasi", bahan_kosong(amplop=[amplop(alokasi=D(0))], transaksi=[txn()]), True),
            ("amplop tanpa alokasi dan tanpa transaksi", bahan_kosong(amplop=[amplop(alokasi=D(0))]), False),
            ("alokasi negatif bukan aktivitas", bahan_kosong(amplop=[amplop(alokasi=D(-5))]), False),
            ("pemasukan saja bukan aktivitas",
             bahan_kosong(pemasukan=[PemasukanPeriode(d(1), D(5_000_000), "Gaji")]), False),
            ("tagihan berikut dan target saja bukan aktivitas",
             bahan_kosong(tagihan_berikut=[TagihanBerikut(date(2026, 11, 5), "Listrik", "x", D(1))]), False),
            ("bahan dasar", bahan(), True),
        ]
        for nama, isi, diharapkan in kasus:
            with self.subTest(nama):
                self.assertIs(ada_aktivitas(isi), diharapkan)


class KontrakBahanTests(unittest.TestCase):
    def test_dataclass_beku(self):
        contoh = [
            amplop(), txn(), PemasukanPeriode(d(1), D(1), "x"), TagihanBerikut(d(1), "x", "env-s", D(1)),
            TargetTabungan("x", "env-s", D(1)), bahan(),
        ]
        for objek in contoh:
            with self.subTest(type(objek).__name__):
                nama_kolom = dataclasses.fields(objek)[0].name
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(objek, nama_kolom, "diubah")

    def test_bidang_dan_urutan_sesuai_brief(self):
        def nama(kelas):
            return [f.name for f in dataclasses.fields(kelas)]

        self.assertEqual(nama(AmplopPeriode), [
            "id", "nama", "emoji", "pribadi", "tujuan", "awal", "alokasi", "terpakai", "akhir", "rollover",
            "ditutup", "alokasi_per_hari", "terpakai_lalu",
        ])
        self.assertEqual(nama(TransaksiPeriode), [
            "id", "amplop_id", "tanggal", "jumlah", "keterangan", "pencatat", "pencatat_id", "milik_penerima",
            "penyesuaian", "tagihan",
        ])
        self.assertEqual(nama(PemasukanPeriode), ["tanggal", "jumlah", "keterangan"])
        self.assertEqual(nama(TagihanBerikut), ["tanggal", "nama", "amplop_id", "jumlah"])
        self.assertEqual(nama(TargetTabungan), ["nama", "amplop_id", "target"])
        self.assertEqual(nama(BahanLaporan), [
            "penerima_nama", "penerima_id", "rumah_nama", "periode_mulai", "periode_akhir", "payday", "angka_per",
            "amplop", "transaksi", "pemasukan", "tagihan_berikut", "target", "streak_saat_ini", "terpakai_lalu_total",
        ])

    def test_id_pencatat_dan_penerima_wajib_tanpa_nilai_bawaan(self):
        # Ruling R15: id yang lupa diisi pemuat akan beku sebagai null, dan baris itu tak pernah bisa dianonimkan saat
        # pencatatnya menghapus akun. Wajib, supaya pemuat yang lupa gagal saat membangun bahan, bukan diam-diam.
        for kelas, nama_kolom in [(TransaksiPeriode, "pencatat_id"), (BahanLaporan, "penerima_id")]:
            with self.subTest(kelas=kelas.__name__):
                kolom = {f.name: f for f in dataclasses.fields(kelas)}[nama_kolom]
                self.assertIs(kolom.default, dataclasses.MISSING)
                self.assertIs(kolom.default_factory, dataclasses.MISSING)

    def test_terpakai_lalu_total_wajib_tanpa_nilai_bawaan(self):
        # Ruling R3: pemuat harus mengisinya (bukan bawaan [None, None, None] yang diam-diam menghapus pembanding).
        isi = bahan()
        kolom = {f.name: f for f in dataclasses.fields(BahanLaporan)}["terpakai_lalu_total"]
        self.assertIs(kolom.default, dataclasses.MISSING)
        self.assertIs(kolom.default_factory, dataclasses.MISSING)
        tanpa_total = {f.name: getattr(isi, f.name) for f in dataclasses.fields(isi) if f.name != "terpakai_lalu_total"}
        with self.assertRaises(TypeError):
            BahanLaporan(**tanpa_total)

    def test_tidak_mengubah_bahan_dan_hasilnya_deterministik(self):
        isi = bahan()
        sebelum = copy.deepcopy(isi)
        pertama = susun_bulanan(isi)
        self.assertEqual(isi, sebelum)
        self.assertEqual(susun_bulanan(isi), pertama)
        self.assertEqual(susun_bulanan(bahan()), pertama)

    def test_modul_hanya_bergantung_pada_hitung_dan_stdlib(self):
        # Murni: tanpa DB, ORM, setelan, atau advisor (Task 4 yang membaca DB). Dibaca dari impor di sumber modul,
        # termasuk impor di dalam fungsi, supaya ketergantungan baru ketahuan di sini.
        import ast
        with open(susun.__file__, encoding="utf-8") as f:
            pohon = ast.parse(f.read())
        impor, dari_app = set(), set()
        for simpul in ast.walk(pohon):
            if isinstance(simpul, ast.Import):
                impor.update(a.name.split(".")[0] for a in simpul.names)
            elif isinstance(simpul, ast.ImportFrom):
                self.assertEqual(simpul.level, 0, "impor relatif tidak dipakai di paket ini")
                impor.add(simpul.module.split(".")[0])
                if simpul.module.startswith("app"):
                    dari_app.add(simpul.module)
        self.assertLessEqual(impor, {"collections", "dataclasses", "datetime", "decimal", "app"})
        self.assertEqual(dari_app, {"app.services.laporan.hitung"})


class KonsistensiAcakTests(unittest.TestCase):
    """Bahan konsisten acak (benih tetap): invarian spec bagian 10 berlaku di segala bentuk jendela dan transaksi.
    Pembanding dihitung dari bahan masukan dengan cara lain dari kode yang diuji (kunci urut negatif, pindai hari
    kalender, bilangan bulat sen), bukan dengan menyalin rumusnya."""

    @staticmethod
    def _bahan_acak(acak: random.Random, putaran: int):
        ps = date(2026, 1, 1) + timedelta(days=acak.randrange(0, 700))
        pe = ps + timedelta(days=acak.randrange(0, 40))
        jumlah_hari = (pe - ps).days + 1
        id_amplop = [f"e{n}" for n in range(acak.randrange(0, 5))]
        transaksi = []
        for i in range(acak.randrange(0, 40) if id_amplop else 0):
            transaksi.append(txn(
                id=f"{putaran}-{i}", amplop_id=acak.choice(id_amplop),
                tanggal=ps + timedelta(days=acak.randrange(jumlah_hari)),
                jumlah=D(acak.randrange(1, 500_000)) / 100, penyesuaian=acak.random() < 0.15,
                milik_penerima=acak.random() < 0.7, keterangan=f"k{i}",
            ))
        baris = []
        for e in id_amplop:
            terpakai = sum((t.jumlah for t in transaksi if t.amplop_id == e), D(0))
            alokasi = D(acak.randrange(0, 2_000_000)) / 100
            awal = D(acak.randrange(-100_000, 500_000)) / 100 + alokasi
            baris.append(amplop(
                id=e, nama=f"Amplop {e}", pribadi=acak.random() < 0.5, awal=awal, alokasi=alokasi,
                terpakai=terpakai, akhir=awal - terpakai, rollover=acak.choice([D(0), awal - terpakai]),
                alokasi_per_hari={ps + timedelta(days=acak.randrange(jumlah_hari)): alokasi},
                terpakai_lalu=[acak.choice([None, D(acak.randrange(0, 90_000)) / 100]) for _ in range(3)],
                tujuan=acak.choice(["expense", "debt", "saving", "sinking_fund"]),
            ))
        pemasukan = [PemasukanPeriode(ps, D(acak.randrange(0, 90_000)) / 100, "Gaji")]
        # Total lingkup p-3..p-1 bebas dari baris (lingkup lebih luas dari baris): None, nol, atau nominal.
        total_lalu = [acak.choice([None, D("0.00"), D(acak.randrange(1, 5_000_000)) / 100]) for _ in range(3)]
        isi = bahan(periode_mulai=ps, periode_akhir=pe, amplop=baris, transaksi=transaksi, pemasukan=pemasukan,
                    tagihan_berikut=[], target=[], terpakai_lalu_total=total_lalu)
        return isi, jumlah_hari

    def test_invarian_di_banyak_bentuk_bahan(self):
        acak = random.Random(20261101)
        for putaran in range(300):
            isi, jumlah_hari = self._bahan_acak(acak, putaran)
            with self.subTest(putaran=putaran):
                data = susun_bulanan(isi)
                self._periksa_invarian(isi, data, jumlah_hari)

    def _periksa_invarian(self, isi: BahanLaporan, data: dict, jumlah_hari: int):
        def total(nilai):
            return sum((Decimal(x) for x in nilai), D(0))

        ps = isi.periode_mulai
        self.assertEqual(json.loads(json.dumps(data, allow_nan=False)), data)

        # Jumlah baris = ringkasan, jumlah harian = terpakai, mutasi keluar per amplop = terpakai.
        for kunci_ringkasan, atribut in [("dialokasikan", "alokasi"), ("terpakai", "terpakai"), ("sisa", "akhir"),
                                         ("dibawa", "rollover")]:
            self.assertEqual(
                Decimal(data["ringkasan"][kunci_ringkasan]), sum((getattr(a, atribut) for a in isi.amplop), D(0))
            )
        self.assertEqual(len(data["harian"]), jumlah_hari)
        self.assertEqual(total(h["terpakai"] for h in data["harian"]), total(a["terpakai"] for a in data["amplop"]))
        for a in data["amplop"]:
            keluar = total(m["jumlah"] for m in data["mutasi"] if m["arah"] == "keluar" and m["amplop"] == a["nama"])
            self.assertEqual(keluar, Decimal(a["terpakai"]))

        # Mutasi: semua baris ikut dan urut tanggal.
        self.assertEqual(len(data["mutasi"]), len(isi.transaksi) + len(isi.pemasukan))
        self.assertEqual([m["tanggal"] for m in data["mutasi"]], sorted(m["tanggal"] for m in data["mutasi"]))

        # Hari terboros: hari bertotal terbesar (seri: paling awal), hanya bila di atas nol.
        per_hari: dict[date, Decimal] = {}
        for t in isi.transaksi:
            per_hari[t.tanggal] = per_hari.get(t.tanggal, D(0)) + t.jumlah
        if per_hari and max(per_hari.values()) > 0:
            hari = min(per_hari, key=lambda h: (-per_hari[h], h))
            self.assertEqual(data["hari_terboros"], {"tanggal": hari.isoformat(), "terpakai": f"{per_hari[hari]:.2f}"})
        else:
            self.assertIsNone(data["hari_terboros"])

        # Lima terbesar tanpa penyesuaian; urutan seri = urutan masukan (kunci negatif, bukan reverse=True).
        biasa = sorted((t for t in isi.transaksi if not t.penyesuaian), key=lambda t: -t.jumlah)[:5]
        self.assertEqual([t["keterangan"] for t in data["terbesar"]], [t.keterangan for t in biasa])

        # Hari mencatat dan beruntun dari catatan penerima, dipindai hari demi hari di jendela.
        dicatat = {t.tanggal for t in isi.transaksi if t.milik_penerima and not t.penyesuaian}
        beruntun = terpanjang = 0
        for n in range(jumlah_hari):
            beruntun = beruntun + 1 if ps + timedelta(days=n) in dicatat else 0
            terpanjang = max(terpanjang, beruntun)
        self.assertEqual(data["sorotan"]["hari_mencatat"], len(dicatat))
        self.assertEqual(data["sorotan"]["beruntun_terpanjang"], terpanjang)

        # Persen terpakai (Ruling R5): hanya amplop selain tabungan, pembilang dan penyebut; daftar tujuan tabungan
        # ditulis ulang di sini, bukan dibaca dari hitung. Bilangan bulat sen; penyebut nol atau negatif: None.
        belanja = [a for a in isi.amplop if a.tujuan not in ("saving", "sinking_fund")]
        penyebut = sum(self._sen(a.awal) for a in belanja)
        pembilang = sum(self._sen(a.terpakai) for a in belanja)
        persen_diharapkan = None if penyebut <= 0 else (200 * pembilang + penyebut) // (2 * penyebut)
        self.assertEqual(data["ringkasan"]["persen_terpakai"], persen_diharapkan)
        self.assertEqual(data["email"]["persen_terpakai"], persen_diharapkan)

        # Amplop aman di sorotan (Ruling R6): bukan tabungan, akhir tidak negatif, saldo awal positif, dan saldo
        # harian tak pernah di bawah nol (dipindai hari demi hari, bukan lewat hitung.pernah_lewat_batas).
        aman = []
        for a in isi.amplop:
            saldo, negatif = a.awal - a.alokasi, False
            for n in range(jumlah_hari):
                hari = ps + timedelta(days=n)
                belanja_hari = sum((t.jumlah for t in isi.transaksi if t.amplop_id == a.id and t.tanggal == hari), D(0))
                saldo += a.alokasi_per_hari.get(hari, D(0)) - belanja_hari
                negatif = negatif or saldo < 0
            if a.tujuan not in ("saving", "sinking_fund") and a.akhir >= 0 and a.awal > 0 and not negatif:
                aman.append(a.nama)
        self.assertEqual(data["sorotan"]["amplop_aman"], aman)

        # Pembanding: total dari `terpakai_lalu_total` (bukan jumlah baris), per amplop dari barisnya; dihitung dengan
        # bilangan bulat sen, bebas dari Decimal dan ROUND_HALF_UP milik kode yang diuji.
        total = isi.terpakai_lalu_total
        lalu = None if total[-1] is None else self._sen(total[-1])
        sekarang = sum(self._sen(a.terpakai) for a in isi.amplop)
        banding = data["banding"]
        self.assertEqual(banding["terpakai_lalu"], self._teks_sen(lalu))
        self.assertEqual(banding["terpakai_rata3"], self._teks_sen(self._rata_sen(total)))
        self.assertEqual(banding["persen_perubahan"], self._persen_ubah(sekarang, lalu))
        self.assertEqual(data["email"]["tren_persen"], banding["persen_perubahan"])
        self.assertEqual([b["id"] for b in banding["amplop"]], [a.id for a in isi.amplop])
        for a, baris in zip(isi.amplop, banding["amplop"]):
            p1 = a.terpakai_lalu[-1]
            self.assertEqual(baris["terpakai_lalu"], None if p1 is None else self._teks_sen(self._sen(p1)))
            self.assertEqual(baris["terpakai_rata3"], self._teks_sen(self._rata_sen(a.terpakai_lalu)))

    @staticmethod
    def _sen(nilai: Decimal) -> int:
        """Nominal kelipatan 0,01 sebagai bilangan bulat sen (kali 100 eksak, tanpa pembagian atau pembulatan)."""
        return int(nilai * 100)

    @staticmethod
    def _teks_sen(sen: int | None) -> str | None:
        if sen is None:
            return None
        return f"{'-' if sen < 0 else ''}{abs(sen) // 100}.{abs(sen) % 100:02d}"

    @classmethod
    def _rata_sen(cls, nilai) -> int | None:
        """Rata-rata nilai yang ada (None dilewati), setengah ke atas ke sen; nilai tidak negatif."""
        ada = [cls._sen(n) for n in nilai if n is not None]
        return (2 * sum(ada) + len(ada)) // (2 * len(ada)) if ada else None

    @staticmethod
    def _persen_ubah(sekarang_sen: int, lalu_sen: int | None) -> int | None:
        """Perubahan persen bulat, setengah menjauhi nol; None tanpa pembanding yang berarti (None, nol, negatif)."""
        if lalu_sen is None or lalu_sen <= 0:
            return None
        pembilang = (sekarang_sen - lalu_sen) * 100
        hasil = (2 * abs(pembilang) + lalu_sen) // (2 * lalu_sen)
        return hasil if pembilang >= 0 else -hasil


if __name__ == "__main__":
    unittest.main()
