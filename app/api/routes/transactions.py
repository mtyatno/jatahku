import hashlib
import logging
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field, field_validator
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.period import document_date_kind
from app.models.models import (
    User, Transaction, Envelope, HouseholdMember, TransactionSource
)
from app.services.behavior import BehaviorCheckResult, check_behavior
from app.services.expense_rules import NOT_SPENDABLE_MSG, PAST_PERIOD_IGNORED, after_expense_recorded, is_spendable
from app.services.kotak_struk.config import PDF_MAX_BYTES
from app.services.kotak_struk.record import (
    NotRecordable, after_recorded, check_recordable, claim_failure_detail, claim_for_recording, heal_recorded,
)
from app.services.plan_limits import check_transaction_limit, has_txn_limit, quota_notice_after_input
from app.services import quota_pass
from app.services.transcription import transcribe_audio, TranscriptionError
from app.services.visibility import masked_description

router = APIRouter()
log = logging.getLogger("jatahku.transactions")

# Rate limiter lokal (pola sama dengan auth.py). Storage in-memory per instance.
limiter = Limiter(key_func=get_remote_address)

# Maks ukuran audio yang diterima (client membatasi rekaman 60 detik).
MAX_AUDIO_BYTES = 10 * 1024 * 1024

# = panjang kolom transactions.description. Keterangan yang lebih panjang (mis.
# hasil dikte) dipotong; dulu gagal 500 saat commit dan klien menganggapnya
# "belum pasti", sehingga kirim ulang terus gagal.
MAX_DESCRIPTION = 500


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
    # Item Kotak Struk yang dicatat transaksi ini (aturan: spec "Bagikan ke Jatahku" 5d).
    receipt_item_id: UUID | None = None

    @field_validator("description")
    @classmethod
    def fit_description(cls, v: str) -> str:
        return v[:MAX_DESCRIPTION]


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


class TransactionCreateResponse(TransactionResponse):
    # Basic: kuota bulan ini habis sesudah input ini → pemberitahuan untuk user.
    quota_notice: str | None = None


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
    receipt_item_id: UUID | None = None   # lihat TransactionCreate

    @field_validator("description")
    @classmethod
    def fit_description(cls, v: str) -> str:
        return v[:MAX_DESCRIPTION]


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
    # True = kiriman lain dengan client_ref yang sama masih diproses; hasil
    # belum pasti (klien jangan menganggapnya gagal permanen).
    pending: bool = False
    # Basic: kuota bulan ini habis sesudah kiriman ini (sama di setiap baris).
    quota_notice: str | None = None


async def _created(txn, user, db, after=None) -> TransactionCreateResponse:
    """Respons simpan: dibangun SEBELUM `after` (efek sesudah commit, async tanpa argumen), karena pemulihan sesi di
    dalamnya meng-expire `txn`; pemberitahuan kuota dihitung sesudahnya (`user` dimuat ulang oleh pemulihan itu)."""
    out = TransactionCreateResponse.model_validate(txn)
    if after is not None:
        await after()
    out.quota_notice = await quota_notice_after_input(user, db)
    return out


# ── Kotak Struk: `receipt_item_id` (spec "Bagikan ke Jatahku" 5d) ──
# Urutan di create/batch: cek idempotensi -> `_receipt_item_error` -> validasi lama -> `claim_for_recording` (sesi
# yang sama, tepat sebelum commit yang menyimpan transaksi, jadi klaim dan transaksi masuk/batal bersama) ->
# commit -> `record.after_recorded` (kirim ulang: `record.heal_recorded`). Klaim itulah yang mencegah satu bukti
# tercatat dua kali; `check_recordable` hanya memberi pesan yang ramah. Pemulihan sesi di helper itu meng-expire objek
# ORM, jadi respons dibangun SEBELUM efek sesudah commit dan batch hanya memakai id.

async def _receipt_item_error(db, user, rid: UUID) -> str | None:
    """None bila item boleh dicatat `user` sekarang, selain itu pesan 409-nya."""
    try:
        await check_recordable(db, rid, user)
    except NotRecordable as exc:
        return exc.detail
    return None


async def _after_saved(db, user, receipt_item_id: UUID | None, *, transaction_id: UUID, envelope_id: UUID,
                       description: str) -> None:
    """Sesudah commit: streak + belajar kata kunci (hook yang sama dengan bot); untuk item Kotak Struk juga menandainya
    `tercatat` (`record.after_recorded`: best-effort, pemulihan sesinya di sana). Hanya id dan keterangan yang
    diberikan: pemulihan sesi meng-expire objek transaksinya."""
    if receipt_item_id:
        await after_recorded(db, user, receipt_item_id, transaction_id=transaction_id, envelope_id=envelope_id,
                             description=description)
    else:
        await after_expense_recorded(db, user, envelope_id, description)


async def _check_row(db, user, row) -> tuple[date | None, BehaviorCheckResult]:
    """`check_behavior` satu baris create/batch (`TransactionCreate` / `BatchTransactionItem`), plus tanggal catatnya
    (None = hari ini). Baris dengan `receipt_item_id` mengikuti aturan bot (Task H1, `handlers._handle_txn_callback`):
    tanggal sesudah hari ini (salah baca) dicatat hari ini; tanggal sebelum awal periode anggaran berjalan dicatat di
    tanggal itu tanpa blok `PAST_PERIOD_IGNORED` (dana dan limit harian periode berjalan; limitnya juga tidak
    dinaikkan). Kunci amplop dan galat tetap memblokir; amplop tabungan dan kuota paket dicek pemanggil sebelumnya.
    Baris tanpa `receipt_item_id` (tanggalnya dipilih user): apa adanya. Hari ini = `date.today()`, sama dengan bot
    dan `check_behavior`."""
    check = await check_behavior(row.envelope_id, user.id, row.amount, db)
    txn_date = row.transaction_date
    if row.receipt_item_id and txn_date is not None:
        today = date.today()
        kind = document_date_kind(txn_date, payday_day=getattr(user, "payday_day", 1) or 1, today=today)
        if kind == "future":
            txn_date = today
        elif kind == "past" and not check.allowed and check.check_type in PAST_PERIOD_IGNORED:
            check = BehaviorCheckResult.ok()
    return txn_date, check


@router.post("/", response_model=TransactionCreateResponse, status_code=status.HTTP_201_CREATED)
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
            heal = None
            if req.receipt_item_id:
                async def heal():
                    await heal_recorded(db, user, req.receipt_item_id, existing.id, existing.envelope_id)
            return await _created(existing, user, db, after=heal)  # sudah tercatat sebelumnya (kirim ulang)
        await idempotency.forget(user.id, req.client_ref)  # transaksinya sudah tidak ada
    if req.receipt_item_id:
        receipt_error = await _receipt_item_error(db, user, req.receipt_item_id)
        if receipt_error:
            raise HTTPException(status_code=409, detail=receipt_error)
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
    # Kuota Basic dicek di awal input; bagian dari input yang dimulai saat kuota
    # masih ada (client_ref berizin) tetap boleh — lihat app/services/quota_pass.py.
    limit_ok, limit_msg = await check_transaction_limit(user, db)
    if not limit_ok and not await quota_pass.held(user.id, [req.client_ref]):
        raise HTTPException(status_code=403, detail=limit_msg)

    # Behavior checks — satu kali (dulu dua kali, dan cek pertama menolak cooling
    # sebelum pending sempat dibuat). Cooling tidak lagi menahan pencatatan.
    txn_date, check = await _check_row(db, user, req)
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
    user_id = user.id  # rollback di bawah meng-expire `user`
    try:
        if req.receipt_item_id and not await claim_for_recording(db, req.receipt_item_id, user_id):
            # Simpan lain (bot, ketukan kedua) mengklaim bukti ini di antara `check_recordable` dan sekarang, atau
            # bukti itu kedaluwarsa / dilewati: pesannya dari status terbaru, dibaca sesudah rollback.
            await db.rollback()
            raise HTTPException(status_code=409,
                                detail=await claim_failure_detail(db, req.receipt_item_id, user_id))
        txn = Transaction(
            envelope_id=req.envelope_id,
            user_id=user_id,
            amount=req.amount,
            description=req.description,
            source=req.source,
            transaction_date=txn_date or date.today(),
            is_private=req.is_private,
        )
        db.add(txn)
        await db.commit()   # transaksi dan klaimnya masuk (atau batal) bersama
    except Exception:
        await idempotency.release(user_id, req.client_ref)
        raise
    # Catat kunci segera setelah commit (id sudah ada), sebelum langkah lain.
    await idempotency.store(user.id, req.client_ref, txn.id)
    await db.refresh(txn)

    # Streak + pembelajaran kata kunci (best-effort) — hook yang sama dengan bot — dan penandaan item Kotak Struk.
    async def after():
        await _after_saved(db, user, req.receipt_item_id, transaction_id=txn.id, envelope_id=txn.envelope_id,
                           description=txn.description)
    return await _created(txn, user, db, after=after)


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
    # Satu kiriman = satu input. Kuota Basic dicek SEKALI di awal: bila masih ada,
    # seluruh kiriman diselesaikan walau melewati batas, dan client_ref-nya diberi
    # izin supaya kirim ulang bagian yang gagal juga boleh (quota_pass).
    quota_ok, quota_msg = await check_transaction_limit(user, db)
    refs = [it.client_ref for it in req.items if it.client_ref]
    if quota_ok:
        if has_txn_limit(user):  # Pro tanpa batas → tidak perlu izin
            await quota_pass.grant(user.id, refs)
        allowed_refs = None  # semua boleh
    else:
        allowed_refs = await quota_pass.held(user.id, refs)
    results = []
    for i, item in enumerate(req.items):
        existing_ref = await idempotency.lookup(user.id, item.client_ref)
        if existing_ref == idempotency.PENDING:
            results.append(BatchTransactionResult(index=i, ok=False, pending=True, description=item.description,
                                                  error="Sedang diproses, coba lagi sebentar"))
            continue
        if existing_ref:  # sudah tercatat di kiriman sebelumnya → jangan buat lagi
            if item.receipt_item_id:
                prior = await db.get(Transaction, UUID(existing_ref))
                if prior is not None:
                    await heal_recorded(db, user, item.receipt_item_id, prior.id, prior.envelope_id)
            results.append(BatchTransactionResult(index=i, ok=True, id=UUID(existing_ref), description=item.description))
            continue
        if not hid:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error="Household not found"))
            continue
        if item.receipt_item_id:
            receipt_error = await _receipt_item_error(db, user, item.receipt_item_id)
            if receipt_error:
                results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=receipt_error))
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
        if allowed_refs is not None and item.client_ref not in allowed_refs:
            results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=quota_msg))
            continue

        txn_date, check = await _check_row(db, user, item)
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
            results.append(BatchTransactionResult(index=i, ok=False, pending=True, description=item.description,
                                                  error="Sedang diproses, coba lagi sebentar"))
            continue
        try:
            if item.receipt_item_id and not await claim_for_recording(db, item.receipt_item_id, user.id):
                # Simpan lain mengklaim bukti ini di antara `check_recordable` dan sekarang (atau bukti itu kedaluwarsa
                # / dilewati). Klaim yang gagal tidak mengubah apa pun, jadi tidak ada yang perlu di-rollback (rollback
                # juga meng-expire `user`); `claim_failure_detail` membaca kolom status terbaru, bukan salinan ORM.
                await idempotency.release(user.id, item.client_ref)
                detail = await claim_failure_detail(db, item.receipt_item_id, user.id)
                results.append(BatchTransactionResult(index=i, ok=False, description=item.description, error=detail))
                continue
            txn = Transaction(
                envelope_id=item.envelope_id,
                user_id=user.id,
                amount=item.amount,
                description=item.description,
                source=item.source,
                transaction_date=txn_date or date.today(),
                is_private=item.is_private,
            )
            db.add(txn)
            await db.commit()   # per baris: transaksi dan klaimnya masuk (atau batal) bersama
        except Exception:
            await idempotency.release(user.id, item.client_ref)
            raise
        txn_id, txn_envelope_id = txn.id, txn.envelope_id   # pemulihan sesi di bawah meng-expire `txn`
        await idempotency.store(user.id, item.client_ref, txn_id)
        await db.refresh(txn)

        await _after_saved(db, user, item.receipt_item_id, transaction_id=txn_id, envelope_id=txn_envelope_id,
                           description=item.description)

        results.append(BatchTransactionResult(index=i, ok=True, id=txn_id, description=item.description))

    if any(r.ok for r in results):
        notice = await quota_notice_after_input(user, db)
        if notice:
            for r in results:
                r.quota_notice = notice
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
RECEIPT_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"}


async def _read_receipt_upload(image: UploadFile, *, allow_pdf: bool = True) -> tuple[bytes, str]:
    """Validasi upload foto/PDF struk. Tanpa deps framework supaya mudah di-test. Jenis sebenarnya (byte awal)
    diperiksa lagi oleh intake Kotak Struk. `allow_pdf=False` untuk rute yang belum menerima PDF (chat web
    `/bot/chat/photo`, keputusan Bagian B)."""
    content_type = (image.content_type or "").split(";")[0].strip().lower()
    if content_type not in RECEIPT_MIME or (content_type == "application/pdf" and not allow_pdf):
        raise HTTPException(
            status_code=415,
            detail=("Format tidak didukung. Pakai JPG, PNG, WebP, atau PDF." if allow_pdf
                    else "Format foto tidak didukung. Pakai JPG, PNG, atau WebP."))
    is_pdf = content_type == "application/pdf"
    max_bytes = PDF_MAX_BYTES if is_pdf else MAX_RECEIPT_BYTES
    data = await image.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Foto kosong, coba lagi")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="PDF terlalu besar (maks 10 MB)" if is_pdf else "Foto terlalu besar (maks 8 MB)")
    return data, content_type


def receipt_key_func(request: Request) -> str:
    """Rate limit per user (klaim `sub` JWT), stabil walau token di-refresh. Tidak dipakai `scan-receipt` lagi: batasnya
    batas intake Kotak Struk (gabungan semua kanal)."""
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
    """Panggil layanan scan + petakan error ke HTTP. Dipakai endpoint web. IntakeRejected → status code-nya;
    OcrBusy (termasuk ScanBusy: belum selesai dibaca) → 503 ramai; OcrFailed → 422 dengan pesan galat item. OCR yang
    tidak terpasang sampai ke sini sebagai item `gagal` (OcrFailed), bukan OcrUnavailable."""
    from app.services.kotak_struk.intake import IntakeRejected
    from app.services.receipt_ocr import OcrBusy, OcrFailed
    from app.services.receipt_scan import scan_receipt

    try:
        return await scan_receipt(user, data, content_type, db)
    except IntakeRejected as exc:  # jenis/ukuran tidak cocok, atau batas per jam / item menunggu
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except OcrBusy:  # termasuk ScanBusy
        raise HTTPException(status_code=503, detail="Scan struk sedang ramai. Coba lagi beberapa detik lagi.")
    except OcrFailed as exc:  # item `gagal`: pesannya dari worker, aman ditampilkan (mis. "PDF terkunci kata sandi")
        raise HTTPException(status_code=422, detail=str(exc) or "Foto tidak bisa dibuka atau resolusinya terlalu besar. Coba foto ulang.")


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
async def scan_receipt_endpoint(
    request: Request,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gambar atau PDF → Kotak Struk (source `web_form`), menunggu hasil maks WAIT_FORM_S; respons lama + field baru.
    Tanpa kuota scan; batas intake Kotak Struk berlaku."""
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
