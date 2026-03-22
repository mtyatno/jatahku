import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    User, Notification, NotificationType, NotificationPreference
)

settings = get_settings()
logger = logging.getLogger("jatahku.notify")


async def get_or_create_prefs(user_id: UUID, db: AsyncSession) -> NotificationPreference:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        prefs = NotificationPreference(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


async def send_notification(
    user_id: UUID,
    notif_type: NotificationType,
    title: str,
    message: str,
    link: str = None,
    telegram_text: str = None,
    db: AsyncSession = None,
):
    """Send notification via WebApp + Telegram based on user preferences."""
    should_close = False
    if db is None:
        db = AsyncSessionLocal()
        should_close = True

    try:
        prefs = await get_or_create_prefs(user_id, db)
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        # Check preference keys
        type_key = notif_type.value
        send_tg = getattr(prefs, f"{type_key}_tg", True)
        send_web = getattr(prefs, f"{type_key}_web", True)

        # Save to WebApp notifications
        if send_web:
            notif = Notification(
                user_id=user_id,
                type=notif_type,
                title=title,
                message=message,
                link=link,
            )
            db.add(notif)
            await db.commit()

        # Send Telegram
        if send_tg and user.telegram_id and settings.TELEGRAM_BOT_TOKEN:
            try:
                bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                tg_msg = telegram_text or f"*{title}*\n{message}"
                await bot.send_message(
                    chat_id=int(user.telegram_id),
                    text=tg_msg,
                    parse_mode="Markdown",
                )
                logger.info(f"TG notification sent to {user.telegram_id}: {title}")
            except Exception as e:
                logger.error(f"TG notification failed for {user.telegram_id}: {e}")

    finally:
        if should_close:
            await db.close()


async def send_budget_warning(user_id: UUID, envelope_name: str, emoji: str, spent_pct: int, remaining: str):
    """Send budget warning when envelope reaches 80% or 90%."""
    if spent_pct >= 90:
        title = f"🔴 {emoji} {envelope_name} hampir habis!"
        msg = f"Sudah terpakai {spent_pct}%. Sisa: {remaining}"
    else:
        title = f"🟡 {emoji} {envelope_name} mulai menipis"
        msg = f"Sudah terpakai {spent_pct}%. Sisa: {remaining}"

    await send_notification(
        user_id=user_id,
        notif_type=NotificationType.budget_warning,
        title=title,
        message=msg,
        link="/envelopes",
        telegram_text=f"{title}\n{msg}",
    )


async def send_subscription_due(user_id: UUID, desc: str, amount: str, envelope_name: str, emoji: str):
    """Notify when subscription is due."""
    title = f"🔔 Jatuh tempo: {desc}"
    msg = f"{amount} — Amplop: {emoji} {envelope_name}"

    await send_notification(
        user_id=user_id,
        notif_type=NotificationType.subscription_due,
        title=title,
        message=msg,
        link="/langganan",
    )
