"""Daftar dan pembuatan ruang (Plugin R4; docs/plugin/04-kontrak-api.md §2, ADR-P1, P4, P13).

`GET /ruang` mengisi pemilih ruang di sidebar dan header HP; klien lalu mengirim id ruang terpilih
sebagai header `X-Jatahku-Ruang` (§1). `POST /ruang` membuat ruang usaha baru dengan pembuatnya
sebagai owner. Ruang keluarga tidak dibuat di sini (dibuat saat daftar akun).

Sampai rilis, ruang usaha di balik flag `ruang_usaha_users` (`ruang.ruang_usaha_dibuka`): di luar
flag, ruang usaha tidak tampil dan tidak bisa dibuat. Undangan ruang usaha baru dibuka di R5,
bersamaan dengan penegakan peran (catatan review PR #171), jadi ruang usaha R4 hanya berisi pemiliknya.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Household, HouseholdMember, HouseholdRole, HouseholdType, User
from app.services import household_cycle
from app.services.ruang import ruang_keluarga_id, ruang_usaha_dibuka

router = APIRouter()

# Batas ruang usaha yang dimiliki satu user selama beta (mencegah ruang kosong menumpuk).
MAKS_RUANG_USAHA = 3
NAMA_MAKS = 60

KODE_BELUM_DIBUKA = "ruang_usaha_belum_dibuka"
PESAN_BELUM_DIBUKA = "Ruang usaha belum tersedia untuk akunmu."
KODE_BATAS = "batas_ruang_usaha"
PESAN_BATAS = f"Kamu sudah punya {MAKS_RUANG_USAHA} ruang usaha. Itu batasnya untuk sekarang."


def _galat(status: int, kode: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "kode": kode})


def _peran(role) -> str:
    return str(getattr(role, "value", role))


class RuangItem(BaseModel):
    id: UUID
    nama: str
    jenis: str                       # rumah_tangga | usaha
    peran: str                       # owner | admin | member
    jumlah_anggota: int
    paket: dict | None = None        # Paket Usaha (ADR-P12, P13): diisi H1/V1; null sampai saat itu
    jam_kerja: dict | None = None    # jadwal anggota dari admin (ADR-P17): diisi R5


class RuangDaftar(BaseModel):
    bawaan: UUID | None              # ruang keluarga; None bila user belum punya household
    items: list[RuangItem]
    boleh_buat_usaha: bool           # flag terbuka dan belum mencapai batas


class RuangBuat(BaseModel):
    nama: str = Field(min_length=1, max_length=NAMA_MAKS)

    @field_validator("nama")
    @classmethod
    def _rapikan(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Nama ruang wajib diisi")
        return v


async def _daftar(db: AsyncSession, user_id, *, usaha: bool) -> list[RuangItem]:
    anggota = (
        select(HouseholdMember.household_id, func.count(HouseholdMember.id).label("n"))
        .group_by(HouseholdMember.household_id)
        .subquery()
    )
    q = (
        select(Household.id, Household.name, Household.type, HouseholdMember.role, anggota.c.n)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .join(anggota, anggota.c.household_id == Household.id)
        .where(HouseholdMember.user_id == user_id)
        .order_by(HouseholdMember.created_at, HouseholdMember.id)
    )
    if not usaha:
        q = q.where(Household.type != HouseholdType.USAHA)
    rows = (await db.execute(q)).all()
    return [
        RuangItem(id=hid, nama=nama, jenis=jenis or HouseholdType.RUMAH_TANGGA, peran=_peran(role), jumlah_anggota=n)
        for hid, nama, jenis, role, n in rows
    ]


async def _jumlah_usaha_milik(db: AsyncSession, user_id) -> int:
    return (await db.execute(
        select(func.count(Household.id))
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == user_id, HouseholdMember.role == HouseholdRole.owner,
               Household.type == HouseholdType.USAHA)
    )).scalar() or 0


@router.get("", response_model=RuangDaftar)
async def daftar_ruang(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Semua ruang user untuk pemilih ruang: ruang keluarga dulu, lalu ruang lain urut bergabung.
    Tanpa header ruang: daftar ini milik user, bukan isi satu ruang."""
    dibuka = await ruang_usaha_dibuka(db, user.id)
    items = await _daftar(db, user.id, usaha=dibuka)
    bawaan = await ruang_keluarga_id(db, user.id)
    items.sort(key=lambda r: r.id != bawaan)   # stabil: ruang keluarga di depan, sisanya tetap urut bergabung
    boleh = dibuka and await _jumlah_usaha_milik(db, user.id) < MAKS_RUANG_USAHA
    return RuangDaftar(bawaan=bawaan, items=items, boleh_buat_usaha=boleh)


@router.post("", response_model=RuangItem, status_code=201)
async def buat_ruang(req: RuangBuat, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Membuat ruang usaha (selalu berjenis usaha); pembuatnya owner. 403 di luar flag, 409 di atas batas."""
    if not await ruang_usaha_dibuka(db, user.id):
        return _galat(403, KODE_BELUM_DIBUKA, PESAN_BELUM_DIBUKA)
    # Kunci baris user: dua permintaan bersamaan tidak bisa sama-sama lolos cek batas (PostgreSQL; SQLite abaikan).
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await _jumlah_usaha_milik(db, user.id) >= MAKS_RUANG_USAHA:
        return _galat(409, KODE_BATAS, PESAN_BATAS)
    ruang = Household(name=req.nama, type=HouseholdType.USAHA)
    household_cycle.init_ruang_usaha(ruang)
    db.add(ruang)
    await db.flush()
    db.add(HouseholdMember(user_id=user.id, household_id=ruang.id, role=HouseholdRole.owner))
    await db.commit()
    return RuangItem(id=ruang.id, nama=ruang.name, jenis=HouseholdType.USAHA, peran="owner", jumlah_anggota=1)
