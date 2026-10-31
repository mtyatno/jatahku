"""Alat baca pasangan label-nilai untuk bukti bayar berbasis teks (QRIS, transfer):
cari nilai di samping/di bawah label, nominal, tanggal-jam Indonesia/Inggris, dan penanda."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.receipt_parser import amounts_in

try:
    WIB = ZoneInfo("Asia/Jakarta")
except ZoneInfoNotFoundError:  # tzdata tidak terpasang; WIB tidak punya DST
    WIB = timezone(timedelta(hours=7), "WIB")


# ── Label dan nilai ─────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _label_re(label: str) -> re.Pattern:
    """Label di awal baris, diikuti akhir baris, spasi, atau titik dua; sisanya = nilai."""
    parts = [re.escape(p) for p in label.split()]
    return re.compile(r"^\s*" + r"\s+".join(parts) + r"(?=$|[\s:：])\s*[:：]?\s*(.*?)\s*$", re.IGNORECASE)


def find_value(lines: list[str], synonyms: list[str]) -> str | None:
    """Nilai di sebelah label. Sinonim lebih awal diutamakan, lalu baris lebih atas.
    Sisa baris sesudah label adalah nilainya; bila kosong, baris berikutnya. Bila baris
    memuat beberapa sinonim ("jumlah" dan "jumlah pembayaran"), yang terpanjang dipakai."""
    labels = [s.strip() for s in synonyms if s and s.strip()]
    for label in labels:
        rx = _label_re(label)
        for i, line in enumerate(lines):
            if not rx.match(line):
                continue
            rest = _rest_after_longest_label(line, labels)
            if not rest and i + 1 < len(lines):
                rest = lines[i + 1].strip()
            if rest:
                return rest
    return None


def _rest_after_longest_label(line: str, labels: list[str]) -> str:
    best = max((s for s in labels if _label_re(s).match(line)), key=len)
    return _label_re(best).match(line).group(1)


def find_amount(lines: list[str], synonyms: list[str]) -> int | None:
    value = find_value(lines, synonyms)
    amounts = amounts_in(value) if value else []
    return amounts[0] if amounts else None


def count_markers(lines: list[str], words: list[str]) -> int:
    """Jumlah kata/frasa unik dari `words` yang muncul sebagai kata utuh di salah satu baris."""
    texts = [line.lower() for line in lines]
    found = 0
    for word in {w.lower().strip() for w in words if w and w.strip()}:
        rx = re.compile(r"(?<!\w)" + r"\s+".join(re.escape(p) for p in word.split()) + r"(?!\w)")
        if any(rx.search(t) for t in texts):
            found += 1
    return found


# ── Tanggal dan jam ─────────────────────────────────────────────────────────

_MONTH_NAMES = [
    ("januari", "january", "jan"), ("februari", "february", "feb", "peb"), ("maret", "march", "mar"),
    ("april", "apr"), ("mei", "may"), ("juni", "june", "jun"), ("juli", "july", "jul"),
    ("agustus", "august", "agu", "ags", "aug"), ("september", "sep", "sept"),
    ("oktober", "october", "okt", "oct"), ("november", "nopember", "nov", "nop"),
    ("desember", "december", "des", "dec"),
]
_MONTHS = {name: number for number, names in enumerate(_MONTH_NAMES, 1) for name in names}

# Tahun dibatasi 20xx supaya nomor referensi dan nominal tidak terbaca sebagai tanggal.
_ISO = re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_DMY_NUM = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})(?!\d)")
# Nama bulan boleh memuat angka 0 sebagai huruf O hasil OCR ("31 0kt 2026", "1 N0v 2026"; ShopeePay A14 r3): hanya nama bulan
# yang dikenal (`_MONTHS`) yang diterima, jadi "Rp100.000 2026" tetap bukan tanggal.
_DMY_NAME = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]*([A-Za-z0]{3,10})\.?[\s.,\-/]*(20\d{2})(?!\d)")
_MDY_NAME = re.compile(r"(?<![A-Za-z])([A-Za-z]{3,10})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})(?!\d)")
_TIME = re.compile(r"(?<![\d:.])(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?(?!\d)(?:\s*([AaPp][Mm])(?![A-Za-z]))?")


def _find_date(text: str):
    """Tanggal sah paling awal di `text`: (mulai, akhir, tahun, bulan, hari) atau None."""
    found = []
    for rx, order in ((_ISO, "ymd"), (_DMY_NUM, "dmy"), (_DMY_NAME, "dMy"), (_MDY_NAME, "Mdy")):
        for m in rx.finditer(text):
            parts = dict(zip(order, m.groups()))
            month = parts.get("M")
            month = _MONTHS.get((month or "").lower().replace("0", "o")) if month is not None else int(parts["m"])
            if not month:
                continue
            try:
                datetime(int(parts["y"]), month, int(parts["d"]))
            except ValueError:
                continue
            found.append((m.start(), m.end(), int(parts["y"]), month, int(parts["d"])))
    return min(found, key=lambda f: f[0]) if found else None


def _find_time(text: str) -> tuple[int, int, int]:
    for m in _TIME.finditer(text):
        hour, minute, second = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        meridiem = (m.group(4) or "").lower()
        if meridiem:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        if hour > 23 or minute > 59 or second > 59:
            continue
        return hour, minute, second
    return 0, 0, 0


def parse_datetime_id(text: str) -> datetime | None:
    """Tanggal (dan jam, bila ada) dalam format Indonesia atau Inggris, zona Asia/Jakarta.
    Tanpa jam -> 00:00. Tanpa tanggal yang sah -> None."""
    found = _find_date(text or "")
    if not found:
        return None
    start, end, year, month, day = found
    hour, minute, second = _find_time(text[:start] + " " + text[end:])
    return datetime(year, month, day, hour, minute, second, tzinfo=WIB)


def find_datetime(lines: list[str]) -> datetime | None:
    """Tanggal-jam dari baris pertama yang terbaca."""
    for line in lines:
        parsed = parse_datetime_id(line)
        if parsed:
            return parsed
    return None
