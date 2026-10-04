"""budget_overspend rule — global projected overspend for the period.

Projects total expense spend across the period; if it exceeds total expense
allocation, emits one danger card. Expense envelopes only (savings/sinking
inflate allocated and aren't "spent", which would mask the signal). The
`expense_reserved` shown in the evidence sums reserved only for expense
envelopes, matching the story about the expense budget.
Returns 0 or 1 card."""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card
from app.services.advisor.rules._base import AdvisorContext, _MIN_PROJECTION_DAYS
from app.services.advisor.projection import project_envelope
from app.services.advisor.rules.depletion import _floor_thousand, _fmt_date
from app.services.advisor.formatting import _money


def evaluate_overspend(ctx: AdvisorContext) -> list[dict]:
    days_used = ctx.days_used
    days_total = ctx.days_total
    days_remaining = ctx.days_remaining

    expense_reserved = Decimal("0")
    expense_allocated = Decimal("0")
    expense_spent = Decimal("0")
    variable_projected_extra = Decimal("0")  # sum of variable_rate*days_remaining
    total_variable_rate = Decimal("0")
    total_variable_count = 0
    excluded_adjustment = Decimal("0")
    excluded_recurring = Decimal("0")
    excluded_outlier = Decimal("0")

    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        reserved = _to_decimal(current.get("reserved"))
        rollover = _to_decimal(current.get("rollover"))
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")
        if purpose != "expense":
            continue
        expense_allocated += allocated
        expense_spent += spent
        expense_reserved += reserved
        proj = project_envelope(
            spent, int(current.get("transaction_count") or 0), allocated + rollover,
            days_used, days_total, days_remaining,
            txns=ctx.txns_by_env.get(str(envelope.id)),
            recurring_amounts=ctx.recurring_by_env.get(str(envelope.id)),
        )
        variable_projected_extra += proj["variable_rate"] * days_remaining
        total_variable_rate += proj["variable_rate"]
        total_variable_count += proj["variable_count"]
        excluded_adjustment += proj["excluded"]["adjustment"]
        excluded_recurring += proj["excluded"]["recurring"]
        excluded_outlier += proj["excluded"]["outlier"]

    cards = []
    if expense_allocated > 0 and days_used >= _MIN_PROJECTION_DAYS:
        projected_total = expense_spent + variable_projected_extra
        if projected_total > expense_allocated:
            shortage = projected_total - expense_allocated
            # cap: thin variable sample across expense envelopes -> warning, not danger
            has_txn_data = any(ctx.txns_by_env.get(str(e.id)) for e in ctx.envelopes)
            severity = "warning" if (has_txn_data and total_variable_count < 5) else "danger"
            remaining = expense_allocated - expense_spent
            safe_daily = _floor_thousand(remaining / days_remaining) if remaining > 0 and days_remaining > 0 else Decimal("0")
            if remaining > 0:
                title = f"Semua amplop belanja: maksimal Rp{_fmt_rp(safe_daily)}/hari"
                body = (
                    f"Kalau tetap Rp{_fmt_rp(total_variable_rate)}/hari, "
                    f"total kurang sekitar Rp{_fmt_rp(shortage)} sebelum periode selesai."
                )
            else:
                title = "Semua amplop belanja: dana sudah habis"
                body = f"Pengeluaran sudah lewat Rp{_fmt_rp(-remaining)} dari total alokasi belanja."
            card = _card(
                "budget_overspend:current",
                "budget_overspend",
                severity,
                title,
                body,
                "/analytics",
                [
                    f"Terpakai Rp{_fmt_rp(expense_spent)} dari Rp{_fmt_rp(expense_allocated)}",
                    f"Reserve rutin Rp{_fmt_rp(expense_reserved)}",
                ],
            )
            card["primary_action"]["label"] = "Buka analitik"
            period_end = ctx.period_info.get("period_end")
            card["detail"] = {
                "available": _money(expense_allocated),
                "spent": _money(expense_spent),
                "remaining": _money(remaining),
                "days_used": days_used,
                "days_remaining": days_remaining,
                "daily_rate": _money(total_variable_rate),
                "safe_daily": _money(safe_daily),
                "period_end": _fmt_date(period_end) if period_end else None,
                "excluded_recurring": _money(excluded_recurring),
                "excluded_adjustment": _money(excluded_adjustment),
                "excluded_outlier": _money(excluded_outlier),
            }
            cards.append(card)
    return cards
