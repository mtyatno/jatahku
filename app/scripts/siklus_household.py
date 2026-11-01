"""Siklus household: migrasi data sekali jalan (spec 2026-10-31-siklus-household, bagian 7).

Dijalankan admin di VPS sesudah deploy dan `alembic upgrade head`; lihat dulu dengan --dry-run, baru --apply:

    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household --dry-run
    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.siklus_household --apply

--dry-run (bawaan: tanpa opsi apa pun = dry-run) mencetak satu baris per household yang punya anggota: id, nama,
jumlah anggota, payday tiap anggota, payday household yang akan dipakai, dan tanda CAMPURAN bila anggota ruang keluarga
punya payday berbeda. Ruang usaha ditandai [usaha] dan tidak pernah CAMPURAN: payday pribadi anggotanya memang boleh
berbeda (itu siklus ruang keluarga mereka). Tidak menulis apa pun.

--apply, per household: mengisi payday household yang masih kosong, menyimpan, menghitung ulang riwayat snapshot
(minimal --periods periode terakhir, bawaan 12, dan selalu mundur sampai aktivitas pertama household; mengisi kolom
allocated/spent), menyamakan payday anggota ruang keluarga dengannya, lalu memberi tahu (lonceng web, dan Telegram bila
tertaut) anggota yang payday-nya berubah. Aman diulang: dijalankan ulang, hasilnya sama dan tidak ada notifikasi kedua,
karena tidak ada anggota yang berubah lagi. --apply menulis ulang snapshot semua household dengan force: cadangkan
tabel monthly_snapshots dulu (perintahnya di AGENTS.md, checklist siklus household).

Jalankan (dry-run lalu --apply) pada hari yang sama dengan merge, SEBELUM job snapshot harian pukul 00:05 (waktu
server) berikutnya: job itu menyamakan anggota yang menyimpang tanpa notifikasi, jadi bila ia jalan lebih dulu, --apply
tidak menemukan siapa pun untuk diberi tahu. Pilih jam sepi yang tidak di sekitar 00:05.
Skrip ini berjalan di proses terpisah, jadi kunci per household milik aplikasi (`household_lock`) hanya berlaku di
dalam proses uvicorn dan tidak menyerialkannya dengan web maupun job itu. Recompute menghapus lalu menyisipkan ulang
kunci snapshot yang juga ditulis job harian; bila berjalan bersamaan, keduanya bisa bertabrakan di kunci unik
(envelope_id, year, month).

Kode keluar 0 bila selesai tanpa error. Error per amplop di dalam recompute tidak menghentikan run: jumlahnya dicetak di
baris terakhir, rinciannya di log `jatahku.household_cycle` ("punya error"), dan kode keluarnya 1. Kegagalan lain
(database, recompute) tidak ditangkap: traceback dan kode keluar 1. Household yang sudah diproses tersimpan, dan run
yang gagal cukup dijalankan ulang: --apply berikutnya melanjutkannya, termasuk menyamakan dan memberi tahu anggota
household yang gagal.
Konfigurasi dibaca dari /opt/jatahku/.env seperti aplikasinya; skrip ini tidak mengarang nilai bawaan.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.models import Household
    from app.services.household_cycle import MemberRow

# Modul aplikasi (model, service, database) diimpor di dalam fungsi, bukan di atas: `app.core.database` memuat
# konfigurasi server saat diimpor, jadi `--help` dan argumen yang salah akan jatuh tanpa DATABASE_URL. Skrip ini juga
# TIDAK boleh mengarang nilai bawaan seperti kotak_corpus.py (`os.environ.setdefault`): `Settings` memberi prioritas
# pada variabel lingkungan di atas /opt/jatahku/.env, jadi nilai karangan akan menimpa DATABASE_URL asli di VPS.

# Spec bagian 7. Sama dengan `household_cycle.RECOMPUTE_PERIODS_ON_CHANGE` (batas bawah: recompute selalu mundur sampai
# aktivitas pertama household); ditulis di sini supaya `--help` tidak mengimpor service itu (lihat catatan di atas).
DEFAULT_PERIODS = 12


@dataclass
class HouseholdSurvey:
    """Satu household yang punya anggota, dibaca tanpa menulis apa pun (`survey`)."""
    household: Household
    members: list[MemberRow]
    target_payday: int  # payday household yang tersimpan, atau (bila NULL) yang akan diisi dari anggota
    mixed: bool  # anggota ruang keluarga punya payday berbeda; ruang usaha tidak pernah


async def survey(db: AsyncSession) -> list[HouseholdSurvey]:
    """Household yang punya anggota (yang kosong dilewati, seperti job harian), yang tertua dulu, beserta anggotanya.

    TIDAK menulis apa pun: payday household yang masih NULL tidak diisi (itu pekerjaan `apply`), hanya dihitung sebagai
    `target_payday`. `mixed` hanya dihitung untuk ruang keluarga (`mirrors_users`, spec bagian 10): anggota ruang usaha
    memang boleh punya payday pribadi berbeda, dan `heal` melewatinya."""
    from app.models.models import Household, HouseholdMember
    from app.services.household_cycle import member_rows, mirrors_users, pick_payday

    households = (await db.execute(
        select(Household)
        .where(Household.id.in_(select(HouseholdMember.household_id)))
        .order_by(Household.created_at, Household.id)
    )).scalars().all()
    surveys = []
    for household in households:
        members = await member_rows(db, household.id)
        surveys.append(HouseholdSurvey(
            household=household,
            members=members,
            target_payday=household.payday_day or pick_payday(members),
            mixed=mirrors_users(household) and len({m.payday_day for m in members}) > 1,
        ))
    return surveys


def _clean(value) -> str:
    """Teks yang diketik user (nama rumah, nama anggota) untuk dicetak: kode kontrol dan pemisah baris jadi spasi, spasi
    beruntun dirapatkan. Satu household harus tetap satu baris, dan escape terminal di sebuah nama tidak boleh sampai
    ke terminal admin."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(value)).split())


def format_survey(surveys: list[HouseholdSurvey]) -> str:
    """Satu baris per household (id, nama, jumlah anggota, payday tiap anggota, target, CAMPURAN bila campuran), lalu
    baris ringkas `"{n} household, {k} campuran"`. Ruang usaha diberi tanda `[usaha]` supaya tidak adanya CAMPURAN pada
    anggota yang payday-nya berbeda tidak membingungkan."""
    from app.services.household_cycle import mirrors_users

    lines = []
    for item in surveys:
        home = item.household
        kind = "" if mirrors_users(home) else f" [{_clean(home.type)}]"
        # `str(HouseholdRole.owner)` adalah "HouseholdRole.owner" (AGENTS.md: enum vs string): yang dicetak nilainya.
        paydays = ", ".join(
            f"{_clean(m.name)} ({getattr(m.role, 'value', m.role)})={m.payday_day}" for m in item.members
        )
        line = (
            f"{home.id}  {_clean(home.name)}{kind}  {len(item.members)} anggota  "
            f"payday anggota: {paydays}  target {item.target_payday}"
        )
        if item.mixed:
            line += "  CAMPURAN"
        lines.append(line)
    lines.append(f"{len(surveys)} household, {sum(1 for item in surveys if item.mixed)} campuran")
    return "\n".join(lines)


async def apply(db: AsyncSession, surveys: list[HouseholdSurvey], periods: int) -> dict:
    """Terapkan migrasi per household: isi payday (`household_payday`), simpan, hitung ulang riwayat
    (`recompute_history`, minimal `periods` periode dan mundur sampai aktivitas pertama, untuk SEMUA household: mengisi
    allocated/spent; angka household yang tidak campuran hanya berubah bila periode tertutupnya diubah setelah
    snapshot-nya dibuat), samakan anggota (`heal`), lalu beri tahu anggota yang payday-nya berubah (tanpa pelaku: pesan
    skrip, dengan jumlah periode yang benar-benar dihitung ulang). Mengembalikan `{"households", "mixed", "snapshots",
    "notified", "errors"}`; `errors` = jumlah error per amplop di semua periode yang dihitung ulang (`recompute_history`
    hanya mencatatnya).

    `commit` di sini, untuk tiap household dan sebelum recompute (kontrak di docstring `household_cycle`):
    `recompute_history` membaca payday lewat sesinya sendiri, sedangkan `household_payday` hanya `flush` pengisian NULL.

    `heal` dan notifikasi SESUDAH recompute: recompute hanya membaca `households.payday_day` (yang sudah terisi dan
    tersimpan), tidak pernah cermin `users.payday_day` anggota, jadi urutan ini tidak mengubah hasilnya. Recompute yang
    gagal (exception) menghentikan semuanya sebelum anggota disamakan, jadi `heal` run berikutnya masih menemukan
    mereka dan memberi tahu mereka; `heal` yang jalan lebih dulu akan menyamakan mereka dan membuat run ulang tidak
    menemukan siapa pun untuk diberi tahu. Pesan "Riwayat ... dihitung ulang" juga benar saat dikirim. Yang sudah
    di-commit tetap tersimpan. Aman diulang: run kedua tidak menemukan anggota yang berubah, jadi tidak ada notifikasi
    kedua."""
    from app.services.household_cycle import heal, household_payday, notify_payday_changed, recompute_history

    snapshots = notified = errors = 0
    for item in surveys:
        household = item.household
        payday = await household_payday(db, household, item.members)
        await db.commit()
        results = await recompute_history(household.id, periods)
        snapshots += sum(period["snapshots_created"] for period in results)
        errors += sum(len(period["errors"]) for period in results)
        changed = await heal(db, household)
        if changed:
            notified += await notify_payday_changed(
                changed, household_name=household.name, day=payday, changed_by=None, periods=len(results),
            )
    return {
        "households": len(surveys),
        "mixed": sum(1 for item in surveys if item.mixed),
        "snapshots": snapshots,
        "notified": notified,
        "errors": errors,
    }


def _positive_int(text: str) -> int:
    """`--periods`: bilangan bulat 1 atau lebih (batas bawah recompute); 0 atau negatif ditolak argparse."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"bukan bilangan bulat: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("harus 1 atau lebih")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.siklus_household",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="(bawaan) daftar household dan rencananya, tanpa menulis apa pun",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help=(
            "per household: household_payday → commit → recompute_history → heal → notifikasi (isi payday household, "
            "simpan, hitung ulang riwayat, samakan anggota, beri tahu anggota yang berubah)"
        ),
    )
    parser.add_argument(
        "--periods", type=_positive_int, default=DEFAULT_PERIODS, metavar="N",
        help=(
            "jumlah MINIMAL periode tertutup terakhir yang dihitung ulang (bawaan %(default)s); recompute selalu "
            "mundur sampai aktivitas pertama tiap household"
        ),
    )
    return parser


async def _run(do_apply: bool, periods: int) -> int:
    from app.core.database import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as db:
            surveys = await survey(db)
            print(format_survey(surveys))
            if not do_apply:
                print("\nDry-run: tidak ada yang ditulis. Jalankan dengan --apply untuk menerapkan.")
                return 0
            summary = await apply(db, surveys, periods)
        print(
            f"\nSelesai: {summary['households']} household diproses ({summary['mixed']} campuran), "
            f"{summary['snapshots']} snapshot ditulis, {summary['notified']} anggota diberi tahu, "
            f"{summary['errors']} error."
        )
        # Error per amplop tidak melempar (hanya tercatat di log), jadi kode keluar yang memberi tahu operator.
        return 1 if summary["errors"] else 0
    finally:
        # Pool asyncpg terikat ke event loop `asyncio.run` ini: ditutup di sini, sebelum loop-nya ditutup.
        await engine.dispose()


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args.apply, args.periods))


if __name__ == "__main__":
    raise SystemExit(main())
