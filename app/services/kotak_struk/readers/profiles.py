"""Profil aplikasi (bank, e-wallet) untuk pembaca QRIS dan transfer. Data, bukan kode:
kata pengenal aplikasi (penerbit) dan sinonim label per field. Menambah aplikasi biasanya
cukup menambah satu entri di PROFILES; label dan tata letak khusus aplikasi diisi dari korpus nyata (Task A14)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.kotak_struk.readers.labels import count_markers


@dataclass
class AppProfile:
    key: str                                    # disimpan di Dokumen Bayar sebagai `issuer`
    label: str                                  # nama untuk manusia
    markers: list[str]                          # kata pengenal aplikasi di bukti
    labels: dict[str, list[str]] = field(default_factory=dict)   # sinonim label khusus aplikasi, per field
    # Tata letak: pihak lawan dicetak tanpa label sebagai baris pertama di bawah logo, sebelum nominal (nama, lalu kota
    # untuk QRIS atau "Bank/e-wallet · nomor" untuk transfer); lihat proof_common.read_header_party.
    party_on_top: bool = False
    # Kalimat yang aplikasi ini cetak pada bukti transaksi yang selesai. Hanya dipakai bila tidak ada kata status sama
    # sekali (gagal/pending selalu menang; lihat proof_common.read_status).
    done_phrases: list[str] = field(default_factory=list)


# Sinonim label per field; urutan = prioritas. Daftar rencana tetap ada (dalam urutan yang sama);
# varian dekat ("Nama Penerima", "Nomor Rekening", "Nomor Referensi", ...) ditambahkan di antaranya.
# Kunci di luar rencana: `sender`, `status` (pembaca transfer), `discount`, `tax`, `extra` (cek silang nominal).
GENERIC_LABELS: dict[str, list[str]] = {
    "amount": ["nominal", "jumlah", "jumlah pembayaran", "total bayar", "total pembayaran", "total", "amount"],
    "fee": ["biaya admin", "biaya", "admin", "fee"],
    # Tambahan di atas nominal yang ikut masuk total seperti biaya. Terpisah dari `fee` karena kata awalnya juga kata biasa
    # ("TIP TOP SWALAYAN", "DONASI KITA BERSAMA"): baris berawalan ini tidak dianggap baris label saat nilai label lain hilang.
    "extra": ["tips", "tip", "service fee", "service charge", "layanan", "ongkir", "donasi"],
    "discount": ["diskon", "potongan", "promo", "voucher", "discount"],
    "tax": ["pajak", "ppn", "pb1", "tax"],
    "merchant": ["merchant", "nama merchant", "nama penerima", "penerima", "nama tujuan", "tujuan", "ke"],
    "city": ["lokasi", "kota"],
    "ref": ["no. referensi", "no referensi", "nomor referensi", "referensi", "no. ref", "no ref", "ref", "rrn", "reference no",
            "id transaksi", "no. transaksi", "no transaksi", "nomor transaksi", "transaction id"],
    "nmid": ["nmid"],
    "account": ["rekening tujuan", "nomor rekening tujuan", "no. rekening tujuan", "no rekening tujuan", "rekening penerima",
                "no. rekening", "no rekening", "nomor rekening", "rekening"],
    "bank": ["bank tujuan", "bank penerima", "bank"],
    "note": ["berita transfer", "berita", "keterangan", "catatan"],
    "sender": ["nama pengirim", "pengirim", "dari"],
    "status": ["status transaksi", "status"],
    # Rekening/akun user sendiri. Tidak dibaca sebagai field; barisnya label (bukan nama, barang, atau nilai label lain).
    "source": ["sumber akun", "sumber dana", "rekening sumber", "sumber rekening", "rekening asal"],
}

PROFILES: list[AppProfile] = [
    AppProfile("bca_mobile", "BCA mobile", ["bca", "m-bca", "mybca"]),
    AppProfile("livin", "Livin' by Mandiri", ["livin", "mandiri"]),
    AppProfile("brimo", "BRImo", ["brimo", "bri"]),
    AppProfile("bni", "BNI Mobile (wondr)", ["wondr", "bni"]),
    AppProfile("bsi", "BSI Mobile", ["bsi", "byond"]),
    # Dikalibrasi A14 ronde 1 (5 bukti asli Jago Syariah: QRIS, transfer ke e-wallet dan bank, PLN, pulsa).
    AppProfile("jago", "Bank Jago", ["jago"], labels={"ref": ["id transaksi", "nomor referensi"]}, party_on_top=True,
               done_phrases=["resi ini merupakan bukti transaksi yang sah"]),
    AppProfile("seabank", "SeaBank", ["seabank"]),
    AppProfile("blu", "blu by BCA Digital", ["blu"]),
    AppProfile("gopay", "GoPay", ["gopay"]),
    AppProfile("ovo", "OVO", ["ovo"]),
    AppProfile("dana", "DANA", ["dana"]),
    AppProfile("shopeepay", "ShopeePay", ["shopeepay"]),
]

# Bank dan e-wallet yang bisa jadi tujuan transfer (selain penanda di PROFILES). Data: baris "GoPay · 0812…" atau
# "Mandiri · 123…" di bawah nama penerima berarti transfer; "PLN Prepaid · 5500…" atau "Indosat · 0815…" tagihan/pulsa.
MONEY_PROVIDERS = [
    "bank", "bca", "mandiri", "bri", "bni", "bsi", "btn", "cimb", "niaga", "permata", "danamon", "mega", "ocbc", "maybank",
    "panin", "btpn", "jenius", "uob", "hsbc", "sinarmas", "bjb", "bpd", "nagari", "muamalat", "neo", "allo", "superbank",
    "krom", "linkaja", "isaku", "sakuku", "flip",
]


# Kata yang boleh menyertai nama aplikasi di baris logo ("Jago Syariah", "livin' by mandiri", "BCA mobile", "Bank Jago").
LOGO_WORDS = {"syariah", "by", "mobile", "bank", "digital", "app", "banking"}


def logo_profile(line: str) -> AppProfile | None:
    """Profil aplikasi bila baris ini baris logo: hanya nama aplikasi (penanda profil) dan kata pendamping LOGO_WORDS.
    Nama usaha yang memuat kata bank/aplikasi ("TOKO MANDIRI JAYA", "KANTIN BNI", "JAGO COFFEE") bukan logo."""
    words = [w.strip("'") for w in re.findall(r"[a-z0-9][a-z0-9'.-]*", (line or "").lower())]
    words = [w for w in words if w]
    markers = {m for p in PROFILES for m in p.markers}
    if not words or not any(w in markers for w in words) or any(w not in markers | LOGO_WORDS for w in words):
        return None
    return detect_issuer([line])


def is_money_provider(name: str | None) -> bool:
    """Nama penyedia ("GoPay", "Mandiri", "Bank Jago Syariah") adalah bank atau e-wallet."""
    words = set(re.findall(r"[a-z][a-z'-]*", (name or "").lower()))
    known = {w for p in PROFILES for w in p.markers} | set(MONEY_PROVIDERS)
    return bool(words & known)


# Baris "Penyedia · nomor" di bawah nama pihak lawan ("Mandiri·…4321", "Bank Jago Syariah•", "GoPay · 0812…"): bank
# di sana milik pihak lawan, bukan aplikasi yang dipakai user. Diawali huruf (baris tanggal "29 Okt 2026·19:35" tidak).
PROVIDER_LINE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9'&.\- ]*?)\s*[·•]\s*(?P<rest>.*?)\s*$")

# Kata "dana" juga kata biasa ("Dana Masuk", "Terima Dana"); bukan penanda aplikasi DANA.
_COMMON_PHRASES = re.compile(
    r"(?<!\w)(dana\s+(masuk|keluar|tersedia|anda|diterima)|(terima|menerima|sumber)\s+dana)(?!\w)", re.IGNORECASE)
# Baris tentang pihak lawan (bank/rekening tujuan, penerima, pengirim): bank atau nama di sana
# bukan aplikasi yang dipakai user ("Bank Tujuan BCA" tidak berarti bukti ini dari BCA mobile).
_COUNTERPARTY_LABELS = ["bank tujuan", "bank penerima", "rekening tujuan", "rekening penerima", "nama merchant", "merchant",
                        "nama penerima", "penerima", "nama tujuan", "tujuan", "ke", "nama pengirim", "pengirim", "dari"]
_COUNTERPARTY_LINE = re.compile(
    r"^\s*(?:" + "|".join(r"\s+".join(re.escape(part) for part in label.split()) for label in _COUNTERPARTY_LABELS)
    + r")(?=$|[\s:：])(.*)$", re.IGNORECASE)


def _issuer_lines(lines: list[str]) -> list[str]:
    """Baris yang boleh jadi petunjuk penerbit: tanpa baris pihak lawan (dan nilainya di baris
    bawah bila labelnya berdiri sendiri) dan tanpa frasa "dana" biasa."""
    out, skip_next = [], False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        m = _COUNTERPARTY_LINE.match(line)
        if m:
            skip_next = not m.group(1).strip()
            continue
        if PROVIDER_LINE.match(line):
            continue
        out.append(_COMMON_PHRASES.sub(" ", line))
    return out


def detect_issuer(lines: list[str]) -> AppProfile | None:
    """Profil dengan penanda terbanyak; seri dimenangkan yang lebih dulu di PROFILES."""
    usable = _issuer_lines(lines)
    best, best_count = None, 0
    for profile in PROFILES:
        found = count_markers(usable, profile.markers)
        if found > best_count:
            best, best_count = profile, found
    return best


def labels_for(profile: AppProfile | None, field: str) -> list[str]:
    """Sinonim label untuk `field`: label profil dulu, lalu generik (tanpa duplikat)."""
    own = profile.labels.get(field, []) if profile else []
    seen: set[str] = set()
    out = []
    for label in [*own, *GENERIC_LABELS.get(field, [])]:
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out
