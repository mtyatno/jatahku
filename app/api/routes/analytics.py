from decimal import Decimal
from datetime import date, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period, get_last_n_periods, get_period_info
from app.models.models import (
    User, Envelope, Transaction, HouseholdMember, Allocation, Income,
    RecurringTransaction, RecurringFrequency,
)

router = APIRouter()


async def _get_hid(user, db):
    r = await db.execute(select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id))
    return r.scalar_one_or_none()


def _payday(user) -> int:
    return getattr(user, 'payday_day', 1) or 1


@router.get("/daily-spending")
async def daily_spending(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Daily spending for current budget period — for bar/line chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    period_start, period_end = get_budget_period(_payday(user))

    result = await db.execute(
        select(
            Transaction.transaction_date,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
        .group_by(Transaction.transaction_date)
        .order_by(Transaction.transaction_date)
    )
    return [{"date": str(r.transaction_date), "total": float(r.total), "count": r.count} for r in result.all()]


@router.get("/envelope-breakdown")
async def envelope_breakdown(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Spending breakdown by envelope for current period — for pie chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    period_start, period_end = get_budget_period(_payday(user))

    result = await db.execute(
        select(
            Envelope.name, Envelope.emoji,
            func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
        )
        .join(Transaction, Transaction.envelope_id == Envelope.id, isouter=True)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            or_(Transaction.is_deleted == False, Transaction.id == None),
            or_(Transaction.transaction_date >= period_start, Transaction.id == None),
            or_(Transaction.transaction_date <= period_end, Transaction.id == None),
        )
        .group_by(Envelope.id, Envelope.name, Envelope.emoji)
        .order_by(func.sum(Transaction.amount).desc().nullslast())
    )
    return [{"name": r.name, "emoji": r.emoji, "spent": float(r.spent)} for r in result.all()]


@router.get("/monthly-trend")
async def monthly_trend(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Last 6 budget periods spending + allocated — for comparison chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    payday_day = _payday(user)
    periods = get_last_n_periods(payday_day, 6)
    result = []
    for p_start, p_end in periods:
        spent_r = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .join(Envelope, Transaction.envelope_id == Envelope.id)
            .where(
                Envelope.household_id == hid,
                Transaction.is_deleted == False,
                Transaction.transaction_date >= p_start,
                Transaction.transaction_date <= p_end,
            )
        )
        spent = float(spent_r.scalar())
        alloc_r = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .join(Envelope, Allocation.envelope_id == Envelope.id)
            .where(
                Envelope.household_id == hid,
                Income.income_date >= p_start,
                Income.income_date <= p_end,
            )
        )
        allocated = float(alloc_r.scalar())
        label = f"{p_start.strftime('%d %b')} – {p_end.strftime('%d %b')}"
        result.append({"month": label, "spent": spent, "allocated": allocated})
    return result


@router.get("/prediction")
async def spending_prediction(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Will budget last until next payday? Prediction based on daily average."""
    hid = await _get_hid(user, db)
    if not hid:
        return {}

    payday_day = _payday(user)
    info = get_period_info(payday_day)
    period_start = info["period_start"]
    period_end = info["period_end"]
    days_passed = info["days_used"]
    days_left = info["days_remaining"]
    days_total = info["days_total"]

    alloc_r = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .join(Envelope, Allocation.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )
    total_allocated = float(alloc_r.scalar())

    spent_r = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    total_spent = float(spent_r.scalar())

    env_r = await db.execute(
        select(Envelope.id).where(Envelope.household_id == hid, Envelope.is_active == True)
    )
    env_ids = [r for r in env_r.scalars().all()]
    total_reserved = 0.0
    for eid in env_ids:
        rec_r = await db.execute(
            select(RecurringTransaction).where(
                RecurringTransaction.envelope_id == eid, RecurringTransaction.is_active == True
            )
        )
        for rec in rec_r.scalars().all():
            if rec.frequency == RecurringFrequency.weekly:
                total_reserved += float(rec.amount) * 4
            elif rec.frequency == RecurringFrequency.yearly:
                total_reserved += float(rec.amount) / 12
            else:
                total_reserved += float(rec.amount)

    daily_avg = total_spent / days_passed if days_passed > 0 else 0
    predicted_total = daily_avg * days_total
    remaining = total_allocated - total_spent
    free = remaining - total_reserved
    safe_daily = free / days_left if days_left > 0 else 0
    on_track = predicted_total <= total_allocated

    return {
        "total_allocated": total_allocated,
        "total_spent": total_spent,
        "total_reserved": total_reserved,
        "remaining": remaining,
        "free": free,
        "daily_avg": round(daily_avg),
        "safe_daily": round(safe_daily),
        "predicted_total": round(predicted_total),
        "on_track": on_track,
        "days_passed": days_passed,
        "days_left": days_left,
        "period_start": str(period_start),
        "period_end": str(period_end),
    }
