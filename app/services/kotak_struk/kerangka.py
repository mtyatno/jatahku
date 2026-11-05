"""Kerangka tata letak bukti bayar untuk belajar lintas user (spec 2026-11-01 §3a, §8; pre-flight K1, G1, G2, G4).

Worker menyimpan kerangka ini di kolom `receipt_scans.layout` (bukan di `document`: tidak pernah dikirim ke klien)
supaya koreksi user yang datang belakangan bisa dipetakan ke baris asalnya tanpa menyimpan teks OCR. Kerangka hanya
memuat STRUKTUR:

    {"v": 1, "key": "gopay", "lines": [
        {"i": 6, "label": "jumlah kirim uang", "kind": "nominal", "amount": 10000},
        {"i": 7, "label": "tanggal", "kind": "tanggal", "date": "2026-10-31"},
        {"i": 3, "label": "ditransfer ke", "kind": "nama", "h": "<HMAC nama ternormalisasi>"},
        {"i": 1, "label": None, "kind": "judul", "words": ["transfer", "berhasil"]}],
     "arah": []}

- `i` = indeks baris di `clean_lines(lines)`; paling banyak LAYOUT_MAX_LINES entri, urut `i`.
- Label hanya dari kosakata label (`LABEL_WORDS`), digit diganti `#`, tanpa kata nama pihak lawan/pengirim/user
  (`safe_label`); label lain menjadi None.
- Baris yang memuat nomor rahasia (referensi, rekening, NMID), nomor tersamar, atau deret >= LONG_DIGITS digit di luar
  nominal/tanggal tidak masuk sama sekali. Nama hanya sebagai HMAC (`merchants.hmac_hex`, kunci `KOTAK_HMAC_KEY`).
- `nominal` hanya dari token uang yang rapi (awalan Rp/IDR, atau ribuan bertitik tanpa nol di depan; angka polos
  >= 1000 hanya di bawah label uang) dan tidak pernah di bawah label nomor (rekening, no, ref, id, NPWP, VA, HP, ...)
  atau di baris alamat: nomor berbentuk angka tidak pernah tersimpan sebagai nominal.
- Kata judul hanya kata kosakata (label, status, arah uang, nama aplikasi), tanpa kata nama.
- `arah` (tahap 2 M3a, `arah_tokens`): token arah uang untuk suara/aturan `arah`, hanya kosakata: `judul:<kata judul
  tanpa kata status>` dan `ke:<kata terdepan penerima: penyedia + kata top-up>` ("ke:gopay topu"); daftar, boleh kosong.
- Hanya `doc_type` di LAYOUT_TYPES (QRIS, transfer, tidak dikenali) dengan kunci aturan (`rule_key`) yang punya
  kerangka: kunci profil aplikasi yang dikenal, atau (tahap 2, `LOGO_KEYS`, hanya `tidak_dikenali`) kunci
  `logo:<kata>` dari baris logo aplikasi tak dikenal. Baris teratas bukti tak dikenal bisa nama orang atau merchant
  (review L1 I-1), jadi kandidatnya ketat (`logo_candidate`, pre-flight A16 K8: satu kata, atau dua kata hanya bila
  salah satunya kata logo/penyedia: "Bank Raya", bukan "Siti Aminah"), dan suara `logo` ditolak bila katanya nama yang
  dikenal (`belajar.learn_app_choice`). Struk belanja tidak pernah punya kerangka.

Batas yang diketahui (spec §8; dicatat untuk dokumen L7): kata nama yang KEBETULAN juga kata kosakata ("Dana", "Mega",
"Toko", "Admin") bisa bertahan di label atau judul bila pembaca tidak membaca nama itu sebagai pihak lawan/pengirim
(mis. pengirim "DANA PRATAMA" dianggap nama penyedia). Yang bocor paling banyak satu kata umum yang tidak mengenali
siapa pun; nama utuh, nomor, dan kata di luar kosakata tidak pernah tersimpan.

Semua fungsi murni (tanpa I/O; `hmac_hex` membaca kunci dari konfigurasi).
"""
from __future__ import annotations

import re

from app.services.kotak_struk.config import (
    KEY_MAX, LAYOUT_LABEL_MAX, LAYOUT_LABEL_WORDS, LAYOUT_MAX_LINES, LAYOUT_TYPES,
)
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.merchants import hmac_hex, normalize_name
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers import transfer as transfer_reader
from app.services.kotak_struk.readers.base import Secrets
from app.services.kotak_struk.readers.labels import find_date, parse_datetime_id
from app.services.kotak_struk.readers.profiles import (
    GENERIC_LABELS, LOGO_WORDS, MONEY_PROVIDERS, PROFILES, AppProfile, detect_issuer, is_provider_only,
)
from app.services.receipt_parser import amounts_in

LAYOUT_VERSION = 1
HEADER_LINES = 4          # judul hanya dari baris-baris teratas (selaras proof_common.HEADER_LINES)
LOGO_KEYS = True          # tahap 2 (M2a): kunci `logo:<kata>` untuk bukti tak dikenal, kandidat ketat (K8)
LOGO_LINES = 3            # kunci logo dari baris-baris teratas (G4)
LOGO_MIN_LETTERS = 3
LOGO_PREFIX = "logo:"
LOGO_MAX_WORDS = 2
# Kata yang membuat kandidat DUA kata sah: kata pendamping logo dan nama penyedia ("Bank Raya", "Kilat Syariah").
LOGO_COMPANIONS: frozenset[str] = frozenset(LOGO_WORDS) | frozenset(MONEY_PROVIDERS)
TITLE_MAX_WORDS = 6
NAME_MAX_WORDS = 6

_EDGE = " \t:：;,.|·•-–—_/\\"           # tanda baca ujung label
_WORD_PUNCT = ".,:;()'\"&/-–!?*•·"       # tanda baca yang dilepas dari kata sebelum dicocokkan

# Kata label kurasi (G2), di luar kata dari GENERIC_LABELS dan label profil aplikasi. "kepada" dan "atas" (label penerima
# "Kepada" dan "Atas Nama"; pre-flight A16 L2 R-2): label "Kepada" kini bisa menjadi suara `label_pihak`; "Atas Nama"
# masuk kerangka tetapi bukan label penerima (`belajar._party_label`: "nama" lemah, "atas" bukan kata penerima).
_CURATED = (
    "jumlah kirim uang bayar pembayaran total nominal transfer ke dari tujuan penerima nama merchant toko tanggal waktu "
    "selesai transaksi biaya admin layanan saldo terpakai dibayar debit sumber metode jenis keterangan catatan tagihan "
    "harga subtotal amount date time paid payment recipient to from name rp idr qris kepada atas"
)


def _mask_digits(text: str) -> str:
    return re.sub(r"\d", "#", text)


def _word(w: str) -> str:
    return w.strip(_WORD_PUNCT).lower()


def words(text: str) -> list[str]:
    """Kata huruf kecil tanpa tanda baca tepi, seperti yang dicocokkan `safe_label` (juga dipakai peringatan Admin)."""
    return [w for w in (_word(x) for x in text.split()) if w]


_words = words   # alias lama; nama publiknya `words` (pre-flight A16 n-1)


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

# Token uang yang rapi: awalan Rp/IDR (ribuan bertitik/berkoma atau angka polos <= 8 digit, tanpa nol di depan), atau
# ribuan bertitik tanpa awalan ("15.000"). Pengelompokan janggal ("012.345.678.9", "5.123.4567") bukan uang: menjadi
# deret angka panjang dan barisnya dibuang. Nominal dan tanggal tidak dihitung sebagai deret panjang (Rp1.500.000).
_MONEY = re.compile(
    r"(?:(?<![A-Za-z])(?:rp|idr)\.?\s*(?:(?!0)\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|(?!0)\d{1,8}(?:[.,]\d{2})?|0)"
    r"|(?<![\d.,])(?!0)\d{1,3}(?:\.\d{3})+(?:,\d{2})?)(?![\d]|[.,]\d)", re.IGNORECASE)
# Angka polos >= 1000 tanpa pemisah: nominal hanya bila labelnya label uang (`_MONEY_WORDS`).
_BARE = re.compile(r"(?<![\d.,])(?!0)\d{4,8}(?![\d]|[.,]\d)")
_MONEY_WORDS = frozenset(
    "nominal jumlah total bayar dibayar pembayaran biaya admin harga subtotal amount tagihan saldo terpakai fee layanan "
    "diskon potongan promo voucher pajak ppn tax discount tips tip ongkir donasi debit paid payment".split())
# Label nomor: angka di bawah/di samping label ini adalah nomor (rekening, referensi, pelanggan, HP, ...), bukan nominal.
_ID_LABEL = re.compile(
    r"(?<![A-Za-z])(?:rek|rekening|no|nomor|ref|referensi|npwp|nmid|nik|id|va|virtual|kode|pos|telp|telepon|hp|phone|"
    r"terminal|pan|rrn|order|sn|trx|akun|account|kartu|card|pelanggan|resi|invoice)(?![A-Za-z])", re.IGNORECASE)
# Baris alamat (kode pos, nomor rumah): tidak pernah nominal.
_ADDRESS = re.compile(
    r"(?<![A-Za-z])(?:jl|jln|jalan|kel|kelurahan|kec|kecamatan|kab|kabupaten|kota|rt|rw|lantai|lt|blok|gedung|tower|"
    r"komplek|perumahan|desa)(?![A-Za-z])", re.IGNORECASE)
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
    return bool(pc.classify_status(text) or pc.STATUS_TITLE.search(text)
                or transfer_reader.TOP_UP.search(text) or transfer_reader.INCOMING.search(text))


def logo_candidate(words: list[str]) -> bool:
    """Kata-kata (huruf kecil) sebuah baris logo boleh menjadi kunci `logo:` (pre-flight A16 K8): 1-2 kata, hanya huruf
    ASCII, bersama >= LOGO_MIN_LETTERS huruf, <= LAYOUT_LABEL_MAX karakter; satu kata, atau dua kata hanya bila salah
    satunya kata logo/penyedia (`LOGO_COMPANIONS`: "bank raya" ya, "siti aminah" tidak); paling sedikit satu kata di luar
    kata pendamping logo (`LOGO_WORDS`: "bank digital", "mobile" bukan nama aplikasi); tidak ada kata `LABEL_WORDS`
    (baris label pasti memuatnya) kecuali kata pendamping/penyedia itu ("bank"); dan bukan kata status. Nama satu kata
    ("Bambang") lolos di sini: ditolak oleh `forbidden_words` saat membuat kerangka dan oleh pemeriksaan nama saat
    suara `logo` (`belajar.learn_app_choice`)."""
    if not 1 <= len(words) <= LOGO_MAX_WORDS or not all(w.isascii() and w.isalpha() and w == w.lower() for w in words):
        return False
    text = " ".join(words)
    if sum(len(w) for w in words) < LOGO_MIN_LETTERS or len(text) > LAYOUT_LABEL_MAX:
        return False
    if len(words) == 2 and not set(words) & LOGO_COMPANIONS:
        return False
    if all(w in LOGO_WORDS for w in words) or set(words) & (LABEL_WORDS - LOGO_COMPANIONS):
        return False
    return not _is_status(text)


def logo_word(key) -> str | None:
    """Kata logo kunci `logo:<kata>` ("logo:newpay" -> "newpay"), hanya bila bentuknya kandidat yang sah
    (`logo_candidate`, huruf kecil, satu spasi, <= KEY_MAX). Kunci profil, kunci rusak, dan selain teks: None."""
    if not isinstance(key, str) or not key.startswith(LOGO_PREFIX) or len(key) > KEY_MAX:
        return None
    word = key[len(LOGO_PREFIX):]
    words = word.split(" ")
    return word if logo_candidate(words) else None


def rule_key(lines: list[str], profile: AppProfile | None, *, forbidden_words: set[str],
             allow_logo: bool = True) -> str | None:
    """Kunci aturan (G4): `profile.key` bila aplikasinya dikenal. Selain itu (hanya dengan `LOGO_KEYS` dan
    `allow_logo`) `logo:<kata>` dari baris logo: baris pertama di antara LOGO_LINES baris bersih teratas yang kata-katanya
    (huruf kecil) lolos `logo_candidate` dan tanpa kata `forbidden_words`. Baris di atasnya hanya boleh bilah status
    (tanpa kata >= 4 huruf): logo selalu di atas, dan baris teks di bawah judul bisa nama orang. Kandidat SATU kata juga
    ditolak bila baris isi berikutnya (bilah status dilewati) baris nominal atau tanggal (`_after_name`, review M2a
    temuan 1): logo aplikasi diikuti judul ("Transfer Berhasil", "Detail Transaksi"), nama penerima besar diikuti
    nominalnya. Selain itu None (tanpa kerangka dan tanpa suara). Pembaca QRIS/transfer memanggilnya tanpa kunci logo
    (`profiles.learned_profile`)."""
    if profile is not None:
        return profile.key
    if not (LOGO_KEYS and allow_logo):
        return None
    clean = pc.clean_lines(lines)
    for i, line in enumerate(clean[:LOGO_LINES]):
        lowered = [w.lower() for w in line.split()]
        if (logo_candidate(lowered) and not _is_status(line) and not set(lowered) & forbidden_words
                and not (len(lowered) == 1 and _after_name(clean[i + 1:]))):
            return LOGO_PREFIX + " ".join(lowered)
        if _TEXT_LINE.search(line):
            return None   # baris teks pertama bukan logo: tidak ada logo
    return None


def _after_name(rest: list[str]) -> bool:
    """Baris isi pertama di `rest` (bilah status seperti "09:41", "LTE", panah dilewati) adalah baris nominal atau
    tanggal: kata tunggal di atasnya lebih mungkin nama penerima daripada logo aplikasi (harga yang diterima: logo
    aplikasi yang langsung diikuti nominal tidak berkunci)."""
    for line in rest:
        if _MONEY.search(line) or find_date(line):
            return True
        if _TEXT_LINE.search(line):
            return False
    return False


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
    found = find_date(rest)
    if found:
        rest = rest[:found[0]] + " " + rest[found[1]:]
    rest = _MONEY.sub(" ", rest)
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

    found = find_date(line)
    if found:
        paid = parse_datetime_id(line)
        if paid is not None:
            return {"i": i, "label": label_of(line[:found[0]]), "kind": "tanggal", "date": paid.date().isoformat()}
    if not _ADDRESS.search(line):
        m, bare = _MONEY.search(line), False
        if m is None:
            m, bare = _BARE.search(line), True
        amounts = amounts_in(m.group(0)) if m else []
        if amounts:
            head = line[:m.start()]
            if _ID_LABEL.search(head) or (not head.strip(_EDGE) and prev and not re.search(r"\d", prev)
                                          and _ID_LABEL.search(prev)):
                return None   # nomor berlabel (rekening, referensi, pelanggan, ...), bukan nominal
            label = label_of(head)
            if not bare or (label and set(_words(label)) & _MONEY_WORDS):
                return {"i": i, "label": label, "kind": "nominal", "amount": int(amounts[0])}
    if i < HEADER_LINES and (pc.STATUS_TITLE.search(line) or transfer_reader.TOP_UP.search(line)
                             or transfer_reader.INCOMING.search(line)):
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


# ── token arah uang (tahap 2 M3a; spec §2 baris `arah`, pre-flight A16 §4, K9) ─────────────────────────────

# Kata top-up di nama penerima ("GOPAY TOPU-SXXXX" pada bukti ShopeePay, "OVO Top Up ...") dan di judul.
TOP_UP_WORDS: frozenset[str] = frozenset({"top", "up", "topup", "topu", "isi", "saldo", "deposit", "reload"})
# Kata penerima yang boleh menjadi token `ke:`: nama penyedia (bank/e-wallet), kata penanda profil aplikasi, dan kata
# top-up. Kata penanda berhuruf < 3 ("m" dari "m-bca") tidak.
ARAH_PARTY_WORDS: frozenset[str] = (
    frozenset(MONEY_PROVIDERS)
    | frozenset(w for p in PROFILES for m in p.markers for w in re.findall(r"[a-z]+", m) if len(w) >= 3)
    | TOP_UP_WORDS)
# Kata judul yang terlalu umum untuk membedakan arah uang: judul yang hanya memuat kata ini tidak memberi token. Termasuk
# kata label kolom (review M3a temuan 1: "Penerima Transfer ...", "Tujuan Transfer", "Pembayaran Tagihan" bukan arah
# uang), juga kata lokasi ("kota", "lokasi", "location"; review M3a nit: "Kirim Uang ke Toko Kota"). Kata arah (top,
# up, isi, saldo, masuk, terima, setoran, penarikan, refund, deposit) dan nama penyedia tidak.
ARAH_GENERIC: frozenset[str] = frozenset(
    "transfer pembayaran bayar transaksi payment transaction kirim uang ke dari qris nominal total rekening "
    "penerima pengirim tujuan kepada nama name recipient atas asal sumber tagihan merchant toko jumlah status "
    "keterangan catatan berita tanggal waktu jam pukul nomor no id ref referensi biaya admin kota lokasi location"
    .split())
# Kata status di judul (dibuang dari token `judul:`): status bukan arah uang ("Transfer Berhasil" -> tanpa token).
ARAH_STATUS_WORDS: frozenset[str] = (
    frozenset(w for w in TITLE_WORDS if pc.classify_status(w))
    | frozenset({"berhasil", "sukses", "success", "successful", "gagal", "failed", "tidak", "belum", "pending",
                 "diproses", "processing", "dibatalkan", "ditolak", "batal", "rejected", "cancelled", "canceled",
                 "void", "telah", "sedang", "selesai"}))
ARAH_JUDUL = "judul:"
ARAH_KE = "ke:"
ARAH_KE_MAX_WORDS = 3
ARAH_KE_MIN_WORDS = 2
_ARAH_PROVIDER_WORDS = ARAH_PARTY_WORDS - TOP_UP_WORDS


_ARAH_WORD = re.compile(r"[a-z]+")


def _plain_words(words: list[str]) -> bool:
    """Kata huruf kecil ASCII saja (tanpa "#", "-", digit) dan tanpa kata berulang (review M3a temuan 2)."""
    return all(_ARAH_WORD.fullmatch(w) for w in words) and len(set(words)) == len(words)


def _judul_ok(words: list[str]) -> bool:
    return (1 <= len(words) <= TITLE_MAX_WORDS and _plain_words(words)
            and all(w in TITLE_WORDS and w not in ARAH_STATUS_WORDS for w in words)
            and any(w not in ARAH_GENERIC for w in words))


def _ke_ok(words: list[str]) -> bool:
    return (ARAH_KE_MIN_WORDS <= len(words) <= ARAH_KE_MAX_WORDS and _plain_words(words)
            and all(w in ARAH_PARTY_WORDS for w in words)
            and any(w in TOP_UP_WORDS for w in words) and any(w in _ARAH_PROVIDER_WORDS for w in words))


def arah_token_ok(token) -> bool:
    """Token arah berbentuk sah (pagar kedua untuk suara): `judul:<kata>` (1-6 kata judul kosakata, tanpa kata status,
    paling sedikit satu kata di luar ARAH_GENERIC) atau `ke:<kata>` (2-3 kata ARAH_PARTY_WORDS, paling sedikit satu
    kata penyedia/penanda dan satu kata TOP_UP_WORDS); huruf kecil, satu spasi. Selain itu (teks lain, kata nama,
    digit) False."""
    if not isinstance(token, str):
        return False
    for prefix, ok in ((ARAH_JUDUL, _judul_ok), (ARAH_KE, _ke_ok)):
        if token.startswith(prefix):
            words = token[len(prefix):].split(" ")
            return ok(words)
    return False


def _judul_token(clean: list[str], forbidden: set[str]) -> str | None:
    """Token `judul:` dari entri judul kerangka (baris judul status/top-up/uang masuk di HEADER_LINES baris teratas,
    kata kosakata `TITLE_WORDS` tanpa kata nama), tanpa kata status; None bila tidak ada atau hanya kata umum."""
    for i, line in enumerate(clean[:HEADER_LINES]):
        entry = _entry(i, line, clean[i - 1] if i else None, forbidden)
        if entry is not None and entry["kind"] == "judul":
            words = [w for w in entry["words"] if w not in ARAH_STATUS_WORDS]
            return ARAH_JUDUL + " ".join(words) if _judul_ok(words) else None
    return None


def _ke_token(name: str | None) -> str | None:
    """Token `ke:` dari kata TERDEPAN nama penerima selama kata itu ARAH_PARTY_WORDS (paling banyak 3; kata lain,
    termasuk yang memuat digit, menghentikannya): "GOPAY TOPU-SXXXX Axxxxxxx" -> "ke:gopay topu". Nama orang yang
    diawali/bergabung dengan nama penyedia ("Shopeepaysitxx Amixxxxx", "GOPAY SITI AMINAH") tidak pernah memberi
    token: kata nama bukan kosakata, dan tanpa kata top-up tidak ada token."""
    words: list[str] = []
    for w in re.findall(r"[a-z0-9]+", (name or "").lower()):
        if w not in ARAH_PARTY_WORDS or len(words) == ARAH_KE_MAX_WORDS:
            break
        words.append(w)
    return ARAH_KE + " ".join(words) if _ke_ok(words) else None


def arah_tokens(lines: list[str], doc: DokumenBayar) -> list[str]:
    """Token arah uang satu bukti (kerangka `"arah"`, suara dan aturan `arah`), hanya kata kosakata, paling banyak satu
    `judul:` lalu satu `ke:` (lihat `_judul_token`, `_ke_token`). `lines` = `clean_lines` baris OCR. Murni dan hanya
    bergantung pada (`lines`, `doc`): worker (kerangka) dan pembaca (M3b, sesudah `apply_flow`) menghitungnya sama
    persis. Kata nama yang dibaca dari bukti itu (pihak lawan, pengirim, merchant) tidak pernah masuk judul; nama user
    tidak dipakai di sini (pembaca tidak mengenalnya), jadi kata judul hanya kosakata."""
    clean = pc.clean_lines(lines)
    forbidden = _forbidden_words(clean, doc, _profile_of(doc, clean), None)
    return [t for t in (_judul_token(clean, forbidden), _ke_token(doc.counterparty.name)) if t]


def build_layout(lines: list[str], doc: DokumenBayar, secrets: Secrets, *, user_name: str | None) -> dict | None:
    """Kerangka aman satu bukti (lihat docstring modul). None bila `doc.doc_type` bukan LAYOUT_TYPES, tanpa kunci aturan
    (aplikasi tak dikenal tanpa baris logo yang sah), atau berkunci logo padahal bukan `tidak_dikenali`. `lines` = baris OCR mentah
    (`TextDoc.lines`); `doc`/`secrets` = hasil pembaca SEBELUM disamarkan worker."""
    if doc.doc_type not in LAYOUT_TYPES:
        return None
    clean = pc.clean_lines(lines)
    profile = _profile_of(doc, clean)
    forbidden = _forbidden_words(clean, doc, profile, user_name)
    key = rule_key(clean, profile, forbidden_words=forbidden)
    # Kunci logo hanya untuk bukti tak dikenal (spec §2): QRIS/transfer tanpa profil aplikasi sering diawali nama merchant,
    # dan nama merchant tidak pernah dipelajari lintas user.
    if key is None or (key.startswith(LOGO_PREFIX) and doc.doc_type != "tidak_dikenali"):
        return None
    logo_line = None if profile is not None else next(
        (i for i, line in enumerate(clean[:LOGO_LINES]) if LOGO_PREFIX + " ".join(line.lower().split()) == key), None)
    entries = []
    for i, line in enumerate(clean):
        if len(entries) >= LAYOUT_MAX_LINES:
            break
        if i == logo_line or _secret_line(line, secrets):
            continue
        entry = _entry(i, line, clean[i - 1] if i else None, forbidden)
        if entry is not None:
            entries.append(entry)
    # `arah` (tahap 2 M3a): kunci tambahan versi 1; kerangka lama tanpa kunci ini tidak memberi suara `arah`.
    return {"v": LAYOUT_VERSION, "key": key, "lines": entries, "arah": arah_tokens(clean, doc)}
