"""Kunci pihak penerima (merchant) dan keterangan transaksi untuk Kotak Struk.

Hanya fungsi murni di modul ini; fungsi basis data (peta merchant per rumah
tangga) ditambahkan di task berikutnya.
"""
import hashlib
import hmac
import logging
import re

from app.core.config import get_settings
from app.services.kotak_struk.document import Counterparty, DokumenBayar

log = logging.getLogger(__name__)

KEY_MAX = 80            # panjang kolom counterparty_key
DESCRIPTION_MAX = 500   # batas keterangan transaksi
MIN_ACCOUNT_DIGITS = 8  # nomor rekening dianggap terbaca utuh bila punya >= ini

# Keterangan cadangan bila bukti tidak punya nama pihak dan user tidak menulis catatan.
# Terlihat user sebagai deskripsi transaksi, tapi bukan catatan user: learnable_text membuangnya.
FALLBACK_QRIS = "Pembayaran QRIS"
FALLBACK_TRANSFER = "Transfer"
FALLBACK_OTHER = "Bukti bayar"
_FALLBACKS = {FALLBACK_QRIS.casefold(), FALLBACK_TRANSFER.casefold(), FALLBACK_OTHER.casefold()}

ACRONYMS = {"PT", "CV", "UD", "TB", "SPBU", "BRI", "BCA", "BNI", "BSI", "BTN", "QRIS", "RS", "RSUD"}

_warned_no_key = False


def normalize_name(s: str | None) -> str:
    """Huruf kecil, tanda baca dibuang (bukan diganti spasi: "P.T." dan "PT" sama),
    spasi dirapatkan."""
    if not s:
        return ""
    s = re.sub(r"[^\w\s]|_", "", s.lower())
    return " ".join(s.split())


def hmac_hex(value: str) -> str:
    """HMAC-SHA256 hex dengan `KOTAK_HMAC_KEY`. Bila kunci belum diisi di .env,
    kunci diturunkan dari JWT_SECRET (peringatan dicatat sekali); tidak pernah
    memakai kunci kosong."""
    global _warned_no_key
    settings = get_settings()
    if settings.KOTAK_HMAC_KEY:
        key = settings.KOTAK_HMAC_KEY.encode()
    else:
        if not _warned_no_key:
            _warned_no_key = True
            log.warning("KOTAK_HMAC_KEY belum diisi; memakai kunci turunan JWT_SECRET. "
                        "Isi KOTAK_HMAC_KEY di .env agar kunci HMAC tidak ikut berubah bila JWT_SECRET diganti.")
        key = hashlib.sha256(("kotak:" + settings.JWT_SECRET).encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def counterparty_key(cp: Counterparty, *, nmid: str | None = None,
                     account_number: str | None = None, bank_code: str | None = None) -> str | None:
    """Kunci pihak penerima: nmid > rekening (HMAC) > nama|kota-atau-bank > None."""
    nmid = (nmid or "").strip()
    if nmid:
        return f"nmid:{nmid.upper()}"[:KEY_MAX]
    # Rekening hanya dipakai bila terbaca utuh: kelompok digit dengan paling banyak satu
    # pemisah (spasi/strip/titik) di antaranya. Nomor tersamar ("****4567",
    # "0123****4567", "0123 .... 4567", "0123-----4567") jatuh ke nama.
    acct = " ".join((account_number or "").split())
    if re.fullmatch(r"[0-9]+(?:[ .\-][0-9]+)*", acct):
        digits = re.sub(r"\D", "", acct)
        if len(digits) >= MIN_ACCOUNT_DIGITS:
            return f"rek:{hmac_hex((bank_code or '') + ':' + digits)}"[:KEY_MAX]
    name = normalize_name(cp.name)
    if not name:
        return None
    return f"nama:{name}|{normalize_name(cp.city) or normalize_name(cp.bank)}"[:KEY_MAX]


def display_name(raw: str | None) -> str:
    """Huruf besar semua -> kapital awal per kata, singkatan di ACRONYMS tetap
    besar, angka dan tanda baca apa adanya. Teks campuran dibiarkan."""
    s = " ".join((raw or "").split())
    if not s.isupper():
        return s
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0) if m.group(0) in ACRONYMS else m.group(0).capitalize(), s)


def compose_description(doc: DokumenBayar, *, display: str | None, note: str | None) -> str:
    """Keterangan transaksi dari bukti bayar.

    Tanpa catatan: QRIS `Siti Aminah (QRIS)`, transfer `Transfer ke Budi Santoso`,
    jenis lain `{nama}`. Dengan catatan: `bakso 2, es teh (Siti Aminah)`.
    Tanpa nama: catatan saja, atau FALLBACK_QRIS / FALLBACK_TRANSFER / FALLBACK_OTHER.
    """
    name = (display or "").strip()
    note = (note or "").strip()
    if note:
        if not name:
            return note[:DESCRIPTION_MAX]
        suffix = f" ({name})"
        return (note[:max(0, DESCRIPTION_MAX - len(suffix))].rstrip() + suffix)[:DESCRIPTION_MAX]
    if doc.doc_type == "qris":
        text = f"{name} (QRIS)" if name else FALLBACK_QRIS
    elif doc.doc_type == "transfer":
        text = f"Transfer ke {name}" if name else FALLBACK_TRANSFER
    else:
        text = name or FALLBACK_OTHER
    return text[:DESCRIPTION_MAX]


def learnable_text(description: str, names: list[str]) -> str:
    """Bagian keterangan yang boleh dipelajari sebagai kata kunci amplop: nama
    merchant (nama asli, nama panggilan), "(QRIS)", "transfer ke", dan tanda
    kurung kosong dibuang. Bila yang tersisa persis salah satu keterangan cadangan
    (bukti tanpa nama dan tanpa catatan), hasilnya kosong. Yang tersisa hanya catatan
    user; kata user sendiri ("transfer arisan") tetap utuh."""
    text = description or ""
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        pattern = r"\s+".join(re.escape(part) for part in name.split())
        text = re.sub(rf"(?<!\w){pattern}(?!\w)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*qris\s*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\btransfer\s+ke\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", " ", text)
    text = " ".join(text.split())
    return "" if text.casefold() in _FALLBACKS else text


def mask_digits(s: str, keep: int = 4) -> str:
    """`…` + `keep` digit terakhir dari deret digit (spasi/strip diabaikan)."""
    digits = re.sub(r"\D", "", s or "")
    if not digits:
        return ""
    return "…" + (digits[-keep:] if keep > 0 else "")
