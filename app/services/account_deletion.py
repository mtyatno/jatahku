"""Hapus akun sungguhan (mobile paket 1.2; syarat Google Play & App Store 5.1.1(v)).

Yang dihapus permanen: baris `users`, sesi login (semua perangkat langsung keluar),
notifikasi, preferensi, streak, kata kunci amplop, scan struk (termasuk item Kotak
Struk), order pembayaran, transaksi tertunda, dan foto profil/bukti bayar di disk.
Berkas Kotak Struk dari item yang belum selesai tidak dihapus di sini: barisnya ikut
terhapus, lalu penyapu berkas yatim (scheduler `kotak_maintenance`) menghapus berkasnya.

Household:
- Hanya user ini anggotanya → household dihapus utuh (amplop, transaksi, pemasukan,
  alokasi, langganan, target, snapshot, cocokkan saldo, merchant rumah tangga dan
  peta merchant → amplop).
- Ada anggota lain → amplop pribadi user dihapus (beserta baris peta merchant ke
  amplop itu; merchant-nya tetap milik household); catatannya di amplop bersama
  dianonimkan ke user "Mantan anggota" (keterangan diganti, nominal tetap) supaya
  saldo bersama tidak berubah (kajian, keputusan pemilik produk #5). Pemasukan user
  dipangkas ke jumlah yang masih teralokasi ke amplop bersama, jadi uangnya tidak
  muncul sebagai "belum dialokasikan" di household. Peran owner pindah ke anggota
  tertua. Peta merchant di amplop bersama tetap, `last_user_id` user ini dikosongkan.

"Mantan anggota" satu baris `users` bersama (FORMER_MEMBER_ID), bukan anggota household
mana pun dan tidak bisa login. Email berawalan `deleted_` supaya scheduler, admin, dan
email notifikasi melewatinya (konvensi yang sudah ada).

Permintaan hapus dari halaman web tanpa login (/hapus-akun) memakai token sekali pakai
di Redis (`acctdel:{token}`, 1 jam), pola sama dengan reset sandi.
"""
import logging
import os
import secrets
import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Allocation, AuthSession, BalanceCheck, Envelope, EnvelopeGroup, Goal, Household,
    HouseholdMember, HouseholdMerchant, HouseholdRole, Income, MerchantEnvelopeMap, MonthlySnapshot,
    Notification, NotificationPreference, PaymentOrder, PendingTransaction, ReceiptLearnVote,
    ReceiptScan, RecurringTransaction, Transaction, User, UserEnvelopeKeyword, UserStreak,
)

logger = logging.getLogger("jatahku.account_deletion")

FORMER_MEMBER_ID = uuid.UUID("00000000-0000-4000-8000-00000000d31e")
FORMER_MEMBER_NAME = "Mantan anggota"
FORMER_MEMBER_EMAIL = "deleted_mantan-anggota@jatahku.com"
ANON_TXN_DESC = "Transaksi mantan anggota"
ANON_INCOME_DESC = "Pemasukan mantan anggota"

UPLOAD_ROOT = "/home/jatahku/web/jatahku.com/public_html"

TOKEN_PREFIX = "acctdel:"
TOKEN_TTL_SECONDS = 3600  # 1 jam


# ── token permintaan hapus (halaman web tanpa login) ─────────────────────────

async def create_deletion_token(redis, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(f"{TOKEN_PREFIX}{token}", user_id, ex=TOKEN_TTL_SECONDS)
    return token


async def redeem_deletion_token(redis, token: str) -> str | None:
    if not token:
        return None
    key = f"{TOKEN_PREFIX}{token}"
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    return value.decode() if isinstance(value, bytes) else value


# ── penghapusan ──────────────────────────────────────────────────────────────

async def _former_member(db: AsyncSession) -> uuid.UUID:
    exists = (await db.execute(select(User.id).where(User.id == FORMER_MEMBER_ID))).scalar_one_or_none()
    if exists is None:
        db.add(User(id=FORMER_MEMBER_ID, name=FORMER_MEMBER_NAME, email=FORMER_MEMBER_EMAIL,
                    password_hash=None, plan="basic"))
        await db.flush()
    return FORMER_MEMBER_ID


async def _delete_envelopes(db: AsyncSession, env_ids: list) -> None:
    if not env_ids:
        return
    for model in (Allocation, Transaction, PendingTransaction, RecurringTransaction,
                  Goal, MonthlySnapshot, UserEnvelopeKeyword, MerchantEnvelopeMap):
        await db.execute(delete(model).where(model.envelope_id.in_(env_ids)))
    await db.execute(delete(Envelope).where(Envelope.id.in_(env_ids)))


async def _delete_household(db: AsyncSession, hid) -> None:
    # Peta merchant dan merchant rumah tangga lebih dulu, eksplisit (tidak bergantung pada FK CASCADE).
    merchant_ids = select(HouseholdMerchant.id).where(HouseholdMerchant.household_id == hid)
    await db.execute(delete(MerchantEnvelopeMap).where(MerchantEnvelopeMap.merchant_id.in_(merchant_ids)))
    await db.execute(delete(HouseholdMerchant).where(HouseholdMerchant.household_id == hid))
    env_ids = list((await db.execute(select(Envelope.id).where(Envelope.household_id == hid))).scalars())
    await _delete_envelopes(db, env_ids)
    income_ids = select(Income.id).where(Income.household_id == hid)
    await db.execute(delete(Allocation).where(Allocation.income_id.in_(income_ids)))
    await db.execute(delete(Income).where(Income.household_id == hid))
    await db.execute(delete(BalanceCheck).where(BalanceCheck.household_id == hid))
    await db.execute(delete(EnvelopeGroup).where(EnvelopeGroup.household_id == hid))
    await db.execute(delete(HouseholdMember).where(HouseholdMember.household_id == hid))
    await db.execute(delete(Household).where(Household.id == hid))


async def _leave_shared_household(db: AsyncSession, user: User, membership: HouseholdMember) -> None:
    hid = membership.household_id
    personal = list((await db.execute(
        select(Envelope.id).where(Envelope.household_id == hid, Envelope.owner_id == user.id)
    )).scalars())
    await _delete_envelopes(db, personal)

    if membership.role == HouseholdRole.owner:
        heir = (await db.execute(
            select(HouseholdMember)
            .where(HouseholdMember.household_id == hid, HouseholdMember.user_id != user.id)
            .order_by(HouseholdMember.created_at, HouseholdMember.id)
            .limit(1)
        )).scalar_one()
        heir.role = HouseholdRole.owner
    await db.delete(membership)


async def _anonymize_leftovers(db: AsyncSession, user_id) -> None:
    """Catatan user yang masih tersisa (di amplop/household bersama) → Mantan anggota."""
    await db.execute(delete(Transaction).where(Transaction.user_id == user_id, Transaction.is_deleted.is_(True)))
    has_txn = (await db.execute(select(func.count(Transaction.id)).where(Transaction.user_id == user_id))).scalar()
    incomes = (await db.execute(select(Income).where(Income.user_id == user_id))).scalars().all()
    has_check = (await db.execute(select(func.count(BalanceCheck.id)).where(BalanceCheck.user_id == user_id))).scalar()
    if not (has_txn or incomes or has_check):
        return

    former = await _former_member(db)
    await db.execute(
        update(Transaction).where(Transaction.user_id == user_id)
        .values(user_id=former, description=ANON_TXN_DESC)
    )
    await db.execute(update(BalanceCheck).where(BalanceCheck.user_id == user_id).values(user_id=former))
    for inc in incomes:
        allocated = (await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0)).where(Allocation.income_id == inc.id)
        )).scalar()
        allocated = Decimal(str(allocated or 0))
        if allocated <= 0:
            await db.delete(inc)
            continue
        inc.amount = min(inc.amount, allocated)
        inc.user_id = former
        inc.description = ANON_INCOME_DESC


async def delete_account(db: AsyncSession, user: User) -> list[str]:
    """Hapus akun `user` beserta datanya dalam satu transaksi, lalu commit.

    Mengembalikan path file di disk (foto profil, bukti bayar) yang perlu dihapus
    setelah commit — lihat `remove_files`.
    """
    if user.id == FORMER_MEMBER_ID:
        raise ValueError("akun Mantan anggota tidak bisa dihapus")
    uid = user.id
    files = [user.profile_pic] if user.profile_pic else []
    files += [p for p in (await db.execute(
        select(PaymentOrder.proof_url).where(PaymentOrder.user_id == uid, PaymentOrder.proof_url.is_not(None))
    )).scalars()]

    memberships = (await db.execute(select(HouseholdMember).where(HouseholdMember.user_id == uid))).scalars().all()
    for m in memberships:
        others = (await db.execute(
            select(func.count(HouseholdMember.id))
            .where(HouseholdMember.household_id == m.household_id, HouseholdMember.user_id != uid)
        )).scalar()
        if others:
            await _leave_shared_household(db, user, m)
        else:
            await _delete_household(db, m.household_id)
    await db.flush()

    # Amplop pribadi di luar household user (sisa data lama), lalu catatan di amplop bersama.
    stray = list((await db.execute(select(Envelope.id).where(Envelope.owner_id == uid))).scalars())
    await _delete_envelopes(db, stray)
    await _anonymize_leftovers(db, uid)

    for model in (PendingTransaction, Notification, NotificationPreference, UserStreak,
                  UserEnvelopeKeyword, ReceiptScan, ReceiptLearnVote, PaymentOrder, AuthSession):
        await db.execute(delete(model).where(model.user_id == uid))
    # Peta merchant yang tersisa (amplop bersama) tetap milik household; jejak user dikosongkan eksplisit.
    await db.execute(update(MerchantEnvelopeMap).where(MerchantEnvelopeMap.last_user_id == uid).values(last_user_id=None))
    await db.flush()
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    logger.info("Akun %s dihapus (%d household)", uid, len(memberships))
    return files


def remove_files(paths: list[str], root: str = UPLOAD_ROOT) -> None:
    """Hapus file unggahan (`/uploads/...`) milik akun yang sudah dihapus. Gagal = dicatat saja."""
    for p in paths:
        if not p or not p.startswith("/uploads/") or ".." in p:
            continue
        try:
            os.remove(os.path.join(root, p.lstrip("/")))
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Gagal menghapus file %s", p, exc_info=True)
