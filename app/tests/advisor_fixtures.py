"""Synthetic fixture builders for app.services.advisor.core.compute_insight_cards.

These build the exact shapes compute_insight_cards reads (see core.py):
- envelopes: objects with .id, .name, .emoji, .purpose, .is_rollover,
  .budget_amount, .is_locked (SimpleNamespace is enough — no DB model needed).
- stats: dict[str(env_id) -> list[dict]] — one dict per period, oldest first,
  with keys allocated/spent/transaction_count/rollover/reserved (Decimal,
  except transaction_count which is int). compute_insight_cards reads only
  the LAST entry as "current" and all-but-last as "history".
- period_info: dict with days_used/days_total/days_remaining/period_start/
  period_end — same shape as app.core.period.get_period_info().
- goals_by_env: dict[str(env_id) -> goal-like object] with .name,
  .target_amount, .target_date.
- balances_by_env: dict[str(env_id) -> Decimal] lifetime balance per
  saving/sinking_fund envelope that has a goal.

Seed IDs are plain strings (not real UUIDs) — compute_insight_cards only ever
does str(envelope.id) / str(g.envelope_id), so plain strings round-trip fine
and make test assertions easier to read.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace


def make_envelope(
    id="env-1",
    name="Makan",
    emoji="🍔",
    purpose="expense",
    is_rollover=False,
    budget_amount=Decimal("0"),
    is_locked=False,
):
    return SimpleNamespace(
        id=id,
        name=name,
        emoji=emoji,
        purpose=purpose,
        is_rollover=is_rollover,
        budget_amount=budget_amount,
        is_locked=is_locked,
    )


def make_period_row(
    allocated=Decimal("0"),
    spent=Decimal("0"),
    transaction_count=0,
    rollover=Decimal("0"),
    reserved=Decimal("0"),
    period_start=None,
    period_end=None,
):
    """One entry in stats[env_id] — a single budget period's numbers."""
    return {
        "period_start": period_start,
        "period_end": period_end,
        "allocated": allocated,
        "spent": spent,
        "transaction_count": transaction_count,
        "rollover": rollover,
        "reserved": reserved,
    }


def make_period_info(
    days_used=15,
    days_total=30,
    days_remaining=15,
    period_start=date(2026, 1, 1),
    period_end=date(2026, 1, 30),
):
    return {
        "period_start": period_start,
        "period_end": period_end,
        "days_total": days_total,
        "days_used": days_used,
        "days_remaining": days_remaining,
    }


def make_goal(name="Dana Darurat", target_amount=Decimal("10000000"), target_date=None):
    return SimpleNamespace(name=name, target_amount=target_amount, target_date=target_date)


def build_stats(*env_id_rows_pairs):
    """build_stats((env_id, [row, row, ...]), (env_id2, [...])) -> stats dict."""
    return {env_id: rows for env_id, rows in env_id_rows_pairs}
