"""Kotak Struk: perintah sekali jalan "hari pertama" (spec 2026-11-01-kotak-belajar §12.3, opsi B).

Sebelum saklar `features.receipt_inbox` dinyalakan untuk semua user, item `siap` lama dari form Catat
(`source = 'web_form'`) dilewati dengan alasan "batal": begitu saklar menyala, item itu akan muncul di Kotak Struk
padahal user sudah lama meninggalkannya. Item dari bot Telegram, chat web, dan Bagikan (`pwa_share`) tidak disentuh,
begitu juga item `gagal` dan item dengan status lain.

Dijalankan admin di VPS TEPAT SEBELUM saklar menyala; lihat dulu tanpa opsi (dry-run), baru --apply:

    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.kotak_hari_pertama
    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.kotak_hari_pertama --apply

Tanpa opsi (bawaan) = dry-run: mencetak jumlah item per jenis bukti (`doc_type`) dan jumlah user, tidak menulis apa
pun. --apply melewati item yang sama satu per satu lewat `record.skip_item(..., "batal")` (UPDATE bersyarat
`siap → dilewati`, commit per item) lalu mencetak jumlah yang dilewati dan yang kalah balapan: item yang dicatat atau
dilewati user bersamaan tidak diubah dan hanya dihitung. Keluaran hanya berisi angka, tanpa id, nama, atau nominal.
Aman diulang: --apply kedua tidak menemukan apa pun.

--lebih-lama-dari JAM (bawaan 24, 0 = semua item siap form Catat): hanya item yang dibuat lebih dari JAM jam yang lalu.
Risiko antrean offline: simpanan form Catat yang masih menunggu di antrean HP untuk item yang dilewati akan ditolak
saat sinkron (item sudah `dilewati`) dan tetap "ditolak" di antrean; karena itu bawaannya 24 jam, item yang baru
disentuh user dibiarkan.

Kode keluar 0 bila selesai. Galat database tidak ditangkap: traceback dan kode keluar 1; item yang sudah dilewati
tetap tersimpan, dan run ulang melanjutkan sisanya.
Konfigurasi dibaca dari /opt/jatahku/.env seperti aplikasinya; skrip ini tidak mengarang nilai bawaan.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Modul aplikasi (model, service, database) diimpor di dalam fungsi, seperti siklus_household.py: `app.core.database`
# memuat konfigurasi server saat diimpor, jadi `--help` dan argumen yang salah tidak boleh membutuhkan DATABASE_URL.

DEFAULT_HOURS = 24  # pre-flight K8: simpanan form Catat yang masih di antrean offline tidak ikut ditolak
MAX_HOURS = 24 * 3650  # 10 tahun: batas waktu tetap dalam jangkauan datetime (angka raksasa ditolak argparse)
SOURCE = "web_form"
REASON = "batal"
NO_TYPE = "tanpa_jenis"  # label hitungan untuk item tanpa `doc_type` (tidak diharapkan pada item `siap`)


@dataclass
class Summary:
    """Hasil `run`: hanya angka. `skipped`/`lost` selalu 0 pada dry-run."""
    found: int = 0
    by_doc_type: dict[str, int] = field(default_factory=dict)
    users: int = 0
    skipped: int = 0
    lost: int = 0


async def candidates(
    db: AsyncSession, *, now: datetime, older_than: timedelta,
) -> list[tuple[uuid.UUID, uuid.UUID, str | None]]:
    """`(id, user_id, doc_type)` item `siap` dari form Catat yang dibuat sebelum `now - older_than`, yang tertua dulu.
    Tidak menulis apa pun."""
    from app.models.models import ReceiptScan
    from app.services.kotak_struk.config import ST_SIAP

    cutoff = _utc(now) - older_than
    rows = (await db.execute(
        select(ReceiptScan.id, ReceiptScan.user_id, ReceiptScan.doc_type)
        .where(ReceiptScan.status == ST_SIAP, ReceiptScan.source == SOURCE, ReceiptScan.created_at < cutoff)
        .order_by(ReceiptScan.created_at, ReceiptScan.id)
    )).all()
    return [(row.id, row.user_id, row.doc_type) for row in rows]


async def run(db: AsyncSession, *, now: datetime, older_than: timedelta, apply: bool) -> Summary:
    """Hitung item `candidates`; dengan `apply=True` lewati satu per satu (`record.skip_item(..., "batal")`, commit per
    item). `skip_item` yang mengembalikan False (item sudah dicatat/dilewati bersamaan, UPDATE bersyarat kalah)
    dihitung di `lost`, tidak melempar. `apply=False` tidak menulis apa pun."""
    from app.services.kotak_struk import record

    rows = await candidates(db, now=now, older_than=older_than)
    summary = Summary(
        found=len(rows),
        by_doc_type=dict(Counter(doc_type or NO_TYPE for _, _, doc_type in rows)),
        users=len({user_id for _, user_id, _ in rows}),
    )
    if not apply:
        return summary
    for item_id, user_id, _ in rows:
        if await record.skip_item(db, item_id, user_id, REASON):
            summary.skipped += 1
        else:
            summary.lost += 1
    return summary


def _utc(dt: datetime) -> datetime:
    """Tanpa zona dianggap UTC (seperti maintenance/worker)."""
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def format_summary(summary: Summary, hours: int, applied: bool) -> str:
    """Hanya angka: jumlah, per `doc_type`, jumlah user, dan (sesudah --apply) dilewati/kalah balapan."""
    lines = [f"Item siap dari form Catat lebih lama dari {hours} jam: {summary.found} ({summary.users} user)"]
    lines += [f"  {doc_type}: {count}" for doc_type, count in sorted(summary.by_doc_type.items())]
    if applied:
        lines.append(
            f"\nSelesai: {summary.skipped} dilewati (alasan \"{REASON}\"), {summary.lost} kalah balapan "
            "(dicatat atau dilewati user bersamaan, tidak diubah)."
        )
    else:
        lines.append("\nDry-run: tidak ada yang ditulis. Jalankan dengan --apply untuk melewati item ini.")
    return "\n".join(lines)


def _hours(text: str) -> int:
    """`--lebih-lama-dari`: bilangan bulat 0 sampai MAX_HOURS; di luar itu ditolak argparse."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"bukan bilangan bulat: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("harus 0 atau lebih")
    if value > MAX_HOURS:
        raise argparse.ArgumentTypeError(f"paling banyak {MAX_HOURS} (10 tahun)")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.kotak_hari_pertama",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="lewati item (record.skip_item, alasan \"batal\"); tanpa opsi ini hanya dry-run",
    )
    parser.add_argument(
        "--lebih-lama-dari", type=_hours, default=DEFAULT_HOURS, metavar="JAM",
        help="hanya item yang dibuat lebih dari JAM jam yang lalu (bawaan %(default)s; 0 = semua)",
    )
    return parser


async def _run(do_apply: bool, hours: int) -> int:
    from app.core.database import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as db:
            summary = await run(
                db, now=datetime.now(timezone.utc), older_than=timedelta(hours=hours), apply=do_apply,
            )
        print(format_summary(summary, hours, do_apply))
        return 0
    finally:
        # Pool asyncpg terikat ke event loop `asyncio.run` ini: ditutup di sini, sebelum loop-nya ditutup.
        await engine.dispose()


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args.apply, args.lebih_lama_dari))


if __name__ == "__main__":
    raise SystemExit(main())
