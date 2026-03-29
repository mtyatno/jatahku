import logging
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User, HouseholdMember, Envelope, Transaction, Allocation
from app.bot.handlers import format_currency, progress_bar, get_envelopes_with_spent

settings = get_settings()
logger = logging.getLogger("jatahku.summary")


async def send_daily_summary(user_id=None):
    """Send daily spending summary to all TG-linked users at 8 PM."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Get all users with telegram
        query = select(User).where(User.telegram_id != None)
        if user_id:
            query = query.where(User.id == user_id)
        result = await db.execute(query)
        users = result.scalars().all()

        for user in users:
            try:
                hid_result = await db.execute(
                    select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
                )
                hid = hid_result.scalar_one_or_none()
                if not hid:
                    continue

                # Today's transactions
                txn_result = await db.execute(
                    select(Transaction)
                    .join(Envelope)
                    .where(
                        Envelope.household_id == hid,
                        Transaction.is_deleted == False,
                        Transaction.transaction_date == today,
                    )
                    .order_by(Transaction.created_at.desc())
                )
                today_txns = txn_result.scalars().all()

                today_total = sum(t.amount for t in today_txns)

                # Get envelope summaries
                from sqlalchemy import or_
                env_result = await db.execute(
                    select(Envelope).where(
                        Envelope.household_id == hid,
                        Envelope.is_active == True,
                        or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
                    ).order_by(Envelope.created_at)
                )
                envelopes = env_result.scalars().all()

                from app.core.period import get_period_info
                payday_day = getattr(user, 'payday_day', 1) or 1
                period_info = get_period_info(payday_day)
                period_start = period_info["period_start"]
                period_end = period_info["period_end"]
                days_left = period_info["days_remaining"]

                lines = [f"📋 Ringkasan hari ini ({today.strftime('%d %b')}):\n"]

                if today_txns:
                    lines.append(f"💸 Total pengeluaran: {format_currency(today_total)}")
                    lines.append(f"📝 {len(today_txns)} transaksi\n")
                    for t in today_txns[:5]:
                        env = next((e for e in envelopes if e.id == t.envelope_id), None)
                        emoji = env.emoji if env else "📁"
                        lines.append(f"  {emoji} {format_currency(t.amount)} — {t.description}")
                    if len(today_txns) > 5:
                        lines.append(f"  ... +{len(today_txns) - 5} lainnya")
                else:
                    lines.append("✨ Nggak ada pengeluaran hari ini. Nice!")

                lines.append(f"\n📊 Sisa dana ({days_left} hari lagi sampai gajian):")
                for env in envelopes:
                    spent_result = await db.execute(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.envelope_id == env.id,
                            Transaction.is_deleted == False,
                            Transaction.transaction_date >= period_start,
                            Transaction.transaction_date <= period_end,
                        )
                    )
                    spent = Decimal(str(spent_result.scalar()))
                    from app.models.models import Allocation, Income as IncModel
                    alloc_r = await db.execute(
                        select(func.coalesce(func.sum(Allocation.amount), 0))
                        .join(IncModel, Allocation.income_id == IncModel.id)
                        .where(
                            Allocation.envelope_id == env.id,
                            IncModel.income_date >= period_start,
                            IncModel.income_date <= period_end,
                        )
                    )
                    allocated = Decimal(str(alloc_r.scalar()))
                    from app.models.models import RecurringTransaction, RecurringFrequency
                    rec_r = await db.execute(
                        select(RecurringTransaction).where(
                            RecurringTransaction.envelope_id == env.id,
                            RecurringTransaction.is_active == True,
                        )
                    )
                    reserved = Decimal("0")
                    for rec in rec_r.scalars().all():
                        if rec.frequency == RecurringFrequency.weekly:
                            reserved += rec.amount * 4
                        elif rec.frequency == RecurringFrequency.yearly:
                            reserved += rec.amount / 12
                        else:
                            reserved += rec.amount
                    remaining = allocated - spent - reserved
                    if allocated > 0:
                        ratio = float(spent / allocated)
                        indicator = "\U0001f534" if ratio >= 0.9 else ("\U0001f7e1" if ratio >= 0.7 else "\U0001f7e2")
                    else:
                        indicator = "\u26aa"
                    emoji = env.emoji or "\U0001f4c1"
                    bar = progress_bar(spent, allocated)
                    lines.append(f"{indicator} {emoji} {env.name}  {bar}  {format_currency(remaining)}")
                await bot.send_message(chat_id=int(user.telegram_id), text="\n".join(lines))
                logger.info(f"Daily summary sent to {user.telegram_id}")

            except Exception as e:
                logger.error(f"Failed daily summary for {user.telegram_id}: {e}")


async def send_weekly_summary(user_id=None):
    """Send weekly summary every Monday morning."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    today = date.today()
    week_start = today - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        query = select(User).where(User.telegram_id != None)
        if user_id:
            query = query.where(User.id == user_id)
        result = await db.execute(query)
        users = result.scalars().all()

        for user in users:
            try:
                hid_result = await db.execute(
                    select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
                )
                hid = hid_result.scalar_one_or_none()
                if not hid:
                    continue

                # Week's transactions
                txn_result = await db.execute(
                    select(Transaction)
                    .join(Envelope)
                    .where(
                        Envelope.household_id == hid,
                        Transaction.is_deleted == False,
                        Transaction.transaction_date >= week_start,
                        Transaction.transaction_date <= today,
                    )
                )
                week_txns = txn_result.scalars().all()
                week_total = sum(t.amount for t in week_txns)

                # Monthly totals
                from sqlalchemy import or_
                env_result = await db.execute(
                    select(Envelope).where(
                        Envelope.household_id == hid,
                        Envelope.is_active == True,
                        or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
                    ).order_by(Envelope.created_at)
                )
                envelopes = env_result.scalars().all()

                from app.core.period import get_period_info
                payday_day = getattr(user, 'payday_day', 1) or 1
                period_info = get_period_info(payday_day)
                period_start = period_info["period_start"]
                period_end = period_info["period_end"]
                days_left = period_info["days_remaining"]
                days_passed = period_info["days_used"]

                from app.models.models import Allocation, Income as IncModel
                total_budget = Decimal("0")
                total_spent = Decimal("0")
                for env in envelopes:
                    alloc_r = await db.execute(
                        select(func.coalesce(func.sum(Allocation.amount), 0))
                        .join(IncModel, Allocation.income_id == IncModel.id)
                        .where(
                            Allocation.envelope_id == env.id,
                            IncModel.income_date >= period_start,
                            IncModel.income_date <= period_end,
                        )
                    )
                    total_budget += Decimal(str(alloc_r.scalar()))
                    spent_result = await db.execute(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.envelope_id == env.id,
                            Transaction.is_deleted == False,
                            Transaction.transaction_date >= period_start,
                            Transaction.transaction_date <= period_end,
                        )
                    )
                    total_spent += Decimal(str(spent_result.scalar()))

                total_remaining = total_budget - total_spent

                # Prediction: at current rate, will budget last?
                if days_passed > 0:
                    daily_avg = total_spent / days_passed
                    predicted_total = daily_avg * (days_passed + days_left)
                    on_track = predicted_total <= total_budget
                else:
                    daily_avg = Decimal("0")
                    predicted_total = Decimal("0")
                    on_track = True

                period_label = f"{period_start.strftime('%d %b')} – {period_end.strftime('%d %b')}"
                lines = [f"📊 Ringkasan minggu ({week_start.strftime('%d %b')} - {today.strftime('%d %b')}):\n"]
                lines.append(f"💸 Pengeluaran minggu ini: {format_currency(week_total)}")
                lines.append(f"📝 {len(week_txns)} transaksi")
                lines.append(f"📈 Rata-rata harian: {format_currency(daily_avg)}/hari\n")

                lines.append(f"📅 Progress periode {period_label} ({days_left} hari lagi):")
                lines.append(f"   Dana: {format_currency(total_budget)}")
                lines.append(f"   Terpakai: {format_currency(total_spent)} ({int(total_spent / total_budget * 100) if total_budget > 0 else 0}%)")
                lines.append(f"   Sisa: {format_currency(total_remaining)}\n")

                if on_track:
                    lines.append(f"✅ Prediksi: On track! Budget cukup sampai gajian.")
                else:
                    over = predicted_total - total_budget
                    lines.append(f"⚠️ Prediksi: Overspend {format_currency(over)} sebelum gajian!")
                    safe_daily = total_remaining / days_left if days_left > 0 else Decimal("0")
                    lines.append(f"💡 Supaya aman, max {format_currency(safe_daily)}/hari.")

                await bot.send_message(chat_id=int(user.telegram_id), text="\n".join(lines))
                logger.info(f"Weekly summary sent to {user.telegram_id}")

            except Exception as e:
                logger.error(f"Failed weekly summary for {user.telegram_id}: {e}")
