from uuid import UUID
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Envelope, Transaction, Allocation, Income,
    HouseholdMember, Household, RecurringTransaction,
    Notification, NotificationType,
)

router = APIRouter()


async def require_admin(user: User = Depends(get_current_user)):
    if not getattr(user, 'is_admin', False):
        raise HTTPException(403, "Admin access required")
    return user


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
        select(func.count(Transaction.id)).where(Transaction.is_deleted == False)
    )).scalar()

    # Today transactions
    today_txns = (await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.is_deleted == False,
            Transaction.transaction_date == today,
        )
    )).scalar()

    # Total spending today
    today_spent = (await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.is_deleted == False,
            Transaction.transaction_date == today,
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
            )
        )).scalar()
        amount = (await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.is_deleted == False,
                Transaction.transaction_date == d,
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
    limit: int = Query(50),
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

    user_list = []
    for u in users:
        txn_count = (await db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == u.id, Transaction.is_deleted == False
            )
        )).scalar()
        user_list.append({
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "plan": getattr(u, 'plan', 'basic') or 'basic',
            "telegram_id": u.telegram_id,
            "is_admin": getattr(u, 'is_admin', False),
            "txn_count": txn_count,
            "created_at": u.created_at.isoformat(),
        })
    return user_list


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
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send notification to all users."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    count = 0
    for u in users:
        notif = Notification(
            user_id=u.id, type=NotificationType.system,
            title=title, message=message,
        )
        db.add(notif)
        count += 1
    await db.commit()
    return {"sent": count}


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


@router.post("/promo-codes")
async def create_promo(
    req: PromoCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    promo = PromoCode(
        code=req.code.upper(),
        discount_pct=req.discount_pct,
        is_free=req.is_free,
        max_uses=req.max_uses,
        event_name=req.event_name,
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=req.valid_days) if req.valid_days else None,
    )
    db.add(promo)
    await db.commit()
    return {"status": "created", "code": promo.code}


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
    } for p in promos]


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
