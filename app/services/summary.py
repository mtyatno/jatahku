import html
import logging
from decimal import Decimal
from datetime import date, timedelta
from collections import defaultdict
from types import SimpleNamespace
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import User, HouseholdMember, Envelope, Transaction
from app.bot.handlers import format_currency
from app.services.envelope_balance import compute_envelope_summaries

settings = get_settings()
logger = logging.getLogger("jatahku.summary")


def _today_txns_query(hid, user_id, today):
    """Transaksi 'hari ini' untuk ringkasan harian. Penyesuaian cocokkan saldo
    dikecualikan: tanggalnya buatan, bukan belanja hari ini."""
    return (
        select(Transaction)
        .join(Envelope)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            Transaction.transaction_date == today,
            Transaction.balance_check_id.is_(None),
            or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
        )
        .order_by(Transaction.created_at.desc())
    )


def _week_txns_query(hid, user_id, week_start, today):
    """Seksi 'Minggu ini' di ringkasan mingguan (tanpa penyesuaian). Seksi
    periode (Dana/Terpakai/Sisa) dihitung terpisah dan tetap menyertakannya.
    Amplop pribadi anggota lain tidak ikut (privasi, sama dgn ringkasan harian)."""
    return (
        select(Transaction)
        .join(Envelope)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= week_start,
            Transaction.transaction_date <= today,
            Transaction.balance_check_id.is_(None),
            or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
        )
    )


def _env_label(env) -> tuple[str, str]:
    """(emoji, nama pendek) untuk baris top-amplop; aman bila amplop tak ditemukan."""
    if env is None:
        return "📁", "Lain"
    parts = (env.name or "").split()
    return env.emoji, (parts[0] if parts else "Lain")


def _esc(s) -> str:
    """Escape teks input user untuk pesan Telegram parse_mode="HTML"."""
    return html.escape("" if s is None else str(s), quote=False)


DAY_ID = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def _short_bar(spent, allocated, width=6):
    """▓▓▓░░░ style bar, width chars."""
    if not allocated or allocated <= 0:
        return ""
    ratio = min(float(spent / allocated), 1.0)
    filled = round(ratio * width)
    return "▓" * filled + "░" * (width - filled)


# Sama dengan KPI dashboard "Sisa bebas" (Dashboard.jsx): tabungan & sinking fund tidak ikut.
NON_FREE_PURPOSES = ("saving", "sinking_fund")


def _purpose(row) -> str:
    p = row.get("purpose")
    return str(getattr(p, "value", p))


def _period_totals(rows) -> tuple[Decimal, Decimal, Decimal]:
    """(dana, terpakai, sisa_bebas) dari baris compute_envelope_summaries — sama
    dengan dashboard: dana = Σ(allocated + rollover), terpakai = Σ spent,
    sisa_bebas = Σ free amplop selain saving/sinking_fund."""
    dana = sum((r["allocated"] + r["rollover"] for r in rows), Decimal("0"))
    terpakai = sum((r["spent"] for r in rows), Decimal("0"))
    sisa_bebas = sum(
        (r["free"] for r in rows if _purpose(r) not in NON_FREE_PURPOSES), Decimal("0")
    )
    return dana, terpakai, sisa_bebas


def _envelope_line(row) -> str:
    """Satu baris seksi "📦 Amplop" ringkasan harian (HTML; emoji/nama ter-escape).
    Sisa = free (termasuk rollover, dikurangi cadangan langganan)."""
    dana = row["allocated"] + row["rollover"]
    spent = row["spent"]
    free = row["free"]
    if dana > 0:
        ratio = row["spent_ratio"]
        indicator = "🔴" if ratio >= 0.9 else ("🟡" if ratio >= 0.7 else "🟢")
    else:
        indicator = "⚪"
    emoji = _esc(row.get("emoji") or "📁")
    name = _esc(row.get("name") or "—")
    rem_str = format_currency(free) if free > 0 else "habis"
    rem_bold = f"<b>{rem_str}</b>"
    if dana > 0 and spent > 0:
        pct = int(float(spent / dana) * 100)
        bar = _short_bar(spent, dana)
        return f"{indicator} {emoji} {name} · {rem_bold}  {bar} {pct}%"
    return f"{indicator} {emoji} {name} · {rem_bold}"


def _week_window(today: date) -> tuple[date, date]:
    """'Minggu ini' = 7 hari inklusif yang berakhir hari ini."""
    return today - timedelta(days=6), today


def _env_lookup(rows) -> dict:
    """id amplop → objek ringan (id, name, emoji) untuk _env_label, dari baris ringkasan."""
    return {
        r["id"]: SimpleNamespace(id=r["id"], name=r.get("name"), emoji=r.get("emoji"))
        for r in rows
    }


def _top_parts(by_env: dict, envs: dict, total) -> list[str]:
    """Top-2 amplop inline + "+X lain Rpyyy"; emoji/nama ter-escape untuk HTML."""
    sorted_envs = sorted(by_env.items(), key=lambda x: x[1], reverse=True)
    parts = []
    shown = Decimal("0")
    for eid, amt in sorted_envs[:2]:
        em, nm = _env_label(envs.get(eid))
        parts.append(f"{_esc(em)} {_esc(nm)} {format_currency(amt)}")
        shown += amt
    rest = total - shown
    if len(sorted_envs) > 2 and rest > 0:
        parts.append(f"+{len(sorted_envs) - 2} lain {format_currency(rest)}")
    return parts


async def send_daily_summary(user_id=None):
    """Send daily spending summary to all Telegram-linked users at 8 PM."""
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None
    today = date.today()

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

                # Today's transactions
                txn_result = await db.execute(_today_txns_query(hid, user.id, today))
                today_txns = txn_result.scalars().all()

                today_total = sum(t.amount for t in today_txns)

                # Per-envelope period stats — sumber yang sama dengan dashboard
                # (GET /envelopes/summary): termasuk rollover & cadangan langganan.
                rows = await compute_envelope_summaries(user, db)
                envs = _env_lookup(rows)
                dana, terpakai, sisa_bebas = _period_totals(rows)

                from app.core.period import get_period_info
                payday_day = getattr(user, 'payday_day', 1) or 1
                period_info = get_period_info(payday_day)
                days_left = period_info["days_remaining"]

                # ── Burn rate & status ─────────────────────────────────────
                days_used = period_info.get("days_used", 1) or 1
                daily_avg = terpakai / days_used if days_used > 0 else Decimal("0")
                projected_end = daily_avg * (days_used + days_left) if daily_avg > 0 else Decimal("0")

                if dana > 0 and projected_end <= dana:
                    status_line = f"✅ On track · avg {format_currency(daily_avg)}/hari"
                elif dana > 0:
                    safe_daily = sisa_bebas / days_left if days_left > 0 else Decimal("0")
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
                    # Top 2 envelopes inline, rest as "+X lainnya Rpyyy"
                    parts = _top_parts(by_env, envs, today_total)

                    lines.append(
                        f"\n💸 Pengeluaran: <b>{format_currency(today_total)}</b> ({len(today_txns)} txn)"
                    )
                    lines.append("  " + " · ".join(parts))
                else:
                    lines.append("\n✨ Nggak ada pengeluaran hari ini. Nice!")

                # ── Envelope section ───────────────────────────────────────
                lines.append(f"\n─────────────────")
                lines.append(f"📦 <b>Amplop</b> — {days_left} hari lagi\n")

                for r in rows:
                    lines.append(_envelope_line(r))

                lines.append(f"─────────────────")
                lines.append(status_line)

                if user.telegram_id and bot:
                    await bot.send_message(
                        chat_id=int(user.telegram_id),
                        text="\n".join(lines),
                        parse_mode="HTML",
                    )
                    logger.info(f"Daily summary sent to TG {user.telegram_id}")

            except Exception as e:
                logger.error(f"Failed daily summary for user {user.id}: {e}")


async def send_weekly_summary(user_id=None):
    """Send weekly summary every Monday morning."""
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None
    today = date.today()
    week_start, _ = _week_window(today)

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
                txn_result = await db.execute(_week_txns_query(hid, user.id, week_start, today))
                week_txns = txn_result.scalars().all()
                week_total = sum(t.amount for t in week_txns)

                # Period totals — sumber & definisi sama dengan dashboard
                # (dana termasuk rollover; Sisa = KPI "Sisa bebas").
                rows = await compute_envelope_summaries(user, db)
                envs = _env_lookup(rows)
                total_budget, total_spent, total_remaining = _period_totals(rows)

                from app.core.period import get_period_info
                payday_day = getattr(user, 'payday_day', 1) or 1
                period_info = get_period_info(payday_day)
                period_start = period_info["period_start"]
                period_end = period_info["period_end"]
                days_left = period_info["days_remaining"]
                days_passed = period_info["days_used"]

                # Prediction: at current rate, will budget last?
                if days_passed > 0:
                    daily_avg = total_spent / days_passed
                    predicted_total = daily_avg * (days_passed + days_left)
                    on_track = predicted_total <= total_budget
                else:
                    daily_avg = Decimal("0")
                    predicted_total = Decimal("0")
                    on_track = True

                # ── Week's spending grouped by envelope ────────────────────
                week_label = f"{week_start.strftime('%d')}–{today.strftime('%d %b')}"
                lines = [f"📊 <b>Minggu ini · {week_label}</b>"]

                if week_txns:
                    by_env: dict = defaultdict(Decimal)
                    for t in week_txns:
                        by_env[t.envelope_id] += t.amount
                    parts = _top_parts(by_env, envs, week_total)

                    lines.append(
                        f"\n💸 Total: <b>{format_currency(week_total)}</b> ({len(week_txns)} txn)"
                    )
                    lines.append("  " + " · ".join(parts))
                else:
                    lines.append("\n✨ Tidak ada pengeluaran minggu ini.")

                # ── Period progress ────────────────────────────────────────
                total_days = days_passed + days_left
                pct_time = int(days_passed / total_days * 100) if total_days > 0 else 0
                pct_budget = int(float(total_spent / total_budget * 100)) if total_budget > 0 else 0
                period_bar = _short_bar(Decimal(days_passed), Decimal(total_days))
                budget_bar = _short_bar(total_spent, total_budget)
                period_label = f"{period_start.strftime('%d %b')} – {period_end.strftime('%d %b')}"

                lines.append(f"\n─────────────────")
                lines.append(f"📅 <b>Periode {period_label}</b>")
                lines.append(f"   Waktu  {period_bar} {pct_time}% ({days_passed}/{total_days} hari)")
                lines.append(f"   Budget {budget_bar} {pct_budget}% terpakai")
                lines.append(f"\n   Dana:     <b>{format_currency(total_budget)}</b>")
                lines.append(f"   Terpakai: <b>{format_currency(total_spent)}</b>")
                lines.append(f"   Sisa:     <b>{format_currency(total_remaining)}</b> · {days_left} hari lagi")
                lines.append(f"\n   Burn rate: {format_currency(daily_avg)}/hari")

                # ── Status ─────────────────────────────────────────────────
                lines.append(f"─────────────────")
                if on_track:
                    lines.append(f"✅ On track — budget cukup sampai gajian")
                else:
                    over = predicted_total - total_budget
                    safe_daily = total_remaining / days_left if days_left > 0 else Decimal("0")
                    lines.append(f"⚠️ Hati-hati — prediksi overspend <b>{format_currency(over)}</b>")
                    lines.append(f"💡 Max <b>{format_currency(safe_daily)}</b>/hari biar aman")

                # ── Discipline: consistency of logging ─────────────────────
                logged_days = len({t.transaction_date for t in week_txns})
                if logged_days >= 6:
                    consistency = "🔥 Konsisten banget!"
                elif logged_days >= 4:
                    consistency = "👍 Lumayan rajin."
                elif logged_days >= 1:
                    consistency = "💪 Yuk lebih sering nyatat."
                else:
                    consistency = "😴 Minggu ini sepi catatan."
                lines.append(f"─────────────────")
                lines.append(f"🗓️ Kamu mencatat <b>{logged_days}/7 hari</b> minggu ini. {consistency}")
                try:
                    from app.services.streak import get_streak
                    s = await get_streak(db, user.id, getattr(user, "timezone", None))
                    if s.current_streak >= 2:
                        lines.append(f"🔥 Streak aktif <b>{s.current_streak} hari</b> · rekor {s.longest_streak} hari")
                    elif s.longest_streak >= 2:
                        lines.append(f"💤 Streak putus · rekormu {s.longest_streak} hari. Mulai lagi yuk!")
                except Exception:
                    pass

                if user.telegram_id and bot:
                    await bot.send_message(
                        chat_id=int(user.telegram_id),
                        text="\n".join(lines),
                        parse_mode="HTML",
                    )
                    logger.info(f"Weekly summary sent to TG {user.telegram_id}")

            except Exception as e:
                logger.error(f"Failed weekly summary for user {user.id}: {e}")
