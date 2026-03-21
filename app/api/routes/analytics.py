from decimal import Decimal
from datetime import date, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Envelope, Transaction, HouseholdMember, Allocation, Income,
    RecurringTransaction, RecurringFrequency,
)

router = APIRouter()


async def _get_hid(user, db):
    r = await db.execute(select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id))
    return r.scalar_one_or_none()


@router.get("/daily-spending")
async def daily_spending(
    year: int = Query(None), month: int = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Daily spending for the month — for bar/line chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    now = date.today()
    y = year or now.year
    m = month or now.month

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
            func.extract("year", Transaction.transaction_date) == y,
            func.extract("month", Transaction.transaction_date) == m,
        )
        .group_by(Transaction.transaction_date)
        .order_by(Transaction.transaction_date)
    )
    return [{"date": str(r.transaction_date), "total": float(r.total), "count": r.count} for r in result.all()]


@router.get("/envelope-breakdown")
async def envelope_breakdown(
    year: int = Query(None), month: int = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Spending breakdown by envelope — for pie chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    now = date.today()
    y = year or now.year
    m = month or now.month

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
            or_(
                Transaction.is_deleted == False,
                Transaction.id == None,
            ),
            or_(
                func.extract("year", Transaction.transaction_date) == y,
                Transaction.id == None,
            ),
            or_(
                func.extract("month", Transaction.transaction_date) == m,
                Transaction.id == None,
            ),
        )
        .group_by(Envelope.id, Envelope.name, Envelope.emoji)
        .order_by(func.sum(Transaction.amount).desc().nullslast())
    )
    return [{"name": r.name, "emoji": r.emoji, "spent": float(r.spent)} for r in result.all()]


@router.get("/monthly-trend")
async def monthly_trend(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Last 6 months spending + allocated — for comparison chart."""
    hid = await _get_hid(user, db)
    if not hid:
        return []
    now = date.today()
    months = []
    for i in range(5, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        # Spent
        spent_r = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .join(Envelope, Transaction.envelope_id == Envelope.id)
            .where(
                Envelope.household_id == hid,
                Transaction.is_deleted == False,
                func.extract("year", Transaction.transaction_date) == y,
                func.extract("month", Transaction.transaction_date) == m,
            )
        )
        spent = float(spent_r.scalar())
        # Allocated
        alloc_r = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .join(Envelope, Allocation.envelope_id == Envelope.id)
            .where(
                Envelope.household_id == hid,
                func.extract("year", Income.income_date) == y,
                func.extract("month", Income.income_date) == m,
            )
        )
        allocated = float(alloc_r.scalar())
        label = date(y, m, 1).strftime("%b %Y")
        months.append({"month": label, "spent": spent, "allocated": allocated})
    return months


@router.get("/prediction")
async def spending_prediction(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Will budget last? Prediction based on daily average."""
    hid = await _get_hid(user, db)
    if not hid:
        return {}
    now = date.today()
    next_month = date(now.year + (1 if now.month == 12 else 0), (now.month % 12) + 1, 1)
    days_passed = now.day
    days_left = (next_month - now).days
    days_total = days_passed + days_left

    # Total allocated
    alloc_r = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .join(Envelope, Allocation.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            func.extract("year", Income.income_date) == now.year,
            func.extract("month", Income.income_date) == now.month,
        )
    )
    total_allocated = float(alloc_r.scalar())

    # Total spent
    spent_r = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == now.year,
            func.extract("month", Transaction.transaction_date) == now.month,
        )
    )
    total_spent = float(spent_r.scalar())

    # Reserved from subscriptions
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
    }
