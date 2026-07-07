from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal


def _payday(user) -> int:
    return getattr(user, "payday_day", 1) or 1


async def _get_household_id(user, db):
    from sqlalchemy import select
    from app.models.models import HouseholdMember

    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _load_visible_envelopes(user, household_id, db):
    from sqlalchemy import or_, select
    from app.models.models import Envelope

    result = await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == household_id,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    return result.scalars().all()


# ── Pure period-bucketing helpers (unit-tested; no DB) ──
def _period_index(d: date, periods: list[tuple[date, date]]):
    for i, (ps, pe) in enumerate(periods):
        if ps <= d <= pe:
            return i
    return None


def _sum_by_period(rows, periods) -> list[Decimal]:
    """rows: iterable of (date, amount). Returns Decimal sum per period index."""
    sums = [Decimal("0") for _ in periods]
    for d, amount in rows:
        idx = _period_index(d, periods)
        if idx is not None:
            sums[idx] += _to_decimal(amount)
    return sums


def _count_by_period(dates, periods) -> list[int]:
    counts = [0 for _ in periods]
    for d in dates:
        idx = _period_index(d, periods)
        if idx is not None:
            counts[idx] += 1
    return counts


def _monthly_reserve(amount, frequency) -> Decimal:
    """Monthly-equivalent reserve for a recurring transaction frequency."""
    if frequency == "weekly":
        return _to_decimal(amount) * Decimal("52") / 12
    if frequency == "yearly":
        return _to_decimal(amount) / 12
    return _to_decimal(amount)


async def envelope_lifetime_balance(envelope_id, db) -> Decimal:
    """Canonical all-time accumulated balance of an envelope:
    sum(allocations) - sum(non-deleted transactions), independent of period or
    rollover snapshots. Single source of truth for savings goal progress so the
    Goals page, advisor, and dashboard cards always agree."""
    from sqlalchemy import func, select
    from app.models.models import Allocation, Transaction

    alloc = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.envelope_id == envelope_id
        )
    )
    spent = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == envelope_id,
            Transaction.is_deleted == False,
        )
    )
    return _to_decimal(alloc.scalar()) - _to_decimal(spent.scalar())


async def load_advisor_context(user, db, periods_count: int = 6) -> dict:
    from app.core.period import get_last_n_periods

    household_id = await _get_household_id(user, db)
    if not household_id:
        return {
            "household_id": None, "periods": [], "envelopes": [], "stats": {},
            "current_txns_by_env": {}, "recurring_by_env": {},
        }

    payday_day = _payday(user)
    periods = get_last_n_periods(payday_day, periods_count)
    envelopes = await _load_visible_envelopes(user, household_id, db)
    stats = {}
    if not envelopes or not periods:
        return {
            "household_id": household_id,
            "payday_day": payday_day,
            "periods": periods,
            "envelopes": envelopes,
            "stats": stats,
            "current_txns_by_env": {},
            "recurring_by_env": {},
        }

    # Batched fetches — a fixed handful of queries regardless of envelope/period
    # count (was O(envelopes x periods x 4) sequential round-trips before).
    from collections import defaultdict
    from sqlalchemy import select
    from app.core.period import get_previous_period
    from app.models.models import (
        Allocation, Income, Transaction, RecurringTransaction, MonthlySnapshot,
    )

    env_ids = [e.id for e in envelopes]
    range_start = periods[0][0]
    range_end = periods[-1][1]

    alloc_rows = (await db.execute(
        select(Allocation.envelope_id, Income.income_date, Allocation.amount)
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id.in_(env_ids),
            Income.income_date >= range_start,
            Income.income_date <= range_end,
        )
    )).all()
    alloc_by_env = defaultdict(list)
    for env_id, income_date, amount in alloc_rows:
        alloc_by_env[str(env_id)].append((income_date, amount))

    from types import SimpleNamespace
    from app.services.visibility import masked_description

    current_start, current_end = periods[-1]
    txn_rows = (await db.execute(
        select(
            Transaction.envelope_id, Transaction.transaction_date, Transaction.amount,
            Transaction.description, Transaction.user_id, Transaction.is_private,
        )
        .where(
            Transaction.envelope_id.in_(env_ids),
            Transaction.is_deleted == False,
            Transaction.transaction_date >= range_start,
            Transaction.transaction_date <= range_end,
        )
    )).all()
    txn_by_env = defaultdict(list)          # (date, amount) for period bucketing (unchanged use)
    current_txns_by_env = defaultdict(list)  # masked views, current period only
    for env_id, txn_date, amount, description, txn_user_id, is_private in txn_rows:
        eid = str(env_id)
        txn_by_env[eid].append((txn_date, amount))
        if current_start <= txn_date <= current_end:
            masked = masked_description(
                getattr(user, "id", None),
                SimpleNamespace(user_id=txn_user_id, is_private=is_private, description=description),
            )
            current_txns_by_env[eid].append(
                SimpleNamespace(amount=_to_decimal(amount), transaction_date=txn_date, description=masked)
            )

    rec_rows = (await db.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.envelope_id.in_(env_ids),
            RecurringTransaction.is_active == True,
        )
    )).scalars().all()
    reserved_by_env = defaultdict(lambda: Decimal("0"))
    recurring_by_env = defaultdict(list)
    for rec in rec_rows:
        reserved_by_env[str(rec.envelope_id)] += _monthly_reserve(rec.amount, rec.frequency)
        freq = rec.frequency.value if hasattr(rec.frequency, "value") else str(rec.frequency)
        recurring_by_env[str(rec.envelope_id)].append(
            {"amount": _to_decimal(rec.amount), "frequency": freq, "norm": ""}
        )

    # Each period's rollover comes from the PREVIOUS period's snapshot (year/month).
    prev_keys = [get_previous_period(payday_day, ps)[0] for ps, _ in periods]
    snap_rows = (await db.execute(
        select(MonthlySnapshot).where(MonthlySnapshot.envelope_id.in_(env_ids))
    )).scalars().all()
    snap_map = {}
    for s in snap_rows:
        snap_map[(str(s.envelope_id), s.year, s.month)] = (
            _to_decimal(s.rollover_amount) if s.rollover_amount else Decimal("0")
        )

    for envelope in envelopes:
        eid = str(envelope.id)
        alloc_sums = _sum_by_period(alloc_by_env.get(eid, []), periods)
        spent_pairs = txn_by_env.get(eid, [])
        spent_sums = _sum_by_period(spent_pairs, periods)
        counts = _count_by_period([d for d, _ in spent_pairs], periods)
        reserved = reserved_by_env.get(eid, Decimal("0"))

        envelope_stats = []
        for i, (period_start, period_end) in enumerate(periods):
            if envelope.is_rollover:
                prev = prev_keys[i]
                rollover = snap_map.get((eid, prev.year, prev.month), Decimal("0"))
            else:
                rollover = Decimal("0")
            envelope_stats.append({
                "period_start": period_start,
                "period_end": period_end,
                "allocated": alloc_sums[i],
                "spent": spent_sums[i],
                "transaction_count": counts[i],
                "rollover": rollover,
                "reserved": reserved,
            })
        stats[eid] = envelope_stats

    return {
        "household_id": household_id,
        "payday_day": payday_day,
        "periods": periods,
        "envelopes": envelopes,
        "stats": stats,
        "current_txns_by_env": dict(current_txns_by_env),
        "recurring_by_env": dict(recurring_by_env),
    }
