from decimal import Decimal
from datetime import date
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    User, Envelope, Transaction, RecurringTransaction,
    HouseholdMember,
)

PLAN_LIMITS = {
    "basic": {"envelopes": 6, "txn_per_month": 50, "recurring": 5},
    "pro": {"envelopes": -1, "txn_per_month": -1, "recurring": -1},
}


async def check_envelope_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Check if user can create more envelopes."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["envelopes"] == -1:
        return True, ""

    hid_r = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_r.scalar_one_or_none()
    if not hid:
        return True, ""

    count = (await db.execute(
        select(func.count(Envelope.id)).where(
            Envelope.household_id == hid, Envelope.is_active == True
        )
    )).scalar()

    if count >= limits["envelopes"]:
        return False, f"Limit {limits['envelopes']} amplop tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""


async def check_transaction_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Check if user can create more transactions this month."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["txn_per_month"] == -1:
        return True, ""

    now = date.today()
    count = (await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user.id,
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == now.year,
            func.extract("month", Transaction.transaction_date) == now.month,
        )
    )).scalar()

    if count >= limits["txn_per_month"]:
        return False, f"Limit {limits['txn_per_month']} transaksi/bulan tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""


async def check_recurring_limit(user: User, db: AsyncSession) -> tuple[bool, str]:
    """Check if user can create more recurring transactions."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["basic"])
    if limits["recurring"] == -1:
        return True, ""

    hid_r = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_r.scalar_one_or_none()
    if not hid:
        return True, ""

    count = (await db.execute(
        select(func.count(RecurringTransaction.id))
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(Envelope.household_id == hid, RecurringTransaction.is_active == True)
    )).scalar()

    if count >= limits["recurring"]:
        return False, f"Limit {limits['recurring']} langganan tercapai. Upgrade ke Pro untuk unlimited."
    return True, ""


def is_pro_feature(feature: str) -> bool:
    """Check if a feature is Pro-only."""
    pro_features = ["behavior_controls", "export", "analytics"]
    return feature in pro_features


def check_pro_access(user: User, feature: str) -> tuple[bool, str]:
    """Check if user has access to a Pro feature."""
    plan = getattr(user, 'plan', 'basic') or 'basic'
    if plan == 'pro':
        return True, ""
    if is_pro_feature(feature):
        return False, f"Fitur ini hanya untuk Pro. Upgrade untuk akses."
    return True, ""
