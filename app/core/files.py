"""Safe image upload helpers.

Never trust the client-supplied filename or Content-Type for the stored
extension — both are attacker-controlled and could place an executable
extension into a web-served directory. Instead, sniff the magic bytes and only
accept a known image type, deriving the extension ourselves.
"""

# (extension, magic-byte predicate) for the image types we accept.
def _detect(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def safe_image_ext(data: bytes) -> str:
    """Return a safe extension for image bytes, or raise ValueError if not a
    recognised image type."""
    ext = _detect(data)
    if ext is None:
        raise ValueError("File bukan gambar yang valid (jpg/png/webp/gif).")
    return ext
