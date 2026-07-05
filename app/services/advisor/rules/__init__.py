"""Advisor rules package — insight/card computation.

Plan B1 Task 7 moved `build_advisor_insights` (async loader) and
`compute_insight_cards` (pure) here from core.py. Task 8 decomposed the
monolithic card logic into per-rule modules (depletion, subscription, drift,
goals, overspend); `compute_insight_cards` is now a thin registry that builds
the shared `AdvisorContext`, runs each `evaluate_*`, then sorts and slices."""
from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import _severity_rank
from app.services.advisor.context import (
    _payday, load_advisor_context, envelope_lifetime_balance,
)
from app.services.advisor.rules._base import AdvisorContext
from app.services.advisor.rules.depletion import evaluate_depletion
from app.services.advisor.rules.subscription import evaluate_subscription
from app.services.advisor.rules.drift import evaluate_drift
from app.services.advisor.rules.goals import evaluate_goals
from app.services.advisor.rules.overspend import evaluate_overspend


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
    pre-loaded by build_advisor_insights (or synthesized by tests).

    Registry: build the shared context, run every per-rule evaluator, then
    sort all emitted cards by (severity_rank, id) and take the top 3 for the
    dashboard. Card append order is irrelevant — the sort key is a total
    order (ids are unique)."""
    ctx = AdvisorContext(
        envelopes=envelopes,
        stats=stats,
        period_info=period_info,
        goals_by_env=goals_by_env,
        balances_by_env=balances_by_env,
    )

    cards = (
        evaluate_depletion(ctx)
        + evaluate_subscription(ctx)
        + evaluate_drift(ctx)
        + evaluate_goals(ctx)
        + evaluate_overspend(ctx)
    )

    cards = sorted(cards, key=lambda item: (_severity_rank(item["severity"]), item["id"]))
    return {
        "period_start": str(period_info["period_start"]),
        "period_end": str(period_info["period_end"]),
        "cards": cards,
        "dashboard_cards": cards[:3],
    }
