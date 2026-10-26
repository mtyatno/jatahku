"""Deteksi duplikat Kotak Struk, lapis 1-3 (spec 2026-10-26 bagian 3d).

Lapis 1 (upload_id) dan lapis 2 pertama (file yang sama, belum selesai) dipakai
intake untuk mengembalikan item yang sudah ada. `recorded_duplicate` dan
`pending_ref_duplicate` dipakai pemrosesan (worker) untuk memberi tanda pada
item baru. Lapis lunak (transaksi manual yang mirip) ada di modul lain.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ReceiptScan, User
from app.services.kotak_struk.config import OPEN_STATUSES, ST_SIAP, ST_TERCATAT


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


async def _recorded_by(db: AsyncSession, household_id: uuid.UUID, column, value: str,
                       exclude_id: uuid.UUID | None) -> uuid.UUID | None:
    q = select(ReceiptScan.id).where(
        ReceiptScan.household_id == household_id, ReceiptScan.status == ST_TERCATAT, column == value)
    if exclude_id is not None:
        q = q.where(ReceiptScan.id != exclude_id)
    return (await db.execute(q.order_by(ReceiptScan.created_at, ReceiptScan.id).limit(1))).scalars().first()


async def recorded_duplicate(db: AsyncSession, household_id: uuid.UUID | None, *, file_sha: str | None,
                             ref_hash: str | None, exclude_id: uuid.UUID | None) -> dict | None:
    """Lapis 2 (file) dan 3 (ref): item `tercatat` di rumah tangga yang sama. Pencatatan
    item ini harus diblokir. File dicek lebih dulu. Tanpa rumah tangga tidak ada cakupan."""
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
