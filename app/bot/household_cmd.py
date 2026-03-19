import httpx
from telegram import Update
from telegram.ext import ContextTypes
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User, HouseholdMember, Household, HouseholdRole
from sqlalchemy import select, func
from app.bot.handlers import get_or_create_user, get_household_id, format_currency

settings = get_settings()

async def cmd_invite(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        membership = await db.execute(
            select(HouseholdMember).where(HouseholdMember.user_id == user.id)
        )
        member = membership.scalar_one_or_none()
        if not member:
            await update.message.reply_text("Ketik /start dulu.")
            return
        if member.role not in (HouseholdRole.owner, HouseholdRole.admin):
            await update.message.reply_text("Hanya owner/admin yang bisa invite.")
            return
        household = await db.execute(select(Household).where(Household.id == member.household_id))
        h = household.scalar_one()

    import secrets, redis.asyncio as aioredis
    code = secrets.token_urlsafe(6)[:8].upper()
    r = aioredis.from_url(settings.REDIS_URL)
    await r.set(f"invite:{code}", str(h.id), ex=86400)
    await r.close()

    await update.message.reply_text(
        f"🏠 Invite ke *{h.name}*\n\n"
        f"Kode: *{code}*\n\n"
        f"Share ke pasangan/keluarga. Mereka kirim:\n"
        f"`/join {code}`\n\n"
        f"Berlaku 24 jam.",
        parse_mode="Markdown",
    )

async def cmd_join(update, context):
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Format: /join KODE\n\nContoh: /join ABC12DEF")
        return

    code = context.args[0].strip().upper()
    tg_user = update.effective_user

    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL)
    household_id = await r.get(f"invite:{code}")
    await r.close()

    if not household_id:
        await update.message.reply_text("❌ Kode invite tidak valid atau sudah expired.")
        return

    household_id = household_id.decode()

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)

        from uuid import UUID
        existing = await db.execute(
            select(HouseholdMember).where(
                HouseholdMember.user_id == user.id,
                HouseholdMember.household_id == UUID(household_id),
            )
        )
        if existing.scalar_one_or_none():
            await update.message.reply_text("Kamu sudah bergabung di household ini.")
            return

        old = await db.execute(
            select(HouseholdMember).where(HouseholdMember.user_id == user.id)
        )
        old_member = old.scalar_one_or_none()
        if old_member:
            await db.delete(old_member)

        db.add(HouseholdMember(
            user_id=user.id,
            household_id=UUID(household_id),
            role=HouseholdRole.member,
        ))
        await db.commit()

        h = await db.execute(select(Household).where(Household.id == UUID(household_id)))
        household = h.scalar_one()

        count = await db.execute(
            select(func.count(HouseholdMember.id)).where(
                HouseholdMember.household_id == UUID(household_id)
            )
        )
        member_count = count.scalar()

    r = aioredis.from_url(settings.REDIS_URL)
    await r.delete(f"invite:{code}")
    await r.close()

    await update.message.reply_text(
        f"✅ Bergabung ke *{household.name}*!\n\n"
        f"Sekarang ada {member_count} anggota.\n"
        f"Semua amplop dan transaksi sekarang shared.\n\n"
        f"Ketik /status untuk lihat budget bersama.",
        parse_mode="Markdown",
    )
