import json
import hashlib
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete, or_, exists
from pydantic import BaseModel

from app.api.routes.auth import limiter
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_session_id, get_current_user
from app.core.security import hash_password, verify_password
from app.services import account_deletion, auth_sessions
from app.services.email_service import (
    send_account_deleted_email, send_account_deletion_email, send_password_changed_email,
)
from app.services.image_upload import PROFILE_PIC_MAX_BYTES, read_image_upload, save_upload
from app.models.models import (
    User, Envelope, Transaction, Allocation, Income,
    RecurringTransaction, Notification, NotificationPreference,
    HouseholdMember, Household, HouseholdType,
    Goal, MonthlySnapshot, PendingTransaction, EnvelopeGroup, UserEnvelopeKeyword,
    UserStreak, BalanceCheck,
)
from app.services.ruang import RuangAktif, RuangTulis, ruang_keluarga_id

router = APIRouter()


class ChangeEmail(BaseModel):
    new_email: str
    password: str


class ChangePassword(BaseModel):
    current_password: str | None = None
    new_password: str


class UpdateProfile(BaseModel):
    name: str | None = None
    timezone: str | None = None
    payday_day: int | None = None
    income_type: str | None = None


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
            Transaction.balance_check_id.is_(None),  # sama dgn limit Basic (plan_limits)
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    monthly_txns = txn_count.scalar()

    # Pemakaian kuota = ruang keluarga, sama dengan plan_limits (kuota per ruang menyusul di R3).
    kuota_hid = await ruang_keluarga_id(db, user.id)
    env_count = await db.execute(
        select(func.count(Envelope.id))
        .where(Envelope.household_id == kuota_hid, Envelope.is_active == True)
    )
    total_envelopes = env_count.scalar()

    rec_count = await db.execute(
        select(func.count(RecurringTransaction.id))
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(Envelope.household_id == kuota_hid, RecurringTransaction.is_active == True)
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
        "has_password": bool(user.password_hash),
        "google_connected": bool(getattr(user, "google_id", None)),
        "timezone": getattr(user, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta',
        "payday_day": getattr(user, 'payday_day', 1) or 1,
        "income_type": getattr(user, 'income_type', 'monthly') or 'monthly',
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
    if req.income_type is not None:
        valid_types = ['monthly', 'weekly', 'daily', 'irregular']
        if req.income_type not in valid_types:
            raise HTTPException(400, f"Invalid income_type. Options: {', '.join(valid_types)}")
        user.income_type = req.income_type
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
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    sid: UUID | None = Depends(get_current_session_id),
    db: AsyncSession = Depends(get_db),
):
    # User Telegram-only belum punya password — boleh set tanpa password lama.
    if user.password_hash:
        if not req.current_password or not verify_password(req.current_password, user.password_hash):
            raise HTTPException(400, "Password lama salah")
    if len(req.new_password) < 6:
        raise HTTPException(400, "Password baru minimal 6 karakter")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    # Perangkat lain keluar; perangkat yang mengganti sandi tetap login.
    await auth_sessions.revoke_all(db, user, "password_change", except_sid=sid)
    if user.email:
        background_tasks.add_task(send_password_changed_email, user.email, user.name)
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
    # Jenis dari isi file, nama file dari server: nama dan content-type kiriman klien tidak dipakai (lihat image_upload).
    data, ext = await read_image_upload(file, PROFILE_PIC_MAX_BYTES)
    user.profile_pic = save_upload(str(user.id), ext, data)
    await db.commit()
    return {"url": user.profile_pic}


@router.get("/export-data")
async def export_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    """Export all user data as JSON.

    Ruang (R2): amplop dan langganan dari ruang aktif. Transaksi dan pemasukan milik user: di ruang
    usaha hanya catatan ruang itu; di ruang keluarga semua catatan user di luar ruang usaha mana pun
    (termasuk household lama yang sudah ditinggalkan, seperti sebelumnya). Tidak ada data ruang
    usaha di ekspor ruang keluarga, dan sebaliknya (AGENTS.md "Plugin dan ruang" aturan 8).
    """
    ruang = await db.get(Household, hid) if hid else None
    if ruang is not None and str(ruang.type) == HouseholdType.USAHA:
        txn_ruang = Transaction.envelope_id.in_(select(Envelope.id).where(Envelope.household_id == hid))
        inc_ruang = Income.household_id == hid
    else:
        usaha = select(Household.id).where(Household.type == HouseholdType.USAHA)
        txn_ruang = Transaction.envelope_id.not_in(select(Envelope.id).where(Envelope.household_id.in_(usaha)))
        inc_ruang = Income.household_id.not_in(usaha)

    # Envelopes
    env_result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    envelopes = [{"name": e.name, "emoji": e.emoji, "budget": str(e.budget_amount)} for e in env_result.scalars().all()]

    # Transactions
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.is_deleted == False, txn_ruang)
        .order_by(Transaction.created_at)
    )
    transactions = [
        {"date": str(t.transaction_date), "amount": str(t.amount), "description": t.description, "source": t.source.value if t.source else None}
        for t in txn_result.scalars().all()
    ]

    # Incomes
    inc_result = await db.execute(
        select(Income).where(Income.user_id == user.id, inc_ruang).order_by(Income.created_at)
    )
    incomes = [{"date": str(i.income_date), "amount": str(i.amount), "source": getattr(i, "source", None)} for i in inc_result.scalars().all()]

    # Recurring
    rec_result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            RecurringTransaction.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
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
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hapus akun permanen + cabut semua sesi (app/services/account_deletion.py)."""
    await _delete_and_notify(db, user, background_tasks)
    return {"status": "deleted"}


GENERIC_DELETION_MESSAGE = "Kalau email terdaftar, link konfirmasi hapus akun sudah dikirim."


class DeletionRequest(BaseModel):
    email: str


class DeletionConfirm(BaseModel):
    token: str


async def _delete_and_notify(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    email, name = user.email, user.name
    files = await account_deletion.delete_account(db, user)
    background_tasks.add_task(account_deletion.remove_files, files)
    if email and not email.startswith(("deleted_", "banned_")):
        background_tasks.add_task(send_account_deleted_email, email, name)


@router.post("/account/deletion-request")
@limiter.limit("3/minute")
async def request_account_deletion(
    request: Request,
    req: DeletionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Halaman /hapus-akun tanpa login: kirim link konfirmasi ke email akun.
    Jawaban selalu sama supaya tidak membocorkan email mana yang terdaftar."""
    email = req.email.strip().lower()
    user = None
    if email and not email.startswith(("deleted_", "banned_")):
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user and user.id != account_deletion.FORMER_MEMBER_ID:
        r = aioredis.from_url(get_settings().REDIS_URL)
        try:
            token = await account_deletion.create_deletion_token(r, str(user.id))
        finally:
            await r.close()
        url = f"https://jatahku.com/hapus-akun?token={token}"
        background_tasks.add_task(send_account_deletion_email, user.email, user.name, url)
    return {"message": GENERIC_DELETION_MESSAGE}


@router.post("/account/deletion-confirm")
@limiter.limit("5/minute")
async def confirm_account_deletion(
    request: Request,
    req: DeletionConfirm,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Link dari email permintaan hapus: token sekali pakai → akun dihapus."""
    r = aioredis.from_url(get_settings().REDIS_URL)
    try:
        user_id = await account_deletion.redeem_deletion_token(r, req.token)
    finally:
        await r.close()
    user = None
    try:
        if user_id:
            user = (await db.execute(select(User).where(User.id == UUID(user_id)))).scalar_one_or_none()
    except ValueError:
        pass
    if not user or user.id == account_deletion.FORMER_MEMBER_ID:
        raise HTTPException(400, "Link tidak valid atau sudah kadaluarsa")
    await _delete_and_notify(db, user, background_tasks)
    return {"status": "deleted"}


@router.post("/logout-all")
async def logout_all(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cabut semua sesi user, termasuk perangkat ini (app/services/auth_sessions.py)."""
    user.updated_at = datetime.now(timezone.utc)
    await auth_sessions.revoke_all(db, user, "logout_all")
    return {"status": "all_sessions_invalidated"}


@router.post("/reset")
async def reset_data(
    req: ResetDataRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangTulis,
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

    # Guard: fail early if household not found
    if not hid:
        raise HTTPException(400, "Data tidak ditemukan")

    # Only household owner can reset data
    role_result = await db.execute(
        select(HouseholdMember.role).where(HouseholdMember.user_id == user.id, HouseholdMember.household_id == hid)
    )
    role = role_result.scalar_one_or_none()
    if role != "owner":
        raise HTTPException(403, "Hanya owner household yang bisa reset data")

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
        .where(Transaction.user_id == user.id, Transaction.is_deleted == False,
               Transaction.envelope_id.in_(env_ids))  # cadangan = yang ikut dihapus, ruang ini saja
        .order_by(Transaction.created_at)
    )
    transactions_data = [
        {"date": str(t.transaction_date), "amount": str(t.amount), "description": t.description}
        for t in txn_result.scalars().all()
    ]

    inc_result = await db.execute(
        select(Income).where(Income.user_id == user.id, Income.household_id == hid).order_by(Income.created_at)
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

    # Hanya pemasukan user di ruang yang di-reset. Dulu semua pemasukan user di household mana pun
    # ikut terhapus, termasuk household lama yang masih dipakai anggota lain (saldonya rusak) dan,
    # sejak R1, ruang usaha (AGENTS.md "Plugin dan ruang" aturan 8).
    inc_scope = (Income.user_id == user.id, Income.household_id == hid)
    inc_ids_result = await db.execute(select(Income.id).where(*inc_scope))
    inc_ids = [row[0] for row in inc_ids_result.all()]
    if inc_ids:
        await db.execute(delete(Allocation).where(Allocation.income_id.in_(inc_ids)))
    await db.execute(delete(Income).where(*inc_scope))

    # Log cocokkan saldo household ikut dihapus — kecuali yang masih dirujuk
    # income penyesuaian milik anggota lain (income mereka tidak ikut di-reset).
    await db.execute(
        delete(BalanceCheck).where(
            BalanceCheck.household_id == hid,
            ~exists().where(Income.balance_check_id == BalanceCheck.id),
        )
    )

    await db.execute(delete(EnvelopeGroup).where(EnvelopeGroup.household_id == hid))

    await db.commit()
    return {"success": True, "email_sent": email_sent}
