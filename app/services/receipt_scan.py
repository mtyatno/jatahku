"""Scan struk untuk web: foto/PDF masuk Kotak Struk lewat intake, dibaca worker (OCR → parser + data belajar →
fallback LLM), lalu hasilnya dikembalikan dalam bentuk respons `scan-receipt` yang lama (lihat docs/kotak-struk.md).
Tidak ada kuota scan lagi.

Juga memproses feedback (nilai akhir yang disimpan user) untuk belajar:
- Profil toko: label baris yang berisi total akhir (ReceiptTotalLabel).
- Alias nama toko salah-baca OCR (ReceiptMerchantAlias).
Teks OCR disimpan sementara hanya untuk proses belajar ini, lalu dihapus.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.models import (
    ProofRule, ReceiptLearnVote, ReceiptMerchantAlias, ReceiptScan, ReceiptTotalLabel, Transaction, User,
)
from app.services.kotak_struk.config import ST_TERCATAT
from app.services.receipt_ocr import OcrBusy, OcrFailed
from app.services.receipt_parser import (
    CARD_KEYS, CASH_KEYS, CHANGE_KEYS, MASKED, NOISE_LINE, NOT_TOTAL,
    ReceiptAdjustment, ReceiptItem, Reconciliation,
    _label_of, amounts_in, merchant_key, payment_amounts,
)

logger = logging.getLogger("jatahku.receipt")

# Data belajar baru dipakai parser setelah disetujui ≥ 2 user BERBEDA,
# supaya satu user (atau satu koreksi keliru) tidak merusak hasil user lain.
MIN_LABEL_HITS = 2
# Teks OCR scan yang tidak pernah diberi feedback dihapus setelah ini.
OCR_TEXT_RETENTION = timedelta(hours=24)


class ScanQuotaExceeded(Exception):
    """Tidak dilempar lagi sejak Kotak Struk (kuota scan dihapus). Dipertahankan untuk kompatibilitas impor."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Kuota {limit} scan/bulan habis")


class ScanBusy(OcrBusy):
    """Item belum selesai dibaca setelah batas tunggu (antrean ramai). Item tetap diproses dan muncul di Kotak Struk.
    Turunan `OcrBusy` supaya penangan lama (bot, rute) tetap memperlakukannya sebagai "sedang ramai"."""


@dataclass
class Quota:
    limit: int | None  # None = tanpa batas
    used: int

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    def as_dict(self) -> dict:
        return {"limit": self.limit, "used": self.used, "remaining": self.remaining}


def _month_start(tz_name: str | None = None) -> datetime:
    """Awal bulan berjalan di zona waktu user (default Asia/Jakarta)."""
    try:
        tz = ZoneInfo(tz_name or get_settings().TZ)
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)
    return datetime(now.year, now.month, 1, tzinfo=tz)


async def get_quota(user: User, db: AsyncSession) -> Quota:
    """Kuota scan sudah dihapus (semua paket, tanpa saklar): `limit` selalu None. `used` (scan bulan ini yang
    totalnya terbaca) tetap dihitung untuk klien lama yang menampilkannya."""
    used = (await db.execute(
        select(func.count(ReceiptScan.id)).where(
            ReceiptScan.user_id == user.id,
            ReceiptScan.created_at >= _month_start(getattr(user, "timezone", None)),
            ReceiptScan.confidence != "gagal",
        )
    )).scalar() or 0
    return Quota(limit=None, used=int(used))


async def _load_learning(db: AsyncSession) -> tuple[dict[str, str], dict[str, list[str]]]:
    aliases = {
        row.raw_key: row.merchant
        for row in (await db.execute(select(ReceiptMerchantAlias).where(ReceiptMerchantAlias.hits >= MIN_LABEL_HITS))).scalars().all()
    }
    profiles: dict[str, list[str]] = {}
    rows = await db.execute(
        select(ReceiptTotalLabel).where(ReceiptTotalLabel.hits >= MIN_LABEL_HITS).order_by(ReceiptTotalLabel.hits.desc())
    )
    for row in rows.scalars().all():
        profiles.setdefault(row.merchant_key, []).append(row.label)
    return aliases, profiles


async def scan_receipt(user: User, data: bytes, content_type: str, db: AsyncSession, *, waiter=None) -> dict:
    """Scan satu foto/PDF lewat Kotak Struk dan tunggu hasilnya (maks `WAIT_FORM_S`): intake `web_form` → worker →
    respons bentuk lama + field baru (`document.scan_receipt_response`). `waiter(item_id, timeout_s)` bisa diganti di
    test. `ScanBusy`: belum selesai (item tetap diproses). `OcrFailed(pesan)`: item `gagal`. `IntakeRejected`: ditolak
    intake (jenis/ukuran/batas); pemanggil memetakannya ke HTTP.

    Koneksi DB dilepas selama menunggu (bisa puluhan detik): penunggu memakai sesinya sendiri."""
    from app.services.kotak_struk.config import ST_DIPROSES, ST_DITERIMA, ST_GAGAL, WAIT_FORM_S
    from app.services.kotak_struk.document import scan_receipt_response
    from app.services.kotak_struk.intake import IntakeRequest, create_item
    from app.services.kotak_struk.view import item_detail
    from app.services.kotak_struk.waiter import wait_for_item

    waiter = waiter or wait_for_item
    item, _ = await create_item(db, IntakeRequest(user, "web_form", data=data, content_type=content_type))
    # PENTING: commit, BUKAN rollback: rollback meng-expire `user` milik pemanggil (MissingGreenlet di AsyncSession).
    # `create_item` hanya commit untuk item baru; item yang sudah ada dikembalikan dengan transaksi baca masih terbuka.
    await db.commit()
    done = await waiter(item.id, WAIT_FORM_S)
    if done is None or done.status in (ST_DITERIMA, ST_DIPROSES):  # None: item hilang selagi ditunggu
        raise ScanBusy("scan struk masih diproses")
    if done.status == ST_GAGAL:
        raise OcrFailed(done.error or "Bukti tidak bisa dibaca")
    return scan_receipt_response(done, await item_detail(db, done, user))


def items_payload(items: list[ReceiptItem], adjustments: list[ReceiptAdjustment],
                  rec: Reconciliation | None) -> dict:
    """Rincian barang untuk klien (web & bot)."""
    return {
        "items": [
            {
                "name": it.name,
                "qty": it.qty,
                "unit_price": it.unit_price,
                "amount": it.amount,
                "discount": it.discount,
                "flag": it.flag,
                "note": it.note,
                "suggestion": it.suggestion,
            }
            for it in items
        ],
        "adjustments": [{"label": a.label, "amount": a.amount, "kind": a.kind} for a in adjustments],
        "reconciliation": None if rec is None else {
            "items_total": rec.items_total,
            "discounts": rec.discounts,
            "charges": rec.charges,
            "expected": rec.expected,
            "diff": rec.diff,
            "status": rec.status,
            "note": rec.note,
        },
    }


async def _vote(db: AsyncSession, kind: str, key: str, value: str, user_id) -> int:
    """Catat suara user (sekali per user) dan kembalikan jumlah user berbeda."""
    await db.execute(
        pg_insert(ReceiptLearnVote)
        .values(kind=kind, key=key, value=value, user_id=user_id)
        .on_conflict_do_nothing()
    )
    return int((await db.execute(
        select(func.count()).select_from(ReceiptLearnVote).where(
            ReceiptLearnVote.kind == kind, ReceiptLearnVote.key == key, ReceiptLearnVote.value == value,
        )
    )).scalar() or 0)


async def _learn_label(db: AsyncSession, mkey: str, label: str, user_id) -> None:
    users = await _vote(db, "label", mkey, label, user_id)
    await db.execute(
        pg_insert(ReceiptTotalLabel)
        .values(merchant_key=mkey, label=label, hits=users)
        .on_conflict_do_update(index_elements=["merchant_key", "label"], set_={"hits": users})
    )


async def _learn_alias(db: AsyncSession, raw_key: str, merchant: str, user_id) -> None:
    users = await _vote(db, "alias", raw_key, merchant, user_id)
    # Nama dengan dukungan user terbanyak yang menang untuk alias ini.
    await db.execute(
        pg_insert(ReceiptMerchantAlias)
        .values(raw_key=raw_key, merchant=merchant, hits=users)
        .on_conflict_do_update(
            index_elements=["raw_key"],
            set_={"merchant": merchant, "hits": users},
            where=ReceiptMerchantAlias.hits <= users,
        )
    )


def clean_merchant_name(name: str | None) -> str | None:
    """Nama toko dari input user → aman ditampilkan ke user lain."""
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9&'.\- ]", "", name)).strip()[:40]
    return cleaned if len(cleaned) >= 2 else None


def find_label_for_amount(lines: list[str], amount: int) -> str | None:
    """Label baris yang memuat `amount` dan layak jadi baris total.

    Baris pembayaran (tunai/kembali/non-tunai) dan baris pajak dilewati; dari
    sisanya diambil yang paling bawah, karena baris item ada di atas baris total.
    """
    for line in reversed(lines):
        if amount not in amounts_in(line):
            continue
        up = line.upper()
        if (NOT_TOTAL.search(up) or CASH_KEYS.search(up) or CHANGE_KEYS.search(up)
                or CARD_KEYS.search(up) or NOISE_LINE.search(up) or MASKED.search(up)):
            continue
        label = _label_of(line)
        if label and len(label) >= 3:
            return label[:100]
    return None


async def apply_feedback(
    user: User, scan_id, db: AsyncSession, *,
    saved: bool, total: int | None = None, txn_date: date | None = None, merchant: str | None = None,
    wrong: bool = False,
) -> ReceiptScan | None:
    """Catat nilai akhir yang disimpan user, lalu belajar dari selisihnya.

    saved=False + wrong=True: user bilang hasilnya salah tapi tidak memberi nilai
    benar (mis. tombol "Nominal salah" di bot) → dihitung sebagai koreksi.
    """
    try:
        scan_id = uuid.UUID(str(scan_id))
    except ValueError:
        return None
    scan = await db.get(ReceiptScan, scan_id)
    if not scan or scan.user_id != user.id or scan.outcome is not None:
        return None

    scan.feedback_at = datetime.now(timezone.utc)
    if not saved:
        scan.outcome = "corrected" if wrong else "discarded"
        scan.ocr_lines = None
        await db.commit()
        return scan

    scan.final_total = Decimal(total) if total else None
    scan.final_date = txn_date
    scan.final_merchant = (merchant or "").strip()[:100] or None
    same_total = scan.parsed_total is not None and total is not None and int(scan.parsed_total) == int(total)
    same_merchant = not scan.final_merchant or (scan.merchant or "").lower() == scan.final_merchant.lower()
    scan.outcome = "accepted" if (same_total and same_merchant) else "corrected"

    lines = json.loads(scan.ocr_lines) if scan.ocr_lines else []
    clean_name = clean_merchant_name(scan.final_merchant)
    final_mkey = merchant_key(clean_name or scan.merchant)

    try:
        # SAVEPOINT: kalau proses belajar gagal (mis. bentrok tulis bersamaan),
        # hanya bagian ini yang dibatalkan; outcome scan tetap tersimpan.
        async with db.begin_nested():
            # Label total: hanya dari scan OCR, dan hanya jika nilainya terbukti
            # oleh pembayaran di struk itu sendiri (tunai−kembali / non-tunai).
            # Mencatat sebagian item saja (total ≠ pembayaran) tidak dipelajari.
            # "tinggi" bisa juga berasal dari rincian barang (bukan pembayaran),
            # jadi syarat pembayaran berlaku di kedua cabang.
            if final_mkey and total and lines and scan.engine == "rapidocr" \
                    and int(total) in payment_amounts(lines):
                # Selalu dari baris yang memuat nominal yang dibayar (bukan label
                # baris yang dipakai parser, yang bisa SUBTOTAL sebelum pajak).
                label = find_label_for_amount(lines, int(total))
            else:
                label = None
            if final_mkey and label:
                await _learn_label(db, final_mkey, label, user.id)

            # Alias nama toko yang salah-baca.
            if scan.merchant and clean_name and not same_merchant:
                raw_key = merchant_key(scan.merchant)
                if raw_key and raw_key != merchant_key(clean_name):
                    await _learn_alias(db, raw_key, clean_name, user.id)
    except Exception as exc:  # belajar itu bonus; jangan gagalkan feedback
        logger.warning("belajar dari struk gagal: %s", exc)

    scan.ocr_lines = None  # privasi: teks struk tidak disimpan setelah dipakai belajar
    await db.commit()
    return scan


async def purge_stale_ocr_text(db: AsyncSession) -> int:
    """Hapus teks OCR dari scan yang tidak pernah diberi feedback (tab ditutup,
    tombol bot diabaikan, tersimpan offline). Dijalankan scheduler tiap jam."""
    cutoff = datetime.now(timezone.utc) - OCR_TEXT_RETENTION
    res = await db.execute(
        update(ReceiptScan)
        .where(ReceiptScan.ocr_lines.isnot(None), ReceiptScan.created_at < cutoff)
        .values(ocr_lines=None, outcome=func.coalesce(ReceiptScan.outcome, "expired"))
    )
    await db.commit()
    return res.rowcount or 0


async def accuracy_stats(db: AsyncSession, since: datetime | None = None) -> dict:
    """Untuk Admin: berapa scan yang diterima tanpa koreksi. Ditambah rincian Kotak Struk (`by_doc_type`,
    `by_issuer`, `unrecognized`) dan `rules_pending` (aturan belajar yang menunggu keputusan pemilik, semua waktu;
    lencana "Aturan belajar", pre-flight G10); kunci lama dan cara hitungnya tidak berubah."""
    since = since or _month_start()  # zona waktu default app
    rows = (await db.execute(
        select(ReceiptScan.outcome, ReceiptScan.engine, func.count(ReceiptScan.id))
        .where(ReceiptScan.created_at >= since)
        .group_by(ReceiptScan.outcome, ReceiptScan.engine)
    )).all()
    out = {"total": 0, "accepted": 0, "corrected": 0, "discarded": 0, "expired": 0, "pending": 0, "llm": 0}
    for outcome, engine, n in rows:
        out["total"] += n
        out[outcome or "pending"] = out.get(outcome or "pending", 0) + n
        if engine == "llm":
            out["llm"] += n
    judged = out["accepted"] + out["corrected"]
    out["accuracy_pct"] = round(100 * out["accepted"] / judged, 1) if judged else None
    worst = (await db.execute(
        select(ReceiptScan.merchant_key, func.count(ReceiptScan.id))
        .where(ReceiptScan.created_at >= since, ReceiptScan.outcome == "corrected")
        .group_by(ReceiptScan.merchant_key).order_by(func.count(ReceiptScan.id).desc()).limit(5)
    )).all()
    out["most_corrected"] = [{"merchant_key": k or "(tidak dikenal)", "count": n} for k, n in worst]
    out.update(await _kotak_breakdown(db, since))
    from app.services.kotak_struk.belajar import ST_MENUNGGU
    out["rules_pending"] = (await db.execute(
        select(func.count(ProofRule.id)).where(ProofRule.status == ST_MENUNGGU)
    )).scalar_one()
    return out


# Tanggal transaksi bukti bayar = tanggal bayar di WIB (seperti `parsed_date` worker Kotak Struk).
_WIB = timezone(timedelta(hours=7), "WIB")
ID_CHUNK = 1000  # id transaksi per SELECT ... IN (...): batas parameter asyncpg/SQLite ~32k


def _txn_ids(raw) -> list[uuid.UUID]:
    """Semua id sah di `transaction_ids`, urutan tetap; yang bukan UUID dilewati."""
    ids = []
    for value in raw if isinstance(raw, list) else []:
        try:
            ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return ids


def _proof_corrected(parsed_total, paid_at: datetime | None, txn) -> bool:
    """Bukti bayar tercatat dikoreksi user: nominal tidak terbaca, nominal transaksi beda, atau tanggal transaksi
    bukan tanggal bayar (WIB). Tanpa transaksi yang masih ada, hanya nominal kosong yang terlihat."""
    if parsed_total is None:
        return True
    if txn is None:
        return False
    amount, txn_date = txn
    if Decimal(amount) != Decimal(parsed_total):
        return True
    if paid_at is not None:
        paid_at = paid_at if paid_at.tzinfo is not None else paid_at.replace(tzinfo=timezone.utc)
        return txn_date != paid_at.astimezone(_WIB).date()
    return False


async def _kotak_breakdown(db: AsyncSession, since: datetime) -> dict:
    """Rincian Kotak Struk untuk Admin (spec §7d butir 4), dihitung di Python dari item periode ini (baris lama tanpa
    status tidak ikut): jumlah per `doc_type`, jumlah `tidak_dikenali`, dan per `issuer` (`document->>'issuer'`)
    total/tercatat/dikoreksi. Dikoreksi: struk belanja = outcome `corrected`; jenis lain = item tercatat yang
    transaksinya (id pertama di `transaction_ids` yang masih ada) berbeda nominal/tanggal dari hasil baca. Transaksi
    dibaca per ID_CHUNK id."""
    rows = (await db.execute(
        select(ReceiptScan.doc_type, ReceiptScan.status, ReceiptScan.outcome,
               ReceiptScan.document["issuer"].as_string(), ReceiptScan.parsed_total, ReceiptScan.paid_at,
               ReceiptScan.transaction_ids)
        .where(ReceiptScan.created_at >= since, ReceiptScan.status.is_not(None))
    )).all()

    by_doc_type: dict[str, int] = {}
    unrecognized = 0
    issued = []
    for doc_type, status, outcome, issuer, parsed_total, paid_at, txn_ids in rows:
        if doc_type:
            by_doc_type[doc_type] = by_doc_type.get(doc_type, 0) + 1
        if doc_type == "tidak_dikenali":
            unrecognized += 1
        if issuer:
            ids = _txn_ids(txn_ids) if status == ST_TERCATAT and doc_type != "struk_belanja" else []
            issued.append((str(issuer), doc_type, status, outcome, parsed_total, paid_at, ids))

    wanted = list({i for *_, ids in issued for i in ids})
    txns = {}
    for start in range(0, len(wanted), ID_CHUNK):
        txns.update({tid: (amount, txn_date) for tid, amount, txn_date in (await db.execute(
            select(Transaction.id, Transaction.amount, Transaction.transaction_date)
            .where(Transaction.id.in_(wanted[start:start + ID_CHUNK]))
        )).all()})

    by_issuer: dict[str, dict] = {}
    for issuer, doc_type, status, outcome, parsed_total, paid_at, ids in issued:
        entry = by_issuer.setdefault(issuer, {"total": 0, "recorded": 0, "corrected": 0})
        entry["total"] += 1
        recorded = status == ST_TERCATAT
        entry["recorded"] += int(recorded)
        if doc_type == "struk_belanja":
            entry["corrected"] += int(outcome == "corrected")
        elif recorded:
            txn = next((txns[i] for i in ids if i in txns), None)
            entry["corrected"] += int(_proof_corrected(parsed_total, paid_at, txn))
    return {"by_doc_type": by_doc_type, "by_issuer": by_issuer, "unrecognized": unrecognized}
