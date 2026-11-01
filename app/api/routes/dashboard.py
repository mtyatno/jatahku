"""Beranda berbasis registry (Plugin B1): `/dashboard/*`, kontrak di docs/plugin/04-kontrak-api.md §4.

Semua endpoint baru (API hanya bertambah). Ruang = `ruang_aktif` (header `X-Jatahku-Ruang`, tanpa
header ruang keluarga; R2). Tata letak adalah dokumen milik user per ruang, jadi `PUT /layout` juga
memakai ruang aktif (keanggotaan sudah diperiksa resolver). Body tidak pernah membawa ruang.
Galat memakai `detail` teks siap tampil + `kode` untuk mesin (§7).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.services.dashboard import batch, layout, registry
from app.services.ruang import RuangAktif

router = APIRouter()

FLAG_KEY = "beranda_registry_users"   # AppSetting: daftar user_id dipisah koma, atau `*` (B2–B3)


async def _flag_aktif(db, user_id) -> bool:
    from sqlalchemy import select
    from app.models.models import AppSetting
    from app.services.advisor.dashboard import flag_aktif
    value = (await db.execute(select(AppSetting.value).where(AppSetting.key == FLAG_KEY))).scalar_one_or_none()
    return flag_aktif(value, user_id)

Surface = Literal["beranda"]


def _galat(status: int, kode: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "kode": kode})


def _tanpa_ruang() -> JSONResponse:
    return _galat(404, "ruang_tidak_ada", "Kamu belum punya rumah tangga. Selesaikan pengaturan awal dulu.")


class LayoutPut(BaseModel):
    surface: Surface = "beranda"
    if_version: int = Field(ge=0)
    items: list[dict[str, Any]] = Field(max_length=registry.MAX_ITEMS)
    removed: list[str] = Field(default_factory=list, max_length=registry.MAX_ITEMS)


class DataItem(BaseModel):
    id: str = Field(pattern=registry.ID_RE.pattern)
    card: str = Field(max_length=80)
    settings: dict[str, Any] = Field(default_factory=dict)


class DataRequest(BaseModel):
    periode: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    items: list[DataItem] = Field(min_length=1, max_length=registry.MAX_ITEMS)


@router.get("/layout")
async def get_layout(
    surface: Surface = Query("beranda"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    if not hid:
        return _tanpa_ruang()
    doc = await layout.ambil(db, user.id, hid, surface)
    # Beranda web memakai registry hanya bila user ada di flag (B2); selain itu tetap Beranda lama.
    return {**doc, "enabled": await _flag_aktif(db, user.id)}


@router.put("/layout")
async def put_layout(
    req: LayoutPut,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    user_id = user.id
    if not hid:
        return _tanpa_ruang()
    try:
        tersimpan = await layout.simpan(db, user_id, hid, req.surface, req.if_version, req.items, req.removed)
    except layout.GalatTataLetak as exc:
        return _galat(exc.status, exc.kode, exc.detail)
    return {"layout": tersimpan, "version": tersimpan["version"]}


@router.get("/cards")
async def get_cards(user: User = Depends(get_current_user)):
    # Semua kartu inti boleh untuk semua peran ruang keluarga; kartu laporan usaha khusus admin (H/U).
    return registry.katalog()


@router.post("/data")
async def post_data(
    req: DataRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,  # POST yang hanya membaca
):
    ids = [i.id for i in req.items]
    if len(set(ids)) != len(ids):
        return _galat(422, "instans_tidak_sah", "Ada ID kartu ganda.")
    if not hid:
        return _tanpa_ruang()
    try:
        periode = await batch.tentukan_periode(user, req.periode)
    except batch.PeriodeTidakDikenal as exc:
        return _galat(422, "periode_tidak_dikenal", str(exc))
    return await batch.jalankan(user, db, periode, [i.model_dump() for i in req.items], household_id=hid)


@router.get("/data/{instance_id}")
async def get_data_instance(
    instance_id: str = Path(pattern=registry.ID_RE.pattern),
    surface: Surface = Query("beranda"),
    periode: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    *,
    hid: RuangAktif,
):
    """Satu instans dari tata letak user sendiri (kartu dan pengaturannya diambil dari dokumen
    tersimpan, bukan dari klien). Bentuk sama dengan satu entri `data` di `POST /dashboard/data`."""
    if not hid:
        return _tanpa_ruang()
    doc = await layout.ambil(db, user.id, hid, surface)
    item = next((i for i in doc["items"] if i["id"] == instance_id), None)
    if item is None:
        return _galat(404, "instans_tidak_ada", "Kartu ini tidak ada di Berandamu.")
    try:
        p = await batch.tentukan_periode(user, periode)
    except batch.PeriodeTidakDikenal as exc:
        return _galat(422, "periode_tidak_dikenal", str(exc))
    hasil = await batch.jalankan(user, db, p, [item], household_id=hid)
    return hasil["data"][instance_id]
