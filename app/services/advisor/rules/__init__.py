"""Advisor rules package — insight/card computation.

Plan B1 Task 7 moved `build_advisor_insights` (async loader) and
`compute_insight_cards` (pure) here from core.py. Task 8 decomposed the
monolithic card logic into per-rule modules (depletion, subscription, drift,
goals, overspend); `compute_insight_cards` is now a thin registry that builds
the shared `AdvisorContext`, runs each `evaluate_*`, then sorts and slices.

Plan B2 Task 12 wraps each evaluator with per-rule error isolation: one
failing rule logs an ERROR and is skipped (result marked `partial` with the
failed rule id recorded) instead of blanking the whole advisor. In test/dev
mode (`_fail_fast()`), the exception is re-raised instead so bugs surface in
CI rather than being silently swallowed."""
import logging
import os
import sys
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

logger = logging.getLogger(__name__)

# (rule_id, evaluator attribute name) — rule_id matches the card "type" for
# observability. The evaluator is looked up by name in this module's globals
# at CALL time (not captured here) so tests can `patch()` the module-level
# name (e.g. `app.services.advisor.rules.evaluate_drift`) and have the
# registry honor the patch. Order matches the original evaluation order
# (depletion, subscription, drift, goals, overspend) — preserved even though
# the final sort key is a total order, for observability/debugging parity.
_RULE_REGISTRY = [
    ("env_depletion", "evaluate_depletion"),
    ("subscription_pressure", "evaluate_subscription"),
    ("allocation_drift", "evaluate_drift"),
    ("goal_progress", "evaluate_goals"),
    ("budget_overspend", "evaluate_overspend"),
]


def _fail_fast() -> bool:
    """Whether a failing rule should re-raise instead of being isolated.

    `ADVISOR_FAIL_FAST` env var wins when set ("1" -> fail-fast, "0" ->
    isolate). When unset, default to fail-fast under unittest (so bugs
    surface in CI/tests) and to isolation otherwise (production)."""
    flag = os.environ.get("ADVISOR_FAIL_FAST")
    if flag is not None:
        return flag == "1"
    return "unittest" in sys.modules


async def build_advisor_insights(user, db) -> dict:
    from app.core.period import get_period_info

    context = await load_advisor_context(user, db)
    envelopes = context.get("envelopes", [])
    stats = context.get("stats", {})
    if not envelopes:
        return {"cards": [], "dashboard_cards": [], "partial": False, "failed_rules": []}

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

    txns_by_env = context.get("current_txns_by_env", {})
    recurring_by_env = context.get("recurring_by_env", {})
    return compute_insight_cards(
        envelopes, stats, period_info, goals_by_env, balances_by_env,
        txns_by_env, recurring_by_env,
    )


def compute_insight_cards(envelopes, stats, period_info, goals_by_env, balances_by_env,
                          txns_by_env=None, recurring_by_env=None) -> dict:
    """Pure card computation — no DB access, no await. All inputs are
    pre-loaded by build_advisor_insights (or synthesized by tests).

    Registry: build the shared context, run every per-rule evaluator, then
    sort all emitted cards by (severity_rank, id) and take the top 3 for the
    dashboard. Card append order is irrelevant to the final result — the sort
    key is a total order (ids are unique) — but is preserved for parity with
    the original evaluation order.

    One failing rule must not blank the whole advisor: each evaluator runs
    in isolation (see `_RULE_REGISTRY` / `_fail_fast`). A failure is logged
    and skipped, and recorded in the returned `failed_rules` (with `partial`
    set True) — unless `_fail_fast()` is True, in which case it re-raises."""
    ctx = AdvisorContext(
        envelopes=envelopes,
        stats=stats,
        period_info=period_info,
        goals_by_env=goals_by_env,
        balances_by_env=balances_by_env,
        txns_by_env=txns_by_env or {},
        recurring_by_env=recurring_by_env or {},
    )

    module_globals = sys.modules[__name__].__dict__
    cards = []
    failed_rules = []
    for rule_id, evaluator_name in _RULE_REGISTRY:
        evaluator = module_globals[evaluator_name]
        try:
            cards.extend(evaluator(ctx))
        except Exception:
            if _fail_fast():
                raise
            logger.error("advisor rule %s failed", rule_id, exc_info=True)
            failed_rules.append(rule_id)

    cards = sorted(cards, key=lambda item: (_severity_rank(item["severity"]), item["id"]))
    return {
        "period_start": str(period_info["period_start"]),
        "period_end": str(period_info["period_end"]),
        "cards": cards,
        "dashboard_cards": cards[:3],
        "partial": bool(failed_rules),
        "failed_rules": failed_rules,
    }
