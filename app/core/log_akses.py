"""Access log uvicorn tanpa rahasia: nilai parameter query sensitif ditulis `***`.

Uvicorn mencatat path beserta query setiap permintaan ke logger `uvicorn.access` (journald di produksi). Tautan di
email dibuka lewat API host dengan token di query (`/auth/verifikasi-email?token=`, `/laporan/berhenti-email?token=`;
token berhenti berlangganan tidak kedaluwarsa), jadi tanpa filter ini siapa pun yang bisa membaca log bisa memakainya.

Yang disamarkan:
- nilai parameter bernama `token` atau `code` (`PARAM_RAHASIA`): tautan email, `/auth/tg-login`, kode undangan
  `/household/join`, kode OAuth `/auth/cms-oauth/callback`;
- nilai parameter apa pun yang memuat alamat email (`@` atau `%40`), mis. `GET /admin/users?search=`.
Path, nama parameter, urutan, dan parameter lain tidak berubah. Rahasia baru lewat query: tambahkan namanya ke
`PARAM_RAHASIA` (lebih baik lagi: kirim lewat badan atau header, bukan query).

Filter dipasang `pasang()` saat `app.main` dimuat. Log akses nginx di depan API tidak lewat sini (lihat AGENTS.md).
"""
import logging
from urllib.parse import unquote_plus

LOGGER_AKSES = "uvicorn.access"
PARAM_RAHASIA = frozenset({"token", "code"})
SAMARAN = "***"


def _memuat_alamat(nilai: str) -> bool:
    return "@" in nilai or "%40" in nilai


def samarkan_query(path_dan_query: str) -> str:
    """`/path?a=1&token=abc` → `/path?a=1&token=***`. Tanpa query atau tanpa nilai sensitif: teks yang sama."""
    path, tanda, query = path_dan_query.partition("?")
    if not tanda or not query:
        return path_dan_query
    bagian = query.split("&")
    berubah = False
    for i, potong in enumerate(bagian):
        nama, sama, nilai = potong.partition("=")
        if not sama or not nilai:
            continue
        if unquote_plus(nama).strip().lower() in PARAM_RAHASIA or _memuat_alamat(nilai):
            bagian[i] = f"{nama}={SAMARAN}"
            berubah = True
    return f"{path}?{'&'.join(bagian)}" if berubah else path_dan_query


class SamarkanQueryRahasia(logging.Filter):
    """Filter logger `uvicorn.access`. Argumen rekaman uvicorn: `(client_addr, method, full_path, http_version,
    status_code)`; hanya `full_path` (indeks 2) yang diganti. Tidak pernah membuang baris log: selalu True. Bila
    penyamaran sendiri galat, query dibuang seluruhnya (gagal-tertutup)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            try:
                tersamar = samarkan_query(args[2])
            except Exception:
                tersamar = f"{args[2].partition('?')[0]}?{SAMARAN}"
            if tersamar != args[2]:
                record.args = args[:2] + (tersamar,) + args[3:]
        return True


def pasang() -> None:
    """Pasang filter di logger `uvicorn.access`; aman dipanggil berulang (tidak menggandakan)."""
    logger = logging.getLogger(LOGGER_AKSES)
    if not any(isinstance(f, SamarkanQueryRahasia) for f in logger.filters):
        logger.addFilter(SamarkanQueryRahasia())
