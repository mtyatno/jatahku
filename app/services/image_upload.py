"""Unggahan gambar yang disimpan di `public_html/uploads`: foto profil dan bukti transfer.

Folder itu disajikan nginx di jatahku.com, origin yang sama dengan app (token login ada di localStorage), dengan
tipe dari ekstensi berkasnya. Satu `.html`/`.svg` di sana berarti XSS tersimpan: skripnya jalan di origin app dan
bisa mencuri token siapa pun yang membuka tautannya. Karena itu, untuk semua rute yang menulis ke folder ini:

- jenis file ditentukan dari ISI (byte awal), tidak pernah dari nama file atau content-type kiriman klien;
- ekstensi di disk hanya salah satu dari `IMAGE_EXTS` (hasil `sniff_image_ext`), jadi bertipe gambar di nginx;
- nama file dibuat server (`name_stem` dari id user/order), tidak pernah dari klien.
"""
import os
import re

from fastapi import HTTPException, UploadFile

UPLOAD_DIR = "/home/jatahku/web/jatahku.com/public_html/uploads"
PROFILE_PIC_MAX_BYTES = 2_000_000
PAYMENT_PROOF_MAX_BYTES = 8 * 1024 * 1024

IMAGE_EXTS = frozenset({"png", "jpg", "gif", "webp"})
_STEM_RE = re.compile(r"[A-Za-z0-9_-]+")


def sniff_image_ext(data: bytes) -> str | None:
    """Ekstensi gambar (`png`, `jpg`, `gif`, `webp`) menurut byte awal `data`; None bila bukan salah satunya
    (HTML, SVG, PDF, HEIC, kosong, dst.)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


async def read_image_upload(file: UploadFile, max_bytes: int) -> tuple[bytes, str]:
    """Baca unggahan (paling banyak `max_bytes`) dan tentukan jenis gambarnya dari isinya: `(data, ext)`.
    400 bila lebih besar dari `max_bytes` atau bukan JPG/PNG/WEBP/GIF. Nama file dan content-type klien tidak dipakai."""
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(400, f"Ukuran gambar maksimal {round(max_bytes / 1_000_000)} MB")
    ext = sniff_image_ext(data)
    if ext is None:
        raise HTTPException(400, "File harus gambar JPG, PNG, WEBP, atau GIF")
    return data, ext


def save_upload(name_stem: str, ext: str, data: bytes) -> str:
    """Tulis `data` ke `{UPLOAD_DIR}/{name_stem}.{ext}` dan kembalikan path publiknya `/uploads/{name_stem}.{ext}`.

    `name_stem` selalu dibuat server (`str(user.id)`, `f"proof_{order_id}"`) dan `ext` datang dari `sniff_image_ext`;
    keduanya tetap diperiksa di sini sebagai lapis kedua: ValueError bila stem bukan `[A-Za-z0-9_-]+` (tidak bisa
    keluar dari folder) atau `ext` bukan ekstensi gambar. Pemeriksaan dilakukan sebelum ada yang ditulis."""
    if not isinstance(name_stem, str) or not _STEM_RE.fullmatch(name_stem):
        raise ValueError(f"name_stem tidak valid: {name_stem!r}")
    if ext not in IMAGE_EXTS:
        raise ValueError(f"ekstensi bukan gambar: {ext!r}")
    fname = f"{name_stem}.{ext}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        f.write(data)
    return f"/uploads/{fname}"
