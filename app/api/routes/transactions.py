from uuid import UUID
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Transaction, Envelope, HouseholdMember, TransactionSource
)
from app.services.behavior import check_behavior, create_pending_transaction
from app.services.behavior import check_behavior, create_pending_transaction

router = APIRouter()


class TransactionCreate(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource = TransactionSource.webapp
    transaction_date: date | None = None


class TransactionResponse(BaseModel):
    id: UUID
    envelope_id: UUID
    user_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource
    transaction_date: date
    is_deleted: bool

    model_config = {"from_attributes": True}


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    req: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify envelope belongs to user's household
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    result = await db.execute(
        select(Envelope).where(Envelope.id == req.envelope_id, Envelope.household_id == hid)
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Envelope not found")

    # Behavior checks
    check = await check_behavior(req.envelope_id, user.id, req.amount, db)
    if not check.allowed:
        if check.check_type == "locked":
            raise HTTPException(status_code=403, detail=f"Amplop dikunci. Tidak bisa belanja.")
        elif check.check_type == "daily_limit":
            d = check.details
            raise HTTPException(status_code=403, detail=f"Melebihi limit harian. Limit: {d['daily_limit']}, terpakai: {d['spent_today']}, diminta: {d['requested']}")
        elif check.check_type == "cooling":
            raise HTTPException(status_code=403, detail=f"Pembelian >= {check.details['threshold']} perlu cooling period 24 jam. Gunakan Telegram untuk transaksi ini.")

    # Run behavior checks
    check = await check_behavior(req.envelope_id, user.id, req.amount, db)
    if not check.allowed:
        if check.check_type == "locked":
            raise HTTPException(status_code=403, detail=f"🔒 Amplop {check.details.get('envelope_name', '')} sedang dikunci.")
        elif check.check_type == "not_funded":
            raise HTTPException(status_code=403, detail=f"💸 {check.reason}")
        elif check.check_type == "insufficient":
            d = check.details
            raise HTTPException(status_code=403, detail=f"💸 Dana tidak cukup. Sisa: Rp{int(d.get('available', 0)):,}, diminta: Rp{int(d.get('requested', 0)):,}")
        elif check.check_type == "cooling":
            pending = await create_pending_transaction(
                req.envelope_id, user.id, req.amount, req.description,
                req.source, cooling_hours=24, db=db,
            )
            raise HTTPException(
                status_code=202,
                detail=f"⏳ Cooling period aktif. Pembelian >= Rp{int(check.details['threshold']):,} perlu tunggu 24 jam. Cek /pending di Telegram.",
            )
        elif check.check_type == "daily_limit":
            d = check.details
            raise HTTPException(
                status_code=403,
                detail=f"⚠️ Melebihi limit harian. Limit: Rp{int(d['daily_limit']):,}/hari, sudah terpakai: Rp{int(d['spent_today']):,}, sisa: Rp{int(d['remaining_today']):,}",
            )

    txn = Transaction(
        envelope_id=req.envelope_id,
        user_id=user.id,
        amount=req.amount,
        description=req.description,
        source=req.source,
        transaction_date=req.transaction_date or date.today(),
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    envelope_id: UUID | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    query = (
        select(Transaction)
        .join(Envelope)
        .where(Envelope.household_id == hid, Transaction.is_deleted == False)
    )
    if envelope_id:
        query = query.where(Transaction.envelope_id == envelope_id)

    query = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    txn_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn.is_deleted = True
    await db.commit()
