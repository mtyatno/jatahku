import logging
from datetime import date
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.period import get_period_for_month
from app.models.models import User, MonthlySnapshot, Envelope, Household, HouseholdMember
from app.services.household_cycle import (
    current_payday, household_lock, household_payday, payday_context, recompute_history,
)
from app.services.rollover import create_monthly_snapshots, get_previous_rollover
from app.services.ruang import RuangAktif, RuangTulis

logger = logging.getLogger("jatahku.snapshots")
router = APIRouter()


class SnapshotResponse(BaseModel):
    envelope_id: UUID
    envelope_name: str
    year: int
    month: int
    opening_balance: Decimal
    closing_balance: Decimal
    rollover_amount: Decimal


@router.get("/", response_model=list[SnapshotResponse])
async def list_snapshots(
    year: int = Query(None),
    month: int = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    """List monthly snapshots for user's household."""
    now = date.today()
    y = year or now.year
    m = month or now.month

    if not hid:
        return []

    result = await db.execute(
        select(MonthlySnapshot, Envelope.name)
        .join(Envelope, MonthlySnapshot.envelope_id == Envelope.id)
        .where(
            Envelope.household_id == hid,
            MonthlySnapshot.year == y,
            MonthlySnapshot.month == m,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
        .order_by(Envelope.created_at)
    )
    rows = result.all()

    return [
        SnapshotResponse(
            envelope_id=snap.envelope_id,
            envelope_name=name,
            year=snap.year,
            month=snap.month,
            opening_balance=snap.opening_balance,
            closing_balance=snap.closing_balance,
            rollover_amount=snap.rollover_amount,
        )
        for snap, name in rows
    ]


@router.post("/run")
async def run_monthly_snapshot(
    year: int = Query(None),
    month: int = Query(None),
    force: bool = Query(False),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger snapshot for a budget period (admin/debug).
    year/month refer to period_start year/month. Setiap household yang punya anggota dihitung dengan tanggal gajian
    rumahnya sendiri (bukan tanggal si pemanggil), jadi periode tiap household bisa berbeda.

    Hanya periode yang sudah TERTUTUP yang ditulis (hari terakhirnya sebelum hari ini). Periode yang sedang berjalan
    atau belum mulai dilewati dengan entri `"skipped": "periode belum tertutup"`: job harian (tanpa `force`) tidak
    pernah menimpa kunci yang sudah ada, jadi snapshot berisi angka setengah jalan, atau yang dibuat sebelum
    pendahulunya ada, membawa rollover yang salah ke semua periode sesudahnya. Tanpa year/month (bulan berjalan)
    karenanya tidak ada yang ditulis: periode yang mulai bulan ini belum pernah tertutup.

    Tiap household diproses di dalam `household_lock` (kunci yang sama dengan recompute dan job harian) dengan tanggal
    gajian yang dibaca ULANG di dalam kunci (`current_payday`), bukan tanggal yang dibaca sebelum menunggu kunci.
    Household yang sudah dihapus dilewati (`"skipped": "household tidak ada"`), dan kegagalan satu household dicatat
    (entri `"errors": ["gagal: <kelas exception>"]`) tanpa menghentikan yang lain.

    `force=true` pada periode tertutup yang lampau menulis ulang SATU mata rantai saja: periode sesudahnya tetap membawa
    rollover lama. Untuk memperbaiki rantai, pakai `POST /snapshots/recompute` (owner/admin rumah itu) atau skrip
    `app.scripts.siklus_household --apply`, yang membangun ulang seluruh riwayat oldest-first."""
    today = date.today()
    y = year or today.year
    m = month or today.month

    households = (await db.execute(
        select(Household).where(Household.id.in_(select(HouseholdMember.household_id)))
    )).scalars().all()

    # Tahap pertama: tanggal rumah yang NULL diisi (`household_payday` flush di sesi ini) dan di-commit sebelum tahap
    # kedua: `current_payday` dan `create_monthly_snapshots` bekerja lewat sesinya sendiri dan tidak boleh berhadapan
    # dengan UPDATE yang belum di-commit (kontrak yang sama dengan `household_cycle.recompute_history`). Nilainya
    # sengaja tidak dipakai untuk jendela: tanggal dibaca ulang di dalam kunci.
    household_ids = []
    for h in households:
        await household_payday(db, h)
        household_ids.append(h.id)
    await db.commit()

    out = [await _run_household(household_id, y, m, force, today) for household_id in household_ids]
    return {
        "households": out,
        "processed": sum(e["processed"] for e in out),
        "snapshots_created": sum(e["snapshots_created"] for e in out),
        "errors": [err for e in out for err in e["errors"]],
    }


async def _run_household(household_id, year: int, month: int, force: bool, today: date) -> dict:
    """Satu household untuk `POST /snapshots/run`: di dalam `household_lock`, tanggal dibaca di dalam kunci, dan hanya
    periode tertutup yang ditulis. Selalu mengembalikan entri dengan `household_id`, `period` (`"awal → akhir"`, None
    bila household-nya sudah tidak ada atau gagal sebelum jendelanya diketahui), `processed`, `snapshots_created`, dan
    `errors`, ditambah `skipped` (alasan) bila dilewati. Exception dicatat dan menjadi entri gagal."""
    entry = {"household_id": str(household_id), "period": None}
    try:
        async with household_lock(household_id):
            payday = await current_payday(household_id)
            if payday is None:
                return {**entry, **_nothing_done(), "skipped": "household tidak ada"}
            period_start, period_end = get_period_for_month(payday, year, month)
            entry["period"] = f"{period_start} → {period_end}"
            if period_end >= today:
                return {**entry, **_nothing_done(), "skipped": "periode belum tertutup"}
            result = await create_monthly_snapshots(
                period_start, period_end, force=force, household_ids=[household_id]
            )
        return {**entry, **result}
    except Exception as e:
        logger.exception("snapshot run household %s gagal", household_id)
        return {**entry, **_nothing_done(), "errors": [f"gagal: {type(e).__name__}"]}


def _nothing_done() -> dict:
    """Angka entri household yang tidak menulis apa pun (daftar `errors` baru tiap kali)."""
    return {"processed": 0, "snapshots_created": 0, "errors": []}


@router.post("/recompute")
async def recompute_snapshots(
    periods: int = Query(
        6, ge=1, le=36,
        description=(
            "Jumlah MINIMAL periode tertutup terakhir yang dihitung ulang. Recompute selalu mundur sampai periode "
            "sebelum aktivitas pertama household, jadi riwayat yang lebih panjang tetap terhitung ulang seluruhnya."
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangTulis,
):
    """Hitung ulang riwayat snapshot household pemanggil, oldest-first dan force=True, dengan tanggal gajian rumah
    (bukan tanggal si pemanggil), supaya rantai rollover terbangun ulang dari ujung ke ujung. `periods` adalah batas
    bawah: recompute selalu mundur sampai periode sebelum aktivitas pertama household (`rollover.recompute_household`),
    karena endpoint ini alat pemulihan (rantai yang rusak karena job snapshot terlewat, atau recompute perubahan tanggal
    yang gagal), dan rantai hanya utuh bila dibangun dari awal riwayat.

    Siklus milik rumah, jadi hanya yang boleh mengubahnya (owner/admin, atau member yang sendirian) yang boleh
    menghitung ulang riwayat; member lain mendapat 403. Household-nya ruang tulis R2 (`hid`; sampai R3 selalu ruang
    keluarga), dan izin dihitung untuk household itu juga (`payday_context(..., household_id=hid)`), jadi sejak R3
    recompute dan izinnya ikut ruang yang ditulis. Tanpa household, atau bukan anggotanya, tidak ada yang dihitung."""
    ctx = await payday_context(db, user, household_id=hid) if hid is not None else None
    if ctx is None:
        return {"recomputed": 0, "periods": []}
    if not ctx.can_change:
        raise HTTPException(
            status_code=403,
            detail="Hanya owner atau admin rumah tangga yang bisa menghitung ulang riwayat.",
        )
    # `recompute_history` membaca lewat sesinya sendiri dan tidak boleh berhadapan dengan tulisan sesi ini yang belum
    # di-commit: `payday_context` bisa mengisi tanggal rumah yang NULL (flush). Commit dulu (lihat docstring
    # `household_cycle.recompute_history`).
    await db.commit()
    out = await recompute_history(hid, periods)
    return {"recomputed": len(out), "periods": out}


@router.post("/daily-summary")
async def trigger_daily_summary(user: User = Depends(require_admin)):
    from app.services.summary import send_daily_summary
    await send_daily_summary()
    return {"status": "sent"}

@router.post("/weekly-summary")
async def trigger_weekly_summary(user: User = Depends(require_admin)):
    from app.services.summary import send_weekly_summary
    await send_weekly_summary()
    return {"status": "sent"}


@router.post("/process-recurring")
async def trigger_recurring(user: User = Depends(require_admin)):
    from app.services.recurring_processor import process_recurring_transactions
    await process_recurring_transactions()
    return {"status": "processed"}
