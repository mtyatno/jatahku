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
from app.services.kotak_struk.readers.labels import find_amount, find_value, parse_datetime_id
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


def read_name(lines: list[str], profile: AppProfile | None, field: str) -> str | None:
    value = read_text(lines, labels_for(profile, field), profile)
    if not value:
        return None
    value = value.strip(" :-–,")
    return value[:NAME_MAX] if re.search(r"[A-Za-z]", value) else None


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
    "Bank Rakyat Indonesia (BRI)" -> "BRI"). Kunci rekening memakainya apa adanya, jadi harus stabil."""
    text = " ".join((value or "").upper().split())
    abbreviation = re.search(r"\(([A-Z0-9]{2,10})\)", text)
    if abbreviation:
        return abbreviation.group(1)
    text = re.split(r"\s+[-–]?\s*\d{4,}", text)[0]          # buang nomor rekening yang menempel
    text = re.sub(r"\(.*?\)", " ", text).strip(" -–:.,")
    text = _BANK_NAMES.get(text, text)
    text = text.removeprefix("BANK ").strip()
    return text[:30] or None


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


def read_amounts(lines: list[str], profile: AppProfile | None) -> tuple[Amounts, str | None]:
    """(nominal, tingkat keyakinan total). Label "total*" -> total; label lain ("nominal", "jumlah", ...)
    -> subtotal; tanpa label total: subtotal + biaya. Biaya hilang atau < Rp100 dianggap 0.
    Tanpa label sama sekali: angka `Rp` yang berdiri sendiri, yang pertama setelah baris QRIS/status
    (keyakinan `sedang`), selain itu yang pertama (`rendah`)."""
    labels = labels_for(profile, "amount")
    total_labels = [label for label in labels if label.lower().startswith("total")]
    subtotal = find_amount(lines, [label for label in labels if label not in total_labels])
    total = find_amount(lines, total_labels)
    fee = find_amount(lines, labels_for(profile, "fee")) or 0
    if subtotal is None and total is None:
        found = _bare_amount(lines)
        return Amounts(fee=fee, total=found[0] if found else None), found[1] if found else None
    if total is None:
        total = subtotal + fee
    return Amounts(subtotal=subtotal, fee=fee, total=total), "tinggi"


def _bare_amount(lines: list[str]) -> tuple[int, str] | None:
    anchor = next((i for i, line in enumerate(lines) if _ANCHOR.search(line)), -1)
    candidates = [(i, amounts_in(line)) for i, line in enumerate(lines) if _AMOUNT_ONLY.fullmatch(line)]
    candidates = [(i, amounts) for i, amounts in candidates if amounts]
    after = [c for c in candidates if c[0] > anchor] if anchor >= 0 else []
    if after:
        return after[0][1][0], "sedang"
    return (candidates[0][1][0], "rendah") if candidates else None


def has_amount(lines: list[str], profile: AppProfile | None = None) -> bool:
    return find_amount(lines, labels_for(profile, "amount")) is not None or _bare_amount(lines) is not None


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


def _strongest(texts: list[str]) -> str | None:
    found = {c for c in map(_classify, texts) if c}
    return next((s for s in (GAGAL, PENDING, BERHASIL) if s in found), None)


def read_status(lines: list[str], profile: AppProfile | None = None) -> str:
    """Status dari label "Status", lalu judul (4 baris pertama), lalu baris pendek di mana saja.
    Kalimat panjang ("Jika transaksi gagal atau pending, hubungi ...") tidak dihitung. Tanpa kata
    status: `tidak_diketahui`."""
    labelled = read_text(lines, labels_for(profile, "status"), profile)
    status = (_classify(labelled) if labelled else None) \
        or _strongest([line for line in lines[:HEADER_LINES] if len(line.split()) <= HEADER_WORDS]) \
        or _strongest([line for line in lines if len(line.split()) <= BODY_WORDS])
    return status or TIDAK_DIKETAHUI


# ── Penjaga struk belanja ───────────────────────────────────────────────────

_CASH_WORD = re.compile(r"(?<![A-Za-z])(?:KEMBALI|KEMBALIAN|TUNAI)(?![A-Za-z])", re.IGNORECASE)
_TOTAL_WORD = re.compile(r"(?<![A-Za-z])TOTAL(?![A-Za-z])", re.IGNORECASE)
_SUBTOTAL = re.compile(r"SUB\s*-?\s*TOTAL", re.IGNORECASE)
MIN_STORE_ITEMS = 3


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


def looks_like_store_receipt(lines: list[str]) -> bool:
    """Pola struk belanja: baris KEMBALI/TUNAI berangka ("Non Tunai (QRIS) 45.400" juga; "Kembali ke
    beranda" tidak), atau >= 3 baris barang sebelum baris total. Bukti QRIS dan transfer tidak pernah
    memakai pola ini, jadi pembaca bukti menolak dokumen seperti ini (skor 0)."""
    if any(_CASH_WORD.search(line) and re.search(r"\d", line) for line in lines):
        return True
    items = 0
    for line in lines:
        if _TOTAL_WORD.search(line) and not _SUBTOTAL.search(line):
            break
        items += _is_item_line(line)
    return items >= MIN_STORE_ITEMS
