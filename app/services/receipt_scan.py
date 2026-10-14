"""Alur scan struk: kuota → OCR → parser (+ data belajar) → fallback LLM → simpan.

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
    ReceiptLearnVote, ReceiptMerchantAlias, ReceiptScan, ReceiptTotalLabel, User,
)
from app.services.receipt_parser import (
    CARD_KEYS, CASH_KEYS, CHANGE_KEYS, MASKED, NOISE_LINE, NOT_TOTAL,
    ReceiptAdjustment, ReceiptItem, Reconciliation,
    _label_of, amounts_in, merchant_key, parse_receipt, payment_amounts, reconcile,
)

logger = logging.getLogger("jatahku.receipt")

# Data belajar baru dipakai parser setelah disetujui ≥ 2 user BERBEDA,
# supaya satu user (atau satu koreksi keliru) tidak merusak hasil user lain.
MIN_LABEL_HITS = 2
# Teks OCR scan yang tidak pernah diberi feedback dihapus setelah ini.
OCR_TEXT_RETENTION = timedelta(hours=24)


class ScanQuotaExceeded(Exception):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Kuota {limit} scan/bulan habis")


@dataclass
class Quota:
    limit: int | None  # None = tanpa batas
    used: int

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    def as_dict(self) -> dict:
        return {"limit": self.limit, "used": self.used, "remaining": self.remaining}


def _plan(user: User) -> str:
    return str(getattr(user, "plan", "basic") or "basic")


def _month_start(tz_name: str | None = None) -> datetime:
    """Awal bulan berjalan di zona waktu user (default Asia/Jakarta)."""
    try:
        tz = ZoneInfo(tz_name or get_settings().TZ)
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)
    return datetime(now.year, now.month, 1, tzinfo=tz)


async def get_quota(user: User, db: AsyncSession) -> Quota:
    # Scan yang totalnya sama sekali tidak terbaca tidak memotong kuota.
    used = (await db.execute(
        select(func.count(ReceiptScan.id)).where(
            ReceiptScan.user_id == user.id,
            ReceiptScan.created_at >= _month_start(getattr(user, "timezone", None)),
            ReceiptScan.confidence != "gagal",
        )
    )).scalar() or 0
    limit = None if _plan(user) == "pro" else get_settings().RECEIPT_SCAN_LIMIT_BASIC
    return Quota(limit=limit, used=int(used))


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


async def scan_receipt(user: User, image_bytes: bytes, content_type: str, db: AsyncSession, *, ocr=None, llm=None) -> dict:
    """Jalankan scan. `ocr`/`llm` bisa diganti di test."""
    from app.services.receipt_ocr import read_receipt_lines
    from app.services.receipt_llm import try_llm_fallback

    ocr = ocr or read_receipt_lines
    llm = llm or try_llm_fallback

    user_id, plan = user.id, _plan(user)
    quota = await get_quota(user, db)
    if quota.limit is not None and quota.used >= quota.limit:
        raise ScanQuotaExceeded(quota.limit)
    # Lepas koneksi DB selama menunggu/menjalankan OCR (bisa beberapa detik),
    # supaya antrean scan tidak menghabiskan pool koneksi API & bot.
    # PENTING: commit, BUKAN rollback. Rollback meng-expire semua objek di sesi
    # (termasuk `user` milik pemanggil); akses atributnya sesudah itu memicu
    # lazy-load → MissingGreenlet di AsyncSession. Commit dengan
    # expire_on_commit=False melepas koneksi tanpa meng-expire objek.
    await db.commit()

    result = await ocr(image_bytes, owner=user_id)
    aliases, profiles = await _load_learning(db)
    parsed = parse_receipt(result.lines, merchant_aliases=aliases, merchant_profiles=profiles)

    engine = "rapidocr"
    merchant, total, txn_date = parsed.merchant, parsed.total, parsed.date
    confidence, evidence = parsed.confidence, list(parsed.evidence)
    items, adjustments, rec = parsed.items, parsed.adjustments, parsed.reconciliation
    confidence_source = parsed.confidence_source
    if confidence in ("rendah", "gagal"):
        try:
            fb = await llm(image_bytes, content_type, user_id, plan)
        except Exception as exc:  # fallback opsional; hasil OCR tetap dipakai
            logger.warning("fallback LLM gagal: %s", exc)
            fb = None
        if fb and fb.get("total"):
            engine = "llm"
            total = fb["total"]
            merchant = fb.get("merchant") or merchant
            txn_date = fb.get("date") or txn_date
            confidence, confidence_source = "sedang", "llm"
            evidence.append("Dibaca ulang dengan AI cadangan")
            # Rincian OCR dicocokkan ulang ke total versi AI (tanpa tanda lama).
            for it in items:
                if it.flag == "cek":
                    it.flag, it.note, it.suggestion = "ok", None, None
            rec = reconcile(items, adjustments, total)

    scan = ReceiptScan(
        user_id=user_id,
        engine=engine,
        merchant=merchant,
        merchant_key=merchant_key(merchant),
        parsed_total=Decimal(total) if total else None,
        parsed_date=txn_date,
        confidence=confidence,
        total_label=parsed.total_label,
        ocr_lines=json.dumps(parsed.lines, ensure_ascii=False) if parsed.lines else None,
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    quota.used += 1
    return {
        "scan_id": str(scan.id),
        "merchant": merchant,
        "date": txn_date.isoformat() if txn_date else None,
        "total": total,
        "confidence": confidence,
        "confidence_source": confidence_source,
        "evidence": evidence,
        "engine": engine,
        "ocr_seconds": round(result.seconds, 2),
        "quota": quota.as_dict(),
        **items_payload(items, adjustments, rec),
    }


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
                label = scan.total_label if (same_total and scan.total_label) \
                    else find_label_for_amount(lines, int(total))
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
    """Untuk Admin: berapa scan yang diterima tanpa koreksi."""
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
    return out
