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
CASH_KEYS = re.compile(r"TUNAI|CASH|UANG\s*DITERIMA|DIBAYAR")
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
class ReceiptParse:
    merchant: str | None
    date: date | None
    total: int | None
    confidence: str  # tinggi | sedang | rendah | gagal
    evidence: list[str] = field(default_factory=list)
    total_label: str | None = None  # label baris yang dipakai (untuk belajar)
    lines: list[str] = field(default_factory=list)


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
    # Token mirip angka (diawali digit): "5O.4OO" → "50.400".
    line = re.sub(
        r"(^|[\s:=(])(\d[0-9OolI|S$B.,:/-]+)(?=$|[\s)])",
        lambda m: m.group(1) + m.group(2).translate(_DIGITISH),
        line,
    )
    line = re.sub(r"[A-Za-z0-9]+", lambda m: _exact_alias(m.group(0), aliases), line)
    line = _LABEL_WORD.sub(lambda m: _fuzzy_keyword(m.group(1)), line)
    return re.sub(r"\s+", " ", line).strip()


# ── Nominal ─────────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"(?:RP\.?\s*)?(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{2}))?(?!\d)", re.I)


def amounts_in(line: str) -> list[int]:
    """Semua nominal rupiah wajar di satu baris ("35.000", "35,000", "35000", "Rp 35.000,00")."""
    out = []
    for m in _AMOUNT_RE.finditer(line):
        raw = m.group(1)
        before = line[m.start() - 1:m.start()] if m.start() > 0 else ""
        after = line[m.end():m.end() + 1]
        if before in ("/", "-") or before.isalpha() or after in ("/", ":"):
            continue  # bagian tanggal/jam/kode: 14.10.26-19:21/3.0.27/THTV-363626
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


def _payments(lines: list[str]):
    """(tunai, kembali, [non-tunai]) — masing-masing (nilai, baris) atau None."""
    cash = change = None
    cards: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        up = line.upper()
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

    def result(value, conf, line=None):
        if line:
            evidence.insert(0, f'Baris "{line}" → {value}')
        return value, conf, evidence, (_label_of(line) if line else None)

    # 1) Kandidat yang dikonfirmasi pembayaran = keyakinan tinggi.
    for w, _, value, line in candidates:
        if value in confirmations:
            return result(value, "tinggi", line)

    # 2) Kandidat terbaik, diturunkan kalau bertentangan dengan pembayaran.
    if candidates:
        w, _, value, line = candidates[0]
        contradicted = exact is not None or bool(card_values)
        if contradicted:
            evidence.append("Total tidak cocok dengan pembayaran — mohon dicek")
            return result(value, "rendah", line)
        return result(value, "sedang" if w >= 70 else "rendah", line)

    # 3) Tanpa baris TOTAL: pakai pembayaran.
    if exact is not None:
        return result(exact, "sedang")
    if card_values:
        return result(card_values[-1], "sedang")
    if pas is not None:  # bisa jadi uang yang diserahkan, bukan total
        return result(pas, "rendah")

    biggest = None
    for line in lines:
        up = line.upper()
        if CASH_KEYS.search(up) or _skip_line(up):
            continue
        for v in amounts_in(line):
            if biggest is None or v > biggest[0]:
                biggest = (v, line)
    if biggest:
        evidence.append(f'Tidak ada kata TOTAL; pakai nominal terbesar "{biggest[1]}"')
        return result(biggest[0], "rendah")
    return None, "gagal", ["Tidak ada nominal yang terbaca"], None


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
    total, conf, evidence, label = find_total(lines, learned)
    return ReceiptParse(
        merchant=merchant,
        date=find_date(lines, today, max_age_days),
        total=total,
        confidence=conf,
        evidence=evidence,
        total_label=label,
        lines=lines,
    )
