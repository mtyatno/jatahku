from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.services.advisor import (
    build_advisor_insights,
    build_allocation_recommendation,
    build_sinking_fund_advice,
)

router = APIRouter()


class AllocationRecommendationRequest(BaseModel):
    income_amount: Decimal


@router.get("/insights")
async def advisor_insights(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await build_advisor_insights(user, db)


@router.post("/allocation-recommendation")
async def allocation_recommendation(
    req: AllocationRecommendationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.income_amount <= 0:
        raise HTTPException(status_code=400, detail="Income amount must be positive")
    return await build_allocation_recommendation(user, req.income_amount, db)


@router.get("/sinking-funds")
async def sinking_fund_advice(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await build_sinking_fund_advice(user, db)


@router.get("/allocation-pattern")
async def allocation_pattern(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.models import Income, Allocation
    from datetime import date, timedelta

    # Get recent incomes (last 3 or last 90 days)
    recent_date = date.today() - timedelta(days=90)

    stmt = (
        select(Allocation)
        .join(Income)
        .where(Income.user_id == user.id)
        .where(Income.income_date >= recent_date)
    )

    result = await db.execute(stmt)
    allocations = result.scalars().all()

    # Sum allocations per envelope
    envelope_totals = {}
    total_allocated = Decimal(0)

    for alloc in allocations:
        envelope_id = str(alloc.envelope_id)
        amount = Decimal(str(alloc.amount))
        envelope_totals[envelope_id] = envelope_totals.get(envelope_id, Decimal(0)) + amount
        total_allocated += amount

    # Convert to percentages
    items = []
    if total_allocated > 0:
        for envelope_id, total_amount in envelope_totals.items():
            pct = int(round((float(total_amount) / float(total_allocated)) * 100))
            items.append({
                "envelope_id": envelope_id,
                "percentage": pct,
                "total_amount": float(total_amount)
            })

    return {
        "items": items,
        "total_allocated": float(total_allocated),
        "period_days": 90
    }
