"""Penentu ruang (Plugin R2, docs/plugin/04-kontrak-api.md §1, ADR-P1, P2).

Ruang = household. Satu user boleh anggota beberapa ruang (R1): ruang keluarga
(`households.type = rumah_tangga`) dan ruang usaha. Semua kode yang dulu mencari
"household milik user" lewat keanggotaan memakai salah satu fungsi di sini, dan
meneruskan `household_id` secara eksplisit ke services:

- `ruang_aktif` (dependency FastAPI) — untuk **membaca**. Header `X-Jatahku-Ruang`
  memilih ruang tempat user menjadi anggota; tanpa header → ruang keluarga, jadi
  klien lama dan user satu ruang tidak berubah perilakunya.
- `ruang_tulis` (dependency FastAPI) — untuk **menulis** sampai R3. Selalu ruang
  keluarga; header yang menunjuk ruang lain ditolak supaya tulis tidak pernah jatuh
  diam-diam ke ruang yang salah. R3 menggantinya dengan ruang dari objek yang ditulis.
- `ruang_keluarga(user, db)` — bot (Telegram dan chat web), job terjadwal, dan
  pekerjaan latar. Chat selalu ruang keluarga (ADR-P2).

Header yang tidak sah (bukan UUID, ruang orang lain, ruang terhapus) → 403
`ruang_tidak_diizinkan`. Tidak pernah ada fallback ke ruang lain.
"""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Household, HouseholdMember, HouseholdType, User

RUANG_HEADER = "X-Jatahku-Ruang"
KODE_DITOLAK = "ruang_tidak_diizinkan"
PESAN_DITOLAK = "Ruang ini tidak bisa dibuka dari akunmu. Muat ulang Jatahku lalu pilih ruang lagi."


class RuangDitolak(HTTPException):
    """403 dengan `detail` teks siap tampil; `install()` menambah field `kode` (§7)."""

    def __init__(self, kode: str = KODE_DITOLAK, detail: str = PESAN_DITOLAK):
        super().__init__(status_code=403, detail=detail)
        self.kode = kode


def install(app: FastAPI) -> None:
    """Pasang handler yang menambah `kode` ke jawaban `RuangDitolak`."""

    async def _handler(request: Request, exc: RuangDitolak):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "kode": exc.kode})

    app.add_exception_handler(RuangDitolak, _handler)


async def ruang_keluarga_id(db: AsyncSession, user_id) -> UUID | None:
    """Household `rumah_tangga` milik user. Bila (tidak semestinya) lebih dari satu,
    keanggotaan tertua menang, supaya hasilnya tetap dan tidak pernah galat."""
    return (await db.execute(
        select(HouseholdMember.household_id)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user_id, Household.type == HouseholdType.RUMAH_TANGGA)
        .order_by(HouseholdMember.created_at, HouseholdMember.id)
        .limit(1)
    )).scalar_one_or_none()


async def ruang_keluarga(user, db: AsyncSession) -> UUID | None:
    return await ruang_keluarga_id(db, user.id)


async def keanggotaan_keluarga(db: AsyncSession, user_id) -> HouseholdMember | None:
    """Baris keanggotaan ruang keluarga user (untuk peran, gabung akun, keluar household)."""
    return (await db.execute(
        select(HouseholdMember)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user_id, Household.type == HouseholdType.RUMAH_TANGGA)
        .order_by(HouseholdMember.created_at, HouseholdMember.id)
        .limit(1)
    )).scalar_one_or_none()


async def keanggotaan(db: AsyncSession, user_id, household_id) -> HouseholdMember | None:
    """Keanggotaan user di satu ruang (peran ada di `.role`), atau None."""
    if household_id is None:
        return None
    return (await db.execute(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user_id, HouseholdMember.household_id == household_id,
        ).limit(1)
    )).scalar_one_or_none()


async def _ruang_dari_header(header: str | None, user, db: AsyncSession) -> UUID | None:
    raw = (header or "").strip()
    if not raw:
        return None
    try:
        hid = UUID(raw)
    except ValueError:
        raise RuangDitolak()
    if await keanggotaan(db, user.id, hid) is None:
        raise RuangDitolak()
    return hid


_HEADER = Header(None, alias=RUANG_HEADER, description="ID ruang yang sedang dibuka (opsional; tanpa header = ruang keluarga)")


async def ruang_aktif(
    x_jatahku_ruang: str | None = _HEADER,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID | None:
    """Ruang untuk membaca: dari header bila ada (dan sah), selain itu ruang keluarga.
    None = user belum punya household; route menangani seperti sebelumnya."""
    hid = await _ruang_dari_header(x_jatahku_ruang, user, db)
    return hid if hid is not None else await ruang_keluarga_id(db, user.id)


async def ruang_tulis(
    x_jatahku_ruang: str | None = _HEADER,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID | None:
    """Ruang untuk menulis sampai R3: selalu ruang keluarga. Header yang menunjuk
    ruang lain ditolak, bukan diabaikan, supaya catatan tidak masuk ruang yang salah."""
    keluarga = await ruang_keluarga_id(db, user.id)
    hid = await _ruang_dari_header(x_jatahku_ruang, user, db)
    if hid is not None and hid != keluarga:
        raise RuangDitolak()
    return keluarga


# Dipakai sebagai parameter keyword-only di route (`*, hid: RuangAktif`): tanpa nilai bawaan,
# sehingga pemanggilan handler langsung (Sumber Beranda, tes) yang lupa `hid` gagal keras,
# bukan diam-diam meneruskan objek Depends sebagai id ruang.
RuangAktif = Annotated[UUID | None, Depends(ruang_aktif)]
RuangTulis = Annotated[UUID | None, Depends(ruang_tulis)]
