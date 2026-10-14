"""Alur scan struk: kuota → OCR → parser (+ data belajar) → fallback LLM → simpan.

Juga memproses feedback (nilai akhir yang disimpan user) untuk belajar:
- Profil toko: label baris yang berisi total akhir (ReceiptTotalLabel).
- Alias nama toko salah-baca OCR (ReceiptMerchantAlias).
Teks OCR disimpan sementara hanya untuk proses belajar ini, lalu dihapus.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.models import ReceiptMerchantAlias, ReceiptScan, ReceiptTotalLabel, User
from app.services.receipt_parser import (
    CARD_KEYS, CASH_KEYS, CHANGE_KEYS, NOISE_LINE, NOT_TOTAL,
    _label_of, amounts_in, merchant_key, parse_receipt,
)

# Label baru dari koreksi baru dipakai parser setelah dikonfirmasi ≥ 2 kali,
# supaya satu koreksi keliru tidak merusak profil toko untuk semua user.
MIN_LABEL_HITS = 2


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


def _month_start() -> datetime:
    today = date.today()
    return datetime(today.year, today.month, 1, tzinfo=timezone.utc)


async def get_quota(user: User, db: AsyncSession) -> Quota:
    used = (await db.execute(
        select(func.count(ReceiptScan.id)).where(
            ReceiptScan.user_id == user.id,
            ReceiptScan.created_at >= _month_start(),
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

    quota = await get_quota(user, db)
    if quota.limit is not None and quota.used >= quota.limit:
        raise ScanQuotaExceeded(quota.limit)

    result = await ocr(image_bytes)
    aliases, profiles = await _load_learning(db)
    parsed = parse_receipt(result.lines, merchant_aliases=aliases, merchant_profiles=profiles)

    engine = "rapidocr"
    merchant, total, txn_date = parsed.merchant, parsed.total, parsed.date
    confidence, evidence = parsed.confidence, list(parsed.evidence)
    if confidence in ("rendah", "gagal"):
        fb = await llm(image_bytes, content_type, user.id, _plan(user))
        if fb and fb.get("total"):
            engine = "llm"
            total = fb["total"]
            merchant = fb.get("merchant") or merchant
            txn_date = fb.get("date") or txn_date
            confidence = "sedang"
            evidence.append("Dibaca ulang dengan AI cadangan")

    scan = ReceiptScan(
        user_id=user.id,
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
        "evidence": evidence,
        "engine": engine,
        "ocr_seconds": round(result.seconds, 2),
        "quota": quota.as_dict(),
    }


async def _bump_label(db: AsyncSession, mkey: str, label: str) -> None:
    row = await db.get(ReceiptTotalLabel, (mkey, label))
    if row:
        row.hits += 1
    else:
        db.add(ReceiptTotalLabel(merchant_key=mkey, label=label, hits=1))


async def _bump_alias(db: AsyncSession, raw_key: str, merchant: str) -> None:
    row = await db.get(ReceiptMerchantAlias, raw_key)
    if row:
        if row.merchant == merchant:
            row.hits += 1
        else:  # koreksi bertentangan → mulai ulang dengan nama baru
            row.merchant, row.hits = merchant, 1
    else:
        db.add(ReceiptMerchantAlias(raw_key=raw_key, merchant=merchant, hits=1))


def find_label_for_amount(lines: list[str], amount: int) -> str | None:
    """Label baris yang memuat `amount` dan layak jadi baris total.

    Baris pembayaran (tunai/kembali/non-tunai) dan baris pajak dilewati; dari
    sisanya diambil yang paling bawah, karena baris item ada di atas baris total.
    """
    for line in reversed(lines):
        if amount not in amounts_in(line):
            continue
        up = line.upper()
        if NOT_TOTAL.search(up) or CASH_KEYS.search(up) or CHANGE_KEYS.search(up) or CARD_KEYS.search(up) or NOISE_LINE.search(up):
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
    final_mkey = merchant_key(scan.final_merchant or scan.merchant)

    # Belajar label total untuk toko ini (hanya dari scan OCR, bukan hasil LLM).
    if final_mkey and total and lines and scan.engine == "rapidocr":
        label = scan.total_label if same_total else find_label_for_amount(lines, int(total))
        if label:
            await _bump_label(db, final_mkey, label)

    # Belajar alias nama toko yang salah-baca.
    if scan.merchant and scan.final_merchant and not same_merchant:
        raw_key = merchant_key(scan.merchant)
        if raw_key and raw_key != merchant_key(scan.final_merchant):
            await _bump_alias(db, raw_key, scan.final_merchant)

    scan.ocr_lines = None  # privasi: teks struk tidak disimpan setelah dipakai belajar
    await db.commit()
    return scan


async def accuracy_stats(db: AsyncSession, since: datetime | None = None) -> dict:
    """Untuk Admin: berapa scan yang diterima tanpa koreksi."""
    since = since or _month_start()
    rows = (await db.execute(
        select(ReceiptScan.outcome, ReceiptScan.engine, func.count(ReceiptScan.id))
        .where(ReceiptScan.created_at >= since)
        .group_by(ReceiptScan.outcome, ReceiptScan.engine)
    )).all()
    out = {"total": 0, "accepted": 0, "corrected": 0, "discarded": 0, "pending": 0, "llm": 0}
    for outcome, engine, n in rows:
        out["total"] += n
        out[outcome or "pending"] += n
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
