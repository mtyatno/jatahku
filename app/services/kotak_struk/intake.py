"""Satu-satunya pintu masuk Kotak Struk: unggahan dari kanal mana pun (Telegram, chat web,
form web, PWA share) menjadi item `diterima` di `receipt_scans` (spec 2026-10-26 bagian
1, 2a, 3d, 6a, 6c). Di sini: validasi, idempotensi (upload_id, file yang sama), batas
(per jam, item menunggu), dan penyimpanan file sementara. Membaca isi bukti adalah
tugas worker."""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.ruang import ruang_keluarga_id
from app.models.models import ReceiptScan, User
from app.services.kotak_struk import dedup
from app.services.kotak_struk.config import (
    IMAGE_MAX_BYTES, MAX_PENDING, PDF_MAX_BYTES, RATE_PER_HOUR, SOURCES, ST_DIPROSES, ST_DITERIMA,
    TEXT_MAX_CHARS,
)
from app.services.kotak_struk.extract import sniff_type

log = logging.getLogger(__name__)

RATE_WINDOW_S = 3600
MSG_EMPTY = "Kirim satu file atau teks"
MSG_TYPE = "Kirim foto (JPG/PNG/WebP), PDF, atau teks"
MSG_TEXT_LONG = "Teks terlalu panjang"
MSG_IMAGE_BIG = "Foto terlalu besar (maks 8 MB)"
MSG_PDF_BIG = "PDF terlalu besar (maks 10 MB)"
MSG_RATE = "Terlalu banyak bukti. Coba lagi sebentar."
MSG_PENDING = "Masih ada bukti yang sedang dibaca. Tunggu sebentar."


@dataclass
class IntakeRequest:
    user: User
    source: str
    upload_id: str | None = None
    data: bytes | None = None
    content_type: str | None = None  # klaim klien; jenis file ditentukan dari isinya (sniff_type)
    text: str | None = None
    channel_meta: dict | None = None


class IntakeRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def normalize_text(text: str) -> str:
    """Baris di-strip, baris kosong dibuang (sama dengan extract_text untuk text/plain)."""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


async def _rate_limited(redis, user_id: uuid.UUID) -> bool:
    """Batas gabungan semua kanal per user per jam. Redis bermasalah -> tidak dibatasi."""
    owned = None
    try:
        if redis is None:
            import redis.asyncio as aioredis
            redis = owned = aioredis.from_url(get_settings().REDIS_URL)
        key = f"kotak:rate:{user_id}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, RATE_WINDOW_S)
        return count > RATE_PER_HOUR
    except Exception as exc:
        log.warning("batas per jam Kotak Struk dilewati (Redis): %s", exc)
        return False
    finally:
        if owned is not None:
            try:
                await owned.aclose()
            except Exception:
                pass


def _write_file(kotak_dir: str, name: str, payload: bytes) -> str:
    """Tulis berkas bukti baru (mode 0600, gagal bila sudah ada). Berkas separuh jadi dihapus."""
    os.makedirs(kotak_dir, mode=0o700, exist_ok=True)
    path = os.path.join(kotak_dir, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _remove_file(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _wake_worker() -> None:
    try:
        # import_module (bukan `from paket import worker`): tidak bergantung pada atribut paket,
        # jadi modul yang diganti di sys.modules (tes) atau yang tidak bisa diimpor tetap dihormati.
        worker = importlib.import_module("app.services.kotak_struk.worker")
    except ImportError:  # worker tidak bisa diimpor di proses ini
        return
    try:
        worker.wake()
    except Exception as exc:  # item sudah tersimpan; worker tetap menemukannya lewat polling
        log.warning("worker.wake gagal: %s", exc)


async def create_item(db: AsyncSession, req: IntakeRequest, *, redis=None, kotak_dir: str | None = None,
                      now: datetime | None = None) -> tuple[ReceiptScan, bool]:
    """Buat item Kotak Struk dari satu unggahan. Mengembalikan (item, dibuat_baru); bila unggahan
    yang sama sudah ada (upload_id, atau file sama yang belum selesai) item lama dikembalikan
    dengan `False`. Gagal -> IntakeRejected(status_code, detail)."""
    user_id = req.user.id  # simpan: rollback bisa meng-expire objek User
    text = req.text if req.text is not None and req.text.strip() else None
    data = req.data or None

    # 1-2. satu file atau satu teks; sumber dikenal
    if (data is None) == (text is None):
        raise IntakeRejected(422, MSG_EMPTY)
    if req.source not in SOURCES:
        raise IntakeRejected(422, "Sumber tidak dikenal")

    # 3. upload_id yang sama (idempotensi); string kosong bukan kunci
    upload_id = req.upload_id or None
    if upload_id:
        existing = await dedup.find_by_upload(db, user_id, upload_id)
        if existing is not None:
            return existing, False

    # 4. ukuran dan jenis
    if text is not None:
        if len(text) > TEXT_MAX_CHARS:
            raise IntakeRejected(413, MSG_TEXT_LONG)
        payload = normalize_text(text).encode("utf-8")
        content_type = "text/plain"
    else:
        content_type = sniff_type(data)
        if content_type is None:
            raise IntakeRejected(415, MSG_TYPE)
        if content_type == "application/pdf":
            if len(data) > PDF_MAX_BYTES:
                raise IntakeRejected(413, MSG_PDF_BIG)
        elif len(data) > IMAGE_MAX_BYTES:
            raise IntakeRejected(413, MSG_IMAGE_BIG)
        payload = data
    sha = hashlib.sha256(payload).hexdigest()

    # 5. file yang sama dengan item user yang belum selesai
    existing = await dedup.find_open_by_file(db, user_id, sha)
    if existing is not None:
        return existing, False

    # 6. batas per jam
    if await _rate_limited(redis, user_id):
        raise IntakeRejected(429, MSG_RATE)

    # 7. item menunggu dibaca
    pending = (await db.execute(
        select(func.count()).select_from(ReceiptScan)
        .where(ReceiptScan.user_id == user_id, ReceiptScan.status.in_((ST_DITERIMA, ST_DIPROSES)))
    )).scalar_one()
    if pending >= MAX_PENDING:
        raise IntakeRejected(429, MSG_PENDING)

    # 8. buat item + tulis file. Satu SAVEPOINT: balapan upload_id (indeks unik) atau gagal tulis
    # file membatalkan barisnya saja, tanpa meng-expire objek lain di sesi pemanggil.
    # Bukti dari chat dan dari web sama-sama dicatat ke ruang keluarga sampai R3 (ruang dari objek).
    household_id = await ruang_keluarga_id(db, user_id)
    kotak_dir = kotak_dir or get_settings().KOTAK_DIR
    item = ReceiptScan(
        user_id=user_id, status=ST_DITERIMA, source=req.source, upload_id=upload_id,
        household_id=household_id, file_sha256=sha, content_type=content_type,
        channel_meta=req.channel_meta, engine="rapidocr", confidence="gagal",
    )
    if now is not None:
        item.created_at = now
    path = None
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
            path = _write_file(kotak_dir, str(item.id), payload)
            item.file_path = path
    except IntegrityError:
        # Permintaan lain dengan upload_id yang sama menang balapan: pakai item itu.
        if upload_id:
            winner = await dedup.find_by_upload(db, user_id, upload_id)
            if winner is not None:
                return winner, False
        raise
    try:
        await db.commit()
    except BaseException:
        _remove_file(path)
        await db.rollback()
        raise

    # 9. bangunkan worker
    _wake_worker()
    return item, True
