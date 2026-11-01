"""Prive dua sisi (Plugin R8; docs/plugin/04-kontrak-api.md §2, 05-desain-buku-usaha.md B1, B2).

Pemilik ruang usaha mengambil uang dari amplop usaha ke ruang keluarganya. Satu-satunya
permintaan tulis yang boleh menyentuh dua ruang (pengecualian `lintas_ruang`, AGENTS.md aturan 8):

- ruang asal = ruang amplop `dari_amplop_id` (`ruang_amplop`, keanggotaan dicek; header tidak dipakai);
- hanya peran **owner** ruang usaha itu; admin dan karyawan ditolak (05-desain B2);
- ruang tujuan = ruang keluarga pemanggil, ditentukan server (`ruang_keluarga_id`), tidak pernah
  dari body atau header — jadi tidak ada cara menulis ke ruang keluarga orang lain;
- kedua sisi dalam satu transaksi database (`fund_shift.record_prive`), idempoten lewat `client_ref`.

Chat tidak punya jalur prive (ADR-P2): bot hanya mencatat ke ruang keluarga.
"""
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Envelope, Household, HouseholdRole, HouseholdType, User
from app.services.ruang import RuangDitolak, keanggotaan, ruang_amplop, ruang_jenis, ruang_keluarga_id

router = APIRouter()

KODE_BUKAN_USAHA = "bukan_ruang_usaha"
KODE_HANYA_PEMILIK = "prive_hanya_pemilik"
KODE_TANPA_KELUARGA = "tanpa_ruang_keluarga"


class PriveCreate(BaseModel):
    dari_amplop_id: UUID
    jumlah: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    tanggal: date | None = None          # bawaan: hari ini di zona waktu user
    catatan: str | None = Field(default=None, max_length=200)
    client_ref: str | None = Field(default=None, max_length=64)


def _ref(client_ref: str | None) -> str | None:
    # Ruang nama sendiri di Redis, supaya tidak pernah tertukar dengan client_ref transaksi.
    return f"prive:{client_ref}" if client_ref else None


def _hari_ini(user) -> date:
    from app.services.streak import user_today
    return user_today(getattr(user, "timezone", None))


@router.post("", status_code=201)
async def create_prive(
    req: PriveCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import idempotency

    ref = _ref(req.client_ref)
    sudah = await idempotency.lookup(user.id, ref)
    if sudah == idempotency.PENDING:
        raise HTTPException(status_code=409, detail="Prive ini sedang diproses. Coba lagi sebentar.")
    if sudah:
        try:
            return json.loads(sudah)  # kirim ulang: kedua sisi sudah tercatat
        except ValueError:
            await idempotency.forget(user.id, ref)

    # Ruang asal dari amplopnya; amplop ruang orang lain = "tidak ditemukan" (tanpa membocorkan ruang).
    usaha_id = await ruang_amplop(db, user, req.dari_amplop_id)
    if not usaha_id:
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
    if await ruang_jenis(db, usaha_id) != HouseholdType.USAHA:
        raise RuangDitolak(kode=KODE_BUKAN_USAHA, status_code=400,
                           detail="Prive hanya bisa diambil dari amplop ruang usaha.")
    anggota = await keanggotaan(db, user.id, usaha_id)
    if anggota is None or anggota.role != HouseholdRole.owner:
        raise RuangDitolak(kode=KODE_HANYA_PEMILIK,
                           detail="Hanya pemilik usaha yang bisa mencatat prive ke ruang keluarga.")
    keluarga_id = await ruang_keluarga_id(db, user.id)
    if not keluarga_id:
        raise RuangDitolak(kode=KODE_TANPA_KELUARGA, status_code=400,
                           detail="Ruang keluargamu belum ada. Buka Jatahku di ruang keluarga dulu, lalu coba lagi.")

    hari_ini = _hari_ini(user)
    tanggal = req.tanggal or hari_ini
    if tanggal > hari_ini:
        raise HTTPException(status_code=400, detail="Tanggal prive tidak boleh di masa depan.")

    if not await idempotency.reserve(user.id, ref):
        raise HTTPException(status_code=409, detail="Prive ini sedang diproses. Coba lagi sebentar.")
    try:
        hasil, goals_before = await _catat(db, user, req, usaha_id, keluarga_id, tanggal)
    except BaseException:
        await db.rollback()
        await idempotency.release(user.id, ref)
        raise
    await idempotency.store(user.id, ref, json.dumps(hasil))

    from app.services.goal_notify import notify_goals_reached
    await notify_goals_reached(db, user, goals_before)  # Tabungan ruang keluarga bisa menuntaskan target
    return hasil


async def _catat(db, user, req: PriveCreate, usaha_id, keluarga_id, tanggal) -> tuple[dict, dict]:
    from app.api.routes.incomes import _get_or_create_tabungan
    from app.services.envelope_balance import compute_envelope_summaries
    from app.services.fund_shift import lock_household, max_transferable, record_prive
    from app.services.goal_notify import goal_snapshot

    # Kunci kedua ruang dalam urutan tetap (hindari deadlock dengan prive/geser dana bersamaan):
    # ruang usaha supaya dua prive tidak sama-sama lolos cek sisa, ruang keluarga supaya Tabungan
    # tidak dibuat dua kali.
    for hid in sorted((usaha_id, keluarga_id), key=str):
        await lock_household(db, hid)

    rows = {str(r["id"]): r for r in await compute_envelope_summaries(user, db, household_id=usaha_id)}
    row = rows.get(str(req.dari_amplop_id))
    if row is None:  # amplop nonaktif, atau amplop pribadi anggota lain
        raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
    batas = max_transferable(row)
    if req.jumlah > batas:
        raise HTTPException(status_code=400, detail=f"Maksimal prive dari {row['name']}: Rp{int(batas):,}".replace(",", "."))

    goals_before = await goal_snapshot(db, keluarga_id)
    dari_env = (await db.execute(select(Envelope).where(Envelope.id == req.dari_amplop_id))).scalar_one()
    nama_usaha = (await db.execute(select(Household.name).where(Household.id == usaha_id))).scalar_one()
    tabungan = await _get_or_create_tabungan(keluarga_id, db)
    keluar, masuk = record_prive(
        db, user_id=user.id, ruang_usaha_id=usaha_id, nama_ruang_usaha=nama_usaha, dari_env=dari_env,
        ruang_keluarga_id=keluarga_id, tabungan=tabungan, amount=req.jumlah, tanggal=tanggal, catatan=req.catatan,
    )
    await db.commit()
    jumlah = str(req.jumlah)
    return {
        "keluar": {"income_id": str(keluar.id), "ruang_id": str(usaha_id), "amplop": dari_env.name},
        "masuk": {"income_id": str(masuk.id), "ruang_id": str(keluarga_id), "amplop": tabungan.name},
        "jumlah": jumlah,
        "tanggal": tanggal.isoformat(),
    }, goals_before
