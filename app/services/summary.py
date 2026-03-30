import logging
from decimal import Decimal
from datetime import date, timedelta
from collections import defaultdict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User, HouseholdMember, Envelope, Transaction, Allocation
from app.bot.handlers import format_currency, get_envelopes_with_spent

settings = get_settings()
logger = logging.getLogger("jatahku.summary")

DAY_ID = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def _short_bar(spent, allocated, width=6):
    """▓▓▓░░░ style bar, width chars."""
    if not allocated or allocated <= 0:
        return ""
    ratio = min(float(spent / allocated), 1.0)
    filled = round(ratio * width)
    return "▓" * filled + "░" * (width - filled)


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

                from app.models.models import Allocation, Income as IncModel
                from app.models.models import RecurringTransaction, RecurringFrequency

                # ── Build per-envelope period stats ────────────────────────
                env_stats = []  # (env, allocated, spent, reserved, remaining, indicator)
                total_period_spent = Decimal("0")
                total_period_allocated = Decimal("0")

                for env in envelopes:
                    spent_r = await db.execute(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.envelope_id == env.id,
                            Transaction.is_deleted == False,
                            Transaction.transaction_date >= period_start,
                            Transaction.transaction_date <= period_end,
                        )
                    )
                    spent = Decimal(str(spent_r.scalar()))

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
                        indicator = "🔴" if ratio >= 0.9 else ("🟡" if ratio >= 0.7 else "🟢")
                    else:
                        indicator = "⚪"

                    env_stats.append((env, allocated, spent, reserved, remaining, indicator))
                    total_period_spent += spent
                    total_period_allocated += allocated

                # ── Burn rate & status ─────────────────────────────────────
                period_info2 = get_period_info(payday_day)
                days_used = period_info2.get("days_used", 1) or 1
                daily_avg = total_period_spent / days_used if days_used > 0 else Decimal("0")
                total_remaining = total_period_allocated - total_period_spent
                projected_end = daily_avg * (days_used + days_left) if daily_avg > 0 else Decimal("0")

                if total_period_allocated > 0 and projected_end <= total_period_allocated:
                    status_line = f"✅ On track · avg {format_currency(daily_avg)}/hari"
                elif total_period_allocated > 0:
                    overshoot = projected_end - total_period_allocated
                    safe_daily = total_remaining / days_left if days_left > 0 else Decimal("0")
                    status_line = f"⚠️ Hati-hati · max {format_currency(safe_daily)}/hari biar aman"
                else:
                    status_line = f"📊 avg {format_currency(daily_avg)}/hari"

                # ── Today's spending grouped by envelope ───────────────────
                day_name = DAY_ID[today.weekday()]
                date_str = today.strftime("%d %b")
                lines = [f"📋 <b>Ringkasan · {day_name}, {date_str}</b>"]

                if today_txns:
                    by_env: dict = defaultdict(Decimal)
                    for t in today_txns:
                        by_env[t.envelope_id] += t.amount
                    sorted_envs = sorted(by_env.items(), key=lambda x: x[1], reverse=True)

                    # Top 2 envelopes inline, rest as "+X lainnya Rpyyy"
                    parts = []
                    shown_total = Decimal("0")
                    for i, (eid, amt) in enumerate(sorted_envs):
                        if i < 2:
                            env = next((e for e in envelopes if e.id == eid), None)
                            em = env.emoji if env else "📁"
                            nm = (env.name or "Lain").split()[0]
                            parts.append(f"{em} {nm} {format_currency(amt)}")
                            shown_total += amt
                        else:
                            break
                    rest = today_total - shown_total
                    if len(sorted_envs) > 2 and rest > 0:
                        extra_count = len(sorted_envs) - 2
                        parts.append(f"+{extra_count} lain {format_currency(rest)}")

                    lines.append(
                        f"\n💸 Pengeluaran: <b>{format_currency(today_total)}</b> ({len(today_txns)} txn)"
                    )
                    lines.append("  " + " · ".join(parts))
                else:
                    lines.append("\n✨ Nggak ada pengeluaran hari ini. Nice!")

                # ── Envelope section ───────────────────────────────────────
                lines.append(f"\n─────────────────")
                lines.append(f"📦 <b>Amplop</b> — {days_left} hari lagi\n")

                for env, allocated, spent, reserved, remaining, indicator in env_stats:
                    emoji = env.emoji or "📁"
                    name = env.name or "—"
                    rem_str = format_currency(remaining) if remaining > 0 else "habis"
                    rem_bold = f"<b>{rem_str}</b>"

                    if allocated > 0 and spent > 0:
                        pct = int(float(spent / allocated) * 100)
                        bar = _short_bar(spent, allocated)
                        lines.append(f"{indicator} {emoji} {name} · {rem_bold}  {bar} {pct}%")
                    else:
                        lines.append(f"{indicator} {emoji} {name} · {rem_bold}")

                lines.append(f"─────────────────")
                lines.append(status_line)

                await bot.send_message(
                    chat_id=int(user.telegram_id),
                    text="\n".join(lines),
                    parse_mode="HTML",
                )
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
