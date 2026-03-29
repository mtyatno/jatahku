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

    if today.day >= payday_day:
        # We're at or past payday this month — period started this month
        period_start = _safe_date(today.year, today.month, payday_day)
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
        period_end = _safe_date(today.year, today.month, payday_day) - timedelta(days=1)

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
