import json
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, PaymentOrder, PromoCode, AppSetting, Notification, NotificationType

router = APIRouter()


async def get_setting(key: str, db: AsyncSession) -> str | None:
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    return s.value if s else None


class CreateOrder(BaseModel):
    promo_code: str | None = None


@router.get("/bank-accounts")
async def get_bank_accounts(db: AsyncSession = Depends(get_db)):
    val = await get_setting("bank_accounts", db)
    return json.loads(val) if val else []


@router.get("/price")
async def get_price(
    promo_code: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    price_str = await get_setting("pro_price", db)
    price = int(price_str) if price_str else 79000
    discount = 0
    promo_valid = False

    if promo_code:
        r = await db.execute(
            select(PromoCode).where(
                PromoCode.code == promo_code.upper(),
                PromoCode.is_active == True,
            )
        )
        promo = r.scalar_one_or_none()
        if promo:
            now = datetime.now(timezone.utc)
            if promo.valid_from and now < promo.valid_from:
                pass
            elif promo.valid_until and now > promo.valid_until:
                pass
            elif promo.max_uses and promo.used_count >= promo.max_uses:
                pass
            else:
                promo_valid = True
                if promo.is_free:
                    discount = 100
                else:
                    discount = promo.discount_pct

    final_price = max(0, price - (price * discount // 100))
    return {
        "original_price": price,
        "discount_pct": discount,
        "final_price": final_price,
        "promo_valid": promo_valid,
        "promo_code": promo_code,
    }


@router.post("/create-order")
async def create_order(
    req: CreateOrder,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if getattr(user, 'plan', 'basic') == 'pro':
        raise HTTPException(400, "Kamu sudah Pro!")

    price_str = await get_setting("pro_price", db)
    price = int(price_str) if price_str else 79000
    discount = 0

    if req.promo_code:
        r = await db.execute(
            select(PromoCode).where(
                PromoCode.code == req.promo_code.upper(),
                PromoCode.is_active == True,
            )
        )
        promo = r.scalar_one_or_none()
        if promo:
            now = datetime.now(timezone.utc)
            valid = True
            if promo.valid_from and now < promo.valid_from:
                valid = False
            if promo.valid_until and now > promo.valid_until:
                valid = False
            if promo.max_uses and promo.used_count >= promo.max_uses:
                valid = False
            if valid:
                discount = 100 if promo.is_free else promo.discount_pct
                promo.used_count += 1

    final_price = max(0, price - (price * discount // 100))

    # If free (100% discount), auto-upgrade
    if final_price == 0:
        user.plan = 'pro'
        order = PaymentOrder(
            user_id=user.id, amount=0, original_amount=price,
            promo_code=req.promo_code, discount_pct=discount,
            status='completed', payment_method='promo',
        )
        db.add(order)
        notif = Notification(
            user_id=user.id, type=NotificationType.system,
            title="Selamat! Kamu sekarang Pro!",
            message="Semua fitur unlimited sudah aktif.",
            link="/settings",
        )
        db.add(notif)
        await db.commit()
        return {"status": "completed", "order_id": str(order.id), "plan": "pro"}

    order = PaymentOrder(
        user_id=user.id, amount=final_price, original_amount=price,
        promo_code=req.promo_code, discount_pct=discount,
        status='pending',
    )
    db.add(order)
    await db.commit()

    banks = await get_setting("bank_accounts", db)
    return {
        "status": "pending",
        "order_id": str(order.id),
        "amount": final_price,
        "bank_accounts": json.loads(banks) if banks else [],
    }


@router.post("/upload-proof/{order_id}")
async def upload_proof(
    order_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(PaymentOrder).where(
            PaymentOrder.id == order_id, PaymentOrder.user_id == user.id
        )
    )
    order = r.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order tidak ditemukan")
    if order.status != 'pending':
        raise HTTPException(400, "Order sudah diproses")

    import os
    data = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    fname = f"proof_{order_id}.{ext}"
    upload_dir = "/home/jatahku/web/jatahku.com/public_html/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    with open(f"{upload_dir}/{fname}", "wb") as f:
        f.write(data)

    order.proof_url = f"/uploads/{fname}"
    order.status = "waiting_confirmation"

    # Notify all admins
    from app.models.models import Notification, NotificationType
    admin_result = await db.execute(select(User).where(User.is_admin == True))
    admins = admin_result.scalars().all()
    for admin in admins:
        notif = Notification(
            user_id=admin.id, type=NotificationType.system,
            title=f"💳 Bukti pembayaran baru!",
            message=f"{user.name} ({user.email}) upload bukti transfer Rp{int(order.amount):,}".replace(",", "."),
            link="/admin",
        )
        db.add(notif)
        # Email admin
        try:
            from app.services.email_service import send_email, email_template
            html = email_template(
                "Bukti Pembayaran Baru",
                f"<p><strong>{user.name}</strong> ({user.email}) baru saja upload bukti transfer.</p>"
                f"<p>Jumlah: <strong>Rp{int(order.amount):,}</strong></p>"
                f"<p>Segera verifikasi di Admin panel.</p>".replace(",", "."),
                "Buka Admin", "https://jatahku.com/admin"
            )
            send_email(admin.email, f"💳 Pembayaran baru: {user.name}", html)
        except:
            pass

    await db.commit()

    return {"status": "waiting_confirmation", "message": "Bukti transfer diterima. Admin akan memverifikasi."}


@router.get("/my-orders")
async def my_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(PaymentOrder).where(PaymentOrder.user_id == user.id)
        .order_by(PaymentOrder.created_at.desc())
    )
    orders = r.scalars().all()
    return [{
        "id": str(o.id),
        "amount": float(o.amount),
        "original_amount": float(o.original_amount),
        "discount_pct": o.discount_pct,
        "promo_code": o.promo_code,
        "status": o.status,
        "payment_method": o.payment_method,
        "created_at": o.created_at.isoformat(),
    } for o in orders]
