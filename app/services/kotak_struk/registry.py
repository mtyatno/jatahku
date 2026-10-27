"""Registri pembaca dokumen: pilih pembaca dengan skor `detect` tertinggi (>= ambang),
jalankan, lalu cek silang. Pembaca struk belanja selalu aktif; pembaca bukti bayar
(QRIS, transfer) hanya bila saklar `receipt_inbox` menyala.

Pembaca bukti bayar didaftarkan di sini, di akhir modul, supaya `read_document` selalu melihatnya
tanpa bergantung pada siapa yang mengimpor modul pembaca (modul pembaca tidak mengimpor registry,
jadi tidak ada impor melingkar)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.kotak_struk import checks as cross_checks
from app.services.kotak_struk.config import READER_THRESHOLD
from app.services.kotak_struk.readers.base import Check, DocReader, ParseContext, Parsed
from app.services.kotak_struk.readers.proof_common import has_header_status_title
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
    mengenalinya, atau bila 4 baris pertamanya memuat judul status ("Transfer Berhasil", "Pembayaran Gagal";
    `has_header_status_title`): bukti dengan satu penanda saja tidak dikenali pembaca bukti, padahal struk belanja tidak
    pernah berjudul seperti itu. Hanya untuk penyimpanan: perutean tetap mengikuti `proofs_enabled` di `read_document`.

    Dipakai worker: dengan saklar mati bukti bayar dibaca pembaca struk belanja, tetapi teks OCR-nya memuat
    nomor rekening/referensi dan nama pihak ketiga, jadi teks, rincian baris, dan nama merchant-nya tidak boleh
    disimpan atau masuk peta merchant."""
    return any(reader.detect(doc) >= READER_THRESHOLD for reader in _PROOF_READERS) or has_header_status_title(doc.lines)


async def read_document(doc: TextDoc, ctx: ParseContext, *, proofs_enabled: bool) -> ReadResult:
    reader: DocReader | None = None
    best = 0.0
    for candidate in readers_for(proofs_enabled):
        score = candidate.detect(doc)
        if score >= READER_THRESHOLD and score > best:  # `>`: seri dimenangkan yang lebih dulu
            reader, best = candidate, score
    reader = reader or _UNKNOWN

    parsed = await reader.parse(doc, ctx)
    cross_checks.apply_flow(parsed, ctx)
    found = [*reader.checks(parsed, ctx), *cross_checks.common_checks(parsed, ctx)]
    parsed.doc.checks = [c.as_dict() for c in found]
    return ReadResult(parsed=parsed, checks=found, reader=reader.name)


# Urutan = pemecah seri skor: QRIS, transfer, lalu struk belanja (lihat `readers_for`).
register_proof_reader(QrisReader())
register_proof_reader(TransferReader())
