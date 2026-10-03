"""subscription_pressure rule — recurring reserve squeezing free cash.

Flags envelopes where a recurring reserve leaves very little free cash
(free below 25% of the reserved amount)."""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card
from app.services.advisor.rules._base import AdvisorContext


def evaluate_subscription(ctx: AdvisorContext) -> list[dict]:
    cards = []
    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")
        allocated = _to_decimal(current.get("allocated"))
        spent = _to_decimal(current.get("spent"))
        rollover = _to_decimal(current.get("rollover"))
        reserved = _to_decimal(current.get("reserved"))
        available = allocated + rollover
        remaining = available - spent
        free = remaining - reserved

        if purpose == "expense" and reserved > 0 and free < reserved * Decimal("0.25"):
            cards.append(_card(
                f"subscription_pressure:{envelope.id}",
                "subscription_pressure",
                "warning",
                (f"{envelope.emoji} {envelope.name}: sisa bebas Rp{_fmt_rp(free)}" if free >= 0
                 else f"{envelope.emoji} {envelope.name}: kurang Rp{_fmt_rp(-free)} untuk tagihan"),
                "Sebagian besar dana amplop ini sudah disisihkan untuk tagihan rutin. "
                "Hindari belanja lain dari amplop ini.",
                "/langganan",
                [
                    f"Sisa dana amplop Rp{_fmt_rp(remaining)}",
                    f"Disisihkan untuk tagihan Rp{_fmt_rp(reserved)}",
                    f"Sisa bebas Rp{_fmt_rp(free)}",
                ],
            ))
    return cards
