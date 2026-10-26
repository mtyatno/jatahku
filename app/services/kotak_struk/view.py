"""Detail satu item Kotak Struk untuk klien (spec 2026-10-26 bagian 5d): API web/mobile dan bot memakai
bentuk yang sama. Hanya membaca: tidak ada commit dan tidak ada tulis ke database."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import HouseholdMember, HouseholdMerchant, ReceiptScan, User
from app.services.kotak_struk import dedup
from app.services.kotak_struk.config import ST_DITERIMA, ST_DIPROSES, ST_GAGAL, ST_SIAP, ST_TERCATAT
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.merchants import compose_description, display_name, merchant_for_item
from app.services.kotak_struk.record import STORE_RECEIPT
from app.services.kotak_struk.suggest import suggest_for_item

NO_DOCUMENT = {ST_DITERIMA, ST_DIPROSES, ST_GAGAL}   # belum ada (atau tidak akan ada) hasil baca
SKIP_FLOWS = {"top_up", "masuk", "antar_rekening_sendiri"}   # arah uang yang bukan pengeluaran
BLOCKED_FAILED = "transaksi_gagal"
BLOCKED_RECORDED = "sudah_tercatat"


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _empty_flags() -> dict:
    return {"duplicate_of": None, "skip_suggestion": None, "blocked": None, "warnings": []}


async def _household_of(db: AsyncSession, item: ReceiptScan, user: User) -> uuid.UUID | None:
    """Rumah tangga item bila `user` masih anggotanya. User yang sudah keluar tidak lagi melihat isi rumah
    tangga itu (peta merchant, nama panggilan, transaksi, nama anggota)."""
    if item.household_id is None:
        return None
    return (await db.execute(
        select(HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user.id, HouseholdMember.household_id == item.household_id).limit(1)
    )).scalars().first()


def _merchant(row: HouseholdMerchant | None, item: ReceiptScan, doc: DokumenBayar) -> dict | None:
    """`{id, name, display_name}`: `name` dari baris peta, lalu nama di item, lalu nama di dokumen; None bila
    tidak ada baris peta dan tidak ada nama sama sekali."""
    raw = (row.raw_name if row is not None else None) or item.merchant or doc.counterparty.name
    name = display_name(raw)
    if row is None and not name:
        return None
    return {"id": str(row.id) if row is not None else None, "name": name,
            "display_name": row.display_name if row is not None else None}


async def _flags(db: AsyncSession, item: ReceiptScan, user: User, doc: DokumenBayar,
                 household_id: uuid.UUID | None) -> dict:
    """Tanda untuk klien: duplikat (tercatat > nomor referensi dibagikan anggota lain > transaksi manual yang
    mirip, yang terakhir hanya untuk item `siap`), pemblokiran, arah uang, dan peringatan."""
    warnings = [c["message"] for c in doc.checks if c.get("level") == "warn" and c.get("message")]

    duplicate = await dedup.recorded_duplicate(
        db, household_id, file_sha=item.file_sha256, ref_hash=item.ref_hash, exclude_id=item.id)
    if duplicate is None:
        duplicate = await dedup.pending_ref_duplicate(db, household_id, item.ref_hash, item.id)
        if duplicate is not None:
            warnings.append(f"Bukti ini juga dibagikan {duplicate['by']}")
    if duplicate is None and item.status == ST_SIAP and item.paid_at is not None and doc.amounts.total:
        duplicate = await dedup.soft_duplicate(
            db, household_id, amount=doc.amounts.total, paid_at=item.paid_at, viewer_id=user.id)

    blocked = None
    if any(c.get("level") == "block" for c in doc.checks):
        blocked = BLOCKED_FAILED
    elif (duplicate or {}).get("recorded") or (item.status == ST_TERCATAT and item.doc_type != STORE_RECEIPT):
        blocked = BLOCKED_RECORDED   # struk belanja boleh dicatat lagi (satu struk, banyak transaksi)
    return {"duplicate_of": duplicate, "skip_suggestion": doc.flow if doc.flow in SKIP_FLOWS else None,
            "blocked": blocked, "warnings": warnings}


async def item_detail(db: AsyncSession, item: ReceiptScan, user: User, *, note: str | None = None) -> dict:
    """Detail item untuk `user` (pemilik item). `note` (catatan user) mempengaruhi saran amplop dan
    `description_preview`. Item yang belum/tidak punya hasil baca (`diterima`, `diproses`, `gagal`) hanya memuat
    kolom dasar; `document`, `merchant`, `suggestion`, `description_preview` adalah None dan tanda kosong."""
    detail = {
        "id": str(item.id), "status": item.status, "doc_type": item.doc_type, "source": item.source,
        "created_at": _iso(item.created_at), "paid_at": _iso(item.paid_at), "document": None, "merchant": None,
        "suggestion": None, "description_preview": None, "flags": _empty_flags(), "error": item.error,
    }
    if item.status in NO_DOCUMENT or not item.document:
        return detail

    doc = DokumenBayar.from_json(item.document)
    household_id = await _household_of(db, item, user)
    row = await merchant_for_item(db, item) if household_id is not None else None
    merchant = _merchant(row, item, doc)
    nickname = (row.display_name if row is not None else None) or (merchant["name"] if merchant else None)

    detail["document"] = item.document
    detail["merchant"] = merchant
    detail["suggestion"] = await suggest_for_item(db, item, user, note=note)
    detail["description_preview"] = compose_description(doc, display=nickname, note=note)
    detail["flags"] = await _flags(db, item, user, doc, household_id)
    return detail
