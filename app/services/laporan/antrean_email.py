"""Antrean email laporan berkala (tahap 2; spec 2026-11-01-laporan-berkala-design bagian 6b-6c, keputusan rencana
tahap 2 butir 2, 3, 5, 6, dan 7; ruling review Task 3 R-T3-1 dan R-T3-2).

`reports.email_status`: `menunggu` → `mengirim` → `terkirim`, atau `gagal` (alasan `smtp`) dan `dilewati` (alasan
`belum_verifikasi`, `dimatikan`, `tanpa_email`). Saat terbit `terbitkan_household` (job.py) mengisinya dari
`status_awal`. Laporan tahap 1 (`email_status` NULL) tidak pernah dikirim. Antrean dijalankan proses
`worker_email` (bukan `laporan_job`); `proses_antrean_email` hanya untuk jalan manual. Satu putaran
(`putaran_antrean`) dipacu dan dihentikan pemanggilnya (worker): `sebelum_laporan` di-await sebelum setiap laporan
(jeda pacu), `berhenti()` dicek sebelum dan sesudahnya, tepat sebelum klaim, dan `sesudah_laporan(hasil)` dipanggil
sesudah setiap laporan yang diproses:

1. Klaim `mengirim` yang lebih tua dari `BATAS_MENGIRIM` (proses berhenti di tengah kiriman, atau kiriman berhasil yang
   hasilnya tidak bisa disimpan) kembali `menunggu`, atau menjadi `gagal`/`smtp` dengan `logger.error` bila
   percobaannya sudah `MAKS_PERCOBAAN`. Percobaannya sudah dihitung saat klaim. Email itu bisa terkirim dua kali dalam
   kasus yang sangat jarang: dipilih daripada email hilang.
2. Paling banyak `KELOMPOK` laporan `menunggu` yang belum pernah diklaim atau diklaim terakhir paling
   sedikit `JEDA_COBA_ULANG` lalu, terbit terlama dulu. Jeda 55 menit untuk "paling cepat 1 jam" (ditetapkan saat
   antrean masih dijalankan job tiap jam di menit 30, ketika 60 menit tepat bisa meleset beberapa detik lalu menunda
   satu jam lagi; worker memakai jeda yang sama).
3. Per laporan, klaim lebih dulu (pola klaim notifikasi R16): UPDATE bersyarat `menunggu` dan jedanya sudah lewat →
   `mengirim`, `email_terakhir_at` = waktu klaim sebenarnya, `email_percobaan` + 1; commit; harus mengenai tepat satu
   baris, jadi job terjadwal dan jalan manual dari shell tidak pernah mengirim laporan yang sama bersamaan. SETIAP
   klaim adalah satu percobaan (R-T3-2): apa pun yang terjadi sesudahnya, satu laporan paling banyak diklaim, dan
   dikirim, `MAKS_PERCOBAAN` kali. Sesudah klaim, user dan pengaturannya dibaca ulang: yang kini tidak lolos
   `status_awal` (email diganti atau dihapus, email laporan dimatikan) menjadi `dilewati` dengan alasannya. Selainnya
   PDF bila kata sandi bisa dipakai, isi email (`surel`), dan kiriman SMTP di thread, berbatas waktu
   (`email_service.SMTP_TIMEOUT`, R-T3-1); koneksi database tidak dipegang selama itu. Berhasil → `terkirim` +
   `email_terkirim_at` (waktu sebenarnya). Gagal (SMTP menjawab gagal, atau galat apa pun sebelum kiriman selesai,
   dicatat `logger.exception` dengan id laporan) → `gagal`/`smtp` dengan `logger.error` bila percobaannya sudah
   `MAKS_PERCOBAAN`, selainnya kembali `menunggu`.

Setiap tulis hasil memeriksa pemiliknya: masih `mengirim` dengan waktu klaim jalan ini. Hasil yang klaimnya sementara
itu dikembalikan langkah 1 (dan mungkin diklaim jalan lain) tidak ditulis, hanya dicatat INFO dengan id; jadi kiriman
lambat yang akhirnya gagal tidak pernah membatalkan `terkirim` milik klaim yang lebih baru. Galat sesudah kiriman
berhasil (hasilnya tidak bisa disimpan) tidak pernah dicatat sebagai gagal: klaimnya dibiarkan untuk langkah 1. Galat
lain di satu laporan dicatat dan antrean lanjut.

Lampiran jatuh dengan anggun (`lampiran_untuk`, keputusan rencana 6), sama dengan jalur unduh PDF
(`_token_masih_terpakai` di app/api/routes/laporan.py): token tak terbaca atau kata sandi yang kini ditolak
`periksa_kata_sandi` → tanpa lampiran, baris "atur kata sandi" (409 di unduh); kunci server tidak ada (503 di unduh)
atau galat PDF tak terduga → tanpa lampiran, baris "unduh di aplikasi". Email tetap terkirim.

Log hanya memuat id laporan atau user, angka, dan teks tetap: tidak pernah alamat email, kata sandi, token, atau isi
laporan. Galat PDF dicatat dengan nama jenisnya saja, karena pesannya bisa memuat isi laporan atau kata sandi.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import Report, ReportSettings, User, email_normal
from app.services import email_service
from app.services.laporan import hitung, pdf, rahasia, surel

logger = logging.getLogger("jatahku.laporan")

STATUS_MENUNGGU = "menunggu"
STATUS_MENGIRIM = "mengirim"
STATUS_TERKIRIM = "terkirim"
STATUS_GAGAL = "gagal"
STATUS_DILEWATI = "dilewati"
ALASAN_BELUM_VERIFIKASI = "belum_verifikasi"
ALASAN_DIMATIKAN = "dimatikan"
ALASAN_TANPA_EMAIL = "tanpa_email"
ALASAN_SMTP = "smtp"

MAKS_PERCOBAAN = 3
JEDA_COBA_ULANG = timedelta(minutes=55)
BATAS_MENGIRIM = timedelta(minutes=30)
KELOMPOK = 100
# Akun terhapus/diblokir (email diganti berawalan ini); tidak pernah dikirimi laporan. Dipakai job.py dan pantau_email.py.
AWALAN_AKUN_NONAKTIF = ("deleted_", "banned_")

_LOG_KUNCI_TIDAK_ADA = "REPORT_SECRET_KEY kosong atau tidak valid: email laporan user %s dikirim tanpa lampiran PDF"
_LOG_TOKEN_TAK_TERBACA = (
    "Kata sandi laporan user %s tersimpan tetapi tidak terbaca (kunci diganti atau data rusak); email laporan dikirim "
    "tanpa lampiran PDF"
)
_LOG_KATA_SANDI_TAK_VALID = (
    "Kata sandi laporan user %s tersimpan tetapi tidak bisa dipakai untuk PDF; email laporan dikirim tanpa lampiran PDF"
)
_LOG_GAGAL = "email laporan %s gagal pada percobaan ke-%s; tidak dicoba lagi (alasan smtp)"
_LOG_BUKAN_PEMILIK = "hasil email laporan %s (%s) tidak dicatat: klaimnya sudah bukan milik jalan ini"


def _jam() -> datetime:
    """Waktu sekarang (UTC): awal jalan, waktu klaim, dan waktu terkirim."""
    return datetime.now(timezone.utc)


def hasil_kosong() -> dict:
    """Hasil `proses_antrean_email` tanpa satu laporan pun yang diproses."""
    return {"terkirim": 0, "gagal": 0, "dilewati": 0, "dicoba_lagi": 0}


def status_awal(user: User, pengaturan: ReportSettings | None) -> tuple[str, str | None]:
    """(status, alasan) email laporan untuk `user` menurut keadaannya sekarang: saat terbit, dan lagi sesudah klaim,
    tepat sebelum mengirim. Urutan alasan: tanpa email (akun hanya Telegram), belum terverifikasi, email laporan
    dimatikan. Tanpa baris `report_settings` = bawaan (`email_on` true)."""
    if not email_normal(user.email):
        return STATUS_DILEWATI, ALASAN_TANPA_EMAIL
    if user.email_verified_at is None:
        return STATUS_DILEWATI, ALASAN_BELUM_VERIFIKASI
    if pengaturan is not None and not pengaturan.email_on:
        return STATUS_DILEWATI, ALASAN_DIMATIKAN
    return STATUS_MENUNGGU, None


def lampiran_untuk(pengaturan: ReportSettings | None) -> tuple[str | None, str]:
    """(kata sandi PDF atau None, kode baris lampiran `surel.LAMPIRAN_*`) untuk email laporan pemilik `pengaturan`.
    Kata sandi hanya dikembalikan bila terbaca dengan kunci server dan masih lolos `pdf.periksa_kata_sandi`. Kegagalan
    dicatat sebagai peringatan dengan id user saja (keputusan rencana 6; docstring modul)."""
    token = None if pengaturan is None else pengaturan.kata_sandi_enc
    if token is None:
        return None, surel.LAMPIRAN_BELUM_DIATUR
    try:
        kata_sandi = rahasia.dekripsi(token)
    except rahasia.KunciLaporanTidakAda:
        logger.warning(_LOG_KUNCI_TIDAK_ADA, pengaturan.user_id)
        return None, surel.LAMPIRAN_TIDAK_TERSEDIA
    except ValueError:
        logger.warning(_LOG_TOKEN_TAK_TERBACA, pengaturan.user_id)
        return None, surel.LAMPIRAN_BELUM_DIATUR
    try:
        pdf.periksa_kata_sandi(kata_sandi)
    except pdf.KataSandiPdfTidakValid:
        logger.warning(_LOG_KATA_SANDI_TAK_VALID, pengaturan.user_id)
        return None, surel.LAMPIRAN_BELUM_DIATUR
    return kata_sandi, surel.LAMPIRAN_TERLAMPIR


def _boleh_dicoba(waktu: datetime):
    """Syarat SQL: belum pernah diklaim, atau diklaim terakhir paling sedikit `JEDA_COBA_ULANG` sebelum `waktu`. Dipakai
    saat memilih antrean DAN di klaim, jadi jalan lain yang memilih laporan yang sama sebelum percobaan ini selesai tidak
    bisa langsung mencobanya lagi."""
    return or_(Report.email_terakhir_at.is_(None), Report.email_terakhir_at <= waktu - JEDA_COBA_ULANG)


def _milik_klaim(report_id, waktu_klaim: datetime) -> tuple:
    """Syarat SQL setiap tulis hasil: laporan ini masih `mengirim` dengan klaim yang dicap `waktu_klaim`."""
    return Report.id == report_id, Report.email_status == STATUS_MENGIRIM, Report.email_terakhir_at == waktu_klaim


async def proses_antrean_email(sekarang: datetime | None = None) -> dict:
    """Satu putaran antrean email tanpa pacu dan tanpa henti (jalan manual dari shell; worker memakai
    `putaran_antrean`).
    Tanpa `sekarang`, setiap cap waktu (awal jalan, klaim, terkirim) memakai waktu saat itu; `sekarang` (tes, atau jalan
    manual untuk waktu tertentu) membekukan jam seluruh jalan. Mengembalikan hasil `putaran_antrean`."""
    jam = None if sekarang is None else (lambda: sekarang)
    hasil, _ = await putaran_antrean(jam)
    return hasil


async def putaran_antrean(
    jam: Callable[[], datetime] | None = None,
    *,
    sebelum_laporan: Callable[[], Awaitable[None]] | None = None,
    berhenti: Callable[[], bool] | None = None,
    sesudah_laporan: Callable[[str | None], None] | None = None,
) -> tuple[dict, bool]:
    """Satu putaran antrean email (langkah dan alasannya: docstring modul): rapikan klaim basi, ambil paling banyak
    `KELOMPOK` laporan siap, proses satu per satu. `jam` memberi setiap cap waktu (awal putaran, klaim, terkirim);
    None = waktu sebenarnya modul ini. `sebelum_laporan` (pacu dari pemanggil) di-await sebelum setiap laporan.
    `berhenti()` dicek sebelum dan sesudah `sebelum_laporan`, tepat sebelum klaim: bila true putaran berakhir dan
    tidak ada laporan lagi yang diklaim (laporan yang sedang berjalan selalu diselesaikan). `sesudah_laporan(hasil)`
    dipanggil sekali sesudah setiap laporan yang diproses dengan hasilnya (`"terkirim"`, `"gagal"`, `"dilewati"`,
    `"dicoba_lagi"`), atau None bila pemrosesannya melempar (sudah dicatat); laporan yang tidak diproses (klaim kalah,
    klaim bukan miliknya lagi, laporan atau user terhapus) tidak dilaporkan. Galat dari `sebelum_laporan`, `berhenti`,
    dan `sesudah_laporan` diteruskan ke pemanggil tanpa klaim berikutnya.

    Mengembalikan `(hasil, penuh)`. `hasil` = jumlah laporan putaran ini `{"terkirim", "gagal", "dilewati",
    "dicoba_lagi"}` (`gagal` termasuk klaim basi yang percobaannya habis); laporan yang galat tanpa hasil tercatat
    tidak dihitung (sudah dicatat di log). `penuh` = jumlah yang diambil tepat `KELOMPOK` dan putaran tidak dihentikan,
    jadi mungkin masih ada antrean. Galat di luar satu laporan (langkah 1 dan 2) diteruskan ke pemanggil."""
    jam = _jam if jam is None else jam
    mulai = jam()
    hasil = hasil_kosong()
    hasil["gagal"] += await _rapikan_klaim_basi(mulai)
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(
            select(Report.id)
            .where(Report.email_status == STATUS_MENUNGGU, _boleh_dicoba(mulai))
            .order_by(Report.terbit_at, Report.id)
            .limit(KELOMPOK)
        )).scalars().all()
    for report_id in ids:
        if berhenti is not None and berhenti():
            return hasil, False
        if sebelum_laporan is not None:
            await sebelum_laporan()
            if berhenti is not None and berhenti():
                return hasil, False
        try:
            keluaran = await _proses_laporan(report_id, jam)
        except Exception:
            logger.exception("email laporan %s gagal diproses; dicoba lagi di jalan berikutnya", report_id)
            if sesudah_laporan is not None:
                sesudah_laporan(None)
            continue
        if keluaran is not None:
            hasil[keluaran] += 1
            if sesudah_laporan is not None:
                sesudah_laporan(keluaran)
    return hasil, len(ids) == KELOMPOK


async def _rapikan_klaim_basi(mulai: datetime) -> int:
    """Langkah 1: klaim `mengirim` yang lebih tua dari `BATAS_MENGIRIM` saat `mulai`. Percobaannya sudah habis →
    `gagal`/`smtp` (satu `logger.error` per laporan, id saja); selainnya kembali `menunggu` (satu peringatan berisi
    jumlah). Mengembalikan jumlah yang menjadi `gagal`."""
    basi = (Report.email_status == STATUS_MENGIRIM, Report.email_terakhir_at < mulai - BATAS_MENGIRIM)
    async with AsyncSessionLocal() as db:
        habis = (await db.execute(
            update(Report)
            .where(*basi, Report.email_percobaan >= MAKS_PERCOBAAN)
            .values(email_status=STATUS_GAGAL, email_alasan=ALASAN_SMTP)
            .returning(Report.id, Report.email_percobaan)
            .execution_options(synchronize_session=False)
        )).all()
        kembali = (await db.execute(
            update(Report).where(*basi).values(email_status=STATUS_MENUNGGU)
            .execution_options(synchronize_session=False)
        )).rowcount
        await db.commit()
    menit = int(BATAS_MENGIRIM.total_seconds() // 60)
    if kembali:
        logger.warning("%s email laporan masih berstatus mengirim lebih dari %s menit; dikembalikan ke antrean",
                       kembali, menit)
    for report_id, percobaan in habis:
        logger.error("email laporan %s masih berstatus mengirim lebih dari %s menit pada percobaan ke-%s; tidak dicoba "
                     "lagi (alasan smtp)", report_id, menit, percobaan)
    return len(habis)


async def _klaim(report_id, waktu_klaim: datetime) -> bool:
    """Klaim laporan untuk jalan ini (langkah 3): satu percobaan. False bila sudah diklaim jalan lain, tidak lagi
    `menunggu`, atau jedanya belum lewat."""
    async with AsyncSessionLocal() as db:
        klaim = await db.execute(
            update(Report)
            .where(Report.id == report_id, Report.email_status == STATUS_MENUNGGU, _boleh_dicoba(waktu_klaim))
            .values(email_status=STATUS_MENGIRIM, email_terakhir_at=waktu_klaim,
                    email_percobaan=Report.email_percobaan + 1)
            .execution_options(synchronize_session=False)
        )
        if klaim.rowcount != 1:
            await db.rollback()
            return False
        await db.commit()
    return True


async def _proses_laporan(report_id, jam: Callable[[], datetime]) -> str | None:
    """Satu laporan dari antrean: klaim, baca ulang, lewati atau kirim, simpan hasilnya. Mengembalikan kunci hasil yang
    bertambah, atau None bila klaimnya kalah atau tidak lagi miliknya, atau laporannya sudah tidak ada. Hanya galat
    sesudah kiriman berhasil yang keluar dari sini (klaimnya dibiarkan untuk langkah 1)."""
    waktu_klaim = jam()
    if not await _klaim(report_id, waktu_klaim):
        return None
    try:
        async with AsyncSessionLocal() as db:
            report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
            user = None if report is None else (await db.execute(
                select(User).where(User.id == report.user_id)
            )).scalar_one_or_none()
            if user is None:   # dihapus sesudah klaim (hapus akun; laporannya ikut terhapus)
                return None
            pengaturan = (await db.execute(
                select(ReportSettings).where(ReportSettings.user_id == user.id)
            )).scalar_one_or_none()
            # Semua yang dibutuhkan dibaca di sini; PDF dan SMTP berjalan tanpa memegang koneksi.
            status, alasan = status_awal(user, pengaturan)
            tujuan, nama, user_id = user.email, user.name, user.id
            data, jenis, mulai, akhir = report.data, report.jenis, report.periode_mulai, report.periode_akhir
        if status != STATUS_MENUNGGU:
            return await _catat_dilewati(report_id, waktu_klaim, alasan)
        kata_sandi, lampiran = lampiran_untuk(pengaturan)
        isi_pdf = nama_file = None
        if kata_sandi is not None:
            try:
                nama_file = hitung.nama_file_pdf(jenis, mulai, akhir)
                isi_pdf = await pdf.buat_pdf(data, kata_sandi)
            except Exception as galat:
                logger.error("PDF laporan %s gagal dibuat (%s); email dikirim tanpa lampiran", report_id,
                             type(galat).__name__)
                isi_pdf = nama_file = None
                lampiran = surel.LAMPIRAN_TIDAK_TERSEDIA
        berhenti = surel.tautan_berhenti(user_id)
        subjek, isi_html, isi_teks = surel.isi_email_laporan(
            data, nama, f"{get_settings().APP_URL}/laporan/{report_id}", berhenti, lampiran,
        )
        terkirim = await asyncio.to_thread(
            email_service.send_laporan_email, tujuan, subjek, isi_html, isi_teks, berhenti,
            pdf_bytes=isi_pdf, filename=nama_file,
        )
    except Exception:
        logger.exception("email laporan %s gagal diproses sebelum terkirim; klaimnya dihitung sebagai percobaan",
                         report_id)
        return await _catat_gagal(report_id, waktu_klaim)
    if terkirim:
        return await _tulis_milik_klaim(report_id, waktu_klaim, "terkirim", email_status=STATUS_TERKIRIM,
                                        email_alasan=None, email_terkirim_at=jam())
    return await _catat_gagal(report_id, waktu_klaim)


async def _catat_dilewati(report_id, waktu_klaim: datetime, alasan: str) -> str | None:
    return await _tulis_milik_klaim(report_id, waktu_klaim, "dilewati", email_status=STATUS_DILEWATI,
                                    email_alasan=alasan)


async def _tulis_milik_klaim(report_id, waktu_klaim: datetime, keluaran: str, **nilai) -> str | None:
    """Tulis hasil `keluaran` (kunci hasil) hanya bila klaimnya masih milik jalan ini (`_milik_klaim`); selainnya
    INFO dengan id dan tidak ada yang berubah."""
    async with AsyncSessionLocal() as db:
        tulis = await db.execute(
            update(Report).where(*_milik_klaim(report_id, waktu_klaim)).values(**nilai)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    if tulis.rowcount == 1:
        return keluaran
    logger.info(_LOG_BUKAN_PEMILIK, report_id, keluaran)
    return None


async def _catat_gagal(report_id, waktu_klaim: datetime) -> str | None:
    """Percobaan yang diklaim jalan ini gagal. Percobaannya sudah dihitung saat klaim: bila sudah `MAKS_PERCOBAAN` →
    `gagal`/`smtp` + `logger.error` (id saja), selainnya kembali `menunggu`. Ditulis hanya bila klaimnya masih milik
    jalan ini (lihat `_tulis_milik_klaim`)."""
    async with AsyncSessionLocal() as db:
        habis = (await db.execute(
            update(Report)
            .where(*_milik_klaim(report_id, waktu_klaim), Report.email_percobaan >= MAKS_PERCOBAAN)
            .values(email_status=STATUS_GAGAL, email_alasan=ALASAN_SMTP)
            .returning(Report.email_percobaan)
            .execution_options(synchronize_session=False)
        )).scalar_one_or_none()
        kembali = 0
        if habis is None:
            kembali = (await db.execute(
                update(Report).where(*_milik_klaim(report_id, waktu_klaim)).values(email_status=STATUS_MENUNGGU)
                .execution_options(synchronize_session=False)
            )).rowcount
        await db.commit()
    if habis is not None:
        logger.error(_LOG_GAGAL, report_id, habis)
        return "gagal"
    if kembali == 1:
        return "dicoba_lagi"
    logger.info(_LOG_BUKAN_PEMILIK, report_id, "gagal")
    return None


async def hidupkan_lagi(db, user_id: UUID, alasan: tuple[str, ...], sekarang: datetime | None = None) -> int:
    """Keputusan rencana 2: laporan `user_id` yang `dilewati` dengan salah satu `alasan` dan terbit paling lama
    `JENDELA_TERBIT_HARI` hari sebelum `sekarang` kembali `menunggu` (alasan dikosongkan). Yang lebih tua tidak dikirim
    lagi. Percobaan yang sudah terpakai dan waktu klaim terakhirnya tetap: jeda 55 menit tetap berlaku, dan laporan
    yang dilewati pada klaim ke-`MAKS_PERCOBAAN` masih mendapat satu klaim lagi (gagal berikutnya langsung `gagal`).
    Dipanggil sesudah verifikasi email berhasil (`belum_verifikasi`, `tanpa_email`) dan saat `email_on` dinyalakan
    (`dimatikan`). TIDAK commit: perubahannya ikut transaksi pemanggil. Mengembalikan jumlah laporan yang
    dihidupkan."""
    from app.services.laporan.job import JENDELA_TERBIT_HARI   # Ruling P3: job.py mengimpor modul ini

    sekarang = sekarang or _jam()
    hasil = await db.execute(
        update(Report)
        .where(
            Report.user_id == user_id,
            Report.email_status == STATUS_DILEWATI,
            Report.email_alasan.in_(alasan),
            Report.terbit_at >= sekarang - timedelta(days=JENDELA_TERBIT_HARI),
        )
        .values(email_status=STATUS_MENUNGGU, email_alasan=None)
        .execution_options(synchronize_session=False)
    )
    return hasil.rowcount
