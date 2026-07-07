"""env_depletion rule — per-envelope depletion projection.

Flags expense envelopes whose current spend rate, projected across the whole
period, would exceed the available budget before the period ends."""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card
from app.services.advisor.rules._base import AdvisorContext, _MIN_PROJECTION_DAYS
from app.services.advisor.projection import project_envelope


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
        transaction_count = int(current.get("transaction_count") or 0)

        if available > 0 and spent > 0 and purpose == "expense" and days_used >= _MIN_PROJECTION_DAYS:
            proj = project_envelope(
                spent, transaction_count, available, days_used, days_total, days_remaining,
                txns=ctx.txns_by_env.get(str(envelope.id)),
                recurring_amounts=ctx.recurring_by_env.get(str(envelope.id)),
            )
            projected = proj["projected"]
            if projected > available and days_remaining > 0:
                pct = int(spent / available * 100)
                shortage = projected - available
                daily_rate = proj["variable_rate"] if proj["variable_rate"] > 0 else (spent / days_used)
                severity = "danger" if shortage > available * Decimal("0.2") else "warning"
                if proj["severity_capped"] and severity == "danger":
                    severity = "warning"
                evidence = [
                    f"Terpakai Rp{_fmt_rp(spent)} dari Rp{_fmt_rp(available)}",
                    f"Rata-rata variabel Rp{_fmt_rp(daily_rate)}/hari",
                ]
                if proj["outliers"]:
                    biggest = max(proj["outliers"], key=lambda t: _to_decimal(getattr(t, "amount", 0)))
                    evidence.append(
                        f"Pengeluaran besar satu kali Rp{_fmt_rp(_to_decimal(getattr(biggest, 'amount', 0)))} ({getattr(biggest, 'description', '')})"
                    )
                cards.append(_card(
                    f"env_depletion:{envelope.id}",
                    "env_depletion",
                    severity,
                    f"{envelope.emoji} {envelope.name} sudah terpakai {pct}%",
                    f"Masih {days_remaining} hari. Proyeksi habis {max(1, int(shortage / daily_rate)) if daily_rate > 0 else days_remaining} hari sebelum periode selesai.",
                    "/allocate",
                    evidence,
                ))
    return cards
