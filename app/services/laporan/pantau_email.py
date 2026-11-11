"""Pemantauan antrean email laporan dan alarm admin (spec 2026-11-11-worker-email-laporan bagian 6).

`keadaan_email` mengumpulkan angka antrean dan tanda hidup worker (dipakai kartu Admin); `periksa_alarm` dipanggil job
tiap jam dan mengirim alarm lewat Telegram admin. Alarm dicatat di `app_settings` (`alarm_email_laporan:<kode>`, waktu
UTC ISO) HANYA bila pesannya benar-benar terkirim, jadi alarm yang gagal terkirim dicoba lagi jam berikutnya. Alarm
per kejadian (`PER_KEJADIAN`): pemeriksaan yang mendapati syaratnya tidak berlaku menghapus catatannya, jadi kejadian
berikutnya langsung dialarmkan; selama satu kejadian berlanjut batas ulang `ULANG` tetap. `email_gagal` tidak pernah
dihapus: catatannya juga batas "gagal baru".
Pesan alarm tidak memuat alamat email atau id user; log tidak memuat isi pesan.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.models import AppSetting, Report, ReportSettings, User
from app.services.laporan import antrean_email, worker_email

logger = logging.getLogger("jatahku.laporan")

AMBANG_PENERIMA = 300
BATAS_HIDUP = timedelta(minutes=10)
BATAS_TERSENDAT_MENIT = 360
MASA_TENANG = timedelta(minutes=15)
ULANG = {
    "pindah_penyedia": timedelta(days=30),
    "worker_mati": timedelta(hours=24),
    "antrean_tersendat": timedelta(hours=24),
    "email_gagal": timedelta(hours=24),
}
KUNCI_ALARM = "alarm_email_laporan:{}"
PER_KEJADIAN = ("pindah_penyedia", "worker_mati", "antrean_tersendat")
WIB = timezone(timedelta(hours=7))
_HOST_LOKAL = ("localhost", "127.0.0.1", "::1")

# Waktu API menyala; diisi `lifespan` app/main.py. None = tanpa masa tenang `worker_mati`.
API_MENYALA: datetime | None = None


def _utc(waktu: datetime) -> datetime:
    """Waktu berzona UTC (SQLite dan teks tanpa zona sudah UTC)."""
    if waktu.tzinfo is None:
        return waktu.replace(tzinfo=timezone.utc)
    return waktu.astimezone(timezone.utc)


def _baca_waktu(teks) -> datetime | None:
    """Waktu UTC dari teks ISO (bytes atau str); tidak terbaca → None."""
    if isinstance(teks, bytes):
        try:
            teks = teks.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(teks, str):
        return None
    try:
        return _utc(datetime.fromisoformat(teks.strip()))
    except (ValueError, OverflowError):   # OverflowError: mis. 0001-01-01T00:00:00+05:00 ke UTC
        return None


async def _tanda_hidup(redis) -> datetime | None:
    """Tanda hidup terakhir worker; Redis tidak ada, galat, atau isinya tidak terbaca → None (tidak melempar)."""
    if redis is None:
        return None
    try:
        nilai = await redis.get(worker_email.KUNCI_HIDUP)
    except Exception:
        logger.warning("email laporan: tanda hidup worker tidak terbaca dari Redis")
        return None
    return _baca_waktu(nilai)


async def _hitung(db, *kondisi) -> int:
    return (await db.execute(select(func.count()).select_from(Report).where(*kondisi))).scalar_one()


async def keadaan_email(db, redis, sekarang: datetime) -> dict:
    """Angka antrean dan tanda hidup worker. `sekarang` berzona; semua hitungan di SQL."""
    sekarang = _utc(sekarang)
    r = Report
    terakhir = await _tanda_hidup(redis)
    hidup = terakhir is not None and sekarang - terakhir <= BATAS_HIDUP

    tertua = (await db.execute(
        select(func.min(r.terbit_at)).where(r.email_status == antrean_email.STATUS_MENUNGGU)
    )).scalar_one_or_none()
    tertua_menit = None if tertua is None else int((sekarang - _utc(tertua)) // timedelta(minutes=1))

    penerima = (await db.execute(
        select(func.count()).select_from(User)
        .outerjoin(ReportSettings, ReportSettings.user_id == User.id)
        .where(
            User.email_verified_at.is_not(None),
            # autoescape: `_` di LIKE cocok dengan karakter apa pun ("deleted1@…" tetap penerima)
            ~User.email.startswith(antrean_email.AWALAN_AKUN_NONAKTIF[0], autoescape=True),
            ~User.email.startswith(antrean_email.AWALAN_AKUN_NONAKTIF[1], autoescape=True),
            (ReportSettings.user_id.is_(None)) | (ReportSettings.email_on.is_not(False)),
        )
    )).scalar_one()

    pengaturan = get_settings()
    return {
        "worker_hidup": hidup,
        "worker_terakhir": terakhir.isoformat() if terakhir else None,
        "menunggu": await _hitung(db, r.email_status == antrean_email.STATUS_MENUNGGU),
        "tertua_menit": tertua_menit,
        "mengirim": await _hitung(db, r.email_status == antrean_email.STATUS_MENGIRIM),
        "terkirim_24_jam": await _hitung(
            db, r.email_status == antrean_email.STATUS_TERKIRIM, r.email_terkirim_at >= sekarang - timedelta(hours=24)),
        "gagal_7_hari": await _hitung(
            db, r.email_status == antrean_email.STATUS_GAGAL, r.email_terakhir_at >= sekarang - timedelta(days=7)),
        "penerima": penerima,
        "ambang_penerima": AMBANG_PENERIMA,
        "smtp_lokal": (pengaturan.SMTP_HOST or "").strip().lower() in _HOST_LOKAL,
        "laju_per_detik": worker_email.laju_dari_pengaturan(pengaturan.EMAIL_LAPORAN_PER_DETIK),
    }


async def _alarm_terakhir(db, kode: str) -> datetime | None:
    baris = await db.get(AppSetting, KUNCI_ALARM.format(kode))
    return None if baris is None else _baca_waktu(baris.value)


async def alarm_berlaku(db, keadaan: dict, sekarang: datetime) -> list[str]:
    """Kode alarm yang syaratnya terpenuhi sekarang, tanpa melihat batas ulang."""
    sekarang = _utc(sekarang)
    kode = []
    if keadaan["penerima"] >= AMBANG_PENERIMA and keadaan["smtp_lokal"]:
        kode.append("pindah_penyedia")
    if not keadaan["worker_hidup"]:
        kode.append("worker_mati")
    if keadaan["tertua_menit"] is not None and keadaan["tertua_menit"] > BATAS_TERSENDAT_MENIT:
        kode.append("antrean_tersendat")
    terakhir = await _alarm_terakhir(db, "email_gagal")
    sejak = terakhir if terakhir is not None else sekarang - timedelta(hours=24)
    if await _hitung(db, Report.email_status == antrean_email.STATUS_GAGAL, Report.email_terakhir_at > sejak):
        kode.append("email_gagal")
    return kode


def pesan_alarm(kode: str, keadaan: dict) -> str:
    """Teks alarm (spec bagian 6). Jam dalam WIB. Tanpa alamat email dan id user."""
    if kode == "pindah_penyedia":
        return (f"📬 Penerima email laporan sudah {keadaan['penerima']}. Saatnya pindah ke penyedia email "
                "transaksional — langkahnya di AGENTS.md bagian 'Pindah penyedia email'.")
    if kode == "worker_mati":
        terakhir = _baca_waktu(keadaan.get("worker_terakhir"))
        if terakhir is not None:
            return (f"⚠️ Worker email laporan tidak memberi tanda hidup sejak {terakhir.astimezone(WIB):%H:%M} WIB. "
                    "Cek: sudo systemctl status jatahku-worker")
        return "⚠️ Worker email laporan tidak memberi tanda hidup. Cek: sudo systemctl status jatahku-worker"
    if kode == "antrean_tersendat":
        return (f"⚠️ Antrean email laporan tersendat: {keadaan['menunggu']} menunggu, tertua "
                f"{keadaan['tertua_menit'] // 60} jam. Cek: sudo journalctl -u jatahku-worker -n 50")
    if kode == "email_gagal":
        return (f"⚠️ Ada email laporan yang gagal dikirim ({keadaan['gagal_7_hari']} dalam 7 hari). Periksa SMTP, "
                'lalu ikuti "kirim ulang email" di docs/laporan-berkala.md.')
    raise ValueError(f"kode alarm tidak dikenal: {kode}")


async def periksa_alarm(
    db, redis, sekarang: datetime, *, kirim: Callable[[str], Awaitable[bool]], api_menyala: datetime | None,
) -> list[str]:
    """Kirim alarm yang berlaku dan sudah lewat batas ulangnya; kembalikan kode yang terkirim. Waktu dicatat hanya
    bila `kirim` mengembalikan True. `worker_mati` dilewati selama `MASA_TENANG` sesudah `api_menyala`. Kode
    `PER_KEJADIAN` yang syaratnya tidak berlaku kehilangan catatannya (kejadian berakhir)."""
    sekarang = _utc(sekarang)
    keadaan = await keadaan_email(db, redis, sekarang)
    berlaku = await alarm_berlaku(db, keadaan, sekarang)
    for kode in PER_KEJADIAN:
        if kode not in berlaku:
            baris = await db.get(AppSetting, KUNCI_ALARM.format(kode))
            if baris is not None:
                await db.delete(baris)
    terkirim = []
    for kode in berlaku:
        if kode == "worker_mati" and api_menyala is not None and sekarang - _utc(api_menyala) < MASA_TENANG:
            continue
        terakhir = await _alarm_terakhir(db, kode)
        if terakhir is not None and sekarang - terakhir < ULANG[kode]:
            continue
        try:
            ok = bool(await kirim(pesan_alarm(kode, keadaan)))
        except Exception:
            logger.warning("email laporan: alarm %s gagal dikirim", kode)
            ok = False
        if not ok:
            continue
        kunci = KUNCI_ALARM.format(kode)
        baris = await db.get(AppSetting, kunci)
        if baris is None:
            db.add(AppSetting(key=kunci, value=sekarang.isoformat()))
        else:
            baris.value = sekarang.isoformat()
        terkirim.append(kode)
    await db.commit()
    return terkirim


async def kirim_telegram_admin(teks: str) -> bool:
    """Kirim `teks` (tanpa `parse_mode`) ke admin lewat bot Telegram. Token atau `ADMIN_TELEGRAM_ID` kosong, atau
    galat apa pun → False dengan peringatan tanpa isi pesan."""
    try:
        from telegram import Bot
        pengaturan = get_settings()
        if not (pengaturan.TELEGRAM_BOT_TOKEN and pengaturan.ADMIN_TELEGRAM_ID):
            logger.warning("email laporan: alarm tidak dikirim, token atau ADMIN_TELEGRAM_ID kosong")
            return False
        await Bot(token=pengaturan.TELEGRAM_BOT_TOKEN).send_message(
            chat_id=int(pengaturan.ADMIN_TELEGRAM_ID), text=teks)
        return True
    except Exception as exc:
        logger.warning("email laporan: alarm tidak terkirim ke Telegram (%s)", type(exc).__name__)
        return False
