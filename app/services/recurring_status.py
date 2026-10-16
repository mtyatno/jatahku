from datetime import date


def take_paid_in_period(recs, pools, period_start: date, period_end: date) -> dict:
    """Langganan bulanan yang benar-benar dibayar di periode berjalan → {rec.id: nominal}.

    Dibayar = next_run sudah di luar periode dan amplopnya punya transaksi "🔄 <deskripsi>" periode
    ini (dibuat oleh Bayar di web/bot, atau pembayaran pertama saat langganan dibuat lewat bot).
    Termasuk bayar lebih awal: tagihan yang jatuh tempo di periode depan lalu dibayar sekarang
    (next_run maju 2 bulan dari periode ini). Transaksi yang cocok diambil dari `pools`
    ({envelope_id: [(amount, description), ...]}) supaya tidak dipakai dua kali.
    Langganan baru yang jatuh tempo pertamanya di periode depan, tanpa transaksi, TIDAK dihitung dibayar.
    """
    paid = {}
    for rec in recs:
        if rec.frequency.value != "monthly" or rec.next_run <= period_end:
            continue
        pool = pools.get(rec.envelope_id, [])
        hit = next((t for t in pool if t[1] == f"🔄 {rec.description}"), None)
        if hit:
            pool.remove(hit)
            paid[rec.id] = hit[0]
    return paid


def compute_recurring_status(next_run: date, frequency_value: str, today: date, period_end: date,
                             paid_in_period: bool = False) -> str:
    """Status pembayaran sebuah langganan untuk periode budget berjalan.
    monthly: overdue (telat) / due (jatuh tempo periode ini) / paid (sudah dibayar periode ini) /
    upcoming (jatuh tempo berikutnya di periode depan, belum ada pembayaran periode ini — mis. baru ditambahkan).
    weekly & yearly (sinking fund): overdue kalau telat, else upcoming (kelunasan tak berlaku)."""
    if next_run < today:
        return "overdue"
    if frequency_value == "monthly":
        if next_run <= period_end:
            return "due"
        return "paid" if paid_in_period else "upcoming"
    return "upcoming"
_MONTHS_ID = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _fmt(d: date) -> str:
    return f"{d.day} {_MONTHS_ID[d.month]}"


def payable_from(next_run: date, payday_day: int) -> date:
    """Awal periode budget tempat jatuh tempo berikutnya berada: sejak tanggal ini tagihan bisa dibayar."""
    from app.core.period import get_budget_period
    return get_budget_period(payday_day or 1, next_run)[0]


def payment_window_error(next_run: date, payday_day: int, today: date) -> str | None:
    """Tagihan hanya bisa dibayar/dilewati kalau jatuh temponya ada di periode budget aktif
    (bayar lebih awal boleh selama masih di periode ini). Jatuh tempo di periode depan ditolak,
    karena alokasi periode itu belum ada. Keputusan pemilik produk, 16 Okt 2026.
    None = boleh; selain itu pesan penolakan."""
    from app.core.period import get_budget_period
    _ps, period_end = get_budget_period(payday_day or 1, today)
    if next_run <= period_end:
        return None
    start = payable_from(next_run, payday_day)
    return (f"Jatuh tempo {_fmt(next_run)} masuk periode berikutnya, jadi belum bisa dibayar. "
            f"Bisa dibayar mulai {_fmt(start)}.")
