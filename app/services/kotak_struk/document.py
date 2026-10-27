"""Dokumen Bayar: representasi seragam satu bukti bayar (struk belanja, QRIS,
transfer, dan jenis lain nanti). Diserialisasi ke kolom `receipt_scans.document`.

Nomor rekening dan RRN tidak pernah disimpan utuh di sini: hanya versi tersamar
(`Counterparty.id_masked`, `Ref.masked`). HMAC-nya ada di kolom `counterparty_key`
dan `ref_hash` (lihat `merchants.hmac_hex`).
"""
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any


@dataclass
class Counterparty:
    name: str | None = None
    city: str | None = None
    id_kind: str | None = None      # nmid | rekening | ...
    id_masked: str | None = None    # mis. "ID10…6544", "…4567"
    bank: str | None = None


@dataclass
class Amounts:
    subtotal: int | None = None
    fee: int = 0
    tax: int = 0
    discount: int = 0
    total: int | None = None


@dataclass
class Line:
    kind: str                       # item | fee | tax | discount | shipping
    name: str
    amount: int
    qty: float | None = None
    unit_price: int | None = None
    flag: str = "ok"
    note: str | None = None
    suggestion: int | None = None


@dataclass
class Ref:
    kind: str                       # rrn | ref | ...
    masked: str


@dataclass
class DokumenBayar:
    doc_type: str                   # struk_belanja | qris | transfer | tidak_dikenali
    issuer: str | None = None
    status: str = "tidak_diketahui"     # berhasil | gagal | pending | tidak_diketahui
    flow: str = "tidak_diketahui"       # keluar | masuk | top_up | antar_rekening_sendiri | tidak_diketahui
    method: str = "lainnya"             # qris | transfer | va | tunai | kartu | lainnya
    paid_at: datetime | None = None
    counterparty: Counterparty = field(default_factory=Counterparty)
    amounts: Amounts = field(default_factory=Amounts)
    lines: list[Line] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    note: str | None = None             # berita transfer
    confidence: dict[str, str] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    schema: int = 1

    def to_json(self) -> dict:
        d = asdict(self)
        d["paid_at"] = self.paid_at.isoformat() if self.paid_at else None
        return d

    @classmethod
    def from_json(cls, d: dict) -> "DokumenBayar":
        """Field yang tidak dikenal diabaikan (di semua tingkat), supaya dokumen
        yang ditulis versi lama atau baru kode tetap bisa dibaca."""
        data = _known(cls, d)
        data["counterparty"] = Counterparty(**_known(Counterparty, d.get("counterparty") or {}))
        data["amounts"] = Amounts(**_known(Amounts, d.get("amounts") or {}))
        data["lines"] = [Line(**_known(Line, x)) for x in d.get("lines") or []]
        data["refs"] = [Ref(**_known(Ref, x)) for x in d.get("refs") or []]
        data["confidence"] = dict(d.get("confidence") or {})
        data["evidence"] = list(d.get("evidence") or [])
        data["checks"] = [dict(c) for c in d.get("checks") or []]
        paid_at = d.get("paid_at")
        data["paid_at"] = datetime.fromisoformat(paid_at) if isinstance(paid_at, str) else paid_at
        return cls(**data)


def _known(cls: type, d: dict) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in names}


def scan_receipt_response(item, detail: dict) -> dict:
    """Respons `POST /transactions/scan-receipt`: bentuk lama (klien web/bot yang ada tidak berubah) ditambah
    `item_id`, `doc_type`, `counterparty` (tersamar), `paid_at`, `flags`, `suggestion`, `description_preview`.
    `item` = item `ReceiptScan` yang sudah dibaca; `detail` = `view.item_detail` untuknya.

    Struk belanja: `items`/`adjustments`/`reconciliation` dibangun ulang dari `lines` dan `document["receipt"]`
    (yang disimpan worker) lewat `receipt_scan.items_payload`, jadi persis seperti scan lama. Bukti lain: kosong."""
    from app.services.receipt_parser import ReceiptAdjustment, ReceiptItem, Reconciliation
    from app.services.receipt_scan import items_payload

    document = item.document or {}
    doc = DokumenBayar.from_json(document) if document else None
    store = doc is not None and item.doc_type == "struk_belanja"
    # Teks bukti bayar yang dibaca pembaca struk (saklar mati) disimpan tanpa `lines` dan tanpa `receipt`: tanpa rincian.
    receipt = (document.get("receipt") or {}) if store else {}
    discounts = receipt.get("item_discounts") or []   # sejajar dengan baris `item`
    items = [
        ReceiptItem(name=line.name, amount=line.amount, qty=line.qty, unit_price=line.unit_price,
                    discount=(discounts[i] if i < len(discounts) else 0) or 0,
                    flag=line.flag, note=line.note, suggestion=line.suggestion)
        for i, line in enumerate(x for x in doc.lines if x.kind == "item")
    ] if store else []
    adjustments = [ReceiptAdjustment(**a) for a in receipt.get("adjustments") or []]
    rec = receipt.get("reconciliation")
    reconciliation = Reconciliation(**{"total": doc.amounts.total, **rec}) if rec else None

    return {
        "scan_id": str(item.id),
        "merchant": item.merchant,
        "date": item.parsed_date.isoformat() if item.parsed_date else None,
        "total": doc.amounts.total if doc else None,
        "confidence": item.confidence,
        "confidence_source": receipt.get("confidence_source"),
        "evidence": list(doc.evidence) if doc else [],
        "engine": item.engine,
        "ocr_seconds": 0,
        "quota": {"limit": None, "used": 0, "remaining": None},
        **items_payload(items, adjustments, reconciliation),
        "item_id": str(item.id),
        "doc_type": item.doc_type,
        "counterparty": document.get("counterparty"),
        "paid_at": detail.get("paid_at"),
        "flags": detail.get("flags"),
        "suggestion": detail.get("suggestion"),
        "description_preview": detail.get("description_preview"),
    }
