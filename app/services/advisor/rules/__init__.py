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
    total_allocated = Decimal("0")
    total_spent = Decimal("0")
    total_reserved = Decimal("0")
    total_free = Decimal("0")
    expense_allocated = Decimal("0")
    expense_spent = Decimal("0")
    sinking_under_funded = False

    saving_items = []
    sinking_items = []

    for envelope in envelopes:
        envelope_stats = stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        rollover = _to_decimal(current.get("rollover"))
        reserved = _to_decimal(current.get("reserved"))
        available = allocated + rollover
        remaining = available - spent
        free = remaining - reserved
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

        total_allocated += allocated
        total_spent += spent
        total_reserved += reserved
        total_free += free
        if purpose == "expense":
            expense_allocated += allocated
            expense_spent += spent

        # Saving: collect item for consolidated card
        goal = goals_by_env.get(str(envelope.id))
        if purpose in ("saving", "sinking_fund") and goal:
            balance = balances_by_env.get(str(envelope.id), Decimal("0"))
            target = _to_decimal(goal.target_amount)
            pct = min(round(float(balance / target) * 100, 1) if target > 0 else 0, 100)

            if purpose == "saving":
                hist_allocations = [
                    _to_decimal(row.get("allocated"))
                    for row in envelope_stats[:-1]
                    if _to_decimal(row.get("allocated")) > 0
                ]
                avg_contribution = _median_decimal(hist_allocations) if hist_allocations else allocated
                if avg_contribution <= 0:
                    avg_contribution = allocated if allocated > 0 else Decimal("1")
                months_to_goal = (target - balance) / avg_contribution if target > balance else 0
                months_to_goal = max(1, round(float(months_to_goal)))
                capped = months_to_goal > 120

                line = f"{envelope.emoji} {goal.name}: {int(pct)}% (Rp{_fmt_rp(balance)} / Rp{_fmt_rp(target)})"
                if allocated <= 0 and not hist_allocations:
                    line += " — belum ada setoran"
                elif capped:
                    line += f" — setoran Rp{_fmt_rp(avg_contribution)}/bln terlalu kecil, estimasi >10 tahun"
                else:
                    line += f" — estimasi {_fmt_months(months_to_goal)} (Rp{_fmt_rp(avg_contribution)}/bln)"
                saving_items.append(line)

            elif purpose == "sinking_fund":
                today = date.today()
                if goal.target_date and goal.target_date > today:
                    months_remaining = max(1, (goal.target_date.year - today.year) * 12 + goal.target_date.month - today.month)
                    monthly_needed = max(Decimal("0"), target - balance) / months_remaining
                    if allocated >= monthly_needed:
                        line = f"✅ {envelope.emoji} {goal.name}: {int(pct)}% — on track ({_fmt_months(months_remaining)})"
                    elif allocated > 0:
                        sinking_under_funded = True
                        line = f"⚠️ {envelope.emoji} {goal.name}: {int(pct)}% — butuh Rp{_fmt_rp(monthly_needed)}/bln (baru Rp{_fmt_rp(allocated)})"
                    else:
                        line = f"📅 {envelope.emoji} {goal.name}: {int(pct)}% — {_fmt_months(months_remaining)}, perlu Rp{_fmt_rp(monthly_needed)}/bln"
                else:
                    line = f"📅 {envelope.emoji} {goal.name}: {int(pct)}% (Rp{_fmt_rp(balance)} / Rp{_fmt_rp(target)})"
                sinking_items.append(line)

        if reserved > 0 and free < reserved * Decimal("0.25"):
            cards.append(_card(
                f"subscription_pressure:{envelope.id}",
                "subscription_pressure",
                "warning",
                f"Reserve rutin menekan amplop {envelope.name}",
                f"Dana bebas setelah reserve tinggal Rp{_fmt_rp(free)}.",
                "/langganan",
                [
                    f"Reserve rutin Rp{_fmt_rp(reserved)}",
                    f"Sisa sebelum reserve Rp{_fmt_rp(remaining)}",
                ],
            ))

        historical_spends = [
            _to_decimal(row.get("spent"))
            for row in envelope_stats[:-1]
            if _to_decimal(row.get("spent")) > 0
        ]
        historical_median = _median_decimal(historical_spends)
        budget_target = _to_decimal(getattr(envelope, "budget_amount", 0))
        if purpose == "expense" and budget_target > 0 and historical_median > budget_target * Decimal("1.15"):
            cards.append(_card(
                f"allocation_drift:{envelope.id}",
                "allocation_drift",
                "info",
                f"Target {envelope.name} lebih rendah dari pola aktual",
                f"Median historis Rp{_fmt_rp(historical_median)}, target sekarang Rp{_fmt_rp(budget_target)}.",
                "/allocate",
                ["Pola ini bisa membuat amplop cepat menipis."],
            ))

    # Consolidated goals card
    if saving_items or sinking_items:
        body_parts = []
        if saving_items:
            body_parts.append("🎯 Progress tabungan:")
            body_parts.extend(f"  • {item}" for item in saving_items)
        if sinking_items:
            if body_parts:
                body_parts.append("")
            body_parts.append("📅 Dana persiapan:")
            body_parts.extend(f"  • {item}" for item in sinking_items)
        severity = "warning" if sinking_under_funded else "info"
        cards.append(_card(
            "goals:consolidated",
            "goal_progress",
            severity,
            "Target menabung & dana persiapan",
            "\n".join(body_parts),
            "/envelopes",
            ["Buka halaman amplop untuk detail dan edit target."],
        ))

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
