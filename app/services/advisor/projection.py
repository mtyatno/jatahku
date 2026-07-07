"""Front-loaded-honest projection for the advisor (Plan B2 §6a).

Pure, DB-free. Burn rate is computed from VARIABLE spending only: a fixed
bill paid on day 1 (matched to a recurring reserve) or a one-off outlier must
not be linearly extrapolated across the whole period — that is the #1 source
of false "budget jebol" alarms.

Two modes:
- Aggregate-only (no per-txn data, e.g. synthetic fixtures): every rupiah is
  treated as variable, so `projected == (spent/days_used)*days_total`, exactly
  the pre-B2 formula, and severity is never capped (no per-txn basis to judge
  sample thinness). This keeps the Plan B1 characterization tests green.
- Per-txn (real data): exclude recurring-matched (amount within ±10% of an
  active recurring) and outlier (> 2x median txn AND > 30% of available)
  transactions from the rate; cap severity when fewer than 5 variable txns.
"""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _median_decimal

_RECURRING_TOLERANCE = Decimal("0.1")
_OUTLIER_MEDIAN_MULT = Decimal("2")
_OUTLIER_AVAIL_FRAC = Decimal("0.3")
_MIN_VARIABLE_TXNS = 5


def _txn_amount(txn) -> Decimal:
    return _to_decimal(getattr(txn, "amount", None))


def _matches_recurring(amount: Decimal, recurring_amounts) -> bool:
    for rec in recurring_amounts or []:
        rec_amt = _to_decimal(rec.get("amount") if isinstance(rec, dict) else rec)
        if rec_amt <= 0:
            continue
        if abs(amount - rec_amt) <= rec_amt * _RECURRING_TOLERANCE:
            return True
    return False


def project_envelope(spent_total, transaction_count, available,
                     days_used, days_total, days_remaining,
                     txns=None, recurring_amounts=None) -> dict:
    spent_total = _to_decimal(spent_total)
    available = _to_decimal(available)
    days_used = max(int(days_used), 1)
    txns = list(txns or [])
    recurring_amounts = recurring_amounts or []

    if txns:
        amounts = [_txn_amount(t) for t in txns]
        median = _median_decimal(amounts)
        variable_total = Decimal("0")
        variable_count = 0
        outliers = []
        for t in txns:
            amount = _txn_amount(t)
            is_recurring = _matches_recurring(amount, recurring_amounts)
            is_outlier = (
                median > 0
                and amount > median * _OUTLIER_MEDIAN_MULT
                and amount > available * _OUTLIER_AVAIL_FRAC
            )
            if is_recurring or is_outlier:
                if is_outlier and not is_recurring:
                    outliers.append(t)
                continue
            variable_total += amount
            variable_count += 1
        severity_capped = variable_count < _MIN_VARIABLE_TXNS
    else:
        variable_total = spent_total
        variable_count = int(transaction_count or 0)
        outliers = []
        severity_capped = False  # aggregate-only: no per-txn basis to cap

    variable_rate = variable_total / days_used
    projected = spent_total + variable_rate * days_remaining
    return {
        "projected": projected,
        "variable_rate": variable_rate,
        "variable_count": variable_count,
        "severity_capped": severity_capped,
        "outliers": outliers,
    }
