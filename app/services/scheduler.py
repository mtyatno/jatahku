import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.rollover import create_monthly_snapshots
from app.services.summary import send_daily_summary, send_weekly_summary
from app.services.recurring_processor import process_recurring_transactions
from app.services.visibility import masked_description

logger = logging.getLogger("jatahku.scheduler")
scheduler = AsyncIOScheduler()


# How many recently-closed periods the daily job backfills. Covers short
# outages; use the /snapshots/recompute endpoint for longer gaps or repairs.
CATCH_UP_PERIODS = 3


async def payday_snapshot_job():
    """Run daily — ensure snapshots exist for all recently-closed budget periods.

    Idempotent and self-healing: walks the last few closed periods oldest-first
    and creates any that are missing (e.g. skipped by a missed run), so the
    rollover chain never loses a link. Existing snapshots are left untouched."""
    from app.core.database import AsyncSessionLocal
    from app.core.period import get_closed_periods
    from app.models.models import User, HouseholdMember

    today = date.today()

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select as _sel
        users_r = await db.execute(_sel(User).where(User.payday_day != None))
        users = users_r.scalars().all()

        # Group user IDs by payday_day
        payday_user_ids: dict[int, list] = {}
        for user in users:
            pd = getattr(user, 'payday_day', 1) or 1
            payday_user_ids.setdefault(pd, []).append(user.id)

        # Resolve the households for each payday_day group
        payday_households: dict[int, list] = {}
        for pd, user_ids in payday_user_ids.items():
            hm_r = await db.execute(
                _sel(HouseholdMember.household_id)
                .where(HouseholdMember.user_id.in_(user_ids))
                .distinct()
            )
            payday_households[pd] = list(hm_r.scalars().all())

    # Backfill recent closed periods per payday_day, oldest-first so each
    # period's rollover sees its (already-created) predecessor.
    for pd, household_ids in payday_households.items():
        if not household_ids:
            continue
        for period_start, period_end in get_closed_periods(pd, today, CATCH_UP_PERIODS):
            result = await create_monthly_snapshots(
                period_start, period_end, household_ids=household_ids
            )
            if result["snapshots_created"]:
                logger.info(
                    f"payday={pd} period {period_start} → {period_end}: "
                    f"{result['snapshots_created']} snapshots created, "
                    f"{len(result['errors'])} errors"
                )


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
                            f"{format_currency(pending.amount)} — {masked_description(user.id, pending)}\n"
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


async def run_user_summaries():
    """Check each user's timezone + preferred time, send if it matches now."""
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.models import User, NotificationPreference

    now_utc = datetime.now(tz.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id != None))
        users = result.scalars().all()

        for user in users:
            try:
                user_tz = ZoneInfo(getattr(user, 'timezone', 'Asia/Jakarta') or 'Asia/Jakarta')
            except:
                user_tz = ZoneInfo('Asia/Jakarta')

            user_now = now_utc.astimezone(user_tz)
            user_hour = f"{user_now.hour:02d}:00"

            # Get preferences
            prefs_r = await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user.id)
            )
            prefs = prefs_r.scalar_one_or_none()

            daily_time = getattr(prefs, 'daily_summary_time', '20:00') or '20:00' if prefs else '20:00'
            weekly_time = getattr(prefs, 'weekly_summary_time', '08:00') or '08:00' if prefs else '08:00'

            # Daily summary
            if prefs and prefs.daily_summary_tg and user_hour == daily_time.split(':')[0] + ':00':
                try:
                    await send_daily_summary(user_id=user.id)
                except Exception as e:
                    logger.error(f"Daily summary failed for {user.id}: {e}")

            # Weekly summary (Monday only)
            if user_now.weekday() == 0 and prefs and prefs.weekly_summary_tg and user_hour == weekly_time.split(':')[0] + ':00':
                try:
                    await send_weekly_summary(user_id=user.id)
                except Exception as e:
                    logger.error(f"Weekly summary failed for {user.id}: {e}")

            # Payday allocation reminder (08:00 local, first 3 days of period)
            if user_hour == "08:00":
                try:
                    from app.services.payday_reminder import send_payday_reminder
                    await send_payday_reminder(user, user_now, prefs, db)
                except Exception as e:
                    logger.error(f"Payday reminder failed for {user.id}: {e}")

            # Daily check-in nudge — if user hasn't logged anything today by
            # their preferred hour, gently ask them to (keeps the habit alive).
            checkin_time = (getattr(prefs, 'checkin_nudge_time', '21:00') or '21:00') if prefs else '21:00'
            checkin_on = getattr(prefs, 'checkin_nudge_tg', True) if prefs else True
            if checkin_on and user_hour == checkin_time.split(':')[0] + ':00':
                try:
                    await send_checkin_nudge(user, user_now.date(), db)
                except Exception as e:
                    logger.error(f"Check-in nudge failed for {user.id}: {e}")

    logger.info(f"User summaries check complete at {now_utc.isoformat()}")


async def send_checkin_nudge(user, local_today, db):
    """Send a once-a-day Telegram nudge if the user hasn't logged today.

    No-ops when: the user has no Telegram, already logged activity today, or a
    nudge was already sent today (anti-spam). The 'no spending' button keeps the
    streak alive without forcing a transaction."""
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from app.models.models import UserStreak
    from app.core.config import get_settings

    if not user.telegram_id:
        return

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    streak = await db.get(UserStreak, user.id)
    # Already logged today → no nudge needed.
    if streak and streak.last_log_date == local_today:
        return
    # Already nudged today → don't spam.
    if streak and streak.last_checkin_date == local_today:
        return

    streak_hint = ""
    if streak and streak.current_streak >= 2 and streak.last_log_date == local_today - timedelta(days=1):
        streak_hint = f"\n\nStreak kamu {streak.current_streak} hari — jangan putus ya 🔥"

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    keyboard = [[InlineKeyboardButton("✅ Gak ada pengeluaran hari ini", callback_data="checkin_none")]]
    try:
        await bot.send_message(
            chat_id=int(user.telegram_id),
            text=(
                "👋 Belum ada catatan hari ini.\n\n"
                "Lagi hemat, atau lupa nyatat? Kirim aja pengeluaranmu "
                "(misal: <i>kopi 25k</i>), atau tekan tombol kalau memang "
                f"gak ada pengeluaran.{streak_hint}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        # Record that we nudged today (create row if needed).
        if streak is None:
            streak = UserStreak(user_id=user.id)
            db.add(streak)
        streak.last_checkin_date = local_today
        await db.commit()
        logger.info(f"Sent check-in nudge to {user.telegram_id}")
    except Exception as e:
        logger.error(f"Failed to send check-in nudge to {user.id}: {e}")


def start_scheduler():
    """Start the APScheduler with monthly snapshot job."""
    scheduler.add_job(
        payday_snapshot_job,
        trigger="cron",
        hour=0,
        minute=5,
        id="payday_snapshot",
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
        run_user_summaries,
        trigger="cron",
        minute=0,  # Every hour, check which users need summary
        id="user_summaries",
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
    logger.info("Scheduler started — monthly snapshot + pending reminders + hourly user summaries + recurring")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
