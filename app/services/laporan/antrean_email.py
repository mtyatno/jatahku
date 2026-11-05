"""Antrean email laporan berkala (tahap 2; spec 2026-11-01-laporan-berkala-design bagian 6b-6c, keputusan rencana
tahap 2 butir 2, 3, 5, 6, dan 7).

`reports.email_status`: `menunggu` → `mengirim` → `terkirim`, atau `gagal` (alasan `smtp`) dan `dilewati` (alasan
`belum_verifikasi`, `dimatikan`, `tanpa_email`). Saat terbit `terbitkan_household` (job.py) mengisinya dari
`status_awal`. Laporan tahap 1 (`email_status` NULL) tidak pernah dikirim. `laporan_job` menjalankan
`proses_antrean_email` tiap jam sesudah sapu notifikasi, di luar kunci household:

1. `mengirim` yang diklaim lebih dari `BATAS_MENGIRIM` lalu (proses mati saat mengirim) kembali `menunggu`; percobaan
   tidak bertambah. Email itu bisa terkirim dua kali dalam kasus yang sangat jarang: dipilih daripada email hilang.
2. Paling banyak `MAKS_EMAIL_PER_JALAN` laporan `menunggu` yang belum pernah dicoba atau dicoba terakhir paling sedikit
   `JEDA_COBA_ULANG` lalu, terbit terlama dulu. Jeda 55 menit untuk "paling cepat 1 jam": job jalan tiap jam di menit
   30, dan 60 menit tepat bisa meleset beberapa detik lalu menunda satu jam lagi.
3. Per laporan, user dan pengaturannya dibaca ulang: yang kini tidak lolos `status_awal` (email diganti atau dihapus,
   email laporan dimatikan) menjadi `dilewati` dengan alasannya. Selainnya diklaim (pola klaim notifikasi R16): UPDATE
   bersyarat `menunggu` dan jedanya sudah lewat → `mengirim` + `email_terakhir_at` = `sekarang`, commit, dan harus
   mengenai tepat satu baris, jadi job terjadwal dan jalan manual dari shell tidak pernah mengirim laporan yang sama
   dua kali (yang kalah tidak mengenai apa-apa, termasuk sesudah yang menang gagal mengirim). Lalu PDF bila kata sandi
   bisa dipakai, isi email (`surel`), dan kiriman SMTP di thread; koneksi database tidak dipegang selama itu.
   Berhasil → `terkirim` + `email_terkirim_at`. Gagal → `email_percobaan` + 1 lalu kembali `menunggu`, atau pada
   percobaan ke-`MAKS_PERCOBAAN` menjadi `gagal`/`smtp` dengan `logger.error`.

Galat tak terduga pada satu laporan dicatat (`logger.exception` dengan id laporan) dan antrean lanjut. Galat sebelum
klaim membiarkan laporan `menunggu` untuk jalan berikutnya; galat sesudah klaim menahannya di `mengirim` sampai langkah
1 mengembalikannya, sama seperti proses yang mati saat mengirim. Hanya kiriman SMTP yang gagal dihitung sebagai
percobaan, jadi laporan yang terkena galat program dikirim begitu galatnya diperbaiki.

Lampiran jatuh dengan anggun (`lampiran_untuk`, keputusan rencana 6), sama dengan jalur unduh PDF
(`_token_masih_terpakai` di app/api/routes/laporan.py): token tak terbaca atau kata sandi yang kini ditolak
`periksa_kata_sandi` → tanpa lampiran, baris "atur kata sandi" (409 di unduh); kunci server tidak ada (503 di unduh)
atau galat PDF tak terduga → tanpa lampiran, baris "unduh di aplikasi". Email tetap terkirim.

Log hanya memuat id laporan atau user, angka, dan teks tetap: tidak pernah alamat email, kata sandi, token, atau isi
laporan. Galat PDF dicatat dengan nama jenisnya saja, karena pesannya bisa memuat isi laporan atau kata sandi.
"""
import asyncio
import logging
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
MAKS_EMAIL_PER_JALAN = 50

_LOG_KUNCI_TIDAK_ADA = "REPORT_SECRET_KEY kosong atau tidak valid: email laporan user %s dikirim tanpa lampiran PDF"
_LOG_TOKEN_TAK_TERBACA = (
    "Kata sandi laporan user %s tersimpan tetapi tidak terbaca (kunci diganti atau data rusak); email laporan dikirim "
    "tanpa lampiran PDF"
)
_LOG_KATA_SANDI_TAK_VALID = (
    "Kata sandi laporan user %s tersimpan tetapi tidak bisa dipakai untuk PDF; email laporan dikirim tanpa lampiran PDF"
)


def hasil_kosong() -> dict:
    """Hasil `proses_antrean_email` tanpa satu laporan pun yang diproses."""
    return {"terkirim": 0, "gagal": 0, "dilewati": 0, "dicoba_lagi": 0}


def status_awal(user: User, pengaturan: ReportSettings | None) -> tuple[str, str | None]:
    """(status, alasan) email laporan untuk `user` menurut keadaannya sekarang: saat terbit, dan lagi tepat sebelum
    mengirim. Urutan alasan: tanpa email (akun hanya Telegram), belum terverifikasi, email laporan dimatikan. Tanpa
    baris `report_settings` = bawaan (`email_on` true)."""
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


def _boleh_dicoba(sekarang: datetime):
    """Syarat SQL: belum pernah dicoba, atau percobaan terakhirnya paling sedikit `JEDA_COBA_ULANG` sebelum
    `sekarang`. Dipakai saat memilih antrean DAN di klaim, jadi jalan lain yang memilih laporan yang sama sebelum
    percobaan ini gagal tidak bisa langsung mencobanya lagi."""
    return or_(Report.email_terakhir_at.is_(None), Report.email_terakhir_at <= sekarang - JEDA_COBA_ULANG)


async def proses_antrean_email(sekarang: datetime | None = None) -> dict:
    """Satu putaran antrean email (langkah dan alasannya: docstring modul). `sekarang` bawaan = waktu server (UTC);
    dipakai untuk semua batas waktu jalan ini dan dicatat sebagai waktu klaim dan waktu terkirim. Mengembalikan jumlah
    laporan jalan ini `{"terkirim", "gagal", "dilewati", "dicoba_lagi"}`; laporan yang terkena galat tak terduga tidak
    dihitung (sudah dicatat). Galat di luar satu laporan (memilih antrean) diteruskan ke pemanggil."""
    sekarang = sekarang or datetime.now(timezone.utc)
    hasil = hasil_kosong()
    async with AsyncSessionLocal() as db:
        basi = await db.execute(
            update(Report)
            .where(Report.email_status == STATUS_MENGIRIM, Report.email_terakhir_at < sekarang - BATAS_MENGIRIM)
            .values(email_status=STATUS_MENUNGGU)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if basi.rowcount:
            logger.warning(
                "%s email laporan tertahan di status mengirim lebih dari %s menit (proses berhenti saat mengirim); "
                "dikembalikan ke antrean", basi.rowcount, int(BATAS_MENGIRIM.total_seconds() // 60),
            )
        ids = (await db.execute(
            select(Report.id)
            .where(Report.email_status == STATUS_MENUNGGU, _boleh_dicoba(sekarang))
            .order_by(Report.terbit_at, Report.id)
            .limit(MAKS_EMAIL_PER_JALAN)
        )).scalars().all()
    for report_id in ids:
        try:
            keluaran = await _proses_laporan(report_id, sekarang)
        except Exception:
            logger.exception("email laporan %s gagal diproses; dicoba lagi di jalan berikutnya", report_id)
            continue
        if keluaran is not None:
            hasil[keluaran] += 1
    return hasil


async def _proses_laporan(report_id, sekarang: datetime) -> str | None:
    """Satu laporan dari antrean: baca ulang, lewati atau klaim, kirim, simpan hasilnya. Mengembalikan kunci hasil
    yang bertambah, atau None bila laporan sudah tidak ada, sudah diurus jalan lain, atau klaimnya kalah."""
    async with AsyncSessionLocal() as db:
        report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
        if report is None or report.email_status != STATUS_MENUNGGU:
            return None
        user = (await db.execute(select(User).where(User.id == report.user_id))).scalar_one_or_none()
        if user is None:   # akun terhapus: laporannya ikut terhapus (CASCADE)
            return None
        pengaturan = (await db.execute(
            select(ReportSettings).where(ReportSettings.user_id == user.id)
        )).scalar_one_or_none()
        status, alasan = status_awal(user, pengaturan)
        if status != STATUS_MENUNGGU:
            lewati = await db.execute(
                update(Report)
                .where(Report.id == report_id, Report.email_status == STATUS_MENUNGGU)
                .values(email_status=STATUS_DILEWATI, email_alasan=alasan)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            return "dilewati" if lewati.rowcount == 1 else None
        klaim = await db.execute(
            update(Report)
            .where(Report.id == report_id, Report.email_status == STATUS_MENUNGGU, _boleh_dicoba(sekarang))
            .values(email_status=STATUS_MENGIRIM, email_terakhir_at=sekarang)
            .execution_options(synchronize_session=False)
        )
        if klaim.rowcount != 1:
            await db.rollback()
            return None
        # Semua yang dibutuhkan dibaca sebelum commit; PDF dan SMTP berjalan tanpa memegang koneksi.
        tujuan, nama, user_id = user.email, user.name, user.id
        data, jenis, mulai, akhir = report.data, report.jenis, report.periode_mulai, report.periode_akhir
        kata_sandi, lampiran = lampiran_untuk(pengaturan)
        await db.commit()

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
    return await _simpan_hasil(report_id, terkirim, sekarang)


async def _simpan_hasil(report_id, terkirim: bool, sekarang: datetime) -> str | None:
    """Simpan hasil kiriman laporan yang diklaim jalan ini, menurut id saja: selama `mengirim` hanya pengklaimnya yang
    menulis (laporan yang dikembalikan langkah 1 di tengah kiriman yang sangat lambat belum boleh dicoba lagi sebelum
    `JEDA_COBA_ULANG` sejak klaim ini). Kiriman yang berhasil selalu dicatat `terkirim`, supaya tidak dikirim lagi."""
    async with AsyncSessionLocal() as db:
        report = (await db.execute(
            select(Report).where(Report.id == report_id).with_for_update()
        )).scalar_one_or_none()
        if report is None:   # dihapus selagi dikirim (hapus akun)
            return "terkirim" if terkirim else None
        if terkirim:
            report.email_status, report.email_alasan, report.email_terkirim_at = STATUS_TERKIRIM, None, sekarang
            await db.commit()
            return "terkirim"
        percobaan = (report.email_percobaan or 0) + 1
        report.email_percobaan = percobaan
        if percobaan < MAKS_PERCOBAAN:
            report.email_status = STATUS_MENUNGGU
            await db.commit()
            return "dicoba_lagi"
        report.email_status, report.email_alasan = STATUS_GAGAL, ALASAN_SMTP
        await db.commit()
    logger.error("email laporan %s gagal dikirim %s kali; tidak dicoba lagi (alasan smtp)", report_id, percobaan)
    return "gagal"


async def hidupkan_lagi(db, user_id: UUID, alasan: tuple[str, ...], sekarang: datetime | None = None) -> int:
    """Keputusan rencana 2: laporan `user_id` yang `dilewati` dengan salah satu `alasan` dan terbit paling lama
    `JENDELA_TERBIT_HARI` hari sebelum `sekarang` kembali `menunggu` (alasan dikosongkan; percobaan dan waktu percobaan
    terakhirnya tetap, jadi batas percobaan dan jedanya tetap berlaku). Yang lebih tua tidak dikirim lagi. Dipanggil
    sesudah verifikasi email berhasil (`belum_verifikasi`, `tanpa_email`) dan saat `email_on` dinyalakan
    (`dimatikan`). TIDAK commit: perubahannya ikut transaksi pemanggil. Mengembalikan jumlah laporan yang
    dihidupkan."""
    from app.services.laporan.job import JENDELA_TERBIT_HARI   # Ruling P3: job.py mengimpor modul ini

    sekarang = sekarang or datetime.now(timezone.utc)
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
