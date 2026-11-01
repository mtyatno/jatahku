"""Fitur Tambahan / plugin (Plugin H1; docs/plugin/04-kontrak-api.md §5).

- `GET /plugins` — katalog untuk ruang aktif (header `X-Jatahku-Ruang`, membaca). Di ruang usaha, karyawan ditolak
  gerbang R5 (403 `khusus_admin`, route ini tidak di `KARYAWAN_BOLEH`); di ruang keluarga semua anggota boleh melihat.
- `POST /ruang/{ruang_id}/plugins/{plugin_id}/pasang | lanjut | jeda | copot` — ruang dari **path**, lalu
  keanggotaan (bukan anggota → 404 seperti ruang tidak ada, supaya keberadaan ruang orang lain tidak bocor),
  lalu peran owner/admin (selain itu 403 `khusus_admin`, ADR-P11). Aturan plugin di `app/plugins/host/siklus.py`.

Router `/ruang` di sini hanya berisi rute plugin; `/ruang` milik R4 boleh menambah router lain di awalan yang sama.
"""
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import HouseholdRole, User
from app.plugins.host import siklus
from app.services.ruang import RuangAktif, RuangDitolak, keanggotaan, ruang_jenis, ruang_objek

router = APIRouter()
ruang_router = APIRouter()

PERAN_KELOLA = (HouseholdRole.owner, HouseholdRole.admin)
_PLUGIN_ID = Path(..., pattern=r"^[a-z][a-z0-9_]{1,29}$")


def _boleh_kelola(peran) -> bool:
    return peran in PERAN_KELOLA


@router.get("")
async def daftar_plugin(
    *,
    hid: RuangAktif,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if hid is None:
        return []
    anggota = await keanggotaan(db, user.id, hid)
    return await siklus.katalog(db, user, hid, await ruang_jenis(db, hid),
                                boleh_kelola=anggota is not None and _boleh_kelola(anggota.role))


async def _ruang_kelola(db: AsyncSession, user: User, ruang_id: str) -> tuple[UUID, str]:
    """Ruang dari path → keanggotaan → peran pengelola. Mengembalikan (household_id, jenis ruang)."""
    try:
        rid = UUID(ruang_id)
    except ValueError:
        rid = None
    hid = await ruang_objek(db, user, rid)
    if hid is None:
        raise RuangDitolak(kode="ruang_tidak_ada", detail="Ruang tidak ditemukan.", status_code=404)
    anggota = await keanggotaan(db, user.id, hid)
    if anggota is None or not _boleh_kelola(anggota.role):
        raise RuangDitolak(kode="khusus_admin", detail="Hanya pemilik dan admin ruang yang bisa mengatur Fitur Tambahan.")
    return hid, await ruang_jenis(db, hid)


class PasangIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pengaturan: dict | None = None


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/pasang")
async def pasang_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    body: PasangIn | None = Body(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, jenis = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.pasang(db, user, hid, jenis, m, pengaturan=(body.pengaturan if body else None))
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/lanjut")
async def lanjut_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, jenis = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.lanjut(db, user, hid, jenis, m)
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/jeda")
async def jeda_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, _ = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.jeda(db, user, hid, m)
    await db.commit()
    return siklus.ke_api(m, inst)


@ruang_router.post("/{ruang_id}/plugins/{plugin_id}/copot")
async def copot_plugin(
    ruang_id: str,
    plugin_id: str = _PLUGIN_ID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hid, _ = await _ruang_kelola(db, user, ruang_id)
    m = siklus.manifest_atau_404(plugin_id)
    inst = await siklus.copot(db, user, hid, m)
    await db.commit()
    # `ekspor` terisi saat endpoint ekspor ada (U1, bersama data plugin pertama); layar copot menawarkannya.
    return {**siklus.ke_api(m, inst), "ekspor": None}
