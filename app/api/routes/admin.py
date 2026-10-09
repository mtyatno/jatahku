from uuid import UUID
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models.models import (
    User, Envelope, Transaction, Allocation, Income,
    HouseholdMember, Household, RecurringTransaction,
    Notification, NotificationType,
)

router = APIRouter()


def fmt(n):
    n = float(n)
    if n >= 1_000_000:
        return f"Rp {n/1_000_000:.1f} jt"
    if n >= 1_000:
        return f"Rp {int(n/1_000)} rb"
    return f"Rp {int(n)}"


@router.get("/dashboard")
async def admin_dashboard(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Total users
    total_users = (await db.execute(select(func.count(User.id)))).scalar()

    # Users this week
    week_users = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )).scalar()

    # Users today
    today_users = (await db.execute(
        select(func.count(User.id)).where(func.date(User.created_at) == today)
    )).scalar()

    # Pro users
    pro_users = (await db.execute(
        select(func.count(User.id)).where(User.plan == 'pro')
    )).scalar()

    # Basic users
    basic_users = (await db.execute(
        select(func.count(User.id)).where(User.plan != 'pro')
    )).scalar()

    # Telegram linked
    tg_linked = (await db.execute(
        select(func.count(User.id)).where(User.telegram_id != None)
    )).scalar()

    # Total transactions
    total_txns = (await db.execute(
        select(func.count(Transaction.id)).where(Transaction.is_deleted == False, Transaction.balance_check_id.is_(None))
    )).scalar()

    # Today transactions
    today_txns = (await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.is_deleted == False,
            Transaction.transaction_date == today,
            Transaction.balance_check_id.is_(None),
        )
    )).scalar()

    # Total spending today
    today_spent = (await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.is_deleted == False,
            Transaction.transaction_date == today,
            Transaction.balance_check_id.is_(None),
        )
    )).scalar()

    # Total spending this month
    month_spent = (await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.is_deleted == False,
            func.extract("year", Transaction.transaction_date) == today.year,
            func.extract("month", Transaction.transaction_date) == today.month,
        )
    )).scalar()

    # Total managed (all allocations)
    total_managed = (await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
    )).scalar()

    # Daily signups last 14 days
    signups = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        count = (await db.execute(
            select(func.count(User.id)).where(func.date(User.created_at) == d)
        )).scalar()
        signups.append({"date": str(d), "count": count})

    # Daily transactions last 14 days
    daily_txns = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        count = (await db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.is_deleted == False,
                Transaction.transaction_date == d,
                Transaction.balance_check_id.is_(None),
            )
        )).scalar()
        amount = (await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.is_deleted == False,
                Transaction.transaction_date == d,
                Transaction.balance_check_id.is_(None),
            )
        )).scalar()
        daily_txns.append({"date": str(d), "count": count, "amount": float(amount)})

    return {
        "users": {
            "total": total_users, "today": today_users, "this_week": week_users,
            "pro": pro_users, "basic": basic_users, "tg_linked": tg_linked,
        },
        "transactions": {
            "total": total_txns, "today": today_txns,
            "today_amount": fmt(today_spent),
            "month_amount": fmt(month_spent),
            "total_managed": fmt(total_managed),
        },
        "charts": {
            "signups": signups,
            "daily_txns": daily_txns,
        },
    }


@router.get("/users")
async def list_users(
    search: str = Query(None),
    plan: str = Query(None),
    status: str = Query(None),
    limit: int = Query(200),
    offset: int = Query(0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc())
    if search:
        query = query.where(
            User.name.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    if plan:
        query = query.where(User.plan == plan)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    users = result.scalars().all()

    if not users:
        return []

    user_ids = [u.id for u in users]
    today = date.today()
    now = datetime.now(timezone.utc)

    # 1. Total transactions & last transaction created_at
    txn_stats_res = await db.execute(
        select(
            Transaction.user_id,
            func.count(Transaction.id).label("txn_count"),
            func.max(Transaction.created_at).label("last_txn_at"),
        )
        .where(
            Transaction.user_id.in_(user_ids),
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),
        )
        .group_by(Transaction.user_id)
    )
    txn_stats = {
        row.user_id: {"txn_count": row.txn_count, "last_txn_at": row.last_txn_at}
        for row in txn_stats_res.all()
    }

    # 2. Total spent this month per user
    month_spent_res = await db.execute(
        select(
            Transaction.user_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("month_spent"),
        )
        .where(
            Transaction.user_id.in_(user_ids),
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),
            func.extract("year", Transaction.transaction_date) == today.year,
            func.extract("month", Transaction.transaction_date) == today.month,
        )
        .group_by(Transaction.user_id)
    )
    month_spent_map = {row.user_id: float(row.month_spent) for row in month_spent_res.all()}

    # 3. Active envelopes count per user (via household membership)
    env_count_res = await db.execute(
        select(
            HouseholdMember.user_id,
            func.count(Envelope.id).label("env_count"),
        )
        .join(Envelope, Envelope.household_id == HouseholdMember.household_id)
        .where(
            HouseholdMember.user_id.in_(user_ids),
            Envelope.is_active == True,
        )
        .group_by(HouseholdMember.user_id)
    )
    env_count_map = {row.user_id: row.env_count for row in env_count_res.all()}

    user_list = []
    for u in users:
        t_data = txn_stats.get(u.id, {"txn_count": 0, "last_txn_at": None})
        txn_count = t_data["txn_count"]
        last_txn_at = t_data["last_txn_at"]
        month_spent = month_spent_map.get(u.id, 0.0)
        env_count = env_count_map.get(u.id, 0)

        # Auth provider
        if u.google_id:
            auth_provider = "google"
        elif (not u.email or "@telegram" in (u.email or "")) and u.telegram_id:
            auth_provider = "telegram"
        else:
            auth_provider = "email"

        # Status calculation
        if (u.email and u.email.startswith("banned_")) or getattr(u, 'password_hash', None) == "BANNED":
            user_status = "banned"
        elif txn_count == 0:
            user_status = "no_txn"
        elif last_txn_at:
            dt = last_txn_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days_ago = (now - dt).days
            if days_ago <= 7:
                user_status = "active"
            elif days_ago <= 30:
                user_status = "idle"
            else:
                user_status = "dormant"
        else:
            user_status = "dormant"

        user_list.append({
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "plan": getattr(u, 'plan', 'basic') or 'basic',
            "telegram_id": u.telegram_id,
            "google_id": u.google_id,
            "is_admin": getattr(u, 'is_admin', False),
            "txn_count": txn_count,
            "envelopes_count": env_count,
            "month_spent": month_spent,
            "auth_provider": auth_provider,
            "status": user_status,
            "income_type": getattr(u, 'income_type', 'monthly') or 'monthly',
            "payday_day": getattr(u, 'payday_day', 1) or 1,
            "timezone": getattr(u, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta',
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "last_txn_at": last_txn_at.isoformat() if last_txn_at else None,
        })

    if status:
        user_list = [u for u in user_list if u["status"] == status]

    return user_list


@router.get("/users/{user_id}/detail")
async def get_user_detail(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    today = date.today()
    now = datetime.now(timezone.utc)

    # 1. Transactions stats
    txn_stat_res = await db.execute(
        select(
            func.count(Transaction.id).label("txn_count"),
            func.max(Transaction.created_at).label("last_txn_at"),
            func.coalesce(func.sum(Transaction.amount), 0).label("total_spent"),
        ).where(
            Transaction.user_id == u.id,
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),
        )
    )
    txn_row = txn_stat_res.one()
    txn_count = txn_row.txn_count or 0
    last_txn_at = txn_row.last_txn_at
    total_spent = float(txn_row.total_spent or 0)

    # 2. Month spent
    month_spent_res = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == u.id,
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),
            func.extract("year", Transaction.transaction_date) == today.year,
            func.extract("month", Transaction.transaction_date) == today.month,
        )
    )
    month_spent = float(month_spent_res.scalar() or 0)

    # 3. Household & Envelopes
    hm_res = await db.execute(
        select(HouseholdMember, Household)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == u.id)
    )
    hm_row = hm_res.first()
    household_data = None
    envelopes_data = []

    if hm_row:
        hm, hh = hm_row
        member_count = (await db.execute(
            select(func.count(HouseholdMember.id)).where(HouseholdMember.household_id == hh.id)
        )).scalar()

        role_str = hm.role.value if hasattr(hm.role, "value") else str(hm.role)
        household_data = {
            "id": str(hh.id),
            "name": hh.name,
            "role": role_str,
            "members_count": member_count or 1,
            "currency": hh.currency,
        }

        env_res = await db.execute(
            select(Envelope)
            .where(Envelope.household_id == hh.id, Envelope.is_active == True)
            .order_by(Envelope.name)
        )
        for env in env_res.scalars().all():
            envelopes_data.append({
                "id": str(env.id),
                "name": env.name,
                "emoji": env.emoji or "",
                "budget_amount": float(env.budget_amount or 0),
                "purpose": env.purpose.value if hasattr(env.purpose, "value") else str(env.purpose or "expense"),
                "classification": env.classification,
                "is_rollover": env.is_rollover,
                "is_personal": env.owner_id is not None,
            })

    # 4. Recent transactions (last 10)
    txns_res = await db.execute(
        select(Transaction, Envelope.name, Envelope.emoji)
        .outerjoin(Envelope, Envelope.id == Transaction.envelope_id)
        .where(Transaction.user_id == u.id, Transaction.is_deleted == False)
        .order_by(Transaction.created_at.desc())
        .limit(10)
    )
    recent_txns = []
    for txn, env_name, env_emoji in txns_res.all():
        source_val = txn.source.value if hasattr(txn.source, "value") else str(txn.source or "webapp")
        recent_txns.append({
            "id": str(txn.id),
            "amount": float(txn.amount),
            "description": txn.description or "",
            "transaction_date": str(txn.transaction_date),
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
            "envelope_name": env_name or "Tanpa Amplop",
            "envelope_emoji": env_emoji or "",
            "source": source_val,
            "is_balance_check": txn.balance_check_id is not None,
        })

    # Auth provider
    if u.google_id:
        auth_provider = "google"
    elif (not u.email or "@telegram" in (u.email or "")) and u.telegram_id:
        auth_provider = "telegram"
    else:
        auth_provider = "email"

    # Status
    if (u.email and u.email.startswith("banned_")) or getattr(u, 'password_hash', None) == "BANNED":
        user_status = "banned"
    elif txn_count == 0:
        user_status = "no_txn"
    elif last_txn_at:
        dt = last_txn_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_ago = (now - dt).days
        if days_ago <= 7:
            user_status = "active"
        elif days_ago <= 30:
            user_status = "idle"
        else:
            user_status = "dormant"
    else:
        user_status = "dormant"

    return {
        "user": {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "plan": getattr(u, 'plan', 'basic') or 'basic',
            "telegram_id": u.telegram_id,
            "google_id": u.google_id,
            "is_admin": getattr(u, 'is_admin', False),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "income_type": getattr(u, 'income_type', 'monthly') or 'monthly',
            "payday_day": getattr(u, 'payday_day', 1) or 1,
            "timezone": getattr(u, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta',
            "auth_provider": auth_provider,
            "status": user_status,
        },
        "stats": {
            "txn_count": txn_count,
            "envelopes_count": len(envelopes_data),
            "month_spent": month_spent,
            "total_spent": total_spent,
            "last_txn_at": last_txn_at.isoformat() if last_txn_at else None,
        },
        "household": household_data,
        "envelopes": envelopes_data,
        "recent_transactions": recent_txns,
    }


class UserAction(BaseModel):
    action: str  # upgrade, downgrade, ban, unban, make_admin, remove_admin


@router.post("/users/{user_id}/action")
async def user_action(
    user_id: UUID,
    req: UserAction,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    if req.action == "upgrade":
        target.plan = "pro"
    elif req.action == "downgrade":
        target.plan = "basic"
    elif req.action == "ban":
        target.password_hash = "BANNED"
        target.email = f"banned_{target.id}@jatahku.com"
    elif req.action == "make_admin":
        target.is_admin = True
    elif req.action == "remove_admin":
        target.is_admin = False
    else:
        raise HTTPException(400, "Invalid action")

    await db.commit()
    return {"status": "ok", "action": req.action, "user": target.name}


@router.post("/users/batch-upgrade")
async def batch_upgrade(
    count: int = Query(10),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Randomly upgrade N basic users to pro."""
    result = await db.execute(
        select(User).where(User.plan != 'pro').order_by(func.random()).limit(count)
    )
    users = result.scalars().all()
    upgraded = []
    for u in users:
        u.plan = 'pro'
        upgraded.append(u.name)
    await db.commit()
    return {"upgraded": upgraded, "count": len(upgraded)}


@router.post("/users/upgrade-all")
async def upgrade_all(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upgrade all users to pro (first 100 promo)."""
    await db.execute(update(User).where(User.plan != 'pro').values(plan='pro'))
    await db.commit()
    total = (await db.execute(select(func.count(User.id)).where(User.plan == 'pro'))).scalar()
    return {"status": "ok", "total_pro": total}


@router.post("/notify-all")
async def notify_all_users(
    title: str = Query(...),
    message: str = Query(...),
    send_telegram: bool = Query(False),
    telegram_text: str = Query(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send in-app notification to all users, optionally also via Telegram."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    count = 0
    tg_sent = 0
    tg_failed = 0

    bot = None
    if send_telegram:
        from telegram import Bot
        from app.core.config import get_settings
        bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)

    for u in users:
        notif = Notification(
            user_id=u.id, type=NotificationType.system,
            title=title, message=message,
        )
        db.add(notif)
        count += 1

        if send_telegram and bot and u.telegram_id:
            try:
                tg_msg = telegram_text or f"*{title}*\n\n{message}"
                await bot.send_message(chat_id=int(u.telegram_id), text=tg_msg, parse_mode="Markdown")
                tg_sent += 1
            except Exception:
                tg_failed += 1

    await db.commit()
    return {"sent": count, "tg_sent": tg_sent, "tg_failed": tg_failed}


class DirectEmailRequest(BaseModel):
    user_id: UUID
    subject: str
    body: str
    cta_text: str | None = None
    cta_url: str | None = None
    send_telegram: bool = False
    telegram_text: str | None = None


class BroadcastRequest(BaseModel):
    subject: str
    body: str
    cta_text: str | None = None
    cta_url: str | None = None


@router.post("/send-email-user")
async def send_email_to_user(
    req: DirectEmailRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a tailored email and/or Telegram message to a specific user."""
    result = await db.execute(select(User).where(User.id == req.user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User tidak ditemukan")

    results = {}

    # Send email
    if u.email and not u.email.startswith("deleted_") and not u.email.startswith("banned_"):
        from app.services.email_service import send_email, email_template
        html = email_template(
            req.subject,
            f"<p>Hai {u.name},</p>" + req.body,
            req.cta_text or None,
            req.cta_url or None,
        )
        results["email"] = "sent" if send_email(u.email, req.subject, html) else "failed"
    else:
        results["email"] = "skipped"

    # Send Telegram
    if req.send_telegram:
        if u.telegram_id:
            try:
                from telegram import Bot
                from app.core.config import get_settings
                bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)
                tg_msg = req.telegram_text or f"*{req.subject}*"
                await bot.send_message(chat_id=int(u.telegram_id), text=tg_msg, parse_mode="Markdown")
                results["telegram"] = "sent"
            except Exception as e:
                results["telegram"] = f"failed: {e}"
        else:
            results["telegram"] = "skipped (tidak ada TG)"

    return {"status": "ok", "to": u.email, "name": u.name, "results": results}


@router.post("/send-tg-reminders")
async def send_tg_reminders(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send email to all users without Telegram linked."""
    from app.services.email_service import send_tg_reminder_email
    result = await db.execute(
        select(User).where(User.telegram_id == None, User.email != None)
    )
    users = result.scalars().all()
    sent = 0
    for u in users:
        if u.email and not u.email.startswith("deleted_") and not u.email.startswith("banned_"):
            if send_tg_reminder_email(u.email, u.name):
                sent += 1
    return {"sent": sent, "total_unlinked": len(users)}


from app.models.models import PaymentOrder, PromoCode, AppSetting


class BankAccountUpdate(BaseModel):
    accounts: list


@router.get("/settings/{key}")
async def get_app_setting(
    key: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Setting not found")
    import json
    try:
        return {"key": s.key, "value": json.loads(s.value)}
    except:
        return {"key": s.key, "value": s.value}


@router.put("/settings/{key}")
async def update_app_setting(
    key: str,
    value: str = Query(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    if s:
        s.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()
    return {"status": "updated"}


@router.get("/payment-orders")
async def list_payment_orders(
    status: str = Query(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    if status:
        query = query.where(PaymentOrder.status == status)
    r = await db.execute(query.limit(50))
    orders = r.scalars().all()
    result = []
    for o in orders:
        u = (await db.execute(select(User).where(User.id == o.user_id))).scalar_one_or_none()
        result.append({
            "id": str(o.id), "user_name": u.name if u else "-",
            "user_email": u.email if u else "-",
            "amount": float(o.amount), "original_amount": float(o.original_amount),
            "discount_pct": o.discount_pct, "promo_code": o.promo_code,
            "status": o.status, "proof_url": o.proof_url,
            "payment_method": o.payment_method,
            "created_at": o.created_at.isoformat(),
        })
    return result


@router.post("/payment-orders/{order_id}/approve")
async def approve_payment(
    order_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PaymentOrder).where(PaymentOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")

    order.status = "completed"
    # Upgrade user
    u = (await db.execute(select(User).where(User.id == order.user_id))).scalar_one_or_none()
    if u:
        u.plan = "pro"
        notif = Notification(
            user_id=u.id, type=NotificationType.system,
            title="Selamat! Upgrade ke Pro berhasil!",
            message="Semua fitur unlimited sudah aktif. Terima kasih!",
            link="/settings",
        )
        db.add(notif)
        # Send email
        try:
            from app.services.email_service import send_email, email_template
            html = email_template(
                "Upgrade Pro Berhasil!",
                "<p>Hai " + u.name + ",</p><p>Pembayaran kamu sudah dikonfirmasi. Semua fitur Pro sudah aktif!</p>",
                "Buka Jatahku", "https://jatahku.com"
            )
            send_email(u.email, "Upgrade Pro Berhasil!", html)
        except:
            pass
    await db.commit()
    return {"status": "approved", "user": u.name if u else "-"}


@router.post("/payment-orders/{order_id}/reject")
async def reject_payment(
    order_id: UUID,
    reason: str = Query("Bukti transfer tidak valid"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PaymentOrder).where(PaymentOrder.id == order_id))
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    order.status = "rejected"
    order.admin_notes = reason
    u = (await db.execute(select(User).where(User.id == order.user_id))).scalar_one_or_none()
    if u:
        notif = Notification(
            user_id=u.id, type=NotificationType.system,
            title="Pembayaran ditolak",
            message=reason,
            link="/settings",
        )
        db.add(notif)
    await db.commit()
    return {"status": "rejected"}


class PromoCreate(BaseModel):
    code: str
    discount_pct: int = 0
    is_free: bool = False
    max_uses: int | None = None
    event_name: str | None = None
    valid_days: int | None = None


class PromoUpdate(BaseModel):
    code: str | None = None
    discount_pct: int | None = None
    is_free: bool | None = None
    max_uses: int | None = None
    event_name: str | None = None
    valid_days: int | None = None
    is_active: bool | None = None


@router.post("/promo-codes")
async def create_promo(
    req: PromoCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        promo = PromoCode(
            code=req.code.upper(),
            discount_pct=req.discount_pct,
            is_free=req.is_free,
            max_uses=req.max_uses,
            event_name=req.event_name,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(days=req.valid_days) if req.valid_days else None,
        )
        db.add(promo)
        await db.commit()
        return {"status": "created", "code": promo.code}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/promo-codes")
async def list_promos(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    promos = r.scalars().all()
    return [{
        "id": str(p.id), "code": p.code,
        "discount_pct": p.discount_pct, "is_free": p.is_free,
        "max_uses": p.max_uses, "used_count": p.used_count,
        "event_name": p.event_name, "is_active": p.is_active,
        "valid_until": p.valid_until.isoformat() if p.valid_until else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in promos]


@router.patch("/promo-codes/{promo_id}")
async def update_promo(
    promo_id: UUID,
    req: PromoUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = r.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    if req.code is not None:
        new_code = req.code.strip().upper()
        if not new_code:
            raise HTTPException(status_code=400, detail="Kode promo tidak boleh kosong")
        if new_code != promo.code:
            dup_r = await db.execute(
                select(PromoCode).where(PromoCode.code == new_code, PromoCode.id != promo_id)
            )
            if dup_r.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Kode promo sudah digunakan")
            promo.code = new_code

    if req.is_free is not None:
        promo.is_free = req.is_free
        if req.is_free:
            promo.discount_pct = 100
        elif req.discount_pct is not None:
            promo.discount_pct = req.discount_pct
    elif req.discount_pct is not None:
        promo.discount_pct = req.discount_pct

    if req.max_uses is not None:
        promo.max_uses = req.max_uses if req.max_uses > 0 else None

    if req.event_name is not None:
        promo.event_name = req.event_name.strip() if req.event_name.strip() else None

    if req.valid_days is not None:
        if req.valid_days > 0:
            promo.valid_until = datetime.utcnow() + timedelta(days=req.valid_days)
        else:
            promo.valid_until = None

    if req.is_active is not None:
        promo.is_active = req.is_active

    await db.commit()
    return {
        "id": str(promo.id),
        "code": promo.code,
        "discount_pct": promo.discount_pct,
        "is_free": promo.is_free,
        "max_uses": promo.max_uses,
        "used_count": promo.used_count,
        "event_name": promo.event_name,
        "is_active": promo.is_active,
        "valid_until": promo.valid_until.isoformat() if promo.valid_until else None,
        "created_at": promo.created_at.isoformat() if promo.created_at else None,
    }


@router.post("/promo-codes/{promo_id}/toggle-active")
async def toggle_promo_active(
    promo_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = r.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    promo.is_active = not promo.is_active
    await db.commit()
    return {"status": "updated", "is_active": promo.is_active}


@router.delete("/promo-codes/{promo_id}")
async def delete_promo(
    promo_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = r.scalar_one_or_none()
    if promo:
        promo.is_active = False
        await db.commit()
    return {"status": "deleted"}


@router.post("/broadcast-article")
async def broadcast_article(
    req: BroadcastRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Broadcast an email to ALL users with email addresses."""
    result = await db.execute(
        select(User).where(
            User.email != None,
            ~User.email.startswith("deleted_"),
            ~User.email.startswith("banned_"),
        )
    )
    users = result.scalars().all()

    sent = 0
    failed = 0
    from app.services.email_service import send_email, email_template

    for u in users:
        if u.email and not u.email.startswith("deleted_") and not u.email.startswith("banned_"):
            try:
                html = email_template(
                    req.subject,
                    f"<p>Hai {u.name},</p>" + req.body,
                    req.cta_text or None,
                    req.cta_url or None,
                )
                if send_email(u.email, req.subject, html):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    return {"status": "ok", "sent": sent, "failed": failed, "total": len(users)}
