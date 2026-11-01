"""Laporan berkala tahap 1, Task 6: PDF ber-AES-256 (`app/services/laporan/pdf.py`; spec
2026-11-01-laporan-berkala-design bagian 4). Fixture: `data` v1 dari `susun_bulanan` atas `BahanLaporan` pabrik
`test_laporan_susun`, jadi kunci yang dibaca PDF selalu yang dihasilkan penyusun. PDF dibuka dengan `pypdfium2` (kata
sandi pengguna) dan isinya dibaca dari lapisan teks; tata letak tidak dicocokkan piksel demi piksel, kecuali dua hal:
letak kolom jumlah di lampiran mutasi (tepi kanan angka dibandingkan dengan tepi kanan judul kolomnya) dan latar sel
badan tabel (satu piksel di bantalan sel dibaca dari hasil render).
Karakter tak kasatmata atau dua arah ditulis dengan `\\N{...}`/`\\x..`, tidak sebagai karakter mentah di sumber.
Run: python -m unittest app.tests.test_laporan_pdf -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import copy
import gc
import hashlib
import io
import re
import time
import traceback
import unittest
import warnings
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pypdfium2 as pdfium
from fpdf import FPDF
from fpdf.enums import AccessPermission, EncryptionMethod
from fpdf.fonts import SubsetMap, TTFFont
from pypdfium2 import PdfiumError

from app.services.laporan import pdf
from app.services.laporan.susun import PemasukanPeriode, TagihanBerikut, TargetTabungan, susun_bulanan
from app.tests.test_laporan_susun import amplop_kecil, bahan, bahan_kosong, d, txn

D = Decimal
KATA_SANDI = "rahasia123"
DIR_FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts"
SHA256_FONT = {
    "NotoSans-Regular.ttf": "f5f552c8c5edb61fe6efb824baf4d4de47b1a8689ab4925ff43f7bd6a4ebece5",
    "NotoSans-Bold.ttf": "3a08a47daa00cade516425c15c57615aef2fd418ec9811a7b9f465088f92cc05",
}
# Urutan judul bagian di PDF (Global Constraints: persis).
JUDUL_BAGIAN = [
    "Ringkasan", "Amplop", "Dibanding periode lalu", "Pola harian", "5 pengeluaran terbesar", "Langganan", "Sorotan",
    "Lampiran: mutasi",
]
ALEF = "\N{ARABIC LETTER ALEF}"
BEH = "\N{ARABIC LETTER BEH}"
PENGGANTI = "\N{REPLACEMENT CHARACTER}"


def buka(isi: bytes, kata_sandi: str | None = KATA_SANDI) -> pdfium.PdfDocument:
    return pdfium.PdfDocument(io.BytesIO(isi), password=kata_sandi)


def teks_per_halaman(isi: bytes, kata_sandi: str | None = KATA_SANDI) -> list[str]:
    """Teks tiap halaman dari lapisan teks PDF, spasi dirapatkan (pdfium menyisipkan CRLF antarbaris)."""
    doc = buka(isi, kata_sandi)
    try:
        hasil = []
        for i in range(len(doc)):
            halaman = doc[i]
            teks = halaman.get_textpage()
            hasil.append(" ".join(teks.get_text_range().split()))
            teks.close()
            halaman.close()
        return hasil
    finally:
        doc.close()


def tepi_kanan(isi: bytes, kata: str, halaman: int = -1) -> float:
    """Koordinat x (poin) tepi kanan kemunculan terakhir `kata` di `halaman`, dari kotak karakter pdfium."""
    doc = buka(isi)
    try:
        hal = doc[halaman % len(doc)]
        teks = hal.get_textpage()
        semua = teks.get_text_range()
        awal = semua.rfind(kata)
        assert awal >= 0, f"{kata!r} tidak ada di halaman {halaman}"
        kanan = teks.get_charbox(awal + len(kata) - 1)[2]
        teks.close()
        hal.close()
        return kanan
    finally:
        doc.close()


def teks_mentah(isi: bytes, halaman: int) -> str:
    """Teks satu halaman apa adanya dari pdfium: tiap baris tergambar dipisah CRLF, spasi tidak dirapatkan. Dua kata
    yang tergambar sebagai satu teks tetap berdampingan di sini; yang dibungkus ke baris kedua dipisah CRLF."""
    doc = buka(isi)
    try:
        hal = doc[halaman]
        teks = hal.get_textpage()
        semua = teks.get_text_range()
        teks.close()
        hal.close()
        return semua
    finally:
        doc.close()


def warna_di_kiri(isi: bytes, kata: str, halaman: int, setelah: str = "", geser: float = 2.0) -> tuple[int, int, int]:
    """Warna piksel (RGB) `geser` poin di kiri huruf pertama `kata` (kemunculan pertama setelah `setelah`), setinggi
    tengah huruf. Di tabel titik itu ada di bantalan kiri sel (1,8 mm), jadi warnanya latar sel."""
    skala = 2.0
    doc = buka(isi)
    try:
        hal = doc[halaman]
        teks = hal.get_textpage()
        semua = teks.get_text_range()
        indeks = semua.index(kata, semua.index(setelah) if setelah else 0)
        kiri, bawah, _, atas = teks.get_charbox(indeks)
        gambar = hal.render(scale=skala).to_pil().convert("RGB")
        x, y = round((kiri - geser) * skala), round((hal.get_size()[1] - (bawah + atas) / 2) * skala)
        teks.close()
        hal.close()
        return gambar.getpixel((x, y))
    finally:
        doc.close()


KETERANGAN = [
    "Makan siang", "Kopi", "Bensin", "Parkir", "Listrik", "Ojek online", "Es teh manis",
    "Belanja mingguan di pasar induk dan toko sebelah rumah (sayur, buah, lauk, bumbu dapur, sabun cuci)",
    "🍔 Burger 🍟", "Tak tercatat (cocokkan saldo)",
]


def bahan_banyak(n: int):
    """`n` pengeluaran di dua amplop sepanjang Oktober 2026 (keterangan beragam, ada yang panjang dan beremoji, tiap
    keterangan diakhiri penanda unik `#k`), dua pemasukan, dan satu amplop tabungan; angka amplop konsisten dengan
    jumlah transaksi."""
    transaksi = [
        txn(
            id=f"t{k}", amplop_id=("env-s", "env-p")[k % 2], tanggal=d(1 + k % 31),
            jumlah=D(5_000 + (k * 7_919) % 95_000 // 100 * 100), keterangan=f"{KETERANGAN[k % len(KETERANGAN)]} #{k}",
            pencatat="Budi" if k % 3 == 0 else "Ani", milik_penerima=k % 3 != 0,
        )
        for k in range(n)
    ]
    terpakai = {i: sum((t.jumlah for t in transaksi if t.amplop_id == i), D(0)) for i in ("env-s", "env-p")}
    return bahan(
        amplop=[
            amplop_kecil("env-s", "Kebutuhan", 20_000_000, terpakai["env-s"]),
            amplop_kecil("env-p", "Jajan", 20_000_000, terpakai["env-p"], pribadi=True),
            amplop_kecil("env-t", "Dana darurat", 500_000, 0, tujuan="saving"),
        ],
        transaksi=transaksi,
    )


def bahan_serba_kosong():
    """Setiap nilai yang boleh `null` di kontrak `data` v1 memang `null`: persen terpakai (hanya amplop tabungan),
    seluruh pembanding, hari terboros, amplop tagihan berikut (di luar bahan), dan persen target (target nol)."""
    return bahan(
        amplop=[
            amplop_kecil("env-t", "Dana darurat", 500_000, 0, tujuan="saving", terpakai_lalu=[None, None, None]),
        ],
        transaksi=[],
        pemasukan=[],
        tagihan_berikut=[TagihanBerikut(date(2026, 11, 5), "Asuransi", "env-hilang", D(150_000))],
        target=[TargetTabungan("Tanpa target", "env-t", D(0))],
        streak_saat_ini=0,
        terpakai_lalu_total=[None, None, None],
    )


def bahan_beremoji():
    return bahan(
        amplop=[
            amplop_kecil("env-s", "🍔 Makan", 500_000, 150_000),
            amplop_kecil("env-t", "Dana darurat", 500_000, 0, tujuan="saving"),
        ],
        transaksi=[
            txn(id="t1", amplop_id="env-s", tanggal=d(12), jumlah=D(54_000), keterangan="🔄 Netflix →", tagihan=True),
            txn(id="t2", amplop_id="env-s", tanggal=d(14), jumlah=D(96_000), keterangan="Sate → Bakso 🍢"),
        ],
        tagihan_berikut=[TagihanBerikut(date(2026, 11, 12), "Netflix →", "env-s", D(54_000))],
        target=[TargetTabungan("Liburan \N{AIRPLANE}\N{VARIATION SELECTOR-16}", "env-t", D(1_000_000))],
    )


DATA = susun_bulanan(bahan())
DATA_BANYAK = susun_bulanan(bahan_banyak(300))


class RupiahTests(unittest.TestCase):
    def test_rupiah(self):
        for nilai, harapan in [
            ("1234567.00", "Rp1.234.567"),
            ("-12000.00", "-Rp12.000"),
            ("0.00", "Rp0"),
            ("500.00", "Rp500"),
            ("1000.00", "Rp1.000"),
            ("1234567890123.00", "Rp1.234.567.890.123"),
        ]:
            with self.subTest(nilai):
                self.assertEqual(pdf.rupiah(nilai), harapan)

    def test_rupiah_dibulatkan_ke_rupiah_utuh(self):
        # Angka laporan berpecahan sen (dua desimal); tampilan rupiah utuh, ROUND_HALF_UP menjauhi nol.
        for nilai, harapan in [
            ("1234.49", "Rp1.234"),
            ("1234.50", "Rp1.235"),
            ("999.99", "Rp1.000"),
            ("-1234.50", "-Rp1.235"),
            ("0.49", "Rp0"),
        ]:
            with self.subTest(nilai):
                self.assertEqual(pdf.rupiah(nilai), harapan)

    def test_rupiah_nol_setelah_pembulatan_tanpa_tanda_minus(self):
        self.assertEqual(pdf.rupiah("-0.40"), "Rp0")
        self.assertEqual(pdf.rupiah("-0.00"), "Rp0")


class TeksPdfTests(unittest.TestCase):
    def test_emoji_dan_panah_dibuang_huruf_dipertahankan(self):
        self.assertEqual(pdf.teks_pdf("🍔 Makan"), "Makan")
        self.assertEqual(pdf.teks_pdf("🔄 Netflix →"), "Netflix")
        self.assertEqual(pdf.teks_pdf("Sate → Bakso 🍢"), "Sate Bakso")

    def test_huruf_tanda_baca_dan_pemisah_rentang_dipertahankan(self):
        for teks in [
            "Kopi susu 35k", "Café é ñ ü", "1 Okt – 31 Okt 2026", "Rp1.234.567 (sewa) · lunas", "Tak tercatat",
        ]:
            with self.subTest(teks):
                self.assertEqual(pdf.teks_pdf(teks), teks)

    def test_baris_baru_dan_tab_jadi_spasi_dan_spasi_dirapatkan(self):
        self.assertEqual(pdf.teks_pdf("beli\nkopi\tsusu\r\n  hangat"), "beli kopi susu hangat")
        self.assertEqual(pdf.teks_pdf("  a\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}b  "), "a b")

    def test_karakter_kontrol_dan_format_dibuang(self):
        # Penyambung emoji, tanda hubung lunak, BOM, dan NUL ada di cmap Noto Sans tetapi tidak berguna di PDF
        # (tanda hubung lunak malah tergambar sebagai tanda hubung di tengah kata).
        kotor = "ko\N{SOFT HYPHEN}pi\N{ZERO WIDTH JOINER}\N{ZERO WIDTH NO-BREAK SPACE}\x00 susu"
        self.assertEqual(pdf.teks_pdf(kotor), "kopi susu")

    def test_gabungan_diseragamkan_ke_nfc(self):
        self.assertEqual(pdf.teks_pdf("cafe\N{COMBINING ACUTE ACCENT}"), "caf\N{LATIN SMALL LETTER E WITH ACUTE}")

    def test_kosong_dan_semuanya_terbuang(self):
        self.assertEqual(pdf.teks_pdf(""), "")
        self.assertEqual(pdf.teks_pdf("🍔🍟 →"), "")

    def test_hasilnya_tidak_pernah_membuat_fpdf2_mengeluh_soal_glyph(self):
        # fpdf2 mencatat "Font ... is missing the following glyphs" saat output(); semua karakter hasil teks_pdf ada
        # di cmap.
        coba = (
            "🍔 Makan → 🔄 Netflix \N{AIRPLANE}\N{VARIATION SELECTOR-16} 餐费 " + ALEF + BEH
            + " \N{CHECK MARK} \N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16} é ñ – · •"
        )

        def render(teks: str) -> None:
            dokumen = FPDF(format="A4")
            dokumen.add_font("NotoSans", "", str(pdf.FONT_REGULAR))
            dokumen.add_page()
            dokumen.set_font("NotoSans", "", 10)
            dokumen.cell(0, 6, teks)
            dokumen.output()

        # Kontrol positif: tanpa disaring, fpdf2 memang mengeluh (tes ini tidak lulus karena fpdf2 diam saja).
        with self.assertLogs("fpdf", level="WARNING") as tangkap:
            render(coba)
        self.assertIn("missing the following glyphs", "\n".join(tangkap.output))
        with self.assertNoLogs(level="WARNING"):
            render(pdf.teks_pdf(coba))
        self.assertEqual(pdf.teks_pdf(coba), "Makan Netflix é ñ – · •")


class RenderPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isi = pdf.render_pdf(DATA, KATA_SANDI)
        cls.halaman = teks_per_halaman(cls.isi)

    def test_terbuka_dengan_kata_sandi_dan_memuat_isi(self):
        self.assertTrue(self.isi.startswith(b"%PDF-"))
        halaman1 = self.halaman[0]
        for harapan in ["Laporan Oktober 2026", "Ringkasan", "Kebutuhan", "Jajan", "Dana darurat"]:
            with self.subTest(harapan):
                self.assertIn(harapan, halaman1)

    def test_a4_tegak(self):
        doc = buka(self.isi)
        try:
            lebar, tinggi = doc[0].get_size()
        finally:
            doc.close()
        self.assertAlmostEqual(lebar, 595.28, delta=0.5)
        self.assertAlmostEqual(tinggi, 841.89, delta=0.5)

    def test_header_memuat_merek_judul_periode_penerima_dan_tanggal_angka(self):
        halaman1 = self.halaman[0]
        for harapan in [
            "Jatahku", "Laporan Oktober 2026", "1 Oktober 2026 – 31 Oktober 2026", "Ani", "Rumah Ani",
            "Angka per 1 November 2026",
        ]:
            with self.subTest(harapan):
                self.assertIn(harapan, halaman1)

    def test_footer_dua_teks_di_setiap_halaman(self):
        jumlah = len(self.halaman)
        self.assertGreaterEqual(jumlah, 2)
        for n, teks in enumerate(self.halaman, start=1):
            with self.subTest(halaman=n):
                self.assertIn(f"Halaman {n} dari {jumlah}", teks)
                self.assertIn("Dibuat otomatis oleh Jatahku", teks)

    def test_setiap_halaman_memuat_tanggal_angka(self):
        for n, teks in enumerate(self.halaman, start=1):
            with self.subTest(halaman=n):
                self.assertIn("Angka per 1 November 2026", teks)

    def test_judul_bagian_persis_dan_berurutan(self):
        semua = " ".join(self.halaman)
        posisi = 0
        for judul in JUDUL_BAGIAN:
            with self.subTest(judul):
                ketemu = semua.find(judul, posisi)
                self.assertGreaterEqual(ketemu, 0, f"{judul!r} tidak ada setelah posisi {posisi}")
                posisi = ketemu + len(judul)

    def test_angka_diformat_apa_adanya_dari_data(self):
        semua = " ".join(self.halaman)
        for harapan in [
            "Rp5.500.000",   # pemasukan
            "Rp840.000",     # terpakai
            "Rp960.000",     # sisa
            "Rp900.000",     # dibawa
            "65%",           # persen_terpakai
            "Rp1.000.000",   # terpakai periode lalu
            "Rp700.000",     # rata-rata tiga periode
            "16%",           # perubahan -16
            "Rp250.000",     # hari terboros dan pengeluaran terbesar
            "Darurat 6 bulan", "Rp500.000", "50%",
            "Netflix", "Listrik",
        ]:
            with self.subTest(harapan):
                self.assertIn(harapan, semua)

    def test_status_amplop_dengan_kata_indonesia(self):
        semua = " ".join(self.halaman)
        for status in ["Aman", "Hampir habis", "Tabungan"]:
            with self.subTest(status):
                self.assertIn(status, semua)

    def test_tidak_ada_sisa_python_di_teks(self):
        semua = " ".join(self.halaman)
        for sisa in [r"\bNone\b", r"\bnan\b", r"[{}]", r"Decimal", PENGGANTI]:
            with self.subTest(sisa):
                self.assertIsNone(re.search(sisa, semua))

    def test_data_tidak_diubah(self):
        data = copy.deepcopy(DATA)
        pdf.render_pdf(data, KATA_SANDI)
        self.assertEqual(data, DATA)

    def test_kunci_email_tidak_dibaca(self):
        # `email` adalah isi badan email (tahap 2); PDF tidak boleh bergantung padanya.
        tanpa_email = {kunci: nilai for kunci, nilai in DATA.items() if kunci != "email"}
        halaman = teks_per_halaman(pdf.render_pdf(tanpa_email, KATA_SANDI))
        self.assertEqual(halaman, self.halaman)

    def test_nilai_null_dicetak_strip_dan_tidak_ada_yang_error(self):
        data = susun_bulanan(bahan_serba_kosong())
        # Prasyarat fixture: semua yang boleh null memang null.
        self.assertIsNone(data["ringkasan"]["persen_terpakai"])
        self.assertIsNone(data["banding"]["terpakai_lalu"])
        self.assertIsNone(data["banding"]["terpakai_rata3"])
        self.assertIsNone(data["banding"]["persen_perubahan"])
        self.assertIsNone(data["banding"]["amplop"][0]["terpakai_lalu"])
        self.assertIsNone(data["banding"]["amplop"][0]["terpakai_rata3"])
        self.assertIsNone(data["hari_terboros"])
        self.assertIsNone(data["langganan"]["jatuh_tempo"][0]["amplop"])
        self.assertIsNone(data["sorotan"]["target"][0]["persen"])
        semua = " ".join(teks_per_halaman(pdf.render_pdf(data, KATA_SANDI)))
        for nama, pola in [
            ("persen terpakai", r"Persen terpakai\s+—"),
            ("periode lalu", r"Periode lalu\s+—"),
            ("rata-rata", r"Rata-rata 3 periode\s+—"),
            ("perubahan", r"Perubahan\s+—"),
            ("baris banding amplop", r"Dana darurat\s+Rp0\s+—\s+—"),
            ("amplop tagihan berikut", r"Asuransi\s+—\s+Rp150\.000"),
            ("persen target", r"Tanpa target\s+—"),
        ]:
            with self.subTest(nama):
                self.assertRegex(semua, pola)
        self.assertIn("Tidak ada hari dengan pengeluaran", semua)
        self.assertNotIn("%", semua)   # tidak ada persen yang bisa dihitung, jadi tidak ada satu pun yang dicetak
        for sisa in [r"\bNone\b", r"\bnan\b"]:
            self.assertIsNone(re.search(sisa, semua))
        for judul in JUDUL_BAGIAN[:-1]:
            self.assertIn(judul, semua)

    def test_data_tanpa_apa_apa_tetap_menjadi_pdf_yang_utuh(self):
        data = susun_bulanan(bahan_kosong())
        halaman = teks_per_halaman(pdf.render_pdf(data, KATA_SANDI))
        semua = " ".join(halaman)
        for judul in JUDUL_BAGIAN:
            self.assertIn(judul, semua)
        self.assertIn(f"Halaman {len(halaman)} dari {len(halaman)}", halaman[-1])

    def test_periode_bukan_bulan_kalender_dan_lintas_tahun(self):
        data = susun_bulanan(bahan(
            periode_mulai=date(2026, 12, 25), periode_akhir=date(2027, 1, 24), payday=25, angka_per=date(2027, 1, 25),
            transaksi=[], pemasukan=[], tagihan_berikut=[], target=[],
        ))
        self.assertEqual(data["judul"], "Laporan 25 Des 2026 – 24 Jan 2027")
        halaman = teks_per_halaman(pdf.render_pdf(data, KATA_SANDI))
        self.assertIn("Laporan 25 Des 2026 – 24 Jan 2027", halaman[0])
        self.assertIn("25 Desember 2026 – 24 Januari 2027", halaman[0])
        self.assertIn("Angka per 25 Januari 2027", halaman[0])

    def test_nominal_sangat_besar_dan_negatif_tidak_merusak_tata_letak(self):
        besar = D("12345678901234.00")
        data = susun_bulanan(bahan(
            amplop=[amplop_kecil("env-s", "Kebutuhan", besar, besar + D(1_000_000), terpakai_lalu=[besar] * 3)],
            transaksi=[txn(id="t1", amplop_id="env-s", tanggal=d(3), jumlah=besar + D(1_000_000))],
            pemasukan=[PemasukanPeriode(d(1), besar, "Warisan")],
            tagihan_berikut=[], target=[],
            terpakai_lalu_total=[besar, besar, besar],
        ))
        halaman = teks_per_halaman(pdf.render_pdf(data, KATA_SANDI))
        semua = " ".join(halaman)
        # Satu angka satu baris: kalau kolom terlalu sempit, angka terpotong ke baris berikut dan pola ini gagal.
        self.assertIn("Rp12.345.678.901.234", semua)
        self.assertIn("Rp12.345.679.901.234", semua)   # terpakai = awal + 1.000.000
        self.assertIn("-Rp1.000.000", semua)           # saldo akhir negatif
        self.assertIn("Lewat batas", semua)

    def test_emoji_dan_penanda_dibuang(self):
        data = susun_bulanan(bahan_beremoji())
        # Prasyarat fixture: data memang masih memuat emoji dan panah; yang membuangnya PDF.
        self.assertEqual(data["amplop"][0]["nama"], "🍔 Makan")
        self.assertEqual(data["terbesar"][1]["keterangan"], "🔄 Netflix →")
        with self.assertNoLogs(level="WARNING"), warnings.catch_warnings(record=True) as peringatan:
            warnings.simplefilter("always")
            isi = pdf.render_pdf(data, KATA_SANDI)
        self.assertEqual([str(p.message) for p in peringatan], [])
        semua = " ".join(teks_per_halaman(isi))
        for terbuang in ["🍔", "🔄", "→", "🍢", "🍟", "\N{AIRPLANE}", PENGGANTI]:
            with self.subTest(terbuang):
                self.assertNotIn(terbuang, semua)
        for tetap in ["Makan", "Netflix", "Sate Bakso", "Liburan"]:
            with self.subTest(tetap):
                self.assertIn(tetap, semua)

    def test_nama_amplop_yang_seluruhnya_terbuang_diberi_tanda_strip(self):
        data = susun_bulanan(bahan(
            amplop=[amplop_kecil("env-s", "🍔🍟", 500_000, 100_000)],
            transaksi=[txn(id="t1", amplop_id="env-s", jumlah=D(100_000))],
            tagihan_berikut=[], target=[],
        ))
        halaman1 = teks_per_halaman(pdf.render_pdf(data, KATA_SANDI))[0]
        self.assertRegex(halaman1, r"—\s+Rp500\.000")

    def test_mutasi_panjang_multi_halaman(self):
        self.assertEqual(len(DATA_BANYAK["mutasi"]), 302)
        mulai = time.perf_counter()
        isi = pdf.render_pdf(DATA_BANYAK, KATA_SANDI)
        lama = time.perf_counter() - mulai
        self.assertLess(lama, 5.0, f"render 300 baris memakan {lama:.2f} detik")
        halaman = teks_per_halaman(isi)
        n = len(halaman)
        self.assertGreaterEqual(n, 3)
        # Judul kolom lampiran ada di halaman terakhir, bukan hanya di halaman pertama lampiran.
        for kolom in ["Tanggal", "Keterangan", "Amplop", "Pencatat", "Masuk", "Keluar"]:
            with self.subTest(kolom):
                self.assertIn(kolom, halaman[-1])
        awal_lampiran = next(i for i, teks in enumerate(halaman) if "Lampiran: mutasi" in teks)
        self.assertLess(awal_lampiran, n - 1, "lampiran harus melintasi lebih dari satu halaman")
        for i in range(awal_lampiran, n):
            with self.subTest(halaman=i + 1):
                self.assertIn("Keterangan", halaman[i])
                self.assertIn(f"Halaman {i + 1} dari {n}", halaman[i])
        # Semua 300 pengeluaran tercetak di halaman lampiran (penanda unik #k di akhir keterangan).
        tercetak = {int(k) for k in re.findall(r"#(\d+)\b", " ".join(halaman[awal_lampiran:]))}
        self.assertEqual(tercetak, set(range(300)))

    def test_lampiran_mulai_di_halaman_baru_dan_bagian_utama_tidak_terpotong(self):
        halaman = teks_per_halaman(pdf.render_pdf(DATA_BANYAK, KATA_SANDI))
        awal_lampiran = next(i for i, teks in enumerate(halaman) if "Lampiran: mutasi" in teks)
        for judul in JUDUL_BAGIAN[:-1]:
            self.assertTrue(
                any(judul in teks for teks in halaman[:awal_lampiran]), f"{judul!r} harus sebelum lampiran"
            )
        for bagian_utama in ["Sorotan", "Langganan", "5 pengeluaran terbesar", "Ringkasan"]:
            self.assertNotIn(bagian_utama, halaman[awal_lampiran])
        self.assertEqual(sum(1 for teks in halaman if "Lampiran: mutasi" in teks), 1)

    def test_jumlah_mutasi_di_kolom_masuk_atau_keluar(self):
        data = susun_bulanan(bahan(
            transaksi=[txn(id="t1", amplop_id="env-p", tanggal=d(4), jumlah=D(36_000), keterangan="Kopi")],
            pemasukan=[PemasukanPeriode(d(2), D(5_000_000), "Gaji")],
        ))
        isi = pdf.render_pdf(data, KATA_SANDI)
        kanan_masuk = tepi_kanan(isi, "Masuk")
        kanan_keluar = tepi_kanan(isi, "Keluar")
        self.assertGreater(kanan_keluar - kanan_masuk, 30)    # dua kolom yang terpisah jelas
        self.assertAlmostEqual(tepi_kanan(isi, "Rp5.000.000"), kanan_masuk, delta=2.5)
        self.assertAlmostEqual(tepi_kanan(isi, "Rp36.000"), kanan_keluar, delta=2.5)

    def test_status_dua_kata_tidak_dibungkus_ke_baris_kedua(self):
        # Kolom status dilebarkan seukuran isi terlebarnya; isinya tebal, jadi harus diukur dengan font tebal.
        data = susun_bulanan(bahan(
            amplop=[
                amplop_kecil("env-a", "Aman", 1_000_000, 100_000),
                amplop_kecil("env-h", "Hampir", 1_000_000, 950_000),
                amplop_kecil("env-l", "Lewat", 500_000, 600_000),
                amplop_kecil("env-t", "Tabungan", 500_000, 0, tujuan="saving"),
                amplop_kecil("env-k", "Kosong", 0, 0),
            ],
            transaksi=[], tagihan_berikut=[], target=[],
        ))
        self.assertEqual(
            [a["status"] for a in data["amplop"]], ["aman", "hampir_habis", "lewat_batas", "tabungan", "kosong"]
        )
        halaman1 = teks_mentah(pdf.render_pdf(data, KATA_SANDI), 0)
        for status in ["Aman", "Hampir habis", "Lewat batas", "Tabungan", "Kosong"]:
            with self.subTest(status):
                self.assertIn(status, halaman1)

    def test_sel_tabel_tidak_terwarnai_sisa_warna_gambar(self):
        # fpdf2 menyalin warna isi yang sedang aktif ke SETIAP sel badan tabel. Sebelum tabel ada kartu, legenda, dan
        # batang grafik yang mengisi warna; latar sel badan harus tetap putih polos.
        def halaman_dengan(teks: str) -> int:
            return next(i for i, isi in enumerate(self.halaman) if teks in isi)

        # Kontrol positif: sel judul kolom memang berlatar (225, 245, 238), jadi pemetaan koordinat dan pembacaan
        # warna di tes ini benar-benar mengenai sel tabel.
        kepala = warna_di_kiri(self.isi, "Saldo awal", 0)
        self.assertLess(kepala[0], 235, f"judul kolom seharusnya berlatar, bukan {kepala}")
        for judul, kata in [
            ("Amplop", "Kebutuhan"),
            ("5 pengeluaran terbesar", "Listrik"),
            ("Terbayar di periode ini", "Netflix"),
        ]:
            with self.subTest(kata):
                warna = warna_di_kiri(self.isi, kata, halaman_dengan(judul), setelah=judul)
                self.assertGreaterEqual(min(warna), 250, f"sel {kata!r} berlatar {warna}, bukan putih")

    def test_tidak_menulis_ke_disk(self):
        asli_open, asli_os_open = open, os.open

        def tolak_tulis_open(berkas, mode="r", *args, **kwargs):
            if any(huruf in str(mode) for huruf in "wax+"):
                raise AssertionError(f"render_pdf menulis ke disk: {berkas!r} mode {mode!r}")
            return asli_open(berkas, mode, *args, **kwargs)

        def tolak_tulis_os(berkas, bendera, *args, **kwargs):
            if bendera & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
                raise AssertionError(f"render_pdf menulis ke disk: {berkas!r} bendera {bendera}")
            return asli_os_open(berkas, bendera, *args, **kwargs)

        with patch("builtins.open", tolak_tulis_open), patch("io.open", tolak_tulis_open), \
                patch("os.open", tolak_tulis_os):
            isi = pdf.render_pdf(DATA, KATA_SANDI)
        self.assertTrue(isi.startswith(b"%PDF-"))
        self.assertEqual(
            sorted(p.name for p in DIR_FONT.iterdir()), ["NotoSans-Bold.ttf", "NotoSans-Regular.ttf", "OFL.txt"]
        )


class KataSandiTests(unittest.TestCase):
    def test_tanpa_atau_salah_kata_sandi_gagal(self):
        isi = pdf.render_pdf(DATA, KATA_SANDI)
        for percobaan in [None, "", "salah-sandi", KATA_SANDI.upper(), KATA_SANDI + " "]:
            with self.subTest(percobaan=percobaan):
                with self.assertRaises(PdfiumError) as ctx:
                    buka(isi, percobaan)
                # Gagal karena kata sandi, bukan karena berkasnya rusak.
                self.assertRegex(str(ctx.exception), r"(?i)password")

    def test_kata_sandi_non_ascii(self):
        sandi = "kopi-é123"
        isi = pdf.render_pdf(DATA, sandi)
        self.assertIn("Ringkasan", teks_per_halaman(isi, sandi)[0])
        with self.assertRaises(PdfiumError):
            buka(isi, "kopi-e123")
        with self.assertRaises(PdfiumError):
            buka(isi, None)

    def test_kata_sandi_dengan_simbol_spasi_dan_emoji(self):
        for sandi in ["Sandi Rahasia #1 & 2!", "🔑🔑🔑🔑🔑🔑", "a" * 64]:
            with self.subTest(sandi):
                isi = pdf.render_pdf(DATA, sandi)
                self.assertIn("Ringkasan", teks_per_halaman(isi, sandi)[0])

    def test_enkripsi_aes_256_revisi_6_dan_izin_cetak_salin(self):
        isi = pdf.render_pdf(DATA, KATA_SANDI)
        self.assertTrue(isi.startswith(b"%PDF-2.0"))
        for pola in [
            rb"/Filter /Standard", rb"/V 5\b", rb"/R 6\b", rb"/Length 256\b", rb"/CFM /AESV3", rb"/StmF /StdCF",
            rb"/StrF /StdCF",
        ]:
            with self.subTest(pola):
                self.assertRegex(isi, pola)
        izin = int(re.search(rb"/P (-?\d+)", isi).group(1)) & 0xFFFFFFFF
        for nama, bendera in [
            ("cetak", AccessPermission.PRINT_LOW_RES), ("cetak resolusi tinggi", AccessPermission.PRINT_HIGH_RES),
            ("salin", AccessPermission.COPY), ("salin untuk aksesibilitas", AccessPermission.COPY_FOR_ACCESSIBILITY),
        ]:
            with self.subTest(nama):
                self.assertTrue(izin & bendera, f"izin {nama} harus aktif")
        for nama, bendera in [
            ("ubah isi", AccessPermission.MODIFY), ("anotasi", AccessPermission.ANNOTATION),
            ("isi formulir", AccessPermission.FILL_FORMS), ("susun halaman", AccessPermission.ASSEMBLE),
        ]:
            with self.subTest(nama):
                self.assertFalse(izin & bendera, f"izin {nama} tidak diminta")

    def test_set_encryption_dipanggil_dengan_kata_sandi_pemilik_acak(self):
        panggilan = []
        asli = FPDF.set_encryption

        def mata_mata(self, *args, **kwargs):
            panggilan.append(kwargs)
            return asli(self, *args, **kwargs)

        with patch.object(FPDF, "set_encryption", mata_mata):
            pdf.render_pdf(DATA, KATA_SANDI)
            pdf.render_pdf(DATA, KATA_SANDI)
        self.assertEqual(len(panggilan), 2)
        for kwargs in panggilan:
            self.assertEqual(kwargs["user_password"], KATA_SANDI)
            self.assertIs(kwargs["encryption_method"], EncryptionMethod.AES_256)
            self.assertGreaterEqual(len(kwargs["owner_password"]), 32)
            self.assertNotEqual(kwargs["owner_password"], KATA_SANDI)
        self.assertNotEqual(panggilan[0]["owner_password"], panggilan[1]["owner_password"])

    def test_dua_render_data_sama_menghasilkan_berkas_berbeda(self):
        # Garam dan IV acak per berkas: PDF yang sama tidak menghasilkan byte yang sama (tidak ada kunci tetap).
        self.assertNotEqual(pdf.render_pdf(DATA, KATA_SANDI), pdf.render_pdf(DATA, KATA_SANDI))

    def test_kata_sandi_kosong_ditolak_dan_tak_pernah_menghasilkan_pdf_terbuka(self):
        for sandi in ["", None]:
            with self.subTest(sandi=sandi), self.assertRaises(pdf.KataSandiPdfTidakValid):
                pdf.render_pdf(DATA, sandi)

    def test_kata_sandi_kosong_setelah_normalisasi_ditolak(self):
        # SASLprep membuang karakter yang "dipetakan ke nol" (tanda hubung lunak, penyambung lebar nol, ...). Kata
        # sandi yang hanya terdiri dari itu menjadi kosong di berkas, yaitu PDF yang terbuka tanpa kata sandi apa pun.
        for nama, sandi in [
            ("tanda hubung lunak", "\N{SOFT HYPHEN}" * 6),
            ("penyambung lebar nol", "\N{ZERO WIDTH JOINER}" * 6),
            ("campuran", "\N{ZERO WIDTH NON-JOINER}\N{SOFT HYPHEN}" * 3),
        ]:
            with self.subTest(nama):
                with self.assertRaises(pdf.KataSandiPdfTidakValid):
                    pdf.periksa_kata_sandi(sandi)
                with self.assertRaises(pdf.KataSandiPdfTidakValid):
                    pdf.render_pdf(DATA, sandi)

    def test_periksa_kata_sandi_menerima_yang_wajar(self):
        for sandi in [
            "rahasia123", "kopi-é123", "Sandi Rahasia #1 & 2!", "🔑" * 6, "a" * 64, "é" * 63 + "a", ALEF * 3 + BEH,
        ]:
            with self.subTest(sandi):
                self.assertIsNone(pdf.periksa_kata_sandi(sandi))

    def test_periksa_kata_sandi_menolak_yang_tak_bisa_dipakai_tanpa_membocorkannya(self):
        for nama, sandi in [
            ("karakter kontrol", "abc\x07def-rahasia"),
            ("NUL", "abc\x00def-rahasia"),
            ("Arab dicampur Latin", "abc" + ALEF + BEH + "def-rahasia"),
            ("lebih dari 127 byte UTF-8", "中" * 43),
            ("lebih dari 127 byte, ASCII", "abc-rahasia-" + "x" * 130),
            ("spasi tak terputus", "abc\N{NO-BREAK SPACE}def-rahasia"),
            ("tanda hubung lunak", "abc\N{SOFT HYPHEN}def-rahasia"),
            ("huruf lebar penuh", "abc\N{FULLWIDTH LATIN SMALL LETTER D}ef-rahasia"),
        ]:
            with self.subTest(nama):
                with self.assertRaises(pdf.KataSandiPdfTidakValid) as ctx:
                    pdf.periksa_kata_sandi(sandi)
                self.assertIsInstance(ctx.exception, ValueError)
                jejak = "".join(traceback.format_exception(ctx.exception))
                self.assertNotIn("rahasia", jejak)
                self.assertNotIn("abc", jejak)
                self.assertNotIn("中", jejak)
                # Pengecualian fpdf2 (yang pesannya memuat kata sandi) juga tidak boleh tertinggal di rantai:
                # kode yang menelusuri `__context__` sendiri (pelapor galat) tidak akan menemukannya.
                self.assertIsNone(ctx.exception.__context__)
                self.assertIsNone(ctx.exception.__cause__)
                # Pesannya siap tampil ke user (PUT kata sandi laporan menjadikannya `detail` 422).
                pesan = str(ctx.exception)
                self.assertTrue(pesan.startswith("Kata sandi"), pesan)
                self.assertTrue(pesan.endswith("."), pesan)

    def test_periksa_kata_sandi_menolak_yang_diubah_saslprep(self):
        # SASLprep (ISO 32000-2) mengubah spasi non-ASCII, karakter yang "dipetakan ke nol", dan bentuk
        # kompatibilitas (NFKC); pembaca berbasis pdfium (Chrome, pypdfium2) tidak melakukannya. Kata sandi seperti
        # itu hanya terbuka di sebagian pembaca, jadi ditolak di muka, bukan setelah PDF sampai ke pemiliknya.
        for nama, sandi in [
            ("spasi tak terputus", "kopi\N{NO-BREAK SPACE}susu-123"),
            ("spasi ideografis", "kopi\N{IDEOGRAPHIC SPACE}susu-123"),
            ("tanda hubung lunak di tengah", "kopi\N{SOFT HYPHEN}susu-123"),
            ("penyambung lebar nol di tengah", "kopi\N{ZERO WIDTH JOINER}susu-123"),
            ("huruf lebar penuh", "\N{FULLWIDTH LATIN SMALL LETTER K}opi-susu-123"),
            ("angka berlingkar", "kopi-susu-\N{CIRCLED DIGIT ONE}"),
            ("ligatur", "\N{LATIN SMALL LIGATURE FI}le-susu-123"),
            ("pangkat", "kopi-susu-x\N{SUPERSCRIPT TWO}"),
        ]:
            with self.subTest(nama):
                with self.assertRaises(pdf.KataSandiPdfTidakValid):
                    pdf.periksa_kata_sandi(sandi)
                with self.assertRaises(pdf.KataSandiPdfTidakValid):
                    pdf.render_pdf(DATA, sandi)

    def test_periksa_kata_sandi_bentuk_gabungan_sama_dengan_nfc_diterima(self):
        # Huruf + tanda gabung (NFD) menjadi huruf utuh baik oleh SASLprep maupun NFC, jadi tidak ada yang berubah
        # secara diam-diam; PUT kata sandi laporan toh menyimpan bentuk NFC. PDF-nya terkunci dengan bentuk NFC.
        nfd = "cafe\N{COMBINING ACUTE ACCENT}-123"
        nfc = "caf\N{LATIN SMALL LETTER E WITH ACUTE}-123"
        self.assertIsNone(pdf.periksa_kata_sandi(nfd))
        isi = pdf.render_pdf(DATA, nfd)
        self.assertIn("Ringkasan", teks_per_halaman(isi, nfc)[0])

    def test_periksa_kata_sandi_batas_127_byte_berlaku_untuk_ascii_juga(self):
        # fpdf2 memotong kata sandi per karakter (bukan per byte) dan diam-diam; kata sandi yang lebih panjang dari
        # 127 byte ditolak, apa pun huruf-hurufnya, bukan dipotong tanpa kabar.
        # Pesannya harus "terlalu panjang" (yang bisa ditindaklanjuti pengguna), bukan pesan bentuk-berubah: potongan
        # diam-diam fpdf2 membuat bentuk SASLprep ASCII panjang berbeda dari NFC-nya, jadi tanpa pengukuran bentuk NFC
        # penolakannya tetap terjadi tetapi dengan alasan yang salah.
        self.assertIsNone(pdf.periksa_kata_sandi("a" * 127))
        self.assertIsNone(pdf.periksa_kata_sandi("é" * 63 + "a"))   # tepat 127 byte
        for nama, sandi in [("ASCII 128", "a" * 128), ("ASCII 200", "a" * 200), ("é 64 (128 byte)", "é" * 64)]:
            with self.subTest(nama), self.assertRaisesRegex(pdf.KataSandiPdfTidakValid, "terlalu panjang"):
                pdf.periksa_kata_sandi(sandi)

    def test_kata_sandi_tak_valid_ditolak_sebelum_font_dibaca(self):
        # fpdf2 menolak kata sandi terlarang baru di output(), setelah font dibaca (dan fpdf2 menyebut kata sandinya di
        # pesan galat). Penolakan dini: tidak ada font dibuka, tidak ada yang tertinggal di memori.
        with patch.object(FPDF, "add_font", side_effect=AssertionError("font tidak boleh dibaca")):
            with self.assertRaises(pdf.KataSandiPdfTidakValid):
                pdf.render_pdf(DATA, "abc\x07def")


class KebocoranMemoriTests(unittest.TestCase):
    """fpdf2 2.8.9 menyimpan `SubsetMap.pick/get_glyph` dalam `functools.cache` tanpa batas dan hanya mengosongkannya di
    akhir `output()` yang sukses; render yang gagal di tengah menahan dua font (sekitar 7 MB) selamanya."""

    @staticmethod
    def font_hidup() -> int:
        gc.collect()
        return sum(1 for o in gc.get_objects() if isinstance(o, TTFFont))

    def test_render_sukses_tidak_menyisakan_font(self):
        sebelum = self.font_hidup()
        for _ in range(3):
            pdf.render_pdf(DATA, KATA_SANDI)
        self.assertLessEqual(self.font_hidup(), sebelum)
        self.assertEqual(SubsetMap.pick.cache_info().currsize, 0)

    def test_render_gagal_di_tengah_tidak_menyisakan_font(self):
        sebelum = self.font_hidup()
        with patch.object(FPDF, "output", side_effect=RuntimeError("gagal di tengah")):
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    pdf.render_pdf(DATA, KATA_SANDI)
        self.assertLessEqual(self.font_hidup(), sebelum)
        self.assertEqual(SubsetMap.pick.cache_info().currsize, 0)
        self.assertEqual(SubsetMap.get_glyph.cache_info().currsize, 0)


class BuatPdfTests(unittest.IsolatedAsyncioTestCase):
    async def test_buat_pdf_lewat_thread_dan_semaphore(self):
        data = {"judul": "contoh"}
        to_thread = AsyncMock(return_value=b"%PDF-palsu")
        with patch("app.services.laporan.pdf.asyncio.to_thread", to_thread):
            hasil = await pdf.buat_pdf(data, "rahasia123")
        self.assertEqual(hasil, b"%PDF-palsu")
        to_thread.assert_awaited_once_with(pdf.render_pdf, data, "rahasia123")
        self.assertEqual(pdf.MAKS_PDF_SERENTAK, 2)
        self.assertIsInstance(pdf._semafor_pdf, asyncio.Semaphore)
        self.assertEqual(pdf._semafor_pdf._value, pdf.MAKS_PDF_SERENTAK)

    async def test_paling_banyak_dua_render_sekaligus(self):
        aktif = puncak = 0

        async def to_thread_palsu(fungsi, *args):
            nonlocal aktif, puncak
            aktif += 1
            puncak = max(puncak, aktif)
            await asyncio.sleep(0.01)
            aktif -= 1
            return b"%PDF-palsu"

        # Semaphore modul terikat ke event loop tempat ia pertama kali diperebutkan; tiap tes memakai yang baru.
        with patch.object(pdf, "_semafor_pdf", asyncio.Semaphore(pdf.MAKS_PDF_SERENTAK)), \
                patch("app.services.laporan.pdf.asyncio.to_thread", to_thread_palsu):
            hasil = await asyncio.gather(*(pdf.buat_pdf({}, "rahasia123") for _ in range(6)))
        self.assertEqual(hasil, [b"%PDF-palsu"] * 6)
        self.assertEqual(puncak, pdf.MAKS_PDF_SERENTAK)

    async def test_slot_dilepas_bila_render_gagal(self):
        semafor = asyncio.Semaphore(pdf.MAKS_PDF_SERENTAK)
        with patch.object(pdf, "_semafor_pdf", semafor), \
                patch("app.services.laporan.pdf.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("gagal"))):
            for _ in range(pdf.MAKS_PDF_SERENTAK + 1):
                with self.assertRaises(RuntimeError):
                    await pdf.buat_pdf({}, "rahasia123")
        self.assertEqual(semafor._value, pdf.MAKS_PDF_SERENTAK)

    async def test_buat_pdf_sungguhan_menghasilkan_pdf_ber_kata_sandi(self):
        isi = await pdf.buat_pdf(DATA, KATA_SANDI)
        self.assertIsInstance(isi, bytes)
        self.assertIn("Laporan Oktober 2026", teks_per_halaman(isi)[0])
        with self.assertRaises(PdfiumError):
            buka(isi, None)


class FontTests(unittest.TestCase):
    def test_font_cocok_sha256(self):
        for nama, harapan in SHA256_FONT.items():
            with self.subTest(nama):
                self.assertEqual(hashlib.sha256((DIR_FONT / nama).read_bytes()).hexdigest(), harapan)

    def test_lisensi_font_ikut_dikirim(self):
        teks = (DIR_FONT / "OFL.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", teks)
        self.assertIn("Noto Project Authors", teks)

    def test_kode_membaca_font_dari_folder_yang_sama(self):
        self.assertEqual(pdf.FONT_REGULAR, DIR_FONT / "NotoSans-Regular.ttf")
        self.assertEqual(pdf.FONT_BOLD, DIR_FONT / "NotoSans-Bold.ttf")

    def test_cmap_bold_mencakup_cmap_regular(self):
        # teks_pdf menyaring dengan cmap Regular; judul dan angka tebal memakai Bold, jadi Bold tidak boleh kurang.
        from fontTools.ttLib import TTFont
        with TTFont(pdf.FONT_REGULAR, lazy=True) as regular, TTFont(pdf.FONT_BOLD, lazy=True) as tebal:
            self.assertLessEqual(set(regular["cmap"].getBestCmap()), set(tebal["cmap"].getBestCmap()))


if __name__ == "__main__":
    unittest.main()
