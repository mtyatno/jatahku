"""Pembaca cadangan: bukti yang tidak dikenali pembaca mana pun. Status hanya dari judul (gagal/pending), seperti struk belanja."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.kotak_struk.document import Amounts, DokumenBayar
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed
from app.services.kotak_struk.readers.struk_belanja import apply_header_status, llm_fallback, parsed_from_receipt
from app.services.receipt_parser import ReceiptParse, amounts_in

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc

_RP_LINE = re.compile(r"(?<![A-Za-z])(?:RP|IDR)(?![A-Za-z])", re.IGNORECASE)


class UnknownReader:
    doc_type = "tidak_dikenali"
    name = "tidak_dikenali"

    def detect(self, doc: TextDoc) -> float:
        return 0.0  # hanya cadangan; registri memakainya bila tidak ada pembaca yang lolos

    async def parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        parsed = await self._parse(doc, ctx)
        # Bukti gagal/pending yang tidak dikenali pembaca mana pun (atau pembaca bukti mati) tetap diblokir/diperingatkan
        # oleh cek status; status bawaan (`tidak_diketahui`, atau `berhasil` dari penyelamatan LLM) hanya diubah oleh judul.
        apply_header_status(parsed.doc, doc.lines)
        return parsed

    async def _parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        # Seperti scan struk lama: foto yang tidak terbaca pun dicoba ke LLM cadangan (bila aktif).
        fb = await llm_fallback(ctx)
        if fb:
            blank = ReceiptParse(merchant=None, date=None, total=None, confidence="gagal", lines=list(doc.lines))
            return parsed_from_receipt(blank, fb)

        amounts = [a for line in doc.lines if _RP_LINE.search(line) for a in amounts_in(line)]
        total = max(amounts) if amounts else None
        evidence = ["Jenis bukti tidak dikenali"]
        if total is not None:
            evidence.append("Total ditebak dari nominal Rp terbesar")
        return Parsed(doc=DokumenBayar(
            doc_type="tidak_dikenali",
            amounts=Amounts(total=total),
            confidence={"total": "rendah"} if total is not None else {},
            evidence=evidence,
        ))

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]:
        return []
