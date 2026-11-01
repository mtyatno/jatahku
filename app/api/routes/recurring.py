from uuid import UUID
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period
from app.models.models import (
    User, Envelope, RecurringTransaction, RecurringFrequency,
    Transaction, TransactionSource,
)
from app.services.recurring_processor import _next_date
from app.services.recurring_status import (
    compute_recurring_status, take_paid_in_period, payable_from, payment_window_error,
)
from app.services.bills_summary import summarize_bills
from app.services.ruang import RuangAktif, ruang_amplop, ruang_objek

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
    status: str = "due"
    # Bayar/Lewati hanya untuk jatuh tempo di periode aktif; payable_from = awal periode jatuh tempo.
    payable: bool = True
    payable_from: date | None = None
    model_config = {"from_attributes": True}


async def _paid_in_period(db: AsyncSession, recs, period_start: date, period_end: date) -> dict:
    """{rec.id: nominal} langganan bulanan yang dibayar di periode ini (lihat take_paid_in_period)."""
    env_ids = {r.envelope_id for r in recs}
    if not env_ids:
        return {}
    rows = (await db.execute(
        select(Transaction.envelope_id, Transaction.amount, Transaction.description)
        .where(
            Transaction.envelope_id.in_(env_ids),
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
            Transaction.description.like("🔄 %"),
        )
    )).all()
    pools = {}
    for env_id, amount, desc in rows:
        pools.setdefault(env_id, []).append((amount, desc))
    return take_paid_in_period(recs, pools, period_start, period_end)


async def _ruang_langganan(db: AsyncSession, user: User, rec_id: UUID):
    """Ruang langganan yang ditulis (lewat amplopnya), hanya bila user anggotanya (R3)."""
    hid = (await db.execute(
        select(Envelope.household_id)
        .join(RecurringTransaction, RecurringTransaction.envelope_id == Envelope.id)
        .where(RecurringTransaction.id == rec_id)
    )).scalar_one_or_none()
    return await ruang_objek(db, user, hid)


@router.get("/", response_model=list[RecurringResponse])
async def list_recurring(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
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

    today = date.today()
    payday = getattr(user, "payday_day", None) or 1
    period_start, period_end = get_budget_period(payday, today)
    paid = await _paid_in_period(db, [r for r, _n, _e in rows], period_start, period_end)

    return [
        RecurringResponse(
            id=r.id, envelope_id=r.envelope_id,
            envelope_name=name, envelope_emoji=emoji,
            amount=r.amount, description=r.description,
            frequency=r.frequency.value, next_run=r.next_run,
            is_active=r.is_active,
            status=compute_recurring_status(r.next_run, r.frequency.value, today, period_end,
                                            paid_in_period=r.id in paid),
            payable=r.next_run <= period_end,
            payable_from=payable_from(r.next_run, payday),
        )
        for r, name, emoji in rows
    ]


@router.post("/", response_model=RecurringResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    req: RecurringCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await ruang_amplop(db, user, req.envelope_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
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
    today = date.today()
    _ps, period_end = get_budget_period(getattr(user, "payday_day", None) or 1, today)
    return RecurringResponse(
        id=rec.id, envelope_id=rec.envelope_id,
        envelope_name=envelope.name, envelope_emoji=envelope.emoji,
        amount=rec.amount, description=rec.description,
        frequency=rec.frequency.value, next_run=rec.next_run,
        is_active=rec.is_active,
        # Baru dibuat di web: belum ada pembayaran, jadi tidak pernah "paid".
        status=compute_recurring_status(rec.next_run, rec.frequency.value, today, period_end),
        payable=rec.next_run <= period_end,
        payable_from=payable_from(rec.next_run, getattr(user, "payday_day", None) or 1),
    )


@router.put("/{rec_id}", response_model=RecurringResponse)
async def update_recurring(
    rec_id: UUID,
    req: RecurringCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _ruang_langganan(db, user, rec_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Tidak ditemukan")
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


async def _resolve_rec(rec_id, user, db, hid):
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


def _ensure_payable(rec, user):
    err = payment_window_error(rec.next_run, getattr(user, "payday_day", None) or 1, date.today())
    if err:
        raise HTTPException(status_code=409, detail=err)


@router.post("/{rec_id}/pay")
async def pay_recurring(
    rec_id: UUID,
    req: PayRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _ruang_langganan(db, user, rec_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Langganan tidak ditemukan")
    rec = await _resolve_rec(rec_id, user, db, hid)
    _ensure_payable(rec, user)
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
    hid = await _ruang_langganan(db, user, rec_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Langganan tidak ditemukan")
    rec = await _resolve_rec(rec_id, user, db, hid)
    _ensure_payable(rec, user)
    rec.next_run = _next_date(rec.next_run, rec.frequency)
    await db.commit()
    return {"next_run": rec.next_run}


@router.post("/{rec_id}/mark-paid")
async def mark_recurring_paid(
    rec_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tandai lunas (AI Advisor DAT-06): tagihan sudah dibayar lewat catat biasa, jadi
    `next_run` dimajukan tanpa transaksi baru. Jendela bayar sama dengan Bayar/Lewati."""
    hid = await _ruang_langganan(db, user, rec_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Langganan tidak ditemukan")
    rec = await _resolve_rec(rec_id, user, db, hid)
    _ensure_payable(rec, user)
    prev = rec.next_run
    rec.next_run = _next_date(rec.next_run, rec.frequency)
    await db.commit()
    return {"prev_next_run": prev, "next_run": rec.next_run}


@router.get("/summary/period")
async def recurring_period_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    """Ringkasan tagihan bulanan periode berjalan untuk kartu KPI Dashboard."""
    if not hid:
        return {"amount_due": 0, "count_due": 0, "count_total": 0, "amount_paid": 0, "has_overdue": False}

    today = date.today()
    period_start, period_end = get_budget_period(getattr(user, "payday_day", None) or 1, today)

    recs = (await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            RecurringTransaction.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )).scalars().all()

    env_ids = {r.envelope_id for r in recs}
    txns_by_env = {}
    if env_ids:
        rows = (await db.execute(
            select(Transaction.envelope_id, Transaction.amount, Transaction.description)
            .where(
                Transaction.envelope_id.in_(env_ids),
                Transaction.is_deleted == False,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )).all()
        for env_id, amount, desc in rows:
            txns_by_env.setdefault(env_id, []).append((amount, desc))

    return summarize_bills(recs, txns_by_env, period_start, period_end, today)


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(
    rec_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _ruang_langganan(db, user, rec_id)
    if not hid:
        raise HTTPException(status_code=404, detail="Tidak ditemukan")
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
