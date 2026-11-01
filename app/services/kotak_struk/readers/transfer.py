"""Pembaca bukti transfer bank/e-wallet berbasis pasangan label-nilai (`transfer.umum`),
termasuk top-up saldo dan uang masuk. Didaftarkan oleh registry.py (modul ini tidak
mengimpor registry)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.kotak_struk.checks import may_be_user, same_person
from app.services.kotak_struk.document import Counterparty, DokumenBayar, Ref
from app.services.kotak_struk.merchants import mask_digits
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed, Secrets
from app.services.kotak_struk.readers.labels import count_markers
from app.services.kotak_struk.readers.profiles import (
    detect_issuer, is_money_provider, learned_paid_at, learned_profile, learned_total,
)

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc

TRANSFER_MARKERS = ["transfer", "rekening tujuan", "bank tujuan", "bi-fast", "berita", "penerima"]
# ShopeePay (A14 r3): label "Jumlah Kirim Uang" di awal baris dihitung satu penanda; "kirim uang" di tengah kalimat tidak
# ("Silakan kirim uang ke rekening BCA …" di faktur). "Kirim Ke"/"Dikirim Dari" hanya dihitung bersama label itu; sendirian
# kata biasa ("Kirim ke: Jl. Merdeka" di faktur belanja online). Kata utuh: "Dikirim ke" tidak cocok dengan "kirim ke".
_SEND_AMOUNT = re.compile(r"^\s*jumlah\s+kirim\s+uang(?=$|[\s:：])", re.IGNORECASE)
_SEND_LABELS = ["kirim ke", "dikirim dari"]
STRONG, OTHER_FLOW_CORROBORATED, OTHER_FLOW = 0.9, 0.9, 0.85

_TOP_UP = re.compile(r"(?<!\w)(top[\s-]?up|isi\s+saldo)(?!\w)", re.IGNORECASE)
_INCOMING = re.compile(r"(?<!\w)(dana\s+masuk|uang\s+masuk|terima\s+dana)(?!\w)", re.IGNORECASE)
_DESTINATION_LINE = re.compile(r"^\s*(?:penerima|tujuan|rekening\s+tujuan|bank\s+tujuan|ke)(?=$|[\s:：])", re.IGNORECASE)
_SENDER_LINE = re.compile(r"^\s*(?:pengirim|dari)(?=$|[\s:：])", re.IGNORECASE)


def _other_flow(lines: list[str], status: str) -> str | None:
    """`top_up` (Top Up, Isi Saldo) atau `masuk` (Dana Masuk, Uang Masuk, Terima Dana; atau label
    "Dari"/"Pengirim" tanpa label tujuan, asal ada kata status). Frasa di baris catatan diabaikan
    ("Berita top up gopay" pada transfer biasa). Selain itu None (= keluar)."""
    texts = [line for line in lines if not pc.is_label_line(line, fields=("note",))]
    if any(_TOP_UP.search(t) for t in texts):
        return "top_up"
    if any(_INCOMING.search(t) for t in texts):
        return "masuk"
    has_sender = any(_SENDER_LINE.match(t) for t in texts)
    has_destination = any(_DESTINATION_LINE.match(t) for t in texts)
    if has_sender and not has_destination and status != pc.TIDAK_DIKETAHUI:
        return "masuk"
    return None


class TransferReader:
    doc_type = "transfer"
    name = "transfer.umum"

    def detect(self, doc: TextDoc) -> float:
        """0.9: dua penanda transfer atau lebih. Top-up dan uang masuk (ada nominalnya): 0.85, naik ke 0.9
        bila ada penanda transfer lain atau kata status, supaya bukti top-up ber-Nominal/Biaya/Total tidak
        kalah dari pembaca struk belanja (0.9; seri: bukti menang). Pola struk belanja: 0."""
        lines = pc.clean_lines(doc.lines)
        if not lines or pc.looks_like_store_receipt(lines):
            return 0.0
        send_amount = any(_SEND_AMOUNT.match(line) for line in lines)
        markers = count_markers(lines, TRANSFER_MARKERS) + send_amount
        if markers >= 2 or (send_amount and count_markers(lines, _SEND_LABELS)):
            return STRONG
        party = pc.read_header_party(lines, detect_issuer(lines))
        if party and is_money_provider(party.provider):
            return STRONG       # nama penerima lalu "GoPay · 0812…" / "Mandiri · 123…" di bawah logo (Jago Syariah)
        status = pc.read_status(lines)
        if _other_flow(lines, status) and pc.has_amount(lines):
            return OTHER_FLOW_CORROBORATED if markers or status != pc.TIDAK_DIKETAHUI else OTHER_FLOW
        return 0.0

    async def parse(self, doc: TextDoc, ctx: ParseContext) -> Parsed:
        lines = pc.clean_lines(doc.lines)
        body = pc.body_lines(lines)
        profile = detect_issuer(lines)
        # Status dan arah uang hanya dari profil asli dan baris bukti: aturan belajar tidak pernah menyentuhnya (spec §1.3).
        status = pc.read_proof_status(body, profile)
        flow = _other_flow(body, status) or "keluar"
        if flow == "masuk" and status == pc.TIDAK_DIKETAHUI:
            status = pc.BERHASIL            # uang yang tercatat masuk sudah sampai
        # Aturan belajar yang disetujui (spec §5): `lp` membaca label (penerima aturan didahulukan).
        learned, lp = learned_profile(lines, profile, ctx.rules)
        amounts, total_confidence = pc.read_amounts(body, lp)
        amounts, total_confidence = learned_total(amounts, total_confidence, body, learned.total)
        paid_at, paid_confidence = learned_paid_at(body, learned.date) or pc.read_paid_at(body, lp)
        block = pc.read_side_block(body, lp) if flow == "keluar" else None
        if block:                                            # ShopeePay "Kirim Ke": nama, lalu "Bank Jago Syariah: 1234…"
            name, bank_code, account = block.name, pc.normalize_bank(block.provider), block.number
        else:
            numbers: list[str] = []    # deret angka panjang yang tercetak di nama/bank: tidak boleh bertahan di sana
            name = pc.read_name(body, lp, "sender" if flow == "masuk" else "merchant", numbers=numbers)
            bank_code = pc.read_bank(body, lp, numbers=numbers)
            account = pc.read_account(body, lp) or pc.account_from(numbers)   # tanpa label rekening: dari angka yang ditemukan
            party = pc.read_header_party(body, lp)
            if party and is_money_provider(party.provider):      # "Mandiri·…4321" di bawah nama penerima
                bank_code = bank_code or pc.normalize_bank(party.provider)
                account = account or party.number
            below = pc.read_party_account(body, lp, "sender" if flow == "masuk" else "merchant")
            if below:                                            # "Ditransfer ke BUDI" lalu "Mandiri 1234…" (GoPay)
                bank_code = bank_code or pc.normalize_bank(below[0])
                account = account or below[1]
        sender = None
        if flow == "keluar" and same_person(ctx.user_name, name):
            # Penerimanya user. Pengirim yang tercetak dan jelas orang lain -> uang masuk dari pengirim itu (bukti dibagikan
            # pengirim); rekening yang terbaca milik user sendiri, jadi tidak dipakai. Pengirim yang bisa jadi user ("ANDI
            # ********"), yang juga mirip user (nama resmi lebih panjang "ANDI PRATAMA BIN SUPARDI", gelar "IR ANDI PRATAMA";
            # `same_person`), atau tidak tercetak: antar rekening sendiri (`checks.apply_flow`).
            sender = pc.read_sender_name(body, lp)
            if sender and not may_be_user(ctx.user_name, sender) and not same_person(ctx.user_name, sender):
                flow, name, bank_code, account = "masuk", sender, None, None
        refs = pc.read_refs(body, lp)

        confidence = {}
        if amounts.total is not None:
            confidence["total"] = total_confidence
        if name:
            confidence["counterparty"] = "tinggi"
        if paid_at:
            confidence["paid_at"] = paid_confidence
        evidence = ["Pembaca transfer umum"]
        if profile:
            evidence.append(f"Aplikasi {profile.label}")
        if status != pc.TIDAK_DIKETAHUI:
            evidence.append(f"Status {status}")
        if flow != "keluar":
            evidence.append({"top_up": "Top-up saldo", "masuk": "Uang masuk"}[flow])
        if flow == "masuk" and sender == name:
            evidence.append("Penerima mirip nama akun kamu, pengirimnya orang lain")

        doc_out = DokumenBayar(
            doc_type=self.doc_type,
            issuer=profile.key if profile else None,
            status=status,
            flow=flow,
            method="transfer",
            paid_at=paid_at,
            counterparty=Counterparty(
                name=name,
                bank=bank_code,
                id_kind="rekening" if account else None,
                id_masked=mask_digits(account) if account else None,
            ),
            amounts=amounts,
            refs=[Ref(kind=kind, masked=pc.mask_ref(value)) for kind, value in refs],
            note=pc.scrub_note(pc.read_note(body, lp), [account or "", *(value for _, value in refs)]),
            confidence=confidence,
            evidence=evidence,
        )
        secrets = Secrets(ref_values=[value for _, value in refs], account_number=account, bank_code=bank_code)
        return Parsed(doc=doc_out, secrets=secrets)

    def checks(self, parsed: Parsed, ctx: ParseContext) -> list[Check]:
        return []   # cek silang bersama (nominal, status, tanggal, arah uang) ada di checks.py


# Nama publik untuk modul lain (kotak_struk/kerangka.py): jangan dihapus atau diganti nama tanpa memperbarui pemakainya.
TOP_UP = _TOP_UP
INCOMING = _INCOMING
