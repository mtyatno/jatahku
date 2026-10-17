"""Mengisi amplop yang kurang dana — SATU sumber aturan untuk web
(FundEnvelopeModal → POST /envelopes/transfer, POST /incomes) dan bot Telegram.

Dua cara, sama dengan dua tab di modal web:
- Geser Amplop: transfer net-nol dari amplop lain. Sumber yang sah = amplop
  aktif lain yang sisanya (remaining) > 0; jumlah maksimal = sisa sumber.
- Top-up Pemasukan: pemasukan baru yang 100% dialokasikan ke amplop tujuan.

Setiap jalur yang memindah dana antar amplop memegang `lock_household` sebelum
menghitung saldo: POST /envelopes/transfer, POST /advisor/execute, geser dana di bot
(satu item & multi-item, termasuk chat web), dan hapus amplop (sisa → Tabungan).
"""
from decimal import Decimal

from app.models.models import Allocation, Income

# Berapa banyak amplop sumber yang ditawarkan sebagai tombol di Telegram.
MAX_SOURCES = 4


async def lock_household(db, hid) -> None:
    """Kunci baris household sampai commit/rollback (`FOR NO KEY UPDATE`, pola
    balance_check.apply). Ambil SEBELUM saldo dihitung ulang: dua geser dana
    bersamaan diserialkan, dan penerus kunci melihat data yang sudah di-commit
    pemegang sebelumnya (READ COMMITTED), jadi tidak sama-sama lolos cek sisa sumber.
    key_share=True tidak memblokir insert ber-FK ke household (pemasukan, amplop)."""
    from sqlalchemy import select
    from app.models.models import Household
    await db.execute(select(Household.id).where(Household.id == hid).with_for_update(key_share=True))


def compute_shortfall(target_remaining: Decimal, amount: Decimal) -> Decimal:
    """Kekurangan dana agar `amount` bisa dicatat di amplop dengan sisa
    `target_remaining` (boleh negatif bila amplop sudah minus). Sama dengan
    neededAmount di web."""
    return max(Decimal(amount) - Decimal(target_remaining), Decimal("0"))


def max_transferable(source_row: dict) -> Decimal:
    """Batas geser dari satu amplop = sisanya (sama dengan modal web)."""
    return max(Decimal(source_row["remaining"]), Decimal("0"))


def transfer_error(source_row: dict | None, target_row: dict | None, amount: Decimal) -> str | None:
    """Alasan transfer ditolak, atau None bila sah. Dipakai endpoint web dan bot.

    `*_row` = baris saldo amplop (dict dengan envelope/name & remaining) milik
    amplop aktif yang boleh diakses user; None = tidak ditemukan.
    """
    if source_row is None or target_row is None:
        return "Amplop tidak ditemukan"
    if Decimal(amount) <= 0:
        return "Jumlah harus lebih dari 0"
    src_id = source_row.get("id") or source_row["envelope"].id
    dst_id = target_row.get("id") or target_row["envelope"].id
    if str(src_id) == str(dst_id):
        return "Amplop sumber dan tujuan tidak boleh sama"
    limit = max_transferable(source_row)
    if Decimal(amount) > limit:
        name = source_row.get("name") or source_row["envelope"].name
        return f"Maksimal transfer dari {name}: Rp{int(limit):,}".replace(",", ".")
    return None


def pick_sources(envelope_data: list[dict], target_id, shortfall: Decimal,
                 limit: int = MAX_SOURCES) -> list[dict]:
    """Amplop yang bisa menutup seluruh kekurangan sendirian, sisa terbesar
    dulu (urutan pilihan di modal web). Sumber sah sama dengan web: amplop lain
    mana pun (termasuk tabungan) yang sisanya cukup.

    `envelope_data` = keluaran get_envelopes_with_spent (dict berisi envelope,
    remaining, reserved, free).
    """
    if shortfall <= 0:
        return []
    candidates = [
        e for e in envelope_data
        if str(e["envelope"].id) != str(target_id)
        and max_transferable(e) >= shortfall
    ]
    candidates.sort(key=lambda e: -Decimal(e["remaining"]))
    return candidates[:limit]


def record_transfer(db, household_id, user_id, from_env, to_env, amount: Decimal) -> Income:
    """Tambahkan transfer internal ke sesi (belum di-commit/flush). Bentuknya
    sama persis dengan POST /envelopes/transfer: Income bernilai 0 + dua
    Allocation (negatif di sumber, positif di tujuan).

    ID Income dibuat di sisi Python agar Allocation bisa langsung merujuknya
    tanpa flush, sehingga pemanggil bisa meng-commit transfer dan transaksi
    pengeluaran dalam satu commit (atau membatalkannya bersama).
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


def topup_description(env) -> str:
    """Keterangan bawaan tab Top-up Pemasukan di modal web."""
    return f"Top-up {env.name}"


def record_topup(db, household_id, user_id, env, amount: Decimal) -> Income:
    """Pemasukan baru yang 100% dialokasikan ke `env` — hasilnya sama dengan
    POST /incomes dari tab Top-up Pemasukan (alokasi penuh → tanpa sisa ke
    Tabungan). Belum di-commit/flush."""
    import uuid
    income = Income(
        id=uuid.uuid4(),
        household_id=household_id,
        user_id=user_id,
        amount=Decimal(amount),
        description=topup_description(env),
    )
    db.add(income)
    db.add(Allocation(income_id=income.id, envelope_id=env.id, amount=Decimal(amount)))
    return income
