"""Cocokkan saldo — spec docs/superpowers/specs/2026-09-30-cocokkan-saldo-design.md.

Penyesuaian = Transaction/Income BIASA yang ditandai balance_check_id, supaya
semua surface saldo (web, bot TG/WA, advisor, rollover) otomatis konsisten.
"""
from dataclasses import dataclass
from decimal import Decimal

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
