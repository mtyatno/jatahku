"""Aturan pencatatan pengeluaran — SATU sumber untuk web (routes/transactions.py)
dan bot Telegram (bot/handlers.py, bot/batch_cmd.py).

Jangan menambah/mengubah aturan pengeluaran di satu kanal saja: ubah di sini
supaya web dan Telegram selalu memutuskan hal yang sama.

Urutan cek (check_expense):
1. Amplop tabungan / sinking fund tidak bisa untuk pengeluaran langsung.
2. Batas transaksi per bulan sesuai paket (Basic: 50, Pro: tanpa batas) — hanya
   di AWAL input: langkah lanjutan input yang sama (antrean multi-item, geser
   dana) memakai skip_plan_limit=True, jadi input yang dimulai saat kuota masih
   ada selalu selesai utuh (aturan pemilik produk, 15 Okt 2026).
3. check_behavior: kunci amplop, dana (belum didanai / tidak cukup), limit
   harian. Cooling period tidak lagi menahan pencatatan (Pikir-Pikir Fase 0).
   Struk/bukti periode lalu yang dicatat di tanggalnya: PAST_PERIOD_IGNORED.
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
# Struk/bukti dari periode lalu yang dicatat di tanggalnya (bot: jawaban "📅 {tanggal}", payload `past_period`; web:
# baris dengan `receipt_item_id` bertanggal sebelum awal periode berjalan): dana dan limit harian periode berjalan
# bukan urusannya, jadi blok ini dilewati tanpa tawaran geser dana atau naikkan limit. Kunci amplop, kuota paket,
# amplop tabungan, dan galat tetap memblokir.
PAST_PERIOD_IGNORED = (*FUNDS_BLOCKS, "daily_limit")


def envelope_purpose(env) -> str:
    """purpose bisa enum atau string (lihat AGENTS.md) — normalisasi ke string."""
    p = getattr(env, "purpose", None)
    return str(getattr(p, "value", p) or "expense")


def is_spendable(env) -> bool:
    """Boleh jadi tujuan pengeluaran langsung (dropdown web juga menyaring ini)."""
    return envelope_purpose(env) not in NON_SPENDABLE_PURPOSES


async def check_expense(envelope, user, amount: Decimal, db, *,
                        skip_plan_limit: bool = False) -> BehaviorCheckResult:
    """Semua aturan sebelum pengeluaran dicatat. check_type tambahan di luar
    check_behavior: "not_spendable" dan "plan_limit".

    skip_plan_limit: langkah lanjutan dari input yang sudah lolos cek kuota di awal."""
    if not is_spendable(envelope):
        return BehaviorCheckResult.blocked(
            "not_spendable", NOT_SPENDABLE_MSG, envelope_name=envelope.name)
    if not skip_plan_limit:
        ok, msg = await check_transaction_limit(user, db, household_id=getattr(envelope, "household_id", None))
        if not ok:
            return BehaviorCheckResult.blocked("plan_limit", msg)
    return await check_behavior(envelope.id, user.id, Decimal(amount), db)


async def after_expense_recorded(db, user, envelope_id, description: str, learn_text: str | None = None):
    """Efek best-effort setelah pengeluaran tercatat (dan di-commit): streak
    disiplin dan pembelajaran kata kunci → amplop. Tidak pernah menggagalkan
    transaksi. Mengembalikan hasil streak (atau None) untuk ditampilkan bot.

    `learn_text` (Kotak Struk): None → kata kunci dipelajari dari `description` (perilaku
    lama); string → dari string itu; string kosong → tidak belajar kata kunci (streak tetap).
    Untuk bukti bayar, server mengisinya dengan catatan user saja (`learn_text_for_item`)."""
    streak = None
    try:
        from app.services.streak import record_activity
        streak = await record_activity(db, user.id, getattr(user, "timezone", None))
    except Exception:
        pass
    try:
        from app.services.txn_nlp import save_learned_keywords
        if learn_text is None or learn_text:
            await save_learned_keywords(user.id, description if learn_text is None else learn_text, envelope_id, db)
        await db.commit()
    except Exception:
        pass
    return streak
