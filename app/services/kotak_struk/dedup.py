"""Deteksi duplikat Kotak Struk, lapis 1-3 (spec 2026-10-26 bagian 3d).

Lapis 1 (upload_id) dan lapis 2 pertama (file yang sama, belum selesai) dipakai
intake untuk mengembalikan item yang sudah ada. `recorded_duplicate` dan
`pending_ref_duplicate` dipakai pemrosesan (worker) untuk memberi tanda pada
item baru. `soft_duplicate` (lapis lunak: transaksi manual yang mirip) dipakai `view.item_detail`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Envelope, ReceiptScan, Transaction, User
from app.services.kotak_struk.config import OPEN_STATUSES, SOFT_DUP_WINDOW, ST_SIAP, ST_TERCATAT
from app.services.kotak_struk.readers.labels import WIB
from app.services.visibility import masked_description


async def find_by_upload(db: AsyncSession, user_id: uuid.UUID, upload_id: str) -> ReceiptScan | None:
    """Lapis 1: item user ini dengan upload_id yang sama (unggahan ulang / ketuk dua kali)."""
    return (await db.execute(
        select(ReceiptScan)
        .where(ReceiptScan.user_id == user_id, ReceiptScan.upload_id == upload_id)
        .limit(1)
    )).scalar_one_or_none()


async def find_open_by_file(db: AsyncSession, user_id: uuid.UUID, sha: str) -> ReceiptScan | None:
    """Lapis 2: item user ini yang belum selesai (diterima/diproses/siap) dengan isi file yang sama."""
    return (await db.execute(
        select(ReceiptScan)
        .where(ReceiptScan.user_id == user_id, ReceiptScan.file_sha256 == sha,
               ReceiptScan.status.in_(OPEN_STATUSES))
        .order_by(ReceiptScan.created_at, ReceiptScan.id)
        .limit(1)
    )).scalars().first()


def _listed_transactions(raw) -> list[uuid.UUID]:
    """Id transaksi di `transaction_ids` item tercatat. Kosong bila NULL, bukan daftar, atau ada isi yang bukan UUID:
    tidak bisa dipastikan transaksinya sudah dihapus, jadi item tetap dihitung tercatat."""
    if not isinstance(raw, list):
        return []
    try:
        return [uuid.UUID(str(value)) for value in raw]
    except ValueError:
        return []


async def _recorded_by(db: AsyncSession, household_id: uuid.UUID, column, value: str,
                       exclude_id: uuid.UUID | None) -> uuid.UUID | None:
    """Item `tercatat` tertua (`created_at`, `id`) dengan `column == value` yang belum dilepas. Dilepas: semua
    transaksi di `transaction_ids` sudah dihapus atau tidak ada lagi (user menghapus catatannya, jadi bukti yang sama
    boleh dicatat lagi). `transaction_ids` kosong/NULL tetap tercatat (fail closed): bukti menjadi `tercatat` lewat
    klaim di commit yang sama dengan transaksinya dan id-nya baru ditambahkan `mark_recorded` sesudahnya, jadi daftar
    kosong bisa berarti transaksinya ada. Tanpa fungsi JSON SQL (SQLite di tes, Postgres di produksi): kandidat dibaca
    berurutan, lalu satu SELECT transaksi yang masih hidup di antara id mereka."""
    q = select(ReceiptScan.id, ReceiptScan.transaction_ids).where(
        ReceiptScan.household_id == household_id, ReceiptScan.status == ST_TERCATAT, column == value)
    if exclude_id is not None:
        q = q.where(ReceiptScan.id != exclude_id)
    candidates = [(item_id, _listed_transactions(raw)) for item_id, raw in
                  (await db.execute(q.order_by(ReceiptScan.created_at, ReceiptScan.id))).all()]
    listed = sorted({txn_id for _, ids in candidates for txn_id in ids})
    # uuid.UUID(str(...)): tipe UUID dari driver (asyncpg) belum tentu sama dengan uuid.UUID di himpunan
    live = {uuid.UUID(str(txn_id)) for txn_id in (await db.execute(
        select(Transaction.id).where(Transaction.id.in_(listed), Transaction.is_deleted == False)  # noqa: E712
    )).scalars()} if listed else set()
    return next((item_id for item_id, ids in candidates if not ids or not live.isdisjoint(ids)), None)


async def recorded_duplicate(db: AsyncSession, household_id: uuid.UUID | None, *, file_sha: str | None,
                             ref_hash: str | None, exclude_id: uuid.UUID | None) -> dict | None:
    """Lapis 2 (file) dan 3 (ref): item `tercatat` di rumah tangga yang sama yang belum dilepas (`_recorded_by`:
    item yang semua transaksinya dihapus tidak dihitung). Pencatatan item ini harus diblokir. File dicek lebih dulu.
    Tanpa rumah tangga tidak ada cakupan."""
    if household_id is None:
        return None
    if file_sha:
        found = await _recorded_by(db, household_id, ReceiptScan.file_sha256, file_sha, exclude_id)
        if found:
            return {"kind": "file", "item_id": str(found), "recorded": True}
    if ref_hash:
        found = await _recorded_by(db, household_id, ReceiptScan.ref_hash, ref_hash, exclude_id)
        if found:
            return {"kind": "ref", "item_id": str(found), "recorded": True}
    return None


async def pending_ref_duplicate(db: AsyncSession, household_id: uuid.UUID | None, ref_hash: str | None,
                                exclude_id: uuid.UUID | None) -> dict | None:
    """Lapis 3: nomor referensi yang sama dengan item `siap` milik anggota rumah tangga LAIN
    (pemilik `exclude_id` tidak dihitung). Hanya peringatan "juga dibagikan {nama}"."""
    if household_id is None or not ref_hash:
        return None
    q = (select(ReceiptScan.id, User.name)
         .join(User, User.id == ReceiptScan.user_id)
         .where(ReceiptScan.household_id == household_id, ReceiptScan.ref_hash == ref_hash,
                ReceiptScan.status == ST_SIAP))
    if exclude_id is not None:
        q = q.where(ReceiptScan.id != exclude_id)
        own = (await db.execute(select(ReceiptScan.user_id).where(ReceiptScan.id == exclude_id))).scalars().first()
        if own is not None:
            q = q.where(ReceiptScan.user_id != own)
    row = (await db.execute(q.order_by(ReceiptScan.created_at, ReceiptScan.id).limit(1))).first()
    if row is None:
        return None
    return {"kind": "ref", "item_id": str(row[0]), "recorded": False, "by": row[1]}


async def soft_duplicate(db: AsyncSession, household_id: uuid.UUID | None, *, amount: int, paid_at: datetime,
                         viewer_id: uuid.UUID | None = None) -> dict | None:
    """Lapis lunak: transaksi tidak terhapus di rumah tangga dengan nominal yang sama, tanggal transaksi sama dengan
    tanggal bayar (WIB, seperti `parsed_date` worker), dan dicatat dalam +/- SOFT_DUP_WINDOW dari `paid_at`.
    Hanya peringatan "mirip ... yang dicatat ...". Hanya yang boleh dilihat `viewer_id` (kontrak visibilitas):
    amplop pribadi anggota lain tidak dihitung, dan deskripsi transaksi privat anggota lain disamarkan. Tanpa
    `viewer_id` yang dikenal hasilnya fail-closed (hanya amplop bersama, deskripsi disamarkan). `paid_at` tanpa zona
    dianggap UTC."""
    if household_id is None or not amount:
        return None
    paid_at = paid_at if paid_at.tzinfo is not None else paid_at.replace(tzinfo=timezone.utc)
    visible = Envelope.owner_id.is_(None)
    if viewer_id is not None:
        visible = or_(visible, Envelope.owner_id == viewer_id)
    row = (await db.execute(
        select(Transaction, Envelope.name)
        .join(Envelope, Envelope.id == Transaction.envelope_id)
        .where(Envelope.household_id == household_id, visible, Transaction.is_deleted == False,  # noqa: E712
               Transaction.amount == amount, Transaction.transaction_date == paid_at.astimezone(WIB).date(),
               Transaction.created_at >= paid_at - SOFT_DUP_WINDOW, Transaction.created_at <= paid_at + SOFT_DUP_WINDOW)
        .order_by(Transaction.created_at, Transaction.id)
        .limit(1)
    )).first()
    if row is None:
        return None
    txn, envelope_name = row
    return {"kind": "soft", "transaction": {
        "id": str(txn.id), "description": masked_description(viewer_id, txn), "amount": int(txn.amount),
        "created_at": txn.created_at.isoformat(), "envelope_name": envelope_name}}
