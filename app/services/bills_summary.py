from datetime import date
from decimal import Decimal

from app.services.recurring_status import take_paid_in_period


def summarize_bills(recs, txns_by_env, period_start: date, period_end: date, today: date) -> dict:
    """Ringkasan tagihan bulanan untuk kartu "Tagihan belum dibayar".

    Belum dibayar mengikuti reserve_for_recs: tagihan bulanan dengan next_run <= akhir periode,
    kecuali yang jatuh tempo di periode ini dan amplopnya punya transaksi periode ini dengan
    nominal persis sama (satu transaksi melunasi satu tagihan). Jumlahnya sama dengan bagian
    bulanan dari cadangan tagihan yang dikurangkan dari Sisa bebas.
    Lunas: yang cocok tadi, ditambah tagihan yang dibayar lewat "Bayar" periode ini (next_run sudah
    maju ke luar periode dan amplopnya punya transaksi "🔄 <deskripsi>" periode ini).

    txns_by_env: {envelope_id: [(amount, description), ...]} transaksi periode ini, tidak dihapus.
    """
    pools = {env_id: list(txns) for env_id, txns in txns_by_env.items()}
    amount_due = Decimal("0")
    amount_paid = Decimal("0")
    count_due = 0
    count_paid = 0
    has_overdue = False

    monthly = [r for r in recs if r.frequency.value == "monthly"]

    # Bayar dulu: transaksinya tidak boleh dipakai lagi untuk mencocokkan tagihan lain.
    for amount in take_paid_in_period(monthly, pools, period_start, period_end).values():
        amount_paid += Decimal(str(amount))
        count_paid += 1

    for rec in monthly:
        if rec.next_run > period_end:
            continue
        pool = pools.get(rec.envelope_id, [])
        if period_start <= rec.next_run:
            hit = next((t for t in pool if Decimal(str(t[0])) == rec.amount), None)
            if hit:
                pool.remove(hit)
                amount_paid += rec.amount
                count_paid += 1
                continue
        amount_due += rec.amount
        count_due += 1
        if rec.next_run < today:
            has_overdue = True

    return {
        "amount_due": float(amount_due),
        "count_due": count_due,
        "count_total": count_due + count_paid,
        "amount_paid": float(amount_paid),
        "has_overdue": has_overdue,
    }
