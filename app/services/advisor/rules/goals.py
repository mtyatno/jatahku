"""goal_progress rule — consolidated saving & sinking-fund progress.

Collects saving/sinking_fund envelopes that have a goal into one card. The
card's severity is `warning` if any sinking fund is under-funded, else
`info`. Returns 0 or 1 card."""
from datetime import date
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _fmt_rp, _fmt_months, _card, _median_decimal
from app.services.advisor.rules._base import AdvisorContext


def evaluate_goals(ctx: AdvisorContext) -> list[dict]:
    sinking_under_funded = False
    saving_items = []
    sinking_items = []

    for envelope in ctx.envelopes:
        envelope_stats = ctx.stats.get(str(envelope.id), [])
        if not envelope_stats:
            continue
        current = envelope_stats[-1]
        allocated = _to_decimal(current.get("allocated"))
        purpose = str(getattr(envelope, "purpose", "expense") or "expense")

        goal = ctx.goals_by_env.get(str(envelope.id))
        if purpose in ("saving", "sinking_fund") and goal:
            balance = ctx.balances_by_env.get(str(envelope.id), Decimal("0"))
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

    if not (saving_items or sinking_items):
        return []

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
    return [_card(
        "goals:consolidated",
        "goal_progress",
        severity,
        "Target menabung & dana persiapan",
        "\n".join(body_parts),
        "/envelopes",
        ["Buka halaman amplop untuk detail dan edit target."],
    )]
