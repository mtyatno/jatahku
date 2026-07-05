import logging
from decimal import Decimal

from app.services.advisor.formatting import (
    _to_decimal, _money, _fmt_rp, _fmt_months, _median_decimal, _card, _severity_rank,
)
from app.services.advisor.context import (
    _payday, _get_household_id, _load_visible_envelopes, _period_index,
    _sum_by_period, _count_by_period, _monthly_reserve,
    load_advisor_context, envelope_lifetime_balance,
)
from app.services.advisor.sinking import (
    normalize_description, detect_interval, _token_overlap, _frequency_monthly_reserve,
    _next_expected_date, _amount_stability, select_visible_samples, _sinking_group_id,
    build_sinking_fund_advice, _ESSENTIAL_KEYWORDS,
)

logger = logging.getLogger("jatahku.advisor")

# Don't project depletion/overspend before this many days into the period —
# early-period spend rates are too volatile and produce false alarms.
_MIN_PROJECTION_DAYS = 3


def _is_saving_sink(item) -> bool:
    """Pure-savings envelope that receives leftover income — purpose 'saving'
    (or the legacy 'Tabungan' name as fallback)."""
    if str(item.get("purpose") or "") == "saving":
        return True
    return str(item.get("name", "")).lower() == "tabungan"


def allocate_income_to_targets(income_amount: Decimal, envelopes: list[dict]) -> dict:
    remaining_income = _to_decimal(income_amount)
    items = []
    warnings = []

    for envelope in envelopes:
        items.append({
            **envelope,
            "minimum": _to_decimal(envelope.get("minimum")),
            "target": _to_decimal(envelope.get("target")),
            "recommended_amount": Decimal("0"),
        })

    allocatable_items = [item for item in items if not item.get("is_locked")]
    sorted_items = sorted(allocatable_items, key=lambda item: item.get("priority", 50))
    total_minimum = sum((item["minimum"] for item in sorted_items), Decimal("0"))

    for item in sorted_items:
        minimum_amount = max(item["minimum"], Decimal("0"))
        if minimum_amount <= 0 or remaining_income <= 0:
            continue
        amount = min(minimum_amount, remaining_income)
        item["recommended_amount"] += amount
        remaining_income -= amount

    if income_amount < total_minimum:
        warnings.append("Income tidak cukup untuk memenuhi semua minimum.")

    target_items = sorted(sorted_items, key=lambda item: (item["minimum"] > 0, item.get("priority", 50)))
    for item in target_items:
        if _is_saving_sink(item) or remaining_income <= 0:
            continue
        target_gap = max(item["target"] - item["recommended_amount"], Decimal("0"))
        if target_gap <= 0:
            continue
        amount = min(target_gap, remaining_income)
        item["recommended_amount"] += amount
        remaining_income -= amount

    sink = next((item for item in items if _is_saving_sink(item)), None)
    if sink and remaining_income > 0:
        sink["recommended_amount"] += remaining_income
        remaining_income = Decimal("0")

    return {
        "items": items,
        "total_recommended": sum((item["recommended_amount"] for item in items), Decimal("0")),
        "unallocated": remaining_income,
        "warnings": warnings,
    }


def build_allocation_distribution(rows, total_income) -> dict:
    """Group per-envelope net allocations into named categories with percentages.

    rows: list of (category_name, net_amount). Categories with equal names are
    summed. Non-positive categories are dropped. Percentages are of total_income.
    """
    total = _to_decimal(total_income)
    merged: dict[str, Decimal] = {}
    for name, amount in rows:
        merged[name] = merged.get(name, Decimal("0")) + _to_decimal(amount)

    positive = {k: v for k, v in merged.items() if v > 0}
    allocated_total = sum(positive.values(), Decimal("0"))

    def pct(v: Decimal) -> int:
        return int(round(float(v) / float(total) * 100)) if total > 0 else 0

    distribution = [
        {"category": name, "amount": float(amount), "pct": pct(amount)}
        for name, amount in sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
    ]
    saving_amount = positive.get("Tabungan", Decimal("0")) + positive.get("Sinking Fund", Decimal("0"))
    return {
        "distribution": distribution,
        "allocated_pct": pct(allocated_total),
        "saving_amount": float(saving_amount),
        "saving_pct": pct(saving_amount),
    }


async def build_advisor_insights(user, db) -> dict:
    from datetime import date
    from app.core.period import get_period_info

    context = await load_advisor_context(user, db)
    envelopes = context.get("envelopes", [])
    stats = context.get("stats", {})
    if not envelopes:
        return {"cards": [], "dashboard_cards": []}

    period_info = get_period_info(context.get("payday_day", _payday(user)), date.today())
    days_used = max(period_info["days_used"], 1)
    days_total = max(period_info["days_total"], 1)
    days_remaining = max(period_info["days_remaining"], 0)

    cards = []
    total_allocated = Decimal("0")
    total_spent = Decimal("0")
    total_reserved = Decimal("0")
    total_free = Decimal("0")
    expense_allocated = Decimal("0")
    expense_spent = Decimal("0")
    sinking_under_funded = False

    # Load goals for saving/sinking_fund envelopes
    from sqlalchemy import select
    from app.models.models import Goal
    goal_result = await db.execute(
        select(Goal).where(Goal.envelope_id.in_([e.id for e in envelopes]))
    )
    goals_by_env = {}
    for g in goal_result.scalars().all():
        goals_by_env[str(g.envelope_id)] = g

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

        if available > 0 and spent > 0 and purpose == "expense" and days_used >= _MIN_PROJECTION_DAYS:
            projected = (spent / days_used) * days_total
            if projected > available and days_remaining > 0:
                pct = int(spent / available * 100)
                shortage = projected - available
                daily_rate = spent / days_used
                cards.append(_card(
                    f"env_depletion:{envelope.id}",
                    "env_depletion",
                    "danger" if shortage > available * Decimal("0.2") else "warning",
                    f"{envelope.emoji} {envelope.name} sudah terpakai {pct}%",
                    f"Masih {days_remaining} hari. Proyeksi habis {max(1, int(shortage / daily_rate))} hari sebelum periode selesai.",
                    "/allocate",
                    [
                        f"Terpakai Rp{_fmt_rp(spent)} dari Rp{_fmt_rp(available)}",
                        f"Rata-rata Rp{_fmt_rp(daily_rate)}/hari",
                    ],
                ))

        # Saving: collect item for consolidated card
        goal = goals_by_env.get(str(envelope.id))
        if purpose in ("saving", "sinking_fund") and goal:
            balance = await envelope_lifetime_balance(envelope.id, db)
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


def _is_essential_envelope(name: str) -> bool:
    normalized = normalize_description(name)
    return bool(set(normalized.split()) & _ESSENTIAL_KEYWORDS)


def _allocation_priority(name: str, minimum: Decimal, essential: bool, purpose: str = "expense") -> int:
    if purpose == "saving" or name.lower() == "tabungan":
        return 90
    if minimum > 0:
        return 10
    if essential:
        return 20
    return 40


async def build_allocation_recommendation(user, income_amount: Decimal, db) -> dict:
    context = await load_advisor_context(user, db)
    envelopes = context.get("envelopes", [])
    stats = context.get("stats", {})

    if not envelopes:
        return {
            "income_amount": _money(income_amount),
            "total_recommended": 0,
            "unallocated": _money(income_amount),
            "confidence": "low",
            "method": "no_envelopes",
            "items": [],
            "warnings": ["Belum ada amplop aktif untuk direkomendasikan."],
        }

    allocation_inputs = []
    item_meta = {}

    for envelope in envelopes:
        envelope_stats = stats.get(str(envelope.id), [])
        current_stats = envelope_stats[-1] if envelope_stats else {}
        historical_stats = envelope_stats[:-1]
        historical_spends = [
            _to_decimal(row["spent"])
            for row in historical_stats
            if _to_decimal(row.get("spent")) > 0 or _to_decimal(row.get("allocated")) > 0
        ]
        historical_average = _median_decimal(historical_spends)
        recurring_reserve = _to_decimal(current_stats.get("reserved"))
        current_rollover = _to_decimal(current_stats.get("rollover"))
        negative_repayment = abs(current_rollover) if current_rollover < 0 else Decimal("0")
        budget_target = _to_decimal(getattr(envelope, "budget_amount", 0))
        essential = _is_essential_envelope(envelope.name)

        minimum = max(recurring_reserve, negative_repayment)
        if essential and minimum == 0 and historical_average > 0:
            minimum = historical_average * Decimal("0.6")

        target = max(budget_target, historical_average, minimum)
        env_purpose = str(getattr(envelope, "purpose", "expense") or "expense")
        priority = _allocation_priority(envelope.name, minimum, essential, env_purpose)
        reasons = []
        if recurring_reserve > 0:
            reasons.append(f"Reserve langganan sekitar Rp{_fmt_rp(recurring_reserve)}/periode")
        if negative_repayment > 0:
            reasons.append(f"Perlu menutup rollover negatif Rp{_fmt_rp(negative_repayment)}")
        if historical_average > 0:
            reasons.append(f"Median historis Rp{_fmt_rp(historical_average)}")
        if not reasons and budget_target > 0:
            reasons.append(f"Mengikuti target amplop Rp{_fmt_rp(budget_target)}")

        if recurring_reserve > target * Decimal("0.7") and target > 0:
            risk_level = "reserve_pressure"
        elif historical_average > budget_target and budget_target > 0:
            risk_level = "watch"
        else:
            risk_level = "normal"

        allocation_input = {
            "id": str(envelope.id),
            "name": envelope.name,
            "emoji": envelope.emoji,
            "minimum": minimum.quantize(Decimal("1")),
            "target": target.quantize(Decimal("1")),
            "priority": priority,
            "purpose": env_purpose,
            "is_locked": bool(getattr(envelope, "is_locked", False)),
        }
        allocation_inputs.append(allocation_input)
        item_meta[str(envelope.id)] = {
            "envelope": envelope,
            "historical_average": historical_average,
            "recurring_reserve": recurring_reserve,
            "current_rollover": current_rollover,
            "risk_level": risk_level,
            "reasons": reasons[:3],
        }

    allocation = allocate_income_to_targets(income_amount, allocation_inputs)
    response_items = []

    for item in allocation["items"]:
        meta = item_meta[item["id"]]
        envelope = meta["envelope"]
        response_items.append({
            "envelope_id": item["id"],
            "name": envelope.name,
            "emoji": envelope.emoji,
            "recommended_amount": _money(item["recommended_amount"]),
            "minimum_amount": _money(item["minimum"]),
            "target_amount": _money(item["target"]),
            "historical_average": _money(meta["historical_average"]),
            "recurring_reserve": _money(meta["recurring_reserve"]),
            "current_rollover": _money(meta["current_rollover"]),
            "risk_level": meta["risk_level"],
            "reasons": meta["reasons"],
        })

    active_history_count = sum(
        1
        for envelope_stats in stats.values()
        for row in envelope_stats[:-1]
        if _to_decimal(row.get("spent")) > 0 or _to_decimal(row.get("allocated")) > 0
    )
    confidence = "medium" if active_history_count >= 3 else "low"

    return {
        "income_amount": _money(income_amount),
        "total_recommended": _money(allocation["total_recommended"]),
        "unallocated": _money(allocation["unallocated"]),
        "confidence": confidence,
        "method": "obligations_then_historical_median",
        "items": response_items,
        "warnings": allocation["warnings"],
    }
