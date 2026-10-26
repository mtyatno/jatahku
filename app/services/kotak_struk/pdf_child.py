"""Pembaca PDF yang berjalan di proses anak (lihat extract.run_pdf_isolated).

PDF datang dari luar, jadi pustaka PDF (pdfium, kode native) tidak pernah
dijalankan di proses API: salah satu PDF jahat yang membuatnya macet, boros
memori, atau crash hanya mematikan proses anak. Modul ini sengaja ringan
(tanpa pypdfium2 di level modul) supaya proses anak spawn cepat menyala dan
extract.py tetap bisa diimpor walau pypdfium2 belum terpasang.

Semua fungsi di sini level modul agar bisa di-pickle untuk spawn. Skrip di
dalam PDF tidak pernah dijalankan (pdfium hanya mengurai dan merender).
"""
from __future__ import annotations

import io
import math
import re

from app.services.kotak_struk.config import PDF_MAX_PAGES

CHILD_MEMORY_LIMIT = 768 * 1024 * 1024  # batas ruang alamat proses anak
# Halaman raksasa (MediaBox ribuan poin) tidak dirender sebesar dpi penuh:
# 25 MP masih di bawah MAX_PIXELS OCR (30 MP) dan muat di batas memori anak.
MAX_RENDER_PIXELS = 25_000_000

_LINE_SPLIT = re.compile(r"\r\n|\n|\r")


def limit_child_memory() -> None:
    """Initializer proses anak: batasi ruang alamat. Diabaikan bila OS tidak mendukung."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY_LIMIT, CHILD_MEMORY_LIMIT))
    except (ImportError, ValueError, OSError):
        pass


def _render_png(page, dpi: int) -> bytes:
    scale = dpi / 72
    width, height = page.get_size()
    if width * height * scale * scale > MAX_RENDER_PIXELS:
        scale = math.sqrt(MAX_RENDER_PIXELS / (width * height))
    image = page.render(scale=scale).to_pil().convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def extract_pdf(data: bytes, max_pages: int = PDF_MAX_PAGES, dpi: int = 200) -> tuple[list[str], list[bytes], int]:
    """Baca PDF -> (baris teks semua halaman bertekst, PNG halaman tanpa teks, jumlah halaman).

    Halaman dianggap bertekst bila lapisan teksnya tidak kosong. Baris halaman
    bertekst digabung berurutan; halaman tanpa teks (hasil pindai) dirender
    ke PNG supaya dibaca OCR oleh pemanggil. Bila dokumen campuran, baris
    hasil OCR menyusul setelah baris lapisan teks.
    """
    # Impor di sini (bukan di level modul): extract.py mengimpor modul ini, dan
    # kelas galatnya didefinisikan di extract.py.
    from app.services.kotak_struk.extract import PdfLocked, PdfTooManyPages, PdfUnreadable
    import pypdfium2 as pdfium  # ImportError dibiarkan naik -> ExtractUnavailable di run_pdf_isolated

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise PdfLocked() from e
        raise PdfUnreadable() from e
    except Exception as e:
        raise PdfUnreadable() from e

    try:
        pages = len(pdf)
        if pages > max_pages:
            raise PdfTooManyPages()
        lines: list[str] = []
        images: list[bytes] = []
        for index in range(pages):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
                if text.strip():
                    lines.extend(s.strip() for s in _LINE_SPLIT.split(text) if s.strip())
                else:
                    images.append(_render_png(page, dpi))
            finally:
                page.close()
        return lines, images, pages
    except PdfTooManyPages:
        raise
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise PdfLocked() from e
        raise PdfUnreadable() from e
    except Exception as e:  # MemoryError (batas RLIMIT_AS), PDF rusak di tengah halaman, dll.
        raise PdfUnreadable() from e
    finally:
        pdf.close()
