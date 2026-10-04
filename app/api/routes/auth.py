from decimal import Decimal
from uuid import UUID
import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
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
from app.services.password_reset import create_reset_token, redeem_reset_token
from app.services.email_service import send_password_reset_email, send_password_changed_email
from app.services.google_auth import verify_google_credential

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class GoogleCredentialRequest(BaseModel):
    credential: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


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


async def _create_user(db: AsyncSession, *, email: str, name: str, password_hash: str | None, google_id: str | None = None) -> User:
    """User baru + household default dengan dia sebagai owner (belum di-commit)."""
    user = User(email=email, name=name, password_hash=password_hash, google_id=google_id)
    db.add(user)
    await db.flush()

    household = Household(name=f"Rumah {name}")
    db.add(household)
    await db.flush()

    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role=HouseholdRole.owner))
    await db.flush()
    return user


async def _notify_admin_new_user(user: User, via: str) -> None:
    try:
        from telegram import Bot
        settings = get_settings()
        if settings.TELEGRAM_BOT_TOKEN and settings.ADMIN_TELEGRAM_ID:
            plan = "Pro 🎉" if user.plan == "pro" else "Basic"
            await Bot(token=settings.TELEGRAM_BOT_TOKEN).send_message(
                chat_id=int(settings.ADMIN_TELEGRAM_ID),
                text=f"👤 *User baru!*\n\nNama: {user.name}\nEmail: `{user.email}`\nPlan: {plan}\nVia: {via}",
                parse_mode="Markdown",
            )
    except Exception:
        pass  # Jangan block register jika notif gagal


def _tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


async def _google_claims(credential: str) -> dict:
    client_id = get_settings().GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(status_code=503, detail="Masuk dengan Google belum diaktifkan")
    claims = await verify_google_credential(credential, client_id)
    if not claims:
        raise HTTPException(status_code=401, detail="Verifikasi Google gagal, coba lagi")
    return claims


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

    user = await _create_user(db, email=req.email, name=req.name, password_hash=hash_password(req.password))
    await db.commit()
    await _notify_admin_new_user(user, via="email")

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


GENERIC_FORGOT_MESSAGE = "Kalau email terdaftar, link reset sudah dikirim."


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = req.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        settings = get_settings()
        r = aioredis.from_url(settings.REDIS_URL)
        try:
            token = await create_reset_token(r, str(user.id))
        finally:
            await r.close()
        reset_url = f"https://jatahku.com/reset-password?token={token}"
        # Kirim di background: respons tidak menunggu SMTP dan tidak
        # membocorkan (lewat timing) apakah email terdaftar.
        background_tasks.add_task(send_password_reset_email, user.email, user.name, reset_url)

    return {"message": GENERIC_FORGOT_MESSAGE}


@router.post("/reset-password", response_model=TokenResponse)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    req: ResetPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not req.new_password or len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter")

    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        user_id = await redeem_reset_token(r, req.token)
    finally:
        await r.close()

    if not user_id:
        raise HTTPException(status_code=400, detail="Link tidak valid atau sudah kadaluarsa")

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Link tidak valid atau sudah kadaluarsa")
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Link tidak valid atau sudah kadaluarsa")

    user.password_hash = hash_password(req.new_password)
    await db.commit()

    if user.email:
        background_tasks.add_task(send_password_changed_email, user.email, user.name)

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


@router.get("/google/config")
async def google_config():
    return {"client_id": get_settings().GOOGLE_CLIENT_ID or None}


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_login(request: Request, req: GoogleCredentialRequest, db: AsyncSession = Depends(get_db)):
    """Masuk atau daftar dengan Google. Email yang sudah terdaftar otomatis disambungkan."""
    claims = await _google_claims(req.credential)

    user = (await db.execute(select(User).where(User.google_id == claims["sub"]))).scalar_one_or_none()
    if user:
        return _tokens(user)

    user = (await db.execute(select(User).where(User.email == claims["email"]))).scalar_one_or_none()
    if user:
        user.google_id = claims["sub"]
        await db.commit()
        return _tokens(user)

    user = await _create_user(db, email=claims["email"], name=claims["name"], password_hash=None, google_id=claims["sub"])
    await db.commit()
    await _notify_admin_new_user(user, via="Google")
    return _tokens(user)


@router.post("/google/link")
@limiter.limit("10/minute")
async def google_link(
    request: Request,
    req: GoogleCredentialRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    claims = await _google_claims(req.credential)

    owner = (await db.execute(select(User).where(User.google_id == claims["sub"]))).scalar_one_or_none()
    if owner and owner.id != user.id:
        raise HTTPException(status_code=400, detail="Akun Google ini sudah tersambung ke akun Jatahku lain")

    if not user.email:
        taken = (await db.execute(select(User).where(User.email == claims["email"]))).scalar_one_or_none()
        if not taken:
            user.email = claims["email"]

    user.google_id = claims["sub"]
    await db.commit()
    return {"status": "linked", "email": user.email}


@router.post("/google/unlink")
async def google_unlink(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.google_id:
        raise HTTPException(status_code=400, detail="Akun Google belum tersambung")
    if not user.password_hash and not user.telegram_id:
        raise HTTPException(status_code=400, detail="Buat password dulu supaya tetap bisa masuk setelah Google diputus")
    user.google_id = None
    await db.commit()
    return {"status": "unlinked"}


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
