import logging
from decimal import Decimal
from datetime import date
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.models import Envelope, Transaction, Allocation, MonthlySnapshot, Household, Income

logger = logging.getLogger("jatahku.rollover")


async def calculate_envelope_balance(env_id, period_start: date, period_end: date, db: AsyncSession) -> dict:
    """Calculate spent and allocated for an envelope within a budget period date range."""
    spent_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == env_id,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    spent = Decimal(str(spent_result.scalar()))

    allocated_result = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id == env_id,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )
    allocated = Decimal(str(allocated_result.scalar()))

    return {"spent": spent, "allocated": allocated}


async def get_previous_rollover(env_id, year, month, db: AsyncSession) -> Decimal:
    """Get rollover amount from the previous period's snapshot (keyed by period_start year/month)."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    result = await db.execute(
        select(MonthlySnapshot.rollover_amount).where(
            MonthlySnapshot.envelope_id == env_id,
            MonthlySnapshot.year == prev_year,
            MonthlySnapshot.month == prev_month,
        )
    )
    rollover = result.scalar_one_or_none()
    return rollover if rollover is not None else Decimal("0")


async def create_monthly_snapshots(period_start: date, period_end: date, force: bool = False) -> dict:
    """Create snapshots for all envelopes for the given budget period.
    Snapshot is keyed by period_start.year and period_start.month.
    Set force=True to overwrite an existing snapshot."""
    target_year = period_start.year
    target_month = period_start.month

    async with AsyncSessionLocal() as db:
        households = await db.execute(select(Household))
        results = {"processed": 0, "snapshots_created": 0, "errors": []}

        for household in households.scalars().all():
            envelopes_result = await db.execute(
                select(Envelope).where(
                    Envelope.household_id == household.id,
                    Envelope.is_active == True,
                )
            )
            envelopes = envelopes_result.scalars().all()

            for env in envelopes:
                try:
                    # Check if snapshot already exists
                    existing_result = await db.execute(
                        select(MonthlySnapshot).where(
                            MonthlySnapshot.envelope_id == env.id,
                            MonthlySnapshot.year == target_year,
                            MonthlySnapshot.month == target_month,
                        )
                    )
                    existing = existing_result.scalar_one_or_none()
                    if existing:
                        if not force:
                            results["processed"] += 1
                            continue
                        await db.delete(existing)
                        await db.flush()

                    # Get previous rollover (keyed by period_start year/month)
                    prev_rollover = await get_previous_rollover(
                        env.id, target_year, target_month, db
                    )

                    # Calculate actual allocated + spent within this period's date range
                    balance = await calculate_envelope_balance(
                        env.id, period_start, period_end, db
                    )
                    spent = balance["spent"]
                    allocated = balance["allocated"]

                    # Opening balance = actual income allocated + rollover carried in
                    opening = allocated + prev_rollover

                    # Closing balance = opening - spent
                    closing = opening - spent

                    # Rollover to next period
                    if env.is_rollover:
                        rollover = closing  # Carry full balance (positive or negative)
                    else:
                        rollover = Decimal("0")  # Reset

                    snapshot = MonthlySnapshot(
                        envelope_id=env.id,
                        year=target_year,
                        month=target_month,
                        opening_balance=opening,
                        closing_balance=closing,
                        rollover_amount=rollover,
                    )
                    db.add(snapshot)
                    results["snapshots_created"] += 1

                except Exception as e:
                    results["errors"].append(f"{env.name}: {str(e)}")

                results["processed"] += 1

        await db.commit()
        logger.info(
            f"Snapshots for period {period_start}→{period_end} "
            f"(key {target_year}-{target_month:02d}): "
            f"{results['snapshots_created']} created, {len(results['errors'])} errors"
        )
        return results


async def get_effective_budget(env_id, period_start: date, period_end: date, db: AsyncSession) -> Decimal:
    """Get effective budget for an envelope in a given period.
    Effective = actual allocated income + rollover from previous period."""
    env_result = await db.execute(select(Envelope).where(Envelope.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        return Decimal("0")

    prev_rollover = await get_previous_rollover(env_id, period_start.year, period_start.month, db)
    balance = await calculate_envelope_balance(env_id, period_start, period_end, db)
    return balance["allocated"] + prev_rollover
