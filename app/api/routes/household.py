import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.models.models import User, Household, HouseholdMember, HouseholdRole

settings = get_settings()
router = APIRouter()

INVITE_TTL = 86400  # 24 hours


class InviteResponse(BaseModel):
    code: str
    household_name: str
    expires_in: int = INVITE_TTL


class HouseholdResponse(BaseModel):
    id: UUID
    name: str
    currency: str
    member_count: int


class MemberResponse(BaseModel):
    user_id: UUID
    name: str
    role: str
    telegram_linked: bool


async def _redis():
    return aioredis.from_url(settings.REDIS_URL)


async def _get_membership(user: User, db: AsyncSession):
    result = await db.execute(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


@router.get("/", response_model=HouseholdResponse)
async def get_household(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _get_membership(user, db)
    if not membership:
        raise HTTPException(status_code=404, detail="No household found")

    result = await db.execute(
        select(Household).where(Household.id == membership.household_id)
    )
    household = result.scalar_one_or_none()

    count_result = await db.execute(
        select(func.count(HouseholdMember.id)).where(
            HouseholdMember.household_id == household.id
        )
    )
    count = count_result.scalar()

    return HouseholdResponse(
        id=household.id, name=household.name,
        currency=household.currency, member_count=count,
    )


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _get_membership(user, db)
    if not membership:
        raise HTTPException(status_code=404, detail="No household found")

    result = await db.execute(
        select(HouseholdMember, User)
        .join(User, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == membership.household_id)
    )
    rows = result.all()

    return [
        MemberResponse(
            user_id=member.user_id, name=u.name,
            role=member.role.value,
            telegram_linked=u.telegram_id is not None,
        )
        for member, u in rows
    ]


@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _get_membership(user, db)
    if not membership:
        raise HTTPException(status_code=404, detail="No household found")

    if membership.role not in (HouseholdRole.owner, HouseholdRole.admin):
        raise HTTPException(status_code=403, detail="Hanya owner/admin yang bisa invite")

    result = await db.execute(
        select(Household).where(Household.id == membership.household_id)
    )
    household = result.scalar_one()

    code = secrets.token_urlsafe(6)[:8].upper()
    r = await _redis()
    await r.set(f"invite:{code}", str(household.id), ex=INVITE_TTL)
    await r.close()

    return InviteResponse(code=code, household_name=household.name)


@router.post("/join")
async def join_household(
    code: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await _redis()
    household_id = await r.get(f"invite:{code}")
    await r.close()

    if not household_id:
        raise HTTPException(status_code=400, detail="Kode invite tidak valid atau expired")

    household_id = household_id.decode()

    # Check user not already in this household
    existing = await db.execute(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == UUID(household_id),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Kamu sudah bergabung di household ini")

    # Remove from old household
    old_membership = await _get_membership(user, db)
    if old_membership:
        await db.delete(old_membership)

    # Join new household
    new_member = HouseholdMember(
        user_id=user.id,
        household_id=UUID(household_id),
        role=HouseholdRole.member,
    )
    db.add(new_member)
    await db.commit()

    result = await db.execute(
        select(Household).where(Household.id == UUID(household_id))
    )
    household = result.scalar_one()

    # Delete used invite code
    r = await _redis()
    await r.delete(f"invite:{code}")
    await r.close()

    return {"status": "joined", "household_name": household.name}
