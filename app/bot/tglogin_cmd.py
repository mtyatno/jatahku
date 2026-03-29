import secrets
import redis.asyncio as aioredis
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User

settings = get_settings()


async def cmd_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate one-time login link for the webapp."""
    telegram_id = str(update.effective_user.id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

    if not user:
        await update.message.reply_text(
            "Akun Telegram kamu belum terhubung ke Jatahku.\n\n"
            "Daftar dulu di jatahku.com lalu hubungkan akun di menu Settings."
        )
        return

    token = secrets.token_urlsafe(32)

    r = aioredis.from_url(settings.REDIS_URL)
    await r.set(f"tglogin:{token}", str(user.id), ex=300)
    await r.close()

    login_url = f"{settings.APP_URL}/auth/tg?token={token}"

    await update.message.reply_text(
        f"🔐 <b>Login ke Jatahku Webapp</b>\n\n"
        f"Klik link berikut untuk masuk:\n{login_url}\n\n"
        f"⏱ Link berlaku <b>5 menit</b> dan hanya bisa digunakan sekali.",
        parse_mode="HTML"
    )
