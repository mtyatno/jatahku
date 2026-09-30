"""Cocokkan saldo — spec docs/superpowers/specs/2026-09-30-cocokkan-saldo-design.md."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.services import balance_check as svc

router = APIRouter()


class PreviewRequest(BaseModel):
    actual_amount: Decimal


class ApplyLine(BaseModel):
    envelope_id: UUID
    # Numeric(15, 2): tolak sub-sen, nol/negatif, dan nominal raksasa saat parsing (422).
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class ApplyRequest(BaseModel):
    actual_amount: Decimal
    expected_app_amount: Decimal
    lines: list[ApplyLine] = []


def _http(e: svc.BalanceCheckError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/status")
async def balance_check_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_status(user, db)


@router.post("/preview")
async def balance_check_preview(
    req: PreviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.build_preview(user, db, req.actual_amount)
    except svc.BalanceCheckError as e:
        raise _http(e)


@router.post("/apply")
async def balance_check_apply(
    req: ApplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.apply_balance_check(
            user, db, req.actual_amount, req.expected_app_amount,
            [(line.envelope_id, line.amount) for line in req.lines],
        )
    except svc.BalanceCheckError as e:
        raise _http(e)


@router.post("/{check_id}/undo")
async def balance_check_undo(
    check_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.undo_balance_check(user, db, check_id)
    except svc.BalanceCheckError as e:
        raise _http(e)
