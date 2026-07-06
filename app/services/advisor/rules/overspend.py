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


def evaluate_overspend(ctx: AdvisorContext) -> list[dict]:
    days_used = ctx.days_used
    days_total = ctx.days_total

    expense_reserved = Decimal("0")
    expense_allocated = Decimal("0")
    expense_spent = Decimal("0")

    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        reserved = _to_decimal(current.get("reserved"))
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

        if purpose == "expense":
            expense_allocated += allocated
            expense_spent += spent
            expense_reserved += reserved

    cards = []
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
                    f"Reserve rutin Rp{_fmt_rp(expense_reserved)}",
                ],
            ))
    return cards
