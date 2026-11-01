"""Pemeliharaan Kotak Struk (spec 2026-10-26 §2d "Masa simpan"). Dijalankan scheduler tiap jam
(`scheduler.kotak_maintenance`).

- `expire_items`: item `siap`/`gagal` yang tidak dikonfirmasi sampai `expires_at` (ITEM_EXPIRY) -> `kedaluwarsa`,
  teks OCR dibuang. Barisnya tetap disimpan (hash file, ref_hash, counterparty_key, transaction_ids, outcome
  tidak disentuh), supaya bukti yang sama tetap bisa dikenali.
- `purge_layouts`: kerangka tata letak (`layout`, belajar lintas user) item selesai (`tercatat`/`dilewati`/`kedaluwarsa`)
  dihapus 24 jam (LAYOUT_TTL) sejak dibaca (`processed_at`); tidak pernah sebelum item selesai, karena belajar dari
  koreksi terjadi saat item selesai. Item kedaluwarsa juga kehilangan kerangkanya di `expire_items`.
- `reconcile_proof_rules`: aturan belajar (`proof_rules`) disamakan dengan tabel suara (`belajar.reconcile_rules`):
  hitungan yang tertinggal karena dua suara bersamaan diperbaiki dan aturan yang terlewat dibuat (review L2 M-2);
  aturan `menunggu` yang turun di bawah ambang (user dilupakan) dihapus, suaranya tetap (review L4a m-6).
- `delete_orphan_files`: berkas di folder sementara yang lebih tua dari ORPHAN_FILE_AGE dan bukan milik item
  yang belum dibaca (`diterima`/`diproses`). Biasanya berkas sudah dihapus worker begitu item selesai; ini
  menyapu sisa (proses mati di tengah jalan, baris item terhapus bersama akun).

Teks OCR yang tidak pernah diberi feedback tetap dihapus setelah 24 jam oleh `receipt_scan.purge_stale_ocr_text`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import null, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ReceiptScan
from app.services.kotak_struk import belajar
from app.services.kotak_struk.config import (
    LAYOUT_TTL, ORPHAN_FILE_AGE, ST_DILEWATI, ST_DIPROSES, ST_DITERIMA, ST_GAGAL, ST_KEDALUWARSA, ST_SIAP, ST_TERCATAT,
)

log = logging.getLogger(__name__)

ID_CHUNK = 1000  # id per SELECT ... IN (...): batas parameter asyncpg/SQLite ~32k


def _utc(dt: datetime) -> datetime:
    """Tanpa zona dianggap UTC (seperti worker)."""
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def expire_items(db: AsyncSession, *, now: datetime) -> int:
    """Satu UPDATE bersyarat: `siap`/`gagal` dengan `expires_at < now` -> `kedaluwarsa`, `ocr_lines` dan `layout` NULL.
    Status lain dan `expires_at` NULL tidak pernah disentuh. Commit sendiri; mengembalikan jumlah baris."""
    res = await db.execute(
        update(ReceiptScan)
        .where(ReceiptScan.status.in_((ST_SIAP, ST_GAGAL)), ReceiptScan.expires_at < _utc(now))
        .values(status=ST_KEDALUWARSA, ocr_lines=None, layout=null())
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return res.rowcount or 0


async def purge_layouts(db: AsyncSession, *, now: datetime) -> int:
    """Satu UPDATE: `layout` NULL untuk item `tercatat`/`dilewati`/`kedaluwarsa` yang masih punya kerangka dan dibaca
    lebih dari LAYOUT_TTL lalu (`processed_at < now - LAYOUT_TTL`, atau tanpa `processed_at`). Item terbuka/gagal tidak
    disentuh. Commit sendiri; mengembalikan jumlah baris."""
    res = await db.execute(
        update(ReceiptScan)
        .where(ReceiptScan.status.in_((ST_TERCATAT, ST_DILEWATI, ST_KEDALUWARSA)), ReceiptScan.layout.is_not(None),
               or_(ReceiptScan.processed_at.is_(None), ReceiptScan.processed_at < _utc(now) - LAYOUT_TTL))
        .values(layout=null())   # SQL NULL, bukan JSON 'null'
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return res.rowcount or 0


async def reconcile_proof_rules(db: AsyncSession) -> int:
    """`belajar.reconcile_rules` lalu commit; mengembalikan jumlah aturan yang dibuat/diperbaiki/dihapus."""
    n = await belajar.reconcile_rules(db)
    await db.commit()
    return n


def _old_candidates(kotak_dir: str, cutoff: datetime) -> list[tuple[uuid.UUID, str]]:
    """Berkas biasa langsung di `kotak_dir` (tanpa rekursi, symlink dilewati) yang namanya UUID dan mtime-nya
    lebih tua dari `cutoff`. Folder tidak ada -> kosong."""
    found: list[tuple[uuid.UUID, str]] = []
    try:
        entries = os.scandir(kotak_dir)
    except FileNotFoundError:
        return found
    with entries:
        for entry in entries:
            try:
                item_id = uuid.UUID(entry.name)
            except ValueError:
                continue  # bukan berkas intake (namanya str(item.id))
            if str(item_id) != entry.name:
                continue  # hanya bentuk kanonik (huruf kecil, bertanda hubung); md5/hex/{...} dibiarkan
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                mtime = datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, timezone.utc)
            except FileNotFoundError:
                continue  # hilang selagi didaftar
            except OSError as exc:
                log.warning("berkas Kotak %s tidak bisa diperiksa: %s", entry.name, exc)
                continue
            if mtime < cutoff:
                found.append((item_id, entry.path))
    return found


def _unlink_all(paths: list[str]) -> int:
    deleted = 0
    for path in paths:
        try:
            os.unlink(path)
        except FileNotFoundError:
            continue  # sudah dihapus pihak lain: bukan galat, tidak dihitung
        except OSError as exc:
            log.warning("berkas yatim Kotak %s gagal dihapus: %s", os.path.basename(path), exc)
            continue
        deleted += 1
    return deleted


async def delete_orphan_files(kotak_dir: str, db: AsyncSession, *, now: datetime) -> int:
    """Hapus berkas yatim di `kotak_dir`: lebih tua dari ORPHAN_FILE_AGE (`now - mtime`), nama berupa UUID kanonik,
    dan bukan berkas item berstatus `diterima`/`diproses` (SELECT per ID_CHUNK id). Berkas item status lain atau
    tanpa baris dihapus. Folder tidak ada -> 0 (tidak dibuat). Mengembalikan jumlah berkas yang dihapus."""
    candidates = await asyncio.to_thread(_old_candidates, kotak_dir, _utc(now) - ORPHAN_FILE_AGE)
    if not candidates:
        return 0
    ids = [item_id for item_id, _ in candidates]
    queued: set[uuid.UUID] = set()
    for start in range(0, len(ids), ID_CHUNK):
        queued.update((await db.execute(
            select(ReceiptScan.id)
            .where(ReceiptScan.id.in_(ids[start:start + ID_CHUNK]),
                   ReceiptScan.status.in_((ST_DITERIMA, ST_DIPROSES)))
        )).scalars())
    doomed = [path for item_id, path in candidates if item_id not in queued]
    return await asyncio.to_thread(_unlink_all, doomed) if doomed else 0
