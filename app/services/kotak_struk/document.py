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
