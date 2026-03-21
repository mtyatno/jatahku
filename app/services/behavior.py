from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import (
    Envelope, Transaction, PendingTransaction, PendingTransactionStatus, TransactionSource
)


class BehaviorCheckResult:
    def __init__(self):
        self.allowed = True
        self.reason = None
        self.check_type = None  # "locked", "daily_limit", "cooling"
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
    """Run all behavior checks before recording a transaction."""

    result = await db.execute(select(Envelope).where(Envelope.id == envelope_id))
    envelope = result.scalar_one_or_none()
    if not envelope:
        return BehaviorCheckResult.blocked("error", "Amplop tidak ditemukan")

    # Check 1: Envelope lock
    if envelope.is_locked:
        return BehaviorCheckResult.blocked(
            "locked",
            f"Amplop {envelope.name} sedang dikunci. Tidak bisa belanja.",
            envelope_name=envelope.name,
        )

    # Check 2: Cooling period (check BEFORE daily limit — big purchases need cooling regardless)
    if envelope.cooling_threshold is not None and amount >= envelope.cooling_threshold:
        return BehaviorCheckResult.blocked(
            "cooling",
            f"Pembelian >= Rp{int(envelope.cooling_threshold):,} perlu cooling period.",
            envelope_name=envelope.name,
            threshold=envelope.cooling_threshold,
            amount=amount,
            cooling_hours=24,
        )

    # Check 3: Daily limit
    if envelope.daily_limit is not None:
        today = date.today()
        spent_today_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == envelope_id,
                Transaction.user_id == user_id,
                Transaction.is_deleted == False,
                Transaction.transaction_date == today,
            )
        )
        spent_today = Decimal(str(spent_today_result.scalar()))

        if spent_today + amount > envelope.daily_limit:
            remaining = max(envelope.daily_limit - spent_today, Decimal("0"))
            return BehaviorCheckResult.blocked(
                "daily_limit",
                f"Melebihi limit harian {envelope.name}.",
                envelope_name=envelope.name,
                daily_limit=envelope.daily_limit,
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
    db: AsyncSession = None,
) -> PendingTransaction:
    """Create a pending transaction with cooling period."""
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
