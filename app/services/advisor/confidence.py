"""Confidence model for advisor recommendations (Plan B2 §6b).

Pure and DB-free. Input is the list of per-period spend (or allocation)
totals that carry signal — one Decimal per historical period with activity.
Output is a 3-tier level plus human-readable reasons for the UI tooltip.

Rules:
- high:   >= 4 active periods AND relative spread (max-median)/median < 50%.
- medium: >= 2 active periods.
- low:    otherwise (new user, dominant outlier, empty/zero-median history).
A zero or near-zero median can never be `high`.
"""
from decimal import Decimal

from app.services.advisor.formatting import _to_decimal, _median_decimal

_HIGH_MIN_PERIODS = 4
_MEDIUM_MIN_PERIODS = 2
_HIGH_MAX_SPREAD = Decimal("0.5")


def assess_confidence(period_spends: list[Decimal]) -> dict:
    values = [_to_decimal(v) for v in period_spends if _to_decimal(v) > 0]
    n = len(values)
    if n == 0:
        return {"level": "low", "reasons": ["Belum ada histori pengeluaran yang cukup."]}

    median = _median_decimal(values)
    if median <= 0:
        return {"level": "low", "reasons": ["Pola pengeluaran belum stabil untuk dinilai."]}

    spread = (max(values) - median) / median
    reasons = [f"{n} periode histori aktif."]
    if n >= _HIGH_MIN_PERIODS and spread < _HIGH_MAX_SPREAD:
        reasons.append("Pengeluaran relatif stabil antar periode.")
        return {"level": "high", "reasons": reasons}
    if n >= _MEDIUM_MIN_PERIODS:
        if spread >= _HIGH_MAX_SPREAD:
            reasons.append("Ada periode dengan lonjakan pengeluaran.")
        return {"level": "medium", "reasons": reasons}
    reasons.append("Histori masih terlalu pendek untuk keyakinan tinggi.")
    return {"level": "low", "reasons": reasons}
