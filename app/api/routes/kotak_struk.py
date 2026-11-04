"""API Kotak Struk ("Bagikan ke Jatahku"; spec 2026-10-26 bagian 5d): unggah bukti, daftar, jumlah, dan detail item,
saran amplop, lewati, jawaban "Aplikasi apa ini?" (belajar lintas user tahap 2), dan nama panggilan merchant. Tipis: validasi dan pengecekan intake ada di
`services/kotak_struk/intake.py`, bentuk detail di `services/kotak_struk/view.py`.

Hanya pemilik item yang bisa melihat atau mengubahnya; item orang lain sama dengan tidak ada (404)."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import ReceiptScan, User
from app.services.kotak_struk import belajar, record
from app.services.kotak_struk.config import PDF_MAX_BYTES, ST_SIAP, WAIT_FORM_S
from app.services.kotak_struk.intake import IntakeRejected, IntakeRequest, create_item
from app.services.kotak_struk.merchants import NICKNAME_MAX, display_name, set_display_name
from app.services.kotak_struk.record import MSG_CANNOT_SKIP, MSG_NOT_FOUND
from app.services.kotak_struk.view import item_detail
from app.services.kotak_struk.waiter import wait_for_item
from app.services.ruang import ruang_objek

router = APIRouter()

LIST_LIMIT = 50
MSG_MERCHANT_NOT_FOUND = "Merchant tidak ditemukan"
MSG_APP_NOT_ASKABLE = "Aplikasi bukti ini tidak bisa dipilih"
MSG_APP_INVALID = "Pilihan aplikasi tidak dikenal"
NOTE_MAX = 200
APP_MAX = 20


class SuggestIn(BaseModel):
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class SkipIn(BaseModel):
    reason: Literal["bukan_pengeluaran", "duplikat", "batal"]
    # Tahap 2 (M3a): alasan "Bukan pengeluaran" (suara aturan `arah`); opsional, hanya bersama `bukan_pengeluaran`.
    alasan: Literal["top_up", "masuk", "antar_rekening_sendiri"] | None = None

    @model_validator(mode="after")
    def _alasan_only_for_not_expense(self):
        if self.alasan is not None and self.reason != record.SKIP_NOT_EXPENSE:
            raise ValueError(record.MSG_ALASAN_ONLY_NOT_EXPENSE)
        return self


class AppChoiceIn(BaseModel):
    app: str = Field(max_length=APP_MAX)   # kunci profil aplikasi atau "baru" (`belajar.APP_CHOICES`)


class AppChoiceOut(BaseModel):
    app: str
    ask_app: bool = False


class MerchantNameIn(BaseModel):
    display_name: str = Field(max_length=NICKNAME_MAX)


class KotakCountResponse(BaseModel):
    count: int


def _mine_with_status(user: User, status: str) -> tuple:
    """Saringan daftar dan jumlah: item milik `user` dengan status itu. Baris riwayat scan lama (status NULL) tidak
    pernah cocok."""
    return ReceiptScan.user_id == user.id, ReceiptScan.status == status


async def _owned_item(db: AsyncSession, item_id: UUID, user: User, *, reload: bool = False) -> ReceiptScan:
    """Item Kotak Struk milik `user`, atau 404. Baris riwayat scan lama (tanpa status) bukan item Kotak Struk.
    `reload`: baca ulang dari database walau objeknya sudah ada di sesi (worker mengubahnya lewat sesi lain)."""
    query = select(ReceiptScan).where(ReceiptScan.id == item_id, ReceiptScan.user_id == user.id,
                                      ReceiptScan.status.is_not(None))
    if reload:
        query = query.execution_options(populate_existing=True)
    item = (await db.execute(query)).scalars().first()
    if item is None:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    return item


@router.post("/")
async def upload(
    response: Response,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    source: str = Form(...),
    upload_id: str | None = Form(default=None, max_length=64),
    wait: int = Form(default=0, ge=0, le=WAIT_FORM_S),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Satu file (foto/PDF) atau satu teks menjadi item `diterima`. 201 item baru, 200 item yang sudah ada
    (upload_id sama). `wait` detik menunggu hasil baca sebelum menjawab."""
    # Cukup sampai satu byte di atas batas terbesar: intake yang menolak (413), isi yang lebih besar tidak dibaca.
    data = await file.read(PDF_MAX_BYTES + 1) if file is not None else None
    req = IntakeRequest(user, source, upload_id=upload_id, data=data,
                        content_type=file.content_type if file is not None else None, text=text)
    try:
        item, created = await create_item(db, req)
    except IntakeRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    # PENTING: commit, BUKAN rollback: rollback meng-expire `user` milik pemanggil (MissingGreenlet di AsyncSession).
    # `create_item` hanya commit untuk item baru; item yang sudah ada dikembalikan dengan transaksi baca masih terbuka,
    # yang menahan koneksi (`idle in transaction`) selama menunggu.
    await db.commit()
    response.status_code = 201 if created else 200
    if wait > 0:
        await wait_for_item(item.id, wait)
        item = await _owned_item(db, item.id, user, reload=True)
    return await item_detail(db, item, user)


@router.get("/")
async def list_items(
    status: str = Query(default=ST_SIAP, max_length=16),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Item milik user dengan status itu (bawaan `siap`: bukti menunggu dicatat), terbaru dulu."""
    rows = (await db.execute(
        select(ReceiptScan).where(*_mine_with_status(user, status))
        .order_by(ReceiptScan.created_at.desc(), ReceiptScan.id.desc()).limit(LIST_LIMIT)
    )).scalars().all()
    return {"items": [await item_detail(db, item, user) for item in rows]}


# Harus di atas `/{item_id}`: rute itu bertipe UUID, jadi "count" di sana dijawab 422, bukan diteruskan ke sini.
@router.get("/count", response_model=KotakCountResponse)
async def count_items(
    status: str = Query(default=ST_SIAP, max_length=16),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Jumlah item milik user dengan status itu (bawaan `siap`), saringan yang sama dengan daftar tanpa batas daftar:
    satu COUNT tanpa detail per item (angka banner "bukti menunggu dicatat" di web)."""
    count = (await db.execute(
        select(func.count()).select_from(ReceiptScan).where(*_mine_with_status(user, status))
    )).scalar_one()
    return {"count": count}


@router.get("/{item_id}")
async def get_item(item_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await item_detail(db, await _owned_item(db, item_id, user), user)


@router.post("/{item_id}/saran")
async def suggest(item_id: UUID, body: SuggestIn, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    """Saran amplop dan keterangan dengan catatan user (dipanggil saat catatan berubah)."""
    detail = await item_detail(db, await _owned_item(db, item_id, user), user, note=body.note)
    return {"suggestion": detail["suggestion"], "description_preview": detail["description_preview"]}


@router.post("/{item_id}/lewati")
async def skip_item(item_id: UUID, body: SkipIn, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """Item `siap`/`gagal` -> `dilewati` (`record.skip_item`, sama dengan tombol bot): pencatatan dan melewati tidak
    mungkin sama-sama menang. `alasan` (opsional, hanya dengan `bukan_pengeluaran`; selain itu 422) menjadi suara
    aturan `arah` bila beda dari arah yang terbaca; galat suara tidak pernah menggagalkan lewati."""
    item = await _owned_item(db, item_id, user)
    try:
        skipped = await record.skip_item(db, item_id, user.id, body.reason, alasan=body.alasan)
    except ValueError as exc:   # pertahanan; `SkipIn` sudah menolaknya
        raise HTTPException(status_code=422, detail=str(exc))
    if not skipped:
        raise HTTPException(status_code=409, detail=MSG_CANNOT_SKIP)
    await db.refresh(item)
    return await item_detail(db, item, user)


@router.post("/{item_id}/aplikasi", response_model=AppChoiceOut)
async def choose_app(item_id: UUID, body: AppChoiceIn, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """Jawaban "Aplikasi apa ini?" untuk bukti `tidak_dikenali` berkunci logo (`flags.ask_app`): sekali per item, menjadi
    suara aturan `logo` (`belajar.learn_app_choice`; tidak mencatat, tidak mengubah status item). Item tidak ada/milik
    user lain 404; nilai bukan kunci profil atau "baru" 422; item yang tidak bisa ditanya atau sudah dijawab 409."""
    item = await _owned_item(db, item_id, user)
    if body.app not in belajar.APP_CHOICES:
        raise HTTPException(status_code=422, detail=MSG_APP_INVALID)
    if belajar.app_logo(item) is None or not await belajar.learn_app_choice(
            db, item, body.app, user_id=user.id, user_name=user.name):
        raise HTTPException(status_code=409, detail=MSG_APP_NOT_ASKABLE)
    await db.commit()
    return AppChoiceOut(app=body.app, ask_app=False)


@router.put("/merchants/{merchant_id}")
async def rename_merchant(merchant_id: UUID, body: MerchantNameIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Nama panggilan merchant untuk seluruh rumah tangga (dibersihkan; kosong menghapusnya). Hanya anggota
    rumah tangga merchant itu (R3: ruang dari baris merchant, lalu keanggotaan dicek)."""
    from app.models.models import HouseholdMerchant
    merchant = await db.get(HouseholdMerchant, merchant_id)
    household_id = await ruang_objek(db, user, merchant.household_id if merchant else None)
    row = await set_display_name(db, merchant_id, household_id, body.display_name) if household_id else None
    if row is None:
        raise HTTPException(status_code=404, detail=MSG_MERCHANT_NOT_FOUND)
    await db.commit()
    return {"id": str(row.id), "name": display_name(row.raw_name), "display_name": row.display_name}
