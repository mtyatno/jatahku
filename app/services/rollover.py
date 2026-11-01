import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import date
from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.period import get_budget_period, get_closed_periods, periods_to_cover
from app.models.models import Envelope, Transaction, Allocation, MonthlySnapshot, Household, Income

logger = logging.getLogger("jatahku.rollover")

# Batas atas periode yang dihitung ulang `recompute_household` saat riwayat household lebih panjang dari `periods`
# pemanggil (10 tahun). Lewat batas ini rantai di ujung paling tua tidak tercakup; dicatat sebagai warning.
MAX_RECOMPUTE_PERIODS = 120


async def calculate_envelope_balance(env_id, period_start: date, period_end: date, db: AsyncSession) -> dict:
    """Calculate spent and allocated for an envelope within a budget period date range."""
    spent_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.envelope_id == env_id,
            Transaction.is_deleted == False,
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date <= period_end,
        )
    )
    spent = Decimal(str(spent_result.scalar()))

    allocated_result = await db.execute(
        select(func.coalesce(func.sum(Allocation.amount), 0))
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id == env_id,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )
    allocated = Decimal(str(allocated_result.scalar()))

    return {"spent": spent, "allocated": allocated}


async def get_previous_rollover(env_id, year, month, db: AsyncSession) -> Decimal:
    """Get rollover amount from the previous period's snapshot (keyed by period_start year/month).

    The previous snapshot's key is derived by plain calendar arithmetic
    (month - 1). This is correct because every budget period spans exactly one
    payday-to-payday window, so consecutive periods always start in consecutive
    calendar months — i.e. (year, month-1) always equals the previous period's
    period_start year/month, for any payday_day. That invariant is locked by
    app/tests/test_rollover_key_invariant.py; do not "simplify" to a
    most-recent-snapshot lookup, which would silently skip a period if one
    snapshot is missing instead of correctly resolving to the exact predecessor."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    result = await db.execute(
        select(MonthlySnapshot.rollover_amount).where(
            MonthlySnapshot.envelope_id == env_id,
            MonthlySnapshot.year == prev_year,
            MonthlySnapshot.month == prev_month,
        )
    )
    rollover = result.scalar_one_or_none()
    return rollover if rollover is not None else Decimal("0")


@dataclass(frozen=True)
class SnapshotValues:
    """Angka satu snapshot (satu amplop, satu periode). Selalu berlaku:
    `opening - allocated` = rollover yang dibawa masuk, dan `closing = opening - spent`."""
    opening: Decimal
    closing: Decimal
    rollover: Decimal
    allocated: Decimal
    spent: Decimal


def snapshot_values(
    prev_rollover: Decimal, allocated: Decimal, spent: Decimal, is_rollover: bool
) -> SnapshotValues:
    """Hitung angka snapshot dari rollover periode sebelumnya, alokasi, dan pengeluaran periode itu (murni, tanpa IO).

    - opening = alokasi pemasukan nyata periode itu + rollover yang dibawa masuk
    - closing = opening - spent
    - rollover (ke periode berikutnya) = closing penuh, positif maupun negatif, bila amplop is_rollover;
      selain itu 0 (reset)."""
    opening = allocated + prev_rollover
    closing = opening - spent
    rollover = closing if is_rollover else Decimal("0")
    return SnapshotValues(
        opening=opening, closing=closing, rollover=rollover, allocated=allocated, spent=spent
    )


async def create_monthly_snapshots(
    period_start: date,
    period_end: date,
    force: bool = False,
    household_ids: list | None = None,
) -> dict:
    """Create snapshots for envelopes for the given budget period.
    Snapshot is keyed by period_start.year and period_start.month.
    Set force=True to overwrite an existing snapshot.
    Pass household_ids to restrict to specific households (e.g. only those
    whose owner's payday_day matches this period).
    Each snapshot also stores the period's allocated_amount and spent_amount."""
    target_year = period_start.year
    target_month = period_start.month

    async with AsyncSessionLocal() as db:
        if household_ids is not None:
            households = await db.execute(
                select(Household).where(Household.id.in_(household_ids))
            )
        else:
            households = await db.execute(select(Household))
        results = {"processed": 0, "snapshots_created": 0, "errors": []}

        for household in households.scalars().all():
            envelopes_result = await db.execute(
                select(Envelope).where(
                    Envelope.household_id == household.id,
                    Envelope.is_active == True,
                )
            )
            envelopes = envelopes_result.scalars().all()

            for env in envelopes:
                try:
                    # Check if snapshot already exists
                    existing_result = await db.execute(
                        select(MonthlySnapshot).where(
                            MonthlySnapshot.envelope_id == env.id,
                            MonthlySnapshot.year == target_year,
                            MonthlySnapshot.month == target_month,
                        )
                    )
                    existing = existing_result.scalar_one_or_none()
                    if existing:
                        if not force:
                            results["processed"] += 1
                            continue
                        await db.delete(existing)
                        await db.flush()

                    # Get previous rollover (keyed by period_start year/month)
                    prev_rollover = await get_previous_rollover(
                        env.id, target_year, target_month, db
                    )

                    # Calculate actual allocated + spent within this period's date range
                    balance = await calculate_envelope_balance(
                        env.id, period_start, period_end, db
                    )
                    v = snapshot_values(
                        prev_rollover, balance["allocated"], balance["spent"], env.is_rollover
                    )

                    snapshot = MonthlySnapshot(
                        envelope_id=env.id,
                        year=target_year,
                        month=target_month,
                        opening_balance=v.opening,
                        closing_balance=v.closing,
                        rollover_amount=v.rollover,
                        allocated_amount=v.allocated,
                        spent_amount=v.spent,
                    )
                    db.add(snapshot)
                    results["snapshots_created"] += 1

                except Exception as e:
                    results["errors"].append(f"{env.name}: {str(e)}")

                results["processed"] += 1

        await db.commit()
        logger.info(
            f"Snapshots for period {period_start}→{period_end} "
            f"(key {target_year}-{target_month:02d}): "
            f"{results['snapshots_created']} created, {len(results['errors'])} errors"
        )
        return results


async def first_activity_date(db: AsyncSession, household_id) -> date | None:
    """Tanggal aktivitas paling awal household: yang lebih dulu dari transaksi pertama dan pemasukan pertama yang
    dialokasikan ke amplopnya, atau None bila belum ada aktivitas. Batas mundur `recompute_household`.

    Amplop household dipilih seperti `create_monthly_snapshots` memilihnya untuk `household_ids`, tetapi TANPA filter
    `is_active`, dan transaksi tidak disaring `is_deleted`: amplop nonaktif dan transaksi yang sudah dihapus hanya
    memperlebar rentangnya (snapshot lama bisa masih memuatnya). Pemasukan tanpa alokasi tidak pernah masuk snapshot,
    jadi tidak dihitung."""
    first_txn = (await db.execute(
        select(func.min(Transaction.transaction_date))
        .join(Envelope, Envelope.id == Transaction.envelope_id)
        .where(Envelope.household_id == household_id)
    )).scalar()
    first_income = (await db.execute(
        select(func.min(Income.income_date))
        .join(Allocation, Allocation.income_id == Income.id)
        .join(Envelope, Envelope.id == Allocation.envelope_id)
        .where(Envelope.household_id == household_id)
    )).scalar()
    dates = [d for d in (first_txn, first_income) if d is not None]
    return min(dates) if dates else None


async def recompute_household(
    household_id, payday_day: int, periods: int, today: date | None = None
) -> list[dict]:
    """Hitung ulang riwayat snapshot SATU household menurut `payday_day`: periode tertutup oldest-first dan
    force=True, supaya rantai rollover terbangun ulang berurutan (tiap periode melihat pendahulunya yang baru
    dihitung). Mengembalikan satu dict per periode: `{"period": "{awal} → {akhir}", **hasil}` (bentuk respons endpoint
    /snapshots/recompute).

    Berapa periode: `periods` dari pemanggil hanya batas BAWAH. Recompute selalu mundur sampai periode sebelum periode
    yang memuat aktivitas pertama household (`first_activity_date`, `period.periods_to_cover`), dibatasi
    `MAX_RECOMPUTE_PERIODS` dengan warning. Periode tertua yang dihitung ulang membaca rollover kunci sebelumnya, dan
    kunci itu berjendela LAMA bila tanggal gajian baru saja berubah: berhenti di periode ke-`periods` meninggalkan celah
    (hari yang tidak terhitung di mana pun) atau tumpang-tindih (terhitung dua kali) di batas itu, dan rollover
    membawanya ke saldo amplop selamanya.

    Snapshot hanya boleh ada untuk periode tertutup, jadi snapshot household ini pada kunci periode berjalan menurut
    `payday_day` (bulan AWAL periode berjalan) dan sesudahnya dibuang, dan itu dilakukan (dan di-commit) SEBELUM
    periode tertutup dibangun ulang: rebuild yang gagal di tengah jalan tidak boleh meninggalkan kunci periode berjalan
    basi. Kuncinya tidak pernah beririsan dengan yang dibangun ulang (setiap kunci tertutup < kunci periode berjalan),
    jadi urutan ini tidak mengubah angka. Kunci snapshot hanya (tahun, bulan awal periode), tanpa jendela tanggalnya,
    dan job harian tidak menimpa kunci yang sudah ada. Contoh: payday 1 → 25 pada 10 Nov 2026. Kunci 2026-10 ditulis
    job 1 Nov dengan angka 1–31 Okt, padahal di bawah payday 25 kunci itu periode berjalan 25 Okt–24 Nov; dibiarkan,
    job 25 Nov melewatinya (sudah ada) dan rollover yang salah terbawa selamanya ke periode berikutnya. Dibuang, job
    membuatnya lagi dengan benar saat periodenya tutup.

    Tidak ada lock di sini: hanya dipanggil lewat `household_cycle.recompute_history`, yang menserialkan per household.
    Tiap langkah memakai sesinya sendiri dan commit di sana."""
    today = today or date.today()
    async with AsyncSessionLocal() as db:
        first = await first_activity_date(db, household_id)
    if first is not None:
        needed = periods_to_cover(payday_day, first, today)
        if needed > MAX_RECOMPUTE_PERIODS:
            logger.warning(
                "recompute household %s: riwayat sejak %s butuh %s periode, dibatasi %s",
                household_id, first, needed, MAX_RECOMPUTE_PERIODS,
            )
        periods = max(periods, min(needed, MAX_RECOMPUTE_PERIODS))

    open_start, _ = get_budget_period(payday_day, today)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(MonthlySnapshot)
            .where(
                MonthlySnapshot.envelope_id.in_(select(Envelope.id).where(Envelope.household_id == household_id)),
                or_(
                    MonthlySnapshot.year > open_start.year,
                    and_(MonthlySnapshot.year == open_start.year, MonthlySnapshot.month >= open_start.month),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()

    out = []
    for period_start, period_end in get_closed_periods(payday_day, today, periods):
        result = await create_monthly_snapshots(
            period_start, period_end, force=True, household_ids=[household_id]
        )
        out.append({"period": f"{period_start} → {period_end}", **result})
    return out


async def get_effective_budget(env_id, period_start: date, period_end: date, db: AsyncSession) -> Decimal:
    """Get effective budget for an envelope in a given period.
    Effective = actual allocated income + rollover from previous period."""
    env_result = await db.execute(select(Envelope).where(Envelope.id == env_id))
    env = env_result.scalar_one_or_none()
    if not env:
        return Decimal("0")

    prev_rollover = await get_previous_rollover(env_id, period_start.year, period_start.month, db)
    balance = await calculate_envelope_balance(env_id, period_start, period_end, db)
    return balance["allocated"] + prev_rollover
