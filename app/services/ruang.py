"""Penentu ruang (Plugin R2, R3; docs/plugin/04-kontrak-api.md §1, ADR-P1, P2).

Ruang = household. Satu user boleh anggota beberapa ruang (R1): ruang keluarga
(`households.type = rumah_tangga`) dan ruang usaha. Semua kode yang dulu mencari
"household milik user" lewat keanggotaan memakai salah satu fungsi di sini, dan
meneruskan `household_id` secara eksplisit ke services:

- `ruang_aktif` (dependency FastAPI) — untuk **membaca**, dan sejak R3 untuk membuat objek
  baru tanpa induk (amplop, grup, pemasukan tanpa alokasi, reset, cocokkan saldo, rencana
  dana). Header `X-Jatahku-Ruang` memilih ruang tempat user menjadi anggota; tanpa header →
  ruang keluarga, jadi klien lama dan user satu ruang tidak berubah perilakunya.
- **Menulis objek yang sudah ada atau objek dengan induk (R3)**: ruang diambil dari objeknya
  (`ruang_amplop`, `ruang_amplop_satu`, `ruang_objek`), lalu keanggotaan dicek; header tidak
  menentukan ruang. Objek di ruang yang bukan milik user → None (route menjawab 404); satu
  permintaan yang menyentuh dua ruang milik user → `LintasRuang` (400 `lintas_ruang`).
- `ruang_tulis` (dependency FastAPI) — hanya untuk undangan anggota: selalu ruang keluarga,
  header ruang lain ditolak (undangan ruang usaha dibuat di R5).
- `ruang_keluarga(user, db)` — bot (Telegram dan chat web), job terjadwal, dan
  pekerjaan latar. Chat selalu ruang keluarga (ADR-P2).

Header yang tidak sah (bukan UUID, ruang orang lain, ruang terhapus) → 403
`ruang_tidak_diizinkan`. Tidak pernah ada fallback ke ruang lain.
"""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Household, HouseholdMember, HouseholdType, User

RUANG_HEADER = "X-Jatahku-Ruang"
KODE_DITOLAK = "ruang_tidak_diizinkan"
PESAN_DITOLAK = "Ruang ini tidak bisa dibuka dari akunmu. Muat ulang Jatahku lalu pilih ruang lagi."


class RuangDitolak(HTTPException):
    """403 dengan `detail` teks siap tampil; `install()` menambah field `kode` (§7)."""

    def __init__(self, kode: str = KODE_DITOLAK, detail: str = PESAN_DITOLAK, status_code: int = 403):
        super().__init__(status_code=status_code, detail=detail)
        self.kode = kode


def install(app: FastAPI) -> None:
    """Pasang handler yang menambah `kode` ke jawaban `RuangDitolak`."""

    async def _handler(request: Request, exc: RuangDitolak):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "kode": exc.kode})

    app.add_exception_handler(RuangDitolak, _handler)


async def ruang_keluarga_id(db: AsyncSession, user_id) -> UUID | None:
    """Household `rumah_tangga` milik user. Bila (tidak semestinya) lebih dari satu,
    keanggotaan tertua menang, supaya hasilnya tetap dan tidak pernah galat."""
    return (await db.execute(
        select(HouseholdMember.household_id)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user_id, Household.type == HouseholdType.RUMAH_TANGGA)
        .order_by(HouseholdMember.created_at, HouseholdMember.id)
        .limit(1)
    )).scalar_one_or_none()


async def ruang_keluarga(user, db: AsyncSession) -> UUID | None:
    return await ruang_keluarga_id(db, user.id)


async def keanggotaan_keluarga(db: AsyncSession, user_id) -> HouseholdMember | None:
    """Baris keanggotaan ruang keluarga user (untuk peran, gabung akun, keluar household)."""
    return (await db.execute(
        select(HouseholdMember)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(HouseholdMember.user_id == user_id, Household.type == HouseholdType.RUMAH_TANGGA)
        .order_by(HouseholdMember.created_at, HouseholdMember.id)
        .limit(1)
    )).scalar_one_or_none()


async def keanggotaan(db: AsyncSession, user_id, household_id) -> HouseholdMember | None:
    """Keanggotaan user di satu ruang (peran ada di `.role`), atau None."""
    if household_id is None:
        return None
    return (await db.execute(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user_id, HouseholdMember.household_id == household_id,
        ).limit(1)
    )).scalar_one_or_none()


async def _ruang_dari_header(header: str | None, user, db: AsyncSession) -> UUID | None:
    raw = (header or "").strip()
    if not raw:
        return None
    try:
        hid = UUID(raw)
    except ValueError:
        raise RuangDitolak()
    if await keanggotaan(db, user.id, hid) is None:
        raise RuangDitolak()
    return hid


_HEADER = Header(None, alias=RUANG_HEADER, description="ID ruang yang sedang dibuka (opsional; tanpa header = ruang keluarga)")


async def ruang_aktif(
    x_jatahku_ruang: str | None = _HEADER,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID | None:
    """Ruang untuk membaca: dari header bila ada (dan sah), selain itu ruang keluarga.
    None = user belum punya household; route menangani seperti sebelumnya."""
    hid = await _ruang_dari_header(x_jatahku_ruang, user, db)
    return hid if hid is not None else await ruang_keluarga_id(db, user.id)


async def ruang_tulis(
    x_jatahku_ruang: str | None = _HEADER,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID | None:
    """Ruang untuk menulis sampai R3: selalu ruang keluarga. Header yang menunjuk
    ruang lain ditolak, bukan diabaikan, supaya catatan tidak masuk ruang yang salah."""
    keluarga = await ruang_keluarga_id(db, user.id)
    hid = await _ruang_dari_header(x_jatahku_ruang, user, db)
    if hid is not None and hid != keluarga:
        raise RuangDitolak()
    return keluarga


# Dipakai sebagai parameter keyword-only di route (`*, hid: RuangAktif`): tanpa nilai bawaan,
# sehingga pemanggilan handler langsung (Sumber Beranda, tes) yang lupa `hid` gagal keras,
# bukan diam-diam meneruskan objek Depends sebagai id ruang.
RuangAktif = Annotated[UUID | None, Depends(ruang_aktif)]
RuangTulis = Annotated[UUID | None, Depends(ruang_tulis)]


# ── R3: ruang dari objek saat menulis ────────────────────────────────────
KODE_LINTAS = "lintas_ruang"
PESAN_LINTAS = "Catatan ini menyentuh dua ruang sekaligus. Catat terpisah di masing-masing ruang."


class LintasRuang(RuangDitolak):
    """400: satu permintaan tulis menyentuh lebih dari satu ruang (prive dua sisi menyusul di R8)."""

    def __init__(self):
        super().__init__(kode=KODE_LINTAS, detail=PESAN_LINTAS, status_code=400)


async def ruang_objek(db: AsyncSession, user, household_id) -> UUID | None:
    """Ruang objek yang ditulis, hanya bila user anggota ruang itu. None = bukan milik user;
    route menjawab seperti objek tidak ada (404), supaya keberadaan objek tidak bocor."""
    if household_id is None or await keanggotaan(db, user.id, household_id) is None:
        return None
    return household_id


async def ruang_amplop(db: AsyncSession, user, envelope_id) -> UUID | None:
    """Ruang amplop `envelope_id` bila user anggotanya (lihat `ruang_objek`)."""
    from app.models.models import Envelope
    if envelope_id is None:
        return None
    hid = (await db.execute(select(Envelope.household_id).where(Envelope.id == envelope_id))).scalar_one_or_none()
    return await ruang_objek(db, user, hid)


async def ruang_amplop_satu(db: AsyncSession, user, envelope_ids) -> UUID | None:
    """Satu ruang untuk sekumpulan amplop dalam satu permintaan tulis (transfer, alokasi pemasukan).
    Amplop di ruang yang bukan milik user diabaikan di sini (route menjawab 404 untuknya, tanpa
    membocorkan ruang lain); amplop milik user di lebih dari satu ruang → `LintasRuang` (400)."""
    from app.models.models import Envelope
    ids = [e for e in envelope_ids if e is not None]
    if not ids:
        return None
    ruang_ids = set((await db.execute(
        select(Envelope.household_id).where(Envelope.id.in_(ids)).distinct()
    )).scalars())
    milik = set()
    for hid in ruang_ids:
        if await keanggotaan(db, user.id, hid) is not None:
            milik.add(hid)
    if len(milik) > 1:
        raise LintasRuang()
    return next(iter(milik), None)


async def ruang_jenis(db: AsyncSession, household_id) -> str | None:
    """`households.type` untuk aturan per ruang (mis. kuota Basic hanya di ruang keluarga, ADR-P13)."""
    if household_id is None:
        return None
    return (await db.execute(select(Household.type).where(Household.id == household_id))).scalar_one_or_none()
