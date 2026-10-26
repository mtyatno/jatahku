"""Hook "item tercatat" Kotak Struk: aturan boleh dicatat, kata kunci yang boleh dipelajari, dan penandaan item
beserta pembelajaran peta merchant (spec 2026-10-26 bagian 4d).

Struk belanja tidak pernah masuk peta merchant (saran per barang tetap lewat kata kunci, umpan balik lewat
`apply_feedback`); hanya bukti bayar (`PROOF_TYPES`) yang mengajari peta.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Envelope, MerchantEnvelopeMap, ReceiptScan, User
from app.services.kotak_struk import dedup
from app.services.kotak_struk.config import PROOF_TYPES, ST_SIAP, ST_TERCATAT
from app.services.kotak_struk.document import Counterparty, DokumenBayar
from app.services.kotak_struk.merchants import _find_merchant, learnable_text, merchant_for_item, upsert_household_merchant

log = logging.getLogger(__name__)

STORE_RECEIPT = "struk_belanja"
MSG_NOT_FOUND = "Bukti tidak ditemukan"
MSG_RECORDED = "Bukti ini sudah tercatat"
MSG_NOT_READY = "Bukti ini belum siap dicatat"
MSG_BLOCKED = "Transaksi gagal, tidak bisa dicatat"


class NotRecordable(Exception):
    """Item tidak boleh dicatat sebagai transaksi; `detail` aman ditampilkan ke user."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


async def check_recordable(db: AsyncSession, item_id: uuid.UUID, user: User) -> ReceiptScan:
    """Item milik `user` yang boleh dicatat sekarang, atau `NotRecordable`. Struk belanja boleh dicatat lagi
    setelah `tercatat` (satu struk, banyak transaksi); bukti lain hanya selagi `siap`."""
    item = await db.get(ReceiptScan, item_id)
    if item is None or item.user_id != user.id:
        raise NotRecordable(MSG_NOT_FOUND)
    if item.doc_type == STORE_RECEIPT:
        if item.status not in (ST_SIAP, ST_TERCATAT):
            raise NotRecordable(MSG_NOT_READY)
    elif item.status == ST_TERCATAT:
        raise NotRecordable(MSG_RECORDED)
    elif item.status != ST_SIAP:
        raise NotRecordable(MSG_NOT_READY)
    if any(c.get("level") == "block" for c in (item.document or {}).get("checks") or []):
        raise NotRecordable(MSG_BLOCKED)
    if await dedup.recorded_duplicate(db, item.household_id, file_sha=item.file_sha256,
                                      ref_hash=item.ref_hash, exclude_id=item.id):
        raise NotRecordable(MSG_RECORDED)
    return item


async def learn_text_for_item(db: AsyncSession, item_id: uuid.UUID, description: str) -> str | None:
    """Bagian `description` yang boleh dipelajari sebagai kata kunci amplop: catatan user tanpa nama merchant
    (nama asli, nama panggilan, nama di bukti), "(QRIS)", dan "transfer ke". None untuk struk belanja dan item
    yang tidak ada (pemanggil memakai perilaku lama: belajar dari keterangan utuh)."""
    item = await db.get(ReceiptScan, item_id)
    if item is None or item.doc_type == STORE_RECEIPT:
        return None
    merchant = await merchant_for_item(db, item)
    names = [merchant.raw_name, merchant.display_name] if merchant is not None else []
    if item.document:
        names.append(DokumenBayar.from_json(item.document).counterparty.name)
    return learnable_text(description, names)


async def _bump_map(db: AsyncSession, merchant_id: uuid.UUID, envelope_id: uuid.UUID,
                    user_id: uuid.UUID, now: datetime) -> None:
    """`count + 1` lewat ekspresi SQL (anggota lain mencatat bersamaan tidak saling menimpa); baris dibuat bila
    belum ada. Balapan dua pembuat baris yang sama (`uq_merchant_env`) jatuh ke kenaikan."""
    bump = (update(MerchantEnvelopeMap)
            .where(MerchantEnvelopeMap.merchant_id == merchant_id, MerchantEnvelopeMap.envelope_id == envelope_id)
            .values(count=MerchantEnvelopeMap.count + 1, last_user_id=user_id, last_used_at=now))
    if (await db.execute(bump)).rowcount:
        return
    try:
        async with db.begin_nested():
            db.add(MerchantEnvelopeMap(merchant_id=merchant_id, envelope_id=envelope_id, count=1,
                                       last_user_id=user_id, last_used_at=now))
            await db.flush()
    except IntegrityError:
        await db.execute(bump)


async def _learn(db: AsyncSession, item: ReceiptScan, user_id: uuid.UUID, envelope_id: uuid.UUID) -> None:
    """Ajari peta merchant rumah tangga item: hanya untuk amplop di rumah tangga itu."""
    envelope_household = (await db.execute(
        select(Envelope.household_id).where(Envelope.id == envelope_id))).scalars().first()
    if envelope_household != item.household_id:
        return
    now = datetime.now(timezone.utc)
    merchant = await _find_merchant(db, item.household_id, item.counterparty_key)
    if merchant is None:
        cp = DokumenBayar.from_json(item.document).counterparty if item.document else Counterparty()
        merchant = await upsert_household_merchant(db, item.household_id, item.counterparty_key,
                                                   item.merchant or cp.name, cp.city, now=now)
    await _bump_map(db, merchant.id, envelope_id, user_id, now)


async def mark_recorded(db: AsyncSession, item_id: uuid.UUID, *, user_id: uuid.UUID, transaction_id: uuid.UUID,
                        envelope_id: uuid.UUID) -> bool:
    """Tandai item `tercatat` setelah transaksinya dibuat: id transaksi ditambahkan ke `transaction_ids`, dan untuk
    bukti bayar peta merchant rumah tangga belajar (amplop terpilih +1). Struk belanja: `ocr_lines` dibiarkan
    (umpan balik lama yang menghapusnya), peta tidak disentuh. False bila item tidak ada. Meng-commit sendiri."""
    item = await db.get(ReceiptScan, item_id)
    if item is None:
        return False
    item.transaction_ids = list(item.transaction_ids or []) + [str(transaction_id)]  # daftar baru: perubahan terdeteksi
    item.status = ST_TERCATAT
    if item.doc_type in PROOF_TYPES and item.household_id is not None and item.counterparty_key:
        try:  # belajar itu bonus: transaksinya sudah tercatat, galatnya tidak boleh membiarkan item tetap `siap`
            async with db.begin_nested():
                await _learn(db, item, user_id, envelope_id)
        except Exception:
            log.warning("peta merchant untuk item Kotak Struk %s tidak diperbarui", item_id, exc_info=True)
    await db.commit()
    return True
