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
    try:
        return await build_advisor_insights(user, db)
    except Exception:
        import logging
        logging.getLogger("jatahku.advisor").exception("build_advisor_insights failed")
        return {"cards": [], "dashboard_cards": []}


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
