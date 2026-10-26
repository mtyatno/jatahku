"""Cek silang dan arah uang untuk Dokumen Bayar.

Cek status (`status_gagal` memblokir, `status_pending` memperingatkan) berlaku untuk SEMUA jenis dokumen: pemblokiran
transaksi gagal tidak boleh bergantung pada pembaca mana yang menang di registri. Cek lain (nominal, tanggal) dan arah
uang hanya untuk bukti bayar (QRIS, transfer): jalur scan struk lama tidak punya cek itu, dan tanggal struk yang lama
tidak boleh tiba-tiba diberi peringatan."""
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


def apply_flow(parsed: Parsed, ctx: ParseContext) -> None:
    """Transfer keluar ke penerima yang "mirip user" (nama sama, atau >= 2 kata nama user ada di
    nama penerima) -> `flow = antar_rekening_sendiri`. Hanya pertanyaan ke user, tidak pernah otomatis."""
    doc = parsed.doc
    if doc.doc_type != "transfer" or doc.flow != "keluar":
        return
    user, recipient = normalize_name(ctx.user_name), normalize_name(doc.counterparty.name)
    if not user or not recipient:
        return
    if user == recipient or len(set(user.split()) & set(recipient.split())) >= 2:
        doc.flow = "antar_rekening_sendiri"
        doc.evidence.append("Nama penerima mirip nama akun kamu")
