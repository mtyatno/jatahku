"""Registri pembaca dokumen: pilih pembaca dengan skor `detect` tertinggi (>= ambang),
jalankan, lalu cek silang. Pembaca struk belanja selalu aktif; pembaca bukti bayar
(QRIS, transfer) hanya bila saklar `receipt_inbox` menyala.

Pembaca bukti bayar didaftarkan di sini, di akhir modul, supaya `read_document` selalu melihatnya
tanpa bergantung pada siapa yang mengimpor modul pembaca (modul pembaca tidak mengimpor registry,
jadi tidak ada impor melingkar)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.services.kotak_struk import checks as cross_checks
from app.services.kotak_struk.config import PROOF_TYPES, READER_THRESHOLD
from app.services.kotak_struk.readers.base import Check, DocReader, ParseContext, Parsed
from app.services.kotak_struk.readers.proof_common import (
    clean_lines, has_header_status_title, has_item_lines, has_status_title, has_success_title, is_app_receipt,
    looks_like_store_text, read_labelled_failure,
)
from app.services.kotak_struk.readers.qris import QrisReader
from app.services.kotak_struk.readers.struk_belanja import StrukBelanjaReader
from app.services.kotak_struk.readers.transfer import TransferReader
from app.services.kotak_struk.readers.unknown import UnknownReader

if TYPE_CHECKING:
    from app.services.kotak_struk.extract import TextDoc

# Pembaca bukti bayar, dalam urutan pendaftaran (didaftarkan lewat register_proof_reader).
_PROOF_READERS: list[DocReader] = []
_STRUK_BELANJA = StrukBelanjaReader()
_UNKNOWN = UnknownReader()


@dataclass
class ReadResult:
    parsed: Parsed
    checks: list[Check]
    reader: str


def register_proof_reader(reader: DocReader) -> None:
    """Daftarkan pembaca bukti bayar. Idempotent per `reader.name`: nama yang sama
    (mis. modul diimpor ulang) menggantikan entri lama di posisi yang sama."""
    for i, known in enumerate(_PROOF_READERS):
        if known.name == reader.name:
            _PROOF_READERS[i] = reader
            return
    _PROOF_READERS.append(reader)


def readers_for(proofs_enabled: bool) -> list[DocReader]:
    """Urutan daftar = urutan pemecah seri: bukti bayar sebelum struk belanja."""
    return [*_PROOF_READERS, _STRUK_BELANJA] if proofs_enabled else [_STRUK_BELANJA]


def looks_like_proof(doc: TextDoc) -> bool:
    """Apakah teks ini tampak bukti bayar (QRIS/transfer), apa pun saklar fiturnya? Ya bila salah satu pembaca bukti
    mengenalinya, bila 4 baris pertamanya memuat judul status ("Transfer Berhasil", "Pembayaran Gagal";
    `has_header_status_title`), bila teksnya resi aplikasi bank/e-wallet (`is_app_receipt`: logo aplikasi dan label rekening
    sumber; juga tagihan dan pulsa, yang memuat nomor meter/HP dan token), atau bila judul status ada di baris mana pun dan teksnya tidak berpola struk belanja
    (`has_status_title`, `looks_like_store_receipt` pada baris yang dinormalkan seperti `parse_receipt`): bukti dengan satu
    penanda saja tidak dikenali pembaca bukti, dan bukti sering mencetak judulnya di bawah rincian atau di bawah baris status
    bar dan nama aplikasi. Struk belanja yang mencetak "Pembayaran QRIS berhasil" di kakinya tetap struk. Hanya untuk
    penyimpanan: perutean, status, cek, dan nominal tetap mengikuti `read_document`.

    Dipakai worker: dengan saklar mati bukti bayar dibaca pembaca struk belanja, tetapi teks OCR-nya memuat
    nomor rekening/referensi dan nama pihak ketiga, jadi teks, rincian baris, dan nama merchant-nya tidak boleh
    disimpan atau masuk peta merchant."""
    if any(reader.detect(doc) >= READER_THRESHOLD for reader in _PROOF_READERS) or has_header_status_title(doc.lines) \
            or is_app_receipt(doc.lines):
        return True
    if not has_status_title(doc.lines):
        return False
    # Pola struk dibaca dari baris yang dinormalkan seperti `parse_receipt` ("TUNAL 50.000" = "TUNAI 50.000"), supaya struk
    # belanja ber-OCR buruk yang mencetak judul status di kakinya tetap struk dan rinciannya tetap tersimpan.
    return not looks_like_store_text(doc.lines)


def _apply_labelled_failure(parsed: Parsed, doc: TextDoc) -> None:
    """Bukti bayar yang dibaca pembaca struk belanja/tidak dikenali (saklar mati, atau tidak dikenali pembaca bukti) dengan
    status BERLABEL gagal/pending ("Status Gagal", GoPay "Status" lalu "Gagal transfer uang ke penerima") diblokir/
    diperingatkan seperti judul status. Hanya untuk teks yang tampak bukti (`looks_like_proof`), tanpa baris barang, dan tanpa
    judul sukses di mana pun ("Pembayaran Berhasil" mengalahkan label); hanya label status pembayaran (`payment_status_value`:
    bukan "Status Member/Poin/Pengiriman/Pesanan/Refund/Settlement"). Struk belanja biasa tidak terpengaruh."""
    d = parsed.doc
    if d.doc_type in PROOF_TYPES or d.status == "gagal" or has_item_lines(doc.lines) or has_success_title(doc.lines) \
            or not looks_like_proof(doc):
        return
    labelled = read_labelled_failure(doc.lines)
    if labelled == "gagal" or (labelled == "pending" and d.status != "pending"):
        d.status = labelled
        d.evidence.append(f"Bukti menyebut status {labelled}")


async def read_document(doc: TextDoc, ctx: ParseContext, *, proofs_enabled: bool) -> ReadResult:
    """Baca `doc` dengan pembaca terbaik, lalu status berlabel, arah uang, dan cek silang. Aturan belajar
    (`ctx.rules`, spec 2026-11-01 §5) hanya sampai ke `parse` pembaca bukti (QRIS, transfer) dan pembaca tidak dikenali,
    dan hanya bila saklar bukti bayar menyala (saklar mati = perilaku lama). Pembaca struk belanja, arah uang, dan cek
    silang (status gagal/pending, nominal, tanggal) selalu menerima konteks TANPA aturan."""
    reader: DocReader | None = None
    best = 0.0
    for candidate in readers_for(proofs_enabled):
        score = candidate.detect(doc)
        if score >= READER_THRESHOLD and score > best:  # `>`: seri dimenangkan yang lebih dulu
            reader, best = candidate, score
    reader = reader or _UNKNOWN

    plain = replace(ctx, rules={}) if ctx.rules else ctx
    parsed = await reader.parse(doc, ctx if proofs_enabled and reader is not _STRUK_BELANJA else plain)
    _apply_labelled_failure(parsed, doc)
    cross_checks.apply_flow(parsed, plain)
    found = [*reader.checks(parsed, plain), *cross_checks.common_checks(parsed, plain)]
    parsed.doc.checks = [c.as_dict() for c in found]
    return ReadResult(parsed=parsed, checks=found, reader=reader.name)


# Urutan = pemecah seri skor: QRIS, transfer, lalu struk belanja (lihat `readers_for`).
register_proof_reader(QrisReader())
register_proof_reader(TransferReader())
