import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.security import hash_password, create_access_token, create_refresh_token
from app.models.models import User
from app.services.merge import get_merge_preview, merge_users

settings = get_settings()
router = APIRouter()
LINK_TTL = 300


def _gen_code():
    return str(secrets.randbelow(900000) + 100000)


async def _redis():
    return aioredis.from_url(settings.REDIS_URL)


# ── Flow A: WebApp user generates code, sends to Telegram bot ──

class LinkGenerateResponse(BaseModel):
    code: str
    expires_in: int = LINK_TTL


@router.post("/link/generate", response_model=LinkGenerateResponse)
async def generate_link_code(user: User = Depends(get_current_user)):
    code = _gen_code()
    r = await _redis()
    await r.set(f"link:webapp:{code}", str(user.id), ex=LINK_TTL)
    await r.close()
    return LinkGenerateResponse(code=code)


class LinkTelegramRequest(BaseModel):
    code: str
    telegram_id: str


class LinkResult(BaseModel):
    status: str  # "linked", "conflict"
    user_name: str | None = None
    conflict: dict | None = None


@router.post("/link/telegram", response_model=LinkResult)
async def link_telegram_account(
    req: LinkTelegramRequest,
    db: AsyncSession = Depends(get_db),
):
    r = await _redis()
    user_id = await r.get(f"link:webapp:{req.code}")
    await r.close()

    if not user_id:
        raise HTTPException(status_code=400, detail="Kode tidak valid atau sudah expired")
    user_id = user_id.decode()

    # Check if telegram_id already belongs to another user
    existing = await db.execute(
        select(User).where(User.telegram_id == req.telegram_id)
    )
    existing_user = existing.scalar_one_or_none()

    if existing_user and str(existing_user.id) != user_id:
        # Conflict! TG already has an account
        preview = await get_merge_preview(existing_user.id, UUID(user_id), db)

        # Store merge intent in Redis
        r = await _redis()
        import json
        await r.set(
            f"merge:{req.code}",
            json.dumps({
                "source_id": str(existing_user.id),
                "target_id": user_id,
                "telegram_id": req.telegram_id,
            }),
            ex=LINK_TTL,
        )
        await r.close()

        return LinkResult(
            status="conflict",
            conflict=preview,
        )

    # No conflict — just link
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    user.telegram_id = req.telegram_id
    await db.commit()

    r = await _redis()
    await r.delete(f"link:webapp:{req.code}")
    await r.close()

    return LinkResult(status="linked", user_name=user.name)


class MergeRequest(BaseModel):
    code: str
    keep_household_id: str


@router.post("/link/merge")
async def execute_merge(
    req: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    r = await _redis()
    merge_data = await r.get(f"merge:{req.code}")
    await r.close()

    if not merge_data:
        raise HTTPException(status_code=400, detail="Merge session expired. Generate link code lagi.")

    import json
    data = json.loads(merge_data.decode())
    source_id = UUID(data["source_id"])
    target_id = UUID(data["target_id"])

    result = await merge_users(
        source_user_id=source_id,
        target_user_id=target_id,
        keep_household_id=UUID(req.keep_household_id),
        db=db,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Clean up Redis
    r = await _redis()
    await r.delete(f"merge:{req.code}")
    await r.delete(f"link:webapp:{req.code}")
    await r.close()

    return result


# ── Flow B: Telegram user generates code, links on WebApp ──

class LinkFromTelegramRequest(BaseModel):
    telegram_id: str


@router.post("/link/generate-for-telegram", response_model=LinkGenerateResponse)
async def generate_code_for_telegram(req: LinkFromTelegramRequest):
    code = _gen_code()
    r = await _redis()
    await r.set(f"link:telegram:{code}", req.telegram_id, ex=LINK_TTL)
    await r.close()
    return LinkGenerateResponse(code=code)


class ClaimTelegramRequest(BaseModel):
    code: str
    email: EmailStr
    password: str
    name: str | None = None


class ClaimTelegramResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/link/claim-telegram", response_model=ClaimTelegramResponse)
async def claim_telegram_account(
    req: ClaimTelegramRequest,
    db: AsyncSession = Depends(get_db),
):
    r = await _redis()
    telegram_id = await r.get(f"link:telegram:{req.code}")
    await r.close()

    if not telegram_id:
        raise HTTPException(status_code=400, detail="Kode tidak valid atau sudah expired")
    telegram_id = telegram_id.decode()

    existing_email = await db.execute(select(User).where(User.email == req.email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Akun Telegram tidak ditemukan")

    user.email = req.email
    user.password_hash = hash_password(req.password)
    if req.name:
        user.name = req.name
    await db.commit()

    r = await _redis()
    await r.delete(f"link:telegram:{req.code}")
    await r.close()

    return ClaimTelegramResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


# ── Unlink ──

@router.post("/link/unlink")
async def unlink_telegram(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.telegram_id:
        raise HTTPException(status_code=400, detail="Akun Telegram belum terhubung")

    user.telegram_id = None
    await db.commit()
    return {"status": "unlinked"}


@router.post("/link/unlink-bot")
async def unlink_from_bot(
    telegram_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")

    user.telegram_id = None
    await db.commit()
    return {"status": "unlinked", "user_name": user.name}
