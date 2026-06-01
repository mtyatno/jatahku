import os
import json
import hashlib
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.models.models import (
    User, Envelope, Transaction, Allocation, Income,
    RecurringTransaction, Notification, NotificationPreference,
    HouseholdMember, Household,
    Goal, MonthlySnapshot, PendingTransaction, EnvelopeGroup, UserEnvelopeKeyword,
    UserStreak,
)

router = APIRouter()


class ChangeEmail(BaseModel):
    new_email: str
    password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class UpdateProfile(BaseModel):
    name: str | None = None
    timezone: str | None = None
    payday_day: int | None = None


class DefaultBehavior(BaseModel):
    default_cooling_threshold: Decimal | None = None
    default_daily_limit: Decimal | None = None
    default_is_locked: bool = False


class ResetDataRequest(BaseModel):
    email: str | None = None  # only provided if user has no email yet


@router.get("/streak")
async def get_streak_info(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current logging-discipline streak for the dashboard badge."""
    from app.services.streak import get_streak, user_today
    s = await get_streak(db, user.id, getattr(user, "timezone", None))
    streak_row = await db.get(UserStreak, user.id)
    logged_today = bool(
        streak_row and streak_row.last_log_date == user_today(getattr(user, "timezone", None))
    )
    return {
        "current_streak": s.current_streak,
        "longest_streak": s.longest_streak,
        "total_logged_days": s.total_logged_days,
        "logged_today": logged_today,
    }


@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Count usage within current budget period
    from datetime import date
    from app.core.period import get_budget_period
    payday_day = getattr(user, 'payday_day', 1) or 1
    period_start, period_end = get_budget_period(payday_day)
    txn_count = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user.id,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    monthly_txns = txn_count.scalar()

    env_count = await db.execute(
        select(func.count(Envelope.id))
        .join(HouseholdMember, HouseholdMember.household_id == Envelope.household_id)
        .where(HouseholdMember.user_id == user.id, Envelope.is_active == True)
    )
    total_envelopes = env_count.scalar()

    rec_count = await db.execute(
        select(func.count(RecurringTransaction.id))
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .join(HouseholdMember, HouseholdMember.household_id == Envelope.household_id)
        .where(HouseholdMember.user_id == user.id, RecurringTransaction.is_active == True)
    )
    total_recurring = rec_count.scalar()

    plan = getattr(user, 'plan', 'basic') or 'basic'
    limits = {
        "basic": {"envelopes": 6, "txn_per_month": 50, "recurring": 5},
        "pro": {"envelopes": -1, "txn_per_month": -1, "recurring": -1},
    }
    plan_limits = limits.get(plan, limits["basic"])

    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "telegram_id": user.telegram_id,
        "timezone": getattr(user, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta',
        "payday_day": getattr(user, 'payday_day', 1) or 1,
        "profile_pic": getattr(user, 'profile_pic', None),
        "plan": plan,
        "default_cooling_threshold": str(user.default_cooling_threshold) if getattr(user, 'default_cooling_threshold', None) else None,
        "default_daily_limit": str(user.default_daily_limit) if getattr(user, 'default_daily_limit', None) else None,
        "default_is_locked": getattr(user, 'default_is_locked', False),
        "last_login": user.last_login.isoformat() if getattr(user, 'last_login', None) else None,
        "usage": {
            "envelopes": total_envelopes,
            "txn_this_month": monthly_txns,
            "recurring": total_recurring,
        },
        "limits": plan_limits,
        "created_at": user.created_at.isoformat(),
    }


@router.put("/profile")
async def update_profile(
    req: UpdateProfile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.name is not None:
        user.name = req.name
    if req.timezone is not None:
        valid_tz = [
            'Asia/Jakarta', 'Asia/Makassar', 'Asia/Jayapura',
            'UTC', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Seoul',
            'Asia/Kuala_Lumpur', 'Asia/Bangkok', 'Asia/Dubai',
            'Europe/London', 'Europe/Berlin', 'America/New_York',
            'America/Los_Angeles', 'Australia/Sydney',
        ]
        if req.timezone not in valid_tz:
            raise HTTPException(400, f"Invalid timezone. Options: {', '.join(valid_tz)}")
        user.timezone = req.timezone
    if req.payday_day is not None:
        if not (1 <= req.payday_day <= 31):
            raise HTTPException(400, "payday_day harus antara 1 dan 31")
        user.payday_day = req.payday_day
    await db.commit()
    return {"status": "updated"}


@router.put("/email")
async def change_email(
    req: ChangeEmail,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(400, "Password salah")
    existing = await db.execute(select(User).where(User.email == req.new_email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email sudah digunakan")
    user.email = req.new_email
    await db.commit()
    return {"status": "updated"}


@router.put("/password")
async def change_password(
    req: ChangePassword,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(400, "Password lama salah")
    if len(req.new_password) < 6:
        raise HTTPException(400, "Password baru minimal 6 karakter")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"status": "updated"}


@router.put("/behavior-defaults")
async def update_behavior_defaults(
    req: DefaultBehavior,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.default_cooling_threshold = req.default_cooling_threshold
    user.default_daily_limit = req.default_daily_limit
    user.default_is_locked = req.default_is_locked
    await db.commit()
    return {"status": "updated"}


@router.post("/profile-pic")
async def upload_profile_pic(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File harus gambar")
    if file.size and file.size > 2_000_000:
        raise HTTPException(400, "Max 2MB")
    data = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    fname = f"{user.id}.{ext}"
    upload_dir = "/home/jatahku/web/jatahku.com/public_html/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    with open(f"{upload_dir}/{fname}", "wb") as f:
        f.write(data)
    user.profile_pic = f"/uploads/{fname}"
    await db.commit()
    return {"url": user.profile_pic}


@router.get("/export-data")
async def export_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user data as JSON."""
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()

    # Envelopes
    env_result = await db.execute(
        select(Envelope).where(Envelope.household_id == hid, Envelope.is_active == True)
    )
    envelopes = [{"name": e.name, "emoji": e.emoji, "budget": str(e.budget_amount)} for e in env_result.scalars().all()]

    # Transactions
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.is_deleted == False)
        .order_by(Transaction.created_at)
    )
    transactions = [
        {"date": str(t.transaction_date), "amount": str(t.amount), "description": t.description, "source": t.source.value if t.source else None}
        for t in txn_result.scalars().all()
    ]

    # Incomes
    inc_result = await db.execute(
        select(Income).where(Income.user_id == user.id).order_by(Income.created_at)
    )
    incomes = [{"date": str(i.income_date), "amount": str(i.amount), "source": getattr(i, "source", None)} for i in inc_result.scalars().all()]

    # Recurring
    rec_result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(Envelope.household_id == hid, RecurringTransaction.is_active == True)
    )
    recurring = [{"description": r.description, "amount": str(r.amount), "frequency": r.frequency.value} for r in rec_result.scalars().all()]

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"name": user.name, "email": user.email},
        "envelopes": envelopes,
        "transactions": transactions,
        "incomes": incomes,
        "recurring": recurring,
    }


@router.delete("/account")
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete: anonymize user data."""
    user.email = f"deleted_{user.id}@jatahku.com"
    user.name = "Deleted User"
    user.password_hash = "DELETED"
    user.telegram_id = None
    user.profile_pic = None

    # Soft delete transactions
    await db.execute(
        update(Transaction).where(Transaction.user_id == user.id).values(is_deleted=True)
    )

    # Deactivate envelopes
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()
    if hid:
        await db.execute(
            update(Envelope).where(Envelope.household_id == hid).values(is_active=False)
        )

    await db.commit()
    return {"status": "deleted"}


@router.post("/logout-all")
async def logout_all(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate all sessions by changing password hash salt."""
    # Simple approach: bump updated_at which invalidates JWTs issued before
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "all_sessions_invalidated"}


@router.post("/reset")
async def reset_data(
    req: ResetDataRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date as _date
    from app.services.email_service import send_data_backup_email

    # Save new email if provided (user had no email before)
    if req.email:
        existing = await db.execute(
            select(User).where(User.email == req.email, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email sudah digunakan")
        user.email = req.email
        await db.flush()

    # Resolve household id
    hid_result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = hid_result.scalar_one_or_none()

    # Guard: fail early if household not found
    if not hid:
        raise HTTPException(400, "Data tidak ditemukan")

    # Collect envelope ids
    env_ids: list = []
    if hid:
        env_ids_result = await db.execute(
            select(Envelope.id).where(Envelope.household_id == hid)
        )
        env_ids = [row[0] for row in env_ids_result.all()]

    # --- Build export payload ---
    envelopes_data = []
    if env_ids:
        env_result = await db.execute(select(Envelope).where(Envelope.id.in_(env_ids)))
        envelopes_data = [
            {"name": e.name, "emoji": e.emoji, "budget": str(e.budget_amount)}
            for e in env_result.scalars().all()
        ]

    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.is_deleted == False)
        .order_by(Transaction.created_at)
    )
    transactions_data = [
        {"date": str(t.transaction_date), "amount": str(t.amount), "description": t.description}
        for t in txn_result.scalars().all()
    ]

    inc_result = await db.execute(
        select(Income).where(Income.user_id == user.id).order_by(Income.created_at)
    )
    incomes_data = [
        {"date": str(i.income_date), "amount": str(i.amount), "description": i.description}
        for i in inc_result.scalars().all()
    ]

    recurring_data = []
    if env_ids:
        rec_result = await db.execute(
            select(RecurringTransaction)
            .where(RecurringTransaction.envelope_id.in_(env_ids))
        )
        recurring_data = [
            {"description": r.description, "amount": str(r.amount), "frequency": r.frequency.value}
            for r in rec_result.scalars().all()
        ]

    export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"name": user.name, "email": user.email},
        "envelopes": envelopes_data,
        "transactions": transactions_data,
        "incomes": incomes_data,
        "recurring": recurring_data,
    }

    # --- Send backup email (non-blocking: reset proceeds even if email fails) ---
    email_sent = False
    if user.email:
        filename = f"jatahku-backup-{_date.today().isoformat()}.json"
        email_sent = send_data_backup_email(user.email, user.name, export, filename)

    # --- Hard delete in FK-safe order ---
    if env_ids:
        await db.execute(delete(PendingTransaction).where(PendingTransaction.envelope_id.in_(env_ids)))
        await db.execute(delete(Transaction).where(Transaction.envelope_id.in_(env_ids)))
        await db.execute(delete(Allocation).where(Allocation.envelope_id.in_(env_ids)))
        await db.execute(delete(Goal).where(Goal.envelope_id.in_(env_ids)))
        await db.execute(delete(MonthlySnapshot).where(MonthlySnapshot.envelope_id.in_(env_ids)))
        await db.execute(delete(RecurringTransaction).where(RecurringTransaction.envelope_id.in_(env_ids)))
        await db.execute(delete(UserEnvelopeKeyword).where(UserEnvelopeKeyword.envelope_id.in_(env_ids)))
        await db.execute(delete(Envelope).where(Envelope.id.in_(env_ids)))

    inc_ids_result = await db.execute(select(Income.id).where(Income.user_id == user.id))
    inc_ids = [row[0] for row in inc_ids_result.all()]
    if inc_ids:
        await db.execute(delete(Allocation).where(Allocation.income_id.in_(inc_ids)))
    await db.execute(delete(Income).where(Income.user_id == user.id))

    await db.execute(delete(EnvelopeGroup).where(EnvelopeGroup.household_id == hid))

    await db.commit()
    return {"success": True, "email_sent": email_sent}
