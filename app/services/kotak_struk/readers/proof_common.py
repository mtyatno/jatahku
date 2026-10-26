"""Alat bersama pembaca QRIS dan transfer: baca field berlabel, nominal, status, waktu,
referensi, penyamaran nomor, dan penjaga supaya struk belanja tidak terbaca sebagai bukti bayar.

Semua fungsi murni (tanpa I/O). `lines` selalu hasil `clean_lines`; pembacaan field berlabel
memakai `body_lines(lines)`, penanda dan tanggal memakai `lines`."""
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

from app.services.kotak_struk.document import Amounts
from app.services.kotak_struk.merchants import mask_digits
from app.services.kotak_struk.readers.labels import find_value, parse_datetime_id
from app.services.kotak_struk.readers.profiles import GENERIC_LABELS, AppProfile, labels_for
from app.services.receipt_parser import amounts_in

NAME_MAX = 100          # kolom raw_name di peta merchant
NOTE_MAX = 200

# Status
BERHASIL, GAGAL, PENDING, TIDAK_DIKETAHUI = "berhasil", "gagal", "pending", "tidak_diketahui"


# ── Baris ───────────────────────────────────────────────────────────────────

def clean_lines(raw: list[str]) -> list[str]:
    """Spasi dirapatkan, baris kosong dibuang."""
    return [" ".join(line.split()) for line in raw if line and line.strip()]


# Baris yang diawali label "merchant"/"id" tapi bukan nama merchant: jangan terbaca sebagai nilainya.
_NOISE_LINE = re.compile(r"^\s*(?:merchant\s+(?:pan|id)|terminal\s+id)(?=$|[\s:：])", re.IGNORECASE)


def body_lines(lines: list[str]) -> list[str]:
    """`lines` dengan baris derau dikosongkan (indeks tetap, supaya label di atas nilai tidak
    salah berpasangan)."""
    return ["" if _NOISE_LINE.match(line) else line for line in lines]


@lru_cache(maxsize=128)
def _label_start(labels: tuple[str, ...]) -> re.Pattern:
    alternatives = "|".join(r"\s+".join(re.escape(p) for p in label.split()) for label in labels)
    return re.compile(r"^\s*(?:" + alternatives + r")(?=$|[\s:：])", re.IGNORECASE)


def is_label_line(text: str, profile: AppProfile | None = None, fields: tuple[str, ...] | None = None) -> bool:
    """Teks diawali salah satu label yang dikenal (semua field, atau hanya `fields`)."""
    names = fields or tuple({*GENERIC_LABELS, *(profile.labels if profile else ())})
    labels = {label.lower() for name in names for label in labels_for(profile, name)}
    return bool(labels) and bool(_label_start(tuple(sorted(labels, key=len, reverse=True))).match(text))


# ── Nilai berlabel ──────────────────────────────────────────────────────────

def read_text(lines: list[str], labels: list[str], profile: AppProfile | None = None) -> str | None:
    """Nilai di samping/di bawah label pertama yang terbaca. Nilai yang diambil dari baris bawah
    tapi ternyata baris label lain (nilai label ini hilang di OCR) ditolak; nilai sebaris dengan
    label dipercaya apa adanya ("Merchant: BANK SAMPAH" tetap nama). Label dicoba satu per satu
    menurut urutannya, dan baris milik label yang lebih panjang ("Bank Tujuan") tidak dibaca oleh
    label yang lebih pendek ("Bank"): "Tujuan" bukan nama bank."""
    for label in labels:
        longer = sorted({other.lower() for other in labels if len(other) > len(label)}, key=len, reverse=True)
        longer_label = _label_start(tuple(longer)) if longer else None
        scan = [("" if longer_label and longer_label.match(line) else line) for line in lines]
        value = find_value(scan, [label])
        if not value:
            continue
        if value in lines and is_label_line(value, profile):
            continue
        return value
    return None


LONG_DIGITS = 6           # deret angka sepanjang ini bukan bagian dari nama, kota, atau bank
ACCOUNT_MIN_DIGITS = 8    # selaras dengan merchants.MIN_ACCOUNT_DIGITS: rekening "terbaca utuh"

_NUMBER_RUN = re.compile(r"\d(?:[\d \-.]*\d)?")
_ID_PREFIX = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,3}\x00")     # "ID1024358806544", "BCA0123456789": awalan ikut hilang


def split_long_numbers(value: str, *, drop_prefix: bool = True) -> tuple[str, list[str]]:
    """(teks tanpa deret angka panjang, deret angkanya). Deret = angka dengan spasi/strip/titik di antaranya
    ("0123 0100 1234 567"); yang punya >= LONG_DIGITS angka dibuang, termasuk awalan huruf <= 3 yang menempel
    ("ID1024358806544") kecuali `drop_prefix=False` (bank: "BCA0123456789" tetap "BCA"). Nomor rekening, NMID,
    dan nomor telepon tidak boleh bertahan di nama, kota, atau bank."""
    found: list[str] = []

    def take(m: re.Match) -> str:
        if sum(c.isdigit() for c in m.group(0)) < LONG_DIGITS:
            return m.group(0)
        found.append(" ".join(m.group(0).split()))
        return "\x00"

    text = _NUMBER_RUN.sub(take, value)
    text = _ID_PREFIX.sub(" ", text) if drop_prefix else text
    return " ".join(text.replace("\x00", " ").split()).strip(" :-–,."), found


def account_from(numbers: list[str]) -> str | None:
    """Nomor rekening dari deret angka yang ditemukan di nilai lain: yang pertama dengan >= ACCOUNT_MIN_DIGITS angka."""
    return next((n for n in numbers if sum(c.isdigit() for c in n) >= ACCOUNT_MIN_DIGITS), None)


def read_name(lines: list[str], profile: AppProfile | None, field: str, *, numbers: list[str] | None = None) -> str | None:
    """Nama pihak (maksimal NAME_MAX). Deret angka panjang dibuang dari nilainya dan, bila `numbers` diberikan,
    ditambahkan ke sana (bahan rekening cadangan). Tanpa huruf: None."""
    value = read_text(lines, labels_for(profile, field), profile)
    if not value:
        return None
    value, found = split_long_numbers(value.strip(" :-–,"))
    if numbers is not None:
        numbers.extend(found)
    return value[:NAME_MAX] if re.search(r"[A-Za-z]", value) else None


def read_city(lines: list[str], profile: AppProfile | None) -> str | None:
    value = read_text(lines, labels_for(profile, "city"), profile)
    value = split_long_numbers(value)[0] if value else ""
    return value[:60] if re.search(r"[A-Za-z]", value) else None


def read_bank(lines: list[str], profile: AppProfile | None, *, numbers: list[str] | None = None) -> str | None:
    """Kode bank ternormalisasi dari label bank; nomor yang menempel di nilainya dibuang (dan masuk `numbers`)."""
    value = read_text(lines, labels_for(profile, "bank"), profile)
    if not value:
        return None
    value, found = split_long_numbers(value, drop_prefix=False)
    if numbers is not None:
        numbers.extend(found)
    return normalize_bank(value)


def scrub_note(note: str | None, secret_values: list[str]) -> str | None:
    """Catatan tanpa deret angka panjang yang sama dengan rahasia bukti (rekening, referensi, NMID): user bisa
    saja menulis "ke rek 0123..." di berita. Angka panjang lain milik user dibiarkan."""
    if not note:
        return None
    secret_digits = {d for d in (re.sub(r"\D", "", v) for v in secret_values if v) if len(d) >= LONG_DIGITS}

    def take(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        known = len(digits) >= LONG_DIGITS and any(digits in d or d in digits for d in secret_digits)
        return " " if known else m.group(0)

    cleaned = " ".join(_NUMBER_RUN.sub(take, note).split()).strip()
    return cleaned or None


def read_note(lines: list[str], profile: AppProfile | None) -> str | None:
    value = read_text(lines, labels_for(profile, "note"), profile)
    return value.strip()[:NOTE_MAX] if value and value.strip() else None


def read_nmid(lines: list[str], profile: AppProfile | None) -> str | None:
    value = read_text(lines, labels_for(profile, "nmid"), profile)
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return cleaned if re.fullmatch(r"[A-Z0-9]{8,20}", cleaned) else None


_ACCOUNT = re.compile(r"(?<![A-Za-z0-9])[\d*•xX][\d\s*•xX.\-]*\d")
_NOT_DESTINATION = re.compile(r"^(sumber|asal|pengirim|anda|dari)(?![A-Za-z])", re.IGNORECASE)


def read_account(lines: list[str], profile: AppProfile | None) -> str | None:
    """Nomor rekening tujuan seperti tercetak (spasi dirapatkan; yang tersamar tetap tersamar).
    Rekening sumber ("Rekening Sumber ...") tidak dipakai."""
    value = read_text(lines, labels_for(profile, "account"), profile)
    if not value or _NOT_DESTINATION.match(value):
        return None
    m = _ACCOUNT.search(value)
    account = " ".join(m.group(0).split()) if m else None
    return account if account and sum(c.isdigit() for c in account) >= 4 else None


_BANK_NAMES = {
    "BANK RAKYAT INDONESIA": "BRI", "BANK CENTRAL ASIA": "BCA", "BANK NEGARA INDONESIA": "BNI",
    "BANK MANDIRI": "MANDIRI", "BANK SYARIAH INDONESIA": "BSI", "BANK TABUNGAN NEGARA": "BTN",
}


def normalize_bank(value: str | None) -> str | None:
    """Kode bank untuk kunci: huruf besar, tanpa spasi berlebih, tanpa awalan "Bank" ("Bank BCA" -> "BCA";
    "Bank Rakyat Indonesia (BRI)" -> "BRI"). Kunci rekening memakainya apa adanya, jadi harus stabil, dan nomor
    yang menempel ("BCA-0123456789", "BCA 0123456789", "BRI (01230100)") tidak boleh ikut. Tanpa huruf: None."""
    text = " ".join((value or "").upper().split())
    abbreviation = re.search(r"\(([A-Z][A-Z0-9]{1,9})\)", text)             # singkatan harus diawali huruf
    if abbreviation:
        return abbreviation.group(1)
    text = re.split(r"[\s\-–:/.(]*\d{4,}", text)[0]                          # buang nomor rekening yang menempel
    text = re.sub(r"\(.*?\)", " ", text).strip(" -–:.,")
    text = _BANK_NAMES.get(text, text)
    text = text.removeprefix("BANK ").strip()
    return text[:30] if re.search(r"[A-Z]", text) else None


def read_refs(lines: list[str], profile: AppProfile | None) -> list[tuple[str, str]]:
    """[(jenis, nilai ternormalisasi)]; nilai = huruf dan angka saja, huruf besar. Minimal 6 karakter
    dan ada angkanya (selain itu bukan nomor referensi). Nilai kembar dibuang."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label in labels_for(profile, "ref"):
        value = read_text(lines, [label], profile)
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9 \-]*", value or "")
        normalized = re.sub(r"[^A-Za-z0-9]", "", m.group(0)).upper() if m else ""
        if len(normalized) >= 6 and re.search(r"\d", normalized) and normalized not in seen:
            seen.add(normalized)
            out.append(("rrn" if label.lower() == "rrn" else "ref", normalized))
    return out


# ── Penyamaran ──────────────────────────────────────────────────────────────

def mask_ref(value: str) -> str:
    """Nomor referensi tersamar: angka saja -> `…` + 4 digit terakhir; campur huruf -> 4 karakter terakhir."""
    return mask_digits(value) if value.isdigit() else "…" + value[-4:]


def mask_id(value: str) -> str:
    """NMID tersamar seperti di spec: `ID10…6544` (4 karakter awal + 4 digit terakhir)."""
    return (value[:4] if len(value) >= 9 else "") + mask_digits(value)


# ── Nominal ─────────────────────────────────────────────────────────────────

_AMOUNT_ONLY = re.compile(r"[-–+\s]*(?:Rp|IDR)\.?\s*[\d.,]+\s*", re.IGNORECASE)
_ANCHOR = re.compile(r"(?<!\w)(qris|transfer|top[\s-]?up|berhasil|sukses|successful|success|gagal|failed|diproses|pending)(?!\w)",
                     re.IGNORECASE)


_SIGN = re.compile(r"(?<![\w/])[-–−(]\s*(?=(?:(?:Rp|IDR)\.?\s*)?\d)", re.IGNORECASE)   # "-Rp5.000", "(Rp5.000)": tanda bukan bagian tanggal
# "Total Biaya", "Total Diskon", ...: jumlah komponen, bukan total bayar.
_TOTAL_OF_COMPONENT = re.compile(r"^\s*total\s+(?:biaya|admin|fee|layanan|diskon|potongan|promo|voucher|pajak|ppn|tax|discount)(?![A-Za-z])", re.IGNORECASE)
_COMPONENT_TOTAL_LABELS = ["total biaya", "total admin", "total fee"]


def _first_value(lines: list[str], label: str, profile: AppProfile | None, exclude: re.Pattern | None = None) -> int | None:
    """Nominal di samping/di bawah baris pertama yang diawali `label`. Nilai di baris bawah hanya dipakai bila
    baris itu bukan label lain ("Biaya Admin" tanpa nilai tidak boleh meminjam "Total Rp150.000")."""
    start = _label_start((label.lower(),))
    for i, line in enumerate(lines):
        m = start.match(line)
        if not m or (exclude and exclude.match(line)):
            continue
        rest = line[m.end():].lstrip(" :：")
        if not rest and i + 1 < len(lines) and not is_label_line(lines[i + 1], profile):
            rest = lines[i + 1]
        amounts = amounts_in(_SIGN.sub(" ", rest))
        if amounts:
            return amounts[0]
    return None


def _first_amount(lines: list[str], labels: list[str], profile: AppProfile | None, exclude: re.Pattern | None = None) -> int | None:
    """Sinonim lebih awal diutamakan (seperti `labels.find_amount`)."""
    for label in labels:
        value = _first_value(lines, label, profile, exclude)
        if value is not None:
            return value
    return None


def _sum_amounts(lines: list[str], labels: list[str], profile: AppProfile | None) -> int:
    """Jumlah nominal semua baris berlabel (biaya, diskon, pajak bisa lebih dari satu baris). Satu baris dihitung
    sekali walau beberapa sinonim cocok ("Biaya Admin" cocok "biaya admin" dan "biaya"). Yang < Rp100 dianggap 0."""
    if not labels:
        return 0
    start = _label_start(tuple(sorted({label.lower() for label in labels}, key=len, reverse=True)))
    total = 0
    for i, line in enumerate(lines):
        m = start.match(line)
        if not m:
            continue
        rest = line[m.end():].lstrip(" :：")
        if not rest and i + 1 < len(lines) and not is_label_line(lines[i + 1], profile):
            rest = lines[i + 1]
        amounts = amounts_in(_SIGN.sub(" ", rest))
        total += amounts[0] if amounts else 0
    return total


def read_amounts(lines: list[str], profile: AppProfile | None) -> tuple[Amounts, str | None]:
    """(nominal, tingkat keyakinan total). Label "total*" -> total; label lain ("nominal", "jumlah", ...)
    -> subtotal. Biaya, diskon, dan pajak dijumlahkan dari semua barisnya (hilang atau < Rp100 = 0); "Total Biaya"
    dipakai sebagai biaya hanya bila tidak ada baris biaya. Tanpa total: subtotal + biaya + pajak - diskon.
    Tanpa label sama sekali: angka `Rp` yang berdiri sendiri, yang pertama setelah baris QRIS/status
    (keyakinan `sedang`), selain itu yang pertama (`rendah`)."""
    labels = labels_for(profile, "amount")
    total_labels = [label for label in labels if label.lower().startswith("total")]
    subtotal = _first_amount(lines, [label for label in labels if label not in total_labels], profile)
    total = _first_amount(lines, total_labels, profile, exclude=_TOTAL_OF_COMPONENT)
    fee = _sum_amounts(lines, labels_for(profile, "fee"), profile) \
        or _first_amount(lines, _COMPONENT_TOTAL_LABELS, profile) or 0
    discount = _sum_amounts(lines, labels_for(profile, "discount"), profile)
    tax = _sum_amounts(lines, labels_for(profile, "tax"), profile)
    if subtotal is None and total is None:
        found = _bare_amount(lines)
        amounts = Amounts(fee=fee, tax=tax, discount=discount, total=found[0] if found else None)
        return amounts, found[1] if found else None
    if total is None:
        total = max(subtotal + fee + tax - discount, 0)
    return Amounts(subtotal=subtotal, fee=fee, tax=tax, discount=discount, total=total), "tinggi"


def _bare_amount(lines: list[str]) -> tuple[int, str] | None:
    anchor = next((i for i, line in enumerate(lines) if _ANCHOR.search(line)), -1)
    candidates = [(i, amounts_in(line)) for i, line in enumerate(lines) if _AMOUNT_ONLY.fullmatch(line)]
    candidates = [(i, amounts) for i, amounts in candidates if amounts]
    after = [c for c in candidates if c[0] > anchor] if anchor >= 0 else []
    if after:
        return after[0][1][0], "sedang"
    return (candidates[0][1][0], "rendah") if candidates else None


def has_amount(lines: list[str], profile: AppProfile | None = None) -> bool:
    return read_amounts(lines, profile)[0].total is not None


# ── Waktu ───────────────────────────────────────────────────────────────────

_TIME_ONLY = re.compile(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(?:WIB|WITA|WIT)?", re.IGNORECASE)
# Baris-baris ini memuat nilai bebas (catatan, nama, nomor) yang bisa kebetulan memuat tanggal.
_VALUE_FIELDS = ("note", "ref", "merchant", "sender", "account", "bank", "nmid")


def read_paid_at(lines: list[str], profile: AppProfile | None = None) -> tuple[datetime | None, str | None]:
    """(waktu bayar, keyakinan): `tinggi` bila ada jam, `sedang` bila hanya tanggal (jam di baris
    sesudahnya dipakai bila berdiri sendiri)."""
    for i, line in enumerate(lines):
        if is_label_line(line, profile, _VALUE_FIELDS):
            continue
        paid = parse_datetime_id(line)
        if not paid:
            continue
        if (paid.hour, paid.minute, paid.second) == (0, 0, 0) and i + 1 < len(lines):
            m = _TIME_ONLY.fullmatch(lines[i + 1])
            if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 and int(m.group(3) or 0) < 60:
                return paid.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3) or 0)), "tinggi"
        midnight = (paid.hour, paid.minute, paid.second) == (0, 0, 0)
        return paid, "sedang" if midnight else "tinggi"
    return None, None


# ── Status ──────────────────────────────────────────────────────────────────

_GAGAL = re.compile(r"(?<!\w)(gagal|failed|tidak\s+berhasil)(?!\w)", re.IGNORECASE)
_PENDING = re.compile(r"(?<!\w)(?<!berhasil )(diproses|pending|processing)(?!\w)", re.IGNORECASE)   # "berhasil diproses" = sukses
_BERHASIL = re.compile(r"(?<!\w)(berhasil|sukses|successful|success)(?!\w)", re.IGNORECASE)
HEADER_LINES = 4          # status biasanya ada di judul bukti
HEADER_WORDS = 8          # kalimat lebih panjang dari ini = catatan kaki, bukan status
BODY_WORDS = 5            # di luar judul, hanya baris yang lebih pendek lagi


def _classify(text: str) -> str | None:
    if _GAGAL.search(text):
        return GAGAL
    if _PENDING.search(text):
        return PENDING
    return BERHASIL if _BERHASIL.search(text) else None


# Kalimat peringatan/bantuan di kaki bukti ("Jika gagal hubungi 14017", "Transaksi gagal? Hubungi kami") memuat
# kata status tapi bukan status transaksi.
_NOT_STATUS = re.compile(r"\?|(?<!\w)(?:jika|bila|apabila|kalau|if|hubungi|silakan|silahkan|contact|please)(?!\w)", re.IGNORECASE)


def _status_lines(texts: list[str], max_words: int) -> list[str]:
    return [t for t in texts if len(t.split()) <= max_words and not _NOT_STATUS.search(t)]


def _strongest(texts: list[str]) -> str | None:
    found = {c for c in map(_classify, texts) if c}
    return next((s for s in (GAGAL, PENDING, BERHASIL) if s in found), None)


def _first(texts: list[str]) -> str | None:
    return next((c for c in map(_classify, texts) if c), None)


def read_status(lines: list[str], profile: AppProfile | None = None) -> str:
    """Status dari label "Status" dan judul (4 baris pertama): kata gagal mengalahkan pending mengalahkan berhasil.
    Lalu baris pendek di mana saja: yang pertama menurut urutan dokumen (bukan yang terburuk, supaya baris
    "Gagal" lain di bawah status "Transaksi Berhasil" tidak membalikkannya). Kalimat panjang dan kalimat
    bersyarat/tanya/ajakan ("Jika gagal hubungi ...", "Gagal? Hubungi kami") tidak dihitung. Tanpa kata
    status: `tidak_diketahui`."""
    labelled = read_text(lines, labels_for(profile, "status"), profile)
    status = (_classify(labelled) if labelled else None) \
        or _strongest(_status_lines(lines[:HEADER_LINES], HEADER_WORDS)) \
        or _first(_status_lines(lines, BODY_WORDS))
    return status or TIDAK_DIKETAHUI


# ── Penjaga struk belanja ───────────────────────────────────────────────────

_CASH_WORD = re.compile(r"(?<![A-Za-z])(?:KEMBALI|KEMBALIAN|TUNAI)(?![A-Za-z])", re.IGNORECASE)
_TOTAL_WORD = re.compile(r"(?<![A-Za-z])TOTAL(?![A-Za-z])", re.IGNORECASE)
_SUBTOTAL = re.compile(r"SUB\s*-?\s*TOTAL", re.IGNORECASE)
# Baris cara bayar sesudah total: "QRIS 40.000", "Pembayaran QRIS Rp 40.000", "Non Tunai (QRIS) 45.400", "DEBIT BCA 45.400".
_PAYMENT_LINE = re.compile(
    r"^\W*(?:(?:pembayaran|bayar|payment|non\s+tunai)\s+)?\(?(?:qris|debit|kredit|credit|e-?money|flazz|brizzi|tapcash)\)?"
    r"[^\d]{0,20}(?:Rp\.?\s*)?\d[\d.,]*\s*$", re.IGNORECASE)
_QTY = re.compile(r"\d{1,3}(?:[.,]\d{1,2})?\s*[xX]?")
MIN_STORE_ITEMS = 3        # barang tanpa kuantitas sebelum total
MIN_QTY_ITEMS = 2          # baris "NAMA QTY HARGA" (bukti bayar tidak pernah memakai bentuk ini)


def _is_item_line(line: str) -> bool:
    """Baris barang struk: nama (>= 3 huruf, "Rp" tidak dihitung) lalu nominal di ujung. Baris berlabel
    bukti bayar (Nominal, Biaya, Rekening, ...) dan baris tanggal bukan barang."""
    if is_label_line(line) or parse_datetime_id(line):
        return False
    tokens = line.split()
    if len(tokens) < 2 or not amounts_in(tokens[-1]):
        return False
    name = re.sub(r"\bRP\b", " ", " ".join(tokens[:-1]).upper())
    return sum(c.isalpha() for c in name) >= 3


def _is_qty_item_line(line: str) -> bool:
    """Barang dengan kuantitas di antara nama dan harga: "KOPI SUSU 1 25.000", "ROTI 2 x 15.000"."""
    tokens = line.split()
    if not _is_item_line(line) or len(tokens) < 3:
        return False
    qty = " ".join(tokens[-3:-1]) if tokens[-2].lower() == "x" and len(tokens) >= 4 else tokens[-2]
    return bool(_QTY.fullmatch(qty))


def _is_cash_line(line: str) -> bool:
    """Baris tunai/kembalian: ada kata TUNAI/KEMBALI dan ujung baris berangka ("TUNAI 50.000", "KEMBALI : 0",
    "Non Tunai (QRIS) 45.400"). Baris catatan ("Berita titip tunai 2 bulan") dan tombol ("Kembali ke Beranda") bukan."""
    tokens = line.split()
    return bool(tokens and _CASH_WORD.search(line) and re.search(r"\d", tokens[-1]) and not is_label_line(line, fields=("note",)))


def looks_like_store_receipt(lines: list[str]) -> bool:
    """Pola struk belanja; bukti QRIS dan transfer tidak pernah memakainya, jadi pembaca bukti menolak
    dokumen seperti ini (skor 0). Salah satu dari:
    - baris tunai/kembalian berangka;
    - >= 3 baris barang sebelum baris total;
    - >= 2 baris "NAMA QTY HARGA" di mana saja;
    - >= 1 baris barang sebelum baris total dan sesudahnya baris cara bayar berangka ("QRIS 40.000").
    Struk toko kecil (1-2 barang) yang dibayar QRIS dan mencetak NMID/Terminal ID masuk pola ini."""
    if any(_is_cash_line(line) for line in lines):
        return True
    total_at = next((i for i, line in enumerate(lines) if _TOTAL_WORD.search(line) and not _SUBTOTAL.search(line)), None)
    before = lines if total_at is None else lines[:total_at]
    items = sum(_is_item_line(line) for line in before)
    if items >= MIN_STORE_ITEMS or sum(_is_qty_item_line(line) for line in lines) >= MIN_QTY_ITEMS:
        return True
    return bool(total_at is not None and items >= 1 and any(_PAYMENT_LINE.match(line) for line in lines[total_at + 1:]))
