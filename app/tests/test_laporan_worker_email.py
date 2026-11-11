"""Worker email laporan (`app/services/laporan/worker_email.py`; spec 2026-11-11-worker-email-laporan-design bagian 3,
ruling P3, P4, P8).

Tanpa database dan tanpa Redis sungguhan: `putaran` (satu putaran antrean) tiruan yang mengikuti naskah, Redis tiruan
dengan `set`, jam monotonik dan `tidur` tiruan (tidur memajukan jam), tunggu kosong tiruan yang mencatat lamanya.
Run: python -m unittest app.tests.test_laporan_worker_email -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import io
import logging
import signal
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.core.config import Settings
from app.models.models import Report, User
from app.services.laporan import antrean_email, pdf, worker_email
from app.services.laporan.antrean_email import hasil_kosong
from app.tests import test_laporan_antrean_email as uji_antrean
from app.tests.test_laporan_pdf import DATA as DATA_PDF, KATA_SANDI as SANDI_PDF

UTC = timezone.utc
T_UTC = datetime(2026, 11, 12, 3, 30, tzinfo=UTC)


class JamTiruan:
    """Jam monotonik tiruan; `tidur` mencatat lamanya dan memajukan jam."""

    def __init__(self):
        self.t = 1000.0
        self.tidurnya = []

    def __call__(self):
        return self.t

    async def tidur(self, detik):
        self.tidurnya.append(detik)
        self.t += detik


class RedisTiruan:
    def __init__(self, galat=None, catatan=None):
        self.galat = galat
        self.catatan = catatan
        self.set_dipanggil = []
        self.ditutup = False

    async def set(self, kunci, nilai, ex=None):
        if self.galat is not None:
            raise self.galat
        self.set_dipanggil.append((kunci, nilai, ex))
        if self.catatan is not None:
            self.catatan.append(("tanda",))
        return True

    async def aclose(self):
        self.ditutup = True


class Naskah:
    """`putaran` tiruan: setiap panggilan menjalankan langkah berikutnya `(fungsi async atau None, hasil, penuh)` atau
    melempar galat. Sesudah naskah habis, menyalakan `berhenti` (jaring pengaman supaya tes tidak berputar terus)."""

    def __init__(self, berhenti, langkah, catatan):
        self.berhenti = berhenti
        self.langkah = list(langkah)
        self.catatan = catatan
        self.dipanggil = 0
        self.fungsi_berhenti = []
        self.sesudah = None

    async def __call__(self, jam=None, *, sebelum_laporan=None, berhenti=None, sesudah_laporan=None):
        await asyncio.sleep(0)   # titik serah: loop yang tak pernah berhenti gagal oleh batas waktu tes, tidak menggantung
        self.dipanggil += 1
        self.catatan.append(("putaran", self.dipanggil))
        self.fungsi_berhenti.append(berhenti)
        self.sesudah = sesudah_laporan
        if not self.langkah:
            self.berhenti.set()
            return hasil_kosong(), False
        langkah = self.langkah.pop(0)
        if isinstance(langkah, Exception):
            raise langkah
        aksi, hasil, penuh = langkah
        if aksi is not None:
            await aksi(sebelum_laporan, berhenti)
        return hasil, penuh


def hasil(terkirim=0, gagal=0, dilewati=0, dicoba_lagi=0):
    return {"terkirim": terkirim, "gagal": gagal, "dilewati": dilewati, "dicoba_lagi": dicoba_lagi}


class TestLaju(unittest.TestCase):
    def test_laju_dari_pengaturan(self):
        kasus = [
            (None, 3.0), ("", 3.0), ("  ", 3.0), ("abc", 3.0), ("nan", 3.0), (True, 3.0),
            ("0", 0.1), ("-1", 0.1), ("500", 20.0), ("2.5", 2.5), (" 4 ", 4.0), ("3", 3.0), ("inf", 20.0),
            ("0,5", 0.5), ("2,5", 2.5), (" 0,5 ", 0.5), ("1,2,3", 3.0), (",", 3.0), ("1.2,3", 3.0),
            (0, 0.1), (-1, 0.1), (500, 20.0), (2.5, 2.5), (0.1, 0.1), (20, 20.0),
        ]
        with self.assertLogs("jatahku.laporan", level="WARNING"):   # peringatan yang diharapkan, tidak ke stderr
            for nilai, harapan in kasus:
                with self.subTest(nilai=nilai):
                    self.assertEqual(worker_email.laju_dari_pengaturan(nilai), harapan)

    def test_laju_di_luar_batas_diperingatkan_tanpa_isi_nilai_rusak(self):
        with self.assertLogs("jatahku.laporan", level="WARNING") as log:
            worker_email.laju_dari_pengaturan("500")
            worker_email.laju_dari_pengaturan("rahasia-salah-baris")
        teks = "\n".join(log.output)
        self.assertIn("500", teks)
        self.assertNotIn("rahasia-salah-baris", teks)

    def test_pengaturan_laju_apa_pun_tidak_menggagalkan_settings(self):
        self.assertEqual(Settings().EMAIL_LAPORAN_PER_DETIK, "3")
        self.assertEqual(Settings(EMAIL_LAPORAN_PER_DETIK="").EMAIL_LAPORAN_PER_DETIK, "")
        for nilai in ("", "abc", "-1", "1e9"):
            with self.subTest(env=nilai), patch.dict(os.environ, {"EMAIL_LAPORAN_PER_DETIK": nilai}):
                self.assertEqual(Settings().EMAIL_LAPORAN_PER_DETIK, nilai)


class TestPemacu(unittest.IsolatedAsyncioTestCase):
    async def test_pemacu_menjaga_jarak(self):
        jam = JamTiruan()
        pemacu = worker_email.Pemacu(4, jam=jam, tidur=jam.tidur)
        await pemacu.tunggu()                  # panggilan pertama: tanpa tidur
        self.assertEqual(jam.tidurnya, [])
        jam.t += 0.1                           # kiriman cepat: sisa jarak ditidurkan
        await pemacu.tunggu()
        self.assertEqual(len(jam.tidurnya), 1)
        self.assertAlmostEqual(jam.tidurnya[0], 0.15)
        jam.t += 1.0                           # kiriman lambat: tanpa tidur
        await pemacu.tunggu()
        self.assertEqual(len(jam.tidurnya), 1)
        await pemacu.tunggu()                  # langsung lagi: jarak penuh dari awal kiriman sebelumnya
        self.assertAlmostEqual(jam.tidurnya[1], 0.25)


class TestJalankan(unittest.IsolatedAsyncioTestCase):
    def siapkan(self, langkah, redis=None, per_detik=4):
        self.berhenti = asyncio.Event()
        self.catatan = []
        self.jam = JamTiruan()
        self.redis = RedisTiruan() if redis is None else redis
        self.naskah = Naskah(self.berhenti, langkah, self.catatan)

        async def tunggu_kosong(berhenti, detik):
            self.catatan.append(("tunggu", detik))

        self.tunggu_kosong = tunggu_kosong
        self.per_detik = per_detik

    async def jalankan(self):
        await asyncio.wait_for(worker_email.jalankan(
            self.berhenti, redis=self.redis, per_detik=self.per_detik, putaran=self.naskah,
            jam=self.jam, tidur=self.jam.tidur, tunggu_kosong=self.tunggu_kosong, waktu_utc=lambda: T_UTC,
        ), 2)

    async def test_kelompok_penuh_langsung_lanjut_kosong_menunggu(self):
        self.siapkan([(None, hasil(terkirim=100), True), (None, hasil(terkirim=3), False)])
        await self.jalankan()
        self.assertEqual(self.catatan[:4], [("putaran", 1), ("putaran", 2), ("tunggu", 60.0), ("putaran", 3)])

    async def test_berhenti_di_tengah_putaran(self):
        async def aksi(sebelum_laporan, berhenti):
            await sebelum_laporan()
            self.assertFalse(berhenti())
            self.berhenti.set()
            self.assertTrue(berhenti())

        for penuh in (False, True):   # penuh=True: henti datang di laporan terakhir kelompok penuh
            with self.subTest(penuh=penuh):
                self.siapkan([(aksi, hasil(terkirim=1), penuh), (None, hasil(), False)])
                await self.jalankan()
                self.assertEqual(self.naskah.dipanggil, 1)
                self.assertEqual(self.catatan, [("putaran", 1)])   # tanpa putaran baru, tanpa tunggu
                self.assertTrue(self.naskah.fungsi_berhenti[0]())

    async def test_berhenti_sebelum_mulai_tanpa_putaran(self):
        self.siapkan([(None, hasil(), False)])
        self.berhenti.set()
        await self.jalankan()
        self.assertEqual(self.naskah.dipanggil, 0)

    async def test_berhenti_saat_menunggu_tanpa_putaran_baru(self):
        self.siapkan([(None, hasil(), False), (None, hasil(), False)])

        async def tunggu_kosong(berhenti, detik):
            self.catatan.append(("tunggu", detik))
            berhenti.set()

        self.tunggu_kosong = tunggu_kosong
        await self.jalankan()
        self.assertEqual(self.catatan, [("putaran", 1), ("tunggu", 60.0)])

    async def test_galat_putaran_tidak_menghentikan_worker(self):
        self.siapkan([RuntimeError("database putus"), RuntimeError("database putus"), (None, hasil(), False)])
        with self.assertLogs("jatahku.laporan", level="ERROR") as log:
            await self.jalankan()
        self.assertEqual(self.catatan[:5], [("putaran", 1), ("tunggu", 60.0), ("putaran", 2), ("tunggu", 60.0),
                                            ("putaran", 3)])
        self.assertEqual(sum("putaran email laporan gagal" in baris for baris in log.output), 2)

    async def test_ringkasan_dicatat_hanya_bila_ada_hasil(self):
        self.siapkan([(None, hasil(terkirim=2, gagal=1, dilewati=3, dicoba_lagi=4), False), (None, hasil(), False)])
        with self.assertLogs("jatahku.laporan", level="INFO") as log:
            await self.jalankan()
        ringkasan = [r.getMessage() for r in log.records if r.getMessage().startswith("email laporan:")]
        self.assertEqual(ringkasan, ["email laporan: 2 terkirim, 1 gagal, 3 dilewati, 4 dicoba lagi"])

    async def test_pacu_dipakai_sebelum_setiap_laporan(self):
        async def aksi(sebelum_laporan, berhenti):
            for _ in range(3):
                await sebelum_laporan()

        self.siapkan([(aksi, hasil(terkirim=3), False)], per_detik=4)
        await self.jalankan()
        self.assertEqual(len(self.jam.tidurnya), 2)
        for detik in self.jam.tidurnya:
            self.assertAlmostEqual(detik, 0.25)

    async def test_tanda_hidup_ditulis_dan_redis_mati_tidak_menghentikan(self):
        self.siapkan([(None, hasil(), False)])
        await self.jalankan()
        self.assertEqual(worker_email.TTL_HIDUP, 7200)
        self.assertEqual(self.redis.set_dipanggil[0], (worker_email.KUNCI_HIDUP, T_UTC.isoformat(), 7200))
        self.assertEqual(datetime.fromisoformat(self.redis.set_dipanggil[0][1]).utcoffset().total_seconds(), 0)

        redis_mati = RedisTiruan(galat=ConnectionError("Error 111 connecting to localhost:6379"))
        self.assertFalse(await worker_email.tulis_tanda_hidup(redis_mati, T_UTC))

        async def aksi(sebelum_laporan, berhenti):
            for _ in range(3):
                self.jam.t += 61
                await sebelum_laporan()

        self.siapkan([(aksi, hasil(terkirim=3), False)], redis=redis_mati)   # dua putaran (naskah habis di ke-2)
        with self.assertLogs("jatahku.laporan", level="WARNING") as log:
            await self.jalankan()
        self.assertGreaterEqual(self.naskah.dipanggil, 2)
        tanda_gagal = [b for b in log.output if "tanda hidup" in b]
        self.assertEqual(len(tanda_gagal), 2)   # sekali per putaran, bukan per percobaan tulis

    async def test_tanda_hidup_diperbarui_selama_mengirim(self):
        async def aksi(sebelum_laporan, berhenti):
            await sebelum_laporan()            # < 60 detik sejak awal putaran: tidak ditulis
            self.jam.t += 30
            await sebelum_laporan()
            self.jam.t += 31                   # 61 detik sejak tanda terakhir: ditulis
            await sebelum_laporan()

        self.siapkan([(aksi, hasil(terkirim=3), False)])
        await self.jalankan()
        # awal putaran 1, satu kali selama mengirim, awal putaran 2 (naskah habis)
        self.assertEqual(len(self.redis.set_dipanggil), 3)

    async def test_tanda_hidup_tidak_ditulis_sesudah_putaran_gagal(self):
        # F-5: tanda hidup berarti "putaran terakhir berjalan". Putaran pertama tetap menulis di awal; putaran yang
        # langsung menyusul putaran gagal tidak menulis di awal, dan menulis lagi begitu putaran itu selesai.
        self.siapkan([RuntimeError("database putus"), RuntimeError("database putus"), (None, hasil(), False)])
        self.redis.catatan = self.catatan
        with self.assertLogs("jatahku.laporan", level="ERROR"):
            await self.jalankan()
        self.assertEqual(self.catatan, [
            ("tanda",), ("putaran", 1), ("tunggu", 60.0),
            ("putaran", 2), ("tunggu", 60.0),
            ("putaran", 3), ("tanda",), ("tunggu", 60.0),
            ("tanda",), ("putaran", 4),
        ])

    async def test_ringkasan_rusak_tidak_menghentikan_worker(self):
        # F-9: ringkasan di dalam `try` putaran: hasil yang rusak dicatat sebagai putaran gagal, worker lanjut.
        self.siapkan([(None, {"terkirim": 1}, False), (None, hasil(), False)])
        with self.assertLogs("jatahku.laporan", level="ERROR") as log:
            await self.jalankan()
        self.assertEqual(self.naskah.dipanggil, 3)
        self.assertEqual(sum("putaran email laporan gagal" in baris for baris in log.output), 1)

    # ------------------------------------------------------------------ pemutus (F-4)

    def aksi_hasil(self, keluaran, cek):
        """Aksi putaran: per keluaran, pacu lalu `sesudah_laporan(keluaran)`; `cek` mencatat `berhenti()` sesudahnya."""
        async def aksi(sebelum_laporan, berhenti):
            for k in keluaran:
                if berhenti():
                    return
                await sebelum_laporan()
                self.naskah.sesudah(k)
                cek.append(berhenti())
        return aksi

    async def test_pemutus_lima_gagal_beruntun_jeda_lalu_lanjut(self):
        self.assertEqual((worker_email.BATAS_GAGAL_BERUNTUN, worker_email.JEDA_GANGGUAN), (5, 300.0))
        cek1, cek2 = [], []
        self.siapkan([
            (self.aksi_hasil(["gagal", "dicoba_lagi", None, "dicoba_lagi", "gagal", "terkirim"], cek1),
             hasil(gagal=2, dicoba_lagi=2), False),
            (self.aksi_hasil(["terkirim", "gagal"], cek2), hasil(terkirim=1, dicoba_lagi=1), False),
        ])
        with self.assertLogs("jatahku.laporan", level="WARNING") as log:
            await self.jalankan()
        self.assertEqual(cek1, [False, False, False, False, True])   # laporan ke-6 tidak diproses
        self.assertEqual(cek2, [False, False])                        # hitungan direset sesudah jeda
        self.assertEqual(self.catatan[:4], [("putaran", 1), ("tunggu", 300.0), ("putaran", 2), ("tunggu", 60.0)])
        self.assertIn("email laporan: 5 kiriman berturut-turut gagal; worker jeda 5 menit",
                      [r.getMessage() for r in log.records if r.levelno == logging.WARNING])

    async def test_pemutus_terkirim_mereset_dilewati_tidak(self):
        cek1, cek2 = [], []
        self.siapkan([
            (self.aksi_hasil(["gagal"] * 4 + ["terkirim"] + ["gagal"] * 4, cek1), hasil(), False),
            (self.aksi_hasil(["gagal"] * 4 + ["dilewati"] + ["dicoba_lagi"], cek2), hasil(), False),
        ])
        await self.jalankan()
        self.assertEqual(cek1, [False] * 9)
        # hitungan berlanjut antarputaran: 4 dari putaran 1 + 4 = 8 ≥ 5 sudah di laporan pertama putaran 2
        self.assertEqual(cek2[0], True)

        cek = []
        self.siapkan([(self.aksi_hasil(["gagal"] * 4 + ["dilewati"] + ["dicoba_lagi"], cek), hasil(), False)])
        await self.jalankan()
        self.assertEqual(cek, [False, False, False, False, False, True])
        self.assertEqual(self.catatan[:2], [("putaran", 1), ("tunggu", 300.0)])

    async def test_berhenti_saat_jeda_gangguan_keluar_seketika(self):
        cek = []
        self.siapkan([(self.aksi_hasil(["gagal"] * 5, cek), hasil(gagal=5), False), (None, hasil(), False)])
        self.tunggu_kosong = worker_email.tunggu_berhenti      # jeda sungguhan 300 detik, diputus oleh berhenti
        asyncio.get_running_loop().call_later(0.05, self.berhenti.set)
        mulai = asyncio.get_running_loop().time()
        with self.assertLogs("jatahku.laporan", level="WARNING"):
            await self.jalankan()                                # batas 2 detik
        self.assertLess(asyncio.get_running_loop().time() - mulai, 2)
        self.assertEqual(self.naskah.dipanggil, 1)

    async def test_berhenti_tetap_dihormati_tanpa_gangguan(self):
        async def aksi(sebelum_laporan, berhenti):
            self.naskah.sesudah("gagal")
            self.assertFalse(berhenti())
            self.berhenti.set()
            self.assertTrue(berhenti())

        self.siapkan([(aksi, hasil(gagal=1), False), (None, hasil(), False)])
        await self.jalankan()
        self.assertEqual(self.catatan, [("putaran", 1)])

    async def test_log_tanpa_alamat(self):
        redis_mati = RedisTiruan(galat=ConnectionError("galat redis untuk pemilik@contoh.id"))
        # Galat putaran dicatat dengan traceback (logger.exception, seperti galat per laporan di antrean_email); galat
        # Redis dengan teks tetap saja, tanpa pesan galatnya.
        self.siapkan([RuntimeError("database putus"), (None, hasil(terkirim=1), False)],
                     redis=redis_mati)
        with self.assertLogs("jatahku.laporan", level="DEBUG") as log:
            await self.jalankan()
        teks = "\n".join(log.output)
        self.assertIn("menyala", teks)
        self.assertNotIn("@", teks)

    async def test_redis_milik_sendiri_ditutup(self):
        self.siapkan([(None, hasil(), False)])
        redis = RedisTiruan()
        with patch.object(worker_email.aioredis, "from_url", return_value=redis) as dari_url:
            await asyncio.wait_for(worker_email.jalankan(
                self.berhenti, per_detik=3, putaran=self.naskah, jam=self.jam, tidur=self.jam.tidur,
                tunggu_kosong=self.tunggu_kosong, waktu_utc=lambda: T_UTC), 5)
        dari_url.assert_called_once()
        self.assertTrue(redis.ditutup)

        self.siapkan([(None, hasil(), False)])
        await self.jalankan()
        self.assertFalse(self.redis.ditutup)   # Redis dari pemanggil tidak ditutup worker


class TestTungguBerhenti(unittest.IsolatedAsyncioTestCase):
    async def test_tunggu_terputus_seketika_oleh_berhenti(self):
        berhenti = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, berhenti.set)
        mulai = asyncio.get_running_loop().time()
        await worker_email.tunggu_berhenti(berhenti, 30)
        self.assertLess(asyncio.get_running_loop().time() - mulai, 2)

    async def test_tunggu_habis_tanpa_berhenti(self):
        berhenti = asyncio.Event()
        await worker_email.tunggu_berhenti(berhenti, 0.05)
        self.assertFalse(berhenti.is_set())


class TestMain(unittest.TestCase):
    def test_sigterm_menghentikan_dan_keluar_normal(self):
        dipanggil = {}

        async def jalankan_tiruan(berhenti, **_):
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(berhenti.wait(), 5)
            dipanggil["berhenti"] = berhenti.is_set()

        with patch.object(worker_email, "jalankan", jalankan_tiruan), \
                patch.object(worker_email, "pasang_log") as pasang:
            worker_email.main()   # tidak melempar SystemExit bukan 0, tidak mati oleh SIGTERM
        self.assertTrue(dipanggil["berhenti"])
        pasang.assert_called_once_with()
        # penangan sinyal dilepas bersama loop: SIGTERM kembali ke bawaan
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)


class TestLog(unittest.TestCase):
    """F-1: log worker tidak membuka logger akar (fontTools mencatat ~70 baris INFO per PDF)."""

    def setUp(self):
        akar, jatahku = logging.getLogger(), logging.getLogger("jatahku")
        keadaan = (akar.level, akar.handlers[:], jatahku.level)

        def pulihkan():
            for h in akar.handlers[:]:
                if h not in keadaan[1]:
                    akar.removeHandler(h)
            for h in keadaan[1]:
                if h not in akar.handlers:
                    akar.addHandler(h)
            akar.setLevel(keadaan[0])
            jatahku.setLevel(keadaan[2])

        self.addCleanup(pulihkan)
        for h in akar.handlers[:]:       # basicConfig hanya memasang penangan bila akar belum punya
            akar.removeHandler(h)

    def test_pihak_ketiga_di_bawah_warning_tidak_lolos(self):
        aliran = io.StringIO()
        worker_email.pasang_log(aliran)
        catatan = []

        class Penampung(logging.Handler):
            def emit(self, record):
                catatan.append(record)

        logging.getLogger().addHandler(Penampung())
        self.assertEqual(logging.getLogger().level, logging.WARNING)
        pdf.render_pdf(DATA_PDF, SANDI_PDF)
        logging.getLogger("jatahku.laporan").info("worker email laporan menyala: 3.0 email per detik")

        luar = [r for r in catatan if r.levelno < logging.WARNING
                and not (r.name == "jatahku" or r.name.startswith("jatahku."))]
        self.assertEqual(luar, [])
        self.assertIn("jatahku.laporan", [r.name for r in catatan if r.levelno == logging.INFO])
        self.assertIn("INFO jatahku.laporan: worker email laporan menyala", aliran.getvalue())


class KomposisiTests(unittest.IsolatedAsyncioTestCase):
    """`jalankan` sungguhan dengan `putaran_antrean` sungguhan di SQLite berkas (bahan `test_laporan_antrean_email`)
    dan pengirim palsu yang menghitung kiriman. Pacu dipercepat (`tidur` hanya titik serah)."""

    asyncSetUp = uji_antrean.AntreanTests.asyncSetUp
    user = uji_antrean.AntreanTests.user
    laporan = uji_antrean.AntreanTests.laporan
    baca = uji_antrean.AntreanTests.baca
    antrean = uji_antrean.AntreanTests.antrean

    async def banyak_laporan(self, n: int) -> list:
        rids = []
        async with self.Session() as db:
            for i in range(n):
                u = User(name=f"U{i:03d}", email=f"u{i:03d}@contoh.id")
                u.email_verified_at = uji_antrean.T0 - 30 * uji_antrean.HARI
                db.add(u)
                await db.flush()
                r = Report(user_id=u.id, jenis="bulanan", periode_mulai=uji_antrean.periode(10)[0],
                           periode_akhir=uji_antrean.periode(10)[1], payday_day=1, data=uji_antrean.DATA,
                           terbit_at=uji_antrean.T0 - (n - i) * uji_antrean.MENIT, email_status="menunggu")
                db.add(r)
                await db.flush()
                rids.append(r.id)
            await db.commit()
        return rids

    async def jalankan(self, berhenti, tunggu_kosong, redis=None):
        async def serah(_detik):
            await asyncio.sleep(0)

        await asyncio.wait_for(worker_email.jalankan(
            berhenti, redis=redis or RedisTiruan(), per_detik=20, tidur=serah, tunggu_kosong=tunggu_kosong,
            waktu_utc=lambda: T_UTC), 30)

    @staticmethod
    async def berhenti_saat_kosong(berhenti, detik):
        berhenti.set()

    async def test_berhenti_di_tengah_kiriman(self):
        rids = await self.banyak_laporan(3)
        berhenti = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def nyalakan():
            berhenti.set()

        def saat_kirim(nomor):          # thread pengirim: berhenti datang selagi kiriman pertama berjalan
            if nomor == 0:
                asyncio.run_coroutine_threadsafe(nyalakan(), loop).result(5)

        self.pengirim.sebelum_menjawab = saat_kirim
        await self.jalankan(berhenti, self.berhenti_saat_kosong)

        self.assertEqual(len(self.pengirim.kiriman), 1)
        self.assertEqual((await self.antrean(rids[0]))[:3], ("terkirim", None, 1))
        for rid in rids[1:]:
            self.assertEqual(await self.antrean(rid), ("menunggu", None, 0, None, None))

    async def test_dua_worker_mengirim_setiap_laporan_sekali(self):
        rids = await self.banyak_laporan(40)
        tunggu = []

        async def tunggu_kosong(berhenti, detik):
            tunggu.append(detik)
            berhenti.set()

        await asyncio.gather(self.jalankan(asyncio.Event(), tunggu_kosong),
                             self.jalankan(asyncio.Event(), tunggu_kosong))

        self.assertEqual(sorted(self.pengirim.tujuan()), [f"u{i:03d}@contoh.id" for i in range(40)])
        for rid in rids:
            self.assertEqual((await self.antrean(rid))[:3], ("terkirim", None, 1))
        self.assertEqual(tunggu, [60.0, 60.0])   # klaim yang kalah tidak dihitung gagal: tanpa jeda gangguan

    async def test_pemutus_laporan_keenam_tidak_diklaim(self):
        rids = await self.banyak_laporan(7)
        self.pengirim.hasil = [False] * 5 + [True] * 2
        berhenti = asyncio.Event()
        saat_jeda = []

        async def tunggu_kosong(henti, detik):
            if detik == worker_email.JEDA_GANGGUAN:
                saat_jeda.append((len(self.pengirim.kiriman), await self.antrean(rids[5])))
                return
            henti.set()

        with self.assertLogs("jatahku.laporan", level="WARNING") as log:
            await self.jalankan(berhenti, tunggu_kosong)

        self.assertEqual(saat_jeda, [(5, ("menunggu", None, 0, None, None))])
        self.assertIn("email laporan: 5 kiriman berturut-turut gagal; worker jeda 5 menit", "\n".join(log.output))
        for rid in rids[:5]:
            self.assertEqual((await self.antrean(rid))[:3], ("menunggu", None, 1))   # dicoba lagi sesudah 55 menit
        for rid in rids[5:]:
            self.assertEqual((await self.antrean(rid))[:3], ("terkirim", None, 1))
        self.assertEqual(len(self.pengirim.kiriman), 7)


if __name__ == "__main__":
    unittest.main()
