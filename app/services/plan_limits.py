from decimal import Decimal
from datetime import date
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    User, Envelope, Transaction, RecurringTransaction,
)
from app.services.ruang import ruang_keluarga_id

PLAN_LIMITS = {
    "basic": {"envelopes": 6, "txn_per_month": 50, "recurring": 5},
    "pro": {"envelopes": -1, "txn_per_month": -1, "recurring": -1},
}


async def check_envelope_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Check if user can create more envelopes."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["envelopes"] == -1:
        return True, ""

    hid = await ruang_keluarga_id(db, user.id)  # kuota per ruang menyusul di R3
    if not hid:
        return True, ""

    count = (await db.execute(
        select(func.count(Envelope.id)).where(
            Envelope.household_id == hid, Envelope.is_active == True
        )
    )).scalar()

    if count >= limits["envelopes"]:
        return False, f"Limit {limits['envelopes']} amplop tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""


MONTHS_ID = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember")


def quota_reset_date(today: date | None = None) -> date:
    """Kuota transaksi dihitung per bulan kalender → reset tanggal 1 bulan depan."""
    t = today or date.today()
    return date(t.year + (t.month == 12), t.month % 12 + 1, 1)


def _reset_text(today: date | None = None) -> str:
    d = quota_reset_date(today)
    return f"{d.day} {MONTHS_ID[d.month - 1]} {d.year}"


def quota_exhausted_message(limit: int, today: date | None = None) -> str:
    """Input baru ditolak karena kuota bulan ini sudah habis."""
    return (f"Kuota {limit} transaksi bulan ini sudah habis. Pencatatan berikutnya bisa lagi "
            f"mulai {_reset_text(today)}, atau upgrade ke Pro untuk tanpa batas.")


def has_txn_limit(user: User) -> bool:
    """Paket ini punya batas transaksi bulanan (Basic)?"""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])["txn_per_month"] != -1


async def monthly_txn_usage(user: User, db: AsyncSession) -> tuple[int, int] | None:
    """(terpakai, batas) transaksi bulan ini; None untuk paket tanpa batas."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["txn_per_month"] == -1:
        return None

    now = date.today()
    count = (await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user.id,
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),  # penyesuaian cocokkan saldo tidak dihitung
            func.extract("year", Transaction.transaction_date) == now.year,
            func.extract("month", Transaction.transaction_date) == now.month,
        )
    )).scalar()
    return int(count or 0), limits["txn_per_month"]


async def check_transaction_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Boleh MEMULAI input pengeluaran baru? (Basic: < 50 transaksi bulan ini.)

    Aturan pemilik produk (15 Okt 2026): input yang dimulai saat kuota masih ada
    diselesaikan utuh walau di tengah jalan melewati batas — jadi cek ini dipakai
    sekali di awal input, bukan per transaksi (lihat app/services/quota_pass.py).
    Sesudah input selesai, quota_notice_after_input memberi tahu bila kuota habis."""
    usage = await monthly_txn_usage(user, db)
    if usage is None:
        return True, ""
    used, limit = usage
    if used >= limit:
        return False, quota_exhausted_message(limit)
    return True, ""


async def quota_notice_after_input(user: User, db: AsyncSession) -> str | None:
    """Pemberitahuan sesudah satu input selesai, bila kuota bulan ini kini habis."""
    usage = await monthly_txn_usage(user, db)
    if usage is None:
        return None
    used, limit = usage
    if used < limit:
        return None
    return (f"Kuota {limit} transaksi bulan ini sudah habis (sudah {used} transaksi). "
            f"Input berikutnya bisa lagi mulai {_reset_text()}, atau upgrade ke Pro untuk tanpa batas.")


async def check_recurring_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Check if user can create more recurring transactions."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["recurring"] == -1:
        return True, ""

    hid = await ruang_keluarga_id(db, user.id)  # kuota per ruang menyusul di R3
    if not hid:
        return True, ""

    count = (await db.execute(
        select(func.count(RecurringTransaction.id))
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(Envelope.household_id == hid, RecurringTransaction.is_active == True)
    )).scalar()

    if count >= limits["recurring"]:
        return False, f"Limit {limits['recurring']} langganan tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""


def is_pro_feature(feature: str) -> bool:
    """Check if a feature is Pro-only."""
    # Behavior controls (kunci, limit harian, cooling/Pikir-Pikir) untuk semua paket.
    pro_features = ["export", "analytics"]
    return feature in pro_features


def check_pro_access(user: User, feature: str) -> tuple[bool, str]:
    """Check if user has access to a Pro feature."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    if plan == 'pro':
        return True, ""
    if is_pro_feature(feature):
        return False, f"Fitur ini hanya untuk Pro. Upgrade untuk akses."
    return True, ""
