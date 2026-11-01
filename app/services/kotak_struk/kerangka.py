"""Kerangka tata letak bukti bayar untuk belajar lintas user (spec 2026-11-01 §3a, §8; pre-flight K1, G1, G2, G4).

Worker menyimpan kerangka ini di kolom `receipt_scans.layout` (bukan di `document`: tidak pernah dikirim ke klien)
supaya koreksi user yang datang belakangan bisa dipetakan ke baris asalnya tanpa menyimpan teks OCR. Kerangka hanya
memuat STRUKTUR:

    {"v": 1, "key": "gopay" | "logo:<kata>", "lines": [
        {"i": 6, "label": "jumlah kirim uang", "kind": "nominal", "amount": 10000},
        {"i": 7, "label": "tanggal", "kind": "tanggal", "date": "2026-10-31"},
        {"i": 3, "label": "ditransfer ke", "kind": "nama", "h": "<HMAC nama ternormalisasi>"},
        {"i": 1, "label": None, "kind": "judul", "words": ["transfer", "berhasil"]}]}

- `i` = indeks baris di `clean_lines(lines)`; paling banyak LAYOUT_MAX_LINES entri, urut `i`.
- Label hanya dari kosakata label (`LABEL_WORDS`), digit diganti `#`, tanpa kata nama pihak lawan/pengirim/user
  (`safe_label`); label lain menjadi None.
- Baris yang memuat nomor rahasia (referensi, rekening, NMID) atau deret >= LONG_DIGITS digit di luar nominal/tanggal
  tidak masuk sama sekali. Nama hanya sebagai HMAC (`merchants.hmac_hex`, kunci `KOTAK_HMAC_KEY`).
- Kata judul hanya kata kosakata (label, status, arah uang, nama aplikasi), tanpa kata nama.
- Hanya `doc_type` di LAYOUT_TYPES (QRIS, transfer, tidak dikenali) dengan kunci aturan (`rule_key`) yang punya
  kerangka; kunci `logo:<kata>` hanya untuk `tidak_dikenali`. Struk belanja tidak pernah punya kerangka.

Semua fungsi murni (tanpa I/O; `hmac_hex` membaca kunci dari konfigurasi).
"""
from __future__ import annotations

import re

from app.services.kotak_struk.config import LAYOUT_LABEL_MAX, LAYOUT_LABEL_WORDS, LAYOUT_MAX_LINES, LAYOUT_TYPES
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.merchants import hmac_hex, normalize_name
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers import transfer as transfer_reader
from app.services.kotak_struk.readers.base import Secrets
from app.services.kotak_struk.readers.labels import _find_date, parse_datetime_id
from app.services.kotak_struk.readers.profiles import (
    GENERIC_LABELS, LOGO_WORDS, MONEY_PROVIDERS, PROFILES, AppProfile, detect_issuer, is_provider_only,
)
from app.services.receipt_parser import amounts_in

LAYOUT_VERSION = 1
HEADER_LINES = 4          # judul hanya dari baris-baris teratas (selaras proof_common.HEADER_LINES)
LOGO_LINES = 3            # kunci logo dari baris-baris teratas (G4)
LOGO_MIN_LETTERS = 3
TITLE_MAX_WORDS = 6
NAME_MAX_WORDS = 6

_EDGE = " \t:：;,.|·•-–—_/\\"           # tanda baca ujung label
_WORD_PUNCT = ".,:;()'\"&/-–!?*•·"       # tanda baca yang dilepas dari kata sebelum dicocokkan

# Kata label kurasi (G2), di luar kata dari GENERIC_LABELS dan label profil aplikasi.
_CURATED = (
    "jumlah kirim uang bayar pembayaran total nominal transfer ke dari tujuan penerima nama merchant toko tanggal waktu "
    "selesai transaksi biaya admin layanan saldo terpakai dibayar debit sumber metode jenis keterangan catatan tagihan "
    "harga subtotal amount date time paid payment recipient to from name rp idr qris"
)


def _mask_digits(text: str) -> str:
    return re.sub(r"\d", "#", text)


def _word(w: str) -> str:
    return w.strip(_WORD_PUNCT).lower()


def _words(text: str) -> list[str]:
    return [w for w in (_word(x) for x in text.split()) if w]


def _label_words() -> frozenset[str]:
    labels = [label for labels in GENERIC_LABELS.values() for label in labels]
    labels += [label for profile in PROFILES for labels in profile.labels.values() for label in labels]
    return frozenset(w for text in [*labels, _CURATED] for w in _words(_mask_digits(text)))


LABEL_WORDS: frozenset[str] = _label_words()

# Kata yang boleh tersimpan di judul: kosakata label, kata status dan arah uang, nama aplikasi/bank. Kata lain (bisa nama
# orang yang tidak terbaca sebagai pihak lawan) dibuang.
_TITLE_EXTRA = (
    "berhasil sukses successful success gagal failed tidak belum pending diproses processing dibatalkan ditolak batal "
    "rejected cancelled canceled void top up isi dana masuk keluar terima diterima terkirim kembali refund pengiriman "
    "penarikan setoran pembelian purchase withdrawal deposit transaction rekening anda telah sedang"
)
TITLE_WORDS: frozenset[str] = (LABEL_WORDS | frozenset(_TITLE_EXTRA.split()) | frozenset(LOGO_WORDS)
                               | frozenset(MONEY_PROVIDERS) | frozenset(m for p in PROFILES for m in p.markers))

# Semua label yang dikenal, terpanjang dulu: pemisah label dan nilai dalam satu baris ("Ditransfer ke Budi").
_KNOWN_LABELS = sorted({label.lower() for labels in GENERIC_LABELS.values() for label in labels}
                       | {label.lower() for p in PROFILES for labels in p.labels.values() for label in labels},
                       key=len, reverse=True)
_KNOWN_LABEL = re.compile(
    r"^\s*(?:" + "|".join(r"\s+".join(re.escape(part) for part in label.split()) for label in _KNOWN_LABELS)
    + r")(?=$|[\s:：])", re.IGNORECASE)

# Nominal dan bagian tanggal tidak dihitung sebagai deret angka panjang (Rp1.500.000 = 7 digit).
_MONEY_TOKEN = re.compile(r"(?:rp|idr)\.?\s*\d{1,8}(?:[.,]\d{3})*(?:,\d{2})?(?!\d)"
                          r"|(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?:,\d{2})?(?![\d])", re.IGNORECASE)
_MONEY_START = re.compile(r"(?:rp|idr)\.?\s*\d|(?<![A-Za-z])\d", re.IGNORECASE)
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z.'&\-,]*")
_TEXT_LINE = re.compile(r"[A-Za-z]{4,}")   # baris yang memuat kata; bilah status ("10:57", "LTE", panah) tidak
# Nomor tersamar ("…4821", "*********2096", "0123****4567", "…K2NW", "xxxx1234"): ekor rekening/PAN/referensi, bukan nominal.
_MASKED_NUMBER = re.compile(r"[*•…]+\s*[A-Za-z]{0,2}\d|\d\s*[*•…]{2,}|(?<![A-Za-z])[xX]{3,}\d")


# ── label ───────────────────────────────────────────────────────────────────

def safe_label(text: str | None, *, forbidden_words: set[str]) -> str | None:
    """Label yang aman dibagikan: huruf kecil, spasi dirapatkan, titik dua/tanda baca ujung dibuang, digit -> `#`.
    None bila kosong, > LAYOUT_LABEL_MAX karakter, > LAYOUT_LABEL_WORDS kata, ada kata di luar `LABEL_WORDS` (token
    yang hanya `#` boleh), ada kata di `forbidden_words` (kata nama pihak lawan/pengirim/user), atau tanpa satu kata pun.
    Label yang memuat `#` boleh disimpan di kerangka tapi tidak pernah menjadi suara (L2)."""
    if not text:
        return None
    label = " ".join(_mask_digits(text).lower().split()).strip(_EDGE)
    label = " ".join(label.split())
    if not label or len(label) > LAYOUT_LABEL_MAX:
        return None
    tokens = label.split()
    if len(tokens) > LAYOUT_LABEL_WORDS:
        return None
    has_word = False
    for token in tokens:
        word = _word(token)
        if not word:
            continue
        if "#" in word and re.fullmatch(r"[#.,:/\-]+", word):
            continue
        if word not in LABEL_WORDS or word in forbidden_words:
            return None
        has_word = True
    return label if has_word else None


# ── kunci aturan ────────────────────────────────────────────────────────────

def _is_status(text: str) -> bool:
    return bool(pc._classify(text) or pc._STATUS_TITLE.search(text)
                or transfer_reader._TOP_UP.search(text) or transfer_reader._INCOMING.search(text))


def rule_key(lines: list[str], profile: AppProfile | None, *, forbidden_words: set[str]) -> str | None:
    """Kunci aturan (G4): `profile.key` bila aplikasinya dikenal. Selain itu `logo:<kata>` dari baris logo: baris pertama
    di antara LOGO_LINES baris bersih teratas yang 1-2 kata, hanya huruf, >= 3 huruf, bukan label/kata status/kata
    `LABEL_WORDS`, dan bukan kata `forbidden_words`; huruf kecil, <= LAYOUT_LABEL_MAX. Baris di atasnya hanya boleh bilah
    status (tanpa kata >= 4 huruf): logo selalu di atas, dan baris teks di bawah judul bisa nama orang. Selain itu None
    (tanpa kerangka dan tanpa suara)."""
    if profile is not None:
        return profile.key
    for line in pc.clean_lines(lines)[:LOGO_LINES]:
        words = line.split()
        candidate = (1 <= len(words) <= 2 and all(w.isascii() and w.isalpha() for w in words)
                     and sum(len(w) for w in words) >= LOGO_MIN_LETTERS)
        if candidate:
            lowered = [w.lower() for w in words]
            key = " ".join(lowered)
            if (len(key) <= LAYOUT_LABEL_MAX and not pc.is_label_line(line) and not _is_status(line)
                    and not set(lowered) & (LABEL_WORDS | forbidden_words)):
                return f"logo:{key}"
        if _TEXT_LINE.search(line):
            return None   # baris teks pertama bukan logo: tidak ada logo
    return None


# ── baris ───────────────────────────────────────────────────────────────────

def _secret_line(line: str, secrets: Secrets) -> bool:
    """Baris memuat nilai rahasia (referensi, rekening, NMID), nomor tersamar, atau deret >= LONG_DIGITS digit di luar
    nominal/tanggal."""
    if _MASKED_NUMBER.search(line):
        return True
    digits = re.sub(r"\D", "", line)
    for value in (*secrets.ref_values, secrets.account_number, secrets.nmid):
        value = (value or "").strip()
        if not value:
            continue
        if len(value) >= 4 and value.lower() in line.lower():
            return True
        value_digits = re.sub(r"\D", "", value)
        if len(value_digits) >= pc.LONG_DIGITS and value_digits in digits:
            return True
    rest = line
    found = _find_date(rest)
    if found:
        rest = rest[:found[0]] + " " + rest[found[1]:]
    rest = _MONEY_TOKEN.sub(" ", rest)
    return bool(pc.split_long_numbers(rest)[1])


def _name_value(value: str) -> str | None:
    """Nilai berbentuk nama: 1-6 kata huruf (boleh `.'&-,`), tanpa digit, bukan kata status, bukan label saja, bukan
    nama bank/e-wallet saja. None bila bukan."""
    value = " ".join(value.split()).strip(_EDGE)
    words = value.split()
    if not 1 <= len(words) <= NAME_MAX_WORDS or not all(_NAME_WORD.fullmatch(w) for w in words):
        return None
    if all(_word(w) in LABEL_WORDS for w in words if _word(w)) or _is_status(value) or is_provider_only(value):
        return None
    return value if normalize_name(value) else None


def _split_label(line: str) -> tuple[str | None, str]:
    """(teks label, nilai) dalam satu baris: titik dua, label yang dikenal, atau awalan kata label ("Dibayar ke TOKO").
    Tanpa label: (None, baris)."""
    m = re.search(r"[:：]", line)
    if m:
        return line[:m.start()], line[m.end():]
    m = _KNOWN_LABEL.match(line)
    if m and line[m.end():].strip():
        return line[:m.end()], line[m.end():]
    words = line.split()
    head = 0
    for i, w in enumerate(words[:-1]):
        if _word(w) not in LABEL_WORDS:
            break
        # Nilai huruf besar sesudah label huruf campuran ("Dibayar ke TOKO MAJU"): "TOKO" milik nilainya.
        if i and not words[0].isupper() and len(w) > 1 and w.isupper():
            break
        head = i + 1
    if head:
        return " ".join(words[:head]), " ".join(words[head:])
    return None, line


def _label_only(line: str | None, forbidden_words: set[str]) -> str | None:
    """Label baris yang berdiri sendiri (tanpa digit), untuk nilai di baris bawahnya."""
    if not line or re.search(r"\d", line):
        return None
    return safe_label(line, forbidden_words=forbidden_words)


def _forbidden_words(lines: list[str], doc: DokumenBayar, profile: AppProfile | None, user_name: str | None) -> set[str]:
    """Kata nama pihak lawan (dokumen, dan yang dibaca pembaca bukti dari baris berlabel), pengirim, dan user."""
    names = [doc.counterparty.name, pc.read_sender_name(lines, profile), user_name]
    try:
        names.append(pc.read_name(pc.body_lines(lines), profile, "merchant"))
    except Exception:   # pembaca nama hanya tambahan pengaman
        pass
    return {w for name in names for w in normalize_name(name).split()}


def _entry(i: int, line: str, prev: str | None, forbidden: set[str]) -> dict | None:
    def label_of(text: str | None) -> str | None:
        text = (text or "").strip(_EDGE)
        if text:
            return safe_label(text, forbidden_words=forbidden)
        return _label_only(prev, forbidden)

    found = _find_date(line)
    if found:
        paid = parse_datetime_id(line)
        if paid is not None:
            return {"i": i, "label": label_of(line[:found[0]]), "kind": "tanggal", "date": paid.date().isoformat()}
    m = _MONEY_START.search(line)
    if m:
        amounts = amounts_in(line[m.start():])
        if amounts:
            return {"i": i, "label": label_of(line[:m.start()]), "kind": "nominal", "amount": int(amounts[0])}
    if i < HEADER_LINES and (pc._STATUS_TITLE.search(line) or transfer_reader._TOP_UP.search(line)
                             or transfer_reader._INCOMING.search(line)):
        words = [w for w in re.findall(r"[a-z]+", line.lower()) if w in TITLE_WORDS and w not in forbidden]
        if words:
            return {"i": i, "label": None, "kind": "judul", "words": words[:TITLE_MAX_WORDS]}
        return None
    label_text, value = _split_label(line)
    name = _name_value(value)
    if name is None:
        return None
    label = safe_label(label_text, forbidden_words=forbidden) if label_text else _label_only(prev, forbidden)
    return {"i": i, "label": label, "kind": "nama", "h": hmac_hex(normalize_name(name))}


def _profile_of(doc: DokumenBayar, lines: list[str]) -> AppProfile | None:
    if doc.issuer:
        known = next((p for p in PROFILES if p.key == doc.issuer), None)
        if known is not None:
            return known
    return detect_issuer(lines)


def build_layout(lines: list[str], doc: DokumenBayar, secrets: Secrets, *, user_name: str | None) -> dict | None:
    """Kerangka aman satu bukti (lihat docstring modul). None bila `doc.doc_type` bukan LAYOUT_TYPES, tanpa kunci aturan,
    atau berkunci logo padahal bukan `tidak_dikenali`. `lines` = baris OCR mentah (`TextDoc.lines`); `doc`/`secrets` = hasil pembaca SEBELUM disamarkan worker."""
    if doc.doc_type not in LAYOUT_TYPES:
        return None
    clean = pc.clean_lines(lines)
    profile = _profile_of(doc, clean)
    forbidden = _forbidden_words(clean, doc, profile, user_name)
    key = rule_key(clean, profile, forbidden_words=forbidden)
    # Kunci logo hanya untuk bukti tak dikenal (spec §2): QRIS/transfer tanpa profil aplikasi sering diawali nama merchant,
    # dan nama merchant tidak pernah dipelajari lintas user.
    if key is None or (key.startswith("logo:") and doc.doc_type != "tidak_dikenali"):
        return None
    logo_line = None if profile is not None else next(
        (i for i, line in enumerate(clean[:LOGO_LINES]) if f"logo:{line.lower()}" == key), None)
    entries = []
    for i, line in enumerate(clean):
        if len(entries) >= LAYOUT_MAX_LINES:
            break
        if i == logo_line or _secret_line(line, secrets):
            continue
        entry = _entry(i, line, clean[i - 1] if i else None, forbidden)
        if entry is not None:
            entries.append(entry)
    return {"v": LAYOUT_VERSION, "key": key, "lines": entries}
