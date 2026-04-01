from datetime import date
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, MonthlySnapshot, Envelope, HouseholdMember
from app.services.rollover import create_monthly_snapshots, get_previous_rollover

router = APIRouter()


class SnapshotResponse(BaseModel):
    envelope_id: UUID
    envelope_name: str
    year: int
    month: int
    opening_balance: Decimal
    closing_balance: Decimal
    rollover_amount: Decimal


@router.get("/", response_model=list[SnapshotResponse])
async def list_snapshots(
    year: int = Query(None),
    month: int = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List monthly snapshots for user's household."""
    now = date.today()
    y = year or now.year
    m = month or now.month

    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        return []

    result = await db.execute(
        select(MonthlySnapshot, Envelope.name)
        .join(Envelope, MonthlySnapshot.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            MonthlySnapshot.year == y,
            MonthlySnapshot.month == m,
        )
        .order_by(Envelope.created_at)
    )
    rows = result.all()

    return [
        SnapshotResponse(
            envelope_id=snap.envelope_id,
            envelope_name=name,
            year=snap.year,
            month=snap.month,
            opening_balance=snap.opening_balance,
            closing_balance=snap.closing_balance,
            rollover_amount=snap.rollover_amount,
        )
        for snap, name in rows
    ]


@router.post("/run")
async def run_monthly_snapshot(
    year: int = Query(None),
    month: int = Query(None),
    force: bool = Query(False),
    user: User = Depends(get_current_user),
):
    """Manually trigger snapshot for a budget period (admin/debug).
    year/month refer to period_start year/month. Uses caller's payday_day to reconstruct period dates."""
    import calendar
    now = date.today()
    y = year or now.year
    m = month or now.month
    payday = user.payday_day or 1

    # Reconstruct the period whose start falls in y/m
    last_day = calendar.monthrange(y, m)[1]
    target_day = min(payday, last_day)
    target_date = date(y, m, target_day)  # = period_start

    from app.core.period import get_budget_period
    period_start, period_end = get_budget_period(payday, target_date)

    result = await create_monthly_snapshots(period_start, period_end, force=force)
    return {"period": f"{period_start} → {period_end}", **result}

@router.post("/daily-summary")
async def trigger_daily_summary(user: User = Depends(get_current_user)):
    from app.services.summary import send_daily_summary
    await send_daily_summary()
    return {"status": "sent"}

@router.post("/weekly-summary")
async def trigger_weekly_summary(user: User = Depends(get_current_user)):
    from app.services.summary import send_weekly_summary
    await send_weekly_summary()
    return {"status": "sent"}


@router.post("/process-recurring")
async def trigger_recurring(user: User = Depends(get_current_user)):
    from app.services.recurring_processor import process_recurring_transactions
    await process_recurring_transactions()
    return {"status": "processed"}
