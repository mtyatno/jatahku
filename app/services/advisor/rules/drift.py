"""allocation_drift rule — target lower than the actual spend pattern.

Flags expense envelopes whose historical median spend runs well above the
configured budget target (more than 15% over)."""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card, _median_decimal
from app.services.advisor.rules._base import AdvisorContext


def evaluate_drift(ctx: AdvisorContext) -> list[dict]:
    cards = []
    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

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
    return cards
