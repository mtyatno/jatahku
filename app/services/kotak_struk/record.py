"""Hook "item tercatat" Kotak Struk: aturan boleh dicatat, kata kunci yang boleh dipelajari, dan penandaan item
beserta pembelajaran peta merchant (spec 2026-10-26 bagian 4d).

Struk belanja tidak pernah masuk peta merchant (saran per barang tetap lewat kata kunci, umpan balik lewat
`apply_feedback`); hanya bukti bayar (`PROOF_TYPES`) yang mengajari peta.

Urutan pemanggil (web dan bot): `check_recordable` (pesan yang ramah), `claim_for_recording` (penjaga atomik terhadap
pencatatan ganda, di-commit bersama transaksinya), lalu sesudah commit `after_recorded` (streak, kata kunci, dan
`mark_recorded`). Kirim ulang `client_ref` yang sudah tercatat memanggil `heal_recorded`.

Satu struk belanja boleh dicatat per barang (banyak transaksi); semua jenis lain (QRIS, transfer, tidak dikenali)
hanya sekali, dan penjaganya (klaim eksklusif, penyembuhan) berlaku untuk semuanya.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Envelope, MerchantEnvelopeMap, ReceiptScan, Transaction, User
from app.services.expense_rules import after_expense_recorded
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


async def claim_for_recording(db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Penjaga atomik terhadap pencatatan ganda: `check_recordable` tidak mengunci, jadi dua simpan bersamaan (bot dan
    web, dua ketukan) bisa sama-sama lolos. Semua jenis selain struk belanja (QRIS, transfer, tidak dikenali; hanya
    sekali dicatat, sama dengan `check_recordable`): satu UPDATE bersyarat `siap` -> `tercatat`; hanya satu pemanggil
    yang mendapat True, yang lain False. Struk belanja (banyak transaksi): True bila milik user dan `siap`/`tercatat`,
    tanpa perubahan. Item tidak ada atau milik user lain: False. TIDAK meng-commit: pemanggil meng-commit klaim
    bersama penyimpanan transaksinya, jadi transaksi yang gagal dibatalkan juga mengembalikan klaimnya."""
    row = (await db.execute(
        select(ReceiptScan.doc_type, ReceiptScan.user_id, ReceiptScan.status).where(ReceiptScan.id == item_id)
    )).first()
    if row is None or row.user_id != user_id:
        return False
    if row.doc_type != STORE_RECEIPT:
        claim = (update(ReceiptScan)
                 .where(ReceiptScan.id == item_id, ReceiptScan.user_id == user_id, ReceiptScan.status == ST_SIAP)
                 .values(status=ST_TERCATAT))
        return (await db.execute(claim)).rowcount == 1
    return row.status in (ST_SIAP, ST_TERCATAT)


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
    bukti bayar QRIS/transfer (`PROOF_TYPES`) peta merchant rumah tangga belajar (amplop terpilih +1). Struk belanja
    dan tidak dikenali: `ocr_lines` dibiarkan (umpan balik lama yang menghapusnya), peta tidak disentuh. Idempoten per `transaction_id`: id yang sudah ada di
    `transaction_ids` tidak ditambah dan peta tidak dinaikkan lagi. Boleh dipanggil setelah `claim_for_recording`
    (status sudah `tercatat`). False bila item tidak ada. Meng-commit sendiri."""
    item = await db.get(ReceiptScan, item_id)
    if item is None:
        return False
    if str(transaction_id) in (item.transaction_ids or []):
        return True
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


# --- sesudah transaksi dari item Kotak Struk tersimpan (web dan bot memakai yang sama) ------------------------------

async def _recover(db: AsyncSession, user: User) -> None:
    """Pulihkan sesi setelah galat database yang ditelan. Flush/commit yang gagal membuat sesi menolak apa pun
    (PendingRollbackError) sampai di-rollback, padahal pemanggil masih butuh sesi ini: baris batch berikutnya,
    pemberitahuan kuota. Rollback meng-expire semua objek sesi (MissingGreenlet bila disentuh lagi), termasuk `user`
    milik permintaan, jadi `user` dimuat ulang; pemanggil juga tidak boleh menyentuh objek ORM lain (transaksi,
    amplop) yang dimuat sebelumnya, hanya id yang sudah diambilnya."""
    try:
        await db.rollback()
        await db.refresh(user)
    except Exception:
        log.warning("sesi database tidak bisa dipulihkan setelah galat di pencatatan item Kotak Struk", exc_info=True)


async def after_recorded(db: AsyncSession, user: User, item_id: uuid.UUID, *, transaction_id: uuid.UUID,
                         envelope_id: uuid.UUID, description: str) -> None:
    """Dipanggil SESUDAH transaksi dari item `item_id` di-commit: streak + belajar kata kunci (hook yang sama dengan
    bot), lalu menandai item `tercatat` (`mark_recorded`). Best-effort: transaksinya sudah tercatat, jadi tidak ada
    galat yang dilempar, hanya dicatat di log; item yang gagal ditandai disembuhkan `heal_recorded` saat `client_ref`
    yang sama dikirim ulang. Kata kunci dari bukti bayar hanya dari catatan user, tanpa nama merchant
    (`learn_text_for_item`). Galat database yang ditelan di dalamnya tidak merusak sesi pemanggil (`_recover`): pemanggil
    memberikan id dan keterangan (bukan objek transaksi) karena objek ORM-nya bisa kedaluwarsa oleh pemulihan itu."""
    user_id = user.id
    learn = None
    try:
        learn = await learn_text_for_item(db, item_id, description)
    except Exception:
        log.warning("learn_text_for_item gagal untuk item Kotak Struk %s; kata kunci tidak dipelajari", item_id,
                    exc_info=True)
        learn = ""   # tidak belajar apa pun, dan jangan jatuh ke keterangan utuh yang memuat nama merchant
        await _recover(db, user)
    await after_expense_recorded(db, user, envelope_id, description, learn_text=learn)   # menelan galatnya sendiri
    if not db.sync_session.is_active:
        log.warning("streak/kata kunci gagal disimpan untuk item Kotak Struk %s; sesi dipulihkan", item_id)
        await _recover(db, user)
    try:
        await mark_recorded(db, item_id, user_id=user_id, transaction_id=transaction_id, envelope_id=envelope_id)
    except Exception:
        log.warning("mark_recorded gagal untuk item Kotak Struk %s (transaksi %s tetap tercatat)", item_id,
                    transaction_id, exc_info=True)
        await _recover(db, user)


async def heal_recorded(db: AsyncSession, user: User, item_id: uuid.UUID, transaction_id: uuid.UUID,
                        envelope_id: uuid.UUID) -> None:
    """Kirim ulang `client_ref` yang sudah tercatat membawa item: tandai item sekali lagi, supaya crash antara commit
    transaksi dan `mark_recorded` pulih (`mark_recorded` idempoten per transaksi: tidak ganda, tidak belajar dua kali).
    Hanya untuk item dan transaksi milik user. Jenis yang hanya sekali dicatat (semua selain struk belanja) hanya
    disembuhkan bila diklaim transaksi tadi tapi belum ditandai (status `tercatat`, `transaction_ids` kosong), jadi
    kirim ulang tidak bisa mengonsumsi atau mengubah bukti lain. Tidak pernah melempar galat."""
    user_id = user.id
    try:
        item = await db.get(ReceiptScan, item_id)
        owner = (await db.execute(select(Transaction.user_id).where(Transaction.id == transaction_id))).scalar_one_or_none()
        if item is None or item.user_id != user_id or owner != user_id:
            return
        if item.status not in (ST_SIAP, ST_TERCATAT):
            return
        if item.doc_type != STORE_RECEIPT and (item.status != ST_TERCATAT or item.transaction_ids):
            return
        await mark_recorded(db, item_id, user_id=user_id, transaction_id=transaction_id, envelope_id=envelope_id)
    except Exception:
        log.warning("mark_recorded (kirim ulang) gagal untuk item Kotak Struk %s", item_id, exc_info=True)
        await _recover(db, user)
