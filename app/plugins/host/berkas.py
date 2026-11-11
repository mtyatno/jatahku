"""Berkas laporan dari plugin: `Laporan` (SDK) → PDF atau CSV, digambar host (Plugin U3).

Plugin tidak membuat byte berkas sendiri (kode plugin tidak boleh mengimpor fpdf2 atau csv; `kode.py`). Ia mengembalikan
`Laporan` dari rute GET, dan host yang menggambarnya, supaya gerbang "Laporan aman" (03-workflow.md, "Keamanan lebih
dulu") dijaga satu tempat untuk semua plugin:

- **PDF** lewat fpdf2 dengan font Noto Sans laporan berkala: teks digambar sebagai teks PDF, bukan HTML, jadi isi
  laporan (nama pelanggan, keterangan) tidak bisa menyisipkan markup; karakter di luar font dibuang `teks_pdf`. Tanpa
  kata sandi (diunduh langsung oleh owner/admin yang sudah login; keputusan E U3). Paling banyak `MAKS_PDF_SERENTAK`
  sekaligus, di thread, berbagi semafor dengan laporan berkala.
- **CSV** UTF-8 dengan BOM: setiap sel teks dari plugin lewat `_csv_text` (awalan rumus `= + - @` tab CR diberi kutip,
  PR #136); angka ditulis sebagai angka, tanggal ISO. Karakter rumus sesudah `;` di dalam teks juga diberi kutip
  (`_teks_csv`, review #204 S2): Excel berpemisah daftar `;` (bawaan regional Indonesia) memecah baris pada `;`, jadi
  `ayam;=1+1;` dari seorang karyawan tanpa ini menjadi sel rumus di lembar kerja pemilik.
- **Batas** (`periksa`): jumlah tabel, kolom, baris, dan panjang teks; jenis sel hanya teks, `Decimal`, `int`, `date`,
  atau None; angka harus terhingga, di bawah `MAKS_ANGKA`, dan paling banyak `MAKS_DESIMAL` angka di belakang koma
  (review #204 R1: `Decimal("1E+200000")` adalah sel 200 KB). Laporan yang melanggar = plugin bermasalah (500
  `plugin_gagal`), bukan dipotong diam-diam.
- **Unduhan**: `Content-Disposition: attachment` dengan nama yang dirapikan host, `X-Content-Type-Options: nosniff`,
  `Cache-Control: no-store`, dan CSP `default-src 'none'; sandbox` (route `/p`). Setiap unduhan diaudit tanpa angka.
- **Dua langkah** (review #204 S1): `pesan` memeriksa `Laporan` selagi fungsi plugin baru selesai (galat bentuk tetap
  500 `plugin_gagal` atas nama plugin itu); `buat` menggambarnya **sesudah** route membatasi frekuensi, mengaudit, dan
  melepas koneksi database, karena PDF ribuan baris makan detik dan mengantre semafor dua slot.
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

MAKS_TABEL = 12
MAKS_KOLOM = 8
MAKS_BARIS = 5000            # total baris semua tabel
MAKS_RINGKASAN = 12
MAKS_CATATAN = 10
MAKS_TEKS = 300
MAKS_DIGIT = 18              # |nilai| sel angka < 10^18; nominal `Numeric(15, 2)` dan jumlahnya jauh di bawah ini
MAKS_ANGKA = 10 ** MAKS_DIGIT
MAKS_DESIMAL = 12            # angka di belakang koma sebuah `Decimal`
FORMAT = {"pdf": ("application/pdf", "pdf"), "csv": ("text/csv; charset=utf-8", "csv")}


@dataclass(frozen=True)
class Berkas:
    isi: bytes
    media: str
    nama: str
    format: str


@dataclass(frozen=True)
class Pesanan:
    """`Laporan` yang sudah diperiksa dan menunggu digambar (`pesan` → route → `buat`)."""
    laporan: object
    ruang: str
    sekarang: datetime

    @property
    def format(self) -> str:
        return self.laporan.format


def _angka_sah(v) -> bool:
    """Angka sel yang teksnya pendek: terhingga, |v| < `MAKS_ANGKA`, pecahan ≤ `MAKS_DESIMAL` angka. `Decimal`
    diperiksa dari eksponennya saja, tanpa aritmetika dan tanpa menulis angkanya: `abs(Decimal("1E+999999999"))`
    melempar `decimal.Overflow`, dan teksnya saja sudah menghabiskan memori."""
    if isinstance(v, int):
        return -MAKS_ANGKA < v < MAKS_ANGKA
    return v.is_finite() and v.adjusted() < MAKS_DIGIT and v.as_tuple().exponent >= -MAKS_DESIMAL


def _sel_sah(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, Decimal)):
        return _angka_sah(v)
    return v is None or isinstance(v, (str, date)) and not isinstance(v, datetime)


def _teks(v, nama: str, maks: int = MAKS_TEKS) -> str:
    if not isinstance(v, str):
        raise TypeError(f"{nama} harus teks")
    return " ".join(v.split())[:maks]


def periksa(lap) -> None:
    """`TypeError`/`ValueError` bila `Laporan` tidak sah (jenis sel, jumlah tabel/kolom/baris, format)."""
    from app.plugins.sdk.context import Laporan, TabelLaporan
    if type(lap) is not Laporan:
        raise TypeError("bukan Laporan")
    if lap.format not in FORMAT:
        raise ValueError("format laporan harus pdf atau csv")
    _teks(lap.nama_berkas, "nama_berkas")
    _teks(lap.judul, "judul")
    _teks(lap.subjudul, "subjudul")
    if not isinstance(lap.ringkasan, tuple) or len(lap.ringkasan) > MAKS_RINGKASAN:
        raise ValueError("ringkasan terlalu banyak")
    for r in lap.ringkasan:
        if not isinstance(r, tuple) or len(r) != 2 or not isinstance(r[0], str) or not _sel_sah(r[1]):
            raise TypeError("ringkasan harus (label, nilai)")
    if not isinstance(lap.catatan, tuple) or len(lap.catatan) > MAKS_CATATAN:
        raise ValueError("catatan terlalu banyak")
    for c in lap.catatan:
        _teks(c, "catatan", 1000)
    if not isinstance(lap.tabel, tuple) or len(lap.tabel) > MAKS_TABEL:
        raise ValueError("tabel terlalu banyak")
    total_baris = 0
    for t in lap.tabel:
        if type(t) is not TabelLaporan:
            raise TypeError("tabel harus TabelLaporan")
        _teks(t.judul, "judul tabel")
        _teks(t.catatan, "catatan tabel", 1000)
        if not isinstance(t.kolom, tuple) or not 1 <= len(t.kolom) <= MAKS_KOLOM:
            raise ValueError(f"tabel harus 1–{MAKS_KOLOM} kolom")
        for k in t.kolom:
            _teks(k, "kolom")
        baris = list(t.baris) + ([t.total] if t.total is not None else [])
        if not isinstance(t.baris, tuple):
            raise TypeError("baris harus tuple")
        for b in baris:
            if not isinstance(b, tuple) or len(b) != len(t.kolom) or not all(_sel_sah(v) for v in b):
                raise TypeError("baris tabel tidak sah")
        total_baris += len(baris)
    if total_baris > MAKS_BARIS:
        raise ValueError(f"lebih dari {MAKS_BARIS} baris")


def nama_berkas(nama: str, ext: str) -> str:
    """Nama unduhan: huruf kecil, angka, dan tanda hubung saja, berawalan `jatahku-`."""
    dasar = re.sub(r"[^a-z0-9]+", "-", nama.lower()).strip("-")[:80] or "laporan"
    return f"jatahku-{dasar}.{ext}"


# ── CSV ──────────────────────────────────────────────────────────────────
_RUMUS_SESUDAH_PEMISAH = re.compile(r"(;\s*)(?=[=+\-@])")


def _teks_csv(v: str) -> str:
    """Sel teks CSV: spasi dirapatkan (tanpa baris baru atau tab), dipotong `MAKS_TEKS`, lalu karakter rumus di awal sel
    (`_csv_text`, PR #136) **dan sesudah setiap `;`** diberi kutip. Berkas ini berpemisah koma, tetapi Excel dengan
    pemisah daftar `;` membukanya dengan memecah baris pada `;`: bagian teks sesudah `;` menjadi awal sel baru."""
    from app.api.routes.export import _csv_text
    return _csv_text(_RUMUS_SESUDAH_PEMISAH.sub(r"\1'", " ".join(v.split())[:MAKS_TEKS]))


def _sel_csv(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return _teks_csv(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, date):
        return v.isoformat()
    return v


def render_csv(lap, *, ruang: str) -> bytes:
    """Satu berkas CSV berbagian: judul, ringkasan (label, nilai), lalu tiap tabel (judul, kepala, baris, total),
    dipisah baris kosong. Semua teks plugin lewat `_csv_text`."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([_sel_csv(lap.judul)])
    if lap.subjudul:
        w.writerow([_sel_csv(lap.subjudul)])
    w.writerow(["Ruang", _sel_csv(ruang)])
    if lap.ringkasan:
        w.writerow([])
        for label, nilai in lap.ringkasan:
            w.writerow([_sel_csv(label), _sel_csv(nilai)])
    for t in lap.tabel:
        w.writerow([])
        w.writerow([_sel_csv(t.judul)])
        w.writerow([_sel_csv(k) for k in t.kolom])
        for b in t.baris:
            w.writerow([_sel_csv(v) for v in b])
        if t.total is not None:
            w.writerow([_sel_csv(v) for v in t.total])
        if t.catatan:
            w.writerow([_sel_csv(t.catatan)])
    for c in lap.catatan:
        w.writerow([])
        w.writerow([_sel_csv(c)])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ── PDF ──────────────────────────────────────────────────────────────────
def _sel_pdf(v) -> str:
    from app.services.laporan.hitung import BLN
    from app.services.laporan.pdf import STRIP, rupiah, teks_pdf
    if v is None:
        return STRIP
    if isinstance(v, Decimal):
        return rupiah(format(v, "f"))
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, date):
        return f"{v.day} {BLN[v.month]} {v.year}"
    return teks_pdf(v[:MAKS_TEKS])


_PERSEN = r"^[-+\u2212]?[0-9][0-9.,]*%$"


def _kanan(t) -> list[bool]:
    """Kolom angka rata kanan: ada sel `Decimal`/`int`, atau semua sel terisi berupa persen ("25,4%")."""
    baris = list(t.baris) + ([t.total] if t.total is not None else [])
    hasil = []
    for i in range(len(t.kolom)):
        isi = [b[i] for b in baris if b[i] is not None]
        angka = any(isinstance(v, (Decimal, int)) for v in isi)
        persen = bool(isi) and all(isinstance(v, str) and re.fullmatch(_PERSEN, v) for v in isi)
        hasil.append(angka or persen)
    return hasil


def render_pdf(lap, *, ruang: str, dibuat: datetime) -> bytes:
    """PDF A4 tegak dari `Laporan`. Sinkron; dari kode async lewat `buat`."""
    from fpdf import FPDF
    from fpdf.enums import TableHeadingsDisplay
    from fpdf.fonts import FontFace

    from app.services.laporan import pdf as gaya
    teks_pdf = gaya.teks_pdf
    margin = gaya._MARGIN

    class _Dok(FPDF):
        def header(self):
            self.set_xy(margin, 11)
            self.set_font("NotoSans", "B", 12)
            self.set_text_color(*gaya.MEREK)
            self.cell(60, 6, "Jatahku")
            self.set_font("NotoSans", "", 8.5)
            self.set_text_color(*gaya.REDUP)
            self.cell(self.epw - 60, 6, teks_pdf(f"{ruang} · dibuat {dibuat.day} {_bln(dibuat)} {dibuat.year}"),
                      align="R")
            self.set_y(21)

        def footer(self):
            self.set_y(-13)
            self.set_draw_color(*gaya.GARIS)
            self.set_line_width(0.2)
            self.line(margin, self.get_y() - 1.5, self.w - margin, self.get_y() - 1.5)
            self.set_font("NotoSans", "", 8)
            self.set_text_color(*gaya.REDUP)
            self.set_x(margin)
            self.cell(60, 5, f"Halaman {self.page_no()} dari {{nb}}")
            self.cell(self.epw - 60, 5, teks_pdf("Dibuat otomatis oleh Jatahku"), align="R")

    def _bln(d):
        from app.services.laporan.hitung import BLN
        return BLN[d.month]

    dok = None
    try:
        dok = _Dok(orientation="P", unit="mm", format="A4")
        dok.set_margins(margin, margin, margin)
        dok.set_auto_page_break(auto=True, margin=20)
        dok.alias_nb_pages()
        dok.add_font("NotoSans", "", str(gaya.FONT_REGULAR))
        dok.add_font("NotoSans", "B", str(gaya.FONT_BOLD))
        dok.set_title(teks_pdf(lap.judul))
        dok.set_author("Jatahku")
        dok.set_creator("Jatahku")
        dok.set_lang("id")
        dok.add_page()

        dok.set_font("NotoSans", "B", 17)
        dok.set_text_color(*gaya.TINTA)
        dok.multi_cell(0, 8, teks_pdf(lap.judul), new_x="LMARGIN", new_y="NEXT")
        if lap.subjudul:
            dok.set_font("NotoSans", "", 10)
            dok.set_text_color(*gaya.REDUP)
            dok.multi_cell(0, 5.5, teks_pdf(lap.subjudul), new_x="LMARGIN", new_y="NEXT")
        dok.ln(3)

        if lap.ringkasan:
            per_baris, celah, tinggi = 3, 4.0, 15.0
            lebar = (dok.epw - celah * (per_baris - 1)) / per_baris
            for i, (label, nilai) in enumerate(lap.ringkasan):
                if i % per_baris == 0:
                    if i:
                        dok.set_y(y + tinggi + celah)
                    if dok.get_y() + tinggi > dok.page_break_trigger:
                        dok.add_page()
                    y = dok.get_y()
                x = margin + (i % per_baris) * (lebar + celah)
                dok.set_fill_color(*gaya.LATAR)
                dok.rect(x, y, lebar, tinggi, style="F", round_corners=True, corner_radius=2)
                dok.set_font("NotoSans", "", 8)
                dok.set_text_color(*gaya.REDUP)
                dok.set_xy(x + 3, y + 2.2)
                dok.cell(lebar - 6, 4, _muat(dok, teks_pdf(label[:80]), lebar - 6, False, 8))
                dok.set_text_color(*gaya.TINTA)
                dok.set_xy(x + 3, y + 7.2)
                dok.cell(lebar - 6, 6, _muat(dok, _sel_pdf(nilai), lebar - 6, True, 13))
            dok.set_xy(margin, y + tinggi + 4)

        for t in lap.tabel:
            if dok.get_y() + 30 > dok.page_break_trigger:
                dok.add_page()
            dok.ln(3)
            dok.set_font("NotoSans", "B", 12)
            dok.set_text_color(*gaya.MEREK)
            dok.set_x(margin)
            dok.cell(0, 7, teks_pdf(t.judul), new_x="LMARGIN", new_y="NEXT")
            kanan = _kanan(t)
            dok.set_font("NotoSans", "", gaya._UKURAN_TABEL)
            dok.set_text_color(*gaya.TINTA)
            dok.set_draw_color(*gaya.GARIS)
            dok.set_line_width(0.2)
            dok.set_fill_color(0)
            with dok.table(
                text_align=["RIGHT" if k else "LEFT" for k in kanan], line_height=gaya._TINGGI_BARIS,
                padding=gaya._PADDING_TABEL, borders_layout="HORIZONTAL_LINES",
                repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE,
                headings_style=FontFace(emphasis="BOLD", color=gaya.TEKS_KEPALA, fill_color=gaya.LATAR_KEPALA),
            ) as tabel:
                kepala = tabel.row()
                for k in t.kolom:
                    kepala.cell(teks_pdf(k[:80]))
                if not t.baris:
                    kosong = tabel.row()
                    kosong.cell("Belum ada catatan.", colspan=len(t.kolom))
                for b in t.baris:
                    r = tabel.row()
                    for v in b:
                        r.cell(_sel_pdf(v))
                if t.total is not None:
                    r = tabel.row()
                    tebal = FontFace(emphasis="BOLD")
                    for v in t.total:            # sel kosong baris total dibiarkan kosong, bukan "—"
                        r.cell("" if v is None else _sel_pdf(v), style=tebal)
            if t.catatan:
                dok.set_font("NotoSans", "", 8.5)
                dok.set_text_color(*gaya.REDUP)
                dok.multi_cell(0, 4.5, teks_pdf(t.catatan), new_x="LMARGIN", new_y="NEXT")
            dok.set_x(margin)

        if lap.catatan:
            dok.ln(4)
            dok.set_font("NotoSans", "", 8.5)
            dok.set_text_color(*gaya.REDUP)
            for c in lap.catatan:
                dok.multi_cell(0, 4.5, teks_pdf(c), new_x="LMARGIN", new_y="NEXT")
                dok.ln(1)
        return bytes(dok.output())
    finally:
        gaya._bersihkan(dok)


def _muat(dok, teks: str, lebar: float, tebal: bool, ukuran: float, minimal: float = 7.0) -> str:
    """Ukuran font terbesar (paling kecil `minimal`) yang membuat `teks` muat; bila masih kebesaran, dipotong "…"."""
    gaya = "B" if tebal else ""
    while ukuran > minimal:
        dok.set_font("NotoSans", gaya, ukuran)
        if dok.get_string_width(teks) <= lebar:
            return teks
        ukuran -= 0.5
    dok.set_font("NotoSans", gaya, minimal)
    while len(teks) > 1 and dok.get_string_width(teks) > lebar:
        teks = teks[:-2].rstrip() + "\N{HORIZONTAL ELLIPSIS}"
    return teks


def pesan(lap, *, ruang: str, sekarang: datetime) -> Pesanan:
    """`Laporan` dari fungsi plugin → `Pesanan` (sudah lewat `periksa`; `TypeError`/`ValueError` bila tidak sah).
    Murah dan tanpa I/O: dipanggil `titik.jalankan_rute` selagi transaksi database permintaan masih terbuka."""
    periksa(lap)
    return Pesanan(laporan=lap, ruang=ruang, sekarang=sekarang)


async def buat(lap, *, ruang: str, sekarang: datetime) -> Berkas:
    """`Laporan` → `Berkas`. Diperiksa dulu (`periksa`); PDF di thread lewat semafor laporan berkala. Pemanggil sudah
    melepas koneksi database (`routes/plugins._kirim_berkas`): menunggu giliran semafor tidak menahan kolam."""
    periksa(lap)
    media, ext = FORMAT[lap.format]
    if lap.format == "csv":
        isi = render_csv(lap, ruang=ruang)
    else:
        from app.services.laporan import pdf as gaya
        async with gaya._semafor_pdf:
            isi = await asyncio.to_thread(render_pdf, lap, ruang=ruang, dibuat=sekarang)
    return Berkas(isi=isi, media=media, nama=nama_berkas(lap.nama_berkas, ext), format=lap.format)
