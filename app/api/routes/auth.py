from decimal import Decimal
from uuid import UUID
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import get_settings

limiter = Limiter(key_func=get_remote_address)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.deps import get_current_user
from app.models.models import User, Household, HouseholdMember, HouseholdRole, Envelope

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    promo_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str | None
    name: str
    telegram_id: str | None
    is_admin: bool = False

    model_config = {"from_attributes": True}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    import re as re_mod
    if not req.email or not re_mod.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", req.email):
        raise HTTPException(status_code=400, detail="Email tidak valid")
    if not req.password or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
    if not req.name or len(req.name.strip()) < 1 or len(req.name) > 100:
        raise HTTPException(status_code=400, detail="Nama tidak valid")
    req.name = req.name.strip()[:100]
    req.email = req.email.strip().lower()[:255]
    # Check if email exists
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user = User(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password),
    )
    db.add(user)
    await db.flush()

    # Create default household
    household = Household(name=f"Rumah {req.name}")
    db.add(household)
    await db.flush()

    # Add user as owner
    membership = HouseholdMember(
        user_id=user.id,
        household_id=household.id,
        role=HouseholdRole.owner,
    )
    db.add(membership)
    await db.flush()

    # Apply promo code if provided
    if req.promo_code:
        from app.models.models import PromoCode
        from datetime import datetime as dt
        promo_result = await db.execute(
            select(PromoCode).where(
                PromoCode.code == req.promo_code.upper(),
                PromoCode.is_active == True,
            )
        )
        promo = promo_result.scalar_one_or_none()
        if promo:
            now = dt.utcnow()
            valid = True
            if promo.valid_from and now < promo.valid_from:
                valid = False
            if promo.valid_until and now > promo.valid_until:
                valid = False
            if promo.max_uses and promo.used_count >= promo.max_uses:
                valid = False
            if valid and promo.is_free:
                user.plan = "pro"
                promo.used_count += 1

    await db.commit()

    # Notify admin on Telegram (fire-and-forget)
    try:
        from telegram import Bot
        from app.core.config import get_settings as _gs
        _s = _gs()
        if _s.TELEGRAM_BOT_TOKEN and _s.ADMIN_TELEGRAM_ID:
            _bot = Bot(token=_s.TELEGRAM_BOT_TOKEN)
            _plan = "Pro 🎉" if user.plan == "pro" else "Basic"
            _promo = f" · promo `{req.promo_code.upper()}`" if req.promo_code and user.plan == "pro" else ""
            await _bot.send_message(
                chat_id=int(_s.ADMIN_TELEGRAM_ID),
                text=f"👤 *User baru!*\n\nNama: {user.name}\nEmail: `{user.email}`\nPlan: {_plan}{_promo}",
                parse_mode="Markdown",
            )
    except Exception:
        pass  # Jangan block register jika notif gagal

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.get("/tg-login", response_model=TokenResponse)
async def tg_login(token: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL)
    user_id_bytes = await r.get(f"tglogin:{token}")
    if user_id_bytes:
        await r.delete(f"tglogin:{token}")
    await r.close()

    if not user_id_bytes:
        raise HTTPException(status_code=400, detail="Link tidak valid atau sudah kadaluarsa")

    result = await db.execute(select(User).where(User.id == UUID(user_id_bytes.decode())))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )
