"""Pembaca cadangan: bukti yang tidak dikenali pembaca mana pun. Status hanya dari judul (gagal/pending; juga judul status
gagal/pending di badan), seperti struk belanja. Total: label total atau nominal utama bila teksnya resi aplikasi bank
(tagihan, pulsa, bukti bayar saat saklar mati), selain itu nominal Rp terbesar."""
from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.kotak_struk.document import Amounts, Counterparty, DokumenBayar
from app.services.kotak_struk.merchants import MIN_ACCOUNT_DIGITS
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed
from app.services.kotak_struk.readers.labels import WIB
from app.services.kotak_struk.readers.profiles import detect_issuer
from app.services.kotak_struk.readers.struk_belanja import apply_header_status, llm_fallback, parsed_from_receipt
from app.services.receipt_parser import ReceiptParse, amounts_in, parse_receipt, printed_dates

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
        # oleh cek status; status bawaan (`tidak_diketahui`, atau `berhasil` dari penyelamatan LLM) hanya diubah oleh judul
        # (atau judul status gagal/pending di badan, `apply_header_status`).
        apply_header_status(parsed.doc, doc.lines)
        return parsed

    async def _parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        # Seperti scan struk lama: foto yang tidak terbaca pun dicoba ke LLM cadangan (bila aktif).
        fb = await llm_fallback(ctx)
        if fb:
            blank = ReceiptParse(merchant=None, date=None, total=None, confidence="gagal", lines=list(doc.lines))
            return parsed_from_receipt(blank, fb)

        amounts = [a for line in doc.lines if _RP_LINE.search(line) for a in amounts_in(line)]
        app_total = self._app_receipt_total(doc)
        if not amounts and app_total is None:
            guess = self._legacy_guess(doc, ctx)
            if guess is not None:
                return guess
        total = app_total if app_total is not None else (max(amounts) if amounts else None)
        evidence = ["Jenis bukti tidak dikenali"]
        paid_at = None
        if total is not None:
            evidence.append("Total dari resi aplikasi" if app_total is not None else "Total ditebak dari nominal Rp terbesar")
            # Tanggal tetap tebakan scan struk lama (seperti `_legacy_guess`): bukti yang dulu terbaca sebagai struk (mis.
            # QRIS Jago Syariah, Task H3) tetap bertanggal, jadi pertanyaan tanggal periode lalu (H1) tetap ada. Hanya
            # bila tercetak tepat satu tanggal: tanggal pertama bisa tanggal berita, masa berlaku, jatuh tempo, periode,
            # atau nomor referensi bertitik. Nama tebakannya tidak dibawa: di teks dengan baris Rp itu biasanya
            # judul/label ("Foto Buram", "Merchant").
            rp = parse_receipt(doc.lines, ctx.today, merchant_aliases=ctx.merchant_aliases,
                               merchant_profiles=ctx.merchant_profiles)
            if len(printed_dates(rp.lines)) == 1:
                _, paid_at = self._legacy_meta(rp)
        return Parsed(doc=DokumenBayar(
            doc_type="tidak_dikenali",
            paid_at=paid_at,
            amounts=Amounts(total=total),
            confidence={"total": "sedang" if app_total is not None else "rendah"} if total is not None else {},
            evidence=evidence,
        ))

    @staticmethod
    def _app_receipt_total(doc: TextDoc) -> int | None:
        """Total resi aplikasi bank/e-wallet (`is_app_receipt`: tagihan, pulsa, atau bukti bayar saat saklar mati) dari
        label total ("Total Bayar", "Total") atau nominal utama di bawah nama pihak lawan (tata letak Jago), dibaca seperti
        pembaca bukti. Nominal Rp terbesar bisa saja saldo atau nominal sebelum biaya. None bila bukan resi aplikasi atau
        tidak ada label/nominal utama (nominal terbesar tetap dipakai, keyakinan `rendah`)."""
        lines = pc.clean_lines(doc.lines)
        if not pc.is_app_receipt(lines):
            return None
        profile = detect_issuer(lines)
        body = pc.body_lines(lines)
        amounts, confidence = pc.read_amounts(body, profile)
        if amounts.total is None or not (confidence == "tinggi" or pc.read_header_party(body, profile)):
            return None
        return amounts.total

    def _legacy_guess(self, doc: TextDoc, ctx: ParseContext) -> Parsed | None:
        """Tanpa baris "Rp"/"IDR": tebakan terbaik scan struk lama (`parse_receipt`), supaya foto yang dulu terbaca
        (mis. "TOKO" + "45.500") tidak jadi tanpa total. Hanya total, tanggal, dan nama merchant; keyakinannya selalu
        `rendah`, dan jenisnya tetap `tidak_dikenali` (spec 6a: nominal berkeyakinan rendah, isi manual): sekali
        dicatat, tanpa teks OCR dan data belajar struk belanja (itu hanya untuk struk belanja yang sungguhan dibaca,
        penyelamatan LLM). Rincian barang, kutipan baris di bukti, dan nama berisi deret digit sepanjang nomor rekening
        tidak dibawa: teks yang tidak dikenali siapa pun bisa memuat rekening/telepon. None bila tidak ada total."""
        rp = parse_receipt(doc.lines, ctx.today, merchant_aliases=ctx.merchant_aliases,
                           merchant_profiles=ctx.merchant_profiles)
        if not rp.total:
            return None
        name, paid_at = self._legacy_meta(rp)
        return Parsed(doc=DokumenBayar(
            doc_type="tidak_dikenali",
            paid_at=paid_at,
            counterparty=Counterparty(name=name),
            amounts=Amounts(total=rp.total),
            confidence={"total": "rendah"},
            evidence=["Jenis bukti tidak dikenali", "Total ditebak dari teks tanpa baris Rp"],
        ))

    @staticmethod
    def _legacy_meta(rp: ReceiptParse) -> tuple[str | None, datetime | None]:
        """(nama merchant, tanggal) tebakan `parse_receipt`; nama yang memuat deret digit sepanjang nomor rekening
        dibuang (teks yang tidak dikenali bisa memuat rekening/telepon)."""
        name = rp.merchant
        if name and sum(c.isdigit() for c in name) >= MIN_ACCOUNT_DIGITS:
            name = None
        paid_at = datetime(rp.date.year, rp.date.month, rp.date.day, tzinfo=WIB) if rp.date else None
        return name, paid_at

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]:
        return []
