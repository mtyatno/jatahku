from datetime import date
from typing import Literal
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.services.advisor import (
    build_advisor_insights,
    build_allocation_recommendation,
    build_sinking_fund_advice,
)

router = APIRouter()


class AllocationRecommendationRequest(BaseModel):
    income_amount: Decimal


@router.get("/insights")
async def advisor_insights(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await build_advisor_insights(user, db)


@router.post("/allocation-recommendation")
async def allocation_recommendation(
    req: AllocationRecommendationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.income_amount <= 0:
        raise HTTPException(status_code=400, detail="Income amount must be positive")
    return await build_allocation_recommendation(user, req.income_amount, db)


@router.get("/page/alokasi")
async def alokasi_page(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Halaman Alokasi (S14): INC-04/INC-03 di atas form + amplop penerima sisa income."""
    from app.services.advisor.allocation import build_alokasi_page
    return await build_alokasi_page(user, db)


@router.get("/sinking-funds")
async def sinking_fund_advice(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await build_sinking_fund_advice(user, db)


# ── AI Advisor v2: perencana dana (S5, 02-aturan.md §8, 04-kontrak-api.md) ──
class KebutuhanItem(BaseModel):
    tujuan_id: UUID
    jumlah: Decimal
    bayar_recurring_id: UUID | None = None
    tenggat: date | None = None


class PlanRequest(BaseModel):
    kebutuhan: list[KebutuhanItem] = Field(min_length=1, max_length=10)
    kecuali: list[UUID] = Field(default_factory=list, max_length=50)    # sumber yang dilepas user
    sertakan: list[UUID] = Field(default_factory=list, max_length=20)   # tabungan yang dipilih user (d, e)


class RencanaKe(BaseModel):
    tujuan_id: UUID
    jumlah: Decimal


class RencanaRow(BaseModel):
    dari_id: UUID
    jumlah: Decimal | None = None
    tercentang: bool = True
    ke: list[RencanaKe] = Field(default_factory=list, max_length=10)


class BayarItem(BaseModel):
    recurring_id: UUID
    jumlah: Decimal | None = None


class ExecuteRequest(BaseModel):
    rencana: list[RencanaRow] = Field(default_factory=list, max_length=50)
    bayar: list[BayarItem] = Field(default_factory=list, max_length=10)
    saldo_versi: str = Field(max_length=64)
    client_ref: str | None = Field(default=None, max_length=100)
    kebutuhan: list[KebutuhanItem] | None = Field(default=None, max_length=10)  # untuk rencana_baru saat 409
    kecuali: list[UUID] = Field(default_factory=list, max_length=50)
    sertakan: list[UUID] = Field(default_factory=list, max_length=20)


def _plan_error(exc):
    if exc.status == 409 and exc.rencana_baru is not None:
        return JSONResponse(status_code=409, content={"detail": exc.detail, "rencana_baru": exc.rencana_baru})
    raise HTTPException(status_code=exc.status, detail=exc.detail)


@router.post("/plan")
async def advisor_plan(
    req: PlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.advisor.execute import PlanError, build_plan
    try:
        return await build_plan(
            user, db, [k.model_dump(mode="json") for k in req.kebutuhan],
            kecuali=[str(x) for x in req.kecuali], sertakan=[str(x) for x in req.sertakan],
        )
    except PlanError as exc:
        return _plan_error(exc)


@router.post("/execute")
async def advisor_execute(
    req: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.advisor.execute import PlanError, execute_plan
    try:
        return await execute_plan(user, db, req.model_dump(mode="json"))
    except PlanError as exc:
        return _plan_error(exc)


# ── AI Advisor v2: dashboard & dismiss (S3, 02-aturan.md §7, §9, 04-kontrak-api.md) ──
@router.get("/dashboard")
async def advisor_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.advisor.dashboard import get_dashboard
    return await get_dashboard(user, db)


class DismissRequest(BaseModel):
    kunci: str = Field(min_length=3, max_length=200)
    pilihan: Literal["nanti", "periode", "tidak_relevan"] = "nanti"


@router.post("/dismiss", status_code=204)
async def advisor_dismiss(
    req: DismissRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.advisor.dashboard import dismiss
    await dismiss(user, db, req.kunci, req.pilihan)
    return Response(status_code=204)


@router.delete("/dismiss", status_code=204)
async def advisor_batal_dismiss(
    kunci: str = Query(min_length=3, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Urungkan / Munculkan lagi (§9, #91). Idempoten: 204 walau tidak ada yang disembunyikan;
    503 bila penyimpanan dismiss gagal (insight mungkin masih tersembunyi)."""
    from app.services.advisor.dashboard import batal_dismiss
    if await batal_dismiss(user, db, kunci) is None:
        raise HTTPException(503, "Gagal memunculkan lagi, coba sebentar lagi")
    return Response(status_code=204)
