import secrets
import redis.asyncio as aioredis
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User

settings = get_settings()
LOGIN_LINK_TTL = 300


async def create_login_url(user_id) -> str:
    """Link login sekali pakai ke webapp — dipakai /webapp dan ajakan setup."""
    token = secrets.token_urlsafe(32)
    r = aioredis.from_url(settings.REDIS_URL)
    await r.set(f"tglogin:{token}", str(user_id), ex=LOGIN_LINK_TTL)
    await r.close()
    return f"{settings.APP_URL}/auth/tg?token={token}"


async def reply_setup_needed(update, user):
    """Balasan untuk akun yang belum punya amplop: satu ketukan ke onboarding web
    (sudah login, tanpa daftar), lalu kembali mencatat di chat."""
    url = await create_login_url(user.id)
    await update.effective_message.reply_text(
        "👋 Budget kamu belum disiapkan.\n\n"
        "Atur dulu di web, sekali ketuk dan tanpa daftar (sekitar 2 menit):\n"
        f"{url}\n\n"
        "Setelah itu kembali ke sini dan catat pengeluaran, misalnya: kopi 35k\n\n"
        "Link berlaku 5 menit. Ketik /start untuk link baru."
    )


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

    login_url = await create_login_url(user.id)

    await update.message.reply_text(
        f"🔐 <b>Login ke Jatahku Webapp</b>\n\n"
        f"Klik link berikut untuk masuk:\n{login_url}\n\n"
        f"⏱ Link berlaku <b>5 menit</b> dan hanya bisa digunakan sekali.",
        parse_mode="HTML"
    )
