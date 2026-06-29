from uuid import UUID
from decimal import Decimal
from datetime import date, datetime
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
    created_at: datetime
    is_deleted: bool

    model_config = {"from_attributes": True}


class SuggestEnvelopeRequest(BaseModel):
    description: str


class BatchSuggestEnvelopeRequest(BaseModel):
    descriptions: list[str]


class BatchSuggestEnvelopeResult(BaseModel):
    index: int
    envelope_id: str | None
    envelope_name: str | None
    confident: bool


class BatchTransactionItem(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource = TransactionSource.webapp
    transaction_date: date | None = None


class BatchTransactionCreate(BaseModel):
    items: list[BatchTransactionItem]


class BatchTransactionResult(BaseModel):
    index: int
    ok: bool
    id: UUID | None = None
    description: str
    error: str | None = None


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

    # Keep the discipline streak alive (best-effort; never block the txn).
    try:
        from app.services.streak import record_activity
        await record_activity(db, user.id, getattr(user, "timezone", None))
    except Exception:
        pass

    # Best-effort: learn keyword -> envelope from this transaction so web input
    # enriches the same per-user learning the bot uses. Never block the txn.
    try:
        from app.services.txn_nlp import save_learned_keywords
        await save_learned_keywords(user.id, req.description, req.envelope_id, db)
        await db.commit()
    except Exception:
        pass

    return txn


@router.post("/suggest-envelope")
async def suggest_envelope(
    req: SuggestEnvelopeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.txn_nlp import find_best_envelope
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid or not req.description.strip():
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    envelope, confident = await find_best_envelope(req.description, hid, db, user.id)
    if not envelope:
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    return {"envelope_id": str(envelope.id), "envelope_name": envelope.name, "confident": bool(confident)}


@router.post("/suggest-envelopes")
async def suggest_envelopes(
    req: BatchSuggestEnvelopeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.txn_nlp import find_best_envelope
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        return {"results": [{"index": i, "envelope_id": None, "envelope_name": None, "confident": False} for i in range(len(req.descriptions))]}

    results = []
    for i, desc in enumerate(req.descriptions):
        if not desc or not desc.strip():
            results.append({"index": i, "envelope_id": None, "envelope_name": None, "confident": False})
            continue
        envelope, confident = await find_best_envelope(desc, hid, db, user.id)
        if envelope:
            results.append({"index": i, "envelope_id": str(envelope.id), "envelope_name": envelope.name, "confident": bool(confident)})
        else:
            results.append({"index": i, "envelope_id": None, "envelope_name": None, "confident": False})
    return {"results": results}


@router.post("/batch")
async def batch_create_transactions(
    req: BatchTransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    results = []
    for i, item in enumerate(req.items):
        if not hid:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error="Household not found"))
            continue

        result_env = await db.execute(
            select(Envelope).where(Envelope.id == item.envelope_id, Envelope.household_id == hid)
        )
        envelope = result_env.scalar_one_or_none()
        if not envelope:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error="Envelope not found"))
            continue

        check = await check_behavior(item.envelope_id, user.id, item.amount, db)
        if not check.allowed:
            msg = check.reason or ""
            if check.check_type == "locked":
                msg = f"Amplop dikunci. Tidak bisa belanja."
            elif check.check_type == "daily_limit":
                d = check.details
                msg = f"Melebihi limit harian. Limit: {d.get('daily_limit',0)}, terpakai: {d.get('spent_today',0)}"
            elif check.check_type == "not_funded":
                msg = check.reason or "Amplop belum didanai"
            elif check.check_type == "insufficient":
                d = check.details
                msg = f"Dana tidak cukup. Sisa: Rp{int(d.get('available', 0)):,}, diminta: Rp{int(d.get('requested', 0)):,}"
            elif check.check_type == "cooling":
                msg = f"Pembelian >= Rp{int(check.details.get('threshold', 0)):,} perlu cooling period 24 jam"
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=msg))
            continue

        txn = Transaction(
            envelope_id=item.envelope_id,
            user_id=user.id,
            amount=item.amount,
            description=item.description,
            source=item.source,
            transaction_date=item.transaction_date or date.today(),
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)

        try:
            from app.services.streak import record_activity
            await record_activity(db, user.id, getattr(user, "timezone", None))
        except Exception:
            pass

        try:
            from app.services.txn_nlp import save_learned_keywords
            await save_learned_keywords(user.id, item.description, item.envelope_id, db)
            await db.commit()
        except Exception:
            pass

        results.append(BatchTransactionResult(index=i, ok=True, id=txn.id, description=item.description))

    return results


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    envelope_id: UUID | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(20, le=500),
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
    if start_date:
        query = query.where(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.where(Transaction.transaction_date <= end_date)

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
