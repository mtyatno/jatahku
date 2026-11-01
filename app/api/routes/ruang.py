"""Ruang usaha: anggota, undangan, batasan, antrean persetujuan, log audit (Plugin R5; 04-kontrak-api.md §2).

Semua route `/ruang/{id}/…` hanya untuk ruang **usaha** (ruang keluarga tetap diatur `/household`) dan hanya untuk
owner dan admin ruang itu; ruang bukan milik user → 404, karyawan → 403 `khusus_admin`. Admin tidak bisa mengubah
atau mengeluarkan owner (ADR-P4). Ruang dari path, keanggotaan dan peran dicek dari baris DB (`_ruang_kelola`);
tidak ada `ruang_id` dari body.

Persetujuan (ADR-P18): draf dicatat atas nama pencatat asli lewat `catat_transaksi` / `catat_pemasukan` di dalam
`peran.atas_izin_pengelola()`, jadi semua aturan pencatatan (amplop, dana, limit harian, kunci, struk) tetap berlaku;
hanya batasan karyawan yang tidak dicek lagi.
"""
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    Envelope, Household, HouseholdMember, HouseholdRole, HouseholdType, RuangAudit, RuangBatasan, RuangDraf,
    RuangUndangan, User,
)
from app.services import peran
from app.services.ruang import RuangAktif, RuangDitolak

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)   # pola sama dengan auth.py (in-memory per instance)

UNDANGAN_HARI = 7
TIDAK_ADA = "Ruang tidak ditemukan"


def _tolak(kode: str, detail: str | None = None, status_code: int = 403):
    return RuangDitolak.dari_peran(peran.PeranDitolak(kode, detail, status_code))


async def _ruang_kelola(db: AsyncSession, user: User, rid: UUID) -> str:
    """Peran user (owner/admin) di ruang usaha `rid`. Bukan anggota atau bukan ruang usaha → 404; karyawan → 403."""
    role, jenis = await peran.peran_di_ruang(db, user.id, rid)
    if role is None or jenis != HouseholdType.USAHA:
        raise HTTPException(status_code=404, detail=TIDAK_ADA)
    if role not in (HouseholdRole.owner.value, HouseholdRole.admin.value):
        raise _tolak("khusus_admin")
    return role


async def _anggota(db: AsyncSession, rid: UUID, uid: UUID) -> HouseholdMember:
    m = (await db.execute(select(HouseholdMember).where(
        HouseholdMember.household_id == rid, HouseholdMember.user_id == uid))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan")
    return m


def _peran(m: HouseholdMember) -> str:
    return m.role.value if isinstance(m.role, HouseholdRole) else str(m.role)


def _jaga_owner(role_saya: str, target: HouseholdMember) -> None:
    if _peran(target) == HouseholdRole.owner.value:
        raise _tolak("khusus_admin", "Pemilik ruang tidak bisa diubah atau dikeluarkan.")


async def _baris_batasan(db: AsyncSession, rid: UUID, uid: UUID, buat: bool = False) -> RuangBatasan | None:
    row = (await db.execute(select(RuangBatasan).where(
        RuangBatasan.household_id == rid, RuangBatasan.user_id == uid))).scalar_one_or_none()
    if row is None and buat:
        row = RuangBatasan(household_id=rid, user_id=uid, jenis_catatan=list(peran.JENIS_SEMUA))
        db.add(row)
    return row


# ── Anggota ────────────────────────────────────────────────────────────────
@router.get("/ruang/{rid}/anggota")
async def daftar_anggota(rid: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    rows = (await db.execute(
        select(HouseholdMember, User).join(User, User.id == HouseholdMember.user_id)
        .where(HouseholdMember.household_id == rid).order_by(HouseholdMember.created_at)
    )).all()
    batasan = {b.user_id: b for b in (await db.execute(
        select(RuangBatasan).where(RuangBatasan.household_id == rid))).scalars()}
    out = []
    for m, u in rows:
        b = batasan.get(u.id)
        role = _peran(m)
        out.append({
            "user_id": str(u.id), "nama": u.name, "peran": role, "jabatan": b.jabatan if b else None,
            "bergabung": m.created_at.isoformat() if m.created_at else None,
            "batasan": peran._dari_baris(b).ke_api() if role == HouseholdRole.member.value else None,
        })
    return out


class UbahAnggota(BaseModel):
    peran: Literal["member", "admin"] | None = None
    jabatan: str | None = Field(default=None, max_length=50)


@router.patch("/ruang/{rid}/anggota/{uid}")
async def ubah_anggota(rid: UUID, uid: UUID, req: UbahAnggota, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    role_saya = await _ruang_kelola(db, user, rid)
    m = await _anggota(db, rid, uid)
    _jaga_owner(role_saya, m)
    rincian = {}
    if req.peran is not None and req.peran != _peran(m):
        rincian["peran"] = {"dari": _peran(m), "ke": req.peran}
        m.role = HouseholdRole(req.peran)
    if "jabatan" in req.model_fields_set:
        b = await _baris_batasan(db, rid, uid, buat=True)
        rincian["jabatan"] = req.jabatan
        b.jabatan = (req.jabatan or "").strip() or None
        b.diubah_oleh = user.id
    if rincian:
        peran.audit(db, rid, user.id, "anggota_diubah", uid, **rincian)
        await db.commit()
    return {"user_id": str(uid), "peran": _peran(m)}


@router.delete("/ruang/{rid}/anggota/{uid}", status_code=204)
async def keluarkan_anggota(rid: UUID, uid: UUID, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Owner/admin mengeluarkan anggota, atau anggota (selain owner) keluar sendiri. Akses hilang seketika; catatan
    lama tetap milik ruang; draf yang menunggu dibatalkan; ruang keluarganya tidak tersentuh."""
    if uid == user.id:
        role, jenis = await peran.peran_di_ruang(db, user.id, rid)
        if role is None or jenis != HouseholdType.USAHA:
            raise HTTPException(status_code=404, detail=TIDAK_ADA)
        aksi = "anggota_keluar"
    else:
        await _ruang_kelola(db, user, rid)
        aksi = "anggota_dikeluarkan"
    m = await _anggota(db, rid, uid)
    if _peran(m) == HouseholdRole.owner.value:
        raise _tolak("khusus_admin", "Pemilik ruang tidak bisa keluar atau dikeluarkan.")
    n = await peran.batalkan_draf_anggota(db, rid, uid)
    b = await _baris_batasan(db, rid, uid)
    if b is not None:
        await db.delete(b)
    await db.delete(m)
    peran.audit(db, rid, user.id, aksi, uid, peran=_peran(m), draf_dibatalkan=n)
    await db.commit()


class BatasanBody(BaseModel):
    jenis_catatan: list[str] = Field(default_factory=lambda: list(peran.JENIS_SEMUA))
    amplop_ids: list[UUID] | None = None
    batas_nominal: Decimal | None = Field(default=None, ge=0)
    foto_nota_di_atas: Decimal | None = Field(default=None, ge=0)
    jendela_ubah: Literal["hari_sama", "tidak_boleh"] = "hari_sama"
    lihat_saldo: bool = False
    jam_kerja: dict | None = None


@router.put("/ruang/{rid}/anggota/{uid}/batasan")
async def atur_batasan(rid: UUID, uid: UUID, req: BatasanBody, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    m = await _anggota(db, rid, uid)
    if _peran(m) != HouseholdRole.member.value:
        raise HTTPException(status_code=422, detail="Batasan hanya untuk karyawan; pemilik dan admin tanpa batasan.")
    jenis = list(dict.fromkeys(req.jenis_catatan))
    if any(j not in peran.JENIS_SEMUA for j in jenis):
        raise HTTPException(status_code=422, detail="Jenis catatan tidak dikenal.")
    amplop = None
    if req.amplop_ids is not None:
        ids = list(dict.fromkeys(req.amplop_ids))
        milik = set((await db.execute(select(Envelope.id).where(
            Envelope.household_id == rid, Envelope.id.in_(ids)))).scalars()) if ids else set()
        if len(milik) != len(ids):
            raise HTTPException(status_code=422, detail="Ada amplop yang bukan milik ruang ini.")
        amplop = [str(i) for i in ids]
    try:
        jam = peran.validasi_jam_kerja(req.jam_kerja, zona_bawaan=user.timezone or peran.ZONA_BAWAAN)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Jam kerja tidak sah: {exc}")
    b = await _baris_batasan(db, rid, uid, buat=True)
    b.jenis_catatan, b.amplop_ids = jenis, amplop
    b.batas_nominal, b.foto_nota_di_atas = req.batas_nominal, req.foto_nota_di_atas
    b.jendela_ubah, b.lihat_saldo, b.jam_kerja = req.jendela_ubah, req.lihat_saldo, jam
    b.diubah_oleh = user.id
    hasil = peran._dari_baris(b).ke_api()
    peran.audit(db, rid, user.id, "batasan_diubah", uid, batasan=hasil)
    await db.commit()
    return hasil


# ── Undangan ───────────────────────────────────────────────────────────────
class UndanganBody(BaseModel):
    peran: Literal["member", "admin"] = "member"


def _kode() -> str:
    return "RU" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))


@router.post("/ruang/{rid}/undangan", status_code=201)
async def buat_undangan(rid: UUID, req: UndanganBody, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Kode sekali pakai, berlaku 7 hari, dengan peran yang ditentukan pembuatnya."""
    await _ruang_kelola(db, user, rid)
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(days=UNDANGAN_HARI)
    u = RuangUndangan(household_id=rid, kode=_kode(), peran=req.peran, dibuat_oleh=user.id, kedaluwarsa=kedaluwarsa)
    db.add(u)
    peran.audit(db, rid, user.id, "undangan_dibuat", peran=req.peran)
    await db.commit()
    return {"kode": u.kode, "peran": u.peran, "kedaluwarsa": kedaluwarsa.isoformat()}


class GabungBody(BaseModel):
    kode: str = Field(min_length=4, max_length=20)


PESAN_KODE = "Kode undangan tidak valid atau sudah tidak berlaku."


@router.post("/ruang/gabung")
@limiter.limit("10/minute")
async def gabung_ruang(request: Request, req: GabungBody, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Bergabung ke ruang usaha lewat kode undangan. Tidak menyentuh ruang keluarga user (ADR-P4)."""
    kode = req.kode.strip().upper()
    now = datetime.now(timezone.utc)
    u = (await db.execute(select(RuangUndangan).where(RuangUndangan.kode == kode))).scalar_one_or_none()
    kedaluwarsa = u.kedaluwarsa if u is not None else None
    if kedaluwarsa is not None and kedaluwarsa.tzinfo is None:
        kedaluwarsa = kedaluwarsa.replace(tzinfo=timezone.utc)
    if u is None or u.dipakai_at is not None or u.dicabut_at is not None or kedaluwarsa <= now:
        raise HTTPException(status_code=400, detail=PESAN_KODE)
    hh = await db.get(Household, u.household_id)
    if hh is None or str(hh.type) != HouseholdType.USAHA:
        raise HTTPException(status_code=400, detail=PESAN_KODE)
    role, _ = await peran.peran_di_ruang(db, user.id, hh.id)
    if role is not None:
        raise HTTPException(status_code=400, detail="Kamu sudah anggota ruang ini.")
    # Klaim kode secara atomik: dua akun dengan kode yang sama, hanya satu yang masuk.
    klaim = await db.execute(update(RuangUndangan).where(
        RuangUndangan.id == u.id, RuangUndangan.dipakai_at.is_(None), RuangUndangan.dicabut_at.is_(None),
    ).values(dipakai_at=now, dipakai_oleh=user.id))
    if klaim.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=400, detail=PESAN_KODE)
    db.add(HouseholdMember(user_id=user.id, household_id=hh.id, role=HouseholdRole(u.peran)))
    peran.audit(db, hh.id, user.id, "anggota_bergabung", user.id, peran=u.peran)
    await db.commit()
    return {"id": str(hh.id), "nama": hh.name, "jenis": HouseholdType.USAHA, "peran": u.peran}


# ── Antrean persetujuan (ADR-P18) ──────────────────────────────────────────
def _draf_api(d: RuangDraf, nama: str | None = None) -> dict:
    return {
        "id": str(d.id), "pencatat": nama, "pencatat_id": str(d.user_id), "jenis": d.jenis,
        "jumlah": int(d.amount), "keterangan": d.description,
        "amplop_id": str(d.envelope_id) if d.envelope_id else None, "ada_foto": d.receipt_item_id is not None,
        "status": d.status, "alasan": d.alasan, "hasil_id": str(d.hasil_id) if d.hasil_id else None,
        "dibuat": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/ruang/{rid}/persetujuan")
async def daftar_persetujuan(rid: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    rows = (await db.execute(
        select(RuangDraf, User.name).join(User, User.id == RuangDraf.user_id)
        .where(RuangDraf.household_id == rid, RuangDraf.status == peran.ST_MENUNGGU)
        .order_by(RuangDraf.created_at)
    )).all()
    return [_draf_api(d, nama) for d, nama in rows]


@router.get("/persetujuan/saya")
async def persetujuan_saya(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), *,
                           hid: RuangAktif):
    """Draf milik user di ruang aktif: yang menunggu, plus yang diputus 14 hari terakhir."""
    if not hid:
        return []
    batas = datetime.now(timezone.utc) - timedelta(days=14)
    rows = (await db.execute(
        select(RuangDraf).where(RuangDraf.household_id == hid, RuangDraf.user_id == user.id,
                                (RuangDraf.status == peran.ST_MENUNGGU) | (RuangDraf.updated_at >= batas))
        .order_by(RuangDraf.created_at.desc()).limit(50)
    )).scalars().all()
    return [_draf_api(d, user.name) for d in rows]


async def _klaim_draf(db: AsyncSession, rid: UUID, draf_id: UUID, ke: str) -> RuangDraf:
    """menunggu → `ke`, atomik (dua admin menyetujui bersamaan: hanya satu yang jalan)."""
    hasil = await db.execute(update(RuangDraf).where(
        RuangDraf.id == draf_id, RuangDraf.household_id == rid, RuangDraf.status == peran.ST_MENUNGGU,
    ).values(status=ke))
    if hasil.rowcount != 1:
        await db.rollback()
        d = (await db.execute(select(RuangDraf).where(
            RuangDraf.id == draf_id, RuangDraf.household_id == rid))).scalar_one_or_none()
        if d is None:
            raise HTTPException(status_code=404, detail="Draf tidak ditemukan")
        raise HTTPException(status_code=409, detail="Draf ini sudah diputus.")
    await db.commit()
    return (await db.execute(select(RuangDraf).where(RuangDraf.id == draf_id))).scalar_one()


@router.post("/ruang/{rid}/persetujuan/{draf_id}/setujui")
async def setujui_draf(rid: UUID, draf_id: UUID, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    admin_id = user.id
    d = await _klaim_draf(db, rid, draf_id, peran.ST_DIPROSES)
    draf_user, jenis = d.user_id, d.jenis
    try:
        pencatat = await db.get(User, draf_user)
        role, _ = await peran.peran_di_ruang(db, draf_user, rid)
        if pencatat is None or role is None:
            raise HTTPException(status_code=409, detail="Pencatat sudah bukan anggota ruang ini.")
        with peran.atas_izin_pengelola():
            if jenis == peran.JENIS_PENGELUARAN:
                from app.api.routes.transactions import TransactionCreate, catat_transaksi
                from app.models.models import TransactionSource
                req = TransactionCreate(
                    envelope_id=d.envelope_id, amount=d.amount, description=d.description,
                    source=TransactionSource(d.source), transaction_date=d.tanggal, is_private=d.is_private,
                    client_ref=d.client_ref, receipt_item_id=d.receipt_item_id)
                res = await catat_transaksi(req, pencatat, db)
            else:
                from app.api.routes.incomes import AllocationItem, IncomeCreate, catat_pemasukan
                rinci = d.rincian or {}
                req = IncomeCreate(amount=d.amount, source=d.description, kind=rinci.get("kind", "pemasukan"),
                                   allocations=[AllocationItem(envelope_id=a["envelope_id"], amount=a["amount"])
                                                for a in rinci.get("allocations", [])])
                res = await catat_pemasukan(req, pencatat, db, rid)
    except Exception:
        await db.rollback()
        await db.execute(update(RuangDraf).where(RuangDraf.id == draf_id, RuangDraf.status == peran.ST_DIPROSES)
                         .values(status=peran.ST_MENUNGGU))
        await db.commit()
        raise
    hasil_id = res.id
    await db.execute(update(RuangDraf).where(RuangDraf.id == draf_id).values(
        status=peran.ST_DISETUJUI, diputus_oleh=admin_id, diputus_at=datetime.now(timezone.utc), hasil_id=hasil_id))
    peran.audit(db, rid, admin_id, "draf_disetujui", draf_user, draf_id=draf_id, jenis=jenis, hasil_id=hasil_id)
    await db.commit()
    kunci = "transaction_id" if jenis == peran.JENIS_PENGELUARAN else "income_id"
    return {kunci: str(hasil_id), "draf_id": str(draf_id), "status": peran.ST_DISETUJUI}


class TolakBody(BaseModel):
    alasan: str | None = Field(default=None, max_length=300)


@router.post("/ruang/{rid}/persetujuan/{draf_id}/tolak")
async def tolak_draf(rid: UUID, draf_id: UUID, req: TolakBody | None = None, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    admin_id = user.id
    d = await _klaim_draf(db, rid, draf_id, peran.ST_DITOLAK)
    alasan = ((req.alasan if req else None) or "").strip() or None
    await db.execute(update(RuangDraf).where(RuangDraf.id == draf_id).values(
        diputus_oleh=admin_id, diputus_at=datetime.now(timezone.utc), alasan=alasan))
    peran.audit(db, rid, admin_id, "draf_ditolak", d.user_id, draf_id=draf_id, jenis=d.jenis)
    await db.commit()
    return {"draf_id": str(draf_id), "status": peran.ST_DITOLAK}


# ── Log audit ──────────────────────────────────────────────────────────────
@router.get("/ruang/{rid}/audit")
async def log_audit(rid: UUID, limit: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await _ruang_kelola(db, user, rid)
    rows = (await db.execute(
        select(RuangAudit).where(RuangAudit.household_id == rid)
        .order_by(RuangAudit.created_at.desc(), RuangAudit.id).limit(limit)
    )).scalars().all()
    return [{"aksi": a.aksi, "oleh": str(a.actor_id) if a.actor_id else None,
             "anggota": str(a.target_user_id) if a.target_user_id else None, "rincian": a.rincian,
             "waktu": a.created_at.isoformat() if a.created_at else None} for a in rows]
