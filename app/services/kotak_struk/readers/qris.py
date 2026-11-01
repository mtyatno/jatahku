"""Pembaca bukti pembayaran QRIS berbasis pasangan label-nilai (`qris.umum`).
Didaftarkan oleh registry.py (modul ini tidak mengimpor registry)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.kotak_struk.document import Counterparty, DokumenBayar, Ref
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed, Secrets
from app.services.kotak_struk.readers.labels import count_markers
from app.services.kotak_struk.readers.profiles import detect_issuer, learned_paid_at, learned_profile, learned_total

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc

# "PAN Merchant" dan "ID Terminal": urutan kata di Jago Syariah (A14). "Nama Pengakuisisi", "PAN Pelanggan": istilah QRIS
# berbahasa Indonesia (ShopeePay, A14 r3).
QRIS_MARKERS = ["qris", "nmid", "merchant pan", "pan merchant", "terminal id", "id terminal", "acquirer", "penerbit",
                "pengakuisisi", "pan pelanggan"]
STRONG, WITH_OUTCOME, WEAK = 0.95, 0.9, 0.7


class QrisReader:
    doc_type = "qris"
    name = "qris.umum"

    def detect(self, doc: TextDoc) -> float:
        """0.95: dua penanda QRIS atau lebih. Hanya kata "QRIS" tapi ada label merchant/nominal: 0.7,
        naik ke 0.9 bila ada kata status ("Berhasil", ...) karena struk belanja tidak memilikinya dan
        bukti ber-Nominal/Biaya/Total bisa dinilai 0.9 oleh pembaca struk belanja (seri: bukti menang).
        Pola struk belanja (KEMBALI/TUNAI, >= 3 barang): 0."""
        lines = pc.clean_lines(doc.lines)
        if not lines or pc.looks_like_store_receipt(lines):
            return 0.0
        if count_markers(lines, QRIS_MARKERS) >= 2:
            return STRONG
        if count_markers(lines, ["qris"]) and (
                pc.read_text(lines, ["merchant", "nama merchant"]) or pc.has_amount(lines)):
            return WITH_OUTCOME if pc.read_status(lines) != pc.TIDAK_DIKETAHUI else WEAK
        return 0.0

    async def parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        lines = pc.clean_lines(doc.lines)
        body = pc.body_lines(lines)
        profile = detect_issuer(lines)
        # Aturan belajar yang disetujui (spec §5): `lp` membaca label (penerima aturan didahulukan); status hanya dari
        # profil asli, jadi aturan tidak pernah menyentuhnya.
        learned, lp = learned_profile(lines, profile, ctx.rules)
        amounts, total_confidence = pc.read_amounts(body, lp)
        amounts, total_confidence = learned_total(amounts, total_confidence, body, learned.total)
        status = pc.read_proof_status(body, profile)
        paid_at, paid_confidence = learned_paid_at(body, learned.date) or pc.read_paid_at(body, lp)
        name = pc.read_name(body, lp, "merchant")     # nomor panjang (NMID, telepon) dibuang dari nama
        city = pc.read_city(body, lp)
        if not city and not pc.read_text(body, pc.labels_for(lp, "merchant"), lp):
            party = pc.read_header_party(body, lp)      # tata letak "nama di bawah logo": kota di bawah nama
            city = party.city if party else None
        nmid = pc.read_nmid(body, lp)
        refs = pc.read_refs(body, lp)

        confidence = {}
        if amounts.total is not None:
            confidence["total"] = total_confidence
        if name:
            confidence["counterparty"] = "tinggi"
        if paid_at:
            confidence["paid_at"] = paid_confidence
        evidence = ["Pembaca QRIS umum"]
        if profile:
            evidence.append(f"Aplikasi {profile.label}")
        if status != pc.TIDAK_DIKETAHUI:
            evidence.append(f"Status {status}")

        doc_out = DokumenBayar(
            doc_type=self.doc_type,
            issuer=profile.key if profile else None,
            status=status,
            flow="keluar",
            method="qris",
            paid_at=paid_at,
            counterparty=Counterparty(
                name=name,
                city=city,
                id_kind="nmid" if nmid else None,
                id_masked=pc.mask_id(nmid) if nmid else None,
            ),
            amounts=amounts,
            refs=[Ref(kind=kind, masked=pc.mask_ref(value)) for kind, value in refs],
            confidence=confidence,
            evidence=evidence,
        )
        return Parsed(doc=doc_out, secrets=Secrets(ref_values=[value for _, value in refs], nmid=nmid))

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]:
        return []   # cek silang bersama (nominal, status, tanggal) ada di checks.common_checks

