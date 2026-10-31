"""Siklus anggaran milik household (spec 2026-10-31-siklus-household, bagian 2).

`households.payday_day` adalah sumber kebenaran tanggal gajian semua anggota (owner yang memutuskan);
`users.payday_day` hanya cermin. NULL pada kolom household berarti "belum dimigrasi": nilainya diturunkan
dari anggota saat pertama dibaca (`household_payday`).

Aturan: atribut `payday_day` (user maupun household) hanya di-assign di modul ini, dan SQL pengisinya hanya di
`household_cycle_schema.py`. Jalur lain membaca lewat `household_payday` / `payday_context` dan mengubah lewat
service ini, supaya cermin tidak menyimpang.

Semua fungsi menerima `db: AsyncSession` dan tidak `commit` sendiri; pemanggil yang commit (pola repo). Satu-satunya
pengecualian adalah `heal`, yang dipanggil job harian tanpa pemanggil lain yang menyimpan.
"""
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Household, HouseholdMember, HouseholdRole, User

logger = logging.getLogger("jatahku.household_cycle")

# Peringkat siapa yang menentukan siklus saat household belum punya tanggal: owner, lalu admin, lalu yang lain.
# Urutan yang sama dengan backfill SQL di household_cycle_schema.py.
_ROLE_RANK = {"owner": 0, "admin": 1}
_OTHER_RANK = 2


@dataclass(frozen=True)
class MemberRow:
    """Satu anggota household beserta tanggal gajian cermin-nya; dasar `pick_payday` dan `PaydayContext`."""
    user_id: uuid.UUID
    name: str
    role: HouseholdRole | str
    created_at: datetime
    payday_day: int


@dataclass
class PaydayContext:
    """Satu titik baca siklus untuk route profil, recompute, dan household."""
    household: Household
    role: HouseholdRole | str
    payday_day: int
    member_count: int
    can_change: bool
    owner_name: str | None  # None bila pemanggil sendiri owner-nya, atau household tanpa owner


def _role_value(role) -> str:
    """Enum maupun string jadi string (AGENTS.md: `HouseholdRole.member != "member"`)."""
    return str(getattr(role, "value", role))


async def membership(db: AsyncSession, user) -> HouseholdMember | None:
    """Keanggotaan household milik `user`, atau None.

    Satu-satunya kueri keanggotaan di modul ini: kelak diganti resolver ruang aktif (spec bagian 10)
    cukup dengan mengubah fungsi ini.
    """
    result = await db.execute(select(HouseholdMember).where(HouseholdMember.user_id == user.id))
    return result.scalar_one_or_none()


async def member_rows(db: AsyncSession, household_id) -> list[MemberRow]:
    """Semua anggota household dalam satu kueri."""
    result = await db.execute(
        select(HouseholdMember.role, HouseholdMember.created_at, User.id, User.name, User.payday_day)
        .join(User, User.id == HouseholdMember.user_id)
        .where(HouseholdMember.household_id == household_id)
    )
    return [
        MemberRow(user_id=user_id, name=name, role=role, created_at=created_at, payday_day=payday_day)
        for role, created_at, user_id, name, payday_day in result.all()
    ]


def pick_payday(rows: Sequence[MemberRow]) -> int:
    """Tanggal gajian anggota yang paling berhak: owner, lalu admin, lalu yang lain; sesama peran yang
    `created_at`-nya tertua. Tanggal kosong (None/0) milik anggota itu dianggap 1; tanpa anggota → 1.
    Murni (tanpa IO): dipakai `household_payday` dan dry-run skrip migrasi."""
    if not rows:
        return 1
    chosen = min(rows, key=lambda r: (_ROLE_RANK.get(_role_value(r.role), _OTHER_RANK), r.created_at))
    return chosen.payday_day or 1


def can_change_payday(role, member_count: int) -> bool:
    """Owner dan admin boleh mengubah; member hanya bila sendirian di household-nya. Peran lain tidak pernah."""
    value = _role_value(role)
    if value in ("owner", "admin"):
        return True
    return value == "member" and member_count == 1


async def household_payday(db: AsyncSession, household, rows: list[MemberRow] | None = None) -> int:
    """Tanggal gajian household.

    Terisi → dikembalikan apa adanya (tanpa kueri). NULL → diturunkan dari `rows` (atau `member_rows` bila
    tidak diberikan) lewat `pick_payday`, ditulis ke `household.payday_day`, lalu `flush`. Boleh dipanggil dari
    handler GET: bila sesinya tidak di-commit, nilai di respons tetap benar dan job harian yang menyimpannya.
    """
    if household.payday_day is not None:
        return household.payday_day
    if rows is None:
        rows = await member_rows(db, household.id)
    day = pick_payday(rows)
    household.payday_day = day
    await db.flush()
    return day


async def payday_context(db: AsyncSession, user) -> PaydayContext | None:
    """Konteks siklus untuk `user`, atau None bila belum punya keanggotaan.

    Tiga kueri berurutan (keanggotaan, household, anggota); tanggal diturunkan dari baris anggota yang sama,
    tanpa kueri tambahan."""
    member = await membership(db, user)
    if member is None:
        return None
    household = (await db.execute(
        select(Household).where(Household.id == member.household_id)
    )).scalar_one()
    rows = await member_rows(db, household.id)
    payday = await household_payday(db, household, rows)
    owner = next((r for r in rows if _role_value(r.role) == "owner"), None)
    return PaydayContext(
        household=household,
        role=member.role,
        payday_day=payday,
        member_count=len(rows),
        can_change=can_change_payday(member.role, len(rows)),
        owner_name=owner.name if owner is not None and owner.user_id != user.id else None,
    )


async def adopt_household_payday(db: AsyncSession, user, household) -> int:
    """Samakan `user` dengan siklus household yang akan dimasukinya; mengembalikan tanggalnya.

    Dipanggil join web dan bot sebelum commit keanggotaan baru, dalam transaksi yang sama. Tidak commit."""
    day = await household_payday(db, household)
    user.payday_day = day
    return day


async def heal(db: AsyncSession, household) -> list[User]:
    """Samakan `users.payday_day` anggota yang menyimpang dari `households.payday_day`.

    Household yang belum punya tanggal dilewati (belum dimigrasi). Tiap anggota yang diperbaiki dicatat sebagai
    warning, `commit` hanya bila ada yang berubah, dan user yang diperbaiki dikembalikan (skrip migrasi memberi
    tahu mereka). Tidak menghitung ulang riwayat: penyimpangan hanya bisa datang dari jalur yang lupa memakai
    service ini, dan job harian menghitung snapshot dengan tanggal household."""
    target = household.payday_day
    if target is None:
        return []
    users = (await db.execute(
        select(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == household.id)
    )).scalars().all()
    fixed: list[User] = []
    for user in users:
        if user.payday_day != target:
            old = user.payday_day
            user.payday_day = target
            logger.warning("payday anggota %s menyimpang (%s → %s)", user.id, old, target)
            fixed.append(user)
    if fixed:
        await db.commit()
    return fixed
