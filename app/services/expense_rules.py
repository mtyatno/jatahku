"""Aturan pencatatan pengeluaran — SATU sumber untuk web (routes/transactions.py)
dan bot Telegram (bot/handlers.py, bot/batch_cmd.py).

Jangan menambah/mengubah aturan pengeluaran di satu kanal saja: ubah di sini
supaya web dan Telegram selalu memutuskan hal yang sama.

Urutan cek (check_expense):
1. Amplop tabungan / sinking fund tidak bisa untuk pengeluaran langsung.
2. Batas transaksi per bulan sesuai paket (Basic: 50, Pro: tanpa batas).
3. check_behavior: kunci amplop, dana (belum didanai / tidak cukup), limit
   harian. Cooling period tidak lagi menahan pencatatan (Pikir-Pikir Fase 0).
"""
from decimal import Decimal

from app.services.behavior import BehaviorCheckResult, check_behavior
from app.services.plan_limits import check_transaction_limit

NON_SPENDABLE_PURPOSES = ("saving", "sinking_fund")
NOT_SPENDABLE_MSG = (
    "Amplop tabungan tidak bisa untuk pengeluaran langsung. "
    "Transfer dana ke amplop expense terlebih dahulu."
)
FUNDS_BLOCKS = ("not_funded", "insufficient")


def envelope_purpose(env) -> str:
    """purpose bisa enum atau string (lihat AGENTS.md) — normalisasi ke string."""
    p = getattr(env, "purpose", None)
    return str(getattr(p, "value", p) or "expense")


def is_spendable(env) -> bool:
    """Boleh jadi tujuan pengeluaran langsung (dropdown web juga menyaring ini)."""
    return envelope_purpose(env) not in NON_SPENDABLE_PURPOSES


async def check_expense(envelope, user, amount: Decimal, db) -> BehaviorCheckResult:
    """Semua aturan sebelum pengeluaran dicatat. check_type tambahan di luar
    check_behavior: "not_spendable" dan "plan_limit"."""
    if not is_spendable(envelope):
        return BehaviorCheckResult.blocked(
            "not_spendable", NOT_SPENDABLE_MSG, envelope_name=envelope.name)
    ok, msg = await check_transaction_limit(user, db)
    if not ok:
        return BehaviorCheckResult.blocked("plan_limit", msg)
    return await check_behavior(envelope.id, user.id, Decimal(amount), db)


async def after_expense_recorded(db, user, envelope_id, description: str):
    """Efek best-effort setelah pengeluaran tercatat (dan di-commit): streak
    disiplin dan pembelajaran kata kunci → amplop. Tidak pernah menggagalkan
    transaksi. Mengembalikan hasil streak (atau None) untuk ditampilkan bot."""
    streak = None
    try:
        from app.services.streak import record_activity
        streak = await record_activity(db, user.id, getattr(user, "timezone", None))
    except Exception:
        pass
    try:
        from app.services.txn_nlp import save_learned_keywords
        await save_learned_keywords(user.id, description, envelope_id, db)
        await db.commit()
    except Exception:
        pass
    return streak
