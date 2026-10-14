"""Geser dana antar amplop — dipakai bot Telegram saat pengeluaran terblokir
karena amplop tujuan kurang dana (setara FundEnvelopeModal di web).

Transfer dicatat persis seperti POST /envelopes/transfer: satu Income bernilai 0
(net nol, bukan pemasukan sungguhan) dengan dua Allocation: negatif di amplop
sumber, positif di amplop tujuan.
"""
from decimal import Decimal

from app.models.models import Allocation, Income

# Berapa banyak amplop sumber yang ditawarkan sebagai tombol.
MAX_SOURCES = 4


def envelope_purpose(env) -> str:
    """purpose bisa enum atau string (lihat AGENTS.md) — normalisasi ke string."""
    p = getattr(env, "purpose", None)
    return str(getattr(p, "value", p) or "expense")


def compute_shortfall(target_remaining: Decimal, amount: Decimal) -> Decimal:
    """Kekurangan dana agar `amount` bisa dicatat di amplop dengan sisa
    `target_remaining` (boleh negatif bila amplop sudah minus)."""
    return max(Decimal(amount) - Decimal(target_remaining), Decimal("0"))


def pick_sources(envelope_data: list[dict], target_id, shortfall: Decimal,
                 limit: int = MAX_SOURCES) -> list[dict]:
    """Amplop yang bisa menutup seluruh kekurangan sendirian.

    Memakai dana *bebas* (sisa − cadangan langganan), bukan sisa mentah, supaya
    dana yang sudah dicadangkan untuk tagihan langganan tidak ikut tergeser.
    Amplop pengeluaran didahulukan, lalu yang dana bebasnya terbesar.

    `envelope_data` = keluaran get_envelopes_with_spent (dict berisi
    envelope, remaining, reserved, free).
    """
    if shortfall <= 0:
        return []
    candidates = [
        e for e in envelope_data
        if str(e["envelope"].id) != str(target_id)
        and Decimal(e["free"]) >= shortfall
    ]
    candidates.sort(key=lambda e: (
        envelope_purpose(e["envelope"]) != "expense",
        -Decimal(e["free"]),
    ))
    return candidates[:limit]


def record_transfer(db, household_id, user_id, from_env, to_env, amount: Decimal) -> Income:
    """Tambahkan transfer internal ke sesi (belum di-commit/flush).

    ID Income dibuat di sisi Python agar Allocation bisa langsung merujuknya
    tanpa flush, sehingga pemanggil bisa meng-commit transfer dan transaksi
    pengeluaran dalam satu commit (atau rollback bersama).
    """
    import uuid
    income = Income(
        id=uuid.uuid4(),
        household_id=household_id,
        user_id=user_id,
        amount=Decimal("0"),  # net nol — bukan pemasukan
        description=f"Transfer: {from_env.name} → {to_env.name}",
    )
    db.add(income)
    db.add(Allocation(income_id=income.id, envelope_id=from_env.id, amount=-amount))
    db.add(Allocation(income_id=income.id, envelope_id=to_env.id, amount=amount))
    return income
