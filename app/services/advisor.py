import re
import logging
from datetime import date
from decimal import Decimal
from statistics import median

logger = logging.getLogger("jatahku.advisor")

_AMOUNT_RE = re.compile(
    r"(?:rp\.?\s*)?\d{1,3}(?:[.,]\d{3})+(?:\s*(?:jt|juta|rb|ribu|k))?"
    r"|(?:rp\.?\s*)?\d+(?:[.,]\d+)?\s*(?:jt|juta|rb|ribu|k)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "aku", "saya", "gue", "gw", "ku", "dong", "nih", "sih", "ya", "deh",
    "lah", "tadi", "barusan", "lagi", "udah", "sudah", "bayar", "beli",
    "buat", "untuk", "ke", "di", "dari", "yang", "dan", "dengan",
}
_YEARLY_WORDS = {"tahunan", "tahun", "annual", "yearly", "renewal", "perpanjang"}
_ESSENTIAL_KEYWORDS = {
    "makan", "belanja", "tagihan", "listrik", "air", "internet", "transport",
    "transportasi", "bensin", "sewa", "kontrak", "sekolah", "asuransi",
}
# Don't project depletion/overspend before this many days into the period —
# early-period spend rates are too volatile and produce false alarms.
_MIN_PROJECTION_DAYS = 3


def normalize_description(text: str) -> str:
    text = _AMOUNT_RE.sub(" ", text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [word for word in text.split() if word not in _STOPWORDS]
    return " ".join(words)


def detect_interval(dates: list[date], normalized_text: str = "") -> dict:
    ordered_dates = sorted(set(dates))
    normalized_words = set(normalized_text.lower().split())

    if len(ordered_dates) < 2:
        if normalized_words & _YEARLY_WORDS:
            return {"frequency": "yearly", "confidence": "low", "median_days": None}
        return {"frequency": "unknown", "confidence": "low", "median_days": None}

    gaps = [
        (ordered_dates[index] - ordered_dates[index - 1]).days
        for index in range(1, len(ordered_dates))
    ]
    median_gap = median(gaps)

    if all(5 <= gap <= 9 for gap in gaps):
        confidence = "high" if len(ordered_dates) >= 3 else "medium"
        return {"frequency": "weekly", "confidence": confidence, "median_days": median_gap}

    if all(25 <= gap <= 35 for gap in gaps):
        confidence = "high" if len(ordered_dates) >= 3 else "medium"
        return {"frequency": "monthly", "confidence": confidence, "median_days": median_gap}

    if all(80 <= gap <= 100 for gap in gaps):
        return {"frequency": "quarterly", "confidence": "medium", "median_days": median_gap}

    if all(170 <= gap <= 195 for gap in gaps):
        return {"frequency": "semiannual", "confidence": "medium", "median_days": median_gap}

    if all(350 <= gap <= 380 for gap in gaps):
        confidence = "high" if len(ordered_dates) >= 3 else "medium"
        return {"frequency": "yearly", "confidence": confidence, "median_days": median_gap}

    return {"frequency": "unknown", "confidence": "low", "median_days": median_gap}


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


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


def _payday(user) -> int:
    return getattr(user, "payday_day", 1) or 1


async def _get_household_id(user, db):
    from sqlalchemy import select
    from app.models.models import HouseholdMember

    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _load_visible_envelopes(user, household_id, db):
    from sqlalchemy import or_, select
    from app.models.models import Envelope

    result = await db.execute(
        select(Envelope)
        .where(
            Envelope.household_id == household_id,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    return result.scalars().all()


# ── Pure period-bucketing helpers (unit-tested; no DB) ──
def _period_index(d: date, periods: list[tuple[date, date]]):
    for i, (ps, pe) in enumerate(periods):
        if ps <= d <= pe:
            return i
    return None


def _sum_by_period(rows, periods) -> list[Decimal]:
    """rows: iterable of (date, amount). Returns Decimal sum per period index."""
    sums = [Decimal("0") for _ in periods]
    for d, amount in rows:
        idx = _period_index(d, periods)
        if idx is not None:
            sums[idx] += _to_decimal(amount)
    return sums


def _count_by_period(dates, periods) -> list[int]:
    counts = [0 for _ in periods]
    for d in dates:
        idx = _period_index(d, periods)
        if idx is not None:
            counts[idx] += 1
    return counts


def _monthly_reserve(amount, frequency) -> Decimal:
    """Monthly-equivalent reserve for a recurring transaction frequency."""
    from app.models.models import RecurringFrequency
    if frequency == RecurringFrequency.weekly:
        return _to_decimal(amount) * 4
    if frequency == RecurringFrequency.yearly:
        return _to_decimal(amount) / 12
    return _to_decimal(amount)


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


async def envelope_lifetime_balance(envelope_id, db) -> Decimal:
    """Canonical all-time accumulated balance of an envelope:
    sum(allocations) - sum(non-deleted transactions), independent of period or
    rollover snapshots. Single source of truth for savings goal progress so the
    Goals page, advisor, and dashboard cards always agree."""
    from sqlalchemy import func, select
    from app.models.models import Allocation, Transaction

    alloc = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0)).where(
            Allocation.envelope_id == envelope_id
        )
    )
    spent = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == envelope_id,
            Transaction.is_deleted == False,
        )
    )
    return _to_decimal(alloc.scalar()) - _to_decimal(spent.scalar())


async def load_advisor_context(user, db, periods_count: int = 6) -> dict:
    from app.core.period import get_last_n_periods

    household_id = await _get_household_id(user, db)
    if not household_id:
        return {"household_id": None, "periods": [], "envelopes": [], "stats": {}}

    payday_day = _payday(user)
    periods = get_last_n_periods(payday_day, periods_count)
    envelopes = await _load_visible_envelopes(user, household_id, db)
    stats = {}
    if not envelopes or not periods:
        return {
            "household_id": household_id,
            "payday_day": payday_day,
            "periods": periods,
            "envelopes": envelopes,
            "stats": stats,
        }

    # Batched fetches — a fixed handful of queries regardless of envelope/period
    # count (was O(envelopes x periods x 4) sequential round-trips before).
    from collections import defaultdict
    from sqlalchemy import select
    from app.core.period import get_previous_period
    from app.models.models import (
        Allocation, Income, Transaction, RecurringTransaction, MonthlySnapshot,
    )

    env_ids = [e.id for e in envelopes]
    range_start = periods[0][0]
    range_end = periods[-1][1]

    alloc_rows = (await db.execute(
        select(Allocation.envelope_id, Income.income_date, Allocation.amount)
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id.in_(env_ids),
            Income.income_date >= range_start,
            Income.income_date <= range_end,
        )
    )).all()
    alloc_by_env = defaultdict(list)
    for env_id, income_date, amount in alloc_rows:
        alloc_by_env[str(env_id)].append((income_date, amount))

    txn_rows = (await db.execute(
        select(Transaction.envelope_id, Transaction.transaction_date, Transaction.amount)
        .where(
            Transaction.envelope_id.in_(env_ids),
            Transaction.is_deleted == False,
            Transaction.transaction_date >= range_start,
            Transaction.transaction_date <= range_end,
        )
    )).all()
    txn_by_env = defaultdict(list)
    for env_id, txn_date, amount in txn_rows:
        txn_by_env[str(env_id)].append((txn_date, amount))

    rec_rows = (await db.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.envelope_id.in_(env_ids),
            RecurringTransaction.is_active == True,
        )
    )).scalars().all()
    reserved_by_env = defaultdict(lambda: Decimal("0"))
    for rec in rec_rows:
        reserved_by_env[str(rec.envelope_id)] += _monthly_reserve(rec.amount, rec.frequency)

    # Each period's rollover comes from the PREVIOUS period's snapshot (year/month).
    prev_keys = [get_previous_period(payday_day, ps)[0] for ps, _ in periods]
    snap_rows = (await db.execute(
        select(MonthlySnapshot).where(MonthlySnapshot.envelope_id.in_(env_ids))
    )).scalars().all()
    snap_map = {}
    for s in snap_rows:
        snap_map[(str(s.envelope_id), s.year, s.month)] = (
            _to_decimal(s.rollover_amount) if s.rollover_amount else Decimal("0")
        )

    for envelope in envelopes:
        eid = str(envelope.id)
        alloc_sums = _sum_by_period(alloc_by_env.get(eid, []), periods)
        spent_pairs = txn_by_env.get(eid, [])
        spent_sums = _sum_by_period(spent_pairs, periods)
        counts = _count_by_period([d for d, _ in spent_pairs], periods)
        reserved = reserved_by_env.get(eid, Decimal("0"))

        envelope_stats = []
        for i, (period_start, period_end) in enumerate(periods):
            if envelope.is_rollover:
                prev = prev_keys[i]
                rollover = snap_map.get((eid, prev.year, prev.month), Decimal("0"))
            else:
                rollover = Decimal("0")
            envelope_stats.append({
                "period_start": period_start,
                "period_end": period_end,
                "allocated": alloc_sums[i],
                "spent": spent_sums[i],
                "transaction_count": counts[i],
                "rollover": rollover,
                "reserved": reserved,
            })
        stats[eid] = envelope_stats

    return {
        "household_id": household_id,
        "payday_day": payday_day,
        "periods": periods,
        "envelopes": envelopes,
        "stats": stats,
    }


def _card(card_id: str, card_type: str, severity: str, title: str, body: str, route: str, evidence: list[str]) -> dict:
    return {
        "id": card_id,
        "type": card_type,
        "severity": severity,
        "title": title,
        "body": body,
        "primary_action": {"label": "Lihat detail", "route": route},
        "evidence": evidence[:3],
    }


def _severity_rank(severity: str) -> int:
    return {"danger": 0, "warning": 1, "info": 2, "positive": 3}.get(severity, 4)


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


def _money(value: Decimal) -> int:
    return int(_to_decimal(value).quantize(Decimal("1")))


def _fmt_rp(value) -> str:
    """Indonesian Rupiah grouping with dots: 1520000 -> '1.520.000'."""
    return f"{_money(value):,}".replace(",", ".")


def _fmt_months(months: int) -> str:
    """Format months as 'X tahun Y bulan' or 'X bulan'."""
    years = months // 12
    remaining = months % 12
    if years > 0 and remaining > 0:
        return f"{years} tahun {remaining} bulan"
    elif years > 0:
        return f"{years} tahun"
    else:
        return f"{months} bulan"


def _median_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


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


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _frequency_monthly_reserve(amount: Decimal, frequency: str) -> Decimal:
    if frequency == "weekly":
        return amount * 4
    if frequency == "quarterly":
        return amount / 3
    if frequency == "semiannual":
        return amount / 6
    if frequency == "yearly":
        return amount / 12
    return amount


def _next_expected_date(dates: list[date], interval: dict) -> str | None:
    from datetime import timedelta

    if not dates:
        return None
    last_date = max(dates)
    frequency = interval.get("frequency")
    days = {
        "weekly": 7,
        "monthly": 30,
        "quarterly": 90,
        "semiannual": 182,
        "yearly": 365,
    }.get(frequency)
    if not days:
        return None
    return str(last_date + timedelta(days=days))


def _amount_stability(amounts: list[Decimal]) -> dict:
    if not amounts:
        return {"kind": "unknown", "confidence": "low", "suggested_amount": Decimal("0")}
    suggested = _median_decimal(amounts)
    if len(amounts) == 1:
        return {"kind": "single", "confidence": "low", "suggested_amount": suggested}
    lowest = min(amounts)
    highest = max(amounts)
    if suggested == 0:
        spread = Decimal("0")
    else:
        spread = (highest - lowest) / suggested
    if spread <= Decimal("0.05"):
        kind = "exact"
        confidence = "high"
    elif spread <= Decimal("0.2"):
        kind = "stable_range"
        confidence = "medium"
    else:
        kind = "variable"
        confidence = "low"
    return {"kind": kind, "confidence": confidence, "suggested_amount": suggested}


def select_visible_samples(viewer_id, transactions) -> list[str]:
    """Sampel deskripsi untuk evidence advisor — hanya dari transaksi yang
    boleh dilihat viewer (milik sendiri atau non-privat). Dedup, urutan asli."""
    from app.services.visibility import can_view_description

    samples: list[str] = []
    for txn in transactions:
        if not can_view_description(viewer_id, txn):
            continue
        if txn.description not in samples:
            samples.append(txn.description)
    return samples


def _sinking_group_id(envelope_id, normalized: str) -> str:
    """ID stabil per-grup sinking-fund tanpa membocorkan token deskripsi.
    Hash dipakai agar deskripsi privat anggota lain tak muncul di body API."""
    import hashlib
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"sfa:{envelope_id}:{digest}"


async def build_sinking_fund_advice(user, db) -> dict:
    from sqlalchemy import select
    from app.models.models import Envelope, RecurringTransaction, Transaction

    context = await load_advisor_context(user, db, periods_count=12)
    household_id = context.get("household_id")
    envelopes = context.get("envelopes", [])
    periods = context.get("periods", [])
    if not household_id or not envelopes or not periods:
        return {
            "summary": {
                "monthly_reserve_needed": 0,
                "new_reserve_needed": 0,
                "recommendation_count": 0,
                "high_confidence_count": 0,
            },
            "recommendations": [],
        }

    envelope_by_id = {str(envelope.id): envelope for envelope in envelopes}
    envelope_ids = [envelope.id for envelope in envelopes]
    first_period_start = periods[0][0]

    txn_result = await db.execute(
        select(Transaction)
        .join(Envelope, Transaction.envelope_id == Envelope.id)
        .where(
            Transaction.envelope_id.in_(envelope_ids),
            Transaction.is_deleted == False,
            Transaction.transaction_date >= first_period_start,
        )
        .order_by(Transaction.transaction_date)
    )
    transactions = txn_result.scalars().all()

    recurring_result = await db.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.envelope_id.in_(envelope_ids),
            RecurringTransaction.is_active == True,
        )
    )
    recurring_entries = recurring_result.scalars().all()
    recurring_norms = [
        {
            "envelope_id": str(entry.envelope_id),
            "description": normalize_description(entry.description),
            "amount": _to_decimal(entry.amount),
            "frequency": entry.frequency.value if hasattr(entry.frequency, "value") else str(entry.frequency),
        }
        for entry in recurring_entries
    ]

    groups = {}
    for transaction in transactions:
        normalized = normalize_description(transaction.description)
        if not normalized:
            continue
        group = groups.setdefault(normalized, {
            "normalized": normalized,
            "transactions": [],
            "amounts": [],
            "dates": [],
            "envelope_ids": [],
            "samples": [],
        })
        group["transactions"].append(transaction)
        group["amounts"].append(_to_decimal(transaction.amount))
        group["dates"].append(transaction.transaction_date)
        group["envelope_ids"].append(str(transaction.envelope_id))

    for group in groups.values():
        group["samples"] = select_visible_samples(user.id, group["transactions"])

    recommendations = []
    for group in groups.values():
        interval = detect_interval(group["dates"], group["normalized"])
        amount_info = _amount_stability(group["amounts"])
        has_explicit_yearly = bool(set(group["normalized"].split()) & _YEARLY_WORDS)
        frequency = interval["frequency"]

        if frequency == "unknown" and not has_explicit_yearly:
            if len(group["transactions"]) < 3:
                continue
            recommendation_type = "review"
            confidence = "low"
        else:
            recommendation_type = "create_recurring"
            confidence = interval["confidence"]
            if amount_info["confidence"] == "low" and confidence == "high":
                confidence = "medium"

        if frequency == "unknown" and has_explicit_yearly:
            frequency = "yearly"
            confidence = "low"
            recommendation_type = "annualize"

        envelope_id = max(set(group["envelope_ids"]), key=group["envelope_ids"].count)
        envelope = envelope_by_id.get(envelope_id)
        if not envelope:
            continue

        duplicate = next(
            (
                entry for entry in recurring_norms
                if entry["envelope_id"] == envelope_id
                and _token_overlap(entry["description"], group["normalized"]) >= 0.5
            ),
            None,
        )
        suggested_amount = _to_decimal(amount_info["suggested_amount"]).quantize(Decimal("1"))
        monthly_reserve = _frequency_monthly_reserve(suggested_amount, frequency).quantize(Decimal("1"))

        if duplicate:
            amount_gap = abs(_to_decimal(duplicate["amount"]) - suggested_amount)
            if suggested_amount > 0 and amount_gap / suggested_amount > Decimal("0.15"):
                recommendation_type = "adjust_recurring"
            else:
                continue

        if group["samples"]:
            sample_line = f"{len(group['transactions'])} transaksi cocok: {', '.join(group['samples'][:2])}"
        else:
            sample_line = f"{len(group['transactions'])} transaksi serupa terdeteksi"
        evidence = [
            sample_line,
            f"Nominal {amount_info['kind']} sekitar Rp{_fmt_rp(suggested_amount)}",
        ]
        if interval.get("median_days"):
            evidence.append(f"Interval median {int(interval['median_days'])} hari")
        elif has_explicit_yearly:
            evidence.append("Ada kata tahunan/renewal/perpanjang pada deskripsi")

        title_frequency = {
            "weekly": "mingguan",
            "monthly": "bulanan",
            "quarterly": "triwulanan",
            "semiannual": "semesteran",
            "yearly": "tahunan",
        }.get(frequency, "berulang")

        recommendations.append({
            "id": _sinking_group_id(envelope_id, group["normalized"]),
            "type": recommendation_type,
            "confidence": confidence,
            "envelope_id": envelope_id,
            "envelope_name": envelope.name,
            "title": (
                f"{group['samples'][0]} terlihat sebagai pengeluaran {title_frequency}"
                if group["samples"]
                else f"Pengeluaran {title_frequency} terdeteksi di amplop {envelope.name}"
            ),
            "description": "Pola ini layak dipisah sebagai sinking fund agar dana bebas tidak terlihat lebih longgar dari kondisi sebenarnya.",
            "suggested_amount": _money(suggested_amount),
            "monthly_reserve": _money(monthly_reserve),
            "frequency": frequency,
            "next_expected_date": _next_expected_date(group["dates"], {**interval, "frequency": frequency}),
            "evidence": evidence[:3],
            "impact": f"Sisihkan sekitar Rp{_fmt_rp(monthly_reserve)}/periode untuk menjaga amplop {envelope.name} tetap siap.",
            "actions": [
                {
                    "kind": recommendation_type,
                    "label": "Tinjau langganan",
                    "payload": {
                        "envelope_id": envelope_id,
                        "amount": _money(suggested_amount),
                        "description": group["samples"][0] if group["samples"] else f"Rutin {envelope.name}",
                        "frequency": frequency,
                        "next_run": _next_expected_date(group["dates"], {**interval, "frequency": frequency}),
                    },
                },
                {"kind": "dismiss", "label": "Abaikan"},
            ],
        })

    recommendations = sorted(
        recommendations,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item["confidence"], 3),
            -item["monthly_reserve"],
            item["title"],
        ),
    )
    monthly_reserve_needed = sum(item["monthly_reserve"] for item in recommendations)
    high_confidence_count = sum(1 for item in recommendations if item["confidence"] == "high")

    return {
        "summary": {
            "monthly_reserve_needed": monthly_reserve_needed,
            "new_reserve_needed": monthly_reserve_needed,
            "recommendation_count": len(recommendations),
            "high_confidence_count": high_confidence_count,
        },
        "recommendations": recommendations,
    }
