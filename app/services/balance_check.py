"""Cocokkan saldo — spec docs/superpowers/specs/2026-09-30-cocokkan-saldo-design.md.

Penyesuaian = Transaction/Income BIASA yang ditandai balance_check_id, supaya
semua surface saldo (web, bot TG/WA, advisor, rollover) otomatis konsisten.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func, update, delete

from app.models.models import (
    BalanceCheck, Transaction, Income, Allocation, Household, HouseholdMember, TransactionSource,
)
from app.services.envelope_balance import compute_envelope_summaries, get_household_id

UNIT = Decimal("1000")
ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("10000000000000")  # batas Numeric(15, 2)
# Sama dengan guard create_transaction: tabungan tidak bisa untuk pengeluaran langsung.
NON_SPENDABLE_PURPOSES = ("saving", "sinking_fund")
ADJ_TXN_DESC = "Tak tercatat (cocokkan saldo)"
ADJ_INCOME_DESC = "Penyesuaian saldo"


class BalanceCheckError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Candidate:
    envelope_id: str
    weight: Decimal          # pengeluaran tercatat 30 hari terakhir
    budget_amount: Decimal   # fallback bila semua weight 0


def _rp(amount: Decimal) -> str:
    return f"Rp{int(amount):,}".replace(",", ".")


def classify_gap(gap: Decimal) -> str:
    if gap < 0:
        return "unrecorded_expense"
    if gap > 0:
        return "surplus"
    return "match"


def suggest_distribution(total: Decimal, candidates: list[Candidate]) -> list[Decimal]:
    """Bagi `total` proporsional ke kandidat, dibulatkan ke bawah per Rp1.000.
    Sisa pembulatan ke kandidat berbobot terbesar (seri → yang lebih dulu).
    Invarian: sum(hasil) == total bila ada bobot > 0; semua >= 0."""
    n = len(candidates)
    if total <= 0 or n == 0:
        return [ZERO] * n
    weights = [max(c.weight, ZERO) for c in candidates]
    if sum(weights) <= 0:
        weights = [max(c.budget_amount, ZERO) for c in candidates]
    total_w = sum(weights)
    if total_w <= 0:
        return [ZERO] * n
    amounts = [(total * w / total_w // UNIT) * UNIT for w in weights]
    top = max(range(n), key=lambda i: (weights[i], -i))
    amounts[top] += total - sum(amounts)
    return amounts


def validate_lines(gap: Decimal, lines: list[tuple], spendable_ids: set[str],
                   all_ids: set[str]) -> str | None:
    """Pesan error (untuk HTTP 400) atau None bila pembagian valid."""
    if gap == 0:
        return None if not lines else "Saldo sudah cocok, tidak ada yang perlu dibagi"
    if not lines:
        return "Pembagian selisih belum diisi"
    ids = [str(eid) for eid, _ in lines]
    if len(set(ids)) != len(ids):
        return "Satu amplop hanya boleh muncul sekali"
    if any(amount <= 0 for _, amount in lines):
        return "Nominal harus lebih dari 0"
    total = sum((amount for _, amount in lines), ZERO)
    if gap < 0:
        if any(eid not in spendable_ids for eid in ids):
            return "Amplop tidak valid untuk pengeluaran"
        if total != -gap:
            return f"Total pembagian harus {_rp(-gap)}"
        return None
    if len(lines) != 1:
        return "Uang lebih hanya bisa dimasukkan ke satu amplop"
    if ids[0] not in all_ids:
        return "Amplop tidak valid"
    if total != gap:
        return f"Nominal harus {_rp(gap)}"
    return None


# --- DB ---------------------------------------------------------------------

WEIGHT_WINDOW_DAYS = 30


def _money(value, detail: str) -> Decimal:
    """Nominal uang >= 0, dinormalisasi ke sen (Numeric(15, 2)). NaN/Infinity, negatif, dan
    di luar batas ditolak 400 — bukan InvalidOperation → 500."""
    value = Decimal(value)
    # is_finite() dulu: membandingkan NaN / men-quantize angka raksasa melempar InvalidOperation.
    if not value.is_finite() or value < 0 or value >= MAX_AMOUNT:
        raise BalanceCheckError(400, detail)
    value = value.quantize(CENT)
    if value >= MAX_AMOUNT:  # 9999999999999.995 membulat ke 10^13 → meluap Numeric(15, 2)
        raise BalanceCheckError(400, detail)
    return value


def _app_amount(rows) -> Decimal:
    """Angka "Menurut Jatahku" = Σ remaining amplop terlihat (sama dgn dashboard)."""
    return sum((r["remaining"] for r in rows), ZERO)


def _brief(r) -> dict:
    return {"envelope_id": r["id"], "name": r["name"], "emoji": r["emoji"], "remaining": r["remaining"]}


def _default_income_target(rows):
    """Tabungan (nama) → amplop saving pertama → amplop pertama. Tidak membuat amplop."""
    for r in rows:
        if r["name"] == "Tabungan":
            return r["id"]
    for r in rows:
        if str(r["purpose"]) == "saving":
            return r["id"]
    return rows[0]["id"] if rows else None


def _latest_check_query(hid):
    return (
        select(BalanceCheck)
        .where(BalanceCheck.household_id == hid, BalanceCheck.undone_at.is_(None))
        .order_by(BalanceCheck.created_at.desc())
        .limit(1)
    )


async def load_expense_weights(envelope_ids, db, today: date) -> dict:
    """Σ pengeluaran tercatat (bukan penyesuaian) per amplop, 30 hari terakhir."""
    if not envelope_ids:
        return {}
    result = await db.execute(
        select(Transaction.envelope_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.envelope_id.in_(envelope_ids),
            Transaction.is_deleted == False,
            Transaction.balance_check_id.is_(None),
            Transaction.transaction_date >= today - timedelta(days=WEIGHT_WINDOW_DAYS - 1),
            Transaction.transaction_date <= today,
        )
        .group_by(Transaction.envelope_id)
    )
    return {str(eid): Decimal(str(total)) for eid, total in result.all()}


async def build_preview(user, db, actual_amount: Decimal, today: date | None = None) -> dict:
    """Hitung selisih + saran pembagian. TIDAK menulis apa pun."""
    actual_amount = _money(actual_amount, "Nominal uang riil tidak valid")
    today = today or date.today()
    rows = await compute_envelope_summaries(user, db)
    app_amount = _app_amount(rows)
    gap = actual_amount - app_amount
    direction = classify_gap(gap)

    suggestions = []
    if direction == "unrecorded_expense":
        expense_rows = [r for r in rows if str(r["purpose"]) == "expense"]
        weights = await load_expense_weights([r["id"] for r in expense_rows], db, today)
        amounts = suggest_distribution(-gap, [
            Candidate(str(r["id"]), weights.get(str(r["id"]), ZERO), r["budget_amount"])
            for r in expense_rows
        ])
        suggestions = [
            {**_brief(r), "amount": amt, "remaining_after": r["remaining"] - amt}
            for r, amt in zip(expense_rows, amounts)
        ]

    return {
        "actual_amount": actual_amount,
        "app_amount": app_amount,
        "gap": gap,
        "direction": direction,
        "suggestions": suggestions,
        "expense_targets": [_brief(r) for r in rows if str(r["purpose"]) not in NON_SPENDABLE_PURPOSES],
        "income_targets": [_brief(r) for r in rows],
        "default_target_envelope_id": _default_income_target(rows),
    }


async def apply_balance_check(user, db, actual_amount: Decimal, expected_app_amount: Decimal,
                              lines: list, today: date | None = None) -> dict:
    """Validasi ulang di server lalu tulis log + penyesuaian dalam satu commit."""
    today = today or date.today()
    actual_amount = _money(actual_amount, "Nominal uang riil tidak valid")
    expected_app_amount = Decimal(expected_app_amount)
    if not expected_app_amount.is_finite() or abs(expected_app_amount) >= MAX_AMOUNT:  # boleh negatif
        raise BalanceCheckError(400, "Data selisih tidak valid, cek ulang")
    hid = await get_household_id(user, db)
    if not hid:
        raise BalanceCheckError(400, "Belum punya household")

    # Serialkan apply per household: dua apply bersamaan (double-tap, dua tab, dua anggota)
    # dengan expected_app_amount sama tak boleh sama-sama lolos cek 409 lalu sama-sama commit.
    # Kunci dipegang sampai commit; penerusnya menghitung ulang SETELAH kunci sehingga melihat
    # data yang di-commit pemegang sebelumnya (READ COMMITTED, default engine) → 409.
    await db.execute(select(Household.id).where(Household.id == hid).with_for_update())

    rows = await compute_envelope_summaries(user, db)
    app_amount = _app_amount(rows)
    if app_amount.quantize(CENT) != expected_app_amount.quantize(CENT):
        raise BalanceCheckError(409, "Data berubah, cek ulang selisihnya")
    gap = actual_amount - app_amount

    spendable = {str(r["id"]) for r in rows if str(r["purpose"]) not in NON_SPENDABLE_PURPOSES}
    error = validate_lines(gap, lines, spendable, {str(r["id"]) for r in rows})
    if error:
        raise BalanceCheckError(400, error)

    check = BalanceCheck(household_id=hid, user_id=user.id, actual_amount=actual_amount,
                         app_amount=app_amount, gap=gap)
    db.add(check)
    await db.flush()

    txns, income = [], None
    if gap < 0:
        for envelope_id, amount in lines:
            txn = Transaction(
                envelope_id=envelope_id, user_id=user.id, amount=amount,
                description=ADJ_TXN_DESC, source=TransactionSource.webapp,
                transaction_date=today, is_private=False, balance_check_id=check.id,
            )
            db.add(txn)
            txns.append(txn)
    elif gap > 0:
        envelope_id, amount = lines[0]
        income = Income(household_id=hid, user_id=user.id, amount=amount,
                        description=ADJ_INCOME_DESC, income_date=today,
                        balance_check_id=check.id)
        db.add(income)
        await db.flush()
        db.add(Allocation(income_id=income.id, envelope_id=envelope_id, amount=amount))
    await db.flush()
    await db.commit()
    return {
        "id": check.id,
        "gap": gap,
        "app_amount": app_amount,
        "transaction_ids": [t.id for t in txns],
        "income_id": income.id if income else None,
    }


async def undo_balance_check(user, db, check_id) -> dict:
    """Batalkan cek TERAKHIR household (hanya oleh pembuatnya)."""
    hid = await get_household_id(user, db)
    if not hid:
        raise BalanceCheckError(404, "Penyesuaian tidak ditemukan")
    latest = (await db.execute(_latest_check_query(hid))).scalar_one_or_none()
    if latest is None or str(latest.id) != str(check_id):
        raise BalanceCheckError(400, "Hanya penyesuaian terakhir yang bisa dibatalkan")
    if str(latest.user_id) != str(user.id):
        raise BalanceCheckError(403, "Hanya pembuat penyesuaian yang bisa membatalkan")

    await db.execute(
        update(Transaction)
        .where(Transaction.balance_check_id == latest.id)
        .values(is_deleted=True)
    )
    income_ids = (await db.execute(
        select(Income.id).where(Income.balance_check_id == latest.id)
    )).scalars().all()
    if income_ids:
        await db.execute(delete(Allocation).where(Allocation.income_id.in_(income_ids)))
        await db.execute(delete(Income).where(Income.id.in_(income_ids)))
    latest.undone_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "undone", "id": latest.id}


async def get_status(user, db) -> dict:
    hid = await get_household_id(user, db)
    if not hid:
        return {"last_checked_at": None, "last_gap": None, "member_count": 0}
    latest = (await db.execute(_latest_check_query(hid))).scalar_one_or_none()
    member_count = (await db.execute(
        select(func.count()).select_from(HouseholdMember).where(HouseholdMember.household_id == hid)
    )).scalar() or 0
    return {
        "last_checked_at": latest.created_at if latest else None,
        "last_gap": latest.gap if latest else None,
        "member_count": member_count,
    }
