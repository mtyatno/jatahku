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
import logging
import signal
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.core.config import Settings
from app.services.laporan import worker_email
from app.services.laporan.antrean_email import hasil_kosong

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
    def __init__(self, galat=None):
        self.galat = galat
        self.set_dipanggil = []
        self.ditutup = False

    async def set(self, kunci, nilai, ex=None):
        if self.galat is not None:
            raise self.galat
        self.set_dipanggil.append((kunci, nilai, ex))
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

    async def __call__(self, jam=None, *, sebelum_laporan=None, berhenti=None):
        await asyncio.sleep(0)   # titik serah: loop yang tak pernah berhenti gagal oleh batas waktu tes, tidak menggantung
        self.dipanggil += 1
        self.catatan.append(("putaran", self.dipanggil))
        self.fungsi_berhenti.append(berhenti)
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
        self.assertEqual(self.redis.set_dipanggil[0], (worker_email.KUNCI_HIDUP, T_UTC.isoformat(), 900))
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
                patch.object(worker_email.logging, "basicConfig") as basic:
            worker_email.main()   # tidak melempar SystemExit bukan 0, tidak mati oleh SIGTERM
        self.assertTrue(dipanggil["berhenti"])
        self.assertEqual(basic.call_args.kwargs["level"], logging.INFO)
        # penangan sinyal dilepas bersama loop: SIGTERM kembali ke bawaan
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)


if __name__ == "__main__":
    unittest.main()
