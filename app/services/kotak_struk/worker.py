"""Worker Kotak Struk: mengklaim item `diterima`, membaca isinya, menyimpan Dokumen Bayar, lalu
mengabari penunggu (spec 2026-10-26 bagian 1, 2a, 2d, 6a).

Di rilis 1 `run_worker` berjalan sebagai tugas asyncio di `lifespan` API; satu titik masuk ini
juga yang nanti dijalankan proses terpisah. Alur satu item (`process_item`): baca file ->
`extract_text` -> `read_document` -> isi kolom -> hapus file -> commit -> kabar selesai.
Koneksi DB tidak dipegang selama OCR/PDF/LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import or_, select, update

from app.models.models import ReceiptScan, User
from app.services import receipt_scan
from app.services.app_config import feature_enabled
from app.services.kotak_struk import belajar, waiter
from app.services.kotak_struk.config import (
    ITEM_EXPIRY, MAX_ATTEMPTS, PROOF_TYPES, STALE_PROCESSING, ST_DITERIMA, ST_DIPROSES, ST_GAGAL, ST_SIAP,
)
from app.services.kotak_struk.extract import ExtractError, TextDoc, extract_text
from app.services.kotak_struk.kerangka import build_layout
from app.services.kotak_struk.merchants import counterparty_key, hmac_hex, upsert_household_merchant
from app.services.kotak_struk.readers.base import ParseContext
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.registry import ReadResult, looks_like_proof, read_document
from app.services.receipt_llm import try_llm_fallback

log = logging.getLogger(__name__)

MSG_UNREADABLE = "Bukti tidak bisa dibaca. Coba kirim ulang."
STATUS_MISSING = "hilang"   # hasil `process_item` bila itemnya sudah tidak ada (mis. akun dihapus)
RECOVER_EVERY_S = 60
NOTIFY_TIMEOUT_S = 20       # kabar ke kanal (Telegram) tidak boleh menahan antrean
CLAIM_TRIES = 5             # kalah balapan klaim: coba item berikutnya
_WAITING = (ST_DITERIMA, ST_DIPROSES)
# Data struk belanja yang tidak punya tempat di DokumenBayar; A10 membangun ulang respons scan-receipt lama darinya.
RECEIPT_KEYS = ("item_discounts", "adjustments", "reconciliation", "confidence_source", "total_label")

_wake = asyncio.Event()


def wake() -> None:
    """Bangunkan loop worker (item baru masuk)."""
    _wake.set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _cut(value: str | None, size: int) -> str | None:
    return value[:size] if value else None


def _default_factory():
    from app.core.database import AsyncSessionLocal
    return AsyncSessionLocal


def _unlink(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:  # sudah tidak ada, atau pembersih file yatim yang akan menyapunya
            pass


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# --- klaim dan pemulihan ------------------------------------------------

async def claim_next(db, *, now: datetime | None = None) -> uuid.UUID | None:
    """Id item `diterima` tertua yang berhasil diklaim (`diproses`, `attempts + 1`), atau None.
    Klaim = UPDATE bersyarat `status='diterima'` dan cek rowcount, jadi dua worker tidak pernah
    memegang item yang sama (aman di Postgres dan SQLite)."""
    now = now or _utcnow()
    for _ in range(CLAIM_TRIES):
        item_id = (await db.execute(
            select(ReceiptScan.id).where(ReceiptScan.status == ST_DITERIMA)
            .order_by(ReceiptScan.created_at, ReceiptScan.id).limit(1)
        )).scalars().first()
        if item_id is None:
            await db.commit()  # akhiri transaksi baca
            return None
        res = await db.execute(
            update(ReceiptScan).where(ReceiptScan.id == item_id, ReceiptScan.status == ST_DITERIMA)
            .values(status=ST_DIPROSES, attempts=ReceiptScan.attempts + 1, processed_at=now)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if res.rowcount == 1:
            return item_id
    return None


async def recover_stale(db, *, now: datetime) -> int:
    """Item `diproses` yang lebih lama dari STALE_PROCESSING (API restart, worker mati): kembali ke
    `diterima` (file tetap ada), atau `gagal` bila percobaannya sudah MAX_ATTEMPTS. Mengembalikan
    jumlah item yang diubah."""
    now = _aware(now)
    stale = or_(ReceiptScan.processed_at.is_(None), ReceiptScan.processed_at < now - STALE_PROCESSING)
    rows = (await db.execute(
        select(ReceiptScan.id, ReceiptScan.attempts, ReceiptScan.file_path)
        .where(ReceiptScan.status == ST_DIPROSES, stale)
    )).all()
    changed, gave_up = 0, []
    for item_id, attempts, file_path in rows:
        giving_up = attempts >= MAX_ATTEMPTS
        values = ({"status": ST_GAGAL, "error": MSG_UNREADABLE, "file_path": None, "expires_at": now + ITEM_EXPIRY}
                  if giving_up else {"status": ST_DITERIMA})
        res = await db.execute(  # bersyarat: item yang baru saja selesai tidak ditimpa
            update(ReceiptScan).where(ReceiptScan.id == item_id, ReceiptScan.status == ST_DIPROSES, stale)
            .values(**values).execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            changed += 1
            if giving_up:
                gave_up.append((item_id, file_path))
    await db.commit()
    announce = [(item_id, file_path, await _channel_meta(db, item_id)) for item_id, file_path in gave_up]
    await db.commit()  # akhiri transaksi baca sebelum mengabari kanal
    for item_id, file_path, channel_meta in announce:
        _unlink(file_path)
        await _announce(item_id, ST_GAGAL, channel_meta)
    return changed


# --- kabar selesai ------------------------------------------------------

async def _channel_meta(db, item_id: uuid.UUID) -> dict | None:
    """`channel_meta` dibaca ulang SESUDAH commit status akhir: bot menyalakan `notify` dengan UPDATE bersyarat
    selama item masih `diterima`/`diproses`, bisa saja di antara pemuatan item di sini dan commit-nya. Nilai di objek
    yang dimuat sebelum commit bisa basi; yang dibaca sesudahnya tidak (UPDATE bot yang kalah balapan tidak mengenai
    baris yang sudah selesai, dan bot lalu merender hasilnya sendiri)."""
    return (await db.execute(select(ReceiptScan.channel_meta).where(ReceiptScan.id == item_id))).scalar_one_or_none()


async def _notify_channel(item_id: uuid.UUID) -> None:
    """Item yang dibaca lewat batas tunggu bot: kanal (Telegram) dikabari lewat hook bot
    `send_ready_message`. Galat apa pun (termasuk hook yang tidak bisa diimpor) hanya dicatat, item sudah
    tersimpan."""
    try:
        from app.bot.receipt_cmd import send_ready_message
        await asyncio.wait_for(send_ready_message(item_id), NOTIFY_TIMEOUT_S)
    except Exception:
        log.warning("kabar ke kanal untuk item Kotak Struk %s gagal", item_id, exc_info=True)


async def _announce(item_id: uuid.UUID, status: str, channel_meta: dict | None) -> None:
    await waiter.publish_done(item_id, status)
    if (channel_meta or {}).get("notify"):
        await _notify_channel(item_id)


# --- satu item ----------------------------------------------------------

class _Outcome(NamedTuple):
    columns: dict
    raw_name: str | None
    city: str | None
    # Teks bukti bayar yang dibaca pembaca struk/tak dikenali: tanpa teks OCR, rincian baris, nama, dan peta merchant.
    unread_proof: bool


def _plain_evidence(evidence: list[str]) -> list[str]:
    """Bukti (`evidence`) tanpa yang mengutip baris OCR ('Baris "..."', 'Non-tunai "..."') atau memuat angka: kutipan
    baris bukti bayar bisa memuat nomor rekening/HP utuh ('Non-tunai "Rekening Debit 0123 0100 1234 567"')."""
    return [e for e in evidence if '"' not in e and not any(c.isdigit() for c in e)]


def _layout(text: TextDoc, doc, secrets, user_name: str | None) -> dict | None:
    """Kerangka tata letak (kolom `layout`, belajar lintas user) dari baris OCR dan hasil baca SEBELUM disamarkan. Galat
    apa pun -> None + peringatan berisi jenis galatnya saja (pesannya bisa mengutip isi bukti); item tetap `siap`."""
    try:
        return build_layout(text.lines, doc, secrets, user_name=user_name)
    except Exception as exc:
        log.warning("kerangka tata letak Kotak Struk tidak dibuat (%s)", type(exc).__name__)
        return None


def _outcome(res: ReadResult, text: TextDoc, *, user_name: str | None = None) -> _Outcome:
    """Hasil baca -> nilai kolom `receipt_scans`. Nomor rekening, NMID, dan nomor referensi hanya
    masuk sebagai kunci/HMAC; Dokumen Bayar hanya memuat versi tersamarnya. `user_name` (nama user) hanya dipakai
    supaya kerangka tata letak tidak memuat namanya."""
    parsed = res.parsed
    doc, extra, secrets = parsed.doc, parsed.extra, parsed.secrets
    layout = _layout(text, doc, secrets, user_name)
    # Cabang berdasarkan jenis dokumen, bukan nama pembaca: penyelamatan LLM berpembaca
    # "tidak_dikenali" tetap struk belanja.
    store_receipt = doc.doc_type == "struk_belanja"
    # Dengan saklar `receipt_inbox` mati (bawaan produksi) bukti bayar dibaca pembaca struk belanja (atau jatuh ke
    # tidak dikenali). Teksnya tetap bukti bayar: memuat nomor rekening/referensi dan nama pihak ketiga, jadi
    # diperlakukan sebagai bukti. Bukti yang dibaca pembaca QRIS/transfer sendiri tidak masuk sini: tidak menyimpan
    # teks OCR dari awal, dan pihak penerimanya memang masuk peta merchant.
    unread_proof = doc.doc_type not in PROOF_TYPES and looks_like_proof(text)
    cp = doc.counterparty
    document = doc.to_json()
    if unread_proof:
        # Yang dibaca pembaca struk dari teks bukti bayar bukan rincian belanja: "barang"-nya potongan nomor rekening/HP
        # ("Rekening Tujuan 0123 0100", harga satuan 1234, nominal 567), "merchant"-nya judul status ("Transfer
        # Berhasil") atau baris pertama yang bisa memuat nomor HP, `evidence` mengutip baris utuh, dan data respons scan
        # lama (`receipt`) mengutip label baris. Yang disimpan hanya nominal, waktu, status, keyakinan, dan cek. Kunci
        # pihak dibentuk tanpa nama tebakan itu (teks yang dibaca pembaca struk tidak punya NMID/rekening: kuncinya None).
        cp = replace(cp, name=None)
        document["lines"] = []
        document["counterparty"]["name"] = None
        document["evidence"] = _plain_evidence(document["evidence"])
    elif store_receipt:
        document["receipt"] = {key: extra.get(key) for key in RECEIPT_KEYS}
    paid_at = doc.paid_at
    if paid_at is not None and paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=WIB)
    total = doc.amounts.total
    # Teks OCR, rincian baris, dan data belajar struk (nama, label total) hanya untuk struk belanja sungguhan (belajar
    # dari umpan balik); teks bukti bayar tidak disimpan.
    ocr_lines = extra.get("ocr_lines") if store_receipt and not unread_proof else None
    columns = {
        "doc_type": doc.doc_type,
        "document": document,
        "parser": res.reader[:40],
        "engine": extra.get("engine") or "rapidocr",
        "merchant": _cut(cp.name, 100),
        "merchant_key": None if unread_proof else _cut(extra.get("merchant_key"), 60),
        "parsed_total": Decimal(total) if total else None,
        "parsed_date": paid_at.astimezone(WIB).date() if paid_at else None,
        "confidence": doc.confidence.get("total") or "gagal",
        "total_label": None if unread_proof else _cut(extra.get("total_label"), 100),
        "ocr_lines": json.dumps(ocr_lines, ensure_ascii=False) if ocr_lines else None,
        "counterparty_key": counterparty_key(cp, nmid=secrets.nmid, account_number=secrets.account_number,
                                             bank_code=secrets.bank_code),
        "ref_hash": hmac_hex(secrets.ref_values[0]) if secrets.ref_values else None,
        "paid_at": paid_at,
        "pages": text.pages,
        "layout": layout,
    }
    return _Outcome(columns, cp.name, cp.city, unread_proof)


async def _store(factory, item_id: uuid.UUID, out: _Outcome, now: datetime) -> str:
    async with factory() as db:
        item = await db.get(ReceiptScan, item_id)
        if item is None:
            return STATUS_MISSING
        path = item.file_path
        siap = item.status in _WAITING
        if siap:  # selain itu user sudah melewati/menghapusnya selagi dibaca: hasilnya dibuang
            for column, value in out.columns.items():
                setattr(item, column, value)
            item.status, item.error = ST_SIAP, None
            item.processed_at, item.expires_at = now, now + ITEM_EXPIRY
            key = out.columns["counterparty_key"]
            # Nama yang dibaca dari teks bukti bayar (mis. "Transfer Berhasil") bukan merchant.
            if key and item.household_id and not out.unread_proof:
                try:  # peta merchant itu bonus: galatnya tidak boleh menggagalkan itemnya
                    async with db.begin_nested():
                        await upsert_household_merchant(db, item.household_id, key, out.raw_name, out.city, now=now)
                except Exception:
                    log.warning("peta merchant untuk item Kotak Struk %s tidak diperbarui", item_id, exc_info=True)
        item.file_path = None
        await db.commit()
        status = item.status
        channel_meta = await _channel_meta(db, item_id) if siap else None
    _unlink(path)
    if siap:
        await _announce(item_id, ST_SIAP, channel_meta)
    return status


async def _fail(factory, item_id: uuid.UUID, message: str, now: datetime) -> str:
    async with factory() as db:
        item = await db.get(ReceiptScan, item_id)
        if item is None:
            return STATUS_MISSING
        path = item.file_path
        failed = item.status in _WAITING
        if failed:
            item.status, item.error = ST_GAGAL, message[:200]
            item.processed_at, item.expires_at = now, now + ITEM_EXPIRY
        item.file_path = None
        await db.commit()
        status = item.status
        channel_meta = await _channel_meta(db, item_id) if failed else None
    _unlink(path)
    if failed:
        await _announce(item_id, ST_GAGAL, channel_meta)
    return status


async def _retry_or_fail(factory, item_id: uuid.UUID, now: datetime) -> str:
    async with factory() as db:
        item = await db.get(ReceiptScan, item_id)
        if item is None:
            return STATUS_MISSING
        if item.status not in _WAITING:
            return item.status
        if item.attempts < MAX_ATTEMPTS:
            item.status = ST_DITERIMA  # file tetap ada; klaim berikutnya mencoba lagi
            await db.commit()
            return ST_DITERIMA
    return await _fail(factory, item_id, MSG_UNREADABLE, now)


async def process_item(item_id: uuid.UUID, *, session_factory=None, extract=None, now: datetime | None = None,
                       proofs_enabled: bool | None = None) -> str:
    """Baca satu item sampai selesai; mengembalikan status akhirnya.

    `siap` (hasil tersimpan), `gagal` (bukti tidak bisa dibaca; pesan di `error`), `diterima` (galat tak
    terduga, akan dicoba lagi selama `attempts` < MAX_ATTEMPTS), status lama bila item bukan lagi
    `diterima`/`diproses` (tidak disentuh), atau "hilang" bila itemnya sudah tidak ada.
    `proofs_enabled=None`: ikuti saklar fitur `receipt_inbox` (web). Saklar menyala: aturan belajar yang disetujui
    (`belajar.approved_rules`, cache 5 menit, galat = tanpa aturan) dimuat di sesi yang sama ke `ParseContext.rules`."""
    factory = session_factory or _default_factory()
    extract = extract or extract_text
    now = _aware(now or _utcnow())

    async with factory() as db:  # sesi dilepas sebelum OCR/PDF/LLM
        item = await db.get(ReceiptScan, item_id)
        if item is None:
            log.warning("item Kotak Struk %s tidak ditemukan", item_id)
            return STATUS_MISSING
        if item.status not in _WAITING:
            return item.status
        file_path, content_type, user_id = item.file_path, item.content_type, item.user_id
        user = await db.get(User, user_id)
        aliases, profiles = await receipt_scan._load_learning(db)
        if proofs_enabled is None:
            proofs_enabled = await feature_enabled(db, "receipt_inbox", "web")
        # Aturan belajar yang disetujui (cache 5 menit; galat -> tanpa aturan). Saklar bukti mati = perilaku lama.
        rules = await belajar.approved_rules(db) if proofs_enabled else {}
    plan = str(getattr(user, "plan", None) or "basic")

    try:
        try:
            data = await asyncio.to_thread(_read_file, file_path) if file_path else None
        except OSError:
            data = None
        if data is None:  # berkas hilang (disapu, disk): mengulang tidak akan menolong
            log.warning("berkas item Kotak Struk %s tidak ada (%s)", item_id, file_path)
            return await _fail(factory, item_id, MSG_UNREADABLE, now)

        text = await extract(data, content_type)
        image = (content_type or "").startswith("image/")
        ctx = ParseContext(
            today=now.astimezone(WIB).date(),
            user_name=getattr(user, "name", None),
            merchant_aliases=aliases, merchant_profiles=profiles,
            image=data if image else None, content_type=content_type if image else None,
            user_id=user_id, plan=plan,
            llm=try_llm_fallback if image else None,
            rules=rules,
        )
        res = await read_document(text, ctx, proofs_enabled=proofs_enabled)
        return await _store(factory, item_id, _outcome(res, text, user_name=getattr(user, "name", None)), now)
    except ExtractError as exc:
        return await _fail(factory, item_id, exc.user_message, now)
    except Exception:
        log.exception("item Kotak Struk %s gagal diproses", item_id)
        return await _retry_or_fail(factory, item_id, now)


# --- loop ---------------------------------------------------------------

async def _sleep(stop: asyncio.Event, timeout: float, wake_event: asyncio.Event | None = None) -> None:
    """Tidur sampai `timeout`, `stop` menyala, atau `wake_event` menyala (yang lebih dulu)."""
    tasks = [asyncio.ensure_future(stop.wait())]
    if wake_event is not None:
        tasks.append(asyncio.ensure_future(wake_event.wait()))
    try:
        await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_worker(stop: asyncio.Event, *, session_factory=None, poll_s: float = 2.0) -> None:
    """Loop worker sampai `stop` menyala: pulihkan item macet saat menyala dan tiap menit, klaim lalu
    proses item `diterima`; tanpa item, tunggu `wake()` atau `poll_s`. Galat satu putaran dicatat dan
    loop lanjut."""
    global _wake
    _wake = wake_event = asyncio.Event()  # terikat ke loop yang menjalankan worker
    factory = session_factory or _default_factory()
    last_recover = None
    log.info("worker Kotak Struk berjalan")
    while not stop.is_set():
        try:
            wake_event.clear()  # sebelum klaim: wake() yang datang sesudahnya tidak hilang
            if last_recover is None or time.monotonic() - last_recover >= RECOVER_EVERY_S:
                last_recover = time.monotonic()
                try:
                    async with factory() as db:
                        recovered = await recover_stale(db, now=_utcnow())
                    if recovered:
                        log.info("worker Kotak Struk memulihkan %d item macet", recovered)
                except Exception:
                    log.exception("pemulihan item Kotak Struk macet gagal")
            async with factory() as db:
                item_id = await claim_next(db)
            if item_id is None:
                await _sleep(stop, poll_s, wake_event)
                continue
            if await process_item(item_id, session_factory=factory) == ST_DITERIMA:
                await _sleep(stop, poll_s)  # akan dicoba lagi: beri jeda, jangan memutar ulang
        except Exception:
            log.exception("putaran worker Kotak Struk gagal")
            await _sleep(stop, poll_s)
    log.info("worker Kotak Struk berhenti")
