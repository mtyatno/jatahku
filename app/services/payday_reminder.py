import logging
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.period import get_budget_period, payday_reminder_day_index
from app.models.models import HouseholdMember, Income

logger = logging.getLogger("jatahku.payday_reminder")
settings = get_settings()

MONTHS_ID = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
             "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

ALLOCATE_URL = "https://jatahku.com/allocate"


def _fmt(d) -> str:
    return f"{d.day} {MONTHS_ID[d.month]}"


async def _has_allocated_this_period(user, period_start, period_end, db: AsyncSession) -> bool:
    """True if the user's household already has a positive income in this period."""
    hid = (await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )).scalar_one_or_none()
    if not hid:
        return False
    cnt = (await db.execute(
        select(func.count()).select_from(Income).where(
            Income.household_id == hid,
            Income.amount > 0,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )).scalar()
    return (cnt or 0) > 0


async def send_payday_reminder(user, user_now: datetime, prefs, db: AsyncSession) -> bool:
    """Send a payday allocation reminder to one Telegram user if due.

    Returns True if a message was sent. Caller (scheduler) gates on the user's
    local hour == 08:00; this function handles pref + window + allocation +
    dedup, then sends."""
    if not settings.TELEGRAM_BOT_TOKEN or not user.telegram_id:
        return False
    # Missing prefs row -> default opt-in
    if prefs is not None and not getattr(prefs, "payday_reminder_tg", True):
        return False

    payday_day = getattr(user, "payday_day", 1) or 1
    today = user_now.date()
    idx = payday_reminder_day_index(payday_day, today)
    if idx is None:
        return False

    period_start, period_end = get_budget_period(payday_day, today)
    if await _has_allocated_this_period(user, period_start, period_end, db):
        return False

    # Dedup guard: at most one send per (user, period, day-index)
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        key = f"payday_nudge:{user.id}:{period_start.isoformat()}:{idx}"
        first = await r.set(key, "1", ex=3456000, nx=True)  # 40-day TTL
        if not first:
            return False
    finally:
        await r.close()

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    if idx == 0:
        text = (
            "💰 <b>Gajian tiba!</b> Saatnya kasih jatah tiap rupiah biar "
            "terkendali sampai gajian berikutnya.\n\n"
            f"Periode baru: <b>{_fmt(period_start)} → {_fmt(period_end)}</b>\n"
            "Tap di bawah untuk alokasikan gajimu 👇"
        )
    else:
        text = (
            "🔔 Gaji belum dialokasikan nih. Yuk bagi jatahnya dulu biar "
            "nggak kebablasan bulan ini."
        )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📥 Alokasikan Gaji", url=ALLOCATE_URL)]]
    )
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=int(user.telegram_id),
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Payday reminder (day {idx}) sent to {user.telegram_id}")
    return True
