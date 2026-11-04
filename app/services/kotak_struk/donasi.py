"""Donasi contoh Kotak Struk (belajar lintas user tahap 2; spec 2026-11-01 §10 Tahap 2 butir 1, §12.4).

User yang SETUJU (opt-in di Settings) menyumbang baris teks bukti TERSAMAR dari bukti bayar yang ia koreksi; pemilik
meninjaunya di Admin dan menyalin yang disetujui ke korpus pembaca. Semuanya di balik saklar `features.kotak_donasi`
(bawaan mati, pre-flight A16 K1/G1): kebijakan privasi yang tayang harus memuat paragraf donasi dulu.

Bagian ini (M1a): saklar, persetujuan, dan lupa.
- `donation_available`: saklar menyala (web).
- `consented` / `set_consent`: satu baris `proof_sample_consents` per user; menyalakan idempoten (waktu pertama tetap),
  mematikan = menghapus baris itu dan `forget_user`.
- `forget_user` (G4): semua `proof_samples` user (juga yang disetujui), persetujuannya, dan `receipt_scans.sample_lines`
  miliknya. Dipakai saat menarik persetujuan, hapus akun (`account_deletion.delete_account`), dan gabung akun
  (`merge.merge_users`, source; persetujuan tidak diwariskan ke target).

Tidak ada fungsi di sini yang meng-commit; pemanggil (route, hapus akun, gabung akun) meng-commit. Modul ini tidak
menanyakan keanggotaan household (`test_ruang_pagar`).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, null, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ProofSample, ProofSampleConsent, ReceiptScan
from app.services.app_config import feature_enabled

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
