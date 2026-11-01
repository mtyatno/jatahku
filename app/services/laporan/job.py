"""Penerbitan laporan bulanan dan notifikasinya (spec 2026-11-01-laporan-berkala-design bagian 3 dan 6d).

`laporan_job` jalan tiap jam di menit 30 (`scheduler.start_scheduler`) dengan tanggal server, dan idempoten: untuk
setiap ruang keluarga (household `rumah_tangga`) yang punya anggota, `terbitkan_household` menerbitkan laporan periode
yang paling baru tutup untuk anggota yang belum punya, lalu setiap laporan baru diberi tahu (lonceng + Telegram) SETELAH
kunci household dilepas. Ruang usaha tidak pernah diproses; pemilihannya hanya di sini (job snapshot memproses semua
household). Kegagalan satu household dicatat dan tidak menghentikan yang lain; household itu dicoba lagi jam
berikutnya.

`terbitkan_household` seluruhnya berjalan di dalam `household_lock`, kunci yang sama dengan job snapshot harian,
`recompute_history`, dan `POST /snapshots/run`, supaya laporan tidak dibaca di tengah recompute riwayat. Tanggal gajian
dibaca SETELAH kunci didapat (`current_payday`), lalu berurutan:
1. periode yang paling baru tutup (`get_closed_periods`, sama dengan job snapshot); berhenti bila tutupnya lebih dari
   `JENDELA_TERBIT_HARI` hari lalu;
2. prasyarat: ada snapshot kunci periode itu di antara amplop household, yaitu job snapshot harian sudah memprosesnya.
   Diperiksa SEBELUM refresh (langkah 4), jadi refresh tidak pernah memenuhi prasyaratnya sendiri;
3. calon penerima: anggota yang `penerima_layak` dan belum punya laporan bulanan periode itu. Tanpa calon, atau tanpa
   transaksi dan alokasi di jendela pada amplop household mana pun (tak seorang pun bisa lolos `ada_aktivitas`),
   berhenti di sini: buku besar hanya ditulis ulang bila ada laporan yang akan dibangun, bukan tiap jam selama tujuh
   hari;
4. refresh snapshot periode itu (Ruling R4): `create_monthly_snapshots(..., force=True)` untuk household ini saja, lalu
   `advisor_cache.invalidate`. Snapshot dibekukan job harian pukul 00.05 UTC, sedangkan mutasi dan pola harian dibaca
   dari transaksi hidup; transaksi bertanggal mundur yang dicatat sesudahnya membuat Σ mutasi ≠ terpakai. Periode yang
   paling baru tutup tidak punya snapshot penerus (periode berjalan belum punya), jadi menulis ulangnya aman. Refresh
   yang melaporkan error per amplop menggagalkan household untuk jam ini (`RefreshSnapshotGagal`): laporan tidak boleh
   beku tanpa belanja satu amplop;
5. per calon `muat_bahan` → lewati bila `ada_aktivitas` False (tidak ada laporan kosong) → `Report` dengan
   `susun_bulanan`; satu commit untuk semua anggota household.
Sesi persiapan (langkah 2–3) ditutup sebelum refresh, dan pembangunan memakai sesi baru, jadi bacaannya pasti melihat
snapshot yang baru ditulis.

`kirim_notifikasi_laporan` mengirim lewat `notification_service.kirim` tanpa memegang sesi DB, lalu mengisi
`notified_at`; gagal kirim tidak membatalkan laporan yang sudah terbit. `email_status` tetap NULL di tahap 1.
"""
import html
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.period import get_closed_periods
from app.models.models import (
    JENIS_BULANAN, Allocation, Envelope, Household, HouseholdMember, HouseholdType, Income, MonthlySnapshot,
    NotificationType, Report, Transaction, User,
)
from app.services import notification_service
from app.services.advisor import advisor_cache
from app.services.household_cycle import current_payday, household_lock, member_rows
from app.services.laporan.muat import muat_bahan
from app.services.laporan.susun import ada_aktivitas, susun_bulanan
from app.services.rollover import create_monthly_snapshots

logger = logging.getLogger("jatahku.laporan")

# Laporan periode yang tutup lebih lama dari ini tidak diterbitkan lagi (server mati beberapa hari tetap terkejar).
JENDELA_TERBIT_HARI = 7
_PESAN_NOTIFIKASI = "Lihat bagaimana periode kemarin berjalan."
_AWALAN_AKUN_NONAKTIF = ("deleted_", "banned_")


class RefreshSnapshotGagal(Exception):
    """Refresh snapshot periode yang baru tutup (Ruling R4) melaporkan error per amplop; household itu dicoba lagi
    jam berikutnya."""


def _tanggal_utc(waktu: datetime) -> date:
    """Tanggal UTC sebuah waktu (asyncpg memberi datetime berzona; SQLite tanpa zona, sudah UTC)."""
    if waktu.tzinfo is not None:
        waktu = waktu.astimezone(timezone.utc)
    return waktu.date()


def penerima_layak(user, period_end: date) -> bool:
    """Apakah `user` boleh menerima laporan periode yang berakhir `period_end`: bukan akun terhapus atau diblokir
    (email berawalan `deleted_`/`banned_`; akun tanpa email tetap layak) dan akunnya dibuat paling lambat
    `period_end` menurut tanggal server (UTC), seperti tanggal tutup periode."""
    if (user.email or "").startswith(_AWALAN_AKUN_NONAKTIF):
        return False
    return _tanggal_utc(user.created_at) <= period_end


def notifikasi_laporan(judul: str, report_id, app_url: str) -> tuple[str, str, str, str]:
    """(judul notifikasi, pesan, tautan, teks Telegram HTML) untuk laporan `judul`. Tanpa nominal. Judul hanya
    di-escape di teks Telegram (parse mode HTML); lonceng menyimpan teks apa adanya. `kirim` tidak memasang tautan
    di Telegram, jadi tautan penuh ke aplikasi ada di teksnya sendiri."""
    judul_notifikasi = f"{judul} siap"
    tautan = f"/laporan/{report_id}"
    telegram = (
        f"<b>{html.escape(judul, quote=False)} siap</b>\n{_PESAN_NOTIFIKASI}\n"
        f'<a href="{app_url}/laporan/{report_id}">Buka laporan</a>'
    )
    return judul_notifikasi, _PESAN_NOTIFIKASI, tautan, telegram


async def _ada_snapshot(db, household_id, period_start: date) -> bool:
    """Ada snapshot kunci periode `period_start` untuk salah satu amplop household (aktif atau tidak)."""
    return (await db.execute(
        select(MonthlySnapshot.id)
        .join(Envelope, Envelope.id == MonthlySnapshot.envelope_id)
        .where(
            Envelope.household_id == household_id,
            MonthlySnapshot.year == period_start.year,
            MonthlySnapshot.month == period_start.month,
        )
        .limit(1)
    )).scalar() is not None


async def _calon_penerima(db, household_id, period_start: date, period_end: date) -> list:
    """`User` anggota household yang `penerima_layak` dan belum punya laporan bulanan periode `period_start`."""
    ids = [m.user_id for m in await member_rows(db, household_id)]
    if not ids:
        return []
    layak = [
        u for u in (await db.execute(
            select(User).where(User.id.in_(ids)).order_by(User.created_at, User.id)
        )).scalars().all()
        if penerima_layak(u, period_end)
    ]
    if not layak:
        return []
    sudah = set((await db.execute(
        select(Report.user_id).where(
            Report.user_id.in_([u.id for u in layak]),
            Report.jenis == JENIS_BULANAN,
            Report.periode_mulai == period_start,
        )
    )).scalars().all())
    return [u for u in layak if u.id not in sudah]


async def _rumah_beraktivitas(db, household_id, period_start: date, period_end: date) -> bool:
    """Ada transaksi tidak terhapus atau alokasi (menurut `income_date`) di jendela pada amplop household mana pun,
    aktif atau tidak, bersama atau pribadi. Syarat perlu supaya anggota mana pun lolos `ada_aktivitas`: lingkup setiap
    anggota adalah sebagian amplop ini, dan himpunannya sama dengan yang dijumlahkan `calculate_envelope_balance`."""
    amplop = select(Envelope.id).where(Envelope.household_id == household_id)
    transaksi = select(Transaction.id).where(
        Transaction.envelope_id.in_(amplop),
        Transaction.is_deleted == False,
        Transaction.transaction_date >= period_start,
        Transaction.transaction_date <= period_end,
    )
    alokasi = (
        select(Allocation.id)
        .join(Income, Allocation.income_id == Income.id)
        .where(
            Allocation.envelope_id.in_(amplop),
            Income.income_date >= period_start,
            Income.income_date <= period_end,
        )
    )
    return bool((await db.execute(select(or_(transaksi.exists(), alokasi.exists())))).scalar())


async def terbitkan_household(household_id, today: date) -> list[uuid.UUID]:
    """Terbitkan laporan bulanan periode yang paling baru tutup untuk anggota household yang belum punya; mengembalikan
    id laporan baru (kosong bila tidak ada yang terbit). Langkah dan alasannya: docstring modul. Melempar
    `RefreshSnapshotGagal` bila refresh snapshot melaporkan error per amplop; galat lain diteruskan apa adanya. Tidak
    mengirim notifikasi: pemanggil yang mengirimnya, setelah kunci household dilepas."""
    async with household_lock(household_id):
        payday = await current_payday(household_id)
        if payday is None:
            logger.warning("household=%s sudah tidak ada saat gilirannya; laporan dilewati", household_id)
            return []
        [(ps, pe)] = get_closed_periods(payday, today, 1)
        if (today - pe).days > JENDELA_TERBIT_HARI:
            return []

        async with AsyncSessionLocal() as db:
            if not await _ada_snapshot(db, household_id, ps):
                logger.debug("household=%s periode %s → %s belum punya snapshot; laporan ditunda", household_id, ps, pe)
                return []
            calon = await _calon_penerima(db, household_id, ps, pe)
            if not calon or not await _rumah_beraktivitas(db, household_id, ps, pe):
                return []
            household = (await db.execute(select(Household).where(Household.id == household_id))).scalar_one()

        hasil = await create_monthly_snapshots(ps, pe, force=True, household_ids=[household_id])
        await advisor_cache.invalidate(household_id)
        if hasil["errors"]:
            raise RefreshSnapshotGagal(f"refresh snapshot {ps} → {pe} gagal: {hasil['errors']}")

        laporan = []
        async with AsyncSessionLocal() as db:
            for user in calon:
                bahan = await muat_bahan(db, user, household, ps, pe, payday, today)
                if not ada_aktivitas(bahan):
                    continue
                report = Report(
                    id=uuid.uuid4(),  # dibuat di sini, bukan saat flush: id dikembalikan untuk notifikasi
                    user_id=user.id, household_id=household_id, jenis=JENIS_BULANAN, periode_mulai=ps,
                    periode_akhir=pe, payday_day=payday, data=susun_bulanan(bahan),
                )
                db.add(report)
                laporan.append(report)
            if laporan:
                await db.commit()
                logger.info("household=%s payday=%s periode %s → %s: %s laporan terbit",
                            household_id, payday, ps, pe, len(laporan))
        return [r.id for r in laporan]


async def kirim_notifikasi_laporan(report_id) -> None:
    """Beri tahu penerima bahwa laporan `report_id` sudah terbit (lonceng, dan Telegram bila tertaut), lalu isi
    `notified_at`. Laporan yang sudah diberi tahu atau sudah tidak ada dilewati. Tidak memegang sesi DB selama
    mengirim; `notified_at` hanya diisi setelah `kirim` kembali, dan galat `kirim` diteruskan ke pemanggil."""
    async with AsyncSessionLocal() as db:
        report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
        if report is None or report.notified_at is not None:
            return
        user = (await db.execute(select(User).where(User.id == report.user_id))).scalar_one()
    judul, pesan, tautan, telegram = notifikasi_laporan(report.data["judul"], report.id, get_settings().APP_URL)
    await notification_service.kirim(user, NotificationType.system, judul, pesan, link=tautan, telegram_html=telegram)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Report).where(Report.id == report_id).values(notified_at=datetime.now(timezone.utc)))
        await db.commit()


async def laporan_job(today: date | None = None) -> dict:
    """Jalan tiap jam: terbitkan laporan bulanan untuk setiap ruang keluarga yang punya anggota, lalu beri tahu
    penerimanya. `today` bawaan = tanggal server. Mengembalikan `{"terbit": laporan baru, "gagal": household gagal}`.
    Household yang gagal dicatat (refresh snapshot yang error: `logger.error` dengan errornya; galat lain:
    `logger.exception`) dan dicoba lagi jam berikutnya; notifikasi yang gagal dicatat tanpa membatalkan laporannya."""
    today = today or date.today()
    async with AsyncSessionLocal() as db:
        household_ids = (await db.execute(
            select(Household.id).where(
                Household.type == HouseholdType.RUMAH_TANGGA,
                Household.id.in_(select(HouseholdMember.household_id)),
            )
        )).scalars().all()

    terbit = gagal = 0
    for household_id in household_ids:
        try:
            ids = await terbitkan_household(household_id, today)
        except RefreshSnapshotGagal as e:
            logger.error("laporan household=%s ditunda ke jam berikutnya: %s", household_id, e)
            gagal += 1
            continue
        except Exception:
            logger.exception("penerbitan laporan household=%s gagal", household_id)
            gagal += 1
            continue
        terbit += len(ids)
        for report_id in ids:
            try:
                await kirim_notifikasi_laporan(report_id)
            except Exception:
                logger.exception("notifikasi laporan %s gagal; laporannya tetap terbit", report_id)
    return {"terbit": terbit, "gagal": gagal}
