from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.models import RecurringTransaction, Transaction


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


def reserve_for_recs(recs, paid_amounts, period_end: date) -> Decimal:
    """Total reserved satu amplop. Tagihan bulanan yang masih jatuh tempo periode ini
    dianggap sudah dibayar bila amplopnya sudah punya transaksi periode ini dengan
    nominal persis sama (dicatat manual, lewat bot, atau penyesuaian cocokkan saldo).
    Satu transaksi hanya melunasi satu tagihan."""
    pool = list(paid_amounts)
    total = Decimal("0")
    for rec in recs:
        reserve = recurring_monthly_reserve(rec.frequency.value, rec.amount, rec.next_run, period_end)
        if rec.frequency.value == "monthly" and reserve and rec.amount in pool:
            pool.remove(rec.amount)
            continue
        total += reserve
    return total


async def envelope_reserved(db, envelope_id, period_start: date, period_end: date) -> Decimal:
    recs = (await db.execute(
        select(RecurringTransaction).where(
            RecurringTransaction.envelope_id == envelope_id,
            RecurringTransaction.is_active == True,
        )
    )).scalars().all()
    due_monthly = any(
        r.frequency.value == "monthly" and r.next_run <= period_end for r in recs
    )
    paid_amounts = []
    if due_monthly:
        paid_amounts = (await db.execute(
            select(Transaction.amount).where(
                Transaction.envelope_id == envelope_id,
                Transaction.is_deleted == False,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )).scalars().all()
    return reserve_for_recs(recs, [Decimal(str(a)) for a in paid_amounts], period_end)
