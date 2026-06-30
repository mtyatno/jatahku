from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period
from app.models.models import (
    User, Envelope, HouseholdMember, Goal, Transaction, Allocation, Income,
)
from app.services.advisor import envelope_lifetime_balance

router = APIRouter()


class GoalCreate(BaseModel):
    envelope_id: UUID
    name: str
    target_amount: Decimal
    target_date: date | None = None


class GoalUpdate(BaseModel):
    name: str | None = None
    target_amount: Decimal | None = None
    target_date: date | None = None


class GoalResponse(BaseModel):
    id: UUID
    envelope_id: UUID
    envelope_name: str
    envelope_emoji: str
    name: str
    target_amount: Decimal
    target_date: date | None = None
    current_balance: Decimal
    progress_pct: float
    monthly_needed: Decimal | None = None
    months_remaining: int | None = None
    is_achieved: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


async def _get_hid(user: User, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _compute_goal_response(goal: Goal, user: User, db: AsyncSession) -> dict:
    """Enrich a Goal record with computed fields (balance, progress, etc.)."""
    env = goal.envelope
    today = date.today()

    # Canonical all-time accumulated balance (sum allocations - sum spent),
    # shared with the advisor so goal progress matches everywhere.
    balance = await envelope_lifetime_balance(env.id, db)
    target = goal.target_amount

    progress_pct = round(min(float(balance / target) * 100, 100), 1) if target > 0 else 0.0
    is_achieved = balance >= target

    months_remaining = None
    monthly_needed = None
    if goal.target_date and goal.target_date > today:
        months_remaining = max(1, (goal.target_date.year - today.year) * 12 + goal.target_date.month - today.month)
        remaining = max(Decimal("0"), target - balance)
        monthly_needed = remaining / months_remaining

    return {
        "id": goal.id,
        "envelope_id": goal.envelope_id,
        "envelope_name": env.name,
        "envelope_emoji": env.emoji or "",
        "name": goal.name,
        "target_amount": target,
        "target_date": goal.target_date,
        "current_balance": balance,
        "progress_pct": progress_pct,
        "monthly_needed": monthly_needed,
        "months_remaining": months_remaining,
        "is_achieved": is_achieved,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


@router.get("/", response_model=list[GoalResponse])
async def list_goals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []

    result = await db.execute(
        select(Goal)
        .options(selectinload(Goal.envelope))
        .join(Envelope, Goal.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Goal.created_at)
    )
    goals = result.scalars().all()

    return [await _compute_goal_response(goal, user, db) for goal in goals]


@router.post("/", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    req: GoalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=404, detail="Household not found")

    # Verify envelope belongs to household
    result = await db.execute(
        select(Envelope).where(
            Envelope.id == req.envelope_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Envelope not found")

    # One goal per envelope
    existing = await db.execute(
        select(Goal).where(Goal.envelope_id == req.envelope_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Amplop ini sudah memiliki target")

    goal = Goal(
        envelope_id=req.envelope_id,
        name=req.name,
        target_amount=req.target_amount,
        target_date=req.target_date,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)

    # Re-fetch with relationship
    result = await db.execute(
        select(Goal).options(selectinload(Goal.envelope)).where(Goal.id == goal.id)
    )
    goal = result.scalar_one()

    return await _compute_goal_response(goal, user, db)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=404, detail="Household not found")

    result = await db.execute(
        select(Goal)
        .options(selectinload(Goal.envelope))
        .join(Envelope, Goal.envelope_id == Envelope.id)
        .where(Goal.id == goal_id, Envelope.household_id == hid)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    return await _compute_goal_response(goal, user, db)


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: UUID,
    req: GoalUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=404, detail="Household not found")

    result = await db.execute(
        select(Goal)
        .options(selectinload(Goal.envelope))
        .join(Envelope, Goal.envelope_id == Envelope.id)
        .where(Goal.id == goal_id, Envelope.household_id == hid)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if req.name is not None:
        goal.name = req.name
    if req.target_amount is not None:
        goal.target_amount = req.target_amount
    if req.target_date is not None:
        goal.target_date = req.target_date

    await db.commit()
    await db.refresh(goal)

    return await _compute_goal_response(goal, user, db)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=404, detail="Household not found")

    result = await db.execute(
        select(Goal)
        .join(Envelope, Goal.envelope_id == Envelope.id)
        .where(Goal.id == goal_id, Envelope.household_id == hid)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    await db.delete(goal)
    await db.commit()
