from uuid import UUID
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Envelope, HouseholdMember, RecurringTransaction, RecurringFrequency
)

router = APIRouter()


class RecurringCreate(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    frequency: RecurringFrequency = RecurringFrequency.monthly
    next_run: date


class RecurringResponse(BaseModel):
    id: UUID
    envelope_id: UUID
    envelope_name: str | None = None
    envelope_emoji: str | None = None
    amount: Decimal
    description: str
    frequency: str
    next_run: date
    is_active: bool
    model_config = {"from_attributes": True}


async def _get_hid(user: User, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


@router.get("/", response_model=list[RecurringResponse])
async def list_recurring(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []

    result = await db.execute(
        select(RecurringTransaction, Envelope.name, Envelope.emoji)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            RecurringTransaction.is_active == True,
        )
        .order_by(RecurringTransaction.next_run)
    )
    rows = result.all()
    return [
        RecurringResponse(
            id=r.id, envelope_id=r.envelope_id,
            envelope_name=name, envelope_emoji=emoji,
            amount=r.amount, description=r.description,
            frequency=r.frequency.value, next_run=r.next_run,
            is_active=r.is_active,
        )
        for r, name, emoji in rows
    ]


@router.post("/", response_model=RecurringResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    req: RecurringCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    env_result = await db.execute(
        select(Envelope).where(Envelope.id == req.envelope_id, Envelope.household_id == hid)
    )
    envelope = env_result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")

    rec = RecurringTransaction(
        envelope_id=req.envelope_id,
        amount=req.amount,
        description=req.description,
        frequency=req.frequency,
        next_run=req.next_run,
        is_active=True,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return RecurringResponse(
        id=rec.id, envelope_id=rec.envelope_id,
        envelope_name=envelope.name, envelope_emoji=envelope.emoji,
        amount=rec.amount, description=rec.description,
        frequency=rec.frequency.value, next_run=rec.next_run,
        is_active=rec.is_active,
    )


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(
    rec_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RecurringTransaction).where(RecurringTransaction.id == rec_id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Tidak ditemukan")
    rec.is_active = False
    await db.commit()
