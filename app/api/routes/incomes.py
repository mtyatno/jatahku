from uuid import UUID
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Income, Allocation, Envelope, HouseholdMember

router = APIRouter()


class IncomeCreate(BaseModel):
    amount: Decimal
    description: str
    income_date: date | None = None


class AllocationItem(BaseModel):
    envelope_id: UUID
    amount: Decimal


class AllocateRequest(BaseModel):
    allocations: list[AllocationItem]


class IncomeResponse(BaseModel):
    id: UUID
    amount: Decimal
    description: str
    income_date: date
    household_id: UUID

    model_config = {"from_attributes": True}


@router.post("/", response_model=IncomeResponse, status_code=status.HTTP_201_CREATED)
async def create_income(
    req: IncomeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        raise HTTPException(status_code=404, detail="No household found")

    income = Income(
        household_id=hid,
        user_id=user.id,
        amount=req.amount,
        description=req.description,
        income_date=req.income_date or date.today(),
    )
    db.add(income)
    await db.commit()
    await db.refresh(income)
    return income


@router.post("/{income_id}/allocate", status_code=status.HTTP_201_CREATED)
async def allocate_income(
    income_id: UUID,
    req: AllocateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Income).where(Income.id == income_id))
    income = result.scalar_one_or_none()
    if not income:
        raise HTTPException(status_code=404, detail="Income not found")

    total_allocated = sum(a.amount for a in req.allocations)
    if total_allocated > income.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Total allocation ({total_allocated}) exceeds income ({income.amount})",
        )

    for item in req.allocations:
        allocation = Allocation(
            income_id=income_id,
            envelope_id=item.envelope_id,
            amount=item.amount,
        )
        db.add(allocation)

    await db.commit()
    return {"message": f"Allocated {total_allocated} to {len(req.allocations)} envelopes"}


@router.get("/", response_model=list[IncomeResponse])
async def list_incomes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    result = await db.execute(
        select(Income)
        .where(Income.household_id == hid)
        .order_by(Income.income_date.desc())
    )
    return result.scalars().all()
