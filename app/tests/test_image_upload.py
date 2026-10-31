"""Keamanan unggahan gambar (`app/services/image_upload.py`).

`POST /user/profile-pic` dan `POST /payment/upload-proof/{id}` dulu menulis berkas ke `public_html/uploads`
(origin jatahku.com, sama dengan app yang menyimpan token di localStorage) dengan ekstensi dari nama file klien
dan tanpa memeriksa isinya: `x.html` ber-content-type `image/png` disajikan nginx sebagai HTML, jadi skripnya
jalan di origin app (XSS tersimpan, token bisa dicuri). Sekarang jenis file ditentukan dari isinya (byte awal),
nama file dibuat server, dan nama file serta content-type kiriman klien tidak dipakai untuk apa pun.

Run: python -m unittest app.tests.test_image_upload -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import io
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import payment, user_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.services import account_deletion, image_upload
from app.tests.fakes import FakeResult, db_with

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16
GIF87 = b"GIF87a" + b"\x01\x00\x01\x00\x00\x00\x00;"
GIF89 = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00;"
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16
HTML = b"<html><script>alert(1)</script>"
SVG = b"<?xml version='1.0'?><svg onload='x'>"
PDF = b"%PDF-1.7"
HEIC = b"\x00\x00\x00\x18ftypheic"

MSG_TIPE = "File harus gambar JPG, PNG, WEBP, atau GIF"
MSG_2MB = "Ukuran gambar maksimal 2 MB"
MSG_8MB = "Ukuran gambar maksimal 8 MB"

sniff = image_upload.sniff_image_ext
read_image_upload = image_upload.read_image_upload


def upload(data: bytes, filename: str | None = "foto.png", content_type: str | None = "image/png") -> UploadFile:
    """UploadFile asli (Starlette) di atas BytesIO, dengan nama file dan content-type seperti yang dikirim klien."""
    headers = Headers({"content-type": content_type}) if content_type else None
    return UploadFile(io.BytesIO(data), filename=filename, headers=headers)


class NoClientMetaUpload:
    """UploadFile tiruan yang gagal bila nama file atau content-type klien dibaca; `read_sizes` mencatat panggilan read."""
    size = None

    def __init__(self, data: bytes):
        self._data = data
        self.read_sizes = []

    @property
    def filename(self):
        raise AssertionError("nama file kiriman klien dibaca")

    @property
    def content_type(self):
        raise AssertionError("content-type kiriman klien dibaca")

    async def read(self, size=-1):
        self.read_sizes.append(size)
        return self._data[:size] if size >= 0 else self._data


class TmpUploadDirCase(unittest.IsolatedAsyncioTestCase):
    """`UPLOAD_DIR` dialihkan ke folder sementara yang belum ada (pembuatan folder ikut teruji)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "uploads")
        patcher = patch.object(image_upload, "UPLOAD_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def written(self) -> list[str]:
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def read_file(self, name: str) -> bytes:
        with open(os.path.join(self.dir, name), "rb") as f:
            return f.read()


# ── sniff_image_ext ──────────────────────────────────────────────────────────────────────────

class SniffImageExtTests(unittest.TestCase):
    def test_each_image_type_is_recognised_from_its_magic_bytes(self):
        for data, ext in [(PNG, "png"), (JPG, "jpg"), (GIF87, "gif"), (GIF89, "gif"), (WEBP, "webp")]:
            with self.subTest(ext=ext, head=data[:12]):
                self.assertEqual(sniff(data), ext)

    def test_minimal_magic_bytes_are_enough(self):
        self.assertEqual(sniff(b"\x89PNG\r\n\x1a\n"), "png")
        self.assertEqual(sniff(b"\xff\xd8\xff"), "jpg")
        self.assertEqual(sniff(b"GIF87a"), "gif")
        self.assertEqual(sniff(b"GIF89a"), "gif")
        self.assertEqual(sniff(b"RIFF\x00\x00\x00\x00WEBP"), "webp")

    def test_html_svg_pdf_heic_and_empty_are_not_images(self):
        for name, data in {
            "html": HTML,
            "svg": SVG,
            "pdf": PDF,
            "heic": HEIC,
            "kosong": b"",
        }.items():
            with self.subTest(name):
                self.assertIsNone(sniff(data))

    def test_lookalikes_and_truncated_headers_are_not_images(self):
        for name, data in {
            "RIFF WAVE (bukan WEBP)": b"RIFF\x24\x00\x00\x00WAVEfmt ",
            "RIFF terpotong": b"RIFF\x00\x00\x00\x00WEB",
            "PNG terpotong": b"\x89PNG\r\n\x1a",
            "PNG tanpa CRLF": b"\x89PNG\n\n\n\n",
            "GIF88a": b"GIF88a",
            "GIF terpotong": b"GIF",
            "JPEG terpotong": b"\xff\xd8",
            "BMP": b"BM" + b"\x00" * 16,
            "svg ber-BOM": b"\xef\xbb\xbf<svg xmlns='http://www.w3.org/2000/svg'/>",
            "html didahului spasi": b"\n <!DOCTYPE html><script>1</script>",
            "teks biasa": b"hello",
            "nol semua": b"\x00" * 32,
            "magic bukan di awal": b"junk" + PNG,
        }.items():
            with self.subTest(name):
                self.assertIsNone(sniff(data))


# ── read_image_upload ────────────────────────────────────────────────────────────────────────

class ReadImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_png_returns_data_and_extension(self):
        self.assertEqual(await read_image_upload(upload(PNG), 2_000_000), (PNG, "png"))

    async def test_extension_comes_from_content_not_from_client(self):
        for data, ext in [(PNG, "png"), (JPG, "jpg"), (GIF89, "gif"), (WEBP, "webp")]:
            with self.subTest(ext=ext):
                got = await read_image_upload(upload(data, "bukan-gambar.bin", "application/octet-stream"), 1000)
                self.assertEqual(got, (data, ext))

    async def test_oversize_profile_pic_is_400_with_exact_message(self):
        too_big = PNG + b"\x00" * (2_000_000 - len(PNG) + 1)
        self.assertEqual(len(too_big), 2_000_001)
        with self.assertRaises(HTTPException) as ctx:
            await read_image_upload(upload(too_big), image_upload.PROFILE_PIC_MAX_BYTES)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_2MB))

    async def test_exactly_the_limit_is_accepted(self):
        at_limit = PNG + b"\x00" * (2_000_000 - len(PNG))
        data, ext = await read_image_upload(upload(at_limit), image_upload.PROFILE_PIC_MAX_BYTES)
        self.assertEqual((len(data), ext), (2_000_000, "png"))

    async def test_payment_proof_limit_is_8_mib_and_message_says_8_mb(self):
        limit = image_upload.PAYMENT_PROOF_MAX_BYTES
        at_limit = JPG + b"\x00" * (limit - len(JPG))
        data, ext = await read_image_upload(upload(at_limit, "x.jpg", "image/jpeg"), limit)
        self.assertEqual((len(data), ext), (limit, "jpg"))
        with self.assertRaises(HTTPException) as ctx:
            await read_image_upload(upload(at_limit + b"\x00", "x.jpg", "image/jpeg"), limit)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_8MB))

    async def test_size_is_checked_before_type(self):
        # berkas raksasa non-gambar dijawab soal ukuran, bukan soal jenis
        with self.assertRaises(HTTPException) as ctx:
            await read_image_upload(upload(b"<" * 2_000_001), 2_000_000)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_2MB))

    async def test_never_reads_more_than_limit_plus_one_byte(self):
        spy = NoClientMetaUpload(PNG + b"\x00" * 5000)
        with self.assertRaises(HTTPException) as ctx:
            await read_image_upload(spy, 1000)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(spy.read_sizes, [1001])

    async def test_html_body_is_rejected_whatever_the_client_says(self):
        for filename, content_type in [
            ("evil.html", "image/png"), ("foto.png", "image/png"), ("x.svg", "image/svg+xml"),
            ("x.jpg", "image/jpeg"), (None, None),
        ]:
            with self.subTest(filename=filename, content_type=content_type):
                with self.assertRaises(HTTPException) as ctx:
                    await read_image_upload(upload(HTML, filename, content_type), 2_000_000)
                self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_TIPE))

    async def test_svg_pdf_heic_and_empty_are_rejected(self):
        for name, data in {"svg": SVG, "pdf": PDF, "heic": HEIC, "kosong": b""}.items():
            with self.subTest(name):
                with self.assertRaises(HTTPException) as ctx:
                    await read_image_upload(upload(data, f"x.{name}", "image/png"), 2_000_000)
                self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_TIPE))


# ── save_upload ──────────────────────────────────────────────────────────────────────────────

class SaveUploadTests(TmpUploadDirCase):
    def test_writes_under_upload_dir_creating_it_and_returns_public_path(self):
        self.assertFalse(os.path.exists(self.dir))
        path = image_upload.save_upload("abc-123_X", "png", PNG)
        self.assertEqual(path, "/uploads/abc-123_X.png")
        self.assertEqual(self.written(), ["abc-123_X.png"])
        self.assertEqual(self.read_file("abc-123_X.png"), PNG)

    def test_accepts_the_stems_the_routes_build(self):
        uid = uuid4()
        for stem in (str(uid), f"proof_{uid}"):
            with self.subTest(stem=stem):
                self.assertEqual(image_upload.save_upload(stem, "jpg", JPG), f"/uploads/{stem}.jpg")
        self.assertEqual(self.written(), sorted([f"{uid}.jpg", f"proof_{uid}.jpg"]))

    def test_second_upload_with_same_stem_replaces_the_file(self):
        image_upload.save_upload("u1", "png", PNG)
        image_upload.save_upload("u1", "png", PNG + b"baru")
        self.assertEqual(self.read_file("u1.png"), PNG + b"baru")

    def test_unsafe_stems_raise_value_error_and_write_nothing(self):
        for stem in ["", ".", "..", "../x", "a/b", "/etc/passwd", "a.b", "a b", "abc\n", "a\x00b", "a\\b", "é", "x.html"]:
            with self.subTest(stem=stem):
                with self.assertRaises(ValueError):
                    image_upload.save_upload(stem, "png", PNG)
        for not_a_str in (None, 123, uuid4()):
            with self.subTest(stem=not_a_str):
                with self.assertRaises(ValueError):
                    image_upload.save_upload(not_a_str, "png", PNG)
        self.assertEqual(self.written(), [])

    def test_non_image_extensions_raise_value_error_and_write_nothing(self):
        for ext in ["html", "htm", "xhtml", "svg", "js", "", "png/../x", "PNG", "jpg.html", ".png"]:
            with self.subTest(ext=ext):
                with self.assertRaises(ValueError):
                    image_upload.save_upload("u1", ext, PNG)
        self.assertEqual(self.written(), [])


class ConstantsTests(unittest.TestCase):
    def test_limits_and_directory(self):
        self.assertEqual(image_upload.PROFILE_PIC_MAX_BYTES, 2_000_000)
        self.assertEqual(image_upload.PAYMENT_PROOF_MAX_BYTES, 8 * 1024 * 1024)
        self.assertEqual(image_upload.UPLOAD_DIR, "/home/jatahku/web/jatahku.com/public_html/uploads")

    def test_directory_matches_the_one_account_deletion_cleans(self):
        # hapus akun menghapus `/uploads/<nama>` di bawah UPLOAD_ROOT: menulis dan menghapus harus satu folder
        self.assertEqual(os.path.join(account_deletion.UPLOAD_ROOT, "uploads"), image_upload.UPLOAD_DIR)


# ── rute: handler dipanggil langsung ─────────────────────────────────────────────────────────

class ProfilePicRouteTests(TmpUploadDirCase):
    def setUp(self):
        super().setUp()
        self.uid = uuid4()
        self.user = SimpleNamespace(id=self.uid, profile_pic="/uploads/lama.png")
        self.db = db_with()

    async def call(self, file):
        return await user_settings.upload_profile_pic(file=file, user=self.user, db=self.db)

    def assert_rejected(self, ctx, detail):
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, detail))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.user.profile_pic, "/uploads/lama.png")
        self.db.commit.assert_not_awaited()

    async def test_html_named_evil_html_with_image_content_type_is_rejected_and_not_written(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(upload(HTML, "evil.html", "image/png"))
        self.assert_rejected(ctx, MSG_TIPE)

    async def test_svg_and_other_markup_extensions_are_rejected(self):
        for filename, body in [("x.svg", SVG), ("x.htm", HTML), ("x.xhtml", HTML), ("x.svg", HTML)]:
            with self.subTest(filename=filename):
                with self.assertRaises(HTTPException) as ctx:
                    await self.call(upload(body, filename, "image/png"))
                self.assert_rejected(ctx, MSG_TIPE)

    async def test_real_png_named_evil_html_is_stored_as_uid_png(self):
        out = await self.call(upload(PNG, "evil.html", "image/png"))
        self.assertEqual(out, {"url": f"/uploads/{self.uid}.png"})
        self.assertEqual(self.written(), [f"{self.uid}.png"])
        self.assertEqual(self.read_file(f"{self.uid}.png"), PNG)
        self.assertEqual(self.user.profile_pic, f"/uploads/{self.uid}.png")
        self.db.commit.assert_awaited_once()

    async def test_png_magic_followed_by_html_never_gets_an_html_extension(self):
        # poliglot: byte awal PNG + HTML. Disimpan sebagai .png (nginx menyajikan image/png), tidak pernah .html
        body = PNG + b"<html><script>alert(document.domain)</script></html>"
        await self.call(upload(body, "evil.html", "text/html"))
        self.assertEqual(self.written(), [f"{self.uid}.png"])

    async def test_client_filename_and_content_type_are_never_read(self):
        out = await self.call(NoClientMetaUpload(JPG))
        self.assertEqual(out, {"url": f"/uploads/{self.uid}.jpg"})
        self.assertEqual(self.written(), [f"{self.uid}.jpg"])

    async def test_extension_is_normalised_whatever_the_client_calls_the_file(self):
        for filename, content_type in [("foto.JPEG", "image/jpeg"), ("foto.exe", "application/octet-stream"),
                                       (None, None), ("tanpa-titik", "")]:
            with self.subTest(filename=filename):
                out = await self.call(upload(JPG, filename, content_type))
                self.assertEqual(out, {"url": f"/uploads/{self.uid}.jpg"})
        self.assertEqual(self.written(), [f"{self.uid}.jpg"])

    async def test_oversize_is_rejected_with_2_mb_message(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.call(upload(PNG + b"\x00" * 2_000_000))
        self.assert_rejected(ctx, MSG_2MB)

    async def test_two_megabytes_exactly_is_still_accepted(self):
        await self.call(upload(PNG + b"\x00" * (2_000_000 - len(PNG))))
        self.assertEqual(self.written(), [f"{self.uid}.png"])


class UploadProofRouteTests(TmpUploadDirCase):
    def setUp(self):
        super().setUp()
        self.user = SimpleNamespace(id=uuid4(), name="Budi", email="budi@test.example")
        self.order_id = uuid4()
        self.order = SimpleNamespace(id=self.order_id, user_id=self.user.id, status="pending",
                                     amount=Decimal("79000"), proof_url=None)

    def db(self, order="default", admins=()):
        order = self.order if order == "default" else order
        return db_with(FakeResult(order), FakeResult(rows=list(admins)))

    async def call(self, file, db):
        return await payment.upload_proof(order_id=self.order_id, file=file, user=self.user, db=db)

    def assert_untouched(self, db):
        self.assertEqual(self.written(), [])
        self.assertEqual((self.order.status, self.order.proof_url), ("pending", None))
        db.commit.assert_not_awaited()

    async def test_html_body_is_rejected_and_order_stays_pending(self):
        db = self.db()
        with self.assertRaises(HTTPException) as ctx:
            await self.call(upload(HTML, "bukti.html", "image/png"), db)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_TIPE))
        self.assert_untouched(db)
        self.assertEqual(db.execute.await_count, 1)  # hanya cari order; belum sampai notifikasi admin

    async def test_svg_body_is_rejected(self):
        db = self.db()
        with self.assertRaises(HTTPException) as ctx:
            await self.call(upload(SVG, "bukti.svg", "image/svg+xml"), db)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_TIPE))
        self.assert_untouched(db)

    async def test_jpeg_named_x_svg_is_stored_as_proof_order_id_jpg(self):
        db = self.db()
        out = await self.call(upload(JPG, "x.svg", "image/svg+xml"), db)
        self.assertEqual(out, {"status": "waiting_confirmation",
                               "message": "Bukti transfer diterima. Admin akan memverifikasi."})
        self.assertEqual(self.written(), [f"proof_{self.order_id}.jpg"])
        self.assertEqual(self.read_file(f"proof_{self.order_id}.jpg"), JPG)
        self.assertEqual(self.order.proof_url, f"/uploads/proof_{self.order_id}.jpg")
        self.assertEqual(self.order.status, "waiting_confirmation")
        db.commit.assert_awaited_once()

    async def test_client_filename_and_content_type_are_never_read(self):
        await self.call(NoClientMetaUpload(WEBP), self.db())
        self.assertEqual(self.written(), [f"proof_{self.order_id}.webp"])

    async def test_limit_is_8_mb_not_the_profile_pic_2_mb(self):
        db = self.db()
        with self.assertRaises(HTTPException) as ctx:  # melebihi 8 MiB: ditolak, order tidak tersentuh
            await self.call(upload(JPG + b"\x00" * image_upload.PAYMENT_PROOF_MAX_BYTES, "x.jpg", "image/jpeg"), db)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, MSG_8MB))
        self.assert_untouched(db)
        await self.call(upload(JPG + b"\x00" * 3_000_000, "x.jpg", "image/jpeg"), self.db())  # 3 MB: lolos (> 2 MB foto profil)
        self.assertEqual(self.written(), [f"proof_{self.order_id}.jpg"])

    async def test_unknown_order_is_404_before_the_body_is_read(self):
        file = NoClientMetaUpload(HTML)
        db = self.db(order=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.call(file, db)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (404, "Order tidak ditemukan"))
        self.assertEqual(file.read_sizes, [])
        self.assertEqual(self.written(), [])

    async def test_processed_order_is_400_before_the_body_is_read(self):
        self.order.status = "completed"
        file = NoClientMetaUpload(HTML)
        db = self.db()
        with self.assertRaises(HTTPException) as ctx:
            await self.call(file, db)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (400, "Order sudah diproses"))
        self.assertEqual(file.read_sizes, [])
        self.assertEqual(self.written(), [])
        self.assertEqual(self.order.status, "completed")
        db.commit.assert_not_awaited()

    async def test_admins_are_still_notified_after_a_valid_upload(self):
        admin = SimpleNamespace(id=uuid4(), email="admin@test.example")
        db = self.db(admins=[admin])
        with patch("app.services.email_service.send_email", return_value=True) as send:
            await self.call(upload(JPG, "x.jpg", "image/jpeg"), db)
        notifs = [c.args[0] for c in db.add.call_args_list]
        self.assertEqual([(n.user_id, n.link) for n in notifs], [(admin.id, "/admin")])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "admin@test.example")
        db.commit.assert_awaited_once()


# ── rute lewat HTTP (multipart sungguhan) ────────────────────────────────────────────────────

class UploadHttpTests(TmpUploadDirCase):
    async def asyncSetUp(self):
        self.uid = uuid4()
        self.order_id = uuid4()
        self.user = SimpleNamespace(id=self.uid, name="Budi", email="budi@test.example", profile_pic=None)
        self.order = SimpleNamespace(id=self.order_id, user_id=self.uid, status="pending",
                                     amount=Decimal("79000"), proof_url=None)
        self.db = db_with(FakeResult(self.order), FakeResult(rows=[]))
        app = FastAPI()
        app.include_router(user_settings.router, prefix="/user")
        app.include_router(payment.router, prefix="/payment")
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def test_profile_pic_html_with_image_content_type_is_400(self):
        r = await self.client.post("/user/profile-pic", files={"file": ("evil.html", HTML, "image/png")})
        self.assertEqual((r.status_code, r.json()), (400, {"detail": MSG_TIPE}))
        self.assertEqual(self.written(), [])
        self.assertIsNone(self.user.profile_pic)

    async def test_profile_pic_real_png_named_evil_html_is_stored_as_png(self):
        r = await self.client.post("/user/profile-pic", files={"file": ("evil.html", PNG, "text/html")})
        self.assertEqual((r.status_code, r.json()), (200, {"url": f"/uploads/{self.uid}.png"}))
        self.assertEqual(self.written(), [f"{self.uid}.png"])

    async def test_profile_pic_oversize_is_400(self):
        r = await self.client.post("/user/profile-pic", files={"file": ("a.png", PNG + b"\x00" * 2_000_000, "image/png")})
        self.assertEqual((r.status_code, r.json()), (400, {"detail": MSG_2MB}))
        self.assertEqual(self.written(), [])

    async def test_payment_proof_svg_is_400(self):
        r = await self.client.post(f"/payment/upload-proof/{self.order_id}",
                                   files={"file": ("bukti.svg", SVG, "image/svg+xml")})
        self.assertEqual((r.status_code, r.json()), (400, {"detail": MSG_TIPE}))
        self.assertEqual(self.written(), [])
        self.assertEqual((self.order.status, self.order.proof_url), ("pending", None))

    async def test_payment_proof_jpeg_named_x_svg_is_stored_as_jpg(self):
        r = await self.client.post(f"/payment/upload-proof/{self.order_id}",
                                   files={"file": ("x.svg", JPG, "image/svg+xml")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "waiting_confirmation")
        self.assertEqual(self.written(), [f"proof_{self.order_id}.jpg"])
        self.assertEqual(self.order.proof_url, f"/uploads/proof_{self.order_id}.jpg")


if __name__ == "__main__":
    unittest.main()
