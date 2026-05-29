"""
Budget period gateway — single source of truth for all period calculations.

For payday_day=1: returns calendar month (backward compatible).
For payday_day=29: returns 29th of this month → 28th of next month.
"""
import calendar
from datetime import date, timedelta


def _safe_date(year: int, month: int, day: int) -> date:
    """Create date, capping day at month's last day (handles Feb 29/30/31)."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def get_budget_period(payday_day: int, today: date | None = None) -> tuple[date, date]:
    """
    Return (period_start, period_end) for the current budget period.

    Examples (payday_day=29, today=2026-03-29):
        → (2026-03-29, 2026-04-28)

    Examples (payday_day=29, today=2026-04-15):
        → (2026-03-29, 2026-04-28)

    Examples (payday_day=1, today=2026-03-15):
        → (2026-03-01, 2026-03-31)  ← same as calendar month
    """
    if today is None:
        today = date.today()
    payday_day = max(1, min(payday_day, 31))

    # This month's payday, capped to the last day of the month. Comparing against
    # this (not the raw payday_day) is essential for payday 29/30/31: in a short
    # month the capped payday can be < payday_day, so `today.day >= payday_day`
    # would wrongly skip the day(s) at month-end into a no-man's-land.
    this_month_payday = _safe_date(today.year, today.month, payday_day)

    if today >= this_month_payday:
        # We're at or past payday this month — period started this month
        period_start = this_month_payday
        if today.month == 12:
            next_year, next_month = today.year + 1, 1
        else:
            next_year, next_month = today.year, today.month + 1
        period_end = _safe_date(next_year, next_month, payday_day) - timedelta(days=1)
    else:
        # Before payday this month — period started last month
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        period_start = _safe_date(prev_year, prev_month, payday_day)
        period_end = this_month_payday - timedelta(days=1)

    return period_start, period_end


def get_previous_period(payday_day: int, today: date | None = None) -> tuple[date, date]:
    """Return (period_start, period_end) for the period before the current one."""
    if today is None:
        today = date.today()
    current_start, _ = get_budget_period(payday_day, today)
    prev_end = current_start - timedelta(days=1)
    return get_budget_period(payday_day, prev_end)


def get_last_n_periods(payday_day: int, n: int, today: date | None = None) -> list[tuple[date, date]]:
    """Return last n periods (including current), oldest first."""
    if today is None:
        today = date.today()
    periods = []
    anchor = today
    for _ in range(n):
        start, end = get_budget_period(payday_day, anchor)
        periods.append((start, end))
        anchor = start - timedelta(days=1)
    periods.reverse()
    return periods


def get_closed_periods(
    payday_day: int, today: date | None = None, max_periods: int = 12
) -> list[tuple[date, date]]:
    """Return up to `max_periods` CLOSED budget periods (oldest first).

    A period is "closed" once it no longer contains `today`. The newest closed
    period is the one ending the day before the current period starts. Used by
    the snapshot catch-up so missed snapshots can be backfilled in dependency
    order (oldest first → each period's rollover sees its predecessor)."""
    if today is None:
        today = date.today()
    current_start, _ = get_budget_period(payday_day, today)
    periods: list[tuple[date, date]] = []
    anchor = current_start - timedelta(days=1)  # last day of newest closed period
    for _ in range(max(0, max_periods)):
        start, end = get_budget_period(payday_day, anchor)
        periods.append((start, end))
        anchor = start - timedelta(days=1)
    periods.reverse()
    return periods


def payday_reminder_day_index(payday_day: int, user_today: date) -> int | None:
    """0/1/2 if user_today is within the first 3 days of the current budget
    period, else None. Drives the payday-reminder re-nudge window (day 0 =
    payday, days 1-2 = follow-up nudges)."""
    period_start, _ = get_budget_period(payday_day, user_today)
    idx = (user_today - period_start).days
    return idx if 0 <= idx <= 2 else None


def get_period_info(payday_day: int, today: date | None = None) -> dict:
    """Return period stats dict for display."""
    if today is None:
        today = date.today()
    start, end = get_budget_period(payday_day, today)
    total = (end - start).days + 1
    used = (today - start).days + 1
    remaining = (end - today).days
    return {
        "period_start": start,
        "period_end": end,
        "days_total": total,
        "days_used": max(used, 0),
        "days_remaining": max(remaining, 0),
    }
