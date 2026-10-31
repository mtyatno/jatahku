from datetime import date
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.period import get_period_for_month
from app.models.models import User, MonthlySnapshot, Envelope, Household, HouseholdMember
from app.services.household_cycle import household_payday, payday_context, recompute_history
from app.services.rollover import create_monthly_snapshots, get_previous_rollover

router = APIRouter()


class SnapshotResponse(BaseModel):
    envelope_id: UUID
    envelope_name: str
    year: int
    month: int
    opening_balance: Decimal
    closing_balance: Decimal
    rollover_amount: Decimal


@router.get("/", response_model=list[SnapshotResponse])
async def list_snapshots(
    year: int = Query(None),
    month: int = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List monthly snapshots for user's household."""
    now = date.today()
    y = year or now.year
    m = month or now.month

    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        return []

    result = await db.execute(
        select(MonthlySnapshot, Envelope.name)
        .join(Envelope, MonthlySnapshot.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            MonthlySnapshot.year == y,
            MonthlySnapshot.month == m,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    rows = result.all()

    return [
        SnapshotResponse(
            envelope_id=snap.envelope_id,
            envelope_name=name,
            year=snap.year,
            month=snap.month,
            opening_balance=snap.opening_balance,
            closing_balance=snap.closing_balance,
            rollover_amount=snap.rollover_amount,
        )
        for snap, name in rows
    ]


@router.post("/run")
async def run_monthly_snapshot(
    year: int = Query(None),
    month: int = Query(None),
    force: bool = Query(False),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger snapshot for a budget period (admin/debug).
    year/month refer to period_start year/month. Setiap household yang punya anggota dihitung dengan tanggal gajian
    rumahnya sendiri (bukan tanggal si pemanggil), jadi periode tiap household bisa berbeda."""
    now = date.today()
    y = year or now.year
    m = month or now.month

    households = (await db.execute(
        select(Household).where(Household.id.in_(select(HouseholdMember.household_id)))
    )).scalars().all()

    # Semua tanggal dihitung dulu, lalu pengisian tanggal rumah yang NULL (`household_payday` flush di sesi ini)
    # di-commit sebelum snapshot dibuat: `create_monthly_snapshots` bekerja lewat sesinya sendiri dan tidak boleh
    # berhadapan dengan UPDATE yang belum di-commit (kontrak yang sama dengan `household_cycle.recompute_history`).
    plan = []
    for h in households:
        payday = await household_payday(db, h)
        period_start, period_end = get_period_for_month(payday, y, m)
        plan.append((h.id, period_start, period_end))
    await db.commit()

    out = []
    for household_id, period_start, period_end in plan:
        r = await create_monthly_snapshots(
            period_start, period_end, force=force, household_ids=[household_id]
        )
        out.append({"household_id": str(household_id), "period": f"{period_start} → {period_end}", **r})
    return {
        "households": out,
        "processed": sum(e["processed"] for e in out),
        "snapshots_created": sum(e["snapshots_created"] for e in out),
        "errors": [err for e in out for err in e["errors"]],
    }

@router.post("/recompute")
async def recompute_snapshots(
    periods: int = Query(6, ge=1, le=36),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hitung ulang `periods` snapshot periode tertutup terakhir household pemanggil, oldest-first dan force=True,
    dengan tanggal gajian rumah (bukan tanggal si pemanggil), supaya rantai rollover terbangun ulang dari ujung ke
    ujung. Memperbaiki rantai yang rusak karena job snapshot terlewat.

    Siklus milik rumah, jadi hanya yang boleh mengubahnya (owner/admin, atau member yang sendirian) yang boleh
    menghitung ulang riwayat; member lain mendapat 403. Tanpa household tidak ada yang dihitung."""
    ctx = await payday_context(db, user)
    if ctx is None:
        return {"recomputed": 0, "periods": []}
    if not ctx.can_change:
        raise HTTPException(
            status_code=403,
            detail="Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat.",
        )
    # `recompute_history` membaca lewat sesinya sendiri dan tidak boleh berhadapan dengan tulisan sesi ini yang belum
    # di-commit: `payday_context` bisa mengisi tanggal rumah yang NULL (flush). Commit dulu (lihat docstring
    # `household_cycle.recompute_history`).
    await db.commit()
    out = await recompute_history(ctx.household.id, periods)
    return {"recomputed": len(out), "periods": out}


@router.post("/daily-summary")
async def trigger_daily_summary(user: User = Depends(require_admin)):
    from app.services.summary import send_daily_summary
    await send_daily_summary()
    return {"status": "sent"}

@router.post("/weekly-summary")
async def trigger_weekly_summary(user: User = Depends(require_admin)):
    from app.services.summary import send_weekly_summary
    await send_weekly_summary()
    return {"status": "sent"}


@router.post("/process-recurring")
async def trigger_recurring(user: User = Depends(require_admin)):
    from app.services.recurring_processor import process_recurring_transactions
    await process_recurring_transactions()
    return {"status": "processed"}
