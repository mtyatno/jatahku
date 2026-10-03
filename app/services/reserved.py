from datetime import date
from decimal import Decimal


def recurring_monthly_reserve(frequency_value: str, amount: Decimal, next_run: date, period_end: date) -> Decimal:
    """Kontribusi setara-bulanan sebuah langganan ke 'reserved' amplop.
    monthly: dinamis — 0 kalau sudah dibayar (next_run maju ke luar periode), else penuh.
    yearly: amount/12 (sinking fund). weekly: amount*52/12."""
    if frequency_value == "weekly":
        return amount * Decimal("52") / Decimal("12")
    if frequency_value == "yearly":
        return amount / Decimal("12")
    if frequency_value == "monthly":
        return amount if next_run <= period_end else Decimal("0")
    return amount
