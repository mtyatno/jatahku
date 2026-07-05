"""Advisor rules package — insight/card computation.

Plan B1 Task 7 moved `build_advisor_insights` (async loader) and
`compute_insight_cards` (pure) here verbatim from core.py. Task 8 will
decompose `compute_insight_cards` into per-rule modules; for now it stays
monolithic — this task only relocates it."""
from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import (
    _to_decimal, _fmt_rp, _fmt_months, _median_decimal, _card, _severity_rank,
)
from app.services.advisor.context import (
    _payday, load_advisor_context, envelope_lifetime_balance,
)
from app.services.advisor.rules._base import AdvisorContext, _MIN_PROJECTION_DAYS
from app.services.advisor.rules.depletion import evaluate_depletion
from app.services.advisor.rules.subscription import evaluate_subscription
from app.services.advisor.rules.drift import evaluate_drift
from app.services.advisor.rules.goals import evaluate_goals


async def build_advisor_insights(user, db) -> dict:
    from app.core.period import get_period_info

    context = await load_advisor_context(user, db)
    envelopes = context.get("envelopes", [])
    stats = context.get("stats", {})
    if not envelopes:
        return {"cards": [], "dashboard_cards": []}

    period_info = get_period_info(context.get("payday_day", _payday(user)), date.today())

    # Load goals for saving/sinking_fund envelopes
    from sqlalchemy import select
    from app.models.models import Goal
    goal_result = await db.execute(
        select(Goal).where(Goal.envelope_id.in_([e.id for e in envelopes]))
    )
    goals_by_env = {}
    for g in goal_result.scalars().all():
        goals_by_env[str(g.envelope_id)] = g

    # Load lifetime balances for saving/sinking_fund envelopes that have a
    # goal — mirrors exactly which envelopes compute_insight_cards will need
    # a balance for (same skip-if-no-stats guard as the card loop below).
    balances_by_env: dict[str, Decimal] = {}
    for envelope in envelopes:
        envelope_stats = stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")
        goal = goals_by_env.get(str(envelope.id))
        if purpose in ("saving", "sinking_fund") and goal:
            balances_by_env[str(envelope.id)] = await envelope_lifetime_balance(envelope.id, db)

    return compute_insight_cards(envelopes, stats, period_info, goals_by_env, balances_by_env)


def compute_insight_cards(envelopes, stats, period_info, goals_by_env, balances_by_env) -> dict:
    """Pure card computation — no DB access, no await. All inputs are
    pre-loaded by build_advisor_insights (or synthesized by tests)."""
    days_used = max(period_info["days_used"], 1)
    days_total = max(period_info["days_total"], 1)
    days_remaining = max(period_info["days_remaining"], 0)

    ctx = AdvisorContext(
        envelopes=envelopes,
        stats=stats,
        period_info=period_info,
        goals_by_env=goals_by_env,
        balances_by_env=balances_by_env,
    )

    cards = []
    cards += evaluate_depletion(ctx)
    cards += evaluate_subscription(ctx)
    cards += evaluate_drift(ctx)
    cards += evaluate_goals(ctx)
    total_reserved = Decimal("0")
    expense_allocated = Decimal("0")
    expense_spent = Decimal("0")

    for envelope in envelopes:
        envelope_stats = stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        reserved = _to_decimal(current.get("reserved"))
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

        total_reserved += reserved
        if purpose == "expense":
            expense_allocated += allocated
            expense_spent += spent

    # Global overspend — expense envelopes only (savings/sinking inflate
    # allocated and aren't "spent", which would mask the signal). Matches the
    # expense-only basis of /analytics/prediction and the "Sisa bebas" KPI.
    if expense_allocated > 0 and days_used >= _MIN_PROJECTION_DAYS:
        projected_total = (expense_spent / days_used) * days_total
        if projected_total > expense_allocated:
            shortage = projected_total - expense_allocated
            cards.append(_card(
                "budget_overspend:current",
                "budget_overspend",
                "danger",
                "Budget periode ini berisiko jebol",
                f"Proyeksi overspend sekitar Rp{_fmt_rp(shortage)} sampai gajian berikutnya.",
                "/analytics",
                [
                    f"Terpakai Rp{_fmt_rp(expense_spent)} dari Rp{_fmt_rp(expense_allocated)}",
                    f"Reserve rutin Rp{_fmt_rp(total_reserved)}",
                ],
            ))

    cards = sorted(cards, key=lambda item: (_severity_rank(item["severity"]), item["id"]))
    return {
        "period_start": str(period_info["period_start"]),
        "period_end": str(period_info["period_end"]),
        "cards": cards,
        "dashboard_cards": cards[:3],
    }
