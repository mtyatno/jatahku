from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _money, _fmt_rp, _median_decimal
from app.services.advisor.context import load_advisor_context
from app.services.advisor.sinking import normalize_description, _ESSENTIAL_KEYWORDS
from app.services.advisor.confidence import assess_confidence


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
            "confidence_reasons": ["Belum ada amplop aktif untuk direkomendasikan."],
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
            "purpose": str(getattr(envelope, "purpose", "expense") or "expense"),
            "recommended_amount": _money(item["recommended_amount"]),
            "minimum_amount": _money(item["minimum"]),
            "target_amount": _money(item["target"]),
            "historical_average": _money(meta["historical_average"]),
            "recurring_reserve": _money(meta["recurring_reserve"]),
            "current_rollover": _money(meta["current_rollover"]),
            "risk_level": meta["risk_level"],
            "reasons": meta["reasons"],
        })

    # Aggregate spend per historical period (all-but-last per envelope), aligned
    # by period index; each envelope's stats list is period-aligned oldest-first.
    period_totals: dict[int, Decimal] = {}
    for envelope_stats in stats.values():
        for idx, row in enumerate(envelope_stats[:-1]):
            period_totals[idx] = period_totals.get(idx, Decimal("0")) + _to_decimal(row.get("spent"))
    confidence_model = assess_confidence(list(period_totals.values()))
    confidence = confidence_model["level"]

    return {
        "income_amount": _money(income_amount),
        "total_recommended": _money(allocation["total_recommended"]),
        "unallocated": _money(allocation["unallocated"]),
        "confidence": confidence,
        "confidence_reasons": confidence_model["reasons"],
        "method": "obligations_then_historical_median",
        "items": response_items,
        "warnings": allocation["warnings"],
    }
