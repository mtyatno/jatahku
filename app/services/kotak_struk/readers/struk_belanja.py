"""Pembaca struk belanja: membungkus `parse_receipt` (beserta data belajarnya) dan fallback
LLM `receipt_llm` apa adanya. Logikanya sama dengan `receipt_scan.scan_receipt` lama."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar, Line
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.readers.proof_common import is_app_receipt, read_body_failure_title, read_header_status
from app.services.receipt_parser import (
    NOT_TOTAL, TOTAL_INCL_TAX, ReceiptParse, amounts_in, merchant_key, normalize_line, parse_receipt, reconcile,
)

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc

logger = logging.getLogger(__name__)

ENGINE_OCR = "rapidocr"
ENGINE_LLM = "llm"
LLM_EVIDENCE = "Dibaca ulang dengan AI cadangan"

# Baris label total yang kuat: TOTAL, GRAND TOTAL, TOTAL BELANJA, TOTAL BAYAR (semuanya memuat kata TOTAL).
# Bukan SUBTOTAL, TOTAL ITEM/QTY/DISKON/PPN, dan sejenisnya.
_TOTAL_WORD = re.compile(r"(?<![A-Z])TOTAL(?![A-Z])")
_SUBTOTAL = re.compile(r"SUB\s*-?\s*TOTAL")


def _is_strong_total(up: str) -> bool:
    if not _TOTAL_WORD.search(up) or _SUBTOTAL.search(up):
        return False
    return bool(TOTAL_INCL_TAX.search(up)) or not NOT_TOTAL.search(up)


def _is_item_like(line: str, up: str) -> bool:
    """Baris barang/angka: ada nama (>= 3 huruf, "Rp" tidak dihitung) dan ada nominal."""
    name = re.sub(r"\bRP\b", " ", up)
    return sum(c.isalpha() for c in name) >= 3 and bool(amounts_in(line))


async def llm_fallback(ctx: ParseContext) -> dict | None:
    """Baca ulang foto dengan LLM cadangan (`ctx.llm`), seperti `scan_receipt` lama.

    Hanya bila `ctx.llm` dan gambar aslinya ada. Galat apa pun, atau jawaban tanpa total,
    menghasilkan None (hasil OCR dipakai). Dipakai bersama oleh pembaca struk belanja dan
    pembaca tidak dikenali.
    """
    if ctx.llm is None or not ctx.image:
        return None
    try:
        fb = await ctx.llm(ctx.image, ctx.content_type, ctx.user_id, ctx.plan)
    except Exception as exc:  # fallback opsional; hasil OCR tetap dipakai
        logger.warning("fallback LLM gagal: %s", exc)
        return None
    return fb if fb and fb.get("total") else None


def apply_header_status(doc: DokumenBayar, lines: list[str]) -> None:
    """Status bawaan dokumen dibiarkan; hanya judul yang bisa mengubahnya ke `gagal`/`pending`: judul bukti (4 baris pertama,
    `read_header_status`), lalu judul status gagal/pending di badan (`read_body_failure_title`, mis. "Transaksi Gagal" di
    bawah rincian), supaya bukti transfer/QRIS yang gagal dan salah rute (ke struk belanja atau pembaca tidak dikenali)
    tetap diblokir oleh cek status (checks.common_checks). Kalimat biasa, bantuan, ajakan, dan tanya di badan dan kaki
    tidak dihitung."""
    header = read_header_status(lines)
    if header in ("gagal", "pending"):
        doc.status = header
        doc.evidence.append(f"Judul bukti menyebut status {header}")
        return
    body = read_body_failure_title(lines)
    if body is not None:
        doc.status = body
        doc.evidence.append(f"Bukti menyebut status {body}")


def _midnight_wib(d: date | None) -> datetime | None:
    return datetime(d.year, d.month, d.day, tzinfo=WIB) if d else None


def parsed_from_receipt(rp: ReceiptParse, fb: dict | None = None) -> Parsed:
    """Hasil `parse_receipt` (+ jawaban LLM `fb` bila ada) -> Dokumen Bayar struk belanja."""
    merchant, total, txn_date = rp.merchant, rp.total, rp.date
    confidence, source = rp.confidence, rp.confidence_source
    evidence = list(rp.evidence)
    items, adjustments, rec = rp.items, rp.adjustments, rp.reconciliation
    engine = ENGINE_OCR
    if fb:
        engine = ENGINE_LLM
        total = fb["total"]
        merchant = fb.get("merchant") or merchant
        txn_date = fb.get("date") or txn_date
        confidence, source = "sedang", "llm"
        evidence.append(LLM_EVIDENCE)
        # Rincian OCR dicocokkan ulang ke total versi AI (tanpa tanda lama).
        for it in items:
            if it.flag == "cek":
                it.flag, it.note, it.suggestion = "ok", None, None
        rec = reconcile(items, adjustments, total)

    lines = [
        Line(kind="item", name=it.name, amount=it.amount, qty=it.qty, unit_price=it.unit_price,
             flag=it.flag, note=it.note, suggestion=it.suggestion)
        for it in items
    ]
    lines += [
        Line(kind="discount" if a.kind == "discount" else "tax", name=a.label, amount=a.amount)
        for a in adjustments
    ]
    doc = DokumenBayar(
        doc_type="struk_belanja",
        status="berhasil",
        flow="keluar",
        method="lainnya",
        paid_at=_midnight_wib(txn_date),
        counterparty=Counterparty(name=merchant),
        amounts=Amounts(total=total),
        lines=lines,
        confidence={"total": confidence},
        evidence=evidence,
    )
    extra = {
        "total_label": rp.total_label,
        "merchant_key": merchant_key(merchant),
        "confidence_source": source,
        "engine": engine,
        # Bentuk JSON yang sama dengan `receipt_scan.items_payload`.
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
        # Voucher yang menempel di barang tidak punya tempat di `Line`; sejajar dengan baris `item`.
        "item_discounts": [it.discount for it in items],
        # Baris OCR yang sudah dinormalkan `parse_receipt` (= kolom `ocr_lines` scan lama); pembelajaran
        # umpan balik memakainya. Jalur penyelamatan UnknownReader tidak menjalankan parse: baris mentah.
        "ocr_lines": list(rp.lines),
    }
    return Parsed(doc=doc, extra=extra)


class StrukBelanjaReader:
    doc_type = "struk_belanja"
    name = "struk_belanja"

    def detect(self, doc: TextDoc) -> float:
        if is_app_receipt(doc.lines):
            return 0.2          # resi aplikasi bank (tagihan, pulsa, bukti bayar): bukan struk belanja
        has_total = False
        item_lines = 0
        for line in doc.lines:
            line = normalize_line(line)
            up = line.upper()
            if _is_strong_total(up):
                has_total = True
            elif _is_item_like(line, up):
                item_lines += 1
        has_items = item_lines >= 2
        if has_total and has_items:
            return 0.9
        if has_total or has_items:
            return 0.6
        return 0.2

    async def parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        rp = parse_receipt(
            doc.lines, ctx.today,
            merchant_aliases=ctx.merchant_aliases, merchant_profiles=ctx.merchant_profiles,
        )
        fb = await llm_fallback(ctx) if rp.confidence in ("rendah", "gagal") else None
        parsed = parsed_from_receipt(rp, fb)
        apply_header_status(parsed.doc, doc.lines)        # status bawaan `berhasil`; judul status bisa menjadikannya gagal/pending
        return parsed

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]:
        return []
