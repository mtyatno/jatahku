import logging
from uuid import UUID
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import (
    User, Household, HouseholdMember, Envelope,
    Transaction, Income, Allocation, MonthlySnapshot,
    RecurringTransaction, Goal,
)

logger = logging.getLogger("jatahku.merge")


async def get_merge_preview(source_user_id: UUID, target_user_id: UUID, db: AsyncSession) -> dict:
    """Preview what will be merged. Source = TG user (will be deleted), Target = WebApp user (keeps)."""

    # Source user info
    src = await db.execute(select(User).where(User.id == source_user_id))
    source = src.scalar_one_or_none()
    if not source:
        return {"error": "Source user not found"}

    # Target user info
    tgt = await db.execute(select(User).where(User.id == target_user_id))
    target = tgt.scalar_one_or_none()
    if not target:
        return {"error": "Target user not found"}

    # Source household
    src_member = await db.execute(
        select(HouseholdMember).where(HouseholdMember.user_id == source_user_id)
    )
    src_membership = src_member.scalar_one_or_none()

    # Target household
    tgt_member = await db.execute(
        select(HouseholdMember).where(HouseholdMember.user_id == target_user_id)
    )
    tgt_membership = tgt_member.scalar_one_or_none()

    source_hh = None
    target_hh = None
    source_envelopes = 0
    target_envelopes = 0
    source_transactions = 0
    source_members = 0
    target_members = 0

    if src_membership:
        h = await db.execute(select(Household).where(Household.id == src_membership.household_id))
        source_hh = h.scalar_one_or_none()
        env_count = await db.execute(
            select(func.count(Envelope.id)).where(
                Envelope.household_id == src_membership.household_id, Envelope.is_active == True
            )
        )
        source_envelopes = env_count.scalar()
        mem_count = await db.execute(
            select(func.count(HouseholdMember.id)).where(
                HouseholdMember.household_id == src_membership.household_id
            )
        )
        source_members = mem_count.scalar()

    if tgt_membership:
        h = await db.execute(select(Household).where(Household.id == tgt_membership.household_id))
        target_hh = h.scalar_one_or_none()
        env_count = await db.execute(
            select(func.count(Envelope.id)).where(
                Envelope.household_id == tgt_membership.household_id, Envelope.is_active == True
            )
        )
        target_envelopes = env_count.scalar()
        mem_count = await db.execute(
            select(func.count(HouseholdMember.id)).where(
                HouseholdMember.household_id == tgt_membership.household_id
            )
        )
        target_members = mem_count.scalar()

    txn_count = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == source_user_id, Transaction.is_deleted == False
        )
    )
    source_transactions = txn_count.scalar()

    return {
        "source": {
            "user_id": str(source_user_id),
            "name": source.name,
            "household_name": source_hh.name if source_hh else None,
            "household_id": str(src_membership.household_id) if src_membership else None,
            "envelopes": source_envelopes,
            "transactions": source_transactions,
            "members": source_members,
        },
        "target": {
            "user_id": str(target_user_id),
            "name": target.name,
            "household_name": target_hh.name if target_hh else None,
            "household_id": str(tgt_membership.household_id) if tgt_membership else None,
            "envelopes": target_envelopes,
            "members": target_members,
        },
    }


async def merge_users(
    source_user_id: UUID,
    target_user_id: UUID,
    keep_household_id: UUID,
    db: AsyncSession,
) -> dict:
    """Merge source user into target user.
    - Move source's data to target
    - Keep the chosen household
    - Delete source user
    """
    source = await db.execute(select(User).where(User.id == source_user_id))
    source_user = source.scalar_one_or_none()
    if not source_user:
        return {"error": "Source user not found"}

    target = await db.execute(select(User).where(User.id == target_user_id))
    target_user = target.scalar_one_or_none()
    if not target_user:
        return {"error": "Target user not found"}

    # Get both memberships
    src_mem = await db.execute(
        select(HouseholdMember).where(HouseholdMember.user_id == source_user_id)
    )
    src_membership = src_mem.scalar_one_or_none()

    tgt_mem = await db.execute(
        select(HouseholdMember).where(HouseholdMember.user_id == target_user_id)
    )
    tgt_membership = tgt_mem.scalar_one_or_none()

    src_hh_id = src_membership.household_id if src_membership else None
    tgt_hh_id = tgt_membership.household_id if tgt_membership else None
    discard_hh_id = tgt_hh_id if keep_household_id == src_hh_id else src_hh_id

    # 1. Reassign source's transactions → target
    await db.execute(
        update(Transaction).where(Transaction.user_id == source_user_id)
        .values(user_id=target_user_id)
    )

    # 2. Reassign source's incomes → target
    await db.execute(
        update(Income).where(Income.user_id == source_user_id)
        .values(user_id=target_user_id)
    )

    # 3. Reassign personal envelopes → target
    await db.execute(
        update(Envelope).where(Envelope.owner_id == source_user_id)
        .values(owner_id=target_user_id)
    )

    # 4. Handle households
    if keep_household_id and discard_hh_id and str(keep_household_id) != str(discard_hh_id):
        # Move envelopes from discarded household to kept household
        await db.execute(
            update(Envelope).where(Envelope.household_id == discard_hh_id)
            .values(household_id=keep_household_id)
        )

        # Move incomes from discarded household
        await db.execute(
            update(Income).where(Income.household_id == discard_hh_id)
            .values(household_id=keep_household_id)
        )

        # Remove all memberships from discarded household
        await db.execute(
            delete(HouseholdMember).where(HouseholdMember.household_id == discard_hh_id)
        )

        # Delete discarded household
        await db.execute(delete(Household).where(Household.id == discard_hh_id))

    # 5. Ensure target is member of kept household
    if keep_household_id:
        existing = await db.execute(
            select(HouseholdMember).where(
                HouseholdMember.user_id == target_user_id,
                HouseholdMember.household_id == keep_household_id,
            )
        )
        if not existing.scalar_one_or_none():
            # Remove old membership
            await db.execute(
                delete(HouseholdMember).where(HouseholdMember.user_id == target_user_id)
            )
            db.add(HouseholdMember(
                user_id=target_user_id,
                household_id=keep_household_id,
                role=src_membership.role if src_membership and src_membership.household_id == keep_household_id else tgt_membership.role,
            ))

    # 6. Transfer telegram_id to target (clear source first to avoid unique constraint)
    tg_id = source_user.telegram_id
    source_user.telegram_id = None
    await db.flush()
    target_user.telegram_id = tg_id

    # 7. Remove source memberships
    await db.execute(
        delete(HouseholdMember).where(HouseholdMember.user_id == source_user_id)
    )

    # 8. Delete source user
    await db.execute(delete(User).where(User.id == source_user_id))

    await db.commit()

    logger.info(f"Merged user {source_user_id} into {target_user_id}, kept household {keep_household_id}")

    return {
        "status": "merged",
        "kept_household": str(keep_household_id),
        "target_user": str(target_user_id),
    }
