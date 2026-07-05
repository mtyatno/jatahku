"""env_depletion rule — per-envelope depletion projection.

Flags expense envelopes whose current spend rate, projected across the whole
period, would exceed the available budget before the period ends."""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card
from app.services.advisor.rules._base import AdvisorContext, _MIN_PROJECTION_DAYS


def evaluate_depletion(ctx: AdvisorContext) -> list[dict]:
    days_used = ctx.days_used
    days_total = ctx.days_total
    days_remaining = ctx.days_remaining

    cards = []
    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        rollover = _to_decimal(current.get("rollover"))
        available = allocated + rollover
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

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
    return cards
