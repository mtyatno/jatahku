"""Siklus anggaran milik household (spec 2026-10-31-siklus-household, bagian 2).

`households.payday_day` adalah sumber kebenaran tanggal gajian semua anggota (owner yang memutuskan);
`users.payday_day` hanya cermin. NULL pada kolom household berarti "belum dimigrasi": nilainya diturunkan
dari anggota saat pertama dibaca (`household_payday`).

Ruang keluarga vs ruang usaha (Plugin R1, spec bagian 10): `users.payday_day` adalah cermin siklus RUANG KELUARGA
user (household `rumah_tangga`; satu user paling banyak punya satu). Ruang usaha (`usaha`) punya siklusnya sendiri di
`households.payday_day` dan tidak pernah dicerminkan ke user. `mirrors_users` memutuskannya: `set_household_payday`
dan `heal` mengikutinya; join web/bot hanya menerima undangan ruang keluarga (Plugin R2), jadi `adopt_household_payday`
hanya pernah dipanggil untuk ruang keluarga. Keanggotaan dibaca lewat resolver ruang (`app/services/ruang.py`, Plugin
R2): `membership` = `ruang.keanggotaan_keluarga`, jadi `payday_context` untuk profil selalu bekerja pada ruang
keluarga, dan `payday_context(..., household_id=…)` (recompute, ruang tulis R2) pada household yang diminta.

Aturan: atribut `payday_day` (user maupun household) hanya di-assign di modul ini, dan SQL pengisinya hanya di
`household_cycle_schema.py`. Jalur lain membaca lewat `household_payday` / `payday_context` dan mengubah lewat
service ini, supaya cermin tidak menyimpang.

Fungsi yang menerima `db: AsyncSession` tidak `commit` sendiri; pemanggil yang commit (pola repo). Ada dua
pengecualian: `heal`, yang dipanggil job harian tanpa pemanggil lain yang menyimpan, dan `set_household_payday`,
yang harus menyimpan perubahan sebelum recompute karena recompute membaca lewat sesi sendiri. `recompute_history`
dan job harian membaca tanggal lewat sesi sendiri yang HANYA-BACA (`current_payday`: tidak assign, flush, maupun
commit; None bila household-nya sudah dihapus), jadi pemanggil yang baru mengubah atau mengisi
`households.payday_day` di sesinya harus commit dulu. Yang memakai sesi sendiri dan commit di sana:
`notification_service.kirim`, dan recompute itu sendiri: `rollover.recompute_household` (membuang kunci periode
berjalan) dan `rollover.create_monthly_snapshots` (satu sesi per periode yang dibangun ulang).

Mengubah tanggal (`set_household_payday`): validasi, no-op bila sama, lalu household dan (untuk ruang keluarga) cermin
semua anggota dalam satu transaksi (commit), `advisor_cache.invalidate`, `recompute_history` (diserialkan per
household, tanggal dibaca di dalam kunci, riwayat mundur sampai aktivitas pertama household), dan notifikasi ke anggota
lain dengan jumlah periode yang benar-benar dihitung ulang. Gagal kirim notifikasi dan gagal recompute dicatat dan
tidak membatalkan perubahan yang sudah di-commit.

Kunci per household itu publik (`household_lock`): `recompute_history`, job snapshot harian
(`scheduler.payday_snapshot_job`), dan `POST /snapshots/run` sama-sama memegangnya, karena semuanya menulis kunci
snapshot yang sama. Semuanya membaca tanggal gajian (`current_payday`) SETELAH memegang kunci, bukan sebelumnya: tanggal
yang dibaca di luar kunci bisa basi saat gilirannya tiba, dan jendela basi menulis kunci periode berjalan yang baru
dibuang recompute.
"""
import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.models import Household, HouseholdMember, HouseholdRole, HouseholdType, NotificationType, User
from app.services import notification_service, rollover, ruang
from app.services.advisor import advisor_cache

logger = logging.getLogger("jatahku.household_cycle")

# Periode tertutup yang diminta dihitung ulang saat tanggal gajian household berubah (spec keputusan 7). Ini batas
# BAWAH: `rollover.recompute_household` selalu mundur sampai periode sebelum aktivitas pertama household (dibatasi
# `rollover.MAX_RECOMPUTE_PERIODS`), jadi riwayat yang lebih panjang tetap terhitung ulang seluruhnya.
RECOMPUTE_PERIODS_ON_CHANGE = 12

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
    """Satu titik baca siklus untuk route profil (`GET`/`PUT /user/profile`) dan `POST /snapshots/recompute`.
    (`GET /household/` tidak memakainya: route itu memakai `_get_membership` + `household_payday`.)"""
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
    """Keanggotaan `user` di ruang keluarganya (household `rumah_tangga`), atau None.

    Satu definisi untuk seluruh aplikasi: diteruskan ke resolver ruang (`ruang.keanggotaan_keluarga`, Plugin R2), tanpa
    kueri sendiri. Keanggotaan ruang usaha (Plugin R1: satu user boleh anggota beberapa household) tidak ikut terpilih;
    bila (tidak semestinya) ada dua ruang keluarga, keanggotaan tertua yang dipakai, tanpa galat."""
    return await ruang.keanggotaan_keluarga(db, user.id)


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


def mirrors_users(household) -> bool:
    """Apakah siklus `household` dicerminkan ke `users.payday_day` anggotanya: hanya ruang keluarga (spec bagian 10).

    Ruang usaha punya siklusnya sendiri di `households.payday_day`; cermin user tetap milik ruang keluarganya.
    Murni (tanpa IO). Objek yang `type`-nya kosong atau tidak ada (stub tes lama, atau `Household` yang belum di-flush
    sehingga bawaan kolomnya belum terisi) dihitung ruang keluarga, sama dengan bawaan kolom."""
    return str(getattr(household, "type", None) or HouseholdType.RUMAH_TANGGA) == HouseholdType.RUMAH_TANGGA


USAHA_PAYDAY = 1  # ruang usaha: periode bulan kalender (desain A2 butir 9)


def init_ruang_usaha(household) -> None:
    """Siklus ruang usaha baru (Plugin R4): bulan kalender, bukan tanggal gajian pemiliknya. Diisi saat dibuat,
    supaya `household_payday` tidak menurunkannya dari `users.payday_day` owner (cermin ruang keluarga)."""
    household.payday_day = USAHA_PAYDAY


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


async def payday_context(db: AsyncSession, user, *, household_id=None) -> PaydayContext | None:
    """Konteks siklus satu household untuk `user` (peran, izin ubah, tanggal), atau None bila `user` bukan anggotanya.

    Tanpa `household_id`: ruang keluarga user (`membership`; keanggotaan ruang usaha tidak dihitung). Profil memakainya,
    karena cermin `users.payday_day` hanya milik ruang keluarga, apa pun ruang yang sedang dibuka. Dengan
    `household_id`: keanggotaan user di household itu (`ruang.keanggotaan`), tanpa jatuh ke ruang lain.
    `POST /snapshots/recompute` memakainya untuk ruang tulis R2, jadi izin dihitung untuk household yang dihitung ulang.

    Tiga kueri berurutan (keanggotaan, household, anggota); tanggal diturunkan dari baris anggota yang sama,
    tanpa kueri tambahan."""
    if household_id is None:
        member = await membership(db, user)
    else:
        member = await ruang.keanggotaan(db, user.id, household_id)
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

    Dipanggil join web dan bot sebelum commit keanggotaan baru, dalam transaksi yang sama, dan hanya untuk ruang
    keluarga: keduanya menolak undangan ke household selain `rumah_tangga` sebelum mengubah apa pun (Plugin R2). Fungsi
    ini sendiri tidak memeriksa tipe. Cermin `users.payday_day` bukan milik ruang usaha, jadi jalur yang kelak
    memasukkan user ke ruang usaha (R5) membaca tanggalnya lewat `household_payday` dan tidak memanggil fungsi ini.
    Tidak commit."""
    day = await household_payday(db, household)
    user.payday_day = day
    return day


async def _member_users(db: AsyncSession, household) -> Sequence[User]:
    """`User` semua anggota household dalam satu kueri; dipakai `heal` dan `set_household_payday`, yang meng-assign
    cermin `payday_day` pada objek-objek ini."""
    result = await db.execute(
        select(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == household.id)
    )
    return result.scalars().all()


async def heal(db: AsyncSession, household) -> list[User]:
    """Samakan `users.payday_day` anggota yang menyimpang dari `households.payday_day`.

    Ruang usaha dilewati tanpa kueri apa pun (`mirrors_users`): cermin anggota adalah siklus ruang keluarga mereka,
    jadi selisihnya dengan tanggal ruang usaha memang benar. Household yang belum punya tanggal juga dilewati (belum
    dimigrasi). Tiap anggota yang diperbaiki dicatat sebagai warning, `commit` hanya bila ada yang berubah, dan user
    yang diperbaiki dikembalikan (skrip migrasi memberi tahu mereka). Tidak menghitung ulang riwayat: penyimpangan
    hanya bisa datang dari jalur yang lupa memakai service ini, dan job harian menghitung snapshot dengan tanggal
    household."""
    if not mirrors_users(household):
        return []
    target = household.payday_day
    if target is None:
        return []
    users = await _member_users(db, household)
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


# ── mengubah tanggal gajian ─────────────────────────────────────────────────
# Satu kunci per household, dipegang semua penulis kunci snapshot `(envelope_id, year, month)` di proses ini:
# `recompute_history`, job harian `scheduler.payday_snapshot_job`, dan `POST /snapshots/run`. Kunci dalam proses sudah
# cukup: app berjalan sebagai satu proses uvicorn, scheduler di dalam proses yang sama (spec, penyesuaian 2). Dict ini
# tumbuh satu entri per household yang pernah di-recompute atau di-snapshot (kecil, dibiarkan). `asyncio.Lock` terikat
# ke event loop tempat ia pertama kali diperebutkan, jadi tes yang berebut kunci memakai id household baru per tes.
_locks: dict[uuid.UUID, asyncio.Lock] = {}


def household_lock(household_id) -> asyncio.Lock:
    """Kunci snapshot milik household ini (satu per household); dibuat saat pertama diminta. Pemakaian:
    `async with household_lock(hid):`. Pemegangnya tidak berjalan bersamaan dengan pemegang lain pada household yang
    sama: `recompute_history`, job snapshot harian, dan `POST /snapshots/run`.

    Recompute menghapus lalu menyisipkan ulang kunci snapshot yang juga ditulis job harian, dan kunci unik
    `(envelope_id, year, month)` bisa bertabrakan bila keduanya berjalan sekaligus. Tidak re-entrant: pemegang tidak
    boleh meminta kunci household yang sama lagi (para pemegangnya tidak saling memanggil)."""
    lock = _locks.get(household_id)
    if lock is None:
        lock = _locks[household_id] = asyncio.Lock()
    return lock


async def current_payday(household_id) -> int | None:
    """Tanggal gajian household yang paling baru di DB, dibaca lewat sesi sendiri, atau None bila household-nya sudah
    tidak ada (dihapus lewat merge atau penghapusan akun). HANYA-BACA.

    Sesi pemanggil bisa memegang household versi lama (sesi tidak kedaluwarsa saat commit), padahal perubahan lain
    mungkin sudah tersimpan. NULL (belum dimigrasi) diturunkan dari anggota dengan `pick_payday`, tanpa menulis
    apa pun: mengisinya lewat koneksi kedua ini bisa menunggu selamanya pada kunci baris yang dipegang transaksi
    pemanggil (yang sudah `flush` pengisian yang sama lewat `household_payday` dan belum commit), padahal kunci
    recompute sedang dipegang.

    Pemakainya (`recompute_history`, job snapshot harian, `POST /snapshots/run`) membacanya SETELAH memegang
    `household_lock`. Perubahan tanggal yang sudah di-commit saat kunci dipegang pasti terbaca (`set_household_payday`
    commit sebelum recompute-nya meminta kunci), dan yang di-commit sesudahnya diikuti recompute-nya sendiri yang
    menunggu kunci ini. Jadi jendela snapshot tidak pernah lebih tua dari recompute terakhir yang sudah selesai."""
    async with AsyncSessionLocal() as db:
        household = (await db.execute(
            select(Household).where(Household.id == household_id)
        )).scalar_one_or_none()
        if household is None:
            return None
        if household.payday_day is not None:
            return household.payday_day
        return pick_payday(await member_rows(db, household_id))


async def recompute_history(household_id, periods: int) -> list[dict]:
    """Hitung ulang riwayat snapshot household, satu recompute pada satu waktu dan tidak bersamaan dengan job snapshot
    harian household yang sama (kunci yang sama: `household_lock`). `periods` adalah batas bawah: recompute mundur
    sampai periode sebelum aktivitas pertama household (`rollover.recompute_household`), jadi panjang hasilnya bisa
    lebih dari `periods`.

    Dua perubahan tanggal beruntun (mengetik "2" lalu "25") bisa menjalankan dua recompute bersamaan dengan jendela
    berbeda, dan yang selesai terakhir menang, belum tentu tanggal terakhir. Maka tanggal dibaca DI DALAM kunci:
    yang menunggu kunci memakai tanggal yang tersimpan setelah recompute di depannya selesai.

    Tanggal dibaca lewat sesi lain dan hanya-baca (`current_payday`): pemanggil yang baru mengubah atau mengisi
    `households.payday_day` di sesinya sendiri harus commit sebelum memanggil ini, kalau tidak yang terbaca nilai
    lama (atau, bila NULL, yang diturunkan dari anggota). Household yang sudah tidak ada (dihapus lewat merge atau
    penghapusan akun) tidak dihitung: hasilnya `[]` dan satu peringatan, bukan error.

    Mengembalikan satu dict per periode (bentuk `rollover.recompute_household`). Error per amplop di dalam periode
    dicatat sebagai error log dan tidak membatalkan apa pun: daftar penuh tetap dikembalikan, pemanggil memutuskan."""
    async with household_lock(household_id):
        payday = await current_payday(household_id)
        if payday is None:
            logger.warning("recompute household %s dilewati: household sudah tidak ada", household_id)
            return []
        results = await rollover.recompute_household(household_id, payday, periods)
    for period in results:
        if period.get("errors"):
            logger.error(
                "recompute household %s periode %s punya error: %s",
                household_id, period.get("period"), period["errors"],
            )
    return results


async def notify_payday_changed(
    users, *, household_name: str, day: int, changed_by: str | None, periods: int, history_recomputed: bool = True
) -> int:
    """Beri tahu `users` bahwa siklus anggaran rumah mereka berubah; mengembalikan jumlah yang berhasil dikirimi.

    `changed_by` terisi (nama yang mengubah) → pesan perubahan oleh owner; None → pesan skrip migrasi, yang tidak
    punya pelaku. `periods` = jumlah periode yang BENAR-BENAR dihitung ulang (panjang hasil `recompute_history`, yang
    bisa lebih dari yang diminta). Kalimat "Riwayat {periods} periode terakhir dihitung ulang." hanya ada bila
    `history_recomputed` (False: recompute gagal, dipakai `set_household_payday`) dan `periods > 0` (0: household sudah
    tidak ada saat recompute), di kedua varian, supaya pesan tidak mengklaim yang tidak terjadi. Judul dan pesan tidak
    dikirim sebagai `telegram_html`: `kirim` yang meng-escape, jadi nama rumah atau orang yang berisi `<` atau `&` aman.
    Tiap kirim dibungkus tersendiri: yang gagal dicatat dan tidak menghentikan yang lain, apalagi membatalkan perubahan
    tanggalnya."""
    if changed_by:
        message = f"Tanggal gajian {household_name} kini tanggal {day} (diubah {changed_by})."
    else:
        message = f"Siklus anggaranmu kini mengikuti {household_name}: tanggal {day}."
    if history_recomputed and periods > 0:
        message += f" Riwayat {periods} periode terakhir dihitung ulang."
    sent = 0
    for user in users:
        try:
            await notification_service.kirim(
                user, NotificationType.system, "Siklus anggaran rumah berubah", message, link="/settings"
            )
            sent += 1
        except Exception:
            logger.error("notifikasi perubahan siklus ke %s gagal", user.id, exc_info=True)
    return sent


async def set_household_payday(db: AsyncSession, household, day: int, *, actor) -> dict:
    """Ubah tanggal gajian household atas nama `actor` (spec bagian 2). Izin dicek route, bukan di sini.

    `ValueError` bila `day` di luar 1–31 (route: 400); tanggal yang sama dengan sekarang → `{"changed": False}`
    tanpa recompute dan tanpa notifikasi. Selain itu household dan, untuk ruang keluarga (`mirrors_users`), cermin
    semua anggota di-assign dalam satu transaksi lalu di-commit (recompute membaca lewat sesi lain, jadi perubahan
    harus sudah tersimpan), cache advisor household dihapus, riwayat dihitung ulang (minimal
    `RECOMPUTE_PERIODS_ON_CHANGE` periode, mundur sampai aktivitas pertama household), dan anggota selain `actor`
    diberi tahu dengan jumlah periode yang dihitung ulang. Ruang usaha menempuh langkah yang sama kecuali cermin:
    `users.payday_day` anggotanya tidak disentuh (itu siklus ruang keluarga mereka), dan `members` tetap menghitung
    anggota ruang itu. Hasil: `{"changed": True, "members": n, "recomputed": k}` (k = periode yang dihitung ulang).

    Recompute yang gagal (exception; error per amplop hanya dicatat oleh `recompute_history`) tidak membatalkan
    perubahan yang sudah di-commit dan tidak membuat pemanggil gagal: dicatat dengan `logger.exception`, hasilnya
    `recomputed: 0`, dan anggota tetap diberi tahu, tanpa klaim bahwa riwayat dihitung ulang. Riwayat bisa
    tertinggal separuh jadi. Mengulang tanggal yang sama tidak memperbaikinya (no-op); pemulihannya dijalankan
    operator: skrip migrasi (`--apply`) atau endpoint `POST /snapshots/recompute`."""
    if not 1 <= day <= 31:
        raise ValueError("payday_day harus antara 1 dan 31")
    if day == await household_payday(db, household):
        return {"changed": False}

    members = await _member_users(db, household)
    household.payday_day = day
    if mirrors_users(household):
        for user in members:
            user.payday_day = day
    await db.commit()

    await advisor_cache.invalidate(household.id)
    try:
        results = await recompute_history(household.id, RECOMPUTE_PERIODS_ON_CHANGE)
        history_recomputed = True
    except Exception:
        logger.exception("recompute riwayat household %s (payday %s) gagal", household.id, day)
        results, history_recomputed = [], False
    await notify_payday_changed(
        [user for user in members if user.id != actor.id],
        household_name=household.name,
        day=day,
        changed_by=actor.name,
        periods=len(results),
        history_recomputed=history_recomputed,
    )
    return {"changed": True, "members": len(members), "recomputed": len(results)}
