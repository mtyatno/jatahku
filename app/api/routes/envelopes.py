from decimal import Decimal
from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Envelope, HouseholdMember, Transaction, Allocation, MonthlySnapshot,
    RecurringTransaction, RecurringFrequency,
)

router = APIRouter()


class EnvelopeCreate(BaseModel):
    name: str
    emoji: str = ""
    budget_amount: Decimal
    is_rollover: bool = True
    group_id: UUID | None = None
    is_personal: bool = False
    is_locked: bool = False
    daily_limit: Decimal | None = None
    cooling_threshold: Decimal | None = None


class EnvelopeResponse(BaseModel):
    id: UUID
    name: str
    emoji: str
    budget_amount: Decimal
    is_rollover: bool
    is_active: bool
    group_id: UUID | None
    household_id: UUID
    owner_id: UUID | None
    is_personal: bool = False
    model_config = {"from_attributes": True}


class EnvelopeSummary(BaseModel):
    id: UUID
    name: str
    emoji: str
    budget_amount: Decimal  # target
    is_rollover: bool
    is_personal: bool
    is_locked: bool
    daily_limit: Decimal | None
    cooling_threshold: Decimal | None
    allocated: Decimal      # actual money in
    spent: Decimal
    reserved: Decimal       # committed for subscriptions this month
    remaining: Decimal      # allocated - spent - reserved (+ rollover)
    free: Decimal           # remaining minus reserved = truly free to spend
    funded_ratio: float     # allocated / budget_amount
    spent_ratio: float      # spent / allocated


async def _get_hid(user: User, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


@router.get("/", response_model=list[EnvelopeResponse])
async def list_envelopes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []
    result = await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    return result.scalars().all()


@router.get("/summary", response_model=list[EnvelopeSummary])
async def envelope_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []

    result = await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    envelopes = result.scalars().all()

    now = date.today()
    summaries = []

    for env in envelopes:
        # Spent this month
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == env.id,
                Transaction.is_deleted == False,
                func.extract("year", Transaction.transaction_date) == now.year,
                func.extract("month", Transaction.transaction_date) == now.month,
            )
        )
        spent = Decimal(str(spent_result.scalar()))

        # Allocated this month (from income allocations)
        from app.models.models import Income
        alloc_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .where(
                Allocation.envelope_id == env.id,
                func.extract("year", Income.income_date) == now.year,
                func.extract("month", Income.income_date) == now.month,
            )
        )
        allocated = Decimal(str(alloc_result.scalar()))

        # Rollover from previous month
        rollover = Decimal("0")
        if env.is_rollover:
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            snap_result = await db.execute(
                select(MonthlySnapshot).where(
                    MonthlySnapshot.envelope_id == env.id,
                    MonthlySnapshot.month == prev_month,
                    MonthlySnapshot.year == prev_year,
                )
            )
            snap = snap_result.scalar_one_or_none()
            if snap and snap.rollover_amount:
                rollover = snap.rollover_amount

        # Calculate reserved from active subscriptions (monthly equivalent)
        rec_result = await db.execute(
            select(RecurringTransaction).where(
                RecurringTransaction.envelope_id == env.id,
                RecurringTransaction.is_active == True,
            )
        )
        recs = rec_result.scalars().all()
        reserved = Decimal("0")
        for rec in recs:
            if rec.frequency == RecurringFrequency.weekly:
                monthly_equiv = rec.amount * 4
            elif rec.frequency == RecurringFrequency.yearly:
                monthly_equiv = rec.amount / 12
            elif rec.frequency == RecurringFrequency.monthly:
                monthly_equiv = rec.amount
            else:
                monthly_equiv = rec.amount
            reserved += monthly_equiv

        # Core formula: remaining = allocated + rollover - spent
        remaining = allocated + rollover - spent
        total_available = allocated + rollover
        free = remaining - reserved  # truly free after reservations

        # Funded ratio: how well funded vs target
        funded_ratio = float(allocated / env.budget_amount) if env.budget_amount > 0 else 0.0

        # Spent ratio: how much spent of available money
        spent_ratio = float(spent / total_available) if total_available > 0 else 0.0

        summaries.append(EnvelopeSummary(
            id=env.id, name=env.name, emoji=env.emoji,
            budget_amount=env.budget_amount, is_rollover=env.is_rollover,
            is_personal=env.owner_id is not None,
            is_locked=env.is_locked,
            daily_limit=env.daily_limit,
            cooling_threshold=env.cooling_threshold,
            allocated=allocated,
            spent=spent, reserved=reserved, remaining=remaining,
            free=free,
            funded_ratio=round(funded_ratio, 4),
            spent_ratio=round(spent_ratio, 4),
        ))

    return summaries


@router.post("/", response_model=EnvelopeResponse, status_code=status.HTTP_201_CREATED)
async def create_envelope(
    req: EnvelopeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    # Check plan limits
    from app.services.plan_limits import check_envelope_limit
    allowed, limit_msg = await check_envelope_limit(user, db)
    if not allowed:
        raise HTTPException(status_code=403, detail=limit_msg)

    if not hid:
        raise HTTPException(status_code=400, detail="Belum punya household")
    envelope = Envelope(
        household_id=hid, name=req.name, emoji=req.emoji,
        budget_amount=req.budget_amount, is_rollover=req.is_rollover,
        group_id=req.group_id,
        owner_id=user.id if req.is_personal else None,
        is_locked=req.is_locked,
        daily_limit=req.daily_limit,
        cooling_threshold=req.cooling_threshold,
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
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(Envelope).where(Envelope.id == envelope_id, Envelope.household_id == hid)
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")

    envelope.name = req.name
    envelope.emoji = req.emoji
    envelope.budget_amount = req.budget_amount
    envelope.is_rollover = req.is_rollover
    envelope.group_id = req.group_id
    envelope.owner_id = user.id if req.is_personal else None
    envelope.is_locked = req.is_locked
    envelope.daily_limit = req.daily_limit
    envelope.cooling_threshold = req.cooling_threshold
    await db.commit()
    await db.refresh(envelope)
    return envelope


@router.delete("/{envelope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_envelope(
    envelope_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date as date_cls
    hid = await _get_hid(user, db)
    result = await db.execute(
        select(Envelope).where(Envelope.id == envelope_id, Envelope.household_id == hid)
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
    if envelope.name == "Tabungan":
        raise HTTPException(status_code=400, detail="Amplop Tabungan tidak bisa dihapus")

    # Find or create Tabungan
    tab_result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid, Envelope.name == "Tabungan", Envelope.is_active == True
        )
    )
    tabungan = tab_result.scalar_one_or_none()
    if not tabungan:
        tabungan = Envelope(household_id=hid, name="Tabungan", emoji="💰", budget_amount=Decimal("0"), is_rollover=True)
        db.add(tabungan)
        await db.flush()

    # Calculate remaining funds in this envelope
    now = date_cls.today()
    from app.models.models import Income
    alloc_result = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id == envelope_id,
            func.extract("year", Income.income_date) == now.year,
            func.extract("month", Income.income_date) == now.month,
        )
    )
    allocated = Decimal(str(alloc_result.scalar()))

    spent_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == envelope_id,
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == now.year,
            func.extract("month", Transaction.transaction_date) == now.month,
        )
    )
    spent = Decimal(str(spent_result.scalar()))
    remaining = allocated - spent

    # Transfer remaining funds to Tabungan via internal transfer
    if remaining > 0:
        from app.models.models import Income as IncomeModel
        transfer = IncomeModel(
            household_id=hid, user_id=user.id, amount=Decimal("0"),
            description=f"Refund: hapus amplop {envelope.name}",
        )
        db.add(transfer)
        await db.flush()
        db.add(Allocation(income_id=transfer.id, envelope_id=envelope_id, amount=-remaining))
        db.add(Allocation(income_id=transfer.id, envelope_id=tabungan.id, amount=remaining))

    # Move all transactions to Tabungan
    from sqlalchemy import update
    await db.execute(
        update(Transaction).where(
            Transaction.envelope_id == envelope_id,
            Transaction.is_deleted == False,
        ).values(envelope_id=tabungan.id)
    )

    # Soft delete
    envelope.is_active = False
    await db.commit()


@router.post("/transfer")
async def transfer_between_envelopes(
    from_id: UUID,
    to_id: UUID,
    amount: Decimal,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transfer allocated funds from one envelope to another."""
    hid = await _get_hid(user, db)

    from_env = await db.execute(select(Envelope).where(Envelope.id == from_id, Envelope.household_id == hid))
    from_envelope = from_env.scalar_one_or_none()
    to_env = await db.execute(select(Envelope).where(Envelope.id == to_id, Envelope.household_id == hid))
    to_envelope = to_env.scalar_one_or_none()

    if not from_envelope or not to_envelope:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Jumlah harus lebih dari 0")

    # Create internal transfer allocations (negative from source, positive to target)
    # We use a special "transfer" income
    from app.models.models import Income
    transfer_income = Income(
        household_id=hid,
        user_id=user.id,
        amount=Decimal("0"),  # net zero
        description=f"Transfer: {from_envelope.name} → {to_envelope.name}",
    )
    db.add(transfer_income)
    await db.flush()

    # Negative allocation from source
    db.add(Allocation(income_id=transfer_income.id, envelope_id=from_id, amount=-amount))
    # Positive allocation to target
    db.add(Allocation(income_id=transfer_income.id, envelope_id=to_id, amount=amount))

    await db.commit()
    return {
        "status": "transferred",
        "from": from_envelope.name,
        "to": to_envelope.name,
        "amount": str(amount),
    }
