from decimal import Decimal
from uuid import UUID
from datetime import date
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period
from app.models.models import (
    User, Income, Allocation, Envelope, HouseholdMember,
)
from app.services.income_history import parse_transfer

router = APIRouter()


def _payday(user) -> int:
    return getattr(user, "payday_day", 1) or 1


def _fmt_time(dt, tz) -> str:
    try:
        zone = ZoneInfo(tz or "Asia/Jakarta")
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
    return dt.astimezone(zone).strftime("%H:%M")


class AllocationItem(BaseModel):
    envelope_id: UUID
    amount: Decimal


class IncomeCreate(BaseModel):
    amount: Decimal
    source: str = "Gaji"
    allocations: list[AllocationItem] = []


class IncomeResponse(BaseModel):
    id: UUID
    amount: Decimal
    source: str
    allocations: list[dict] = []
    unallocated: Decimal = Decimal("0")


async def _get_hid(user: User, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _get_or_create_tabungan(hid: UUID, db: AsyncSession) -> Envelope:
    """Get or create the Tabungan envelope for auto-allocation of remainder."""
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.name == "Tabungan",
            Envelope.is_active == True,
        )
    )
    tabungan = result.scalar_one_or_none()
    if not tabungan:
        tabungan = Envelope(
            household_id=hid,
            name="Tabungan",
            emoji="💰",
            budget_amount=Decimal("0"),
            is_rollover=True,
        )
        db.add(tabungan)
        await db.flush()
    return tabungan


@router.post("/", response_model=IncomeResponse, status_code=201)
async def create_income(
    req: IncomeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        raise HTTPException(status_code=400, detail="Belum punya household")

    # Validate allocations don't exceed income
    total_allocated = sum(a.amount for a in req.allocations)
    if total_allocated > req.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Total alokasi (Rp{int(total_allocated):,}) melebihi income (Rp{int(req.amount):,})"
        )

    # Validate all envelopes belong to this household
    for alloc in req.allocations:
        env_check = await db.execute(
            select(Envelope).where(
                Envelope.id == alloc.envelope_id,
                Envelope.household_id == hid,
                or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            )
        )
        if not env_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Amplop {alloc.envelope_id} tidak ditemukan")

    # Create income
    income = Income(
        household_id=hid,
        user_id=user.id,
        amount=req.amount,
        description=req.source,
    )
    db.add(income)
    await db.flush()

    # Create allocations
    alloc_details = []
    for alloc in req.allocations:
        if alloc.amount > 0:
            db.add(Allocation(
                income_id=income.id,
                envelope_id=alloc.envelope_id,
                amount=alloc.amount,
            ))
            env = await db.execute(select(Envelope).where(Envelope.id == alloc.envelope_id))
            e = env.scalar_one()
            alloc_details.append({"envelope": e.name, "emoji": e.emoji, "amount": str(alloc.amount)})

    # Auto-allocate remainder to Tabungan
    remainder = req.amount - total_allocated
    if remainder > 0:
        tabungan = await _get_or_create_tabungan(hid, db)
        db.add(Allocation(
            income_id=income.id,
            envelope_id=tabungan.id,
            amount=remainder,
        ))
        alloc_details.append({"envelope": "Tabungan", "emoji": "💰", "amount": str(remainder), "auto": True})

    await db.commit()

    return IncomeResponse(
        id=income.id,
        amount=income.amount,
        source=income.description,
        allocations=alloc_details,
        unallocated=Decimal("0"),  # always 0 now — remainder goes to Tabungan
    )


@router.get("/")
async def list_incomes(
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid = await _get_hid(user, db)
    if not hid:
        return []

    if not period_start or not period_end:
        period_start, period_end = get_budget_period(_payday(user))

    result = await db.execute(
        select(Income)
        .where(
            Income.household_id == hid,
            Income.user_id == user.id,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
        .order_by(Income.created_at.desc())
    )
    incomes = result.scalars().all()

    output = []
    for inc in incomes:
        alloc_result = await db.execute(
            select(Allocation, Envelope.name, Envelope.emoji, Envelope.purpose)
            .join(Envelope, Allocation.envelope_id == Envelope.id)
            .where(
                Allocation.income_id == inc.id,
                or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            )
        )
        allocs = [
            {"envelope": name, "emoji": emoji, "amount": str(a.amount), "purpose": purpose}
            for a, name, emoji, purpose in alloc_result.all()
        ]
        is_transfer = inc.amount == 0
        output.append({
            "id": str(inc.id),
            "amount": str(inc.amount),
            "source": inc.description,
            "date": inc.income_date.strftime("%Y-%m-%d"),
            "time": _fmt_time(inc.created_at, getattr(user, "timezone", None)),
            "type": "transfer" if is_transfer else "income",
            "allocations": allocs,
            "transfer": parse_transfer(allocs) if is_transfer else None,
        })
    return output
