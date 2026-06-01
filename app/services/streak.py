"""Discipline framework — input-consistency streak tracking.

A user keeps their streak alive by *showing up* each day: either recording a
transaction or explicitly marking the day as no-spending. This rewards the
habit of logging, which is what keeps Jatahku's data (and therefore its
budgeting) accurate.

The single entry point is `record_activity()`, called from every place a
transaction is committed (web API + Telegram bot) and from the check-in
"no spending today" button.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User, UserStreak

logger = logging.getLogger("jatahku.streak")

# Milestones worth celebrating in chat.
MILESTONES = {3, 7, 14, 30, 50, 100, 150, 200, 365}


@dataclass
class StreakResult:
    current_streak: int
    longest_streak: int
    total_logged_days: int
    # True only when this call advanced the streak to a new day (not a repeat
    # log on a day already counted). Callers use this to decide whether to show
    # a streak line at all.
    advanced: bool = False
    # The milestone reached on this call, if any (e.g. 7), else None.
    milestone: int | None = None


def user_today(tz_str: str | None) -> date:
    """Today's date in the user's local timezone."""
    try:
        tz = ZoneInfo(tz_str or "Asia/Jakarta")
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    return datetime.now(_tz.utc).astimezone(tz).date()


async def record_activity(
    db: AsyncSession, user_id, tz_str: str | None
) -> StreakResult:
    """Register that the user logged activity today; update their streak.

    Idempotent within a day: logging twice on the same local date advances the
    streak only once. Commits the streak row itself so callers don't have to.
    """
    today = user_today(tz_str)

    streak = await db.get(UserStreak, user_id)
    if streak is None:
        # Set counters explicitly — Python-side column defaults aren't applied
        # until flush, so reading them before that would yield None.
        streak = UserStreak(
            user_id=user_id,
            current_streak=0,
            longest_streak=0,
            total_logged_days=0,
        )
        db.add(streak)

    if streak.last_log_date == today:
        # Already counted today — nothing changes.
        await db.commit()
        return StreakResult(
            current_streak=streak.current_streak,
            longest_streak=streak.longest_streak,
            total_logged_days=streak.total_logged_days,
            advanced=False,
        )

    if streak.last_log_date == today - timedelta(days=1):
        streak.current_streak += 1
    else:
        # First ever log, or a gap broke the chain — start fresh at 1.
        streak.current_streak = 1

    streak.last_log_date = today
    streak.total_logged_days += 1
    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak

    milestone = streak.current_streak if streak.current_streak in MILESTONES else None

    result = StreakResult(
        current_streak=streak.current_streak,
        longest_streak=streak.longest_streak,
        total_logged_days=streak.total_logged_days,
        advanced=True,
        milestone=milestone,
    )

    # Surface milestones in the web notification bell (persisted, dedup'd by the
    # once-per-day advance guard above so it can't fire twice for the same day).
    if milestone:
        try:
            from app.models.models import Notification, NotificationType
            db.add(Notification(
                user_id=user_id,
                type=NotificationType.system,
                title="🔥 Streak milestone!",
                message=milestone_message(result),
                link="/",
            ))
        except Exception:
            pass

    await db.commit()
    return result


async def get_streak(db: AsyncSession, user_id, tz_str: str | None) -> StreakResult:
    """Read current streak without mutating it.

    If the user has missed a day (last log is older than yesterday), the stored
    `current_streak` is stale — report it as broken (0) without writing, so a
    read never has side effects.
    """
    streak = await db.get(UserStreak, user_id)
    if streak is None:
        return StreakResult(0, 0, 0)

    today = user_today(tz_str)
    current = streak.current_streak
    if streak.last_log_date is not None and streak.last_log_date < today - timedelta(days=1):
        current = 0
    return StreakResult(
        current_streak=current,
        longest_streak=streak.longest_streak,
        total_logged_days=streak.total_logged_days,
    )


def milestone_message(result: StreakResult) -> str:
    """A short celebratory line for a milestone, or '' if not a milestone."""
    m = result.milestone
    if not m:
        return ""
    labels = {
        3: "3 hari berturut-turut! Kebiasaan baik dimulai 🌱",
        7: "Seminggu penuh disiplin! 🔥",
        14: "2 minggu konsisten — keren! 💪",
        30: "Sebulan penuh nyatat! Kamu serius soal duit 🏆",
        50: "50 hari! Luar biasa 🌟",
        100: "100 hari!! Kamu legend 👑",
        150: "150 hari konsisten 🚀",
        200: "200 hari! Disiplin level dewa 🧘",
        365: "SATU TAHUN PENUH 🎉🎉 Hormat setinggi-tingginya!",
    }
    return labels.get(m, f"{m} hari berturut-turut! 🔥")
