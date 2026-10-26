"""Kunci pihak penerima (merchant) dan keterangan transaksi untuk Kotak Struk.

Hampir semuanya fungsi murni; fungsi basis data (peta merchant per rumah tangga)
dimulai dari `upsert_household_merchant`.
"""
import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.models import HouseholdMerchant, ReceiptScan
from app.services.kotak_struk.document import Counterparty, DokumenBayar

log = logging.getLogger(__name__)

KEY_MAX = 80            # panjang kolom counterparty_key
RAW_NAME_MAX = 100      # panjang kolom household_merchants.raw_name
CITY_MAX = 60           # panjang kolom household_merchants.city
NICKNAME_MAX = 60       # panjang kolom household_merchants.display_name
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


async def _find_merchant(db: AsyncSession, household_id: uuid.UUID, key: str) -> HouseholdMerchant | None:
    return (await db.execute(
        select(HouseholdMerchant).where(
            HouseholdMerchant.household_id == household_id, HouseholdMerchant.counterparty_key == key)
    )).scalars().first()


def _refresh_merchant(row: HouseholdMerchant, raw_name: str | None, city: str | None, now: datetime) -> None:
    # Nama dan kota yang tidak terbaca di bukti ini tidak menghapus yang sudah diketahui.
    # `display_name` (nama panggilan dari user) tidak pernah disentuh.
    if raw_name:
        row.raw_name = raw_name[:RAW_NAME_MAX]
    if city:
        row.city = city[:CITY_MAX]
    row.last_seen_at = now


async def upsert_household_merchant(db: AsyncSession, household_id: uuid.UUID, key: str, raw_name: str | None,
                                    city: str | None, *, now: datetime) -> HouseholdMerchant:
    """Catat pihak penerima di peta merchant rumah tangga: baris baru, atau perbarui `raw_name`, `city`,
    dan `last_seen_at` baris yang ada (unik per rumah tangga + kunci). Tidak meng-commit; pemanggil
    yang commit. Balapan dua pembuat baris yang sama ditangani lewat SAVEPOINT, jadi sesi pemanggil
    tetap bisa dipakai."""
    row = await _find_merchant(db, household_id, key)
    if row is None:
        row = HouseholdMerchant(household_id=household_id, counterparty_key=key,
                                raw_name=(raw_name or "")[:RAW_NAME_MAX], city=city[:CITY_MAX] if city else None,
                                last_seen_at=now, created_at=now)
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
            return row
        except IntegrityError:
            row = await _find_merchant(db, household_id, key)
            if row is None:
                raise
    _refresh_merchant(row, raw_name, city, now)
    await db.flush()
    return row


async def merchant_for_item(db: AsyncSession, item: ReceiptScan) -> HouseholdMerchant | None:
    """Baris peta merchant milik item (kunci pihak penerimanya di rumah tangga item), atau None
    bila item tanpa rumah tangga/kunci atau barisnya belum ada."""
    if item.household_id is None or not item.counterparty_key:
        return None
    return await _find_merchant(db, item.household_id, item.counterparty_key)


def clean_nickname(name: str | None) -> str | None:
    """Nama panggilan dari input user, aman ditampilkan ke anggota lain: tag `<...>` dan karakter selain huruf,
    angka, spasi, `&'.-` dibuang (seperti `receipt_scan.clean_merchant_name`), spasi dirapatkan, dipotong
    NICKNAME_MAX. Tidak ada yang tersisa -> None."""
    text = re.sub(r"<[^>]*>", "", name or "")
    text = " ".join(re.sub(r"[^A-Za-z0-9&'.\- ]", "", text).split())[:NICKNAME_MAX].strip()
    return text or None


async def set_display_name(db: AsyncSession, merchant_id: uuid.UUID, household_id: uuid.UUID,
                           name: str) -> HouseholdMerchant | None:
    """Pasang nama panggilan merchant (berlaku untuk seluruh rumah tangga). Nama yang setelah dibersihkan
    kosong menghapus nama panggilan (baris dikembalikan dengan `display_name` None). Merchant yang tidak ada
    atau milik rumah tangga lain -> None. Tidak meng-commit; pemanggil yang commit."""
    row = await db.get(HouseholdMerchant, merchant_id)
    if row is None or row.household_id != household_id:
        return None
    row.display_name = clean_nickname(name)
    await db.flush()
    return row
