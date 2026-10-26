import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
import asyncio, io, time, unittest
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import AsyncMock, patch
import pypdfium2
from PIL import Image
from app.services import receipt_ocr
from app.services.receipt_ocr import OcrResult
from app.services.kotak_struk import extract as X
from app.services.kotak_struk import pdf_child
from app.services.kotak_struk.pdf_child import extract_pdf

def minimal_pdf(lines):
    """PDF satu halaman berteks Helvetica (tanpa pustaka luar)."""
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out.encode())); out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode())
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return (out + f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()

def slow(data, max_pages, dpi=200):
    time.sleep(5)

def crash(data, max_pages, dpi=200):
    os._exit(1)

def missing_dependency(data, max_pages, dpi=200):
    import pustaka_pdf_yang_tidak_ada  # noqa: F401

class SniffTests(unittest.TestCase):
    def test_magic_bytes(self):
        self.assertEqual(X.sniff_type(b"\xff\xd8\xff\xe0xx"), "image/jpeg")
        self.assertEqual(X.sniff_type(b"\x89PNG\r\n\x1a\n"), "image/png")
        self.assertEqual(X.sniff_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(X.sniff_type(minimal_pdf(["a"])), "application/pdf")
        self.assertIsNone(X.sniff_type(b"<html>"))

class PdfTests(unittest.TestCase):
    def test_text_layer_read_without_ocr(self):
        lines, images, pages = extract_pdf(minimal_pdf(["Transfer Berhasil", "Nominal Rp150.000"]), max_pages=5)
        self.assertEqual((lines, images, pages), (["Transfer Berhasil", "Nominal Rp150.000"], [], 1))

    def test_garbage_pdf_is_unreadable(self):
        with self.assertRaises(X.PdfUnreadable):
            extract_pdf(b"%PDF-1.4 rusak", max_pages=5)

    def test_password_protected_pdf_is_locked(self):
        error = pypdfium2.PdfiumError("Failed to load document (PDFium: Incorrect password error).")
        with patch.object(pypdfium2, "PdfDocument", side_effect=error):
            with self.assertRaises(X.PdfLocked):
                extract_pdf(minimal_pdf(["a"]), max_pages=5)

    def test_too_many_pages_is_rejected(self):
        with self.assertRaises(X.PdfTooManyPages):
            extract_pdf(minimal_pdf(["a"]), max_pages=0)

    def test_page_without_text_is_rendered_to_png(self):
        lines, images, pages = extract_pdf(minimal_pdf([]), max_pages=5)
        self.assertEqual((lines, len(images), pages), ([], 1, 1))
        self.assertEqual(Image.open(io.BytesIO(images[0])).format, "PNG")

    def test_huge_page_render_is_capped(self):
        with patch.object(pdf_child, "MAX_RENDER_PIXELS", 1_000_000):
            _, images, _ = extract_pdf(minimal_pdf([]), max_pages=5)
        width, height = Image.open(io.BytesIO(images[0])).size
        # pdfium membulatkan tiap sisi ke atas, jadi batas hanya kira-kira; A4 pada 200 dpi = 3,9 MP.
        self.assertLess(width * height, 1_100_000)

class ExtractTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text(self):
        doc = await X.extract_text("Transfer berhasil\n\n  Rp150.000 \n".encode(), "text/plain")
        self.assertEqual((doc.lines, doc.kind), (["Transfer berhasil", "Rp150.000"], "text"))

    async def test_image_uses_ocr_without_owner(self):
        ocr = AsyncMock(return_value=OcrResult(lines=["QRIS", "Rp 25.000"], score=0.9, seconds=1))
        doc = await X.extract_text(b"\xff\xd8\xffimg", "image/jpeg", ocr=ocr)
        self.assertEqual((doc.lines, doc.kind), (["QRIS", "Rp 25.000"], "image"))
        self.assertIsNone(ocr.call_args.kwargs.get("owner"))

    async def test_scanned_pdf_pages_are_ocred(self):
        runner = AsyncMock(return_value=([], [b"png1"], 1))
        ocr = AsyncMock(return_value=OcrResult(lines=["Total Rp 99.000"], score=0.9, seconds=1))
        doc = await X.extract_text(minimal_pdf(["x"]), "application/pdf", ocr=ocr, pdf_runner=runner)
        self.assertEqual((doc.lines, doc.kind, doc.pages), (["Total Rp 99.000"], "pdf_ocr", 1))

    async def test_pdf_text_layer_only_is_pdf_text(self):
        runner = AsyncMock(return_value=(["Transfer Berhasil"], [], 2))
        ocr = AsyncMock()
        doc = await X.extract_text(minimal_pdf(["x"]), "application/pdf", ocr=ocr, pdf_runner=runner)
        self.assertEqual((doc.lines, doc.kind, doc.pages), (["Transfer Berhasil"], "pdf_text", 2))
        ocr.assert_not_called()

    async def test_pdf_timeout_is_unreadable(self):
        with self.assertRaises(X.PdfUnreadable), self.assertLogs(X.log, "WARNING"):
            await X.run_pdf_isolated(minimal_pdf(["a"]), timeout_s=1, fn=slow)

    async def test_pdf_timeout_terminates_child_process(self):
        spawned = []

        class Recording(ProcessPoolExecutor):
            def submit(self, *args, **kwargs):
                future = super().submit(*args, **kwargs)
                spawned.extend(self._processes.values())
                return future

        with patch.object(X, "ProcessPoolExecutor", Recording):
            with self.assertRaises(X.PdfUnreadable), self.assertLogs(X.log, "WARNING"):
                await X.run_pdf_isolated(minimal_pdf(["a"]), timeout_s=1, fn=slow)
        self.assertEqual(len(spawned), 1)
        for _ in range(40):
            if not spawned[0].is_alive():
                break
            await asyncio.sleep(0.05)
        self.assertFalse(spawned[0].is_alive())

    async def test_crashed_child_is_unreadable(self):
        with self.assertRaises(X.PdfUnreadable):
            await X.run_pdf_isolated(minimal_pdf(["a"]), timeout_s=10, fn=crash)

    async def test_missing_pdf_library_is_unavailable(self):
        with self.assertRaises(X.ExtractUnavailable):
            await X.run_pdf_isolated(minimal_pdf(["a"]), timeout_s=10, fn=missing_dependency)

    async def test_pdf_read_in_child_process(self):
        result = await X.run_pdf_isolated(minimal_pdf(["Transfer Berhasil", "Nominal Rp150.000"]))
        self.assertEqual(result, (["Transfer Berhasil", "Nominal Rp150.000"], [], 1))

    async def test_pdf_errors_cross_the_process_boundary(self):
        with self.assertRaises(X.PdfUnreadable):
            await X.run_pdf_isolated(b"%PDF-1.4 rusak")
        with self.assertRaises(X.PdfTooManyPages) as ctx:
            await X.run_pdf_isolated(minimal_pdf(["a"]), max_pages=0)
        self.assertEqual(ctx.exception.user_message, "PDF lebih dari 5 halaman")

    async def test_ocr_unavailable_and_failed_are_mapped(self):
        unavailable = AsyncMock(side_effect=receipt_ocr.OcrUnavailable())
        with self.assertRaises(X.ExtractUnavailable):
            await X.extract_text(b"\xff\xd8\xffimg", "image/jpeg", ocr=unavailable)
        failed = AsyncMock(side_effect=receipt_ocr.OcrFailed())
        with self.assertRaises(X.ImageUnreadable):
            await X.extract_text(b"\x89PNGimg", "image/png", ocr=failed)

    async def test_ocr_busy_propagates_unchanged(self):
        busy = AsyncMock(side_effect=receipt_ocr.OcrBusy("antrean scan penuh"))
        with self.assertRaises(receipt_ocr.OcrBusy):
            await X.extract_text(b"\xff\xd8\xffimg", "image/jpeg", ocr=busy)

    async def test_error_messages_for_user(self):
        self.assertEqual(X.PdfLocked().user_message, "PDF terkunci kata sandi")
        self.assertEqual(X.PdfTooManyPages().user_message, "PDF lebih dari 5 halaman")
