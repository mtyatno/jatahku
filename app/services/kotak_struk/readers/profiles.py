"""Profil aplikasi (bank, e-wallet) untuk pembaca QRIS dan transfer. Data, bukan kode:
kata pengenal aplikasi (penerbit) dan sinonim label per field. Menambah aplikasi biasanya
cukup menambah satu entri di PROFILES; label khusus aplikasi diisi dari korpus nyata (Task A14)."""
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


# Sinonim label per field; urutan = prioritas. Daftar rencana tetap ada (dalam urutan yang sama);
# varian dekat ("Nama Penerima", "Nomor Rekening", "Nomor Referensi", ...) ditambahkan di antaranya.
# Kunci di luar rencana: `sender`, `status` (pembaca transfer), `discount`, `tax` (cek silang nominal).
GENERIC_LABELS: dict[str, list[str]] = {
    "amount": ["nominal", "jumlah", "jumlah pembayaran", "total bayar", "total pembayaran", "total", "amount"],
    "fee": ["biaya admin", "biaya", "admin", "fee"],
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
}

PROFILES: list[AppProfile] = [
    AppProfile("bca_mobile", "BCA mobile", ["bca", "m-bca", "mybca"]),
    AppProfile("livin", "Livin' by Mandiri", ["livin", "mandiri"]),
    AppProfile("brimo", "BRImo", ["brimo", "bri"]),
    AppProfile("bni", "BNI Mobile (wondr)", ["wondr", "bni"]),
    AppProfile("bsi", "BSI Mobile", ["bsi", "byond"]),
    AppProfile("jago", "Bank Jago", ["jago"]),
    AppProfile("seabank", "SeaBank", ["seabank"]),
    AppProfile("blu", "blu by BCA Digital", ["blu"]),
    AppProfile("gopay", "GoPay", ["gopay"]),
    AppProfile("ovo", "OVO", ["ovo"]),
    AppProfile("dana", "DANA", ["dana"]),
    AppProfile("shopeepay", "ShopeePay", ["shopeepay"]),
]

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
