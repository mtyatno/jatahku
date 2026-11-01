from decimal import Decimal
from uuid import UUID
from datetime import date
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import Literal

from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import get_budget_period
from app.models.models import (
    User, Income, Allocation, Envelope, )
from app.services.income_history import parse_transfer
from app.services.ruang import RuangAktif, RuangDitolak, ruang_amplop_satu
from app.services import peran

router = APIRouter()


def _payday(user) -> int:
    return getattr(user, "payday_day", 1) or 1


def _fmt_time(dt, tz) -> str:
    try:
        zone = ZoneInfo(tz or "Asia/Jakarta")
    except Exception:
        zone = ZoneInfo("Asia/Jakarta")
    return dt.astimezone(zone).strftime("%H:%M")


class AllocationItem(BaseModel):
    envelope_id: UUID
    amount: Decimal


class IncomeCreate(BaseModel):
    amount: Decimal
    source: str = "Gaji"
    allocations: list[AllocationItem] = []
    # Klien hanya boleh menyatakan pemasukan biasa atau top-up amplop; transfer dan
    # penyesuaian ditulis server lewat jalurnya sendiri (fund_shift, balance_check).
    kind: Literal["pemasukan", "top-up"] = "pemasukan"
    # R5 (aditif): kunci idempotensi draf penjualan karyawan; kiriman ulang mendapat draf yang sama.
    client_ref: str | None = Field(default=None, max_length=64)


class IncomeResponse(BaseModel):
    id: UUID
    amount: Decimal
    source: str
    allocations: list[dict] = []
    unallocated: Decimal = Decimal("0")
    kind: str = "pemasukan"


async def _get_or_create_tabungan(hid: UUID, db: AsyncSession) -> Envelope:
    """Get or create the Tabungan envelope for auto-allocation of remainder."""
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.name == "Tabungan",
            Envelope.is_active == True,
        )
    )
    tabungan = result.scalar_one_or_none()
    if not tabungan:
        tabungan = Envelope(
            household_id=hid,
            name="Tabungan",
            emoji="💰",
            budget_amount=Decimal("0"),
            is_rollover=True,
        )
        db.add(tabungan)
        await db.flush()
    return tabungan


@router.post("/", response_model=IncomeResponse, status_code=201,
             responses={202: {"description": "Karyawan di atas batas nominal: draf menunggu persetujuan"}})
async def create_income(
    req: IncomeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    # R3: ruang pemasukan = ruang amplop alokasinya (semua harus satu ruang, selain itu 400 lintas_ruang;
    # semua amplop di ruang orang lain = 404, sama dengan objek asing lain, kontrak §1);
    # pemasukan tanpa alokasi = objek baru tanpa induk → ruang dari header (`ruang_aktif`, keanggotaan dicek).
    if req.allocations:
        hid = await ruang_amplop_satu(db, user, [a.envelope_id for a in req.allocations], karyawan=True)
        if not hid:
            raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
    if not hid:
        raise HTTPException(status_code=400, detail="Belum punya household")
    return await catat_pemasukan(req, user, db, hid)


async def catat_pemasukan(req: IncomeCreate, user: User, db: AsyncSession, hid: UUID):
    """Jalur pencatatan pemasukan (route di atas, dan persetujuan draf R5 di dalam `peran.atas_izin_pengelola`)."""
    # Validate allocations don't exceed income
    total_allocated = sum(a.amount for a in req.allocations)
    if total_allocated > req.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Total alokasi (Rp{int(total_allocated):,}) melebihi income (Rp{int(req.amount):,})"
        )

    # Validate all envelopes belong to this household
    for alloc in req.allocations:
        env_check = await db.execute(
            select(Envelope).where(
                Envelope.id == alloc.envelope_id,
                Envelope.household_id == hid,
                or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            )
        )
        if not env_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Amplop {alloc.envelope_id} tidak ditemukan")

    # R5: karyawan di ruang usaha mencatat penjualan dalam batasan; di atas batas nominal → draf. Validasi di atas
    # jalan lebih dulu, supaya draf tidak pernah berisi alokasi yang tidak sah (review PR #175, temuan 5).
    batasan = await peran.batasan_karyawan(db, user.id, hid)
    if batasan is not None:
        draf = await peran.draf_dari_ref(db, user.id, req.client_ref)
        if draf is not None:   # kiriman ulang (temuan 6): status draf terbaru, tanpa draf atau pemasukan kedua
            from app.api.routes.transactions import jawaban_draf
            return jawaban_draf(draf)
    try:
        perlu = peran.cek_catat(batasan, jenis=peran.JENIS_PENJUALAN,
                                amplop_ids=[a.envelope_id for a in req.allocations], jumlah=req.amount, ada_foto=True)
        if batasan is not None and total_allocated != req.amount:
            # Sisa pemasukan otomatis masuk (atau membuat) amplop Tabungan, di luar amplop yang diizinkan (temuan 3).
            raise peran.PeranDitolak(
                "alokasi_tidak_penuh", "Bagikan seluruh penjualan ke amplop yang diizinkan untukmu.", status_code=422)
    except peran.PeranDitolak as exc:
        raise RuangDitolak.dari_peran(exc)
    if perlu:
        from app.api.routes.transactions import jawaban_draf
        draf = await peran.buat_draf(
            db, household_id=hid, user_id=user.id, jenis=peran.JENIS_PENJUALAN, amount=req.amount,
            description=req.source, envelope_id=req.allocations[0].envelope_id if req.allocations else None,
            client_ref=req.client_ref,
            rincian={"kind": req.kind, "allocations": [
                {"envelope_id": str(a.envelope_id), "amount": str(a.amount)} for a in req.allocations]})
        return jawaban_draf(draf, peran.pesan_persetujuan(batasan))

    # Goal yang baru tercapai karena pemasukan ini dinotifikasi (app/services/goal_notify.py)
    from app.services.goal_notify import goal_snapshot, notify_goals_reached
    goals_before = await goal_snapshot(db, hid)

    # Create income
    income = Income(
        household_id=hid,
        user_id=user.id,
        amount=req.amount,
        description=req.source,
        kind=req.kind,
    )
    db.add(income)
    await db.flush()

    # Create allocations
    alloc_details = []
    for alloc in req.allocations:
        if alloc.amount > 0:
            db.add(Allocation(
                income_id=income.id,
                envelope_id=alloc.envelope_id,
                amount=alloc.amount,
            ))
            env = await db.execute(select(Envelope).where(Envelope.id == alloc.envelope_id))
            e = env.scalar_one()
            alloc_details.append({"envelope": e.name, "emoji": e.emoji, "amount": str(alloc.amount)})

    # Auto-allocate remainder to Tabungan
    remainder = req.amount - total_allocated
    if remainder > 0:
        tabungan = await _get_or_create_tabungan(hid, db)
        db.add(Allocation(
            income_id=income.id,
            envelope_id=tabungan.id,
            amount=remainder,
        ))
        alloc_details.append({"envelope": "Tabungan", "emoji": "💰", "amount": str(remainder), "auto": True})

    await db.commit()
    # Notifikasi target (berisi angka) untuk pemilik ruang bila pencatatnya karyawan, juga saat draf disetujui
    # (review PR #175, temuan 4). Peran dibaca langsung, karena `batasan` None di dalam persetujuan.
    penerima = user
    role, jenis = await peran.peran_di_ruang(db, user.id, hid)
    if role == "member" and jenis == "usaha":
        penerima = await peran.owner_ruang(db, hid)
    if penerima is not None:
        await notify_goals_reached(db, penerima, goals_before)

    return IncomeResponse(
        id=income.id,
        amount=income.amount,
        source=income.description,
        allocations=alloc_details,
        unallocated=Decimal("0"),  # always 0 now — remainder goes to Tabungan
        kind=income.kind,
    )


@router.get("/")
async def list_incomes(
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    if not hid:
        return []

    if not period_start or not period_end:
        period_start, period_end = get_budget_period(_payday(user))

    result = await db.execute(
        select(Income)
        .where(
            Income.household_id == hid,
            Income.user_id == user.id,
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
        .order_by(Income.created_at.desc())
    )
    incomes = result.scalars().all()

    output = []
    for inc in incomes:
        alloc_result = await db.execute(
            select(Allocation, Envelope.name, Envelope.emoji, Envelope.purpose)
            .join(Envelope, Allocation.envelope_id == Envelope.id)
            .where(
                Allocation.income_id == inc.id,
                or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            )
        )
        allocs = [
            {"envelope": name, "emoji": emoji, "amount": str(a.amount), "purpose": purpose}
            for a, name, emoji, purpose in alloc_result.all()
        ]
        is_transfer = inc.amount == 0
        output.append({
            "id": str(inc.id),
            "amount": str(inc.amount),
            "source": inc.description,
            "date": inc.income_date.strftime("%Y-%m-%d"),
            "time": _fmt_time(inc.created_at, getattr(user, "timezone", None)),
            "type": "transfer" if is_transfer else "income",
            "allocations": allocs,
            "transfer": parse_transfer(allocs) if is_transfer else None,
            "is_adjustment": getattr(inc, "balance_check_id", None) is not None,
            "kind": inc.kind,
        })
    return output
