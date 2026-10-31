"""Parser struk berbasis aturan (tanpa LLM).

Input: baris-baris teks hasil OCR. Output: ReceiptParse (toko, tanggal, total,
tingkat keyakinan, bukti). Murni (tanpa DB/IO) supaya mudah di-test; data hasil
belajar (profil toko, alias salah-baca) dioper lewat argumen.

Alur keyakinan total:
- "tinggi": baris TOTAL cocok dengan sumber kedua (tunai − kembali / non-tunai).
- "sedang": satu sumber yang kuat (baris TOTAL, atau tunai − kembali saja).
- "rendah": hanya tebakan (SUBTOTAL / nominal terbesar).
- "gagal": tidak ada nominal sama sekali.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# ── Kosakata ────────────────────────────────────────────────────────────────

# Kata kunci yang dikenali secara toleran (salah baca OCR 1 huruf tetap cocok).
VOCAB = [
    "TOTAL", "SUBTOTAL", "GRAND", "BELANJA", "BAYAR", "PEMBAYARAN", "TAGIHAN",
    "JUMLAH", "HARGA", "JUAL", "TUNAI", "KEMBALI", "KEMBALIAN", "HEMAT",
    "VOUCHER", "DISKON", "DEBIT", "KREDIT", "CREDIT", "CASH", "CHANGE", "NETTO",
]

# Salah baca OCR yang sering & tidak tertangkap jarak-1 (atau terlalu pendek).
OCR_ALIASES = {
    "T0TAL": "TOTAL", "TOTA1": "TOTAL", "T0TA1": "TOTAL", "TOTAI": "TOTAL",
    "TUNAL": "TUNAI", "TUNA1": "TUNAI", "TUNAl": "TUNAI",
    "KEHBALI": "KEMBALI", "KEMBAL1": "KEMBALI", "KEMBAII": "KEMBALI", "KEHBAL1": "KEMBALI",
}

# Bobot lebih tinggi = lebih mungkin total akhir yang dibayar.
# Urutan = urutan pengecekan (yang pertama cocok dipakai), jadi SUB TOTAL
# dicek paling awal agar tidak tertangkap pola TOTAL biasa.
TOTAL_KEYS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"SUB\s*-?\s*TOTAL"), 30),
    (re.compile(r"GRAND\s*TOTAL"), 100),
    (re.compile(r"TOTAL\s*(BAYAR|PEMBAYARAN|TAGIHAN|BELANJA|HARGA|AKHIR|PENJUALAN|PAYMENT|DUE)"), 95),
    (re.compile(r"JUMLAH\s*(BAYAR|TAGIHAN|PEMBAYARAN)"), 90),
    (re.compile(r"HARUS\s*DI\s*BAYAR|YANG\s*DIBAYAR"), 90),
    (re.compile(r"NET\s*TOTAL|TOTAL\s*NET|NETTO"), 85),
    (re.compile(r"(^|[^A-Z])TOTAL([^A-Z]|$)"), 70),
    (re.compile(r"TAGIHAN"), 60),
    (re.compile(r"HARGA\s*JUAL"), 50),
    (re.compile(r"JUMLAH([^A-Z]|$)"), 45),
]
# "TOTAL (INCL. TAX)" tetap baris total walau memuat kata pajak.
TOTAL_INCL_TAX = re.compile(r"TOTAL\s*\(?\s*(INCL|INC\b|TERMASUK|SETELAH|AFTER|NETT)")
# Nomor kartu/akun tersamar: "**** 1234", "XXXX8899".
MASKED = re.compile(r"\*{2,}|X{4,}")
# Baris ini BUKAN total walau ada kata TOTAL.
NOT_TOTAL = re.compile(
    r"TOTAL\s*(ITEM|QTY|JML|JUMLAH\s*ITEM|DISKON|DISC|HEMAT|POTONGAN|PPN|PAJAK|POIN|POINT)"
    r"|ITEM\s*TOTAL|QTY|HEMAT|POIN|POINT|DPP|PPN|PAJAK|TAX|SERVICE|KEMBALI|CHANGE|DISKON|DISC|VOUCHER"
)
CASH_KEYS = re.compile(r"\bTUNAI\b|\bCASH\b|UANG\s*DITERIMA|\bDIBAYAR\b")
CHANGE_KEYS = re.compile(r"KEMBALI(AN)?|CHANGE|SUSUK")
CARD_KEYS = re.compile(
    r"DEBIT|KREDIT|CREDIT|QRIS|GOPAY|OVO|\bDANA\b|SHOPEEPAY|LINKAJA|FLAZZ|E-?MONEY|BRIZZI|NON\s*TUNAI|EDC|KARTU"
)
NOISE_LINE = re.compile(
    r"NPWP|NPWVP|TELP|TLP|PHONE|HP\s*[:.]|WA\s*[:.]|NO\.?\s*(STRUK|NOTA|TRX|TRANS|REF|KARTU|INV)|INVOICE|KASIR"
    r"|CASHIER|ID\s*TRX|MEMBER|KODE|REF\s*NO|APPR|TID|MID|BATCH|TRACE|RRN|POINKU|PURCHASE"
)
ADDRESS_START = re.compile(r"^(JL|JLN|JALAN|KOMP|RUKO|RT|KEL|KEC|KAB|KOTA|GEDUNG|BOULEVARD|PT)\b")

KNOWN_MERCHANTS = [
    "INDOMARET", "ALFAMART", "ALFAMIDI", "ALFA EXPRESS", "LAWSON", "FAMILYMART", "FAMILY MART", "CIRCLE K",
    "SUPERINDO", "SUPER INDO", "HYPERMART", "TRANSMART", "CARREFOUR", "LOTTE MART", "LOTTE GROSIR", "GIANT",
    "FOODHALL", "RANCH MARKET", "GRAND LUCKY", "YOGYA", "GRIYA", "BORMA", "RAMAYANA", "MATAHARI",
    "GUARDIAN", "WATSONS", "CENTURY", "KIMIA FARMA", "APOTEK K-24", "VIVA APOTEK", "PERTAMINA", "SHELL",
    "BP AKR", "STARBUCKS", "KOPI KENANGAN", "JANJI JIWA", "FORE COFFEE", "TOMORO", "POINT COFFEE", "CHATIME",
    "MIXUE", "KFC", "MCDONALD", "BURGER KING", "PIZZA HUT", "DOMINO", "HOKBEN", "HOKA HOKA BENTO",
    "YOSHINOYA", "RICHEESE", "SOLARIA", "J.CO", "BREADTALK", "SUSHI TEI", "MIE GACOAN", "IKEA",
    "ACE HARDWARE", "INFORMA", "MR.DIY", "MR DIY", "MINISO", "DAISO", "UNIQLO", "GRAMEDIA", "EIGER",
]
# "PT INDOMARCO" bukan nama toko; cek nama dagang di atas dulu.
_MERCHANT_RE = [(m, re.compile(r"(^|[^A-Z])" + re.escape(m) + r"([^A-Z]|$)")) for m in KNOWN_MERCHANTS]

MONTHS = {
    "JAN": 1, "FEB": 2, "PEB": 2, "MAR": 3, "APR": 4, "MEI": 5, "MAY": 5, "JUN": 6, "JUL": 7,
    "AGU": 8, "AGS": 8, "AUG": 8, "SEP": 9, "OKT": 10, "OCT": 10, "NOV": 11, "NOP": 11, "DES": 12, "DEC": 12,
}

MIN_AMOUNT = 100
MAX_AMOUNT = 100_000_000


# ── Hasil ───────────────────────────────────────────────────────────────────

@dataclass
class ReceiptItem:
    """Satu barang di struk."""
    name: str
    amount: int  # subtotal baris yang dipakai (sesudah koreksi otomatis)
    qty: float | None = None
    unit_price: int | None = None
    discount: int = 0  # voucher/diskon yang melekat ke barang ini
    read_amount: int | None = None  # subtotal seperti terbaca OCR
    flag: str = "ok"  # ok | auto (dikoreksi otomatis) | cek (perlu dicek user)
    note: str | None = None
    suggestion: int | None = None  # nominal yang disarankan (cek)
    line: int = -1
    line_end: int = -1  # baris terakhir (barang dua baris)

    @property
    def calc(self) -> int | None:
        """qty × harga satuan, kalau keduanya terbaca."""
        if self.qty and self.unit_price:
            return int(round(self.qty * self.unit_price))
        return None


@dataclass
class ReceiptAdjustment:
    """Penyesuaian di luar barang: diskon/voucher global atau pajak/service."""
    label: str
    amount: int  # selalu positif
    kind: str  # discount | charge


@dataclass
class Reconciliation:
    items_total: int
    discounts: int
    charges: int
    expected: int  # items_total − discounts + charges
    total: int | None
    diff: int | None  # total − expected
    status: str  # cocok | selisih | kosong
    note: str | None = None


@dataclass
class ReceiptParse:
    merchant: str | None
    date: date | None
    total: int | None
    confidence: str  # tinggi | sedang | rendah | gagal
    evidence: list[str] = field(default_factory=list)
    total_label: str | None = None  # label baris yang dipakai (untuk belajar)
    lines: list[str] = field(default_factory=list)
    items: list[ReceiptItem] = field(default_factory=list)
    adjustments: list[ReceiptAdjustment] = field(default_factory=list)
    reconciliation: Reconciliation | None = None
    # Apa yang menguatkan total: payment (tunai/non-tunai) | items (rincian cocok)
    # | items_sum (total = jumlah rincian, tanpa baris TOTAL) | None
    confidence_source: str | None = None


# ── Normalisasi ─────────────────────────────────────────────────────────────

def _levenshtein1(a: str, b: str) -> bool:
    """True jika jarak edit a↔b ≤ 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b)) == 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _exact_alias(word: str, aliases: dict[str, str]) -> str:
    up = word.upper()
    return aliases.get(up) or OCR_ALIASES.get(up) or word


def _fuzzy_keyword(word: str) -> str:
    up = word.upper()
    if len(up) >= 5 and up.isalpha() and up not in VOCAB:
        for v in VOCAB:
            if len(v) >= 5 and _levenshtein1(up, v):
                return v
    return word


# Kata tepat sebelum nominal / titik dua = label baris ("TUNAL : 50.000").
# Pencocokan toleran HANYA di posisi ini, supaya nama toko/barang seperti
# "TUNAS JAYA" tidak berubah jadi "TUNAI JAYA".
_LABEL_WORD = re.compile(r"\b([A-Za-z]{5,})(?=\s*[:=]?\s*(?:RP\.?\s*)?\(?\d)", re.I)


_DIGITISH = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "$": "5", "B": "8"})


def normalize_line(line: str, aliases: dict[str, str] | None = None) -> str:
    aliases = aliases or {}
    line = line.replace("\t", " ")
    # Huruf O di antara huruf yang terbaca 0: "T0TAL" → "TOTAL".
    line = re.sub(r"(?<=[A-Za-z])0(?=[A-Za-z])", "O", line)
    # Token mirip angka (diawali digit): "5O.4OO" → "50.400". Kecuali isi
    # kemasan di nama barang seperti "20S"/"12B" (angka + satu huruf S/B).
    line = re.sub(
        r"(^|[\s:=(])(\d[0-9OolI|S$B.,:/-]+)(?=$|[\s)])",
        lambda m: m.group(1) + (m.group(2) if re.fullmatch(r"\d+[SB]", m.group(2))
                                else m.group(2).translate(_DIGITISH)),
        line,
    )
    line = re.sub(r"[A-Za-z0-9]+", lambda m: _exact_alias(m.group(0), aliases), line)
    fuzzed = _LABEL_WORD.sub(lambda m: _fuzzy_keyword(m.group(1)), line)
    # Terima koreksi toleran hanya jika hasilnya baris label yang dikenal;
    # "BAYAM 7.500" tidak boleh jadi "BAYAR 7.500".
    if fuzzed != line and _is_label_line(fuzzed.upper()):
        line = fuzzed
    return re.sub(r"\s+", " ", line).strip()


def _is_label_line(up: str) -> bool:
    return bool(
        any(rx.search(up) for rx, _ in TOTAL_KEYS)
        or CASH_KEYS.search(up) or CHANGE_KEYS.search(up) or CARD_KEYS.search(up) or NOT_TOTAL.search(up)
    )


# ── Nominal ─────────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"(?:RP\.?\s*)?(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{2}))?(?!\d)", re.I)
# Sambungan token sesudah angka: huruf/digit yang menempel, atau sesudah satu "-" ("2610264RL9", "261026-4RL9").
_TOKEN_TAIL = re.compile(r"(-?)([A-Za-z0-9]+)")
_QTY_TAIL = re.compile(r"[xX]\d+")   # "3.500x12": pengali jumlah, bukan kode
# Angka tersamar: ekor nomor rekening/HP/kartu yang dicetak aplikasi atau korpus ("…4321", "Bank Mandiri-…4321",
# "****1234", "•• 4567"): deret angka tanpa pemisah ribuan. "…" harus menempel; deret >= 2 tanda samaran boleh diikuti
# satu spasi. Satu tanda saja ("KOPI *15.000", "Total • Rp52.500") bukan samaran, dan nominal berpemisah ribuan sesudah
# titik penuntun ("TOTAL…27.000", "TOTAL ••• 27.000") tetap nominal.
_MASKED_BEFORE = re.compile(r"(?:…|[*•●]{2,}\s?)$")


def _id_digits(raw: str, rest: str) -> bool:
    """Angka ini bagian ID/kode transaksi, bukan nominal: sambungannya kode campuran huruf+digit ≥ 3 karakter
    ("261026-4RL9-PVRERW", "2610264RL9"), atau angka polos ≥ 6 digit yang disambung "-" ke segmen lain
    ("261026-PVRERW"). Huruf pajak/satuan yang menempel ke harga ("12.500A", "8.500B", "600ML") dan kode pajak dua
    karakter ("12500B1") tetap nominal."""
    m = _TOKEN_TAIL.match(rest)
    if not m:
        return False
    dash, run = m.groups()
    if len(run) >= 3 and re.search(r"[A-Za-z]", run) and re.search(r"\d", run) and not _QTY_TAIL.fullmatch(run):
        return True
    return bool(dash) and raw.isdigit() and len(raw) >= 6


def amounts_in(line: str) -> list[int]:
    """Semua nominal rupiah wajar di satu baris ("35.000", "35,000", "35000", "Rp 35.000,00")."""
    out = []
    for m in _AMOUNT_RE.finditer(line):
        raw = m.group(1)
        before = line[m.start() - 1:m.start()] if m.start() > 0 else ""
        after = line[m.end():m.end() + 1]
        if before in ("/", "-") or before.isalpha() or after in ("/", ":"):
            continue  # bagian tanggal/jam/kode: 14.10.26-19:21/3.0.27/THTV-363626
        if _id_digits(raw, line[m.end():]):
            continue  # ID transaksi: 261026-4RL9-PVRERW, 2610264RL9
        if not re.search(r"[.,]", raw) and _MASKED_BEFORE.search(line[:m.start()]):
            continue  # ekor nomor tersamar: …4321, ****1234 (berpemisah ribuan = nominal: "TOTAL…27.000")
        value = int(re.sub(r"[.,]", "", raw))
        if value < MIN_AMOUNT or value > MAX_AMOUNT:
            continue  # < Rp100 biasanya qty/kode
        if not re.search(r"[.,]", raw) and len(raw) >= 9:
            continue  # nomor telp/kartu
        out.append(value)
    return out


def _label_of(line: str) -> str:
    """Bagian huruf dari baris (tanpa nominal & tanda baca) — kunci untuk profil toko."""
    label = re.sub(r"[^A-Z ]", " ", line.upper())
    label = re.sub(r"\bRP\b", " ", label)
    return re.sub(r"\s+", " ", label).strip()


# ── Tanggal ─────────────────────────────────────────────────────────────────

def _make_date(d: int, mo: int, y: int, today: date, max_age_days: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        dt = date(y, mo, d)
    except ValueError:
        return None
    diff = (today - dt).days
    if diff < -1 or diff > max_age_days:
        return None
    return dt


_DATE_PATTERNS = [
    (re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})[\s\-/.]*([A-Z]{3})[A-Z]*[\s\-/.,]*(\d{2,4})\b"),
     lambda m: (int(m[1]), MONTHS[m[2]], int(m[3])) if m[2] in MONTHS else None),
]


def find_date(lines: list[str], today: date, max_age_days: int = 366) -> date | None:
    for line in lines:
        up = line.upper()
        for pat, conv in _DATE_PATTERNS:
            for m in pat.finditer(up):
                parts = conv(m)
                if not parts:
                    continue
                dt = _make_date(*parts, today=today, max_age_days=max_age_days)
                if dt:
                    return dt
    return None


def printed_dates(lines: list[str]) -> set[date]:
    """Semua tanggal kalender sah yang tercetak (pola `find_date`, berapa pun umurnya), tanpa duplikat."""
    found = set()
    for line in lines:
        up = line.upper()
        for pat, conv in _DATE_PATTERNS:
            for m in pat.finditer(up):
                parts = conv(m)
                if not parts:
                    continue
                d, mo, y = parts
                try:
                    found.add(date(y + 2000 if y < 100 else y, mo, d))
                except ValueError:
                    pass
    return found


# ── Toko ────────────────────────────────────────────────────────────────────

def _title(s: str) -> str:
    return re.sub(r"(^|[\s(&.-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), s.lower())


def merchant_key(name: str | None) -> str | None:
    """Kunci stabil untuk profil toko: huruf/angka kapital tanpa spasi."""
    if not name:
        return None
    key = re.sub(r"[^A-Z0-9]", "", name.upper())
    return key[:60] or None


def find_merchant(lines: list[str], merchant_aliases: dict[str, str] | None = None) -> str | None:
    merchant_aliases = merchant_aliases or {}
    top = lines[:12]
    for line in top:
        up = line.upper()
        for name, rx in _MERCHANT_RE:
            if rx.search(up):
                return _title(name)
    for line in top:  # alias hasil belajar: "INDOMAREI" → "Indomaret"
        for word in re.findall(r"[A-Z0-9][A-Z0-9 .&'-]{2,}", line.upper()):
            k = merchant_key(word)
            if k in merchant_aliases:
                return merchant_aliases[k]
    for line in lines[:6]:
        letters = sum(c.isalpha() for c in line)
        compact = len(re.sub(r"\s", "", line)) or 1
        up = line.upper()
        if letters < 3 or letters / compact < 0.6:
            continue
        if NOISE_LINE.search(up) or ADDRESS_START.search(up):
            continue
        return _title(re.sub(r"[^A-Za-z0-9&'.\s-]", "", line).strip())[:40] or None
    return None


# ── Total ───────────────────────────────────────────────────────────────────

def _amount_for(lines: list[str], i: int) -> tuple[int, int] | None:
    """Nominal untuk baris kunci i: nominal terakhir di baris itu, atau baris berikutnya
    kalau baris berikutnya hanya angka."""
    here = amounts_in(lines[i])
    if here:
        return here[-1], i
    if i + 1 < len(lines):
        nxt = amounts_in(lines[i + 1])
        has_words = re.search(r"[A-Z]{4,}", lines[i + 1].upper().replace("RP", ""))
        if nxt and not has_words:
            return nxt[-1], i + 1
    return None


def _skip_line(up: str) -> bool:
    """Baris yang nominalnya bukan uang belanja: nomor kartu tersamar, ID, telp."""
    return bool(NOISE_LINE.search(up) or MASKED.search(up))


PAYMENT_TAIL_LINES = 4
# Label pembayaran di awal baris (boleh diawali nama bank): "BCA DEBIT 69.300".
PAYMENT_START = re.compile(
    r"^[^A-Z0-9]*(?:(?:BCA|BNI|BRI|MANDIRI|CIMB|BSI|PERMATA|DANAMON|BTN|OCBC|MAYBANK|JENIUS|MEGA|PANIN)\s+)?"
    r"(TUNAI|CASH|KEMBALI(AN)?|CHANGE|NON\s*TUNAI|DEBIT|KREDIT|CREDIT|QRIS|GOPAY|OVO|DANA|SHOPEEPAY|LINKAJA"
    r"|FLAZZ|E-?MONEY|BRIZZI|EDC|KARTU\s+(DEBIT|KREDIT)|BAYAR|PEMBAYARAN|UANG\s*DITERIMA)\b"
)


def _payment_start(lines: list[str]) -> tuple[int, bool]:
    """(baris pertama yang boleh berisi pembayaran, wajib berlabel?).

    Ada baris ringkasan → mulai dari situ. Tidak ada → hanya beberapa baris
    terakhir, dan barisnya harus diawali label pembayaran (nama barang seperti
    "TOP UP GOPAY" atau "KARTU PERDANA" bukan pembayaran)."""
    first = next((i for i, l in enumerate(lines) if _is_summary(l.upper())), None)
    if first is not None:
        return first, False
    return max(0, len(lines) - PAYMENT_TAIL_LINES), True


def _payments(lines: list[str]):
    """(tunai, kembali, [non-tunai]) — masing-masing (nilai, baris) atau None.

    Hanya dicari mulai baris ringkasan/pembayaran pertama, supaya nama barang
    seperti "KARTU UCAPAN" atau "CASHEW" tidak dianggap pembayaran.
    """
    cash = change = None
    cards: list[tuple[int, str]] = []
    first, need_label = _payment_start(lines)
    for i, line in enumerate(lines):
        if i < first:
            continue
        up = line.upper()
        if need_label and not PAYMENT_START.search(up):
            continue
        if _skip_line(up) or "TOTAL" in up:
            continue
        if CHANGE_KEYS.search(up):
            a = _amount_for(lines, i)
            if a and change is None:
                change = (a[0], line)
        elif CARD_KEYS.search(up):  # dicek sebelum tunai: "NON TUNAI" mengandung TUNAI
            a = _amount_for(lines, i)
            if a:
                cards.append((a[0], line))
        elif CASH_KEYS.search(up):
            a = _amount_for(lines, i)
            if a and cash is None:
                cash = (a[0], line)
    return cash, change, cards


def payment_line_indices(lines: list[str]) -> list[int]:
    """Indeks baris tunai/kembali/non-tunai yang dipakai _payments (urut naik)."""
    out = []
    first, need_label = _payment_start(lines)
    for i, line in enumerate(lines):
        if i < first:
            continue
        up = line.upper()
        if need_label and not PAYMENT_START.search(up):
            continue
        if _skip_line(up) or "TOTAL" in up:
            continue
        if (CHANGE_KEYS.search(up) or CARD_KEYS.search(up) or CASH_KEYS.search(up)) and _amount_for(lines, i):
            out.append(i)
    return out


def payment_amounts(lines: list[str]) -> set[int]:
    """Nominal yang benar-benar dibayar menurut struk (tunai − kembali, non-tunai,
    atau tunai pas). Dipakai untuk memvalidasi koreksi sebelum dipelajari."""
    cash, change, cards = _payments(lines)
    out = {v for v, _ in cards}
    if cash and change and cash[0] > change[0]:
        out.add(cash[0] - change[0])
    elif cash and not change:
        out.add(cash[0])
    return out


def find_total(lines: list[str], learned_labels: list[str] | None = None):
    learned = [lbl for lbl in (learned_labels or []) if lbl]
    candidates: list[tuple[int, int, int, str]] = []  # (weight, line_idx, value, raw_line)
    cash, change, cards = _payments(lines)

    for i, line in enumerate(lines):
        up = line.upper()
        if _skip_line(up):
            continue
        if "TOTAL" not in up and (CHANGE_KEYS.search(up) or CARD_KEYS.search(up) or CASH_KEYS.search(up)):
            continue
        label = _label_of(line)
        if label and label in learned:  # profil toko hasil belajar
            a = _amount_for(lines, i)
            if a:
                candidates.append((96, i, a[0], line))
                continue
        if NOT_TOTAL.search(up) and not TOTAL_INCL_TAX.search(up):
            continue
        for rx, weight in TOTAL_KEYS:
            if rx.search(up):
                a = _amount_for(lines, i)
                if a:
                    candidates.append((weight, i, a[0], line))
                break

    candidates.sort(key=lambda c: (-c[0], -c[1]))
    exact = cash[0] - change[0] if (cash and change and cash[0] > change[0]) else None
    pas = cash[0] if (cash and not change) else None
    card_values = [v for v, _ in cards]
    confirmations = set(card_values) | {v for v in (exact, pas) if v is not None}

    evidence = []
    if exact is not None:
        evidence.append(f"Tunai {cash[0]} − kembali {change[0]} = {exact}")
    if pas is not None:
        evidence.append(f"Tunai {pas} (tanpa kembalian)")
    for v, line in cards:
        evidence.append(f'Non-tunai "{line}" → {v}')

    def result(value, conf, line=None, idx=None):
        """(nilai, keyakinan, bukti, label, indeks baris total, indeks baris tebakan)."""
        if line:
            evidence.insert(0, f'Baris "{line}" → {value}')
        return value, conf, evidence, (_label_of(line) if line else None), idx, None

    # 1) Kandidat yang dikonfirmasi pembayaran = keyakinan tinggi.
    for w, idx, value, line in candidates:
        if value in confirmations:
            return result(value, "tinggi", line, idx)

    # 2) Kandidat terbaik, diturunkan kalau bertentangan dengan pembayaran.
    if candidates:
        w, idx, value, line = candidates[0]
        contradicted = exact is not None or bool(card_values)
        if contradicted:
            evidence.append("Total tidak cocok dengan pembayaran — mohon dicek")
            return result(value, "rendah", line, idx)
        return result(value, "sedang" if w >= 70 else "rendah", line, idx)

    # 3) Tanpa baris TOTAL: pakai pembayaran.
    if exact is not None:
        return result(exact, "sedang")
    if card_values:
        return result(card_values[-1], "sedang")
    if pas is not None:  # bisa jadi uang yang diserahkan, bukan total
        return result(pas, "rendah")

    biggest = None
    for i, line in enumerate(lines):
        up = line.upper()
        if CASH_KEYS.search(up) or _skip_line(up):
            continue
        for v in amounts_in(line):
            if biggest is None or v > biggest[0]:
                biggest = (v, line, i)
    if biggest:
        evidence.append(f'Tidak ada kata TOTAL; pakai nominal terbesar "{biggest[1]}"')
        value, conf, ev, label, idx, _ = result(biggest[0], "rendah")
        return value, conf, ev, label, idx, biggest[2]
    return None, "gagal", ["Tidak ada nominal yang terbaca"], None, None, None


# ── Rincian barang ──────────────────────────────────────────────────────────
#
# Struk minimarket umumnya: NAMA [QTY] [HARGA] SUBTOTAL per baris, voucher
# "(3.000)" tepat di bawah barangnya, lalu baris ringkasan (HARGA JUAL /
# SUBTOTAL / TOTAL). Wilayah barang = setelah baris tanggal/kasir sampai baris
# ringkasan pertama; di antara ringkasan pertama dan baris TOTAL ada diskon
# global & pajak/service. Σ barang − diskon + pajak harus = total.

DISCOUNT_KEYS = re.compile(r"VOUCHER|\bVC\b|DISKON|\bDISC|POTONGAN|PROMO|CASHBACK|HEMAT")
# Baris diskon: kata diskon di mana saja ("SPESIAL DISKON"), kecuali PROMO yang
# harus di awal ("PAKET PROMO 25.000" itu barang, "PROMO 5.000" itu potongan).
DISCOUNT_LABEL = re.compile(r"\b(VOUCHER|VC|DISKON|DISC|DISCOUNT|POTONGAN|CASHBACK|HEMAT)\b|^PROMO\b")
# Ringkasan diskon ("TOTAL DISC", "ANDA HEMAT"): jangan dihitung dua kali.
DISCOUNT_SUMMARY = re.compile(r"TOTAL\s*(DISC|DISKON|HEMAT|POTONGAN|VOUCHER|PROMO)|ANDA\s*HEMAT|^HEMAT\b")
# Baris ringkasan/pembayaran: kata kunci di AWAL baris, supaya nama barang seperti
# "SENSODYNE TOTAL CARE" atau "CASHEW" tidak memotong daftar barang.
SUMMARY_START = re.compile(
    r"^[^A-Z0-9]*(?:\d+\s*(?:ITEM|ITEMS|PCS|QTY|BRG|BARANG)\s*[:.]?\s*)?(SUB\s*-?\s*TOTAL|GRAND\s*TOTAL|TOTAL|HARGA\s*JUAL|JUMLAH|TAGIHAN|NETTO|NET\s*TOTAL|BAYAR|PEMBAYARAN"
    r"|TUNAI|CASH|KEMBALI(AN)?|CHANGE|NON\s*TUNAI|DEBIT|KREDIT|CREDIT|QRIS|GOPAY|OVO|DANA|SHOPEEPAY|LINKAJA"
    r"|FLAZZ|E-?MONEY|BRIZZI|EDC|ANDA\s*HEMAT|HARUS\s*DI\s*BAYAR|YANG\s*DIBAYAR)\b"
)
CHARGE_LABEL = re.compile(
    r"^(PAJAK|TAX|PB\s?1|PPN|SERVICE|SVC|SC|BIAYA|ONGKIR|ADMIN|KEMASAN|PACKAGING|PEMBULATAN|ROUNDING)\b"
)
CHARGE_KEYS = re.compile(
    r"PAJAK|\bTAX\b|\bPB\s?1\b|\bPPN\b|SERVICE|\bSVC\b|\bSC\b|BIAYA|ONGKIR|ADMIN|KEMASAN|PACKAGING|PEMBULATAN|ROUNDING"
)
INFO_ONLY = re.compile(r"DPP|TERMASUK|INCLUDED|\bINCL")  # pajak yang sudah termasuk harga
SUBTOTAL_KEYS = re.compile(r"SUB\s*-?\s*TOTAL|HARGA\s*JUAL|TOTAL\s*(ITEM|QTY)")
ADDRESS_WORDS = re.compile(r"\b(JL|JLN|JALAN|KEL|KEC|KAB|KOTA|RT|RW|PROV|BLOK|KOMP|RUKO|GEDUNG)\b")
_DATE_LIKE = re.compile(
    r"(?<!\d)\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}(?!\d)|\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b"
    r"|\b\d{1,2}\s*(JAN|FEB|MAR|APR|MEI|MAY|JUN|JUL|AGU|AGS|AUG|SEP|OKT|OCT|NOV|NOP|DES|DEC)[A-Z]*\s*\d{2,4}\b"
)
_NUM_TOKEN = re.compile(
    r"^(\()?(-)?(?:RP\.?)?(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,3}))?(-)?(\))?$", re.I
)
_SEP_TOKENS = {":", "=", "X", "@", "*", "RP", "RP.", "-", "/"}
MAX_ITEMS = 80


def _num_token(tok: str):
    """Token angka → (nilai, negatif?, punya pemisah ribuan?, desimal) atau None."""
    m = _NUM_TOKEN.match(tok)
    if not m:
        return None
    raw = m.group(3)
    has_sep = bool(re.search(r"[.,]", raw))
    if not has_sep and len(raw) >= 9:
        return None  # nomor telp/kartu
    value = int(re.sub(r"[.,]", "", raw))
    if value > MAX_AMOUNT:
        return None  # bukan nominal belanja (nomor seri, NIK, dsb.)
    neg = bool(m.group(1) or m.group(2) or m.group(5))
    return value, neg, has_sep, m.group(4)


def _qty_value(info) -> float | None:
    value, neg, has_sep, dec = info
    if neg or has_sep:
        return None
    if dec:  # berat: "0,25" kg
        q = float(f"{value}.{dec}")
        return q if 0 < q < 100 else None
    return float(value) if 1 <= value <= 99 else None


def _clean_name(tokens: list[str]) -> str:
    name = " ".join(tokens).strip(" :=-*@")
    name = re.sub(r"\s*\bRP\.?$", "", name, flags=re.I).strip(" :=-")
    return name[:60]


def _parse_line(line: str):
    """Baris → ("item", ReceiptItem) | ("discount", label, nilai) | None."""
    toks = line.split()
    trail = []  # token angka di ujung kanan, dari kanan ke kiri: (index, info)
    j = len(toks) - 1
    while j >= 0:
        t = toks[j]
        if t.upper() in _SEP_TOKENS:
            j -= 1
            continue
        info = _num_token(t)
        if info is None:
            break
        trail.append((j, info))
        j -= 1
    if not trail:
        return None
    total_j, tinfo = trail[0]
    tval, tneg, _tsep, tdec = tinfo
    rest = trail[1:]
    consumed = {total_j}
    unit = qty = None
    if rest:
        j1, i1 = rest[0]
        if i1[0] >= MIN_AMOUNT and not i1[3] and not i1[1]:
            unit = i1[0]
            consumed.add(j1)
            if len(rest) > 1:
                q = _qty_value(rest[1][1])
                if q is not None:
                    qty = q
                    consumed.add(rest[1][0])
        else:
            q = _qty_value(i1)
            if q is not None:
                qty = q
                consumed.add(j1)
    # Token angka yang tidak terpakai (mis. "720" pada "ROSY 720") milik nama;
    # pemisah ("x", ":", "Rp") di antara angka-angka ekor dibuang.
    first_num = min(consumed)
    name_tokens = [t for k, t in enumerate(toks)
                   if k < total_j and k not in consumed and not (k > first_num and t.upper() in _SEP_TOKENS)]
    # Format qty di depan: "2 INDOMIE GORENG 7.000"
    if qty is None and len(name_tokens) >= 2 and re.fullmatch(r"\d{1,2}", name_tokens[0]) \
            and re.search(r"[A-Za-z]{2,}", name_tokens[1]):
        qty = float(name_tokens[0])
        name_tokens = name_tokens[1:]
    name = _clean_name(name_tokens)
    letters = sum(c.isalpha() for c in name)

    if tneg or (DISCOUNT_LABEL.search(name.upper()) and unit is None and qty is None):
        if tval >= MIN_AMOUNT // 2 and not tdec:
            # Nominal positif dengan kata diskon ("VOUCHER GAME 20.000") bisa juga
            # barang → ditandai ambigu, diputuskan saat dicocokkan dengan total.
            return ("discount", name or "Diskon", tval, not tneg)
        return None
    if letters < 2:
        return None

    read_amount = tval if not tdec else None
    item = ReceiptItem(name=name, amount=0, qty=qty, unit_price=unit, read_amount=read_amount)
    if read_amount is None or read_amount < MIN_AMOUNT:
        # Subtotal baris tidak terbaca (mis. "4.500" terbaca "40"): pakai qty × harga.
        if unit is None:
            return None
        item.qty = qty or 1.0
        item.amount = int(round(item.qty * unit))
        item.flag = "auto"
        shown = toks[total_j]
        item.note = f"Subtotal terbaca \"{shown}\"; dipakai {_fmt_qty(item.qty)} × {_rp(unit)} = {_rp(item.amount)}"
        return ("item", item)
    item.amount = read_amount
    if unit is not None and unit != read_amount and qty is None:
        # qty menempel ke harga: "16000" = qty 1 + harga 6000.
        digits = str(unit)
        for q in range(1, 10):
            head, tail = str(q), digits[1:]
            if digits.startswith(head) and tail and int(tail) * q == read_amount:
                item.qty, item.unit_price = float(q), int(tail)
                break
    if item.qty is None and item.unit_price is not None and item.unit_price == read_amount:
        item.qty = 1.0
    if item.qty is not None and item.unit_price is None and item.qty >= 1:
        per = read_amount / item.qty
        if per == int(per):
            item.unit_price = int(per)
    return ("item", item)


def _fmt_qty(q: float | None) -> str:
    if q is None:
        return "1"
    return str(int(q)) if q == int(q) else f"{q:g}".replace(".", ",")


def _rp(n: int) -> str:
    return "Rp" + f"{int(n):,}".replace(",", ".")


def _is_summary(up: str) -> bool:
    return bool(SUMMARY_START.search(up.strip()))


def _line_weight(line: str) -> int:
    """Bobot baris total (urutan TOTAL_KEYS); 0 kalau bukan baris total."""
    up = line.upper()
    for rx, weight in TOTAL_KEYS:
        if rx.search(up):
            return weight
    return 0


def _merge_two_line_items(lines: list[str], start: int, end: int) -> list[tuple[int, int, str]]:
    """(baris awal, baris akhir, teks). Gabungkan barang dua baris:
    "INDOMIE GORENG" + "2 X 3.500 7.000"."""
    out, i = [], start
    while i < end:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < end else None
        if (nxt and re.search(r"[A-Za-z]{2,}", line) and not amounts_in(line)
                and re.match(r"^\(?\d", nxt) and amounts_in(nxt)
                and not re.search(r"[A-Za-z]{3,}", re.sub(r"\b(PCS|KG|GR|ML|LTR|BKS|PAK|RP)\b", "", nxt, flags=re.I))):
            out.append((i, i + 1, f"{line} {nxt}"))
            i += 2
            continue
        out.append((i, i, line))
        i += 1
    return out


def _adjustment_from(line: str):
    """Baris penyesuaian → ReceiptAdjustment atau None."""
    up = line.upper()
    if SUBTOTAL_KEYS.search(up) or _skip_line(up) or INFO_ONLY.search(up):
        return None
    toks = line.split()
    info = None
    for t in reversed(toks):
        info = _num_token(t)
        if info:
            break
    if not info or info[0] < MIN_AMOUNT // 2 or info[3]:
        return None
    value, neg = info[0], info[1]
    label = _clean_name([t for t in toks if not _num_token(t)]) or "Penyesuaian"
    if neg or DISCOUNT_KEYS.search(up):
        return ReceiptAdjustment(label=label, amount=value, kind="discount")
    if CHARGE_KEYS.search(up):
        return ReceiptAdjustment(label=label, amount=value, kind="charge")
    return None


def _first_payment_idx(lines: list[str], after: int) -> int:
    for i in range(max(after, 0), len(lines)):
        up = lines[i].upper()
        if CASH_KEYS.search(up) or CHANGE_KEYS.search(up) or CARD_KEYS.search(up):
            return i
    return len(lines)


def charges_between(lines: list[str], a: int, b: int) -> list[ReceiptAdjustment]:
    """Pajak/service di antara baris a..b-1 (mis. sesudah TOTAL sebelum pajak)."""
    out = []
    for i in range(a, b):
        adj = _adjustment_from(lines[i])
        if adj and adj.kind == "charge":
            out.append(adj)
    return out


def _digits_close(a: int, b: int) -> bool:
    """Beda satu angka (salah baca OCR): 3800 ↔ 8800, 4500 ↔ 45000."""
    return a != b and _levenshtein1(str(a), str(b))


def reconcile(items: list[ReceiptItem], adjustments: list[ReceiptAdjustment], total: int | None) -> Reconciliation:
    items_total = sum(it.amount for it in items)
    discounts = sum(it.discount for it in items) + sum(a.amount for a in adjustments if a.kind == "discount")
    charges = sum(a.amount for a in adjustments if a.kind == "charge")
    expected = items_total - discounts + charges
    if not items:
        return Reconciliation(items_total, discounts, charges, expected, total, None, "kosong")
    diff = None if total is None else total - expected
    status = "cocok" if diff == 0 else "selisih"
    return Reconciliation(items_total, discounts, charges, expected, total, diff, status)


def _annotate(items: list[ReceiptItem], adjustments: list[ReceiptAdjustment], total: int | None) -> Reconciliation:
    """Cocokkan rincian ke total; koreksi otomatis yang terbukti, tandai yang meragukan."""
    rec = reconcile(items, adjustments, total)
    if rec.status != "selisih" or rec.diff is None:
        return rec

    # 1) Subtotal baris ≠ qty × harga: pakai qty × harga jika itu membuat cocok.
    mismatched = [it for it in items if it.calc is not None and it.calc != it.amount]
    if mismatched:
        if rec.diff == sum(it.calc - it.amount for it in mismatched):
            fix = mismatched
        else:
            fix = [it for it in mismatched if it.calc - it.amount == rec.diff][:1]
        for it in fix:
            it.note = f"Dikoreksi: {_fmt_qty(it.qty)} × {_rp(it.unit_price)} = {_rp(it.calc)} (terbaca {_rp(it.amount)})"
            it.amount, it.flag = it.calc, "auto"
        rec = reconcile(items, adjustments, total)
        if rec.status == "cocok":
            return rec

    diff = rec.diff
    # 2) Satu angka salah baca: nominal + selisih beda satu digit dari yang terbaca.
    candidates = [(it, it.amount + diff) for it in items
                  if it.amount + diff >= MIN_AMOUNT and _digits_close(it.amount, it.amount + diff)]
    strong = [(it, c) for it, c in candidates if it.calc == c]
    if len(strong) == 1:
        it, c = strong[0]
        it.note = f"Dikoreksi: {_fmt_qty(it.qty)} × {_rp(it.unit_price)} = {_rp(c)} (terbaca {_rp(it.amount)})"
        it.amount, it.flag = c, "auto"
        return reconcile(items, adjustments, total)
    if 1 <= len(candidates) <= 3:
        for it, c in candidates:
            it.flag, it.suggestion = "cek", c
            it.note = (f"Mungkin {_rp(c)}? Angka bisa salah baca" if len(candidates) == 1
                       else f"Salah satu barang bertanda mungkin salah baca — coba {_rp(c)}")

    # 3) Rincian kelebihan sebesar satu barang: mungkin terbaca dobel / bukan barang.
    if diff < 0:
        same = [it for it in items if it.amount == -diff and it.flag == "ok"]
        seen: set[str] = set()
        dupes = []
        for it in same:  # barang dengan nama sama: tandai salinan yang belakangan saja
            key = it.name.upper()
            if key in seen:
                dupes.append(it)
            seen.add(key)
        for it in (dupes or same):
            it.flag, it.suggestion = "cek", 0
            it.note = ("Sepertinya terbaca dua kali — hapus jika di struk hanya sekali" if dupes
                       else "Mungkin terbaca dobel atau bukan barang — hapus jika tidak ada di struk")

    # 4) Sisa ketidakcocokan qty × harga yang belum dijelaskan.
    for it in items:
        if it.flag == "ok" and it.calc is not None and it.calc != it.amount:
            it.flag = "cek"
            it.note = f"{_fmt_qty(it.qty)} × {_rp(it.unit_price)} = {_rp(it.calc)}, tapi subtotal terbaca {_rp(it.amount)}"

    rec = reconcile(items, adjustments, total)
    flagged = any(it.flag == "cek" for it in items)
    if rec.diff and flagged:
        word = "kurang" if rec.diff > 0 else "lebih"
        rec.note = f"Rincian {word} {_rp(abs(rec.diff))} dari total — cek barang yang ditandai."
    elif rec.diff and rec.diff > 0:
        rec.note = f"Ada {_rp(rec.diff)} yang belum masuk rincian — mungkin ada barang yang tidak terbaca."
    elif rec.diff and rec.diff < 0:
        rec.note = f"Rincian kelebihan {_rp(-rec.diff)} dari total — mungkin ada diskon yang tidak terbaca."
    return rec


_TOTALISH_WORDS = {"BAYAR", "BYR", "JUMLAH", "JML", "TAGIHAN", "TTL", "GRAND", "NETTO", "NETT", "TOTAL"}


def _looks_like_total_label(name: str) -> bool:
    """Nama baris mirip label total yang tidak dikenali ("BAYAR", "JML", "TOTL")."""
    for word in re.findall(r"[A-Z]+", name.upper()):
        if word in _TOTALISH_WORDS or word.startswith("TOT") or _levenshtein1(word, "TOTAL"):
            return True
    return False


def _flag_mismatches(items: list[ReceiptItem]) -> None:
    """Tandai qty × harga ≠ subtotal tanpa mengoreksi (total belum bisa dipercaya)."""
    for it in items:
        if it.flag == "ok" and it.calc is not None and it.calc != it.amount:
            it.flag = "cek"
            it.note = f"{_fmt_qty(it.qty)} × {_rp(it.unit_price)} = {_rp(it.calc)}, tapi subtotal terbaca {_rp(it.amount)}"


def extract_items(lines: list[str], total: int | None, total_idx: int | None, *, annotate: bool = True):
    """Rincian barang + penyesuaian + rekonsiliasi terhadap total.

    annotate=False: total belum bisa dipercaya (tebakan) → jangan koreksi barang
    berdasarkan total itu, cukup tandai yang jelas janggal.
    """
    if not lines:
        return [], [], reconcile([], [], total)
    # Akhir wilayah barang: baris ringkasan/pembayaran pertama.
    end = next((i for i, l in enumerate(lines) if _is_summary(l.upper())), len(lines))
    if total_idx is not None and total_idx < end:
        end = total_idx
    pay_idx = payment_line_indices(lines)
    if pay_idx and pay_idx[0] < end:  # mis. "BCA DEBIT 69.300" tanpa baris TOTAL
        end = pay_idx[0]
    # Awal: sesudah baris tanggal/kasir di kepala struk (kalau ada).
    date_idx = next((i for i, l in enumerate(lines[:end]) if _DATE_LIKE.search(l.upper())), None)
    start = date_idx + 1 if date_idx is not None else 0

    items: list[ReceiptItem] = []
    adjustments: list[ReceiptAdjustment] = []
    ambiguous: list = []  # (pemilik diskon, label, nilai, baris awal, baris akhir)
    last_item_end = None
    for i, j, line in _merge_two_line_items(lines, start, end):
        up = line.upper()
        if _skip_line(up) or ADDRESS_WORDS.search(up) or _DATE_LIKE.search(up):
            continue
        if CHARGE_LABEL.search(up.strip()):  # pajak/service tanpa baris subtotal
            adj = _adjustment_from(line)
            if adj:
                adjustments.append(adj)
            continue
        parsed = _parse_line(line)
        if not parsed:
            continue
        if parsed[0] == "discount":
            _, label, value, is_ambiguous = parsed
            if items and last_item_end == i - 1:  # voucher tepat di bawah barangnya
                items[-1].discount += value
                last_item_end = j  # voucher berikutnya tetap ke barang yang sama
                owner = items[-1]
            else:
                owner = ReceiptAdjustment(label=label, amount=value, kind="discount")
                adjustments.append(owner)
            if is_ambiguous:
                ambiguous.append((owner, label, value, i, j))
            continue
        item = parsed[1]
        item.line, item.line_end = i, j
        items.append(item)
        last_item_end = j
        if len(items) >= MAX_ITEMS:
            break

    # Antara ringkasan pertama dan baris TOTAL: diskon global & pajak/service.
    b_end = total_idx if (total_idx is not None and total_idx >= end) else _first_payment_idx(lines, end)
    inline_disc = sum(it.discount for it in items)
    for i in range(end, b_end):
        up = lines[i].upper()
        adj = _adjustment_from(lines[i])
        if not adj:
            continue
        if adj.kind == "discount" and DISCOUNT_SUMMARY.search(up.strip()):
            counted = inline_disc + sum(a.amount for a in adjustments if a.kind == "discount")
            if counted == adj.amount:
                continue  # ringkasan dari diskon yang sudah dihitung
        adjustments.append(adj)

    _resolve_ambiguous(items, adjustments, ambiguous, total if annotate else None)
    if annotate:
        rec = _annotate(items, adjustments, total)
    else:
        _flag_mismatches(items)
        rec = reconcile(items, adjustments, total)
    return items, adjustments, rec


def _resolve_ambiguous(items, adjustments, ambiguous, total) -> None:
    """Baris "diskon" bernominal positif: jadikan barang kalau itu yang membuat
    rincian cocok dengan total; tanpa total yang bisa dipercaya → barang."""
    if not ambiguous:
        return
    if total is not None:
        diff = reconcile(items, adjustments, total).diff
        # Diskon → barang menaikkan perkiraan 2 × nilai.
        pick = [a for a in ambiguous if diff == 2 * a[2]]
        if not pick:
            return
        flip = pick[:1]
        note = "Dibaca sebagai barang (bukan diskon) agar cocok dengan total"
    else:
        flip = ambiguous
        note = None
    for owner, label, value, i, j in flip:
        if isinstance(owner, ReceiptItem):
            owner.discount -= value
        elif owner in adjustments:
            adjustments.remove(owner)
        item = ReceiptItem(name=label, amount=value, read_amount=value, line=i, line_end=j,
                           flag="auto" if note else "ok", note=note)
        items.append(item)
    items.sort(key=lambda it: it.line)


# ── Entry point ─────────────────────────────────────────────────────────────

def parse_receipt(
    raw_lines: list[str],
    today: date | None = None,
    *,
    max_age_days: int = 366,
    ocr_aliases: dict[str, str] | None = None,
    merchant_aliases: dict[str, str] | None = None,
    merchant_profiles: dict[str, list[str]] | None = None,
) -> ReceiptParse:
    """Parse baris OCR. merchant_profiles: {merchant_key: [label total yang dipelajari]}."""
    today = today or date.today()
    lines = [normalize_line(l, ocr_aliases) for l in raw_lines]
    lines = [l for l in lines if l]
    merchant = find_merchant(lines, merchant_aliases)
    learned = (merchant_profiles or {}).get(merchant_key(merchant) or "", [])
    total, conf, evidence, label, total_idx, guess_idx = find_total(lines, learned)
    paid = payment_amounts(lines)
    trusted = guess_idx is None  # total dari baris berlabel / pembayaran, bukan tebakan
    items, adjustments, rec = extract_items(lines, total if trusted else None, total_idx, annotate=trusted)
    source = "payment" if (total is not None and total in paid) else None

    if not trusted:
        # Total = tebakan "nominal terbesar" (tidak ada baris TOTAL yang dikenali).
        guess_item = next((it for it in items if it.line <= guess_idx <= it.line_end), None)
        others = [it for it in items if it is not guess_item]
        if guess_item is not None and others and guess_item is items[-1] \
                and _looks_like_total_label(guess_item.name) \
                and reconcile(others, adjustments, None).expected == guess_item.amount:
            # Baris paling bawah berlabel asing ("BAYAR 50.000") = jumlah barang lain → itu totalnya.
            items.remove(guess_item)
            total, conf, source = guess_item.amount, "rendah", "items"
            evidence = [f'"{lines[guess_idx]}" dianggap total: sama dengan jumlah {len(items)} barang lainnya']
            rec = reconcile(items, adjustments, total)
        elif guess_item is not None and items and rec.expected >= MIN_AMOUNT:
            total, conf, source = rec.expected, "rendah", "items_sum"
            evidence = ["Tidak ada baris TOTAL; total dihitung dari rincian barang"]
            rec = reconcile(items, adjustments, total)
        else:
            rec = reconcile(items, adjustments, total)
            if rec.status == "cocok" and total is not None:
                conf, source = "sedang", "items"
                evidence.append(f"Rincian {len(items)} barang cocok dengan angka total")
    elif total is None:
        if items and rec.expected >= MIN_AMOUNT:
            total, conf, source = rec.expected, "rendah", "items_sum"
            evidence = ["Tidak ada baris TOTAL; total dihitung dari rincian barang"]
            rec = reconcile(items, adjustments, total)
    else:
        # Baris TOTAL sebelum pajak/service ("TOTAL 60.000 / SERVICE / PB1 / DEBIT 69.300").
        if paid and total not in paid and items and total_idx is not None:
            post = charges_between(lines, total_idx + 1, _first_payment_idx(lines, total_idx + 1))
            with_post = rec.expected + sum(a.amount for a in post)
            if post and with_post in paid:
                adjustments.extend(post)
                total, conf, source = with_post, "tinggi", "payment"
                label = None  # total yang dibayar tidak ada di baris berlabel → jangan dipelajari
                evidence.append(f"Rincian + pajak/service = {with_post}, cocok dengan pembayaran")
                rec = reconcile(items, adjustments, total)
        if rec.status == "cocok":
            evidence.append(f"Rincian {len(items)} barang cocok dengan total")
            contradicted = bool(paid) and total not in paid
            weight = 96 if (label and label in learned) else (_line_weight(lines[total_idx]) if total_idx is not None else 0)
            # Pajak/service sesudah baris TOTAL yang tidak terbukti → total itu mungkin
            # sebelum pajak; jangan dinaikkan.
            trailing = charges_between(lines, total_idx + 1, _first_payment_idx(lines, total_idx + 1)) \
                if (total_idx is not None and source != "payment") else []
            if trailing:
                evidence.append("Ada pajak/service sesudah baris TOTAL — cek total yang dibayar")
            # Naik ke "tinggi" hanya untuk baris total akhir (bukan SUBTOTAL/HARGA JUAL)
            # yang tidak dibantah pembayaran.
            if conf != "tinggi" and not contradicted and weight >= 70 and not trailing:
                conf, source = "tinggi", source or "items"
            elif conf != "tinggi" and source == "payment":
                # Tanpa baris TOTAL, tapi Σ rincian = nominal pembayaran → dua sumber sepakat.
                conf = "tinggi"
    return ReceiptParse(
        merchant=merchant,
        date=find_date(lines, today, max_age_days),
        total=total,
        confidence=conf,
        evidence=evidence,
        total_label=label,
        lines=lines,
        items=items,
        adjustments=adjustments,
        reconciliation=rec,
        confidence_source=source,
    )
