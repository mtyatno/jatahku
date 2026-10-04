"""env_depletion rule — per-envelope depletion projection.

Flags expense envelopes whose current spend rate, projected across the whole
period, would exceed the available budget before the period ends. Each card
leads with an action (a safe daily amount until the period ends) and carries
a structured `detail` so the UI can show the calculation behind it.

Envelopes whose spending this period is only bills or balance adjustments
have no daily habit to project; they are skipped and listed in `ctx.notes`."""
from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _card, _money
from app.services.advisor.rules._base import AdvisorContext, _MIN_PROJECTION_DAYS
from app.services.advisor.projection import project_envelope

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _fmt_date(value) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {_BULAN[value.month - 1]}"


def _floor_thousand(value: Decimal) -> Decimal:
    """A safe daily limit is advice; round it down so following it never overshoots."""
    return (value // 1000) * 1000 if value >= 1000 else value.quantize(Decimal("1"))


def _skip_reason(excluded: dict) -> str:
    if excluded["recurring"] > 0 and excluded["adjustment"] > 0:
        return "isinya tagihan rutin dan penyesuaian saldo"
    if excluded["recurring"] > 0:
        return "isinya tagihan rutin"
    if excluded["adjustment"] > 0:
        return "isinya penyesuaian cocokkan saldo"
    return "isinya pengeluaran satu kali"


def evaluate_depletion(ctx: AdvisorContext) -> list[dict]:
    days_used = ctx.days_used
    days_total = ctx.days_total
    days_remaining = ctx.days_remaining
    period_end = ctx.period_info.get("period_end")

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

        if not (available > 0 and spent > 0 and purpose == "expense" and days_used >= _MIN_PROJECTION_DAYS):
            continue
        proj = project_envelope(
            spent, transaction_count, available, days_used, days_total, days_remaining,
            txns=ctx.txns_by_env.get(str(envelope.id)),
            recurring_amounts=ctx.recurring_by_env.get(str(envelope.id)),
        )
        daily_rate = proj["variable_rate"]
        remaining = available - spent
        name = f"{envelope.emoji} {envelope.name}"

        if daily_rate <= 0 and remaining > 0:
            ctx.notes.append({
                "envelope_id": str(envelope.id),
                "name": name,
                "reason": _skip_reason(proj["excluded"]),
            })
            continue
        if proj["projected"] <= available or days_remaining <= 0:
            continue

        shortage = proj["projected"] - available
        severity = "danger" if shortage > available * Decimal("0.2") else "warning"
        if proj["severity_capped"] and severity == "danger":
            severity = "warning"
        pct = int(spent / available * 100)

        if remaining > 0:
            safe_daily = _floor_thousand(remaining / days_remaining)
            days_until_empty = int(remaining / daily_rate)
            days_early = max(1, days_remaining - days_until_empty)
            title = f"{name}: maksimal Rp{_fmt_rp(safe_daily)}/hari"
            body = (
                f"Sudah terpakai {pct}%. Kalau tetap Rp{_fmt_rp(daily_rate)}/hari, "
                f"sisa Rp{_fmt_rp(remaining)} habis {days_early} hari sebelum periode selesai."
            )
        else:
            safe_daily = Decimal("0")
            days_early = days_remaining
            title = f"{name}: dana sudah habis"
            body = (
                f"Sudah lewat Rp{_fmt_rp(-remaining)} dari dana amplop. "
                f"Pindahkan dana dari amplop lain atau tahan belanja di amplop ini."
            )

        evidence = [
            f"Terpakai Rp{_fmt_rp(spent)} dari Rp{_fmt_rp(available)}",
            f"Rata-rata variabel Rp{_fmt_rp(daily_rate)}/hari",
        ]
        if proj["outliers"]:
            biggest = max(proj["outliers"], key=lambda t: _to_decimal(getattr(t, "amount", 0)))
            evidence.append(
                f"Pengeluaran besar satu kali Rp{_fmt_rp(_to_decimal(getattr(biggest, 'amount', 0)))} ({getattr(biggest, 'description', '')})"
            )
        card = _card(
            f"env_depletion:{envelope.id}",
            "env_depletion",
            severity,
            title,
            body,
            "/allocate",
            evidence,
        )
        card["primary_action"]["label"] = "Atur alokasi"
        excluded = proj["excluded"]
        card["detail"] = {
            "available": _money(available),
            "spent": _money(spent),
            "remaining": _money(remaining),
            "days_used": days_used,
            "days_remaining": days_remaining,
            "daily_rate": _money(daily_rate),
            "safe_daily": _money(safe_daily),
            "days_early": days_early,
            "period_end": _fmt_date(period_end) if period_end else None,
            "excluded_recurring": _money(excluded["recurring"]),
            "excluded_adjustment": _money(excluded["adjustment"]),
            "excluded_outlier": _money(excluded["outlier"]),
        }
        cards.append(card)
    return cards
