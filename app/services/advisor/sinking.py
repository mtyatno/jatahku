import re
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from app.services.advisor.formatting import _to_decimal, _money, _fmt_rp, _median_decimal
from app.services.advisor.context import load_advisor_context

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
