from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import (
    Envelope, Transaction, PendingTransaction, PendingTransactionStatus, TransactionSource
)
from app.core.period import get_budget_period, get_previous_period


def spent_today_query(envelope_id, user_id, today):
    """Spent hari ini untuk daily limit. Penyesuaian cocokkan saldo tidak dihitung:
    tanggalnya buatan dan tidak boleh memblokir belanja hari ini."""
    return select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.envelope_id == envelope_id,
        Transaction.user_id == user_id,
        Transaction.is_deleted == False,
        Transaction.transaction_date == today,
        Transaction.balance_check_id.is_(None),
    )


def daily_limit_bypass_key(user_id, envelope_id) -> str:
    """Kunci Redis "limit harian dinaikkan hari ini" untuk satu user + amplop."""
    return f"dlimit_temp:{user_id}:{envelope_id}"


def seconds_until_midnight(now=None) -> int:
    from datetime import time as _time
    now = now or datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), _time.min)
    return max(1, int((midnight - now).total_seconds()))


async def raise_daily_limit_today(user_id, envelope_id) -> None:
    """Naikkan limit harian amplop ini untuk user sampai tengah malam (setelah
    user mengonfirmasi). SATU-SATUNYA penulis bypass — dipakai web
    (POST /transactions dengan raise_daily_limit) dan bot (tombol "Catat,
    naikkan limit hari ini"). check_behavior membaca kunci yang sama."""
    import redis.asyncio as aioredis
    from app.core.config import get_settings as _gs
    r = aioredis.from_url(_gs().REDIS_URL)
    try:
        await r.setex(daily_limit_bypass_key(user_id, envelope_id), seconds_until_midnight(), "1")
    finally:
        await r.aclose()


class BehaviorCheckResult:
    def __init__(self):
        self.allowed = True
        self.reason = None
        self.check_type = None  # "locked", "not_funded", "insufficient", "daily_limit"
        self.details = {}

    @staticmethod
    def ok():
        return BehaviorCheckResult()

    @staticmethod
    def blocked(check_type, reason, **details):
        r = BehaviorCheckResult()
        r.allowed = False
        r.check_type = check_type
        r.reason = reason
        r.details = details
        return r


async def check_behavior(
    envelope_id: UUID,
    user_id: UUID,
    amount: Decimal,
    db: AsyncSession,
) -> BehaviorCheckResult:
    """Run all behavior checks before recording a transaction.

    Cooling period TIDAK lagi menahan pencatatan (Pikir-Pikir Fase 0, Okt 2026):
    user Jatahku mencatat SETELAH membayar, jadi menahan catatan hanya membuat
    data hilang. cooling_threshold tetap disimpan untuk fitur refleksi
    "Sepadan?" (lihat dokumen desain Pikir-Pikir).
    """

    result = await db.execute(select(Envelope).where(Envelope.id == envelope_id))
    envelope = result.scalar_one_or_none()
    if not envelope:
        return BehaviorCheckResult.blocked("error", "Amplop tidak ditemukan")

    # Load user defaults as fallback when envelope-level settings are not set
    from app.models.models import User
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    effective_is_locked = envelope.is_locked or (user.default_is_locked if user else False)
    effective_daily_limit = envelope.daily_limit if envelope.daily_limit is not None else (user.default_daily_limit if user else None)

    # Check 1: Envelope lock
    if effective_is_locked:
        return BehaviorCheckResult.blocked(
            "locked",
            f"Amplop {envelope.name} sedang dikunci. Tidak bisa belanja.",
            envelope_name=envelope.name,
        )

    # Determine current budget period from user's payday_day
    payday_day = getattr(user, 'payday_day', 1) or 1
    period_start, period_end = get_budget_period(payday_day)

    # Check 2: Not funded — no allocation = no spending
    from app.models.models import Allocation, Income
    alloc_result = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id == envelope_id,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )
    allocated = Decimal(str(alloc_result.scalar()))

    # Also check rollover
    from app.models.models import MonthlySnapshot
    rollover = Decimal("0")
    if envelope.is_rollover:
        prev_start, _ = get_previous_period(payday_day)
        snap_result = await db.execute(
            select(MonthlySnapshot).where(
                MonthlySnapshot.envelope_id == envelope_id,
                MonthlySnapshot.month == prev_start.month,
                MonthlySnapshot.year == prev_start.year,
            )
        )
        snap = snap_result.scalar_one_or_none()
        if snap and snap.rollover_amount:
            rollover = snap.rollover_amount

    total_available = allocated + rollover
    if total_available <= 0:
        return BehaviorCheckResult.blocked(
            "not_funded",
            f"Amplop {envelope.name} belum ada dana. Alokasikan income dulu.",
            envelope_name=envelope.name,
        )

    # Check 2b: Amount exceeds available
    spent_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == envelope_id,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    current_spent = Decimal(str(spent_result.scalar()))
    remaining = total_available - current_spent
    if amount > remaining:
        return BehaviorCheckResult.blocked(
            "insufficient",
            f"Dana di amplop {envelope.name} tidak cukup.",
            envelope_name=envelope.name,
            available=remaining,
            requested=amount,
        )

    # Check 3: Daily limit (skipped if user has a temp bypass active for today)
    if effective_daily_limit is not None:
        # Check Redis temp bypass set when user confirmed a limit override
        _bypass = False
        try:
            import redis.asyncio as aioredis
            from app.core.config import get_settings as _gs
            _r = aioredis.from_url(_gs().REDIS_URL)
            _bypass = bool(await _r.get(daily_limit_bypass_key(user_id, envelope_id)))
            await _r.aclose()
        except Exception:
            pass

        if not _bypass:
            today = date.today()
            spent_today_result = await db.execute(spent_today_query(envelope_id, user_id, today))
            spent_today = Decimal(str(spent_today_result.scalar()))

        if not _bypass and spent_today + amount > effective_daily_limit:
            remaining = max(effective_daily_limit - spent_today, Decimal("0"))
            return BehaviorCheckResult.blocked(
                "daily_limit",
                f"Melebihi limit harian {envelope.name}.",
                envelope_name=envelope.name,
                daily_limit=effective_daily_limit,
                spent_today=spent_today,
                remaining_today=remaining,
                requested=amount,
            )

    return BehaviorCheckResult.ok()


async def create_pending_transaction(
    envelope_id: UUID,
    user_id: UUID,
    amount: Decimal,
    description: str,
    source: TransactionSource,
    cooling_hours: int = 24,
    is_private: bool = False,
    db: AsyncSession = None,
) -> PendingTransaction:
    """Create a pending transaction with cooling period.

    Sejak Pikir-Pikir Fase 0 tidak ada jalur pencatatan yang membuat pending
    baru. confirm/cancel/get_user_pending tetap dipakai untuk baris lama."""
    now = datetime.now(timezone.utc)
    pending = PendingTransaction(
        envelope_id=envelope_id,
        user_id=user_id,
        amount=amount,
        description=description,
        source=source,
        status=PendingTransactionStatus.pending,
        cooling_hours=cooling_hours,
        confirm_after=now + timedelta(hours=cooling_hours),
        expires_at=now + timedelta(hours=cooling_hours + 24),
        is_private=is_private,
    )
    db.add(pending)
    await db.commit()
    await db.refresh(pending)
    return pending


async def confirm_pending(pending_id: UUID, db: AsyncSession) -> dict:
    """Confirm a pending transaction after cooling period."""
    result = await db.execute(
        select(PendingTransaction).where(PendingTransaction.id == pending_id)
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return {"error": "Transaksi pending tidak ditemukan"}

    if pending.status != PendingTransactionStatus.pending:
        return {"error": f"Status sudah {pending.status.value}"}

    now = datetime.now(timezone.utc)
    if now < pending.confirm_after:
        remaining = pending.confirm_after - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return {"error": f"Cooling period belum selesai. Tunggu {hours}j {minutes}m lagi."}

    # Create actual transaction
    txn = Transaction(
        envelope_id=pending.envelope_id,
        user_id=pending.user_id,
        amount=pending.amount,
        description=pending.description,
        source=pending.source,
        transaction_date=date.today(),
        is_private=pending.is_private,
    )
    db.add(txn)
    pending.status = PendingTransactionStatus.confirmed
    await db.commit()

    return {"status": "confirmed", "transaction_id": str(txn.id)}


async def cancel_pending(pending_id: UUID, db: AsyncSession) -> dict:
    """Cancel a pending transaction."""
    result = await db.execute(
        select(PendingTransaction).where(PendingTransaction.id == pending_id)
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return {"error": "Transaksi pending tidak ditemukan"}

    if pending.status != PendingTransactionStatus.pending:
        return {"error": f"Status sudah {pending.status.value}"}

    pending.status = PendingTransactionStatus.cancelled
    await db.commit()
    return {"status": "cancelled"}


async def get_user_pending(user_id: UUID, db: AsyncSession) -> list:
    """Get all pending transactions for a user."""
    result = await db.execute(
        select(PendingTransaction)
        .where(
            PendingTransaction.user_id == user_id,
            PendingTransaction.status == PendingTransactionStatus.pending,
        )
        .order_by(PendingTransaction.created_at.desc())
    )
    return result.scalars().all()
