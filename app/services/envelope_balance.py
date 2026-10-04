"""Rumus saldo per amplop untuk satu periode budget — SATU sumber untuk dashboard
(`GET /envelopes/summary`) dan cocokkan saldo (spec 2026-09-30).

Diekstrak apa adanya dari envelopes.envelope_summary.
Rumus inti: remaining = allocated + rollover - spent; free = remaining - reserved.
Dikunci oleh app/tests/test_envelope_balance.py — jangan ubah tanpa test.
"""
from decimal import Decimal
from datetime import date, timedelta

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.period import get_budget_period, get_previous_period
from app.models.models import (
    Envelope, EnvelopeGroup, HouseholdMember, Transaction, Allocation, Income,
    MonthlySnapshot,
)
from app.services.reserved import envelope_reserved


async def get_household_id(user, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def compute_envelope_summaries(
    user,
    db: AsyncSession,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[dict]:
    """Saldo tiap amplop aktif yang terlihat user (shared + personal miliknya).
    Tanpa period_start/period_end → periode berjalan (payday user)."""
    hid = await get_household_id(user, db)
    if not hid:
        return []

    result = await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    envelopes = result.scalars().all()

    group_result = await db.execute(
        select(EnvelopeGroup.id, EnvelopeGroup.name).where(EnvelopeGroup.household_id == hid)
    )
    group_names = {gid: gname for gid, gname in group_result.all()}

    now = date.today()
    payday_day = getattr(user, 'payday_day', None) or 1
    if period_start and period_end:
        # Historical period: rollover comes from the period before period_start
        prev_start, _ = get_budget_period(payday_day, period_start - timedelta(days=1))
    else:
        period_start, period_end = get_budget_period(payday_day, now)
        prev_start, _ = get_previous_period(payday_day, now)
    summaries = []

    for env in envelopes:
        # Spent this budget period
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == env.id,
                Transaction.is_deleted == False,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )
        spent = Decimal(str(spent_result.scalar()))

        # Allocated this budget period (from income allocations)
        alloc_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .where(
                Allocation.envelope_id == env.id,
                Income.income_date >= period_start,
                Income.income_date <= period_end,
            )
        )
        allocated = Decimal(str(alloc_result.scalar()))

        # Rollover from previous budget period (snapshot keyed by prev_start year/month)
        rollover = Decimal("0")
        if env.is_rollover:
            snap_result = await db.execute(
                select(MonthlySnapshot).where(
                    MonthlySnapshot.envelope_id == env.id,
                    MonthlySnapshot.year == prev_start.year,
                    MonthlySnapshot.month == prev_start.month,
                )
            )
            snap = snap_result.scalar_one_or_none()
            if snap and snap.rollover_amount:
                rollover = snap.rollover_amount

        # Tagihan langganan yang belum dibayar periode ini (setara-bulanan)
        reserved = await envelope_reserved(db, env.id, period_start, period_end)

        # Core formula: remaining = allocated + rollover - spent
        remaining = allocated + rollover - spent
        total_available = allocated + rollover
        free = remaining - reserved  # truly free after reservations

        # Funded ratio: how well funded vs target
        funded_ratio = float(allocated / env.budget_amount) if env.budget_amount > 0 else 0.0

        # Spent ratio: how much spent of available money
        spent_ratio = float(spent / total_available) if total_available > 0 else 0.0

        summaries.append({
            "id": env.id, "name": env.name, "emoji": env.emoji,
            "budget_amount": env.budget_amount, "is_rollover": env.is_rollover,
            "is_personal": env.owner_id is not None,
            "is_locked": env.is_locked,
            "daily_limit": env.daily_limit,
            "cooling_threshold": env.cooling_threshold,
            "allocated": allocated,
            "rollover": rollover,
            "spent": spent, "reserved": reserved, "remaining": remaining,
            "free": free,
            "funded_ratio": round(funded_ratio, 4),
            "spent_ratio": round(spent_ratio, 4),
            "group_id": env.group_id,
            "group_name": group_names.get(env.group_id),
            "purpose": env.purpose,
            "classification": env.classification,
        })

    return summaries
