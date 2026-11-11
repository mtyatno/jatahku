"""Worker email laporan: proses tersendiri yang menjalankan antrean email laporan dengan laju tetap (spec
2026-11-11-worker-email-laporan-design bagian 3; ruling P3, P4, P8). Dijalankan `python -m
app.services.laporan.worker_email` dari `/opt/jatahku/app`; memuat pengaturan yang sama dengan API, tanpa FastAPI,
scheduler, atau bot.

Loop: tulis tanda hidup, satu putaran `antrean_email.putaran_antrean`. Kelompok penuh → langsung putaran berikutnya;
selainnya, atau bila putaran galat (dicatat), tunggu `JEDA_KOSONG` detik yang terputus seketika oleh permintaan
berhenti. Sebelum setiap laporan: pacu (`1 / laju` detik dari awal kiriman sebelumnya) dan tanda hidup bila sudah
`JEDA_TANDA` detik. Berhenti (SIGTERM/SIGINT) dicek sebelum setiap putaran dan oleh putaran tepat sebelum klaim, jadi
tidak ada putaran atau klaim baru; kiriman yang sedang berjalan diselesaikan, lalu keluar 0.

Pemutus: hasil setiap laporan yang diproses (`sesudah_laporan`) dihitung; `gagal`, `dicoba_lagi`, dan galat (None)
berturut-turut menambah hitungan, `terkirim` mereset, `dilewati` membiarkan. Pada `BATAS_GAGAL_BERUNTUN` putaran itu
tidak mengklaim apa pun lagi, worker mencatat WARNING dan menunggu `JEDA_GANGGUAN` detik (terputus seketika oleh
permintaan berhenti), mereset hitungan, lalu lanjut. Jadi gangguan SMTP atau kuota penyedia menghabiskan percobaan
paling banyak lima laporan per jeda, bukan seluruh antrean.

Tanda hidup: kunci Redis `KUNCI_HIDUP`, waktu UTC ISO, TTL `TTL_HIDUP`; artinya "putaran terakhir berjalan". Ditulis di
awal setiap putaran kecuali putaran yang langsung menyusul putaran galat (mis. database tidak terjangkau), yang
menulisnya begitu ia selesai; putaran pertama selalu menulis. Redis tidak terjangkau dicatat sekali per putaran (teks
tetap, tanpa pesan galatnya) dan pengiriman tetap jalan. Log tanpa alamat, token, atau kata sandi; hanya logger
`jatahku` yang mencatat INFO, pihak ketiga (mis. fontTools) mulai WARNING (`pasang_log`).
"""
import asyncio
import logging
import math
import signal
import sys
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.services.laporan import antrean_email

logger = logging.getLogger("jatahku.laporan")

KUNCI_HIDUP = "laporan:worker_email:hidup"
TTL_HIDUP = 7200  # 2 jam: alarm masih bisa menyebut "sejak HH:MM"; hidup tetap ≤ 10 menit (pantau_email)
JEDA_KOSONG = 60.0
JEDA_TANDA = 60.0
LAJU_MIN = 0.1
LAJU_MAKS = 20.0
LAJU_BAWAAN = 3.0
BATAS_WAKTU_REDIS = 5   # detik; Redis yang menggantung tidak boleh menahan pengiriman
BATAS_GAGAL_BERUNTUN = 5
JEDA_GANGGUAN = 300.0
_HASIL_GAGAL = ("gagal", "dicoba_lagi", None)


def laju_dari_pengaturan(nilai) -> float:
    """Laju (email per detik) dari `EMAIL_LAPORAN_PER_DETIK` (teks .env, atau angka). Kosong/None → bawaan; satu koma
    dibaca sebagai pemisah desimal ("0,5" → 0.5); bukan angka → bawaan dengan peringatan (tanpa isinya: bisa saja
    rahasia salah baris); di luar `LAJU_MIN`-`LAJU_MAKS` → batas terdekat dengan peringatan."""
    if nilai is None or isinstance(nilai, bool) or (isinstance(nilai, str) and not nilai.strip()):
        return LAJU_BAWAAN
    if isinstance(nilai, str) and nilai.count(",") == 1 and "." not in nilai:
        nilai = nilai.replace(",", ".")
    try:
        laju = float(nilai)
    except (TypeError, ValueError):
        laju = math.nan
    if math.isnan(laju):
        logger.warning("EMAIL_LAPORAN_PER_DETIK bukan angka; dipakai bawaan %s email per detik", LAJU_BAWAAN)
        return LAJU_BAWAAN
    terbatas = min(max(laju, LAJU_MIN), LAJU_MAKS)
    if terbatas != laju:
        logger.warning("EMAIL_LAPORAN_PER_DETIK %s di luar %s-%s; dipakai %s", laju, LAJU_MIN, LAJU_MAKS, terbatas)
    return terbatas


class Pemacu:
    """Menjaga jarak `1 / per_detik` detik antara awal dua kiriman; kiriman lambat tidak menambah jeda. Panggilan
    pertama tidak menunggu."""

    def __init__(self, per_detik: float, *, jam=time.monotonic, tidur=asyncio.sleep):
        self.jarak = 1.0 / per_detik
        self.jam = jam
        self.tidur = tidur
        self.terakhir = None

    async def tunggu(self) -> None:
        if self.terakhir is not None:
            sisa = self.jarak - (self.jam() - self.terakhir)
            if sisa > 0:
                await self.tidur(sisa)
        self.terakhir = self.jam()


async def tulis_tanda_hidup(redis, sekarang: datetime) -> bool:
    """`SET KUNCI_HIDUP <waktu UTC ISO> EX TTL_HIDUP`. Galat Redis → False (tidak melempar, tidak mencatat)."""
    try:
        await redis.set(KUNCI_HIDUP, sekarang.astimezone(timezone.utc).isoformat(), ex=TTL_HIDUP)
    except Exception:
        return False
    return True


async def tunggu_berhenti(berhenti: asyncio.Event, detik: float) -> None:
    """Tunggu `detik`, atau kurang bila `berhenti` dinyalakan."""
    try:
        await asyncio.wait_for(berhenti.wait(), detik)
    except asyncio.TimeoutError:
        pass


def _sekarang_utc() -> datetime:
    return datetime.now(timezone.utc)


async def jalankan(
    berhenti: asyncio.Event,
    *,
    redis=None,
    per_detik: float | None = None,
    putaran=antrean_email.putaran_antrean,
    jam=time.monotonic,
    tidur=asyncio.sleep,
    tunggu_kosong=tunggu_berhenti,
    waktu_utc=_sekarang_utc,
) -> None:
    """Loop worker sampai `berhenti` dinyalakan (docstring modul). `redis=None` → klien dari `REDIS_URL`, ditutup saat
    selesai; `per_detik=None` → `EMAIL_LAPORAN_PER_DETIK`. `jam`, `tidur`, `tunggu_kosong`, `waktu_utc`: celah tes
    (ruling P3)."""
    settings = get_settings()
    laju = laju_dari_pengaturan(settings.EMAIL_LAPORAN_PER_DETIK if per_detik is None else per_detik)
    milik_sendiri = redis is None
    if milik_sendiri:
        redis = aioredis.from_url(settings.REDIS_URL, socket_timeout=BATAS_WAKTU_REDIS,
                                  socket_connect_timeout=BATAS_WAKTU_REDIS)
    pemacu = Pemacu(laju, jam=jam, tidur=tidur)
    gangguan = {"beruntun": 0}
    putaran_gagal = False

    def sesudah_laporan(keluaran):
        if keluaran == "terkirim":
            gangguan["beruntun"] = 0
        elif keluaran in _HASIL_GAGAL:
            gangguan["beruntun"] += 1

    def harus_berhenti() -> bool:
        return berhenti.is_set() or gangguan["beruntun"] >= BATAS_GAGAL_BERUNTUN

    logger.info("worker email laporan menyala: %s email per detik", laju)
    try:
        while not berhenti.is_set():
            tanda = {"terakhir": jam(), "dicatat": False}

            async def tulis_tanda():
                tanda["terakhir"] = jam()
                if not await tulis_tanda_hidup(redis, waktu_utc()) and not tanda["dicatat"]:
                    tanda["dicatat"] = True
                    logger.warning("tanda hidup worker email laporan tidak bisa ditulis ke Redis; pengiriman lanjut")

            async def sebelum_laporan():
                await pemacu.tunggu()
                if jam() - tanda["terakhir"] >= JEDA_TANDA:
                    await tulis_tanda()

            tanda_ditunda = putaran_gagal   # putaran sebelumnya galat: tanda hidup menunggu putaran ini selesai
            if not tanda_ditunda:
                await tulis_tanda()
            try:
                hasil, penuh = await putaran(sebelum_laporan=sebelum_laporan, berhenti=harus_berhenti,
                                             sesudah_laporan=sesudah_laporan)
                if any(hasil.values()):
                    logger.info("email laporan: %s terkirim, %s gagal, %s dilewati, %s dicoba lagi",
                                hasil["terkirim"], hasil["gagal"], hasil["dilewati"], hasil["dicoba_lagi"])
            except Exception:
                logger.exception("putaran email laporan gagal; dicoba lagi dalam %s detik", JEDA_KOSONG)
                putaran_gagal, penuh = True, False
            else:
                putaran_gagal = False
                if tanda_ditunda:
                    await tulis_tanda()
            if berhenti.is_set():
                break
            if gangguan["beruntun"] >= BATAS_GAGAL_BERUNTUN:
                logger.warning("email laporan: %s kiriman berturut-turut gagal; worker jeda %s menit",
                               BATAS_GAGAL_BERUNTUN, int(JEDA_GANGGUAN // 60))
                await tunggu_kosong(berhenti, JEDA_GANGGUAN)
                gangguan["beruntun"] = 0
                continue
            if not penuh:
                await tunggu_kosong(berhenti, JEDA_KOSONG)
    finally:
        if milik_sendiri:
            await redis.aclose()
    logger.info("worker email laporan berhenti")


async def _utama() -> None:
    berhenti = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sinyal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sinyal, berhenti.set)
    await jalankan(berhenti)


def pasang_log(aliran=None) -> None:
    """Log worker ke `aliran` (bawaan stderr, untuk journald): akar WARNING, supaya pustaka pihak ketiga (fontTools
    mencatat ~70 baris INFO per PDF) tidak membanjiri jurnal; logger `jatahku` (`jatahku.laporan`, `jatahku.email`)
    INFO."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr if aliran is None else aliran,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("jatahku").setLevel(logging.INFO)


def main() -> None:
    """Pasang log (`pasang_log`) dan penangan SIGTERM/SIGINT, jalankan sampai berhenti, keluar 0."""
    pasang_log()
    asyncio.run(_utama())


if __name__ == "__main__":
    main()
