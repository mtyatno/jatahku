"""Perhitungan murni laporan berkala (tahap 1, Task 2; spec bagian 2c, 2d, 3, 4, 6b): judul, nama file, status
amplop, "pernah lewat batas", beruntun, persen, uang, dan teks sorotan.

Semua fungsi murni (tanpa DB, setelan, atau I/O), jadi harapan di sini ditulis tangan sebagai literal dan
tidak pernah dihitung oleh fungsi yang diuji. Header env tetap dipasang seperti modul tes lain walau modul
ini tidak menyentuh DB.
Run: python -m unittest app.tests.test_laporan_hitung -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.services.laporan import hitung
from app.services.laporan.hitung import (
    BLN, BULAN, adalah_bulan_kalender, beruntun_terpanjang, judul_bulanan, nama_file_pdf,
    pernah_lewat_batas, persen, persen_perubahan, rata_rata, status_amplop, teks_sorotan, uang,
)

D = Decimal


def d(n: int) -> date:
    """Tanggal n di Oktober 2026."""
    return date(2026, 10, n)


class NamaBulanTests(unittest.TestCase):
    def test_tuple_berindeks_bulan_1_sampai_12_dengan_indeks_0_kosong(self):
        # Pemanggil memakai BULAN[ps.month] langsung; tanpa string kosong di indeks 0 semua bulan bergeser satu.
        for nama, nilai, pertama, terakhir in [("BULAN", BULAN, "Januari", "Desember"), ("BLN", BLN, "Jan", "Des")]:
            with self.subTest(nama):
                self.assertIsInstance(nilai, tuple)
                self.assertEqual(len(nilai), 13)
                self.assertEqual(nilai[0], "")
                self.assertEqual(nilai[1], pertama)
                self.assertEqual(nilai[12], terakhir)


class BulanKalenderTests(unittest.TestCase):
    def test_adalah_bulan_kalender(self):
        kasus = [
            ("Oktober penuh (31 hari)", date(2026, 10, 1), date(2026, 10, 31), True),
            ("September penuh (30 hari)", date(2026, 9, 1), date(2026, 9, 30), True),
            ("Februari biasa", date(2026, 2, 1), date(2026, 2, 28), True),
            ("Februari kabisat", date(2028, 2, 1), date(2028, 2, 29), True),
            ("Desember penuh", date(2026, 12, 1), date(2026, 12, 31), True),
            ("Februari kabisat berhenti tanggal 28", date(2028, 2, 1), date(2028, 2, 28), False),
            ("gajian 25: 25 Sep sampai 24 Okt", date(2026, 9, 25), date(2026, 10, 24), False),
            ("berakhir sehari sebelum akhir bulan 31 hari", date(2026, 10, 1), date(2026, 10, 30), False),
            ("berakhir sehari sebelum akhir bulan 30 hari", date(2026, 9, 1), date(2026, 9, 29), False),
            ("mulai tanggal 2", date(2026, 10, 2), date(2026, 10, 31), False),
            ("tanggal 1 sampai akhir bulan berikutnya", date(2026, 10, 1), date(2026, 11, 30), False),
            ("tanggal 1 sampai akhir bulan yang sama tahun depan", date(2026, 10, 1), date(2027, 10, 31), False),
        ]
        for nama, ps, pe, diharapkan in kasus:
            with self.subTest(nama):
                self.assertIs(adalah_bulan_kalender(ps, pe), diharapkan)


class JudulTests(unittest.TestCase):
    def test_judul(self):
        self.assertEqual(judul_bulanan(date(2026, 10, 1), date(2026, 10, 31)), "Laporan Oktober 2026")
        self.assertEqual(judul_bulanan(date(2026, 9, 25), date(2026, 10, 24)), "Laporan 25 Sep – 24 Okt 2026")
        self.assertEqual(judul_bulanan(date(2026, 12, 25), date(2027, 1, 24)), "Laporan 25 Des 2026 – 24 Jan 2027")
        self.assertEqual(judul_bulanan(date(2026, 1, 31), date(2026, 2, 27)), "Laporan 31 Jan – 27 Feb 2026")

    def test_bulan_kalender_memakai_nama_penuh_untuk_setiap_bulan(self):
        kasus = [
            (date(2026, 1, 1), date(2026, 1, 31), "Laporan Januari 2026"),
            (date(2026, 2, 1), date(2026, 2, 28), "Laporan Februari 2026"),
            (date(2026, 3, 1), date(2026, 3, 31), "Laporan Maret 2026"),
            (date(2026, 4, 1), date(2026, 4, 30), "Laporan April 2026"),
            (date(2026, 5, 1), date(2026, 5, 31), "Laporan Mei 2026"),
            (date(2026, 6, 1), date(2026, 6, 30), "Laporan Juni 2026"),
            (date(2026, 7, 1), date(2026, 7, 31), "Laporan Juli 2026"),
            (date(2026, 8, 1), date(2026, 8, 31), "Laporan Agustus 2026"),
            (date(2026, 9, 1), date(2026, 9, 30), "Laporan September 2026"),
            (date(2026, 10, 1), date(2026, 10, 31), "Laporan Oktober 2026"),
            (date(2026, 11, 1), date(2026, 11, 30), "Laporan November 2026"),
            (date(2026, 12, 1), date(2026, 12, 31), "Laporan Desember 2026"),
        ]
        for ps, pe, diharapkan in kasus:
            with self.subTest(diharapkan):
                self.assertEqual(judul_bulanan(ps, pe), diharapkan)

    def test_periode_lintas_bulan_memakai_singkatan_untuk_setiap_bulan(self):
        kasus = [
            (date(2026, 1, 20), date(2026, 2, 19), "Laporan 20 Jan – 19 Feb 2026"),
            (date(2026, 2, 20), date(2026, 3, 19), "Laporan 20 Feb – 19 Mar 2026"),
            (date(2026, 3, 20), date(2026, 4, 19), "Laporan 20 Mar – 19 Apr 2026"),
            (date(2026, 4, 20), date(2026, 5, 19), "Laporan 20 Apr – 19 Mei 2026"),
            (date(2026, 5, 20), date(2026, 6, 19), "Laporan 20 Mei – 19 Jun 2026"),
            (date(2026, 6, 20), date(2026, 7, 19), "Laporan 20 Jun – 19 Jul 2026"),
            (date(2026, 7, 20), date(2026, 8, 19), "Laporan 20 Jul – 19 Agu 2026"),
            (date(2026, 8, 20), date(2026, 9, 19), "Laporan 20 Agu – 19 Sep 2026"),
            (date(2026, 9, 20), date(2026, 10, 19), "Laporan 20 Sep – 19 Okt 2026"),
            (date(2026, 10, 20), date(2026, 11, 19), "Laporan 20 Okt – 19 Nov 2026"),
            (date(2026, 11, 20), date(2026, 12, 19), "Laporan 20 Nov – 19 Des 2026"),
            (date(2026, 12, 20), date(2027, 1, 19), "Laporan 20 Des 2026 – 19 Jan 2027"),
        ]
        for ps, pe, diharapkan in kasus:
            with self.subTest(diharapkan):
                self.assertEqual(judul_bulanan(ps, pe), diharapkan)

    def test_hari_satu_digit_tanpa_nol_di_depan(self):
        self.assertEqual(judul_bulanan(date(2026, 9, 5), date(2026, 10, 4)), "Laporan 5 Sep – 4 Okt 2026")
        self.assertEqual(judul_bulanan(date(2026, 12, 5), date(2027, 1, 4)), "Laporan 5 Des 2026 – 4 Jan 2027")

    def test_sebagian_bulan_tidak_diringkas_jadi_nama_bulan(self):
        self.assertEqual(judul_bulanan(date(2026, 10, 1), date(2026, 10, 30)), "Laporan 1 Okt – 30 Okt 2026")

    def test_pemisah_adalah_en_dash_u2013_dengan_spasi_di_kedua_sisi(self):
        # Kode titik ditulis lewat chr() supaya tanda hubung biasa ("-") atau tanda lain tidak lolos tanpa terlihat.
        en_dash = chr(0x2013)
        self.assertEqual(
            judul_bulanan(date(2026, 9, 25), date(2026, 10, 24)), f"Laporan 25 Sep {en_dash} 24 Okt 2026"
        )
        self.assertEqual(
            judul_bulanan(date(2026, 12, 25), date(2027, 1, 24)), f"Laporan 25 Des 2026 {en_dash} 24 Jan 2027"
        )


class NamaFileTests(unittest.TestCase):
    def test_nama_file(self):
        self.assertEqual(nama_file_pdf("bulanan", date(2026, 10, 1), date(2026, 10, 31)), "jatahku-laporan-2026-10.pdf")
        self.assertEqual(
            nama_file_pdf("bulanan", date(2026, 9, 25), date(2026, 10, 24)), "jatahku-laporan-2026-09-25.pdf"
        )

    def test_bulan_dan_hari_satu_digit_diberi_nol_di_depan(self):
        self.assertEqual(nama_file_pdf("bulanan", date(2026, 3, 1), date(2026, 3, 31)), "jatahku-laporan-2026-03.pdf")
        self.assertEqual(
            nama_file_pdf("bulanan", date(2026, 3, 5), date(2026, 4, 4)), "jatahku-laporan-2026-03-05.pdf"
        )

    def test_periode_lintas_tahun_memakai_tanggal_awal(self):
        self.assertEqual(
            nama_file_pdf("bulanan", date(2026, 12, 25), date(2027, 1, 24)), "jatahku-laporan-2026-12-25.pdf"
        )

    def test_jenis_selain_bulanan_ditolak(self):
        # Tahap 3 menambah jenis lain; sampai itu tiba, nama file untuk jenis tak dikenal tidak boleh dikarang.
        for jenis in ("kuartalan", "tahunan", ""):
            with self.subTest(jenis):
                with self.assertRaises(ValueError):
                    nama_file_pdf(jenis, date(2026, 10, 1), date(2026, 10, 31))


class StatusAmplopTests(unittest.TestCase):
    def test_status_amplop(self):
        # (nama, tujuan, awal, terpakai, akhir, status); baris 1, 4, 6, 7, 8 dari brief.
        kasus = [
            ("tabungan mengalahkan lewat batas", "saving", D(100), D(200), D(-100), "tabungan"),
            ("sinking_fund juga tabungan", "sinking_fund", D(100), D(200), D(-100), "tabungan"),
            ("tabungan mengalahkan kosong", "saving", D(0), D(0), D(0), "tabungan"),
            ("akhir negatif", "expense", D(100), D(150), D(-50), "lewat_batas"),
            ("lewat batas mengalahkan kosong", "expense", D(0), D(50), D(-50), "lewat_batas"),
            ("tanpa saldo awal dan tanpa pakai", "expense", D(0), D(0), D(0), "kosong"),
            ("tepat 70 persen terpakai", "expense", D(100), D(70), D(30), "hampir_habis"),
            ("69 persen terpakai", "expense", D(100), D(69), D(31), "aman"),
            ("69,99 persen terpakai", "expense", D(100), D("69.99"), D("30.01"), "aman"),
            ("habis tepat tidak dihitung lewat batas", "expense", D(100), D(100), D(0), "hampir_habis"),
            ("belum terpakai", "expense", D(100), D(0), D(100), "aman"),
            ("utang mengikuti ambang seperti pengeluaran", "debt", D(100), D(80), D(20), "hampir_habis"),
            ("ambang 70 persen pada nominal rupiah besar", "expense", D(1000000), D(700000), D(300000), "hampir_habis"),
            ("tepat di bawah ambang pada nominal besar", "expense", D(1000000), D("699999.99"), D("300000.01"), "aman"),
        ]
        for nama, tujuan, awal, terpakai, akhir, diharapkan in kasus:
            with self.subTest(nama):
                self.assertEqual(status_amplop(tujuan, awal, terpakai, akhir), diharapkan)

    def test_ambang_dibaca_dari_konstanta_modul(self):
        # Spec 2d: ambang jadi satu konstanta di modul laporan; ubah satu nilai, status ikut berubah.
        self.assertEqual(status_amplop("expense", D(100), D(50), D(50)), "aman")
        with patch.object(hitung, "AMBANG_HAMPIR_HABIS", D("0.5")):
            self.assertEqual(status_amplop("expense", D(100), D(50), D(50)), "hampir_habis")


class PernahLewatBatasTests(unittest.TestCase):
    def test_pernah_lewat_batas(self):
        ps, pe = d(1), d(31)
        kasus = [
            # (nama, rollover_masuk, alokasi per hari, belanja per hari, ps, pe, diharapkan); tiga pertama dari brief
            ("belanja 120 pada 3 Okt mendahului alokasi 50 pada 5 Okt",
             D(0), {d(1): D(100), d(5): D(50)}, {d(3): D(120)}, ps, pe, True),
            ("tanpa belanja 120", D(0), {d(1): D(100), d(5): D(50)}, {}, ps, pe, False),
            ("alokasi dan belanja di hari yang sama", D(0), {d(1): D(100)}, {d(1): D(100)}, ps, pe, False),
            ("saldo tepat nol bukan lewat batas", D(0), {d(1): D(100)}, {d(3): D(100)}, ps, pe, False),
            ("kurang satu sen", D(0), {d(1): D(100)}, {d(3): D("100.01")}, ps, pe, True),
            ("tidak ada kejadian sama sekali", D(0), {}, {}, ps, pe, False),
            ("rollover masuk menutup belanja tepat", D(100), {}, {d(2): D(100)}, ps, pe, False),
            ("rollover masuk kurang satu", D(100), {}, {d(2): D(101)}, ps, pe, True),
            ("belanja tersebar habiskan rollover tepat nol", D(100), {}, {d(1): D(60), d(2): D(40)}, ps, pe, False),
            ("belanja di hari pertama melebihi saldo", D(0), {}, {d(1): D(1)}, ps, pe, True),
            ("belanja di hari terakhir melebihi saldo", D(0), {d(1): D(100)}, {d(31): D(101)}, ps, pe, True),
            ("belanja sesudah periode diabaikan", D(0), {d(1): D(100)}, {date(2026, 11, 1): D(500)}, ps, pe, False),
            ("belanja sebelum periode diabaikan", D(0), {d(1): D(100)}, {date(2026, 9, 30): D(500)}, ps, pe, False),
            ("alokasi sesudah periode tidak menolong",
             D(0), {date(2026, 11, 1): D(1000)}, {d(31): D(50)}, ps, pe, True),
            # rollover negatif nyata (opening = alokasi + rollover; rollover bisa minus)
            ("rollover negatif tanpa alokasi", D(-50), {}, {}, ps, pe, True),
            ("rollover negatif tertutup alokasi hari pertama", D(-50), {d(1): D(100)}, {}, ps, pe, False),
            ("rollover negatif baru tertutup alokasi tanggal 5", D(-50), {d(5): D(100)}, {}, ps, pe, True),
            # periode gajian lintas bulan dan tahun harus dilewati hari demi hari
            ("lintas tahun: kurang satu pada 1 Jan",
             D(0), {date(2026, 12, 25): D(100)}, {date(2027, 1, 1): D(101)},
             date(2026, 12, 25), date(2027, 1, 24), True),
            ("lintas tahun: tepat nol pada 1 Jan",
             D(0), {date(2026, 12, 25): D(100)}, {date(2027, 1, 1): D(100)},
             date(2026, 12, 25), date(2027, 1, 24), False),
            # periode satu hari
            ("satu hari: belanja melebihi alokasi", D(0), {d(5): D(10)}, {d(5): D(20)}, d(5), d(5), True),
            ("satu hari: alokasi sama dengan belanja", D(0), {d(5): D(20)}, {d(5): D(20)}, d(5), d(5), False),
        ]
        for nama, rollover, alokasi, belanja, mulai, akhir, diharapkan in kasus:
            with self.subTest(nama):
                self.assertIs(pernah_lewat_batas(rollover, alokasi, belanja, mulai, akhir), diharapkan)


class BeruntunTests(unittest.TestCase):
    def test_beruntun(self):
        self.assertEqual(beruntun_terpanjang([]), 0)
        self.assertEqual(beruntun_terpanjang([d(1), d(2), d(3), d(5), d(6)]), 3)  # d(n) = date(2026, 10, n)

    def test_beruntun_kasus_lain(self):
        kasus = [
            ("satu hari", [d(5)], 1),
            ("beruntun pertama yang terpanjang", [d(1), d(2), d(3), d(4), d(6), d(7)], 4),
            ("beruntun terpanjang di tengah", [d(1), d(2), d(4), d(5), d(6), d(7), d(9)], 4),
            ("imbang menghasilkan panjangnya", [d(1), d(2), d(4), d(5)], 2),
            ("celah satu hari memutus", [d(1), d(3)], 1),
            ("masukan tak berurutan", [d(3), d(1), d(2)], 3),
            ("tanggal ganda dihitung sekali", [d(1), d(1), d(2)], 2),
            ("tanggal ganda di tengah rentetan tidak memutusnya", [d(1), d(2), d(2), d(3)], 3),
            ("semua tanggal sama", [d(4), d(4), d(4)], 1),
            ("lintas bulan dan tahun", [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1)], 3),
            ("28 Feb ke 1 Mar tahun biasa berurutan", [date(2026, 2, 28), date(2026, 3, 1)], 2),
            ("Februari kabisat punya tanggal 29", [date(2028, 2, 28), date(2028, 2, 29), date(2028, 3, 1)], 3),
        ]
        for nama, tanggal, diharapkan in kasus:
            with self.subTest(nama):
                self.assertEqual(beruntun_terpanjang(tanggal), diharapkan)

    def test_menerima_iterable_sekali_pakai_dan_himpunan(self):
        self.assertEqual(beruntun_terpanjang(d(n) for n in (1, 2, 3)), 3)
        self.assertEqual(beruntun_terpanjang({d(1), d(2), d(4)}), 2)


class PersenDanUangTests(unittest.TestCase):
    def test_persen_dan_uang(self):
        self.assertEqual(persen(D("1"), D("3")), 33)
        self.assertIsNone(persen(D(5), D(0)))
        self.assertEqual(persen_perubahan(D(88), D(100)), -12)
        self.assertIsNone(persen_perubahan(D(5), None))
        self.assertEqual(uang(D("1.005")), "1.01")


class PersenTests(unittest.TestCase):
    def test_pembulatan_setengah_ke_atas(self):
        # 12,5 dan 0,5 dan 2,5 adalah titik tengah: round() bulat-genap memberi 12, 0, 2; harapan 13, 1, 3.
        kasus = [
            (D(1), D(8), 13),        # 12,5
            (D(1), D(200), 1),       # 0,5
            (D(1), D(40), 3),        # 2,5
            (D(2), D(3), 67),        # 66,67
            (D(31), D(250), 12),     # 12,4: di bawah titik tengah turun
            (D(49), D(10000), 0),    # 0,49
        ]
        for bagian, total, diharapkan in kasus:
            with self.subTest(f"{bagian}/{total}"):
                self.assertEqual(persen(bagian, total), diharapkan)

    def test_total_nol_atau_negatif_tidak_punya_persen(self):
        for total in (D(0), D(-1)):
            with self.subTest(total):
                self.assertIsNone(persen(D(5), total))
        self.assertIsNone(persen(D(0), D(0)))

    def test_bagian_nol_adalah_nol_bukan_none(self):
        self.assertEqual(persen(D(0), D(100)), 0)

    def test_tidak_dibatasi_seratus(self):
        self.assertEqual(persen(D(100), D(100)), 100)
        self.assertEqual(persen(D(150), D(100)), 150)

    def test_hasil_bertipe_int_agar_bisa_masuk_json(self):
        self.assertIs(type(persen(D(1), D(3))), int)


class PersenPerubahanTests(unittest.TestCase):
    def test_naik_turun_dan_tetap(self):
        kasus = [
            (D(112), D(100), 12),
            (D(150), D(100), 50),
            (D(100), D(100), 0),
            (D(0), D(100), -100),
            (D(2), D(3), -33),       # -33,33
            (D(4), D(3), 33),        # 33,33
            (D(1500000), D(1000000), 50),
        ]
        for sekarang, lalu, diharapkan in kasus:
            with self.subTest(f"{sekarang} vs {lalu}"):
                self.assertEqual(persen_perubahan(sekarang, lalu), diharapkan)

    def test_pembulatan_setengah_menjauhi_nol(self):
        kasus = [
            (D("112.5"), D(100), 13),     # +12,5
            (D("87.5"), D(100), -13),     # -12,5: ROUND_HALF_UP menjauhi nol, bukan floor(x + 0,5) yang memberi -12
            (D("100.4"), D(100), 0),      # +0,4
            (D("99.6"), D(100), 0),       # -0,4
        ]
        for sekarang, lalu, diharapkan in kasus:
            with self.subTest(f"{sekarang} vs {lalu}"):
                self.assertEqual(persen_perubahan(sekarang, lalu), diharapkan)

    def test_tanpa_pembanding_yang_berarti_none(self):
        # None = periode lalu tanpa angka; nol dan negatif tidak bisa jadi dasar persen.
        for lalu in (None, D(0), D(-10)):
            with self.subTest(lalu):
                self.assertIsNone(persen_perubahan(D(5), lalu))
        self.assertIsNone(persen_perubahan(D(0), D(0)))

    def test_hasil_bertipe_int_agar_bisa_masuk_json(self):
        self.assertIs(type(persen_perubahan(D(88), D(100))), int)
        self.assertIs(type(persen_perubahan(D("99.6"), D(100))), int)


class RataRataTests(unittest.TestCase):
    def test_tanpa_nilai_sama_sekali_adalah_none(self):
        for nama, nilai in [("kosong", []), ("satu None", [None]), ("semua None", [None, None, None])]:
            with self.subTest(nama):
                self.assertIsNone(rata_rata(nilai))

    def test_none_dilewati_dan_tidak_masuk_pembagi(self):
        # Periode tanpa snapshot (None) tidak dihitung; rata-rata 10 dan 20 adalah 15, bukan 10.
        self.assertEqual(rata_rata([D(10), None, D(20)]), D(15))
        self.assertEqual(rata_rata([None, D(100), None]), D(100))

    def test_nol_adalah_nilai_nyata_dan_ikut_dihitung(self):
        self.assertEqual(rata_rata([D(0), D(10)]), D(5))
        self.assertEqual(rata_rata([D(0)]), D(0))

    def test_hasil_decimal_eksak_tanpa_float(self):
        hasil = rata_rata([D("0.10"), D("0.20")])
        self.assertIsInstance(hasil, Decimal)
        self.assertEqual(hasil, D("0.15"))
        self.assertEqual(rata_rata([D(10), D(20), D(30)]), D(20))

    def test_tidak_dibulatkan_agar_pembulatan_hanya_sekali_di_uang(self):
        hasil = rata_rata([D(1), D(2), D(4)])  # 7/3
        self.assertTrue(D("2.3333") < hasil < D("2.3334"), hasil)


class UangTests(unittest.TestCase):
    def test_dua_desimal_setengah_ke_atas(self):
        kasus = [
            ("1.005", "1.01"),             # float memberi 1.00
            ("2.675", "2.68"),             # float memberi 2.67
            ("0.005", "0.01"),
            ("0.004", "0.00"),
            ("1234567.891", "1234567.89"),
            ("-1.005", "-1.01"),           # setengah menjauhi nol
            ("-12.345", "-12.35"),
            ("-0.005", "-0.01"),
        ]
        for masukan, diharapkan in kasus:
            with self.subTest(masukan):
                self.assertEqual(uang(D(masukan)), diharapkan)

    def test_selalu_dua_desimal_tanpa_notasi_ilmiah_atau_pemisah_ribuan(self):
        kasus = [
            ("5", "5.00"),
            ("0", "0.00"),
            ("0.1", "0.10"),
            ("12.3", "12.30"),
            ("-5", "-5.00"),
            ("1500000", "1500000.00"),
            ("1E+6", "1000000.00"),
        ]
        for masukan, diharapkan in kasus:
            with self.subTest(masukan):
                self.assertEqual(uang(D(masukan)), diharapkan)

    def test_nol_negatif_ditulis_nol(self):
        # Pembulatan angka negatif sangat kecil: quantize menjaga tandanya ("-0.00"); laporan beku tak boleh memuatnya.
        for masukan in ("-0.004", "-0.00"):
            with self.subTest(masukan):
                self.assertEqual(uang(D(masukan)), "0.00")

    def test_hasil_bertipe_str(self):
        self.assertIs(type(uang(D("1.5"))), str)


class TeksSorotanTests(unittest.TestCase):
    def test_teks_sorotan(self):
        self.assertEqual(teks_sorotan(7, 0, 9), "Mencatat 7 hari berturut-turut")
        self.assertEqual(teks_sorotan(6, 2, 9), "2 amplop tidak pernah lewat batas")
        self.assertEqual(teks_sorotan(0, 0, 3), "Mencatat di 3 hari")
        self.assertEqual(teks_sorotan(0, 0, 0), "Siap untuk periode berikutnya")

    def test_urutan_prioritas_dan_batasnya(self):
        kasus = [
            ("beruntun menang atas amplop aman", (12, 5, 20), "Mencatat 12 hari berturut-turut"),
            ("beruntun 6 belum cukup, tanpa amplop aman jatuh ke hari mencatat", (6, 0, 9), "Mencatat di 9 hari"),
            ("satu amplop aman sudah cukup", (0, 1, 4), "1 amplop tidak pernah lewat batas"),
            ("amplop aman menang atas hari mencatat", (3, 4, 5), "4 amplop tidak pernah lewat batas"),
            ("satu hari mencatat sudah cukup", (0, 0, 1), "Mencatat di 1 hari"),
        ]
        for nama, (beruntun, amplop_aman, hari_mencatat), diharapkan in kasus:
            with self.subTest(nama):
                self.assertEqual(teks_sorotan(beruntun, amplop_aman, hari_mencatat), diharapkan)


if __name__ == "__main__":
    unittest.main()
