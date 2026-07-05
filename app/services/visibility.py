"""Kontrak visibilitas household — SATU-SATUNYA pintu untuk menyajikan
deskripsi transaksi lintas-anggota (spec 2026-07-05 §4).

Kontrak:
- Amplop personal (owner_id terisi): seluruh data hanya terlihat pemilik
  (di-enforce di level query oleh route; modul ini mengurus deskripsi).
- Amplop shared: semua anggota melihat semua transaksi penuh, KECUALI
  deskripsi transaksi is_private=True milik anggota lain -> "Transaksi privat".
  Nominal, tanggal, amplop, dan identitas pencatat TETAP terlihat.
- Agregat (saldo, spent, KPI, count) selalu menghitung semua transaksi.
- Fail-closed: data janggal/ambigu -> sembunyikan deskripsi.

masked_description() adalah primitive WAJIB untuk semua permukaan.
present_transaction() adalah serializer default untuk route API; permukaan
lain boleh punya serializer sendiri selama deskripsi lewat masked_description().
"""

PRIVATE_PLACEHOLDER = "Transaksi privat"


def can_view_description(viewer_id, txn) -> bool:
    txn_user_id = getattr(txn, "user_id", None)
    if viewer_id is None or txn_user_id is None:
        return False
    if str(txn_user_id) == str(viewer_id):
        return True
    # fail-closed: is_private tidak ada / None -> anggap privat
    is_private = getattr(txn, "is_private", None)
    if is_private is None:
        return False
    return not bool(is_private)


def masked_description(viewer_id, txn) -> str:
    if can_view_description(viewer_id, txn):
        return txn.description
    return PRIVATE_PLACEHOLDER


def present_transaction(viewer_id, txn) -> dict:
    return {
        "id": txn.id,
        "envelope_id": txn.envelope_id,
        "user_id": txn.user_id,
        "amount": txn.amount,
        "description": masked_description(viewer_id, txn),
        "source": txn.source,
        "transaction_date": txn.transaction_date,
        "created_at": txn.created_at,
        "is_deleted": txn.is_deleted,
        "is_private": bool(getattr(txn, "is_private", False)),
        "is_own": str(getattr(txn, "user_id", "")) == str(viewer_id or ""),
    }
