"""Cek silang dan arah uang untuk Dokumen Bayar.

Cek status (`status_gagal` memblokir, `status_pending` memperingatkan) berlaku untuk SEMUA jenis dokumen: pemblokiran
transaksi gagal tidak boleh bergantung pada pembaca mana yang menang di registri. Cek lain (nominal, tanggal) dan arah
uang hanya untuk bukti bayar (QRIS, transfer): jalur scan struk lama tidak punya cek itu, dan tanggal struk yang lama
tidak boleh tiba-tiba diberi peringatan."""
import re

from app.services.kotak_struk.config import OLD_PROOF_DAYS, PROOF_TYPES
from app.services.kotak_struk.merchants import normalize_name
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed
from app.services.kotak_struk.readers.labels import WIB

_RANK = {"rendah": 0, "sedang": 1, "tinggi": 2}


def _lower_confidence(confidence: dict, key: str, level: str) -> None:
    """Turunkan keyakinan `key` ke `level`; yang sudah lebih rendah tidak dinaikkan."""
    if _RANK.get(confidence.get(key), len(_RANK)) > _RANK[level]:
        confidence[key] = level


def common_checks(parsed: Parsed, ctx: ParseContext) -> list[Check]:
    """Status (semua jenis dokumen), lalu nominal dan tanggal (bukti bayar saja). Menurunkan `confidence`
    pada dokumen bila perlu."""
    doc = parsed.doc
    found: list[Check] = []
    proof = doc.doc_type in PROOF_TYPES
    a = doc.amounts
    if proof and a.subtotal is not None and a.total is not None and a.subtotal + a.fee + a.tax - a.discount != a.total:
        found.append(Check("selisih_nominal", "warn", "Nominal + biaya tidak sama dengan total"))
        _lower_confidence(doc.confidence, "total", "sedang")
    if doc.status == "gagal":
        found.append(Check("status_gagal", "block", "Transaksi gagal, tidak bisa dicatat"))
    elif doc.status == "pending":
        found.append(Check("status_pending", "warn", "Transaksi masih diproses bank"))
    if proof and doc.paid_at:
        paid_on = doc.paid_at.astimezone(WIB).date() if doc.paid_at.tzinfo else doc.paid_at.date()
        if paid_on > ctx.today:
            found.append(Check("tanggal_depan", "warn", "Tanggal di bukti ada di masa depan"))
            _lower_confidence(doc.confidence, "paid_at", "rendah")
        elif (ctx.today - paid_on).days > OLD_PROOF_DAYS:
            found.append(Check("bukti_lama", "warn", f"Bukti ini lebih dari {OLD_PROOF_DAYS} hari lalu"))
    return found


def same_person(user_name: str | None, name: str | None) -> bool:
    """Nama "mirip user": sama, atau >= 2 kata nama user ada di nama itu."""
    user, other = normalize_name(user_name), normalize_name(name)
    if not user or not other:
        return False
    return user == other or len(set(user.split()) & set(other.split())) >= 2


# Kata yang disamarkan aplikasi: huruf awal lalu x berulang atau bintang ("Axxxxxxx", "ANDI***", "SITI********").
_MASKED_WORD = re.compile(r"([A-Za-z]+?)(?:[xX]{2,}|[*•]+)")


def may_be_user(user_name: str | None, name: str | None) -> bool:
    """Nama (mungkin disamarkan aplikasi) bisa jadi nama user: setiap kata yang terlihat ada di nama user, dan kata yang
    disamarkan ("ANDI ********", "ANDI*** PRATA***", "Axxx Pxxxxxx") cocok dengan awal kata nama user. Kata tanpa huruf
    (bintang, hasil OCR bintang) tidak dihitung. Tanpa kata terlihat: tidak."""
    user_words = normalize_name(user_name).split()
    words = [w for w in (name or "").split() if re.search(r"[A-Za-z]", w)]
    if not user_words or not words:
        return False
    for word in words:
        masked = _MASKED_WORD.fullmatch(word)
        if masked:
            if not any(u.startswith(masked.group(1).lower()) for u in user_words):
                return False
        elif normalize_name(word) not in user_words:
            return False
    return True


def apply_flow(parsed: Parsed, ctx: ParseContext) -> None:
    """Transfer keluar ke penerima yang "mirip user" (`same_person`) -> `flow = antar_rekening_sendiri`. Hanya pertanyaan
    ke user, tidak pernah otomatis. (Penerima mirip user tetapi pengirimnya orang lain = uang masuk: pembaca transfer.)"""
    doc = parsed.doc
    if doc.doc_type != "transfer" or doc.flow != "keluar":
        return
    if same_person(ctx.user_name, doc.counterparty.name):
        doc.flow = "antar_rekening_sendiri"
        doc.evidence.append("Nama penerima mirip nama akun kamu")
