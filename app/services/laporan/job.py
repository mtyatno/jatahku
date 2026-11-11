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
   Diperiksa SEBELUM refresh (langkah 4), jadi refresh tidak pernah memenuhi prasyaratnya sendiri. Belum ada: ditunda
   ke jam berikutnya (log DEBUG); di hari terakhir jendela, household yang beraktivitas di periode itu dicatat WARNING
   (Ruling R16), karena laporannya hilang bila snapshot tidak dibuat hari itu;
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
5. pengaturan laporan (`report_settings`) semua calon dalam satu kueri, lalu per calon `muat_bahan` → lewati bila
   `ada_aktivitas` False (tidak ada laporan kosong) → `Report` dengan `susun_bulanan` dan status email awal dari
   `antrean_email.status_awal` (`menunggu`, atau `dilewati` dengan alasannya); satu commit untuk semua anggota
   household.
Sesi persiapan (langkah 2–3) ditutup sebelum refresh, dan pembangunan memakai sesi baru, jadi bacaannya pasti melihat
snapshot yang baru ditulis.

Notifikasi (Ruling R16): `kirim_notifikasi_laporan` menyimpan lonceng dan `notified_at` dalam SATU transaksi, didahului
UPDATE bersyarat `notified_at IS NULL` (klaim), lalu sesudah commit mengirim Telegram sekali lewat
`notification_service.kirim(permukaan=("telegram",))`, best-effort. Jadi mencoba lagi tidak pernah membuat lonceng kedua,
dan Telegram yang gagal permanen (bot diblokir) tidak dikirim ulang. Setelah semua household, `laporan_job` menyapu
laporan yang `notified_at`-nya masih NULL dan terbit dalam `JENDELA_TERBIT_HARI` hari (`kirim_notifikasi_tertunda`):
galat DB atau restart di antara commit laporan dan notifikasinya tersusulkan jam berikutnya. Gagal kirim tidak
membatalkan laporan yang sudah terbit.

Email: `laporan_job` TIDAK mengirim email. Antrean email (laporan baru maupun yang menunggu coba ulang) dijalankan
proses terpisah `worker_email`; job hanya mengisi status email awal saat terbit (`status_awal`). Worker mati tidak
menghentikan penerbitan atau notifikasi, hanya menunda email.

Batas waktu: household baru tidak dimulai sesudah `BATAS_JALAN` (40 menit) sejak job mulai, supaya satu jalan tidak
bertabrakan dengan jalan jam berikutnya (`max_instances=1`). Sisanya dihitung `ditunda`, tidak diterbitkan dan tidak
diberi tahu di jalan ini, dan diselesaikan jalan berikutnya (penerbitan idempoten). Sapu notifikasi dan pemeriksaan
alarm tetap dijalankan. Jalan yang menerbitkan, menggagalkan, atau menunda sesuatu mencatat satu baris INFO berisi
durasi (detik) dan ketiga angkanya; jalan sepi tiap jam tidak menambah log.

Alarm: sesudah sapu, `laporan_job` memanggil `pantau_email.periksa_alarm` (spec worker email bagian 6) dengan sesi
database dan klien Redis miliknya sendiri; galat apa pun darinya dicatat dan tidak mengubah hasil job.
"""
import html
import logging
import time as waktu_mod
import uuid
from datetime import date, datetime, time, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.period import get_closed_periods
from app.models.models import (
    JENIS_BULANAN, Allocation, Envelope, Household, HouseholdMember, HouseholdType, Income, MonthlySnapshot,
    Notification, NotificationType, Report, ReportSettings, Transaction, User,
)
from app.services import notification_service
from app.services.advisor import advisor_cache
from app.services.household_cycle import current_payday, household_lock, member_rows
from app.services.laporan import pantau_email
from app.services.laporan.antrean_email import AWALAN_AKUN_NONAKTIF, status_awal
from app.services.laporan.muat import muat_bahan
from app.services.laporan.susun import ada_aktivitas, susun_bulanan
from app.services.rollover import create_monthly_snapshots

logger = logging.getLogger("jatahku.laporan")

# Laporan periode yang tutup lebih lama dari ini tidak diterbitkan lagi (server mati beberapa hari tetap terkejar).
JENDELA_TERBIT_HARI = 7
# Household baru tidak dimulai sesudah selama ini sejak `laporan_job` mulai (jalan berikutnya menyelesaikan sisanya).
BATAS_JALAN = timedelta(minutes=40)
_BATAS_WAKTU_REDIS = 5   # detik; Redis yang menggantung tidak boleh menahan job
_PESAN_NOTIFIKASI = "Lihat bagaimana periode kemarin berjalan."


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
    if (user.email or "").startswith(AWALAN_AKUN_NONAKTIF):
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
                if (today - pe).days == JENDELA_TERBIT_HARI and await _rumah_beraktivitas(db, household_id, ps, pe):
                    logger.warning(
                        "household=%s periode %s → %s masih belum punya snapshot di hari terakhir jendela terbit; "
                        "laporan periode ini tidak akan terbit bila snapshot tidak dibuat hari ini",
                        household_id, ps, pe,
                    )
                else:
                    logger.debug("household=%s periode %s → %s belum punya snapshot; laporan ditunda",
                                 household_id, ps, pe)
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
            pengaturan = {
                p.user_id: p for p in (await db.execute(
                    select(ReportSettings).where(ReportSettings.user_id.in_([u.id for u in calon]))
                )).scalars().all()
            }
            for user in calon:
                bahan = await muat_bahan(db, user, household, ps, pe, payday, today)
                if not ada_aktivitas(bahan):
                    continue
                email_status, email_alasan = status_awal(user, pengaturan.get(user.id))
                report = Report(
                    id=uuid.uuid4(),  # dibuat di sini, bukan saat flush: id dikembalikan untuk notifikasi
                    user_id=user.id, household_id=household_id, jenis=JENIS_BULANAN, periode_mulai=ps,
                    periode_akhir=pe, payday_day=payday, data=susun_bulanan(bahan),
                    email_status=email_status, email_alasan=email_alasan,
                )
                db.add(report)
                laporan.append(report)
            if laporan:
                await db.commit()
                logger.info("household=%s payday=%s periode %s → %s: %s laporan terbit",
                            household_id, payday, ps, pe, len(laporan))
        return [r.id for r in laporan]


async def kirim_notifikasi_laporan(report_id) -> bool:
    """Beri tahu penerima bahwa laporan `report_id` sudah terbit; True bila lonceng baru dibuat. Laporan yang sudah
    diberi tahu, sudah tidak ada, atau diklaim proses lain lebih dulu dilewati (False).

    Lonceng dan `notified_at` disimpan dalam satu transaksi, didahului UPDATE bersyarat `notified_at IS NULL` yang
    harus mengenai tepat satu baris: dua proses yang bersamaan tidak bisa sama-sama membuat lonceng (yang kalah
    menunggu kunci baris, lalu tidak mengenai apa-apa). Galat database diteruskan ke pemanggil tanpa ada yang
    tersimpan, jadi sapu berikutnya mencoba lagi. Telegram (bila tertaut) dikirim sekali setelah commit, best-effort:
    gagal hanya dicatat, tidak diulang, dan tidak pernah membatalkan lonceng. Tanpa nominal di keduanya."""
    async with AsyncSessionLocal() as db:
        report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
        if report is None or report.notified_at is not None:
            return False
        user = (await db.execute(select(User).where(User.id == report.user_id))).scalar_one()
        judul, pesan, tautan, telegram = notifikasi_laporan(report.data["judul"], report.id, get_settings().APP_URL)
        klaim = await db.execute(
            update(Report).where(Report.id == report_id, Report.notified_at.is_(None))
            .values(notified_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )
        if klaim.rowcount != 1:
            await db.rollback()
            return False
        db.add(Notification(user_id=user.id, type=NotificationType.system, title=judul, message=pesan, link=tautan))
        await db.commit()
    try:
        await notification_service.kirim(user, NotificationType.system, judul, pesan, link=tautan,
                                         telegram_html=telegram, permukaan=("telegram",))
    except Exception:
        logger.exception("Telegram untuk laporan %s gagal; lonceng sudah tersimpan, tidak dikirim ulang", report_id)
    return True


async def kirim_notifikasi_tertunda(today: date, kecuali=frozenset()) -> int:
    """Sapu notifikasi yang tertinggal (Ruling R16): laporan yang `notified_at`-nya NULL dan `terbit_at`-nya paling
    awal pukul 00.00 UTC `JENDELA_TERBIT_HARI` hari sebelum `today`, terlama dulu, selain `kecuali` (sudah dicoba di
    jalan ini). Masing-masing lewat `kirim_notifikasi_laporan` (tidak pernah lonceng kedua); galat satu laporan dicatat
    dan yang lain tetap dicoba, laporan itu dicoba lagi jam berikutnya sampai keluar jendela. Mengembalikan jumlah
    lonceng yang dibuat."""
    batas = datetime.combine(today - timedelta(days=JENDELA_TERBIT_HARI), time.min, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(
            select(Report.id)
            .where(Report.notified_at.is_(None), Report.terbit_at >= batas)
            .order_by(Report.terbit_at, Report.id)
        )).scalars().all()
    terkirim = 0
    for report_id in ids:
        if report_id in kecuali:
            continue
        try:
            if await kirim_notifikasi_laporan(report_id):
                terkirim += 1
        except Exception:
            logger.exception("notifikasi laporan %s yang tertinggal masih gagal; dicoba lagi jam berikutnya", report_id)
    if terkirim:
        logger.info("%s notifikasi laporan yang tertinggal dikirim", terkirim)
    return terkirim


async def _periksa_alarm_email() -> None:
    """Pemeriksaan alarm email laporan dengan sesi dan klien Redis milik sendiri (ditutup di sini). Galat apa pun,
    termasuk saat membuka Redis atau sesi, dicatat dan tidak pernah dilempar: alarm tidak boleh mengubah hasil job."""
    try:
        redis = aioredis.from_url(get_settings().REDIS_URL, socket_timeout=_BATAS_WAKTU_REDIS,
                                  socket_connect_timeout=_BATAS_WAKTU_REDIS)
        try:
            async with AsyncSessionLocal() as db:
                await pantau_email.periksa_alarm(
                    db, redis, datetime.now(timezone.utc),
                    kirim=pantau_email.kirim_telegram_admin, api_menyala=pantau_email.API_MENYALA,
                )
        finally:
            await redis.aclose()
    except Exception:
        logger.exception("pemeriksaan alarm email laporan gagal; dicoba lagi jam berikutnya")


async def laporan_job(today: date | None = None, *, jam=waktu_mod.monotonic) -> dict:
    """Jalan tiap jam: terbitkan laporan bulanan untuk setiap ruang keluarga yang punya anggota, beri tahu
    penerimanya, sapu notifikasi yang tertinggal (`kirim_notifikasi_tertunda`; laporan yang sudah dicoba di jalan ini
    tidak dicoba dua kali), lalu periksa alarm email (`_periksa_alarm_email`). Tidak mengirim email: antrean email
    milik `worker_email`. `today` bawaan = tanggal server; `jam` = jam monotonik (detik) yang dipakai untuk batas
    waktu dan durasi, diganti tes. Mengembalikan `{"terbit": laporan baru, "gagal": household gagal, "ditunda":
    household yang tidak dimulai karena melewati BATAS_JALAN}`.
    Household yang gagal dicatat (refresh snapshot yang error: `logger.error` dengan errornya; galat lain:
    `logger.exception`) dan dicoba lagi jam berikutnya; notifikasi yang gagal dicatat tanpa membatalkan laporannya dan
    disusulkan sapu jam berikutnya. Household yang ditunda tidak diterbitkan maupun diberi tahu di jalan ini (WARNING
    menyebut jumlahnya); sapu dan alarm tetap jalan. Jalan yang menerbitkan, menggagalkan, atau menunda sesuatu
    mencatat durasi dan ketiga angka di log INFO. Galat pemeriksaan alarm dicatat, tidak mengubah hasil."""
    today = today or date.today()
    mulai = jam()
    async with AsyncSessionLocal() as db:
        household_ids = (await db.execute(
            select(Household.id).where(
                Household.type == HouseholdType.RUMAH_TANGGA,
                Household.id.in_(select(HouseholdMember.household_id)),
            )
        )).scalars().all()

    terbit = gagal = ditunda = 0
    dicoba = set()
    for urutan, household_id in enumerate(household_ids):
        if jam() - mulai >= BATAS_JALAN.total_seconds():
            ditunda = len(household_ids) - urutan
            logger.warning("laporan_job melewati batas %s menit: %s household ditunda ke jam berikutnya",
                           int(BATAS_JALAN.total_seconds() // 60), ditunda)
            break
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
            dicoba.add(report_id)
            try:
                await kirim_notifikasi_laporan(report_id)
            except Exception:
                logger.exception("notifikasi laporan %s gagal; laporannya tetap terbit", report_id)
    try:
        await kirim_notifikasi_tertunda(today, kecuali=frozenset(dicoba))
    except Exception:
        logger.exception("sapu notifikasi laporan gagal; dicoba lagi jam berikutnya")
    if terbit or gagal or ditunda:
        logger.info("laporan_job selesai dalam %.1f detik: %s terbit, %s gagal, %s ditunda",
                    jam() - mulai, terbit, gagal, ditunda)
    await _periksa_alarm_email()
    return {"terbit": terbit, "gagal": gagal, "ditunda": ditunda}
