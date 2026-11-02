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


# ── Label aturan belajar (spec 2026-11-01 §5; plan Task L3) ────────────────

# Tanda baca di depan baris yang bukan bagian label ("• Total Bayar", "- Waktu Selesai"); sama dengan pinggiran yang
# dibuang `kerangka.safe_label`, jadi label aturan (dari kerangka) cocok dengan baris yang sama.
_LEAD = " \t:：;,.|·•-–—_/\\"
_AMOUNT_START = re.compile(r"(?:Rp|IDR)\.?\s*\d|\d", re.IGNORECASE)


def _learned_values(lines: list[str], labels: list[str], starts) -> tuple[str, int] | None:
    """(teks nilai, indeks barisnya) untuk label aturan yang PERSIS (bukan awalan label lain): sisa baris sesudah label
    (dan titik dua) bila `starts(sisa)`, atau, bila label berdiri sendiri, baris berikutnya bila `starts(baris itu)`.
    Label lebih awal diutamakan, lalu baris lebih atas. Sama dengan cara kerangka memberi label: teks sebelum nilai di
    baris yang sama, atau baris label di atas nilai yang berdiri sendiri."""
    for label in labels:
        rx = _label_re(label)
        for i, line in enumerate(lines):
            m = rx.match(line.lstrip(_LEAD))
            if not m:
                continue
            rest = m.group(1)
            if rest:
                if starts(rest):
                    return rest, i
                continue
            following = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if following and starts(following):
                return following, i + 1
    return None


def learned_amount(lines: list[str], labels: list[str]) -> int | None:
    """Nominal di label aturan `label_total` (K6: dibaca sebagai TOTAL, bukan subtotal): nilai harus diawali nominal
    ("Rp12.500", "12.500"), jadi label aturan "total" tidak membaca baris "Total Bayar Rp11.000" dan "jumlah" tidak
    membaca "Jumlah Kirim Uang". Nominal PERTAMA di nilai itu (seperti kerangka memberi suara). None bila tidak ketemu
    (pembaca memakai logika biasa)."""
    if not labels:
        return None
    found = _learned_values(lines, labels, lambda text: bool(_AMOUNT_START.match(text)))
    amounts = amounts_in(found[0]) if found else []
    return amounts[0] if amounts else None


# Jam saja di baris sesudah tanggal ("26 Okt 2026" lalu "00:01 WIB"), sama dengan `proof_common.read_paid_at`.
_TIME_LINE = re.compile(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(?:WIB|WITA|WIT)?", re.IGNORECASE)


def learned_datetime(lines: list[str], labels: list[str]) -> datetime | None:
    """Waktu bayar di label aturan `label_tanggal`: nilai harus diawali tanggal (label aturan "waktu" tidak membaca
    "Waktu Selesai 26 Okt 2026"). Jam dari baris yang sama, atau, bila tanpa jam, dari baris sesudahnya yang hanya
    berisi jam (seperti `proof_common.read_paid_at`). None bila tidak ketemu (pembaca memakai logika biasa)."""
    if not labels:
        return None

    def starts_with_date(text: str) -> bool:
        found = _find_date(text)
        return bool(found) and not text[:found[0]].strip(_LEAD)

    found = _learned_values(lines, labels, starts_with_date)
    if not found:
        return None
    value, at = found
    paid = parse_datetime_id(value)
    if paid is not None and (paid.hour, paid.minute, paid.second) == (0, 0, 0) and at + 1 < len(lines):
        m = _TIME_LINE.fullmatch(lines[at + 1].strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 and int(m.group(3) or 0) < 60:
            paid = paid.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3) or 0))
    return paid


def mask_partial_labels(lines: list[str], labels: list[str], label_words) -> tuple[list[str], bool]:
    """(baris, ada yang persis) untuk label penerima aturan (`label_pihak`): baris yang diawali label aturan tetapi
    labelnya di kerangka lebih panjang ("Tujuan Transfer Lainnya" untuk aturan "tujuan": kerangka menyerap kata label
    "transfer" ke labelnya) dikosongkan (indeks tetap), supaya label aturan hanya membaca baris yang labelnya PERSIS
    label itu. Persis: diikuti titik dua, akhir baris (nilai di baris bawah), atau kata yang bukan kata label
    (`label_words` = kerangka.LABEL_WORDS); kata label berhuruf besar sesudah label berhuruf campuran tetap nilai
    ("Ke TOKO MAJU"), seperti `kerangka._split_label`."""
    out, whole = list(lines), False
    for i, line in enumerate(lines):
        text = line.lstrip(_LEAD)
        hits = [label for label in labels if _label_re(label).match(text)]
        if not hits:
            continue
        if any(_whole_label(text, label, label_words) for label in hits):
            whole = True
        else:
            out[i] = ""
    return out, whole


def _whole_label(text: str, label: str, label_words) -> bool:
    parts = [re.escape(p) for p in label.split()]
    m = re.match(r"^\s*" + r"\s+".join(parts) + r"(?=$|[\s:：])\s*", text, re.IGNORECASE)
    rest = text[m.end():]
    if not rest or rest[0] in ":：":
        return True
    raw = rest.split()[0]
    word = raw.strip(".,:;()'\"&/-–!?*•·").lower()
    if not word or word not in label_words:
        return True
    head = text.split()[0]
    return not head.isupper() and len(raw) > 1 and raw.isupper()


# Nama publik untuk modul lain (kotak_struk/kerangka.py): jangan dihapus atau diganti nama tanpa memperbarui pemakainya.
find_date = _find_date
