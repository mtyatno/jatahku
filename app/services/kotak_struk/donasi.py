"""Donasi contoh Kotak Struk (belajar lintas user tahap 2; spec 2026-11-01 §10 Tahap 2 butir 1, §12.4).

User yang SETUJU (opt-in di Settings) menyumbang baris teks bukti TERSAMAR dari bukti bayar yang ia koreksi; pemilik
meninjaunya di Admin dan menyalin yang disetujui ke korpus pembaca. Semuanya di balik saklar `features.kotak_donasi`
(bawaan mati, pre-flight A16 K1/G1): kebijakan privasi yang tayang harus memuat paragraf donasi dulu.

Bagian M1a: saklar, persetujuan, dan lupa. Bagian M1b: `sample_lines` (baris tersamar yang ditangkap worker).
- `donation_available`: saklar menyala (web).
- `consented` / `set_consent`: satu baris `proof_sample_consents` per user; menyalakan idempoten (waktu pertama tetap),
  mematikan = menghapus baris itu dan `forget_user`.
- `sample_lines` (M1b, pre-flight A16 §2, K5, G6): dari teks OCR dan hasil baca SEBELUM disamarkan (titik yang sama
  dengan kerangka tata letak worker), hanya dipanggil worker untuk user yang setuju saat saklar menyala.
- `forget_user` (G4): semua `proof_samples` user (juga yang disetujui), persetujuannya, dan `receipt_scans.sample_lines`
  miliknya. Dipakai saat menarik persetujuan, hapus akun (`account_deletion.delete_account`), dan gabung akun
  (`merge.merge_users`, source; persetujuan tidak diwariskan ke target).

Tidak ada fungsi di sini yang meng-commit; pemanggil (route, hapus akun, gabung akun) meng-commit. Modul ini tidak
menanyakan keanggotaan household (`test_ruang_pagar`).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import delete, exists, null, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ProofSample, ProofSampleConsent, ReceiptScan
from app.services.app_config import feature_enabled
from app.services.kotak_struk import kerangka, samaran
from app.services.kotak_struk.config import PROOF_TYPES, SAMPLE_LINE_MAX, SAMPLE_MAX_LINES, SAMPLE_TYPES
from app.services.kotak_struk.document import DokumenBayar
from app.services.kotak_struk.extract import KIND_IMAGE, TextDoc
from app.services.kotak_struk.readers import proof_common as pc
from app.services.kotak_struk.readers.base import Secrets
from app.services.kotak_struk.registry import looks_like_proof

FEATURE = "kotak_donasi"


async def donation_available(db: AsyncSession) -> bool:
    """Saklar donasi contoh (`features.kotak_donasi`, web). Mati: tidak ada tombol di Settings dan tidak ada baris yang
    ditangkap; menarik persetujuan tetap bisa."""
    return await feature_enabled(db, FEATURE, "web")


async def consented(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """User ini sudah menyalakan donasi contoh (ada baris persetujuan)."""
    return bool((await db.execute(
        select(exists().where(ProofSampleConsent.user_id == user_id)))).scalar())


async def consented_at(db: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """Waktu user menyalakan donasi contoh, atau None bila belum/sudah ditarik."""
    return (await db.execute(
        select(ProofSampleConsent.consented_at).where(ProofSampleConsent.user_id == user_id))).scalar_one_or_none()


async def set_consent(db: AsyncSession, user_id: uuid.UUID, on: bool, *, now: datetime) -> datetime | None:
    """Nyalakan (`on`) atau tarik persetujuan donasi contoh. Menyalakan idempoten: baris yang sudah ada tidak diubah
    (waktu persetujuan pertama tetap), dua permintaan bersamaan tidak menggagalkan satu sama lain (SAVEPOINT);
    mengembalikan waktu persetujuan. Menarik: baris persetujuan dihapus dan `forget_user` (semua sampel dan baris
    tersamar user ini); mengembalikan None. Tidak memeriksa saklar (route yang menolak menyalakan saat saklar mati) dan
    tidak meng-commit."""
    if not on:
        await forget_user(db, user_id)
        return None
    current = await consented_at(db, user_id)
    if current is not None:
        return current
    try:
        async with db.begin_nested():
            db.add(ProofSampleConsent(user_id=user_id, consented_at=now))
            await db.flush()
    except IntegrityError:   # permintaan lain baru saja menyalakannya: pakai baris itu
        pass
    return await consented_at(db, user_id)


async def forget_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Lupakan semua donasi user ini (G4): hapus semua `proof_samples`-nya (menunggu, disetujui, ditolak), baris
    persetujuannya, dan kosongkan `receipt_scans.sample_lines` miliknya (SQL NULL). Sampel milik user lain yang pernah
    ia putuskan sebagai admin tidak disentuh (pemanggil hapus akun mengosongkan `decided_by`). Tidak meng-commit."""
    await db.execute(delete(ProofSample).where(ProofSample.user_id == user_id))
    await db.execute(delete(ProofSampleConsent).where(ProofSampleConsent.user_id == user_id))
    await db.execute(
        update(ReceiptScan)
        .where(ReceiptScan.user_id == user_id, ReceiptScan.sample_lines.is_not(None))
        .values(sample_lines=null())
        .execution_options(synchronize_session=False)
    )


# ── Baris tersamar (M1b) ────────────────────────────────────────────────────

_LONG_DIGITS = re.compile(r"\d{%d,}" % samaran.MIN_RUN_DIGITS)
_NMID_LINE = re.compile(r"nmid", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
GROUPED_MIN_DIGITS = 10
_GROUPED_NUMBER = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?![\d])")
_AFTER_CURRENCY = re.compile(r"(?:rp|idr)\s*[.:]?\s*$", re.IGNORECASE)


# Kata kosakata label/status/arah uang (bukan nama). Kata penyedia/logo/penanda aplikasi di `kerangka.TITLE_WORDS`
# ("mega", "neo", "jago", "mandiri", "permata") sering juga nama orang, jadi tidak termasuk (review M1b temuan 1). Sisa
# risiko: "dana" kata label ("Sumber Dana") sekaligus nama depan; nama itu di tebakan pembaca struk tidak disamarkan
# otomatis, pemilik meninjaunya di Admin.
_VOCAB_WORDS: frozenset[str] = kerangka.LABEL_WORDS | frozenset(kerangka._TITLE_EXTRA.split())


def _party_name(doc: DokumenBayar) -> str | None:
    """Nama pihak lawan dokumen. Bukti yang tidak dibaca pembaca QRIS/transfer (struk belanja/tidak dikenali): "nama"-nya
    tebakan pembaca struk, sering judul status atau logo aplikasi ("Transfer Berhasil", "Bca Mobile"; worker membuangnya
    dari Dokumen Bayar). Tebakan yang SEMUA katanya kosakata judul (`kerangka.TITLE_WORDS`) bukan nama (None). Selain itu
    hanya kata kosakata label/status (`_VOCAB_WORDS`) yang tidak disamarkan; kata lain, juga kata penyedia/logo,
    disamarkan ("Penerima Budi" -> "Budi"; "Mega Lestari" -> kedua katanya)."""
    name = doc.counterparty.name
    if not name or doc.doc_type in PROOF_TYPES:
        return name
    words = [(w, kerangka.words(w)) for w in name.split()]
    words = [(w, norm[0]) for w, norm in words if norm]
    if all(norm in kerangka.TITLE_WORDS for _w, norm in words):
        return None
    return " ".join(w for w, norm in words if norm not in _VOCAB_WORDS) or None


def _known_names(clean: list[str], doc: DokumenBayar, user_name: str | None) -> dict[str, str | None]:
    """Nama yang dikenal per peran samaran: pihak lawan dokumen (`_party_name`), pengirim tercetak, merchant yang dibaca
    pembaca bukti dari baris berlabel, dan user (sumber yang sama dengan `kerangka._forbidden_words`)."""
    profile = kerangka._profile_of(doc, clean)
    try:   # pembaca nama hanya tambahan pengaman
        merchant = pc.read_name(pc.body_lines(clean), profile, "merchant")
    except Exception:
        merchant = None
    return {"pihak": _party_name(doc), "pengirim": pc.read_sender_name(clean, profile), "merchant": merchant,
            "user": user_name}


def _grouped_account(line: str) -> bool:
    """Ada nomor berkelompok ribuan >= GROUPED_MIN_DIGITS digit yang tidak langsung sesudah Rp/IDR ("Rek 1.234.567.890":
    `mask_line` membiarkannya karena berbentuk nominal). "Rp 1.234.567" tetap."""
    for m in _GROUPED_NUMBER.finditer(line):
        if sum(c.isdigit() for c in m.group()) >= GROUPED_MIN_DIGITS and not _AFTER_CURRENCY.search(line[:m.start()]):
            return True
    return False


def _holds_secret(line: str, secrets: Secrets) -> bool:
    """Baris masih memuat nilai rahasia (nomor referensi, rekening, NMID di luar baris berlabel NMID), deret >= 6 digit,
    alamat email, atau nomor berkelompok ribuan >= 10 digit di luar Rp/IDR (review M1b temuan 2, 3).

    Dua aturan terakhir (email, nomor berkelompok) juga harus diterapkan pemeriksaan persetujuan Admin (M1d) pada baris
    editan, bersama `\\d{6,}`."""
    if _LONG_DIGITS.search(line) or _EMAIL.search(line) or _grouped_account(line):
        return True
    digits = re.sub(r"\D", "", line)
    values = [*secrets.ref_values, secrets.account_number]
    if not _NMID_LINE.search(line):
        values.append(secrets.nmid)
    for value in values:
        value = (value or "").strip()
        if not value:
            continue
        if len(value) >= 4 and value.lower() in line.lower():
            return True
        value_digits = re.sub(r"\D", "", value)
        if len(value_digits) >= pc.LONG_DIGITS and value_digits in digits:
            return True
    return False


def sample_lines(lines: list[str], doc: DokumenBayar, secrets: Secrets, *, user_name: str | None) -> list[str] | None:
    """Baris tersamar satu bukti untuk donasi contoh, atau None.

    Hanya bukti bayar (G6): `doc.doc_type` di SAMPLE_TYPES, atau teks yang tampak bukti (`looks_like_proof`; bukti yang
    dibaca pembaca struk); struk belanja biasa tidak pernah. `lines` = baris OCR mentah, `doc`/`secrets` = hasil pembaca
    SEBELUM disamarkan worker. Langkah: `clean_lines` -> `samaran.mask_line` -> `samaran.pseudonymise` (nama pihak lawan,
    pengirim, merchant terbaca, user) -> baris yang masih memuat nilai `secrets` atau deret >= 6 digit dibuang -> paling
    banyak SAMPLE_MAX_LINES baris, masing-masing SAMPLE_LINE_MAX karakter. None juga bila tidak ada baris tersisa."""
    if doc.doc_type not in SAMPLE_TYPES and not looks_like_proof(TextDoc(lines=list(lines), kind=KIND_IMAGE)):
        return None
    clean = pc.clean_lines(lines)
    masked = [samaran.mask_line(line) for line in clean]
    named, _user = samaran.pseudonymise(masked, _known_names(clean, doc, user_name))
    kept = [line[:SAMPLE_LINE_MAX] for line in named if not _holds_secret(line, secrets)]
    return kept[:SAMPLE_MAX_LINES] or None
