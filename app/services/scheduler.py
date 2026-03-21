import logging
from datetime import date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.rollover import create_monthly_snapshots
from app.services.summary import send_daily_summary, send_weekly_summary
from app.services.recurring_processor import process_recurring_transactions

logger = logging.getLogger("jatahku.scheduler")
scheduler = AsyncIOScheduler()


async def monthly_snapshot_job():
    """Run on the 1st of each month — snapshot the previous month."""
    now = date.today()
    if now.month == 1:
        target_year, target_month = now.year - 1, 12
    else:
        target_year, target_month = now.year, now.month - 1

    logger.info(f"Running monthly snapshot for {target_year}-{target_month:02d}")
    result = await create_monthly_snapshots(target_year, target_month)
    logger.info(f"Snapshot result: {result}")


async def check_pending_reminders():
    """Check for pending transactions ready to confirm, send Telegram reminder."""
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from app.core.database import AsyncSessionLocal
    from app.models.models import PendingTransaction, PendingTransactionStatus, User, Envelope
    import redis.asyncio as aioredis
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        # Find pending transactions that are past confirm_after and not yet reminded
        result = await db.execute(
            select(PendingTransaction, User, Envelope)
            .join(User, PendingTransaction.user_id == User.id)
            .join(Envelope, PendingTransaction.envelope_id == Envelope.id)
            .where(
                PendingTransaction.status == PendingTransactionStatus.pending,
                PendingTransaction.confirm_after <= now,
            )
        )
        rows = result.all()

        r = aioredis.from_url(settings.REDIS_URL)
        for pending, user, envelope in rows:
            # Check if already reminded (use Redis to track)
            reminded_key = f"reminded:{pending.id}"
            already = await r.get(reminded_key)
            if already:
                continue

            if user.telegram_id:
                try:
                    emoji = envelope.emoji or "📁"
                    from app.bot.handlers import format_currency
                    keyboard = [
                        [InlineKeyboardButton("✅ Konfirmasi", callback_data=f"cool_confirm_{pending.id}")],
                        [InlineKeyboardButton("❌ Batalkan", callback_data=f"cool_cancel_{pending.id}")],
                    ]
                    await bot.send_message(
                        chat_id=int(user.telegram_id),
                        text=(
                            f"🔔 Cooling period selesai!\n\n"
                            f"{format_currency(pending.amount)} — {pending.description}\n"
                            f"Amplop: {emoji} {envelope.name}\n\n"
                            f"Masih mau beli? Konfirmasi atau batalkan."
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                    # Mark as reminded (expire in 48h)
                    await r.set(reminded_key, "1", ex=172800)
                    logger.info(f"Sent cooling reminder to {user.telegram_id} for pending {pending.id}")
                except Exception as e:
                    logger.error(f"Failed to send reminder: {e}")

        # Auto-expire old pending transactions
        expired = await db.execute(
            select(PendingTransaction).where(
                PendingTransaction.status == PendingTransactionStatus.pending,
                PendingTransaction.expires_at < now,
            )
        )
        for p in expired.scalars().all():
            p.status = PendingTransactionStatus.expired
            logger.info(f"Auto-expired pending transaction {p.id}")

        await db.commit()
        await r.close()


def start_scheduler():
    """Start the APScheduler with monthly snapshot job."""
    scheduler.add_job(
        monthly_snapshot_job,
        trigger="cron",
        day=1,
        hour=0,
        minute=5,
        id="monthly_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        check_pending_reminders,
        trigger="interval",
        minutes=5,
        id="pending_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        send_daily_summary,
        trigger="cron",
        hour=13,  # 20:00 WIB = 13:00 UTC
        minute=0,
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_summary,
        trigger="cron",
        day_of_week="mon",
        hour=1,  # 08:00 WIB = 01:00 UTC
        minute=0,
        id="weekly_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        process_recurring_transactions,
        trigger="cron",
        hour=0,  # 07:00 WIB = 00:00 UTC
        minute=1,
        id="recurring_transactions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — monthly snapshot + pending reminders + daily 20:00 + weekly Monday 08:00")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
