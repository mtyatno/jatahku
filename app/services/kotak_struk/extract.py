"""Ekstraksi teks bukti bayar: gambar -> OCR, PDF -> lapisan teks / render + OCR, teks -> baris.

Hasilnya TextDoc untuk pembaca dokumen (registry). PDF dibaca di proses
terpisah dengan batas waktu dan memori (pdf_child.py, spec 3a/6b).
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

from app.services import receipt_ocr
from app.services.kotak_struk.config import PDF_MAX_PAGES, PDF_TIMEOUT_S
from app.services.kotak_struk.pdf_child import extract_pdf, limit_child_memory

log = logging.getLogger(__name__)

KIND_IMAGE = "image"
KIND_PDF_TEXT = "pdf_text"
KIND_PDF_OCR = "pdf_ocr"
KIND_TEXT = "text"


@dataclass
class TextDoc:
    lines: list[str]
    kind: str  # image | pdf_text | pdf_ocr | text
    pages: int = 1


class ExtractError(Exception):
    """Bukti tidak bisa dibaca; `user_message` aman ditampilkan ke user."""
    user_message = "Bukti tidak bisa dibaca."

    def __init__(self, user_message: str | None = None):
        if user_message is not None:
            self.user_message = user_message
        # args berisi pesan: exception ini harus bisa di-pickle lintas proses (anak PDF -> API).
        super().__init__(self.user_message)


class PdfLocked(ExtractError):
    user_message = "PDF terkunci kata sandi"


class PdfTooManyPages(ExtractError):
    user_message = f"PDF lebih dari {PDF_MAX_PAGES} halaman"


class PdfUnreadable(ExtractError):
    user_message = "PDF tidak bisa dibaca"


class ExtractUnavailable(ExtractError):
    user_message = "Baca bukti sedang tidak bisa. Catat manual dulu."


class ImageUnreadable(ExtractError):
    user_message = "Gambar tidak bisa dibaca. Coba kirim ulang."


def sniff_type(data: bytes) -> str | None:
    """Jenis file dari byte awalnya (bukan dari nama atau header kiriman)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _kill_pool(executor: ProcessPoolExecutor) -> None:
    """Hentikan paksa proses anak (yang mungkin macet di kode native) dan lepas pool."""
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        try:
            process.terminate()
        except (OSError, ValueError):  # sudah mati / sudah ditutup
            pass


async def run_pdf_isolated(
    data: bytes, *, timeout_s: int = PDF_TIMEOUT_S, max_pages: int = PDF_MAX_PAGES, fn=extract_pdf
) -> tuple[list[str], list[bytes], int]:
    """Jalankan `fn(data, max_pages)` di proses anak baru (spawn) dengan batas waktu.

    Satu pool per panggilan, jadi proses yang macet atau crash tidak memengaruhi
    panggilan lain. Timeout atau anak yang mati mendadak -> PdfUnreadable.
    """
    loop = asyncio.get_running_loop()
    executor = ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn"), initializer=limit_child_memory
    )
    try:
        return await asyncio.wait_for(loop.run_in_executor(executor, fn, data, max_pages), timeout_s)
    except TimeoutError as e:
        log.warning("PDF melewati batas waktu %ss; proses anak dimatikan", timeout_s)
        _kill_pool(executor)
        raise PdfUnreadable() from e
    except BrokenProcessPool as e:  # anak crash / dibunuh (mis. kehabisan memori)
        raise PdfUnreadable() from e
    except ImportError as e:  # pypdfium2 belum terpasang
        raise ExtractUnavailable() from e
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


async def _ocr_image(ocr, image: bytes) -> list[str]:
    # OcrBusy sengaja tidak ditangkap: worker yang memutuskan ulang-coba.
    try:
        result = await ocr(image, owner=None)
    except receipt_ocr.OcrUnavailable as e:
        raise ExtractUnavailable() from e
    except receipt_ocr.OcrFailed as e:
        raise ImageUnreadable() from e
    return result.lines


def _split_text(data: bytes) -> list[str]:
    text = data.decode("utf-8-sig", errors="replace")
    return [s.strip() for s in text.splitlines() if s.strip()]


async def extract_text(data: bytes, content_type: str, *, ocr=None, pdf_runner=None) -> TextDoc:
    """Ubah file bukti menjadi baris teks. `ocr` dan `pdf_runner` bisa diganti (tes)."""
    ocr = ocr or receipt_ocr.read_receipt_lines
    pdf_runner = pdf_runner or run_pdf_isolated
    ctype = (content_type or "").split(";")[0].strip().lower()

    if ctype == "text/plain":
        return TextDoc(lines=_split_text(data), kind=KIND_TEXT)
    if ctype.startswith("image/"):
        return TextDoc(lines=await _ocr_image(ocr, data), kind=KIND_IMAGE)
    if ctype == "application/pdf":
        lines, page_images, pages = await pdf_runner(data)
        lines = list(lines)
        for image in page_images:
            lines.extend(await _ocr_image(ocr, image))
        return TextDoc(lines=lines, kind=KIND_PDF_OCR if page_images else KIND_PDF_TEXT, pages=pages)
    raise ValueError(f"tipe berkas tidak didukung: {content_type!r}")
