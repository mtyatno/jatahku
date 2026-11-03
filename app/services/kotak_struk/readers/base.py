"""Tipe dasar pembaca dokumen: konteks, hasil baca, cek silang, dan Protocol pembaca."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Callable, Protocol

from app.services.kotak_struk.document import DokumenBayar

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc


@dataclass
class Secrets:
    """Nilai mentah yang tidak boleh disimpan utuh. Pemanggil (worker) hanya menyimpan
    HMAC-nya; yang masuk Dokumen Bayar hanya versi tersamar."""
    ref_values: list[str] = field(default_factory=list)
    account_number: str | None = None
    bank_code: str | None = None
    nmid: str | None = None


@dataclass
class Parsed:
    doc: DokumenBayar
    secrets: Secrets = field(default_factory=Secrets)
    # Struk belanja: total_label, merchant_key, confidence_source, engine,
    # reconciliation, adjustments (bentuk JSON seperti `receipt_scan.items_payload`),
    # item_discounts (voucher per barang, sejajar dengan baris `item` di doc.lines),
    # ocr_lines (baris OCR yang sudah dinormalkan parse_receipt, untuk pembelajaran umpan balik).
    extra: dict = field(default_factory=dict)


@dataclass
class Check:
    code: str
    level: str      # warn | block
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "message": self.message}


@dataclass
class ParseContext:
    today: date
    user_name: str | None = None
    merchant_aliases: dict = field(default_factory=dict)
    merchant_profiles: dict = field(default_factory=dict)
    # Hanya untuk fallback LLM struk belanja: gambar asli, tipenya, dan fungsi pemanggilnya
    # (`llm(image, content_type, user_id, plan) -> dict | None`). Tanpa gambar atau `llm`, tidak ada panggilan.
    image: bytes | None = None
    content_type: str | None = None
    user_id: Any = None
    plan: str = "basic"
    llm: Callable | None = None
    # Aturan belajar yang disetujui pemilik (spec 2026-11-01 §5): `{rule_key: {"label_total": [...], "label_pihak": [...],
    # "label_tanggal": [...]}}`, dimuat worker dari cache (`belajar.approved_rules`). Kosong = perilaku tanpa aturan
    # (bawaan; tes pembaca dan `kotak_corpus` selalu kosong). Hanya pembaca QRIS, transfer, dan tidak dikenali yang
    # membacanya, dan hanya untuk label nilai; status, arah uang, cek, dan dedup tidak pernah (registry memberi mereka
    # konteks tanpa aturan).
    rules: dict = field(default_factory=dict)


class DocReader(Protocol):
    doc_type: str
    name: str

    def detect(self, doc: TextDoc) -> float: ...

    async def parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed: ...

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]: ...
