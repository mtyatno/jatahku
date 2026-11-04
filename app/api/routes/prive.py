"""Prive dua sisi (Plugin R8; docs/plugin/04-kontrak-api.md §2, 05-desain-buku-usaha.md B1, B2).

Pemilik ruang usaha mengambil uang dari amplop usaha ke ruang keluarganya. Satu-satunya
permintaan tulis yang boleh menyentuh dua ruang (pengecualian `lintas_ruang`, AGENTS.md aturan 8):

- ruang asal = ruang amplop `dari_amplop_id` (`ruang_amplop`, keanggotaan dicek; header tidak dipakai);
- hanya peran **owner** ruang usaha itu; admin dan karyawan ditolak (05-desain B2);
- ruang tujuan = ruang keluarga pemanggil, ditentukan server (`ruang_keluarga_id`), tidak pernah
  dari body atau header — jadi tidak ada cara menulis ke ruang keluarga orang lain;
- kedua sisi dalam satu transaksi database (`fund_shift.record_prive`);
- sisa amplop dihitung dengan siklus **ruang usaha** (`household_payday`, bulan kalender), bukan tanggal
  gajian keluarga user; tanggal hanya di irisan periode berjalan kedua ruang, dengan satu sumber "hari ini"
  (`date.today()`, sama dengan perhitungan saldo), supaya cek sisa tidak bisa dilewati (review #177);
- `client_ref` wajib dan idempotensi **fail-closed**: prive tidak bisa dibatalkan, jadi Redis tidak
  terjangkau (timeout 2 detik) → 503; hasil disimpan ke Redis sebelum commit dan tidak dihapus bila commit
  gagal (hanya status pending yang dilepas), karena commit bisa sampai di database walau jawabannya hilang;
  kunci yang menunjuk baris yang tidak ada dianggap basi.

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
SCOPE_REF = "priveref"   # ruang nama kunci Redis sendiri (idempotency.py), terpisah dari txnref
PESAN_SIBUK = "Prive ini sedang diproses. Coba lagi sebentar."
PESAN_REDIS = "Prive belum bisa dicatat sekarang. Coba lagi sebentar."


class PriveCreate(BaseModel):
    dari_amplop_id: UUID
    jumlah: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    tanggal: date | None = None          # bawaan: hari ini; hanya irisan periode berjalan kedua ruang
    catatan: str | None = Field(default=None, max_length=200)
    client_ref: str = Field(min_length=1, max_length=64)   # wajib: prive tidak bisa dibatalkan


async def _periode_irisan(db, usaha_id, keluarga_id) -> tuple[int, date, date]:
    """(payday ruang usaha, awal, akhir): irisan periode berjalan ruang usaha dan ruang keluarga.
    Hari ini (`date.today()`, sumber yang sama dengan `compute_envelope_summaries`) selalu di dalamnya."""
    from app.core.period import get_budget_period
    from app.services.household_cycle import household_payday
    hari_ini = date.today()
    usaha = await db.get(Household, usaha_id)
    keluarga = await db.get(Household, keluarga_id)
    payday_usaha = await household_payday(db, usaha)
    a_u, z_u = get_budget_period(payday_usaha, hari_ini)
    a_k, z_k = get_budget_period(await household_payday(db, keluarga), hari_ini)
    return payday_usaha, max(a_u, a_k), min(z_u, z_k, hari_ini)


def _cek_tanggal(diminta: date | None, awal: date, akhir: date) -> date:
    tanggal = diminta or akhir
    if tanggal > akhir:
        raise HTTPException(status_code=400, detail="Tanggal prive tidak boleh di masa depan.")
    if tanggal < awal:
        raise HTTPException(status_code=400,
                            detail=f"Tanggal prive paling awal {awal:%d/%m/%Y} (awal periode berjalan).")
    return tanggal


@router.post("", status_code=201)
async def create_prive(
    req: PriveCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Ruang asal dari amplopnya; amplop ruang orang lain = "tidak ditemukan" (tanpa membocorkan ruang).
    # Karyawan ruang usaha ditolak di sini oleh gerbang R5 (403 `khusus_admin`).
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
    from app.services import idempotency
    try:
        hasil, goals_before = await _catat(db, user, req, usaha_id, keluarga_id, req.client_ref)
    except idempotency.RedisTidakTersedia:
        await db.rollback()
        raise HTTPException(status_code=503, detail=PESAN_REDIS)
    except BaseException:
        await db.rollback()
        raise
    if goals_before is not None:
        try:  # sesudah commit: gagal kirim notifikasi target tidak boleh menjadi 500 (kiriman ulang dobel)
            from app.services.goal_notify import notify_goals_reached
            await notify_goals_reached(db, user, goals_before)
        except Exception:
            import logging
            logging.getLogger("jatahku.prive").exception("notify_goals_reached gagal")
    return hasil


async def _catat(db, user, req: PriveCreate, usaha_id, keluarga_id, ref) -> tuple[dict, dict | None]:
    """Mengembalikan (jawaban, potret target sebelum) — potret None bila ini kiriman ulang."""
    from app.api.routes.incomes import _get_or_create_tabungan
    from app.models.models import Income
    from app.services import idempotency
    from app.services.envelope_balance import compute_envelope_summaries
    from app.services.fund_shift import lock_household, max_transferable, record_prive
    from app.services.goal_notify import goal_snapshot

    kunci = dict(scope=SCOPE_REF, strict=True)
    # Kunci kedua ruang dalam urutan tetap (hindari deadlock dengan prive/geser dana bersamaan):
    # ruang usaha supaya dua prive tidak sama-sama lolos cek sisa, ruang keluarga supaya Tabungan
    # tidak dibuat dua kali. Pemeriksaan client_ref juga di bawah kunci ini, supaya kiriman ulang
    # yang bersamaan melihat hasil yang sudah di-commit, bukan kunci yang belum di-commit.
    for hid in sorted((usaha_id, keluarga_id), key=str):
        await lock_household(db, hid)

    sudah = await idempotency.lookup(user.id, ref, **kunci)
    if sudah == idempotency.PENDING:
        raise HTTPException(status_code=409, detail=PESAN_SIBUK)
    if sudah:
        try:
            lama = json.loads(sudah)
            ada = await db.get(Income, UUID(lama["keluar"]["income_id"]))
        except (ValueError, KeyError, TypeError):
            lama, ada = None, None
        if ada is not None and ada.user_id == user.id:
            await db.rollback()  # lepas kunci; tidak ada yang ditulis
            return lama, None    # kiriman ulang: kedua sisi sudah tercatat (sebelum cek tanggal: periode bisa berganti)
        await idempotency.forget(user.id, ref, **kunci)  # basi: commit sebelumnya benar-benar gagal
    if not await idempotency.reserve(user.id, ref, **kunci):
        raise HTTPException(status_code=409, detail=PESAN_SIBUK)

    try:
        payday_usaha, awal, akhir = await _periode_irisan(db, usaha_id, keluarga_id)
        tanggal = _cek_tanggal(req.tanggal, awal, akhir)
        rows = {str(r["id"]): r for r in await compute_envelope_summaries(
            user, db, household_id=usaha_id, payday_day=payday_usaha)}
        row = rows.get(str(req.dari_amplop_id))
        if row is None:  # amplop nonaktif, atau amplop pribadi anggota lain
            raise HTTPException(status_code=404, detail="Amplop tidak ditemukan")
        batas = max_transferable(row)
        if req.jumlah > batas:
            raise HTTPException(status_code=400,
                                detail=f"Maksimal prive dari {row['name']}: Rp{int(batas):,}".replace(",", "."))

        goals_before = await goal_snapshot(db, keluarga_id)
        dari_env = (await db.execute(select(Envelope).where(Envelope.id == req.dari_amplop_id))).scalar_one()
        nama_usaha = (await db.execute(select(Household.name).where(Household.id == usaha_id))).scalar_one()
        tabungan = await _get_or_create_tabungan(keluarga_id, db)
        keluar, masuk = record_prive(
            db, user_id=user.id, ruang_usaha_id=usaha_id, nama_ruang_usaha=nama_usaha, dari_env=dari_env,
            ruang_keluarga_id=keluarga_id, tabungan=tabungan, amount=req.jumlah, tanggal=tanggal,
            catatan=req.catatan,
        )
        hasil = {
            "keluar": {"income_id": str(keluar.id), "ruang_id": str(usaha_id), "amplop": dari_env.name},
            "masuk": {"income_id": str(masuk.id), "ruang_id": str(keluarga_id), "amplop": tabungan.name},
            "jumlah": str(req.jumlah),
            "tanggal": tanggal.isoformat(),
        }
        # Hasil disimpan SEBELUM commit: bila Redis mati sesudah commit, kiriman ulang tetap tidak dobel.
        await idempotency.store(user.id, ref, json.dumps(hasil), **kunci)
        await db.commit()
    except BaseException:
        # Hanya status pending yang dilepas. Hasil yang sudah disimpan dibiarkan: commit bisa sampai di database
        # walau jawabannya hilang (koneksi putus); bila commit benar-benar gagal, kunci itu dikenali basi.
        try:
            await idempotency.release(user.id, ref, scope=SCOPE_REF)
        except Exception:
            pass
        raise
    return hasil, goals_before
