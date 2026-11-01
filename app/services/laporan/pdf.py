"""PDF laporan berkala ber-AES-256 (spec 2026-11-01-laporan-berkala-design, bagian 4; tahap 1, Task 6).

`render_pdf(data, kata_sandi)` mengubah `data` v1 (kunci dan kontrak null: docstring `susun.py`) menjadi PDF A4 tegak
yang dienkripsi AES-256 (`EncryptionMethod.AES_256`: PDF 2.0, revisi 6). Kata sandi pengguna = kata sandi laporan user;
kata sandi pemilik acak per berkas (`secrets.token_urlsafe`) dan tidak disimpan; mencetak dan menyalin diizinkan,
mengubah isi tidak. PDF dibuat saat diminta dan hanya di memori: tidak ada berkas yang ditulis. Teks digambar sebagai
teks PDF (bukan HTML), jadi isi `data` tidak bisa menyisipkan markup.

Modul ini hanya memformat: angka, persen, dan teks sorotan dibaca dari `data` dan tidak dihitung ulang ("satu sumber
angka"). Satu-satunya hitungan adalah skala sumbu grafik dan lebar kolom. Nilai `null` dicetak "—" (lihat daftar
`null` di docstring `susun.py`); `ringkasan.persen_terpakai` bukan Σ terpakai / Σ awal tabel amplop (tabungan tidak
ikut) dan tidak pernah dihitung dari tabel itu. `data["email"]` adalah isi badan email (tahap 2) dan tidak dibaca di
sini.

Font Noto Sans Regular dan Bold (OFL; lisensi di `app/assets/fonts/OFL.txt`) tertanam sebagian saja (subset) oleh
fpdf2. Karakter yang tidak ada di cmap font (emoji, panah, aksara lain) dibuang `teks_pdf`, sehingga fpdf2 tidak pernah
mencatat peringatan glyph hilang. Semua teks dinamis lewat `teks_pdf`.

Empat kehati-hatian soal fpdf2 2.8.9:
- `table()` menyalin warna isi yang sedang aktif ke SETIAP sel badan tabel. Kartu, legenda, dan batang grafik
  meninggalkan warna isi, jadi `_tabel` mengembalikannya ke bawaan sebelum membuat tabel.
- Kata sandi diperiksa sebelum apa pun dibuat (`periksa_kata_sandi`). fpdf2 baru menolak kata sandi terlarang di
  `output()`, setelah font dibaca, dan menyebut kata sandinya di pesan galat; pesan itu tidak boleh sampai ke log.
  Kata sandi yang setelah SASLprep kosong akan menghasilkan PDF tanpa kata sandi, jadi juga ditolak.
- `SubsetMap.pick/get_glyph` memakai `functools.cache` tanpa batas yang menahan seluruh font (sekitar 7 MB) dan baru
  dikosongkan di akhir `output()` yang sukses. Render yang gagal di tengah akan membocorkannya di proses API yang
  berumur panjang, maka cache dikosongkan di `finally`.
- Kata sandi non-ASCII mengikuti ISO 32000-2 (SASLprep lalu UTF-8): terbuka di pembaca yang patuh (juga pdfium untuk
  teks NFC biasa). Teks yang berubah oleh SASLprep (bentuk NFD, spasi non-ASCII) tidak terbuka di pdfium.

Logger proyek (`jatahku.laporan`) tidak dipakai di sini: tidak ada yang layak dicatat dari pembuatan satu PDF, dan nama
amplop atau keterangan tidak boleh masuk log.
"""
import asyncio
import functools
import secrets
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from pathlib import Path

from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.encryption import StandardSecurityHandler
from fpdf.enums import AccessPermission, EncryptionMethod, TableHeadingsDisplay, TextEmphasis
from fpdf.errors import FPDFException
from fpdf.fonts import FontFace, SubsetMap

from app.services.laporan.hitung import BLN, BULAN

DIR_FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_REGULAR = DIR_FONT / "NotoSans-Regular.ttf"
FONT_BOLD = DIR_FONT / "NotoSans-Bold.ttf"

# Paling banyak dua PDF dibuat sekaligus (spec bagian 4): tiap render memakai satu thread dan puluhan MB sementara.
MAKS_PDF_SERENTAK = 2
# Terikat ke event loop tempat ia pertama kali diperebutkan; di API itu satu loop (satu worker uvicorn).
_semafor_pdf = asyncio.Semaphore(MAKS_PDF_SERENTAK)

# Cetak dan salin saja (salin untuk aksesibilitas ikut, supaya pembaca layar tetap bisa membacanya).
_IZIN = (
    AccessPermission.PRINT_LOW_RES | AccessPermission.PRINT_HIGH_RES | AccessPermission.COPY
    | AccessPermission.COPY_FOR_ACCESSIBILITY
)
# ISO 32000-2, 7.6.4.3.3: kata sandi pengguna revisi 6 dipotong pada 127 byte UTF-8. Pembaca yang patuh memotong di
# situ, sedangkan fpdf2 memotong per karakter; di bawah batas ini keduanya sama.
_MAKS_BYTE_KATA_SANDI = 127

STRIP = "\N{EM DASH}"                  # nilai null
_RENTANG = " \N{EN DASH} "
_TITIK_TENGAH = " \N{MIDDLE DOT} "

# Warna merek dari frontend (index.css: --brand-*; tailwind: amber, danger, info).
TINTA = (31, 41, 55)
REDUP = (95, 104, 118)
GARIS = (209, 216, 222)
LATAR = (240, 247, 244)
LATAR_KEPALA = (225, 245, 238)
TEKS_KEPALA = (8, 80, 65)
MEREK = (15, 110, 86)
MEREK_TERANG = (29, 158, 117)
SOROT = (186, 117, 23)
_WARNA_STATUS = {
    "aman": (15, 110, 86), "hampir_habis": (133, 79, 11), "lewat_batas": (163, 45, 45),
    "tabungan": (24, 95, 165), "kosong": REDUP,
}
_NAMA_STATUS = {
    "aman": "Aman", "hampir_habis": "Hampir habis", "lewat_batas": "Lewat batas", "tabungan": "Tabungan",
    "kosong": "Kosong",
}

_MARGIN = 15.0
_UKURAN_TABEL = 8.5
_TINGGI_BARIS = 4.4
_PADDING_TABEL = (1.2, 1.8)   # (atas-bawah, kiri-kanan)
_TINGGI_JUDUL = 18.0          # judul bagian beserta jarak di atas dan bawahnya
_MAKS_JAGA = 100.0            # bagian yang lebih tinggi dari ini dibiarkan menyambung ke halaman berikutnya


def _tinggi_tabel(n_baris: int) -> float:
    """Perkiraan tinggi tabel `n_baris` baris isi beserta judul kolomnya, untuk menjaga tabel kecil tetap utuh di satu
    halaman (baris yang membungkus lebih tinggi sedikit; tabel panjang memang disambung)."""
    return (n_baris + 1) * (_TINGGI_BARIS + 2 * _PADDING_TABEL[0]) + 2


class KataSandiPdfTidakValid(ValueError):
    """Kata sandi yang tidak bisa dipakai sebagai kata sandi PDF AES-256: kosong (juga setelah SASLprep), memuat
    karakter yang dilarang standar PDF (karakter kontrol, dua arah bercampur), atau lebih dari 127 byte UTF-8.
    Pesannya tidak pernah memuat kata sandinya."""


def periksa_kata_sandi(kata_sandi: str) -> None:
    """Menolak (`KataSandiPdfTidakValid`) kata sandi yang `render_pdf` tidak bisa pakai dengan benar. Dipakai
    `render_pdf` sebelum membuat apa pun, dan bisa dipakai PUT kata sandi laporan supaya yang tak terpakai tidak
    pernah tersimpan. Sengaja memakai `StandardSecurityHandler.prepare_string` milik fpdf2 (SASLprep): hasilnya
    adalah byte yang benar-benar menjadi dasar kata sandi di berkas."""
    if not kata_sandi:
        raise KataSandiPdfTidakValid("kata sandi PDF kosong")
    try:
        byte_kata_sandi = StandardSecurityHandler.prepare_string(kata_sandi)
    except FPDFException:
        # `from None`: pesan fpdf2 memuat kata sandinya, dan rantai pengecualian ikut tercetak di log.
        raise KataSandiPdfTidakValid("kata sandi PDF memuat karakter yang dilarang standar PDF") from None
    if not byte_kata_sandi:
        raise KataSandiPdfTidakValid("kata sandi PDF kosong setelah normalisasi")
    if len(byte_kata_sandi) > _MAKS_BYTE_KATA_SANDI:
        raise KataSandiPdfTidakValid(f"kata sandi PDF lebih dari {_MAKS_BYTE_KATA_SANDI} byte (UTF-8)")


@functools.lru_cache(maxsize=1)
def _cmap_regular() -> frozenset[int]:
    """Titik kode yang ada di font Regular, dibaca sekali. Persis yang dipakai fpdf2 untuk memutuskan "glyph hilang"
    (`TTFFont.cmap` = `getBestCmap()`); cmap Bold sama atau lebih luas (dijaga tes)."""
    with TTFont(FONT_REGULAR, lazy=True) as font:
        return frozenset(font["cmap"].getBestCmap())


def teks_pdf(s: str) -> str:
    """Teks yang aman digambar dengan Noto Sans: karakter yang tidak ada di cmap font Regular dibuang (emoji, panah,
    aksara lain), jadi fpdf2 tidak pernah mencatat peringatan glyph hilang. Selain itu: NFC (huruf bertanda tampil
    utuh); semua spasi dan karakter pemisah baris (baris baru, tab, spasi lebar) jadi satu spasi; karakter kontrol dan
    format (penyambung emoji, tanda hubung lunak, BOM, NUL) dibuang walau ada di cmap, karena tidak berguna di PDF;
    spasi berulang dirapatkan dan ujung dipangkas, supaya "🍔 Makan" menjadi "Makan" dan bukan " Makan"."""
    ada = _cmap_regular()
    sisa = []
    for huruf in unicodedata.normalize("NFC", s):
        if huruf.isspace():
            sisa.append(" ")
        elif unicodedata.category(huruf) in ("Cc", "Cf"):
            continue
        elif ord(huruf) in ada:
            sisa.append(huruf)
    return " ".join("".join(sisa).split())


def rupiah(nilai: str) -> str:
    """"1234567.00" menjadi "Rp1.234.567"; negatif "-Rp12.000"; nol "Rp0". Angka laporan berpecahan sen, tampilannya
    rupiah utuh (ROUND_HALF_UP menjauhi nol); hasil bulat nol tidak pernah bertanda minus."""
    bulat = Decimal(nilai).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if not bulat:
        return "Rp0"
    angka = f"{abs(bulat):,}".replace(",", ".")
    return f"-Rp{angka}" if bulat < 0 else f"Rp{angka}"


def _rp(nilai: str | None) -> str:
    return STRIP if nilai is None else rupiah(nilai)


def _tanggal(iso: str) -> str:
    """"2026-10-01" menjadi "1 Oktober 2026"."""
    t = date.fromisoformat(iso)
    return f"{t.day} {BULAN[t.month]} {t.year}"


def _tanggal_pendek(iso: str) -> str:
    """"2026-10-01" menjadi "1 Okt" (tahun sudah ada di judul dan periode; bulan menjaga periode lintas bulan)."""
    t = date.fromisoformat(iso)
    return f"{t.day} {BLN[t.month]}"


def _perubahan(persen: int | None) -> str:
    if persen is None:
        return STRIP
    if persen == 0:
        return "Tidak berubah"
    return f"{'Naik' if persen > 0 else 'Turun'} {abs(persen)}%"


def _teks(s, kosong: str = "") -> str:
    """Teks dinamis siap gambar; `kosong` bila seluruhnya terbuang (nama yang hanya emoji tetap punya penanda)."""
    return teks_pdf(str(s)) or kosong


def _puncak_grafik(maks: Decimal) -> Decimal:
    """Batas atas sumbu grafik: bilangan bulat 1, 2, 4, 6, 8, atau 10 kali pangkat sepuluh, paling kecil yang tidak
    kurang dari `maks`. Setengahnya selalu angka dengan satu desimal, jadi garis tengah punya label yang wajar."""
    if maks <= 0:
        return Decimal(1)
    skala = Decimal(1).scaleb(maks.adjusted())
    return next(m * skala for m in (1, 2, 4, 6, 8, 10) if maks <= m * skala)


def _ringkas(nilai: Decimal) -> str:
    """Label sumbu: 0, 250 rb, 1,5 jt, 2 M (ribu, juta, miliar), desimal koma."""
    if nilai == 0:
        return "0"
    for batas, satuan in ((Decimal(10) ** 9, "M"), (Decimal(10) ** 6, "jt"), (Decimal(10) ** 3, "rb")):
        if nilai >= batas:
            angka = f"{nilai / batas:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"{angka} {satuan}"
    return f"{nilai:.0f}"


class _Laporan(FPDF):
    """Satu dokumen laporan. `header`/`footer` dipanggil fpdf2 di setiap halaman; `susun` menggambar bagian 1-7 dan
    lampiran. Semua koordinat dalam mm, A4 tegak, margin 15 mm."""

    def __init__(self, data: dict):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.lap = data
        self._y_badan = _MARGIN
        self.set_margins(_MARGIN, _MARGIN, _MARGIN)
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()
        self.add_font("NotoSans", "", str(FONT_REGULAR))
        self.add_font("NotoSans", "B", str(FONT_BOLD))
        self.set_title(_teks(data["judul"]))
        self.set_author("Jatahku")
        self.set_creator("Jatahku")
        self.set_lang("id")

    # ------------------------------------------------------------------ alat gambar

    def _font(self, tebal: bool, ukuran: float) -> None:
        self.set_font("NotoSans", "B" if tebal else "", ukuran)

    def _gaya(self, tebal: bool = False, ukuran: float = 9.5, warna=TINTA) -> None:
        self._font(tebal, ukuran)
        self.set_text_color(*warna)

    def _muat(self, teks: str, lebar: float, tebal: bool, ukuran: float, minimal: float = 7.0) -> str:
        """Atur font ke ukuran terbesar (paling kecil `minimal`) yang membuat `teks` muat dalam `lebar`; bila masih
        kebesaran, potong dengan "…". Mengembalikan teks yang akan digambar."""
        while ukuran > minimal:
            self._font(tebal, ukuran)
            if self.get_string_width(teks) <= lebar:
                return teks
            ukuran -= 0.5
        self._font(tebal, minimal)
        while len(teks) > 1 and self.get_string_width(teks) > lebar:
            teks = teks[:-2].rstrip() + "\N{HORIZONTAL ELLIPSIS}"
        return teks

    def _butuh(self, tinggi: float) -> None:
        """Pindah ke halaman baru bila sisa halaman kurang dari `tinggi` (judul bagian tidak boleh terpisah dari
        isinya)."""
        if self.get_y() + tinggi > self.page_break_trigger:
            self.add_page()

    def _judul_bagian(self, judul: str, butuh: float = 45.0) -> None:
        self._butuh(butuh)
        if self.get_y() > self._y_badan + 0.5:
            self.ln(7)
        self._gaya(True, 12.5, MEREK)
        self.set_x(_MARGIN)
        self.cell(0, 7, teks_pdf(judul), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*GARIS)
        self.set_line_width(0.25)
        self.line(_MARGIN, self.get_y() + 0.4, self.w - _MARGIN, self.get_y() + 0.4)
        self.ln(3.2)

    def _subjudul(self, teks: str, butuh: float = 24.0) -> None:
        self._butuh(butuh)
        self._gaya(True, 9.5, TINTA)
        self.set_x(_MARGIN)
        self.cell(0, 5.5, teks_pdf(teks), new_x="LMARGIN", new_y="NEXT")
        self.ln(0.8)

    def _catatan(self, teks: str) -> None:
        self._gaya(False, 9, REDUP)
        self.set_x(_MARGIN)
        self.multi_cell(0, 5, teks_pdf(teks), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def _kartu(self, x: float, y: float, lebar: float, tinggi: float, label: str, nilai: str, sub: str | None = None):
        """Kotak angka: label kecil, nilai tebal, keterangan kecil di bawahnya (bila ada)."""
        self.set_fill_color(*LATAR)
        self.rect(x, y, lebar, tinggi, style="F", round_corners=True, corner_radius=2)
        dalam = lebar - 6
        self._gaya(False, 8, REDUP)
        self.set_xy(x + 3, y + 2.2)
        self.cell(dalam, 4, self._muat(teks_pdf(label), dalam, False, 8), new_x="LEFT", new_y="NEXT")
        self._gaya(True, 13.5, TINTA)
        teks = self._muat(teks_pdf(nilai), dalam, True, 13.5, minimal=8)
        self.set_xy(x + 3, y + 7.2)
        self.cell(dalam, 6.2, teks, new_x="LEFT", new_y="NEXT")
        if sub:
            self._gaya(False, 7, REDUP)
            self.set_xy(x + 3, y + 13.6)
            self.cell(dalam, 3.4, self._muat(teks_pdf(sub), dalam, False, 7, minimal=6), new_x="LEFT", new_y="NEXT")

    def _baris_kartu(self, kartu: list[tuple], per_baris: int, tinggi: float) -> None:
        """Susun `kartu` (label, nilai, sub) dalam grid `per_baris` kolom selebar halaman; kursor turun di bawahnya."""
        celah = 4.0
        lebar = (self.epw - celah * (per_baris - 1)) / per_baris
        baris = ceil(len(kartu) / per_baris)
        self._butuh(baris * tinggi + (baris - 1) * celah)
        y = self.get_y()
        for i, (label, nilai, sub) in enumerate(kartu):
            self._kartu(
                _MARGIN + (i % per_baris) * (lebar + celah), y + (i // per_baris) * (tinggi + celah),
                lebar, tinggi, label, nilai, sub,
            )
        self.set_xy(_MARGIN, y + baris * tinggi + (baris - 1) * celah + 2)

    def _lebar_kolom(self, kepala: list[str], baris: list[list], bobot: list[float | None]) -> list[float]:
        """Lebar kolom tabel: kolom berbobot `None` pas dengan isi terlebar (angka tidak pernah terpotong ke baris
        lain), sisanya dibagi menurut bobot. Jumlahnya persis lebar halaman."""
        total = self.epw
        pad = 2 * _PADDING_TABEL[1] + 0.8
        tetap: dict[int, float] = {}
        for i, b in enumerate(bobot):
            if b is not None:
                continue
            isi = 0.0
            for r in baris:   # sel tebal diukur dengan font tebal, kalau tidak teksnya lebih lebar dari kolomnya
                self._font(_tebal(r[i]), _UKURAN_TABEL)
                isi = max(isi, self.get_string_width(_isi_sel(r[i])))
            self._font(True, _UKURAN_TABEL)   # judul kolom tebal
            tetap[i] = max(isi, self.get_string_width(teks_pdf(kepala[i]))) + pad
        sisa_minimal = 0.3 * total
        jumlah_tetap = sum(tetap.values())
        if jumlah_tetap > total - sisa_minimal:   # nominal yang tidak masuk akal besarnya: kecilkan merata
            for i in tetap:
                tetap[i] *= (total - sisa_minimal) / jumlah_tetap
            jumlah_tetap = total - sisa_minimal
        jumlah_bobot = sum(b for b in bobot if b is not None)
        return [
            tetap[i] if b is None else (total - jumlah_tetap) * b / jumlah_bobot for i, b in enumerate(bobot)
        ]

    def _tabel(self, kepala: list[str], baris: list[list], bobot: list[float | None], rata: list[str],
               zebra: bool = False) -> None:
        """Tabel selebar halaman, judul kolom berulang di setiap halaman. Sel: teks, atau (teks, FontFace)."""
        self._butuh(22)
        lebar = self._lebar_kolom(kepala, baris, bobot)
        self._gaya(False, _UKURAN_TABEL)
        self.set_draw_color(*GARIS)
        self.set_line_width(0.2)
        # fpdf2 menyalin warna isi yang sedang aktif ke SETIAP sel badan tabel (`Table._initial_style`). Warna sisa dari
        # kartu, batang grafik, atau legenda akan mewarnai seluruh baris, jadi kembalikan ke bawaan (abu-abu 0).
        # Harus `DeviceGray(0)`: `set_fill_color(0, 0, 0)` adalah DeviceRGB dan tidak dianggap bawaan.
        self.set_fill_color(0)
        opsi = {}
        if zebra:
            opsi = {"cell_fill_color": LATAR, "cell_fill_mode": "EVEN_ROWS"}
        with self.table(
            col_widths=lebar, text_align=rata, line_height=_TINGGI_BARIS, padding=_PADDING_TABEL,
            borders_layout="HORIZONTAL_LINES", repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE,
            headings_style=FontFace(emphasis="BOLD", color=TEKS_KEPALA, fill_color=LATAR_KEPALA), **opsi,
        ) as tabel:
            judul = tabel.row()
            for teks in kepala:
                judul.cell(teks_pdf(teks))
            for isi in baris:
                baris_tabel = tabel.row()
                for sel in isi:
                    if isinstance(sel, tuple):
                        baris_tabel.cell(sel[0], style=sel[1])
                    else:
                        baris_tabel.cell(sel)
        self.set_x(_MARGIN)
        self.ln(2)

    # ------------------------------------------------------------------ header dan footer

    def header(self) -> None:
        lap = self.lap
        angka_per = teks_pdf(f"Angka per {_tanggal(lap['angka_per'])}")
        kanan = self.w - _MARGIN
        if self.page_no() == 1:
            self.set_xy(_MARGIN, 12)
            self._gaya(True, 13, MEREK)
            self.cell(60, 7, "Jatahku")
            self._gaya(False, 8.5, REDUP)
            self.set_xy(_MARGIN + 60, 12.8)
            self.cell(self.epw - 60, 5, angka_per, align="R")
            self.set_draw_color(*MEREK)
            self.set_line_width(0.7)
            self.line(_MARGIN, 20.5, kanan, 20.5)
            self._gaya(True, 21, TINTA)
            judul = self._muat(_teks(lap["judul"]), self.epw, True, 21, minimal=12)
            self.set_xy(_MARGIN, 24.5)
            self.cell(self.epw, 10, judul)
            periode = lap["periode"]
            self._gaya(False, 10, TINTA)
            self.set_xy(_MARGIN, 36)
            self.cell(self.epw, 5.5, teks_pdf(f"{_tanggal(periode['mulai'])}{_RENTANG}{_tanggal(periode['akhir'])}"))
            penerima = lap["penerima"]
            self._gaya(False, 10, REDUP)
            orang = _TITIK_TENGAH.join(p for p in (_teks(penerima["nama"]), _teks(penerima["rumah"])) if p)
            self.set_xy(_MARGIN, 41.8)
            self.cell(self.epw, 5.5, self._muat(orang, self.epw, False, 10, minimal=7))
            self.set_y(52)
        else:
            self.set_xy(_MARGIN, 11)
            self._gaya(True, 9, MEREK)
            self.cell(17, 5, "Jatahku")
            self._gaya(False, 9, REDUP)
            self.cell(self.epw - 17 - 60, 5, self._muat(_teks(lap["judul"]), self.epw - 17 - 60, False, 9, minimal=7))
            self._gaya(False, 8.5, REDUP)
            self.cell(60, 5, angka_per, align="R")
            self.set_draw_color(*MEREK)
            self.set_line_width(0.5)
            self.line(_MARGIN, 17.5, kanan, 17.5)
            self.set_y(23)
        self._y_badan = self.get_y()

    def footer(self) -> None:
        # Nomor halaman rata kiri: `{nb}` diganti jumlah halaman saat output, jadi lebarnya belum diketahui saat
        # ditempatkan dan rata kanan akan bergeser.
        self.set_y(-13)
        self.set_draw_color(*GARIS)
        self.set_line_width(0.2)
        self.line(_MARGIN, self.get_y() - 1.5, self.w - _MARGIN, self.get_y() - 1.5)
        self._gaya(False, 8, REDUP)
        self.set_x(_MARGIN)
        self.cell(60, 5, f"Halaman {self.page_no()} dari {{nb}}")
        self.cell(self.epw - 60, 5, teks_pdf("Dibuat otomatis oleh Jatahku"), align="R")

    # ------------------------------------------------------------------ bagian

    def susun(self) -> None:
        self.add_page()
        self._ringkasan()
        self._amplop()
        self._banding()
        self._pola_harian()
        self._terbesar()
        self._langganan()
        self._sorotan()
        self._lampiran()

    def _ringkasan(self) -> None:
        r = self.lap["ringkasan"]
        persen = r["persen_terpakai"]
        self._judul_bagian("Ringkasan", butuh=60)
        self._baris_kartu([
            ("Pemasukan", rupiah(r["pemasukan"]), None),
            ("Dialokasikan", rupiah(r["dialokasikan"]), None),
            ("Terpakai", rupiah(r["terpakai"]), None),
            ("Sisa", rupiah(r["sisa"]), None),
            ("Dibawa ke periode berikut", rupiah(r["dibawa"]), None),
            (
                "Persen terpakai", STRIP if persen is None else f"{persen}%",
                "tidak ada dasar perhitungan" if persen is None else "dari saldo awal amplop, tanpa tabungan",
            ),
        ], per_baris=3, tinggi=18.5)

    def _amplop(self) -> None:
        amplop = self.lap["amplop"]
        self._judul_bagian("Amplop", butuh=min(_TINGGI_JUDUL + _tinggi_tabel(len(amplop)), _MAKS_JAGA))
        if not amplop:
            self._catatan("Belum ada amplop di periode ini.")
            return
        baris = []
        for a in amplop:
            nama = _teks(a["nama"], STRIP) + (" (ditutup)" if a["ditutup"] else "")
            warna = _WARNA_STATUS.get(a["status"], REDUP)
            baris.append([
                nama, rupiah(a["awal"]), rupiah(a["terpakai"]), rupiah(a["akhir"]), rupiah(a["rollover"]),
                (_NAMA_STATUS.get(a["status"], a["status"]), FontFace(emphasis="BOLD", color=warna)),
            ])
        self._tabel(
            ["Amplop", "Saldo awal", "Terpakai", "Sisa", "Dibawa", "Status"], baris,
            bobot=[1, None, None, None, None, None], rata=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "LEFT"],
        )

    def _banding(self) -> None:
        b = self.lap["banding"]
        tabel = _tinggi_tabel(len(b["amplop"])) if b["amplop"] else 0.0
        self._judul_bagian("Dibanding periode lalu", butuh=min(_TINGGI_JUDUL + 16.5 + tabel, _MAKS_JAGA))
        self._baris_kartu([
            ("Terpakai periode ini", rupiah(self.lap["ringkasan"]["terpakai"]), None),
            ("Periode lalu", _rp(b["terpakai_lalu"]), None),
            ("Rata-rata 3 periode", _rp(b["terpakai_rata3"]), None),
            ("Perubahan", _perubahan(b["persen_perubahan"]), None),
        ], per_baris=4, tinggi=14.5)
        per_id = {a["id"]: a for a in self.lap["amplop"]}
        baris = []
        for sel in b["amplop"]:
            amplop = per_id.get(sel["id"])
            baris.append([
                _teks(amplop["nama"], STRIP) if amplop else STRIP,
                rupiah(amplop["terpakai"]) if amplop else STRIP,
                _rp(sel["terpakai_lalu"]), _rp(sel["terpakai_rata3"]),
            ])
        if baris:
            self._tabel(
                ["Amplop", "Periode ini", "Periode lalu", "Rata-rata 3 periode"], baris,
                bobot=[1, None, None, None], rata=["LEFT", "RIGHT", "RIGHT", "RIGHT"],
            )

    def _pola_harian(self) -> None:
        harian, terboros = self.lap["harian"], self.lap["hari_terboros"]
        self._judul_bagian("Pola harian", butuh=72)
        if terboros is None or not harian:
            self._catatan("Tidak ada hari dengan pengeluaran di periode ini.")
            return
        self._grafik_harian(harian, terboros["tanggal"])
        y = self.get_y()
        self.set_fill_color(*SOROT)
        self.rect(_MARGIN, y + 1.1, 2.8, 2.8, style="F")
        self._gaya(False, 9, TINTA)
        self.set_xy(_MARGIN + 4.5, y)
        self.cell(
            0, 5,
            teks_pdf(f"Hari terboros: {_tanggal(terboros['tanggal'])}{_TITIK_TENGAH}{rupiah(terboros['terpakai'])}"),
            new_x="LMARGIN", new_y="NEXT",
        )
        self.ln(1)

    def _grafik_harian(self, harian: list[dict], tanggal_terboros: str) -> None:
        """Batang terpakai per hari dari `rect`. Hari bertotal minus (pengembalian) tidak digambar; tinggi batang
        hanya skala tampilan dari angka `data`."""
        nilai = [max(Decimal(h["terpakai"]), Decimal(0)) for h in harian]
        puncak = _puncak_grafik(max(nilai))
        kiri, kanan, tinggi = _MARGIN + 17, self.w - _MARGIN, 36.0
        atas = self.get_y() + 3
        dasar = atas + tinggi
        for pecahan in (Decimal(0), Decimal("0.5"), Decimal(1)):
            y = dasar - tinggi * float(pecahan)
            self.set_draw_color(*GARIS)
            self.set_line_width(0.15)
            self.line(kiri, y, kanan, y)
            self._gaya(False, 7, REDUP)
            self.set_xy(_MARGIN, y - 1.8)
            self.cell(15.5, 3.6, _ringkas(puncak * pecahan), align="R")
        n = len(harian)
        slot = (kanan - kiri) / n
        lebar_batang = slot * 0.68
        for i, v in enumerate(nilai):
            if v <= 0:
                continue
            h = max(float(v / puncak) * tinggi, 0.35)
            self.set_fill_color(*(SOROT if harian[i]["tanggal"] == tanggal_terboros else MEREK_TERANG))
            self.rect(kiri + i * slot + (slot - lebar_batang) / 2, dasar - h, lebar_batang, h, style="F")
        self._gaya(False, 6.5, REDUP)
        for i in range(0, n, ceil(n / 31)):
            t = date.fromisoformat(harian[i]["tanggal"])
            tengah = kiri + i * slot + slot / 2
            self.set_xy(tengah - 4, dasar + 0.8)
            self.cell(8, 3, str(t.day), align="C")
            if i == 0 or t.day == 1:
                self.set_xy(tengah - 6, dasar + 3.6)
                self.cell(12, 3, BLN[t.month], align="C")
        self.set_xy(_MARGIN, dasar + 8)

    def _terbesar(self) -> None:
        terbesar = self.lap["terbesar"]
        self._judul_bagian(
            "5 pengeluaran terbesar", butuh=min(_TINGGI_JUDUL + _tinggi_tabel(len(terbesar)), _MAKS_JAGA)
        )
        if not terbesar:
            self._catatan("Belum ada pengeluaran di periode ini.")
            return
        baris = [
            [
                str(n), _tanggal_pendek(t["tanggal"]), _teks(t["amplop"], STRIP), _teks(t["keterangan"]),
                _teks(t["pencatat"]), rupiah(t["jumlah"]),
            ]
            for n, t in enumerate(terbesar, start=1)
        ]
        self._tabel(
            ["No", "Tanggal", "Amplop", "Keterangan", "Pencatat", "Jumlah"], baris,
            bobot=[None, None, 1, 1.8, 0.9, None], rata=["LEFT", "LEFT", "LEFT", "LEFT", "LEFT", "RIGHT"],
        )

    def _langganan(self) -> None:
        langganan = self.lap["langganan"]
        kelompok = (
            ("Terbayar di periode ini", "Tidak ada langganan yang terbayar di periode ini.", langganan["terbayar"]),
            ("Jatuh tempo di periode berikut", "Tidak ada langganan yang jatuh tempo di periode berikut.",
             langganan["jatuh_tempo"]),
        )
        tinggi_isi = [min(_tinggi_tabel(len(sel)) if sel else 8.0, _MAKS_JAGA) for _, _, sel in kelompok]
        self._judul_bagian("Langganan", butuh=min(_TINGGI_JUDUL + 7 + tinggi_isi[0], _MAKS_JAGA))
        for (judul, kosong, sel), tinggi in zip(kelompok, tinggi_isi):
            self._subjudul(judul, butuh=7 + tinggi)
            if not sel:
                self._catatan(kosong)
                continue
            self._tabel(
                ["Tanggal", "Nama", "Amplop", "Jumlah"],
                [
                    [_tanggal_pendek(s["tanggal"]), _teks(s["nama"], STRIP), _teks(s["amplop"], STRIP) if s["amplop"]
                     else STRIP, rupiah(s["jumlah"])]
                    for s in sel
                ],
                bobot=[None, 1.4, 1, None], rata=["LEFT", "LEFT", "LEFT", "RIGHT"],
            )

    def _sorotan(self) -> None:
        s = self.lap["sorotan"]
        self._judul_bagian("Sorotan", butuh=60)
        self._baris_kartu([
            ("Hari mencatat", f"{s['hari_mencatat']} hari", None),
            ("Catat beruntun terpanjang", f"{s['beruntun_terpanjang']} hari", None),
            ("Streak saat terbit", f"{s['streak_saat_ini']} hari", None),
        ], per_baris=3, tinggi=14.5)
        self._subjudul("Amplop yang tidak pernah lewat batas")
        aman = [n for n in (_teks(nama) for nama in s["amplop_aman"]) if n]
        self._gaya(False, 9.5, TINTA)
        self.set_x(_MARGIN)
        self.multi_cell(0, 5.2, ", ".join(aman) if aman else STRIP, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self._subjudul("Target tabungan")
        if not s["target"]:
            self._catatan("Belum ada target tabungan.")
            return
        for t in s["target"]:
            self._target(t)

    def _target(self, t: dict) -> None:
        """Satu target: nama dan persen, batang progres (dibatasi 100%), lalu terkumpul dari target."""
        self._butuh(16)
        persen = t["persen"]
        y = self.get_y()
        self._gaya(True, 9.5, TINTA)
        self.set_xy(_MARGIN, y)
        self.cell(self.epw - 30, 5, self._muat(_teks(t["nama"], STRIP), self.epw - 30, True, 9.5))
        self._gaya(True, 9.5, MEREK)
        self.cell(30, 5, STRIP if persen is None else f"{persen}%", align="R")
        batang = y + 6.4
        self.set_fill_color(*GARIS)
        self.rect(_MARGIN, batang, self.epw, 2.4, style="F", round_corners=True, corner_radius=1.2)
        if persen is not None and persen > 0:
            self.set_fill_color(*MEREK_TERANG)
            self.rect(_MARGIN, batang, max(self.epw * min(persen, 100) / 100, 2.4), 2.4, style="F",
                      round_corners=True, corner_radius=1.2)
        self._gaya(False, 8, REDUP)
        self.set_xy(_MARGIN, batang + 3.4)
        self.cell(self.epw, 4, teks_pdf(f"Terkumpul {rupiah(t['terkumpul'])} dari target {rupiah(t['target'])}"))
        self.set_xy(_MARGIN, batang + 10)

    def _lampiran(self) -> None:
        mutasi = self.lap["mutasi"]
        if mutasi:
            self.add_page()   # lampiran di halaman sendiri; bagian utama tidak terseret ke tabel panjang
        self._judul_bagian("Lampiran: mutasi", butuh=30)
        if not mutasi:
            self._catatan("Tidak ada pemasukan atau pengeluaran tercatat di periode ini.")
            return
        self._catatan("Pemasukan yang dicatat dan semua pengeluaran di lingkup laporan, menurut tanggal.")
        baris = []
        for m in mutasi:
            masuk = m["arah"] == "masuk"
            gaya = FontFace(color=REDUP) if m["penyesuaian"] else None

            def sel(teks: str, gaya_sel=gaya):
                return (teks, gaya_sel) if gaya_sel else teks

            baris.append([
                sel(_tanggal_pendek(m["tanggal"])), sel(_teks(m["keterangan"])),
                sel(_teks(m["amplop"], STRIP) if m["amplop"] else STRIP), sel(_teks(m["pencatat"])),
                (rupiah(m["jumlah"]), FontFace(color=gaya.color if gaya else MEREK)) if masuk else "",
                "" if masuk else sel(rupiah(m["jumlah"])),
            ])
        self._tabel(
            ["Tanggal", "Keterangan", "Amplop", "Pencatat", "Masuk", "Keluar"], baris,
            bobot=[None, 2.0, 1.25, 0.8, None, None], zebra=True,
            rata=["LEFT", "LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT"],
        )


def _isi_sel(sel) -> str:
    """Teks sebuah sel tabel, yang bisa berupa teks atau (teks, FontFace)."""
    return sel[0] if isinstance(sel, tuple) else sel


def _tebal(sel) -> bool:
    """Apakah sel tabel (teks, FontFace) bergaya tebal."""
    gaya = sel[1] if isinstance(sel, tuple) else None
    return gaya is not None and gaya.emphasis is not None and TextEmphasis.B in gaya.emphasis


def _bersihkan(dokumen: FPDF | None) -> None:
    """Dipanggil di `finally` setiap render. Tutup berkas font yang masih terbuka (fpdf2 menutupnya hanya di `output()`
    yang sukses) dan kosongkan cache glyph global fpdf2 (lihat docstring modul). Aman juga saat render lain berjalan di
    thread lain: fpdf2 sendiri mengosongkan cache itu di akhir tiap `output()`, dan hasil yang hilang dari cache
    dihitung ulang dengan nilai yang sama."""
    if dokumen is not None:
        for font in dokumen.fonts.values():
            tutup = getattr(font, "close", None)
            if tutup is not None:
                tutup()
    for fungsi in (SubsetMap.pick, SubsetMap.get_glyph):
        kosongkan = getattr(fungsi, "cache_clear", None)
        if kosongkan is not None:
            kosongkan()


def render_pdf(data: dict, kata_sandi: str) -> bytes:
    """PDF laporan dari `data` v1, dienkripsi AES-256 dengan `kata_sandi` sebagai kata sandi pengguna. Sinkron dan
    berat (puluhan hingga ratusan milidetik, lebih untuk ratusan baris mutasi): dari kode async lewat `buat_pdf`.
    `KataSandiPdfTidakValid` bila kata sandinya tidak bisa dipakai; `data` tidak diubah. Hasilnya hanya di memori."""
    periksa_kata_sandi(kata_sandi)
    dokumen = None
    try:
        dokumen = _Laporan(data)
        dokumen.susun()
        dokumen.set_encryption(
            owner_password=secrets.token_urlsafe(24),
            user_password=kata_sandi,
            encryption_method=EncryptionMethod.AES_256,
            permissions=_IZIN,
        )
        return bytes(dokumen.output())
    finally:
        _bersihkan(dokumen)


async def buat_pdf(data: dict, kata_sandi: str) -> bytes:
    """`render_pdf` di thread, paling banyak `MAKS_PDF_SERENTAK` sekaligus; permintaan lain menunggu giliran. Bila
    permintaan dibatalkan saat thread berjalan, slot dilepas padahal threadnya selesai sendiri beberapa saat
    kemudian."""
    async with _semafor_pdf:
        return await asyncio.to_thread(render_pdf, data, kata_sandi)
