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
    User, Envelope, HouseholdMember, RecurringTransaction, RecurringFrequency,
    Transaction, TransactionSource,
)
from app.services.recurring_processor import _next_date

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
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
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
        select(Envelope).where(
            Envelope.id == req.envelope_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
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


@router.put("/{rec_id}", response_model=RecurringResponse)
async def update_recurring(
    rec_id: UUID,
    req: RecurringCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            RecurringTransaction.id == rec_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Tidak ditemukan")

    env_result = await db.execute(
        select(Envelope).where(
            Envelope.id == req.envelope_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    envelope = env_result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")

    rec.envelope_id = req.envelope_id
    rec.amount = req.amount
    rec.description = req.description
    rec.frequency = req.frequency
    rec.next_run = req.next_run
    await db.commit()
    await db.refresh(rec)
    return RecurringResponse(
        id=rec.id, envelope_id=rec.envelope_id,
        envelope_name=envelope.name, envelope_emoji=envelope.emoji,
        amount=rec.amount, description=rec.description,
        frequency=rec.frequency.value, next_run=rec.next_run,
        is_active=rec.is_active,
    )


class PayRequest(BaseModel):
    amount: Decimal | None = None


async def _resolve_rec(rec_id, user, db):
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            RecurringTransaction.id == rec_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Langganan tidak ditemukan")
    return rec


@router.post("/{rec_id}/pay")
async def pay_recurring(
    rec_id: UUID,
    req: PayRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await _resolve_rec(rec_id, user, db)
    prev = rec.next_run
    amount = req.amount if req.amount is not None else rec.amount
    txn = Transaction(
        envelope_id=rec.envelope_id, user_id=user.id, amount=amount,
        description=f"🔄 {rec.description}", source=TransactionSource.webapp,
        transaction_date=date.today(),
    )
    db.add(txn)
    rec.next_run = _next_date(rec.next_run, rec.frequency)
    await db.commit()
    await db.refresh(txn)
    return {"txn_id": txn.id, "prev_next_run": prev, "next_run": rec.next_run}


@router.post("/{rec_id}/skip")
async def skip_recurring(
    rec_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await _resolve_rec(rec_id, user, db)
    rec.next_run = _next_date(rec.next_run, rec.frequency)
    await db.commit()
    return {"next_run": rec.next_run}


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(
    rec_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            RecurringTransaction.id == rec_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Tidak ditemukan")
    rec.is_active = False
    await db.commit()
