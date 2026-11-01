"""Alat bersama pembaca QRIS dan transfer: baca field berlabel, nominal, status, waktu,
referensi, penyamaran nomor, dan penjaga supaya struk belanja tidak terbaca sebagai bukti bayar.

Semua fungsi murni (tanpa I/O). `lines` selalu hasil `clean_lines`; pembacaan field berlabel
memakai `body_lines(lines)`, penanda dan tanggal memakai `lines`."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from app.services.kotak_struk.document import Amounts
from app.services.kotak_struk.merchants import mask_digits
from app.services.kotak_struk.readers.labels import find_value, parse_datetime_id
from app.services.kotak_struk.readers.labels import count_markers
from app.services.kotak_struk.readers.profiles import (
    GENERIC_LABELS, PARTY_ACCOUNT_LINE, PROVIDER_LINE, AppProfile, is_money_provider, is_provider_only, labels_for,
    logo_profile,
)
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
_NOISE_LINE = re.compile(r"^\s*(?:merchant\s+(?:pan|id)|terminal\s+id|pan\s+(?:merchant|pelanggan)|customer\s+pan|id\s+terminal)"
                         r"(?=$|[\s:：])", re.IGNORECASE)


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
    names = fields or tuple({*GENERIC_LABELS, *(profile.labels if profile else ())} - WORDLIKE_FIELDS)
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


# Field yang labelnya kata biasa: tidak dianggap baris label saat mencari nilai yang hilang ("TIP TOP SWALAYAN" adalah nama).
WORDLIKE_FIELDS = frozenset({"extra"})
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
    ditambahkan ke sana (bahan rekening cadangan). Nama yang terbelah dua baris di samping labelnya digabung
    (`_wrapped_head`). Tanpa label: nama di bawah logo bila tata letak aplikasinya begitu (`read_header_party`).
    Tanpa huruf: None."""
    value = read_text(lines, labels_for(profile, field), profile)
    if value:
        head = _wrapped_head(lines, labels_for(profile, field), value, profile)
        value = f"{head} {value}" if head else value
    else:
        party = read_header_party(lines, profile)
        value = party.name if party else None
    if not value:
        return None
    value, found = split_long_numbers(value.strip(" :-–,"))
    if numbers is not None:
        numbers.extend(found)
    return value[:NAME_MAX] if re.search(r"[A-Za-z]", value) else None


_NAME_PART = re.compile(r"[A-Z][A-Z.'\-]*(?: [A-Z][A-Z.'\-]*){0,2}")


def _wrapped_head(lines: list[str], labels: list[str], value: str, profile: AppProfile | None) -> str | None:
    """Baris pertama nama yang terbelah dua baris ("ANDI" lalu "Nama Penerima PRATAMA"): aplikasi yang mencetak nilai
    rata kanan memecah nama panjang, dan OCR menaruh potongan pertamanya DI ATAS baris label. Digabung hanya bila nilai
    ada sebaris dengan label, nilai dan baris di atasnya sama-sama 1-3 kata huruf besar tanpa angka, dan baris di atas
    itu yatim: bukan label, bukan nilai label yang berdiri sendiri di atasnya, tanpa kata status atau jenis bukti
    ("QRIS", "TRANSFER"), dan bukan nama bank/aplikasi. Baris lain (judul, "QRIS", "BANK BCA", "BRIMO", nilai
    "Keterangan") tidak pernah digabung."""
    start = _label_start(tuple(sorted({label.lower() for label in labels}, key=len, reverse=True)))
    at = next((i for i, line in enumerate(lines) if (m := start.match(line)) and line[m.end():].strip(" :：") == value), None)
    if not at or not _NAME_PART.fullmatch(value):
        return None
    head = lines[at - 1]
    if not _NAME_PART.fullmatch(head) or is_label_line(head, profile) or _ANCHOR.search(head) or is_money_provider(head):
        return None
    above = lines[at - 2] if at >= 2 else ""
    if above and is_label_line(above, profile) and not _rest_of_label(above, profile):
        return None                                   # nilai label lain ("Keterangan" / "BAYAR")
    return head


def _rest_of_label(line: str, profile: AppProfile | None) -> str:
    names = tuple({*GENERIC_LABELS, *(profile.labels if profile else ())} - WORDLIKE_FIELDS)
    labels = {label.lower() for name in names for label in labels_for(profile, name)}
    m = _label_start(tuple(sorted(labels, key=len, reverse=True))).match(line)
    return line[m.end():].strip(" :：") if m else line


@dataclass
class HeaderParty:
    """Pihak lawan tanpa label di bawah logo (`AppProfile.party_on_top`)."""
    name: str | None
    city: str | None
    provider: str | None        # "GoPay", "Mandiri", "PLN Prepaid": bank/e-wallet tujuan, atau penyedia tagihan
    number: str | None          # nomor di baris penyedia (rekening/HP/meter), seperti tercetak
    amount: int                 # nominal besar di bawahnya


HEADER_PARTY_LINES = 5          # baris antara logo dan nominal
_INITIALS = re.compile(r"^(?P<name>.*\S)\s+(?P<initials>[A-Z]{1,2})$")
_PROVIDER_NUMBER = re.compile(r"[\d*•…]*\d(?:[ \-]?\d{3,})*")
_CITY = re.compile(r"[A-Za-z][A-Za-z .'\-]*")


def _initials_of(name: str) -> set[str]:
    words = re.findall(r"[A-Za-z]+", name)
    if not words:
        return set()
    if len(words) == 1:
        return {words[0][0].upper(), words[0][:2].upper()}
    return {(words[0][0] + words[-1][0]).upper()}


def read_header_party(lines: list[str], profile: AppProfile | None) -> HeaderParty | None:
    """Pihak lawan di tata letak "nama di bawah logo" (Jago Syariah): baris sesudah baris logo aplikasi (`logo_profile`,
    salah satu dari 2 baris pertama) sampai baris nominal Rp yang berdiri sendiri (paling banyak HEADER_PARTY_LINES baris di antaranya).
    - baris "Penyedia · nomor" ("GoPay·…7890", "Mandiri·…4321", "PLN Prepaid·…1234") = penyedia dan nomornya;
    - nama = baris pertama; bila inisial avatar menempel di ujung salah satu baris ("SITI AMINAH SA", "PRATAMA AP"), nama
      = baris-baris sampai di situ digabung, tanpa inisialnya (inisial harus huruf awal kata pertama dan terakhir);
    - kota = baris huruf sesudah nama (QRIS: "BANDUNG").
    None bila profilnya bukan tata letak ini atau baris-barisnya tidak ada."""
    if profile is None or not profile.party_on_top:
        return None
    logo = next((i for i, line in enumerate(lines[:2]) if (p := logo_profile(line)) and p.key == profile.key), None)
    if logo is None:
        return None
    end = next((i for i in range(logo + 1, min(len(lines), logo + 2 + HEADER_PARTY_LINES))
                if _AMOUNT_ONLY.fullmatch(lines[i]) and amounts_in(lines[i])), None)
    if end is None or end == logo + 1:
        return None
    # Judul status ("Transfer Sedang Diproses") dan baris yang hanya berisi kata status/jenis bukti ("Berhasil", "QRIS")
    # bukan nama; nama yang memuat kata status ("CV SUKSES JAYA") tetap nama.
    block = [line for line in lines[logo + 1:end]
             if line and not is_label_line(line, profile) and not _is_status_title(line)
             and _ANCHOR.sub(" ", line).strip(" !.,:-")]
    provider = number = None
    at = next((j for j, line in enumerate(block) if PROVIDER_LINE.match(line)), None)
    if at is not None:
        m = PROVIDER_LINE.match(block[at])
        provider = m.group("name").strip() or None
        found = _PROVIDER_NUMBER.search(m.group("rest"))
        number = found.group(0) if found and sum(c.isdigit() for c in found.group(0)) >= 4 else None
        block = block[:at]
    name, rest = (block[0], block[1:]) if block else (None, [])
    for k, line in enumerate(block):
        m = _INITIALS.match(line)
        joined = " ".join([*block[:k], m.group("name")]) if m else ""
        if m and m.group("initials") in _initials_of(joined):
            name, rest = joined, block[k + 1:]
            break
    if name:
        name = split_long_numbers(name)[0] or None
    city = next((line for line in rest if _CITY.fullmatch(line) and len(line.split()) <= 3), None)
    return HeaderParty(name=name, city=city, provider=provider, number=number, amount=amounts_in(lines[end])[0])


def read_party_account(lines: list[str], profile: AppProfile | None, field: str = "merchant") -> tuple[str, str] | None:
    """(bank/e-wallet, nomor) dari baris tepat di bawah nama pihak lawan yang sebaris dengan labelnya ("Ditransfer ke
    BUDI" lalu "Mandiri 1234…" / "ShopeePay …6390"; GoPay). Hanya bila penyedianya bank/e-wallet dan nomornya >= 4 digit."""
    start = _label_start(tuple(sorted({label.lower() for label in labels_for(profile, field)}, key=len, reverse=True)))
    for i, line in enumerate(lines[:-1]):
        m = start.match(line)
        if not m or not line[m.end():].strip(" :："):
            continue
        below = None if is_label_line(lines[i + 1], profile) else PARTY_ACCOUNT_LINE.match(lines[i + 1])
        if below and is_money_provider(below.group("name")) and sum(c.isdigit() for c in below.group("number")) >= 4:
            return below.group("name").strip(), " ".join(below.group("number").split())
    return None


# ShopeePay "Kirim Ke": nama penerima lalu "Bank Jago Syariah: 1234…" / "GoPay: 0812…", rata kanan dan berpusat pada labelnya,
# jadi OCR menaruh baris pertama blok DI ATAS baris label (seperti `_wrapped_head`) dan baris bank/nomor di nilai label atau
# tepat di bawahnya. Blok ini hanya dikenali dari baris "Penyedia: nomor" (dengan titik dua) yang hanya berisi nama bank/e-wallet
# (`is_provider_only`); ikon bank di depannya terbaca satu huruf ("o  Bank Jago Syariah:").
_PROVIDER_COLON = re.compile(r"(?:\S\s+)?(?P<name>[A-Za-z][A-Za-z'&.\- ]*?)\s*:\s*(?P<number>[\d*•…][\d *•…\-]*\d)?")
_PARTY_NUMBER = re.compile(r"[\d*•…][\d *•…\-]*\d")
# Kata nama di blok: huruf besar ("ANDI", "TOPU-SXXXX"), atau samaran aplikasi berhuruf kecil hasil OCR ("Axxxxxxx").
_BLOCK_NAME_WORD = re.compile(r"[A-Z][A-Z.'\-]*|[A-Z][a-z]*x{2,}")


@dataclass
class SideBlock:
    name: str | None
    provider: str
    number: str | None


def _provider_value(text: str) -> tuple[str, str | None] | None:
    m = _PROVIDER_COLON.fullmatch(text.strip())
    if not m or not is_provider_only(m.group("name")):
        return None
    return m.group("name").strip(), m.group("number")


def _block_name(text: str) -> bool:
    words = text.split()
    return 1 <= len(words) <= 3 and all(_BLOCK_NAME_WORD.fullmatch(w) for w in words)


def read_side_block(lines: list[str], profile: AppProfile | None, field: str = "merchant") -> SideBlock | None:
    """Pihak lawan di blok rata kanan berpusat pada labelnya (ShopeePay "Kirim Ke"), lihat `_PROVIDER_COLON`:
    - nilai label "Bank Jago Syariah:" (nomornya di baris bawah) -> nama = baris di atas label;
    - nilai label potongan nama ("Axxxxxxx") dan baris bawahnya "GoPay: 0812…" -> nama = baris di atas + nilai itu.
    Baris di atas hanya dipakai bila berbentuk nama (1-3 kata huruf besar/samaran), bukan label, bukan kata status, bukan
    hanya nama bank, dan bukan nilai label lain yang berdiri sendiri. None bila tidak ada baris "Penyedia:" di blok itu."""
    start = _label_start(tuple(sorted({label.lower() for label in labels_for(profile, field)}, key=len, reverse=True)))
    for i, line in enumerate(lines):
        m = start.match(line)
        if not m:
            continue
        value = line[m.end():].lstrip(" :：").rstrip()
        below = lines[i + 1].strip() if i + 1 < len(lines) else ""
        own = _provider_value(value) if value else None
        if own:
            provider, number = own
            number = number or (below if _PARTY_NUMBER.fullmatch(below) else None)
            parts = []
        else:
            under = _provider_value(below) if below else None
            if not under or not under[1] or not _block_name(value):
                continue
            (provider, number), parts = under, [value]
        head = lines[i - 1].strip() if i >= 1 else ""
        above = lines[i - 2] if i >= 2 else ""
        if head and _block_name(head) and not is_label_line(head, profile) and not _ANCHOR.search(head) \
                and not is_provider_only(head) and not (above and is_label_line(above, profile)
                                                        and not _rest_of_label(above, profile)):
            parts = [head, *parts]
        return SideBlock(name=" ".join(parts) or None, provider=provider, number=number)
    return None


# Kata nama orang: diawali huruf besar, boleh berakhir bintang samaran ("ANDI***").
_PERSON_WORD = re.compile(r"[A-Z][A-Za-z.'\-]*[*•]*")


def _person_name(value: str) -> str | None:
    """Nama orang dari nilai label: 1-4 kata berhuruf awal besar tanpa angka, bukan nama bank/aplikasi. Samaran tanpa huruf
    ("********", yang OCR bisa baca "水水水水") dibuang. Kalimat kaki ("Dikirim dari app GoPay. Dapetin gratis", "dari Bank
    Syariah Indonesia. Semoga …") dan sumber dana ("Saldo ShopeePay") bukan nama."""
    words = [w.strip(",") for w in value.split()]
    words = [w for w in words if re.search(r"[A-Za-z0-9]", w)]
    if not 1 <= len(words) <= 4 or not all(_PERSON_WORD.fullmatch(w) for w in words):
        return None
    name = " ".join(words)
    return None if is_money_provider(name) else name


def read_sender_name(lines: list[str], profile: AppProfile | None) -> str | None:
    """Nama pengirim yang tercetak: label pengirim ("Pengirim", "Dari", "Dikirim Dari"), lalu label rekening/akun sumber
    ("Sumber akun", "Rekening Sumber"; nama yang terbelah dua baris digabung, `_wrapped_head`). Hanya nilai yang berbentuk nama
    orang (`_person_name`); selain itu None."""
    for field in ("sender", "source"):
        labels = labels_for(profile, field)
        value = read_text(lines, labels, profile)
        if value:
            head = _wrapped_head(lines, labels, value, profile)
            name = _person_name(f"{head} {value}" if head else value)
            if name:
                return name
    return None


def is_app_receipt(lines: list[str]) -> bool:
    """Resi dari aplikasi bank/e-wallet, bukan struk belanja: baris logo aplikasi (`logo_profile`: hanya nama aplikasi,
    bukan "TOKO MANDIRI JAYA") di salah satu dari 2 baris pertama dan ada label rekening/akun sumber ("Sumber akun", "Sumber Dana", "Rekening Sumber"). Toko tidak mencetak
    rekening sumber user; tagihan dan pulsa dari aplikasi bank ("PPj", "Materai", "Admin Bank" di atas "Total Bayar")
    berbentuk struk tetapi bukan belanja, jadi pembaca struk belanja tidak mengambilnya (FS-2: jenis `tagihan`)."""
    cleaned = clean_lines(lines)
    if not any(logo_profile(line) for line in cleaned[:2]):
        return False
    source = _label_start(tuple(sorted({label.lower() for label in labels_for(None, "source")}, key=len, reverse=True)))
    return any(source.match(line) for line in cleaned)


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
        status = _ANY_STATUS.search(value or "")
        if status:                       # status dicetak di samping ID ("123456-ABCD-EFGHIJ  Sukses")
            value = value[:status.start()]
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


# Label biaya tambahan (`extra`: layanan, tips, ongkir, ...) juga kata biasa di baris bantuan dan promo ("Layanan Pelanggan
# 1500888", "Tips Aman: hubungi 1500888", "Ongkir Gratis s/d Rp10.000"). Barisnya dihitung biaya hanya bila sisanya nominal saja
# ("Rp2.000", "2.000", "2000"), atau keterangan tanpa angka (persen boleh) lalu nominal ber-Rp/IDR atau berpemisah ribuan di ujung
# baris ("Layanan BI-FAST Rp2.500", "Service Charge 10% Rp2.500"). Keterangan promo/batas (gratis, s/d, maks, ...) bukan biaya.
_EXTRA_VALUE = re.compile(
    r"(?P<note>(?:[^\d]|\d+(?:[.,]\d+)?\s*%)*?)\s*"
    r"(?P<amount>(?:Rp|IDR)\.?\s*\d[\d.,]*|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+)\s*(?:,-|-)?\s*(?P<suffix>(?:Rp|IDR)\.?)?\s*\)?\s*",
    re.IGNORECASE)
_MONEY = re.compile(r"(?:Rp|IDR)|\d{1,3}[.,]\d{3}", re.IGNORECASE)
_PROMO_WORDS = re.compile(r"(?<!\w)(?:gratis|free|s/d|s\.d|hingga|sampai|maks(?:imal)?|max|min(?:imal)?|up\s+to)(?!\w)", re.IGNORECASE)


PLAIN_FEE_DIGITS = 4      # angka polos (tanpa Rp, tanpa pemisah ribuan) lebih panjang dari ini = nomor call centre/telepon


def _extra_amount(text: str) -> int:
    """Nominal biaya tambahan dari sisa baris sesudah labelnya (lihat `_EXTRA_VALUE`); selain bentuk itu 0. Angka polos
    ("2000") dihitung hanya sampai PLAIN_FEE_DIGITS digit: "14017", "1500888" sesudah "Layanan"/"Tips" adalah nomor
    call centre, bukan biaya; nominal ber-Rp/IDR atau berpemisah ribuan boleh berapa pun."""
    m = _EXTRA_VALUE.fullmatch(text.strip())
    if not m:
        return 0
    note, amount = m.group("note").strip(), m.group("amount")
    if note and (_PROMO_WORDS.search(note) or not _MONEY.match(amount)):
        return 0
    if amount.isdigit() and len(amount) > PLAIN_FEE_DIGITS and not m.group("suffix"):
        return 0
    found = amounts_in(amount)
    return found[0] if found else 0


# Nilai baris biaya yang berarti gratis: "Gratis!", atau harga coret lalu "Gratis!" ("Rp2.000 Gratis!"). Kata gratis di
# dalam keterangan ("Rp2.500 (gratis 25x/bulan)") bukan nilainya.
_FREE_VALUE = re.compile(r"(?:(?:Rp|IDR)?\.?\s*\d[\d.,]*\s+)?(?:gratis|free)\W*", re.IGNORECASE)


def _sum_amounts(lines: list[str], labels: list[str], profile: AppProfile | None,
                 strict_labels: list[str] | tuple[str, ...] = (), struck: bool = False) -> int:
    """Jumlah nominal semua baris berlabel (biaya, diskon, pajak bisa lebih dari satu baris). Satu baris dihitung
    sekali walau beberapa sinonim cocok ("Biaya Admin" cocok "biaya admin" dan "biaya"). Yang < Rp100 dianggap 0.
    Baris yang labelnya di `strict_labels` (biaya tambahan berkata biasa) dibaca dengan `_extra_amount`. `struck` (biaya):
    harga coret di depan harga sebenarnya ("Biaya admin Rp2.000 Rp1.000" = 1.000, "Rp2.000 Gratis!" = 0, GoPay): nominal
    terakhir hanya bila tepat dua nominal dan yang terakhir lebih kecil ("Biaya Admin Rp2.500 Total Rp52.500" = 2.500), dan
    gratis hanya bila itu nilai barisnya."""
    if not labels:
        return 0
    start = _label_start(tuple(sorted({label.lower() for label in labels}, key=len, reverse=True)))
    strict = {" ".join(label.lower().split()) for label in strict_labels}
    total = 0
    for i, line in enumerate(lines):
        m = start.match(line)
        if not m:
            continue
        rest = line[m.end():].lstrip(" :：")
        if not rest and i + 1 < len(lines) and not is_label_line(lines[i + 1], profile):
            rest = lines[i + 1]
        rest = _SIGN.sub(" ", rest)
        if " ".join(m.group(0).lower().split()) in strict:
            total += _extra_amount(rest)
            continue
        amounts = amounts_in(rest)
        if struck and _FREE_VALUE.fullmatch(rest.strip()):
            continue
        if struck and len(amounts) == 2 and amounts[1] < amounts[0]:
            total += amounts[1]
            continue
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
    fee_labels = labels_for(profile, "fee")
    extra_labels = [label for label in labels_for(profile, "extra") if label.lower() not in {f.lower() for f in fee_labels}]
    fee = _sum_amounts(lines, [*fee_labels, *extra_labels], profile, strict_labels=extra_labels, struck=True) \
        or _first_amount(lines, _COMPONENT_TOTAL_LABELS, profile) or 0
    discount = _sum_amounts(lines, labels_for(profile, "discount"), profile)
    tax = _sum_amounts(lines, labels_for(profile, "tax"), profile)
    if subtotal is None and total is None:
        party = read_header_party(lines, profile)
        found = (party.amount, "sedang") if party else _bare_amount(lines)
        amounts = Amounts(fee=fee, tax=tax, discount=discount, total=found[0] if found else None)
        return amounts, found[1] if found else None
    if total is None:
        total = max(subtotal + fee + tax - discount, 0)
    return Amounts(subtotal=subtotal, fee=fee, tax=tax, discount=discount, total=total), "tinggi"


def _bare_amount(lines: list[str]) -> tuple[int, str] | None:
    """Angka `Rp` yang berdiri sendiri: yang pertama sesudah baris QRIS/status (`sedang`), selain itu yang pertama: `sedang`
    bila tepat di bawah baris logo aplikasi (ShopeePay mencetak nominal di atas statusnya), selain itu `rendah`."""
    anchor = next((i for i, line in enumerate(lines) if _ANCHOR.search(line)), -1)
    candidates = [(i, amounts_in(line)) for i, line in enumerate(lines) if _AMOUNT_ONLY.fullmatch(line)]
    candidates = [(i, amounts) for i, amounts in candidates if amounts]
    after = [c for c in candidates if c[0] > anchor] if anchor >= 0 else []
    if after:
        return after[0][1][0], "sedang"
    if not candidates:
        return None
    under_logo = candidates[0][0] >= 1 and candidates[0][0] <= 2 and logo_profile(lines[candidates[0][0] - 1])
    return candidates[0][1][0], "sedang" if under_logo else "rendah"


def has_amount(lines: list[str], profile: AppProfile | None = None) -> bool:
    return read_amounts(lines, profile)[0].total is not None


# ── Waktu ───────────────────────────────────────────────────────────────────

_TIME_ONLY = re.compile(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(?:WIB|WITA|WIT)?", re.IGNORECASE)
# Baris-baris ini memuat nilai bebas (catatan, nama, nomor) yang bisa kebetulan memuat tanggal.
_VALUE_FIELDS = ("note", "ref", "merchant", "sender", "account", "bank", "nmid")


def _valid_time(m: re.Match | None) -> tuple[int, int, int] | None:
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59 or int(m.group(3) or 0) > 59:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _labelled_time(lines: list[str], profile: AppProfile | None) -> tuple[int, int, int] | None:
    """Jam dari baris berlabel jam yang nilainya jam saja ("Waktu 9:31", "Jam: 14.05", "Pukul 08:12:33 WIB")."""
    start = _label_start(tuple(sorted({label.lower() for label in labels_for(profile, "time")}, key=len, reverse=True)))
    for line in lines:
        m = start.match(line)
        if m:
            found = _valid_time(_TIME_ONLY.fullmatch(line[m.end():].strip(" :：")))
            if found:
                return found
    return None


def read_paid_at(lines: list[str], profile: AppProfile | None = None) -> tuple[datetime | None, str | None]:
    """(waktu bayar, keyakinan): `tinggi` bila ada jam, `sedang` bila hanya tanggal (jam di baris
    sesudahnya dipakai bila berdiri sendiri, atau jam di baris berlabel jam di mana pun: "Waktu 9:31" + "Tanggal
    31 Okt 2026")."""
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
        if (paid.hour, paid.minute, paid.second) == (0, 0, 0):
            labelled = _labelled_time(lines, profile)
            if labelled:
                return paid.replace(hour=labelled[0], minute=labelled[1], second=labelled[2]), "tinggi"
        midnight = (paid.hour, paid.minute, paid.second) == (0, 0, 0)
        return paid, "sedang" if midnight else "tinggi"
    return None, None


# ── Status ──────────────────────────────────────────────────────────────────

_GAGAL = re.compile(r"(?<!\w)(gagal|failed|tidak\s+berhasil)(?!\w)", re.IGNORECASE)
# Kegagalan yang dinyatakan dengan negasi kata sukses/terkirim ("Tidak sukses", "Dana tidak terkirim", "Unsuccessful"), dan
# "belum ..." = belum selesai (pending: "Belum berhasil", "Pembayaran belum diterima", "Dana belum masuk"). "Belum lunas"
# sengaja tidak: itu status tagihan/kredit di struk, bukan status bukti bayar. "Tidak dibayar"/"Not paid" = belum dibayar
# (pending), bukan gagal.
# Kata tiba (terkirim/diterima/masuk, dan dibayar/paid) hanya dihitung bila negasinya MENUTUP klausa (`_END`): "Transaksi
# tidak masuk poin", "Transfer tidak diterima di kasir", "Biaya admin tidak dibayar penerima" di kaki struk bukan status.
# Negasi kata sukses (berhasil/sukses) berlaku di mana saja ("Tidak sukses karena saldo kurang"). Di luar nilai label status
# pembayaran kata tiba juga butuh subjek uang di depannya, dan di struk belanja "tidak ..."-nya tidak dihitung (`_mask_arrival`).
_END = r"(?=\s*(?:$|[.,!;:)]))"
_ARRIVAL_VERB = r"(?:terkirim|diterima|masuk)"
_NEGATED_DONE_WORD = (r"(?:tidak|tak|gak|nggak|ga|not)\s+(?:berhasil|sukses|successful|success)"
                      r"|(?:tidak|tak|gak|nggak|ga|not)\s+" + _ARRIVAL_VERB + _END + r"|unsuccessful")
_NOT_YET_DONE_WORD = (r"belum\s+(?:berhasil|sukses|selesai)|belum\s+(?:" + _ARRIVAL_VERB + r"|dibayar)" + _END
                      + r"|(?:tidak|not)\s+(?:dibayar|paid)" + _END + r"|not\s+yet")
_NEGATED_DONE = re.compile(r"(?<!\w)(?:" + _NEGATED_DONE_WORD + r")(?!\w)", re.IGNORECASE)
_NOT_YET_DONE = re.compile(r"(?<!\w)(?:" + _NOT_YET_DONE_WORD + r")(?!\w)", re.IGNORECASE)
_PENDING = re.compile(r"(?<!\w)(?<!berhasil )(diproses|pending|processing)(?!\w)", re.IGNORECASE)   # "berhasil diproses" = sukses
_BERHASIL = re.compile(r"(?<!\w)(berhasil|sukses|successful|success)(?!\w)", re.IGNORECASE)
HEADER_LINES = 4          # status biasanya ada di judul bukti
HEADER_WORDS = 8          # kalimat lebih panjang dari ini = catatan kaki, bukan status
BODY_WORDS = 5            # di luar judul, hanya baris yang lebih pendek lagi


def _classify(text: str) -> str | None:
    """Negasi dibaca sebelum kata sukses: "Belum berhasil" = pending, "Tidak sukses" = gagal, tidak pernah berhasil."""
    if _NEGATED_DONE.search(text) or _GAGAL.search(text):
        return GAGAL
    if _NOT_YET_DONE.search(text) or _PENDING.search(text):
        return PENDING
    return BERHASIL if _BERHASIL.search(text) else None


# Kalimat peringatan/bantuan di kaki bukti ("Jika gagal hubungi 14017", "Transaksi gagal? Hubungi kami") memuat
# kata status tapi bukan status transaksi. Sebuah baris dilewati hanya bila:
# - kata bersyarat/ajakan (jika, bila, apabila, kalau, if, hubungi, silakan, please, contact) muncul SEBELUM kata status
#   pertama ("Hubungi 14017 jika gagal", "Silakan hubungi kami bila gagal"), atau kalimat dibuka "Untuk ..."
#   ("Untuk transaksi gagal, cek riwayat"; "Pembayaran untuk Tagihan PLN Gagal" tetap kegagalan), atau
# - "?" tepat sesudah sebuah kata status ("Transaksi gagal?", "Failed? Contact us").
# Ajakan yang muncul SESUDAH kata status ("Transaksi Gagal, silakan coba lagi", "Failed. Please try again") adalah
# kegagalan sungguhan dan tetap dihitung; bagian kalimat sesudah kata bersyarat itu dibuang ("Transaksi Berhasil,
# jika gagal hubungi 14017" = berhasil).
_STATUS_WORD = (r"(?:" + _NEGATED_DONE_WORD + r"|" + _NOT_YET_DONE_WORD
                + r"|gagal|failed|tidak\s+berhasil|diproses|pending|processing|berhasil|sukses|successful|success)")
_ANY_STATUS = re.compile(r"(?<!\w)" + _STATUS_WORD + r"(?!\w)", re.IGNORECASE)
_CONDITIONAL = re.compile(r"(?<!\w)(?:jika|bila|apabila|kalau|if|hubungi|silakan|silahkan|contact|please)(?!\w)", re.IGNORECASE)
_LEADING_UNTUK = re.compile(r"^\W*untuk(?!\w)", re.IGNORECASE)
# Daftar kata status: "pending atau gagal", "pending/gagal", "gagal, pending, atau tidak berhasil", "gagal ataupun yang pending",
# "failed or pending".
_STATUS_LIST = _STATUS_WORD + r"(?:[\s/,&\-–]+(?:(?:atau|ataupun|maupun|dan|serta|or|and)\s+)?(?:yang\s+)?" + _STATUS_WORD + r")*"
# Frasa bantuan yang menyebut JENIS transaksi, bukan status bukti ini ("Info untuk transaksi gagal: 14017", "Bantuan untuk
# transaksi gagal", "Pengaduan transaksi pending/gagal: 14017", "Biaya transfer untuk transaksi gagal dikembalikan", "For failed
# or pending transactions call 14017"): dibuang sebelum status dibaca. "untuk" + nama/tagihan tetap status ("Pembayaran untuk
# Tagihan PLN Gagal").
_HELP_PHRASE = re.compile(
    r"(?<!\w)(?:untuk|pengaduan|bantuan|keluhan)\s+(?:transaksi|pembayaran|transfer)\s+(?:yang\s+)?" + _STATUS_LIST + r"(?!\w)"
    r"|(?<!\w)for\s+" + _STATUS_LIST + r"\s+(?:transactions?|payments?|transfers?)(?!\w)",
    re.IGNORECASE)


# Negasi kata tiba di luar nilai label status pembayaran (`_mask_arrival`; nilai label "Status: Belum diterima", "Status:
# Tidak terkirim" tidak dibatasi):
# - hanya status bila klausanya menyebut uangnya lebih dulu ("Dana belum masuk", "Pembayaran QRIS belum diterima, harap
#   tunggu") dan tidak menyebut imbalan (`_REWARD`): "Poin belum masuk", "Kembalian tidak diterima", "Poin transaksi ini belum
#   masuk" bukan status pembayaran;
# - di teks berbaris barang (struk belanja) negasi "tidak ..." tidak pernah status walau bersubjek uang: itu pemberitahuan
#   toko ("Transfer tidak diterima", "Pembayaran non tunai tidak diterima"), dan struk belanja tidak boleh diblokir oleh
#   kakinya. "belum ..." bersubjek uang tetap memperingatkan ("Pembayaran belum diterima, harap tunggu").
_ARRIVAL = re.compile(r"(?<!\w)(?:(?P<negated>tidak|tak|gak|nggak|ga|not)|belum)\s+" + _ARRIVAL_VERB + _END, re.IGNORECASE)
_MONEY_SUBJECT = re.compile(r"(?<!\w)(?:dana|uang|saldo|transfer|pembayaran|transaksi|payment)(?!\w)", re.IGNORECASE)
# Klausa yang menyebut imbalan ("Poin transaksi ini belum masuk", "Saldo poin belum masuk") tentang imbalan itu, bukan uangnya
# (A14 r3, carry re-review 5 m1).
_REWARD = re.compile(r"(?<!\w)(?:poin|point|points|cashback|voucher|kupon|stamp|hadiah)(?!\w)", re.IGNORECASE)
# Batas klausa: tanda baca (titik/koma di dalam nominal, "Rp50.000", bukan batas), garis tegak, tanda pisah berspasi, dan kata
# sambung "dan"/"tetapi"/"tapi"/"namun" ("Transaksi berhasil dan poin belum masuk").
_CLAUSE_BREAK = re.compile(r"[.,](?!\d)|[;!?|]|\s[-–—]+\s|(?<!\w)(?:dan|tetapi|tapi|namun)(?!\w)", re.IGNORECASE)


def _mask_arrival(text: str, *, store: bool) -> str:
    """Negasi kata tiba yang bukan status (lihat di atas) diganti tanda netral per huruf: jumlah kata baris tetap (batas
    HEADER_WORDS/BODY_WORDS tetap menghitungnya), tetapi bukan lagi kata status."""
    def mask(m: re.Match) -> str:
        clause = _CLAUSE_BREAK.split(text[:m.start()])[-1]
        if (store and m.group("negated")) or _REWARD.search(clause) or not _MONEY_SUBJECT.search(clause):
            return re.sub(r"\S", "·", m.group(0))
        return m.group(0)
    return _ARRIVAL.sub(mask, text)


def _is_status_sentence(text: str) -> bool:
    words = list(_ANY_STATUS.finditer(text))
    if not words:
        return False
    before = text[:words[0].start()]
    if _CONDITIONAL.search(before) or _LEADING_UNTUK.match(before):
        return False
    return not any(text[m.end():].lstrip().startswith("?") for m in words)


def _status_part(text: str) -> str:
    """Bagian kalimat status sampai kata bersyarat/ajakan pertama sesudah kata statusnya."""
    first = _ANY_STATUS.search(text)
    cut = _CONDITIONAL.search(text, first.end()) if first else None
    return text[:cut.start()] if cut else text


# Baris nama pihak lawan ("Merchant TOKO GAGAL MANIA", "Penerima CV SUKSES", atau nama di bawah label "Merchant" yang berdiri
# sendiri): kata status di dalam nama bukan status transaksi. Kecuali bila baris itu sendiri judul status (`_is_status_title`):
# OCR bisa kehilangan nama di bawah "Merchant" sehingga "Pembayaran Gagal" jatuh di bawah label itu, dan "Tujuan Transfer Gagal"
# atau "Dari rekening gagal didebet" diawali kata yang kebetulan label nama. Judul dari baris nama hanya boleh menyumbang
# gagal/pending, tidak pernah berhasil: "Tujuan Transfer CV SUKSES JAYA" juga berbentuk judul, dan "berhasil" palsu di judul
# akan menutupi kegagalan di bawah baris 4.
_NAME_FIELDS = ("merchant", "sender")
# Judul status: kata benda transaksi, paling banyak 3 kata lain, lalu kata status ("Transfer Gagal", "Transaksi Anda Gagal",
# "Payment failed", "Top Up Gagal", "rekening gagal didebet"). Nama seperti "TOKO GAGAL MANIA" atau "BUDI GAGAL" tidak.
# "dana"/"saldo" sengaja tidak masuk: kata biasa dalam nama ("DANA SUKSES ABADI").
_STATUS_TITLE = re.compile(
    r"(?<!\w)(?:transaksi|transfer|pembayaran|payment|transaction|top[\s-]?up|isi\s+saldo|rekening|pengiriman|penarikan|setoran|"
    r"pembelian|purchase|withdrawal|deposit)(?!\w)\s+(?:\S+\s+){0,3}" + _STATUS_WORD + r"(?!\w)", re.IGNORECASE)


# Kata status "batal" (keputusan pemilik 3, spec §7): dibatalkan, ditolak, batal, rejected, cancelled/canceled, void = gagal,
# tetapi HANYA di (a) judul status (kata benda transaksi, paling banyak 3 kata lain, lalu kata itu: "Transfer Dibatalkan",
# "Pembayaran Ditolak", "Transaksi Batal", "Payment rejected"), (b) nilai label status pembayaran ("Status: Dibatalkan",
# "Status Transaksi Ditolak"), dan (c) baris berstatus saja di 4 baris pertama ("Dibatalkan", "Ditolak", "Rejected",
# "Cancelled"; "Batal" dan "Void" saja tidak pernah: tombol "Batal", baris "VOID" di struk). Baris badan pendek tidak
# membacanya. Di posisi itu kata ini diganti "gagal" (`_cancel_as_failed`), sehingga aturan kata gagal yang ada (kaki
# bersyarat/tanya/bantuan, baris nama, batas kata) tetap berlaku. Tidak dihitung: kata itu sesudah negasi/modal/kata
# penghubung ("tidak dapat dibatalkan", "akan dibatalkan", "Payment cannot be cancelled", "Transaksi yang dibatalkan tidak
# dapat dikembalikan": kebijakan, bukan status) atau diikuti kata bersyarat ("Transaksi dibatalkan jika tidak dibayar").
# Di posisi lain kata ini hanya mencegah `berhasil` (`_NOT_DONE`).
_CANCEL_WORD = r"(?:dibatalkan|ditolak|batal|rejected|cancell?ed|void)"
_CANCEL = re.compile(r"(?<!\w)" + _CANCEL_WORD + r"(?!\w)", re.IGNORECASE)
_CANCEL_GUARD = (r"(?:tidak|tak|gak|nggak|ga|belum|bukan|dapat|bisa|boleh|akan|harus|perlu|mau|ingin|yang|"
                 r"not|cannot|can|will|could|may|might|must|to|be|which|that)")
_CANCEL_GUARD_WORD = re.compile(r"(?<!\w)" + _CANCEL_GUARD + r"(?!\w)", re.IGNORECASE)
_CANCEL_TITLE = re.compile(
    r"(?<!\w)(?:transaksi|transfer|pembayaran|payment|transaction|top[\s-]?up|isi\s+saldo|rekening|pengiriman|penarikan|setoran|"
    r"pembelian|purchase|withdrawal|deposit)(?!\w)\s+(?:(?!" + _CANCEL_GUARD + r"(?!\w))\S+\s+){0,3}"
    r"(?P<word>" + _CANCEL_WORD + r")(?!\w)", re.IGNORECASE)
# Baris berstatus saja (hanya di judul): "Dibatalkan", "Telah ditolak", "Cancelled!". Bukan "Batal"/"Void".
_CANCEL_ALONE = re.compile(r"\W*(?:(?:telah|sudah|has\s+been|was)\s+)?(?P<word>dibatalkan|ditolak|rejected|cancell?ed)\W*",
                           re.IGNORECASE)
_IF_WORD = re.compile(r"(?<!\w)(?:jika|bila|apabila|kalau|if|unless|kecuali)(?!\w)", re.IGNORECASE)


def _cancel_counts(text: str, m: re.Match) -> bool:
    """Kata batal di `m` dihitung bila tidak diikuti kata bersyarat ("dibatalkan jika tidak dibayar")."""
    return not _IF_WORD.search(text, m.end())


def _cancel_as_failed(text: str, *, value: bool = False, header: bool = False) -> str:
    """`text` dengan kata batal yang dihitung diganti "gagal" (lihat `_CANCEL_WORD`): selalu di judul status; di mana saja
    bila `value` (nilai label status pembayaran), kecuali sesudah negasi/modal; seluruh baris bila `header` dan baris itu
    berstatus saja. Selain itu teks dikembalikan apa adanya."""
    if not _CANCEL.search(text or ""):
        return text
    if header:
        m = _CANCEL_ALONE.fullmatch(text)
        if m:
            return text[:m.start("word")] + "gagal" + text[m.end("word"):]
    spans = []
    if value:
        for m in _CANCEL.finditer(text):
            if not _CANCEL_GUARD_WORD.search(text[:m.start()]) and _cancel_counts(text, m):
                spans.append((m.start(), m.end()))
    else:
        for m in _CANCEL_TITLE.finditer(text):
            if _cancel_counts(text, m):
                spans.append((m.start("word"), m.end("word")))
    for start, end in reversed(spans):
        text = text[:start] + "gagal" + text[end:]
    return text


def _is_status_title(text: str) -> bool:
    return bool(_STATUS_TITLE.search(text) or _STATUS_TITLE.search(_cancel_as_failed(text)))


def _name_label_end(text: str) -> int | None:
    labels = {label.lower() for name in _NAME_FIELDS for label in labels_for(None, name)}
    m = _label_start(tuple(sorted(labels, key=len, reverse=True))).match(text)
    return m.end() if m else None


def _status_lines(texts: list[str], max_words: int, *, store: bool = False, header: bool = False) -> list[str]:
    """Bagian status dari baris yang cukup pendek. Baris nama pihak lawan (dan nilai di bawah label nama yang berdiri
    sendiri) dilewati, kecuali yang berupa judul status gagal/pending. Frasa bantuan (`_HELP_PHRASE`) dibuang sebelum status dibaca, dan
    pembuangan itu hanya boleh MENGURANGI status: baris yang sejak awal bukan kalimat status ("Untuk transaksi pending atau
    gagal hubungi 14017" dibuka "Untuk") tetap dilewati walau sisa frasanya memuat kata status. Di luar nilai label status
    pembayaran negasi kata tiba dibatasi (`_mask_arrival`; `store`: teks berbaris barang, `has_item_lines`). Kata batal
    (`_CANCEL_WORD`) dibaca sebagai gagal di judul status, nilai label status pembayaran, dan, bila `header` (4 baris
    pertama), baris berstatus saja (`_cancel_as_failed`)."""
    out, name_below = [], False
    for text in texts:
        value = payment_status_value(text)
        if _STATUS_LABEL_WORD.match(text) and value is None:
            name_below = False
            continue                     # "Status Member: Gagal", "Status Pengiriman: Gagal": bukan status pembayaran
        is_name, name_below = name_below, False
        if value is None:
            text = _mask_arrival(text, store=store)
        text = _cancel_as_failed(text, value=value is not None, header=header)
        label_end = _name_label_end(text)
        if label_end is not None:
            text = text[label_end:].strip(" :：")
            name_below = not text
            from_name = True
        else:
            from_name = is_name
        if from_name and not _is_status_title(text):
            continue
        if len(text.split()) > max_words or not _is_status_sentence(text):
            continue
        text = _HELP_PHRASE.sub(" ", text)
        if _is_status_sentence(text):
            part = _status_part(text)
            if from_name and _classify(part) == BERHASIL:   # judul di baris nama: hanya gagal/pending (lihat _NAME_FIELDS)
                continue
            out.append(part)
    return out


def _strongest(texts: list[str]) -> str | None:
    found = {c for c in map(_classify, texts) if c}
    return next((s for s in (GAGAL, PENDING, BERHASIL) if s in found), None)


def _first(texts: list[str]) -> str | None:
    return next((c for c in map(_classify, texts) if c), None)


def read_header_status(lines: list[str]) -> str | None:
    """Hanya tingkat judul (4 baris pertama): `gagal`, `pending`, `berhasil`, atau None. Dipakai pembaca struk belanja
    supaya bukti yang salah rute tetap ketahuan gagalnya; kalimat di badan dan kaki tidak dihitung (judul status
    gagal/pending di badan: `read_body_failure_title`)."""
    cleaned = clean_lines(lines)
    return _strongest(_status_lines(cleaned[:HEADER_LINES], HEADER_WORDS, store=has_item_lines(cleaned), header=True))


def has_header_status_title(lines: list[str]) -> bool:
    """Ada judul status bukti bayar di judul (4 baris pertama): baris yang dihitung `read_header_status` dan sekaligus
    judul status (`_is_status_title`: kata benda transaksi lalu kata status, "Transfer Berhasil", "Pembayaran Gagal",
    "Top Up Sukses"). Kata status di nama toko ("TOKO SUKSES MAKMUR", "Warung Sukses") dibaca `read_header_status`
    sebagai `berhasil`, tetapi bukan judul status, jadi struk belanja biasa tidak memenuhinya."""
    cleaned = clean_lines(lines)
    return any(_is_status_title(part)
               for part in _status_lines(cleaned[:HEADER_LINES], HEADER_WORDS, store=has_item_lines(cleaned), header=True))


def has_status_title(lines: list[str]) -> bool:
    """Ada judul status bukti bayar di baris mana pun (bukan hanya 4 baris pertama), dibaca seperti
    `has_header_status_title`: nama-aware, frasa bantuan dibuang, paling banyak 8 kata. Dipakai `registry.looks_like_proof`
    hanya untuk teks tanpa pola struk belanja: judul di kaki struk belanja sungguhan ("Pembayaran QRIS berhasil",
    "TRANSAKSI BERHASIL" dari mesin EDC) tidak menjadikannya bukti."""
    cleaned = clean_lines(lines)
    return any(_is_status_title(part) for part in _status_lines(cleaned, HEADER_WORDS, store=has_item_lines(cleaned)))


def read_body_failure_title(lines: list[str]) -> str | None:
    """`gagal`/`pending` dari judul status di badan (sesudah 4 baris pertama), untuk pembaca struk belanja dan tidak
    dikenali, yang selain itu hanya membaca judul (`read_header_status`): bukti bayar yang sampai ke sana (saklar mati,
    atau tidak dikenali pembaca bukti) bisa mencetak "Transaksi Gagal" di bawah rinciannya. Hanya judul status
    (`_is_status_title`: kata benda transaksi + kata status, "Transaksi Gagal", "Transfer Diproses", "Payment failed"),
    dibaca seperti `_status_lines`:
    kalimat biasa ("Cetak ulang gagal"), kalimat bantuan/ajakan/tanya ("Info untuk transaksi gagal: 14017", "Transaksi
    gagal? Hubungi kami"), dan judul sukses dari baris nama tidak dihitung. Yang menentukan judul status PERTAMA menurut
    urutan dokumen, seperti badan di `read_status`: judul sukses di 4 baris pertama ("Transfer Berhasil") atau di badan
    ("Transaksi Berhasil") berarti kalimat gagal sesudahnya kaki bukti ("Info transaksi pending/gagal: 14017",
    "Dana transaksi gagal akan dikembalikan"), bukan status bukti ini. `berhasil` tidak pernah dikembalikan."""
    cleaned = clean_lines(lines)
    if has_header_status_title(cleaned):   # judul status di 4 baris pertama yang menentukan (gagal/pending: read_header_status)
        return None
    # Seluruh teks, supaya label nama di judul terbawa ke badan ("Penerima" di baris 4, namanya di baris 5). Judul status
    # dari 4 baris pertama sudah tidak ada (di atas), jadi judul pertama di sini pasti dari badan.
    first = next((part for part in _status_lines(cleaned, HEADER_WORDS, store=has_item_lines(cleaned))
                  if _is_status_title(part)), None)
    status = _classify(first) if first is not None else None
    return status if status in (GAGAL, PENDING) else None


# Nilai label status yang berarti selesai, tanpa kata status biasa (hanya sebagai nilai label "Status").
_DONE_VALUE = re.compile(r"\W*(?:selesai|completed?|done)\W*", re.IGNORECASE)


# Label status PEMBAYARAN: "Status" saja atau dengan kata transaksi/pembayaran/transfer. "Status Member", "Status Poin",
# "Status Pengiriman", "Status Pesanan", "Status Refund", "STATUS SETTLEMENT" bukan status pembayaran ini (A14 r2 re-review).
_PAYMENT_STATUS = re.compile(r"^\s*status(?:\s+(?:transaksi|pembayaran|transfer|transaction|payment))?(?=$|[\s:：])",
                             re.IGNORECASE)


_STATUS_LABEL_WORD = re.compile(r"^\W*status(?!\w)", re.IGNORECASE)


# Kata benda di awal nilai yang berarti status hal lain, bukan pembayaran ("Status: Pesanan Diproses", "Status Member Gold").
_OTHER_STATUS_NOUN = re.compile(
    r"(?:pesanan|order|pengiriman|kiriman|delivery|shipping|member|keanggotaan|membership|poin|point|points|refund|"
    r"pengembalian|settlement|langganan|subscription|voucher|promo|garansi|warranty|cetak|print|stok|stock)(?!\w)",
    re.IGNORECASE)
# Nilai yang menyebut pembayarannya sendiri tetap status pembayaran walau diawali kata benda lain ("Order gagal dibayar",
# "Akun tujuan tidak aktif, transaksi gagal"). Akun/kartu/pelanggan bukan kata benda "hal lain": sarana pembayaran.
_PAYMENT_MENTION = re.compile(
    r"(?<!\w)(?:transaksi|transfer|pembayaran|bayar|dibayar|payment|paid|transaction|dana|uang)(?!\w)", re.IGNORECASE)


def payment_status_value(line: str) -> str | None:
    """Nilai baris label status pembayaran ("" bila labelnya berdiri sendiri), atau None bila bukan baris itu. Labelnya
    "Status" atau "Status Transaksi/Pembayaran/Transfer"; label berkualifikasi lain ("Status Member: …", "STATUS
    SETTLEMENT: …") dan nilai yang diawali kata benda hal lain ("Status: Pesanan Diproses", "Status Pengiriman Gagal",
    "Status Member Gold") bukan status pembayaran. Selain itu nilainya dibaca apa adanya, jadi kata status di mana saja di
    nilai itu berlaku ("Status: Uang gagal dikirim", "Status: Dalam antrian (pending)")."""
    m = _PAYMENT_STATUS.match(line or "")
    if not m:
        return None
    rest = line[m.end():]
    if re.search(r"[:：]", rest):
        head, value = re.split(r"[:：]", rest, maxsplit=1)
        if head.strip():
            return None                  # "Status Member: ...", "STATUS SETTLEMENT: ..."
    else:
        value = rest
    value = value.strip()
    if _OTHER_STATUS_NOUN.match(value) and not _PAYMENT_MENTION.search(value):
        return None
    return value


def read_payment_status(lines: list[str]) -> str | None:
    """Nilai status pembayaran pertama menurut urutan dokumen: sebaris, atau baris di bawah label yang berdiri sendiri
    (bila baris itu bukan label lain)."""
    for i, line in enumerate(lines):
        value = payment_status_value(line)
        if value is None:
            continue
        if value:
            return value
        if i + 1 < len(lines) and lines[i + 1] and not is_label_line(lines[i + 1]):
            return lines[i + 1]
    return None


def read_status(lines: list[str], profile: AppProfile | None = None) -> str:
    """Status dari label "Status" dan judul (4 baris pertama): kata gagal mengalahkan pending mengalahkan berhasil.
    Lalu baris pendek di mana saja: yang pertama menurut urutan dokumen (bukan yang terburuk, supaya baris
    "Gagal" lain di bawah status "Transaksi Berhasil" tidak membalikkannya). Kalimat panjang dan kalimat
    bersyarat/tanya ("Jika gagal hubungi ...", "Gagal? Hubungi kami") tidak dihitung, tapi kegagalan yang
    diikuti ajakan ("Gagal, silakan coba lagi") tetap dihitung (lihat `_is_status_sentence`). Tanpa kata
    status: `berhasil` bila nilai label status "Selesai"/"Completed"/"Done", selain itu `tidak_diketahui` (pembaca bukti:
    lihat `read_proof_status`)."""
    labelled = read_payment_status(lines)
    store = has_item_lines(lines)
    status = (_classify(_cancel_as_failed(labelled, value=True)) if labelled else None) \
        or _strongest(_status_lines(lines[:HEADER_LINES], HEADER_WORDS, store=store, header=True)) \
        or _first(_status_lines(lines, BODY_WORDS, store=store))
    if status is None and labelled and _DONE_VALUE.fullmatch(labelled) \
            and not any(_NOT_DONE.search(line) or _GAGAL.search(line) or _PENDING.search(line) for line in lines):
        status = BERHASIL                # "Status: Selesai" (GoPay), "Status: Completed": paling lemah, kata status lain menang
    return status or TIDAK_DIKETAHUI


# Kata yang berarti transaksi tidak (atau belum) selesai, di luar kosakata status: kalimat resi aplikasi tidak boleh
# menjadikannya berhasil ("Dibatalkan", "Ditolak", "Menunggu", "Dikembalikan" di samping ID, "Pembayaran tertunda").
_NOT_DONE = re.compile(
    r"(?<!\w)(?:(?:di|ter|pem)?batal(?:kan|an)?|(?:di|pe)?tolak(?:an)?|(?:di|ter|pe)?tunda(?:kan|an)?|menunggu|"
    r"dikembalikan|pengembalian|refund(?:ed)?|kedaluwarsa|kadaluarsa|expired|cancel(?:l?ed)?|rejected|reversal)(?!\w)",
    re.IGNORECASE)


STATUS_BLOCK = 4          # baris di bawah label "Status" yang berdiri sendiri


def read_labelled_failure(lines: list[str]) -> str | None:
    """`gagal`/`pending` dari label status ("Status Gagal", "Status: Pending", atau "Status" lalu blok statusnya di
    baris-baris bawah, paling banyak STATUS_BLOCK baris sampai baris label berikutnya: "Gagal transfer uang ke penerima"), yang terburuk dari semua baris berlabel status; selain itu None. Untuk bukti yang dibaca
    jalur struk/tidak dikenali (registry, hanya bila `looks_like_proof`)."""
    cleaned = clean_lines(lines)
    found = set()
    for i, line in enumerate(cleaned):
        inline = payment_status_value(line)
        if inline is None:
            continue
        # Tanpa nilai sebaris: blok status di bawahnya (GoPay: judul lalu langkah-langkah), sampai baris label berikutnya;
        # yang menentukan baris berstatus PERTAMA di blok itu (judulnya), bukan langkah atau kaki sesudahnya.
        # Kata batal dibaca di nilai sebaris dan di baris tepat di bawah label (nilainya); baris blok berikutnya hanya
        # sebagai judul status ("Batal" sebagai tombol di bawah langkah-langkah bukan status).
        values = [inline] if inline else list(itertools.takewhile(lambda v: not is_label_line(v), cleaned[i + 1:i + 1 + STATUS_BLOCK]))
        for k, value in enumerate(values):
            value = _cancel_as_failed(value, value=k == 0)
            if len(value.split()) <= HEADER_WORDS and _is_status_sentence(value):
                found.add(_classify(_status_part(value)))
                break
    return GAGAL if GAGAL in found else PENDING if PENDING in found else None


def has_success_title(lines: list[str]) -> bool:
    """Ada judul status sukses ("Pembayaran Berhasil", "Transaksi berhasil", "Transfer Berhasil") di baris mana pun."""
    cleaned = clean_lines(lines)
    return any(_is_status_title(part) and _classify(part) == BERHASIL
               for part in _status_lines(cleaned, HEADER_WORDS, store=has_item_lines(cleaned)))


def has_item_lines(lines: list[str]) -> bool:
    """Ada baris barang struk ("Roti 15.000", "Kopi Susu 1 25.000"): bukti bayar tidak punya baris barang."""
    return any(_is_item_line(line) for line in clean_lines(lines))


def read_proof_status(lines: list[str], profile: AppProfile | None = None) -> str:
    """Status untuk pembaca bukti (QRIS, transfer): `read_status`, lalu judul status gagal/pending di badan
    (`read_body_failure_title`, seperti jalur struk/tidak dikenali: "Transaksi gagal, dana dikembalikan ke saldo kamu",
    "Transaksi kamu sedang diproses bank tujuan", yang terlalu panjang untuk `read_status`) yang hanya boleh memperburuk
    status. Tanpa status apa pun: `berhasil` bila tercetak kalimat resi aplikasinya (`AppProfile.done_phrases`) dan tidak ada
    kata gagal/pending/belum selesai di mana pun (`_NOT_DONE`), selain itu `tidak_diketahui`."""
    status = read_status(lines, profile)
    body = read_body_failure_title(lines)
    if body == GAGAL or (body == PENDING and status != GAGAL):
        status = body
    if status == TIDAK_DIKETAHUI and profile and profile.done_phrases and count_markers(lines, profile.done_phrases) \
            and not any(_NOT_DONE.search(line) or _ANY_STATUS.search(line) for line in lines):
        status = BERHASIL
    return status


# ── Penjaga struk belanja ───────────────────────────────────────────────────

_CASH_WORD = re.compile(r"(?<![A-Za-z])(?:KEMBALI|KEMBALIAN|TUNAI)(?![A-Za-z])", re.IGNORECASE)
_TOTAL_WORD = re.compile(r"(?<![A-Za-z])TOTAL(?![A-Za-z])", re.IGNORECASE)
_SUBTOTAL = re.compile(r"SUB\s*-?\s*TOTAL", re.IGNORECASE)
# Baris cara bayar sesudah total: "QRIS 40.000", "Pembayaran QRIS Rp 40.000", "Non Tunai (QRIS) 45.400", "DEBIT BCA 45.400".
# Angka di ujung baris harus nominal yang SAMA dengan total (RRN, nomor referensi, kartu tersamar, nomor rekening bukan).
_PAYMENT_LINE = re.compile(
    r"^\W*(?:(?:pembayaran|bayar|payment|non\s+tunai)\s+)?\(?(?:qris|debit|kredit|credit|e-?money|flazz|brizzi|tapcash)\)?"
    r"(?P<rest>[^\d]{0,20}(?:Rp\.?\s*)?\d[\d.,]*)\s*$", re.IGNORECASE)
# Kata awal baris bukti bayar yang bukan nama barang, walau berbentuk "kata + nominal": subtotal, harga, tip, tagihan,
# top up, saldo, dan sejenisnya. Kata utuh di awal baris ("Tipe Roti" tetap barang).
_NON_ITEM_HEAD = re.compile(
    r"^\W*(?:sub\s*-?\s*total|harga|tips?|tagihan|top[\s-]?up|isi\s+saldo|saldo|kode\s+unik|cashback|pembulatan|materai|"
    r"pembayaran|payment|bayar)(?![A-Za-z])", re.IGNORECASE)
_NUMBER_ONLY = re.compile(r"(?:Rp\.?\s*)?[\d.,]+", re.IGNORECASE)
_QTY = re.compile(r"\d{1,2}(?:[.,]\d{1,3})?")          # kuantitas: 1-2 angka (boleh desimal "0,5"); kelompok 3-4 angka = nomor rekening
_PRICE = re.compile(r"(?:Rp\.?\s*)?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|Rp\.?\s*\d+", re.IGNORECASE)   # harga: ada pemisah ribuan atau awalan Rp
MIN_STORE_ITEMS = 3        # barang tanpa kuantitas sebelum total
MIN_QTY_ITEMS = 2          # baris "NAMA QTY HARGA" (bukti bayar tidak pernah memakai bentuk ini)


def _is_item_line(line: str) -> bool:
    """Baris barang struk: nama (>= 3 huruf, "Rp" tidak dihitung) lalu nominal di ujung. Baris berlabel
    bukti bayar (Nominal, Biaya, Subtotal, Harga, Tip, Top Up, Rekening, ...) dan baris tanggal bukan barang."""
    if is_label_line(line) or _NON_ITEM_HEAD.match(line) or parse_datetime_id(line):
        return False
    tokens = line.split()
    if len(tokens) < 2 or not amounts_in(tokens[-1]):
        return False
    name = re.sub(r"\bRP\b", " ", " ".join(tokens[:-1]).upper())
    return sum(c.isalpha() for c in name) >= 3


def _is_qty_item_line(line: str) -> bool:
    """Barang dengan kuantitas kecil di antara nama dan harga: "KOPI SUSU 1 25.000", "ROTI 2 x 15.000", "TEPUNG 0,5 12.500".
    Harga harus bernominal wajar dengan pemisah ribuan atau awalan Rp: kelompok nomor rekening ("BCA 123 456 7890")
    bukan barang."""
    if not _is_item_line(line):
        return False
    tokens = line.split()
    if len(tokens) < 3:
        return False
    price = tokens[-1] if not re.fullmatch(r"(?:Rp\.?)", tokens[-2], re.IGNORECASE) else f"{tokens[-2]} {tokens[-1]}"
    qty_at = -3 if price != tokens[-1] else -2
    if tokens[qty_at].lower() == "x" and len(tokens) >= abs(qty_at) + 2:
        qty_at -= 1
    qty = tokens[qty_at].rstrip("xX")
    return bool(_QTY.fullmatch(qty) and _PRICE.fullmatch(price) and amounts_in(price))


# Kata TUNAI/KEMBALI lalu hanya pemisah, "(QRIS)", dan mata uang sampai nominal di ujung baris. Kalimat yang sekadar
# menyebut kata itu ("Dana Rp50.000 akan kembali ke rekening Anda", "Kembali ke halaman utama 2026", "Tarik tunai di
# 1.000 ATM") bukan baris tunai.
_CASH_LINE = re.compile(
    r"(?<![A-Za-z])(?:KEMBALI|KEMBALIAN|TUNAI)(?![A-Za-z])[\s:：.=]*(?:\([^)]*\)[\s:：.=]*)?(?:(?:Rp|IDR)\.?\s*)?[\d.,]*\d(?:\s*(?:Rp|IDR)\.?)?\s*$",
    re.IGNORECASE)


def _is_cash_line(line: str) -> bool:
    """Baris tunai/kembalian ("TUNAI 50.000", "TUNAI 50.000 IDR", "KEMBALI : 0", "Non Tunai (QRIS) 45.400").
    Baris catatan ("Berita titip tunai 2") dan tombol ("Kembali ke Beranda") bukan."""
    return bool(_CASH_LINE.search(line)) and not is_label_line(line, fields=("note",))


def _total_amounts(lines: list[str], total_at: int) -> list[int]:
    """Nominal di baris total, atau di baris sesudahnya bila nilai berada di bawah label dan baris itu murni angka
    (baris cara bayar sesudah "Total" tidak boleh terbaca sebagai nilai total)."""
    found = amounts_in(lines[total_at])
    if not found and total_at + 1 < len(lines) and _NUMBER_ONLY.fullmatch(lines[total_at + 1]):
        found = amounts_in(lines[total_at + 1])
    return found


def _is_payment_line_for(line: str, totals: list[int]) -> bool:
    """Baris cara bayar yang nominalnya sama dengan total ("QRIS 40.000" sesudah "Total 40.000")."""
    m = _PAYMENT_LINE.match(line)
    return bool(m and any(a in totals for a in amounts_in(m.group("rest"))))


def looks_like_store_receipt(lines: list[str]) -> bool:
    """Pola struk belanja; bukti QRIS dan transfer tidak pernah memakainya, jadi pembaca bukti menolak
    dokumen seperti ini (skor 0). Salah satu dari:
    - baris tunai/kembalian berangka;
    - >= 3 baris barang sebelum baris total;
    - >= 2 baris "NAMA QTY HARGA" di mana saja;
    - >= 1 baris "NAMA QTY HARGA" sebelum baris total dan sesudahnya baris cara bayar ("QRIS 40.000") bernominal sama dengan total.
    Baris berlabel bukti (Subtotal, Harga, Tip, Top Up, Nominal, ...) tidak pernah dihitung barang.
    Struk toko kecil (1-2 barang) yang dibayar QRIS dan mencetak NMID/Terminal ID masuk pola ini."""
    if any(_is_cash_line(line) for line in lines):
        return True
    total_at = next((i for i, line in enumerate(lines) if _TOTAL_WORD.search(line) and not _SUBTOTAL.search(line)), None)
    before = lines if total_at is None else lines[:total_at]
    items = sum(_is_item_line(line) for line in before)
    if items >= MIN_STORE_ITEMS or sum(_is_qty_item_line(line) for line in lines) >= MIN_QTY_ITEMS:
        return True
    # Baris "NAMA harga" tak berkuantitas bisa saja biaya tambahan bukti ("Donasi Rp2.000", "Layanan Rp1.000"), jadi
    # untuk aturan baris-cara-bayar hanya baris berkuantitas yang dihitung barang.
    if total_at is None or not any(_is_qty_item_line(line) for line in before):
        return False
    totals = _total_amounts(lines, total_at)
    return any(_is_payment_line_for(line, totals) for line in lines[total_at + 1:])


# Nama publik untuk modul lain (kotak_struk/kerangka.py, tes impornya di test_kotak_kerangka): jangan dihapus atau
# diganti nama tanpa memperbarui pemakainya.
classify_status = _classify
STATUS_TITLE = _STATUS_TITLE
