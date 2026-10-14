import hashlib
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, Transaction, Envelope, HouseholdMember, TransactionSource
)
from app.services.behavior import check_behavior
from app.services.expense_rules import NOT_SPENDABLE_MSG, after_expense_recorded, is_spendable
from app.services.plan_limits import check_transaction_limit
from app.services.transcription import transcribe_audio, TranscriptionError
from app.services.visibility import masked_description

router = APIRouter()

# Rate limiter lokal (pola sama dengan auth.py). Storage in-memory per instance.
limiter = Limiter(key_func=get_remote_address)

# Maks ukuran audio yang diterima (client membatasi rekaman 60 detik).
MAX_AUDIO_BYTES = 10 * 1024 * 1024


class TransactionCreate(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource = TransactionSource.webapp
    transaction_date: date | None = None
    is_private: bool = False
    # User mengonfirmasi "Catat, naikkan limit hari ini" (sama dengan bot)
    raise_daily_limit: bool = False
    # Kunci idempotensi dari klien: kirim ulang tidak mencatat dua kali.
    client_ref: str | None = Field(default=None, max_length=64)


class TransactionResponse(BaseModel):
    id: UUID
    envelope_id: UUID
    user_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource
    transaction_date: date
    created_at: datetime
    is_deleted: bool
    is_private: bool = False
    is_own: bool = True
    is_adjustment: bool = False

    model_config = {"from_attributes": True}


class SuggestEnvelopeRequest(BaseModel):
    description: str


class BatchSuggestEnvelopeRequest(BaseModel):
    descriptions: list[str]


class BatchSuggestEnvelopeResult(BaseModel):
    index: int
    envelope_id: str | None
    envelope_name: str | None
    confident: bool


class BatchTransactionItem(BaseModel):
    envelope_id: UUID
    amount: Decimal
    description: str
    source: TransactionSource = TransactionSource.webapp
    transaction_date: date | None = None
    is_private: bool = False
    raise_daily_limit: bool = False
    client_ref: str | None = Field(default=None, max_length=64)


def _rp(x) -> str:
    return f"Rp{int(x):,}".replace(",", ".")


def daily_limit_message(envelope_name: str, d: dict) -> str:
    """Pesan blok limit harian. Frontend mengenali frasa "limit harian" untuk
    menawarkan tombol "Catat, naikkan limit hari ini"."""
    return (f"Melebihi limit harian {envelope_name}: limit {_rp(d.get('daily_limit', 0))}/hari, "
            f"terpakai {_rp(d.get('spent_today', 0))}, diminta {_rp(d.get('requested', 0))}.")


async def _raise_daily_limit(user_id, envelope_id) -> None:
    """Naikkan limit harian hari ini (fungsi yang sama dengan bot)."""
    from app.services.behavior import raise_daily_limit_today
    try:
        await raise_daily_limit_today(user_id, envelope_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Gagal menaikkan limit harian. Coba lagi sebentar.")


class BatchTransactionCreate(BaseModel):
    items: list[BatchTransactionItem]


class BatchTransactionResult(BaseModel):
    index: int
    ok: bool
    id: UUID | None = None
    description: str
    error: str | None = None


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    req: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import idempotency
    existing_ref = await idempotency.lookup(user.id, req.client_ref)
    if existing_ref == idempotency.PENDING:
        raise HTTPException(status_code=409, detail="Transaksi ini sedang diproses. Coba lagi sebentar.")
    if existing_ref:
        existing = await db.get(Transaction, UUID(existing_ref))
        if existing and existing.user_id == user.id:
            return existing  # sudah tercatat sebelumnya (kirim ulang)
    # Verify envelope belongs to user's household
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    result = await db.execute(
        select(Envelope).where(
            Envelope.id == req.envelope_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        raise HTTPException(status_code=404, detail="Envelope not found")

    # Aturan bersama web + Telegram (app/services/expense_rules.py)
    if not is_spendable(envelope):
        raise HTTPException(status_code=403, detail=NOT_SPENDABLE_MSG)
    limit_ok, limit_msg = await check_transaction_limit(user, db)
    if not limit_ok:
        raise HTTPException(status_code=403, detail=limit_msg)

    # Behavior checks — satu kali (dulu dua kali, dan cek pertama menolak cooling
    # sebelum pending sempat dibuat). Cooling tidak lagi menahan pencatatan.
    check = await check_behavior(req.envelope_id, user.id, req.amount, db)
    if not check.allowed and check.check_type == "daily_limit" and req.raise_daily_limit:
        # Dikonfirmasi user → limit dinaikkan sampai tengah malam, lalu cek ulang.
        await _raise_daily_limit(user.id, envelope.id)
        check = await check_behavior(req.envelope_id, user.id, req.amount, db)
    if not check.allowed:
        if check.check_type == "locked":
            raise HTTPException(status_code=403, detail=f"Amplop dikunci. Tidak bisa belanja.")
        elif check.check_type == "not_funded":
            raise HTTPException(status_code=403, detail=f"💸 {check.reason}")
        elif check.check_type == "insufficient":
            d = check.details
            raise HTTPException(status_code=403, detail=f"💸 Dana tidak cukup. Sisa: Rp{int(d.get('available', 0)):,}, diminta: Rp{int(d.get('requested', 0)):,}")
        elif check.check_type == "daily_limit":
            raise HTTPException(status_code=403, detail=daily_limit_message(envelope.name, check.details))
        else:
            raise HTTPException(status_code=403, detail=check.reason or "Transaksi tidak bisa dicatat.")

    if not await idempotency.reserve(user.id, req.client_ref):
        raise HTTPException(status_code=409, detail="Transaksi ini sedang diproses. Coba lagi sebentar.")
    txn = Transaction(
        envelope_id=req.envelope_id,
        user_id=user.id,
        amount=req.amount,
        description=req.description,
        source=req.source,
        transaction_date=req.transaction_date or date.today(),
        is_private=req.is_private,
    )
    db.add(txn)
    try:
        await db.commit()
    except Exception:
        await idempotency.release(user.id, req.client_ref)
        raise
    await db.refresh(txn)
    await idempotency.store(user.id, req.client_ref, txn.id)

    # Streak + pembelajaran kata kunci (best-effort) — hook yang sama dengan bot.
    await after_expense_recorded(db, user, req.envelope_id, req.description)

    return txn


@router.post("/suggest-envelope")
async def suggest_envelope(
    req: SuggestEnvelopeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.txn_nlp import find_best_envelope
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid or not req.description.strip():
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    envelope, confident = await find_best_envelope(req.description, hid, db, user.id)
    if not envelope:
        return {"envelope_id": None, "envelope_name": None, "confident": False}
    return {"envelope_id": str(envelope.id), "envelope_name": envelope.name, "confident": bool(confident)}


@router.post("/suggest-envelopes")
async def suggest_envelopes(
    req: BatchSuggestEnvelopeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.txn_nlp import find_best_envelope
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        return {"results": [{"index": i, "envelope_id": None, "envelope_name": None, "confident": False} for i in range(len(req.descriptions))]}

    results = []
    for i, desc in enumerate(req.descriptions):
        if not desc or not desc.strip():
            results.append({"index": i, "envelope_id": None, "envelope_name": None, "confident": False})
            continue
        envelope, confident = await find_best_envelope(desc, hid, db, user.id)
        if envelope:
            results.append({"index": i, "envelope_id": str(envelope.id), "envelope_name": envelope.name, "confident": bool(confident)})
        else:
            results.append({"index": i, "envelope_id": None, "envelope_name": None, "confident": False})
    return {"results": results}


@router.post("/batch")
async def batch_create_transactions(
    req: BatchTransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    from app.services import idempotency
    results = []
    for i, item in enumerate(req.items):
        existing_ref = await idempotency.lookup(user.id, item.client_ref)
        if existing_ref == idempotency.PENDING:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description,
                                                  error="Sedang diproses, coba lagi sebentar"))
            continue
        if existing_ref:  # sudah tercatat di kiriman sebelumnya → jangan buat lagi
            results.append(BatchTransactionResult(index=i, ok=True, id=UUID(existing_ref), description=item.description))
            continue
        if not hid:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error="Household not found"))
            continue

        result_env = await db.execute(
            select(Envelope).where(
                Envelope.id == item.envelope_id,
                Envelope.household_id == hid,
                or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
            )
        )
        envelope = result_env.scalar_one_or_none()
        if not envelope:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error="Envelope not found"))
            continue

        if not is_spendable(envelope):
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=NOT_SPENDABLE_MSG))
            continue
        limit_ok, limit_msg = await check_transaction_limit(user, db)
        if not limit_ok:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=limit_msg))
            continue

        check = await check_behavior(item.envelope_id, user.id, item.amount, db)
        if not check.allowed and check.check_type == "daily_limit" and item.raise_daily_limit:
            try:
                from app.services.behavior import raise_daily_limit_today
                await raise_daily_limit_today(user.id, envelope.id)
                check = await check_behavior(item.envelope_id, user.id, item.amount, db)
            except Exception:
                pass  # Redis gagal → tetap dilaporkan sebagai melebihi limit harian
        if not check.allowed:
            msg = check.reason or ""
            if check.check_type == "locked":
                msg = f"Amplop dikunci. Tidak bisa belanja."
            elif check.check_type == "daily_limit":
                msg = daily_limit_message(envelope.name, check.details)
            elif check.check_type == "not_funded":
                msg = check.reason or "Amplop belum didanai"
            elif check.check_type == "insufficient":
                d = check.details
                msg = f"Dana tidak cukup. Sisa: Rp{int(d.get('available', 0)):,}, diminta: Rp{int(d.get('requested', 0)):,}"
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=msg))
            continue

        if not await idempotency.reserve(user.id, item.client_ref):
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description,
                                                  error="Sedang diproses, coba lagi sebentar"))
            continue
        txn = Transaction(
            envelope_id=item.envelope_id,
            user_id=user.id,
            amount=item.amount,
            description=item.description,
            source=item.source,
            transaction_date=item.transaction_date or date.today(),
            is_private=item.is_private,
        )
        db.add(txn)
        try:
            await db.commit()
        except Exception:
            await idempotency.release(user.id, item.client_ref)
            raise
        await db.refresh(txn)
        await idempotency.store(user.id, item.client_ref, txn.id)

        await after_expense_recorded(db, user, item.envelope_id, item.description)

        results.append(BatchTransactionResult(index=i, ok=True, id=txn.id, description=item.description))

    return results


def transcribe_key_func(request: Request) -> str:
    """Rate limit per-user: hash header Authorization; fallback ke IP."""
    auth = request.headers.get("authorization", "")
    if auth:
        return hashlib.sha256(auth.encode()).hexdigest()[:16]
    return get_remote_address(request)


async def _transcribe_request(audio: UploadFile) -> str:
    """Validasi + panggil provider. Tanpa deps framework supaya mudah di-test."""
    content_type = (audio.content_type or "").split(";")[0].strip()
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Format audio tidak didukung")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Tidak ada suara terdeteksi, coba lagi")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Rekaman terlalu panjang (maks 60 detik)")
    try:
        text = await transcribe_audio(data, content_type)
    except TranscriptionError:
        raise HTTPException(status_code=502, detail="Transkripsi gagal, coba lagi")
    if not text:
        raise HTTPException(status_code=422, detail="Tidak ada suara terdeteksi, coba lagi")
    return text


@router.post("/transcribe")
@limiter.limit("20/hour", key_func=transcribe_key_func)
async def transcribe_endpoint(
    request: Request,
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    return {"text": await _transcribe_request(audio)}


# ── Scan struk (OCR RapidOCR, tanpa LLM; fallback LLM opsional ber-plafon) ──

# Client mengompres foto (sisi panjang ≤1600px, JPEG) jadi ±300 KB; batas ini
# menampung foto mentah dari klien lama / bot.
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
RECEIPT_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


async def _read_receipt_upload(image: UploadFile) -> tuple[bytes, str]:
    """Validasi upload foto struk. Tanpa deps framework supaya mudah di-test."""
    content_type = (image.content_type or "").split(";")[0].strip().lower()
    if content_type not in RECEIPT_MIME:
        raise HTTPException(status_code=415, detail="Format foto tidak didukung. Pakai JPG, PNG, atau WebP.")
    data = await image.read(MAX_RECEIPT_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Foto kosong, coba lagi")
    if len(data) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="Foto terlalu besar (maks 8 MB)")
    return data, content_type


def receipt_key_func(request: Request) -> str:
    """Rate limit per user (klaim `sub` JWT), stabil walau token di-refresh."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            import jwt as pyjwt
            sub = pyjwt.decode(auth[7:], options={"verify_signature": False}).get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return transcribe_key_func(request)


async def run_receipt_scan(user: User, data: bytes, content_type: str, db: AsyncSession) -> dict:
    """Panggil layanan scan + petakan error ke HTTP. Dipakai endpoint web."""
    from app.services.receipt_ocr import OcrBusy, OcrFailed, OcrUnavailable
    from app.services.receipt_scan import ScanQuotaExceeded, scan_receipt

    try:
        return await scan_receipt(user, data, content_type, db)
    except ScanQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=f"Kuota scan struk bulan ini ({exc.limit}x) sudah habis. Upgrade ke Pro untuk scan tanpa batas, atau catat manual.",
        )
    except OcrUnavailable:
        raise HTTPException(status_code=503, detail="Scan struk sedang tidak tersedia. Catat manual dulu ya.")
    except OcrBusy:
        raise HTTPException(status_code=503, detail="Scan struk sedang ramai. Coba lagi beberapa detik lagi.")
    except OcrFailed:
        raise HTTPException(status_code=422, detail="Foto tidak bisa dibuka atau resolusinya terlalu besar. Coba foto ulang.")


class ReceiptFeedback(BaseModel):
    saved: bool
    total: Decimal | None = Field(default=None, gt=0, lt=10**12)
    transaction_date: date | None = None
    merchant: str | None = Field(default=None, max_length=200)


@router.get("/scan-receipt/quota")
async def receipt_scan_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.receipt_scan import get_quota
    return (await get_quota(user, db)).as_dict()


@router.post("/scan-receipt")
@limiter.limit("30/hour", key_func=receipt_key_func)
async def scan_receipt_endpoint(
    request: Request,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data, content_type = await _read_receipt_upload(image)
    return await run_receipt_scan(user, data, content_type, db)


@router.post("/scan-receipt/{scan_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def receipt_scan_feedback(
    scan_id: UUID,
    req: ReceiptFeedback,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Nilai akhir yang disimpan user → bahan belajar parser. Best-effort."""
    from app.services.receipt_scan import apply_feedback
    await apply_feedback(
        user, scan_id, db, saved=req.saved,
        total=int(req.total) if req.total is not None else None,
        txn_date=req.transaction_date, merchant=req.merchant,
    )


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    envelope_id: UUID | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(20, le=500),
    offset: int = Query(0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()

    query = (
        select(Transaction)
        .join(Envelope)
        .where(
            Envelope.household_id == hid,
            Transaction.is_deleted == False,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    if envelope_id:
        query = query.where(Transaction.envelope_id == envelope_id)
    if start_date:
        query = query.where(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.where(Transaction.transaction_date <= end_date)

    query = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    txns = result.scalars().all()
    return [
        TransactionResponse(
            id=t.id, envelope_id=t.envelope_id, user_id=t.user_id,
            amount=t.amount,
            description=masked_description(user.id, t),
            source=t.source, transaction_date=t.transaction_date,
            created_at=t.created_at, is_deleted=t.is_deleted,
            is_private=t.is_private,
            is_own=str(t.user_id) == str(user.id),
            is_adjustment=getattr(t, "balance_check_id", None) is not None,
        )
        for t in txns
    ]


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    txn_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    )
    hid = result.scalar_one_or_none()
    if not hid:
        raise HTTPException(status_code=404, detail="Household not found")

    result = await db.execute(
        select(Transaction)
        .join(Envelope)
        .where(
            Transaction.id == txn_id,
            Envelope.household_id == hid,
            or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
        )
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn.is_deleted = True
    await db.commit()
