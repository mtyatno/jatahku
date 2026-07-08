from datetime import date


def compute_recurring_status(next_run: date, frequency_value: str, today: date, period_end: date) -> str:
    """Status pembayaran sebuah langganan untuk periode budget berjalan.
    monthly: overdue (telat) / due (jatuh tempo periode ini) / paid (next_run sudah lewat periode).
    weekly & yearly (sinking fund): overdue kalau telat, else upcoming (kelunasan tak berlaku)."""
    if next_run < today:
        return "overdue"
    if frequency_value == "monthly":
        return "due" if next_run <= period_end else "paid"
    return "upcoming"
