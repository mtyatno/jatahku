import logging
from datetime import date, timedelta
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import (
    RecurringTransaction, RecurringFrequency, Envelope, User, HouseholdMember
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from app.core.config import get_settings
from app.bot.handlers import format_currency

settings = get_settings()
logger = logging.getLogger("jatahku.recurring")


def _next_date(current: date, freq: RecurringFrequency) -> date:
    if freq == RecurringFrequency.weekly:
        return current + timedelta(weeks=1)
    elif freq == RecurringFrequency.monthly:
        month = current.month + 1 if current.month < 12 else 1
        year = current.year if current.month < 12 else current.year + 1
        day = min(current.day, 28)
        return date(year, month, day)
    elif freq == RecurringFrequency.yearly:
        return date(current.year + 1, current.month, current.day)
    return current + timedelta(days=30)


async def process_recurring_transactions():
    """Send reminders for recurring transactions due today. User must confirm."""
    today = date.today()

    if not settings.TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RecurringTransaction)
            .where(
                RecurringTransaction.is_active == True,
                RecurringTransaction.next_run <= today,
            )
        )
        recs = result.scalars().all()

        if not recs:
            return

        for rec in recs:
            try:
                env_result = await db.execute(
                    select(Envelope).where(Envelope.id == rec.envelope_id)
                )
                envelope = env_result.scalar_one_or_none()
                if not envelope:
                    continue

                # Find all TG-linked users in this household
                members_result = await db.execute(
                    select(User)
                    .join(HouseholdMember, HouseholdMember.user_id == User.id)
                    .where(
                        HouseholdMember.household_id == envelope.household_id,
                        User.telegram_id != None,
                    )
                )
                users = members_result.scalars().all()

                emoji = envelope.emoji or "📁"
                freq_label = {"weekly": "mingguan", "monthly": "bulanan", "yearly": "tahunan"}

                keyboard = [
                    [InlineKeyboardButton("✅ Bayar & catat", callback_data=f"recpay_{rec.id}")],
                    [InlineKeyboardButton("⏭️ Skip bulan ini", callback_data=f"recskip_{rec.id}")],
                    [InlineKeyboardButton("❌ Berhenti langganan", callback_data=f"recstop_{rec.id}")],
                ]

                for user in users:
                    try:
                        await bot.send_message(
                            chat_id=int(user.telegram_id),
                            text=(
                                f"🔔 Jatuh tempo langganan!\n\n"
                                f"🔄 {rec.description}\n"
                                f"{format_currency(rec.amount)} · {freq_label.get(rec.frequency.value, rec.frequency.value)}\n"
                                f"Amplop: {emoji} {envelope.name}\n\n"
                                f"Sudah bayar? Atau mau skip/berhenti?"
                            ),
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                        logger.info(f"Sent recurring reminder to {user.telegram_id}: {rec.description}")
                    except Exception as e:
                        logger.error(f"Failed notify {user.telegram_id}: {e}")

            except Exception as e:
                logger.error(f"Failed recurring {rec.id}: {e}")
