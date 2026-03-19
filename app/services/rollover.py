import logging
from decimal import Decimal
from datetime import date
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.models import Envelope, Transaction, Allocation, MonthlySnapshot, Household

logger = logging.getLogger("jatahku.rollover")


async def calculate_envelope_balance(env_id, year, month, db: AsyncSession) -> dict:
    """Calculate spent and allocated for an envelope in a specific month."""
    spent_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == env_id,
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == year,
            func.extract("month", Transaction.transaction_date) == month,
        )
    )
    spent = Decimal(str(spent_result.scalar()))

    allocated_result = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.envelope_id == env_id,
        )
    )
    allocated = Decimal(str(allocated_result.scalar()))

    return {"spent": spent, "allocated": allocated}


async def get_previous_rollover(env_id, year, month, db: AsyncSession) -> Decimal:
    """Get rollover amount from the previous month's snapshot."""
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


async def create_monthly_snapshots(target_year: int, target_month: int) -> dict:
    """Create snapshots for all envelopes for the given month.
    Call this at the START of a new month to snapshot the PREVIOUS month."""
    async with AsyncSessionLocal() as db:
        # Get all households
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
                    existing = await db.execute(
                        select(MonthlySnapshot).where(
                            MonthlySnapshot.envelope_id == env.id,
                            MonthlySnapshot.year == target_year,
                            MonthlySnapshot.month == target_month,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue  # Already snapshotted

                    # Get previous rollover
                    prev_rollover = await get_previous_rollover(
                        env.id, target_year, target_month, db
                    )

                    # Opening balance = budget + previous rollover
                    opening = env.budget_amount + prev_rollover

                    # Calculate spent this month
                    balance = await calculate_envelope_balance(
                        env.id, target_year, target_month, db
                    )
                    spent = balance["spent"]

                    # Closing balance = opening - spent
                    closing = opening - spent

                    # Rollover to next month
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
            f"Monthly snapshots for {target_year}-{target_month:02d}: "
            f"{results['snapshots_created']} created, {len(results['errors'])} errors"
        )
        return results


async def get_effective_budget(env_id, year, month, db: AsyncSession) -> Decimal:
    """Get effective budget for an envelope in a given month.
    Effective = base budget + rollover from previous month."""
    env_result = await db.execute(select(Envelope).where(Envelope.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        return Decimal("0")

    prev_rollover = await get_previous_rollover(env_id, year, month, db)
    return env.budget_amount + prev_rollover
