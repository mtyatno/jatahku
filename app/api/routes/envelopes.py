from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Envelope, EnvelopeGroup, HouseholdMember

router = APIRouter()


class EnvelopeCreate(BaseModel):
    name: str
    emoji: str = ""
    budget_amount: Decimal
    is_rollover: bool = True
    group_id: UUID | None = None


class EnvelopeResponse(BaseModel):
    id: UUID
    name: str
    emoji: str
    budget_amount: Decimal
    is_rollover: bool
    is_active: bool
    group_id: UUID | None
    household_id: UUID

    model_config = {"from_attributes": True}


async def _get_user_household_id(user: User, db: AsyncSession) -> UUID:
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        raise HTTPException(status_code=404, detail="No household found")
    return hid


@router.get("/", response_model=list[EnvelopeResponse])
async def list_envelopes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_user_household_id(user, db)
    result = await db.execute(
        select(Envelope)
        .where(Envelope.household_id == hid, Envelope.is_active == True)
        .order_by(Envelope.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=EnvelopeResponse, status_code=status.HTTP_201_CREATED)
async def create_envelope(
    req: EnvelopeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_user_household_id(user, db)
    envelope = Envelope(
        household_id=hid,
        name=req.name,
        emoji=req.emoji,
        budget_amount=req.budget_amount,
        is_rollover=req.is_rollover,
        group_id=req.group_id,
    )
    db.add(envelope)
    await db.commit()
    await db.refresh(envelope)
    return envelope


@router.put("/{envelope_id}", response_model=EnvelopeResponse)
async def update_envelope(
    envelope_id: UUID,
    req: EnvelopeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_user_household_id(user, db)
    result = await db.execute(
        select(Envelope).where(Envelope.id == envelope_id, Envelope.household_id == hid)
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Envelope not found")

    envelope.name = req.name
    envelope.emoji = req.emoji
    envelope.budget_amount = req.budget_amount
    envelope.is_rollover = req.is_rollover
    envelope.group_id = req.group_id
    await db.commit()
    await db.refresh(envelope)
    return envelope


@router.delete("/{envelope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_envelope(
    envelope_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_user_household_id(user, db)
    result = await db.execute(
        select(Envelope).where(Envelope.id == envelope_id, Envelope.household_id == hid)
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Envelope not found")

    envelope.is_active = False
    await db.commit()
