"""Laporan berkala tahap 2, Task 3: antrean email laporan (`app/services/laporan/antrean_email.py`; spec
2026-11-01-laporan-berkala-design bagian 6b-6c, keputusan rencana tahap 2 butir 2, 3, 5, 6, dan 7).

Antrean berjalan di SQLite BERKAS (folder sementara per tes), bukan in-memory: dua `proses_antrean_email` yang
bersamaan harus memakai sesi dan koneksi masing-masing ke database yang sama, seperti job terjadwal dan jalan manual
dari shell. `AsyncSessionLocal` modul antrean diganti; pengirim (`email_service.send_laporan_email`) dipalsukan dan
mencatat setiap kiriman (dipanggil di thread lewat `asyncio.to_thread`, seperti SMTP sungguhan); kunci Fernet ditambal
lewat `rahasia.get_settings`. PDF lampiran dibuka dengan `pypdfium2` hanya di thread event loop (pdfium tidak aman
antar-thread). Status email saat terbit dan pemanggilan antrean oleh `laporan_job`: `test_laporan_job`.
Butuh `aiosqlite` (kecuali tes fungsi murni); dilewati bila tidak ada.
Run: python -m unittest app.tests.test_laporan_antrean_email -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import asyncio
import calendar
import contextlib
import importlib.util
import io
import logging
import random
import shutil
import tempfile
import threading
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pypdfium2 as pdfium
from cryptography.fernet import Fernet
from pypdfium2 import PdfiumError
from sqlalchemy import event
from sqlalchemy.orm import configure_mappers

from app.core.config import get_settings
from app.core.database import Base
from app.models.models import Report, ReportSettings, User
from app.services import email_service
from app.services.laporan import antrean_email, pdf, rahasia, surel
from app.services.laporan.susun import susun_bulanan
from app.tests.test_laporan_susun import bahan

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

UTC = timezone.utc
MENIT = timedelta(minutes=1)
JAM = timedelta(hours=1)
HARI = timedelta(days=1)
T0 = datetime(2026, 11, 5, 0, 30, tzinfo=UTC)   # satu jalan job (tiap jam di menit 30)
KUNCI = Fernet.generate_key().decode()
KUNCI_LAIN = Fernet.generate_key().decode()
SANDI = "rahasia-é123"   # NFC, dengan huruf bertanda supaya jalur non-ASCII ikut teruji
DATA = susun_bulanan(bahan())   # "Laporan Oktober 2026", periode 1-31 Okt 2026
KOSONG = {"terkirim": 0, "gagal": 0, "dilewati": 0, "dicoba_lagi": 0}
_OTOMATIS = object()

# Teks persis kotak PDF (spec, teks email laporan resmi), sengaja ditulis ulang di sini, bukan diimpor dari `surel`.
BARIS_TERLAMPIR = (
    "Berkas PDF terlampir dilindungi kata sandi laporan yang Anda atur di Pengaturan → Laporan. Demi keamanan, "
    "kata sandi tidak pernah dikirim lewat email. Lupa kata sandi? Atur ulang di Pengaturan → Laporan, lalu unduh "
    "PDF dari halaman laporan."
)
BARIS_ATUR_SANDI = ("PDF belum dilampirkan karena kata sandi laporan belum diatur. Atur di Pengaturan → Laporan agar "
                    "laporan berikutnya disertai PDF terkunci.")
BARIS_UNDUH = "PDF tidak dapat dilampirkan kali ini. Rincian lengkap tetap tersedia di aplikasi."


def periode(bulan: int) -> tuple[date, date]:
    """Bulan kalender 2026 (gajian tanggal 1). Satu user tidak boleh punya dua laporan bulanan dengan awal sama."""
    return date(2026, bulan, 1), date(2026, bulan, calendar.monthrange(2026, bulan)[1])


def kunci(nilai: str):
    """Tambal pembacaan setelan: `rahasia` hanya membaca kunci lewat get_settings()."""
    return patch.object(rahasia, "get_settings", return_value=SimpleNamespace(REPORT_SECRET_KEY=nilai))


def utc(waktu: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime tanpa zona (nilainya UTC); samakan supaya bisa dibandingkan dengan T0."""
    if waktu is None or waktu.tzinfo is not None:
        return waktu
    return waktu.replace(tzinfo=UTC)


def isi_log(catatan: list[logging.LogRecord]) -> str:
    """Seluruh teks catatan log, termasuk jejak galat bila ada."""
    pemformat = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return "\n".join(pemformat.format(c) for c in catatan)


def teks_pdf(isi: bytes, kata_sandi: str | None) -> str:
    """Teks halaman pertama PDF, spasi dirapatkan. Dipanggil di thread tes (pdfium tidak aman antar-thread)."""
    dok = pdfium.PdfDocument(io.BytesIO(isi), password=kata_sandi)
    try:
        halaman = dok[0]
        teks = halaman.get_textpage()
        hasil = " ".join(teks.get_text_range().split())
        teks.close()
        halaman.close()
        return hasil
    finally:
        dok.close()


class JamPalsu:
    """Jam yang diatur tes dan bisa dimajukan dari thread pengirim (mis. kiriman yang makan waktu)."""

    def __init__(self, waktu: datetime):
        self.waktu = waktu

    def kelas_datetime(self) -> type:
        """Pengganti kelas `datetime` di modul antrean: `now()` membaca jam ini, selebihnya `datetime` biasa."""
        jam = self

        class Datetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return jam.waktu if tz is None else jam.waktu.astimezone(tz)

        return Datetime


class PengirimPalsu:
    """Pengganti `email_service.send_laporan_email` (tanda tangan sama). Mencatat setiap kiriman, lalu menjawab
    `hasil`: bool; daftar bool menurut nomor urut kiriman; atau fungsi alamat → bool atau galat yang dilempar (pengirim
    sungguhan tidak pernah melempar, jadi galat hanya untuk tes jaring pengaman). `sebelum_menjawab(nomor)` (opsional)
    dipanggil di thread pengirim dengan nomor urut kiriman, mis. untuk menahan kiriman di satu penghalang."""

    def __init__(self):
        self.kiriman: list[SimpleNamespace] = []
        self.hasil = True
        self.sebelum_menjawab = None
        self._kunci = threading.Lock()

    def __call__(self, to_email, subject, html_body, text_body, unsubscribe_url, pdf_bytes=None, filename=None):
        with self._kunci:
            nomor = len(self.kiriman)
            self.kiriman.append(SimpleNamespace(
                tujuan=to_email, subjek=subject, html=html_body, teks=text_body, berhenti=unsubscribe_url,
                pdf=pdf_bytes, nama_file=filename,
            ))
        if self.sebelum_menjawab is not None:
            self.sebelum_menjawab(nomor)
        if isinstance(self.hasil, list):
            hasil = self.hasil[nomor]
        elif callable(self.hasil):
            hasil = self.hasil(to_email)
        else:
            hasil = self.hasil
        if isinstance(hasil, BaseException):
            raise hasil
        return hasil

    def tujuan(self) -> list[str]:
        return [k.tujuan for k in self.kiriman]


class StatusAwalTests(unittest.TestCase):
    """`status_awal`: dipakai saat terbit dan saat laporan dibaca ulang sebelum dikirim."""

    @staticmethod
    def orang(email, terverifikasi: bool) -> User:
        u = User(id=uuid.uuid4(), name="Ani", email=email)
        # Sesudah email: event model mengosongkan `email_verified_at` setiap kali email diisi.
        u.email_verified_at = datetime(2026, 10, 2, tzinfo=UTC) if terverifikasi else None
        return u

    @staticmethod
    def atur(email_on: bool) -> ReportSettings:
        return ReportSettings(user_id=uuid.uuid4(), kata_sandi_enc=None, email_on=email_on, kuartalan_on=True,
                              tahunan_on=True)

    def test_status_awal_urutan_alasan(self):
        a = antrean_email
        # Nilai persis (Global Constraints): disimpan di kolom String(16)/String(32) dan dibaca task lain.
        self.assertEqual(
            (a.STATUS_MENUNGGU, a.STATUS_MENGIRIM, a.STATUS_TERKIRIM, a.STATUS_GAGAL, a.STATUS_DILEWATI),
            ("menunggu", "mengirim", "terkirim", "gagal", "dilewati"),
        )
        self.assertEqual(
            (a.ALASAN_BELUM_VERIFIKASI, a.ALASAN_DIMATIKAN, a.ALASAN_TANPA_EMAIL, a.ALASAN_SMTP),
            ("belum_verifikasi", "dimatikan", "tanpa_email", "smtp"),
        )
        self.assertEqual(
            (a.MAKS_PERCOBAAN, a.JEDA_COBA_ULANG, a.BATAS_MENGIRIM, a.KELOMPOK),
            (3, timedelta(minutes=55), timedelta(minutes=30), 100),
        )
        self.assertEqual(a.hasil_kosong(), KOSONG)

        kasus = [
            # (keterangan, user, pengaturan, hasil); urutan alasan: tanpa email, belum terverifikasi, email_on mati
            ("tanpa email mengalahkan semua", self.orang(None, True), self.atur(False), ("dilewati", "tanpa_email")),
            ("email hanya spasi", self.orang("   ", False), None, ("dilewati", "tanpa_email")),
            ("belum terverifikasi mengalahkan email_on mati", self.orang("ani@contoh.id", False), self.atur(False),
             ("dilewati", "belum_verifikasi")),
            ("belum terverifikasi", self.orang("ani@contoh.id", False), None, ("dilewati", "belum_verifikasi")),
            ("email_on mati", self.orang("ani@contoh.id", True), self.atur(False), ("dilewati", "dimatikan")),
            ("tanpa baris pengaturan = bawaan", self.orang("ani@contoh.id", True), None, ("menunggu", None)),
            ("email_on hidup", self.orang("ani@contoh.id", True), self.atur(True), ("menunggu", None)),
        ]
        for keterangan, user, pengaturan, harapan in kasus:
            with self.subTest(keterangan):
                self.assertEqual(antrean_email.status_awal(user, pengaturan), harapan)


class LampiranUntukTests(unittest.TestCase):
    """`lampiran_untuk` (keputusan rencana 6): kata sandi PDF atau None, dan kode baris lampiran di badan email. Sama
    dengan jalur unduh PDF: token tak terbaca atau kata sandi yang kini ditolak = belum diatur (409 di unduh); kunci
    server tidak ada = PDF hanya di aplikasi (503 di unduh)."""

    def setUp(self):
        self.enterContext(kunci(KUNCI))
        self.uid = uuid.uuid4()

    def atur(self, token: str | None) -> ReportSettings:
        return ReportSettings(user_id=self.uid, kata_sandi_enc=token, email_on=True, kuartalan_on=True,
                              tahunan_on=True)

    def test_lampiran_untuk(self):
        token = rahasia.enkripsi(SANDI)
        self.assertEqual(antrean_email.lampiran_untuk(None), (None, "belum_diatur"))
        self.assertEqual(antrean_email.lampiran_untuk(self.atur(None)), (None, "belum_diatur"))
        self.assertEqual(antrean_email.lampiran_untuk(self.atur(token)), (SANDI, "terlampir"))

        lama, ditolak = "sandi-lama-rahasia", "abc\x07def-rahasia"
        kasus = [
            # (keterangan, token tersimpan, kunci server saat mengirim, kode)
            ("token dari kunci lain", Fernet(KUNCI_LAIN.encode()).encrypt(lama.encode()).decode(), KUNCI,
             "belum_diatur"),
            ("bukan token Fernet", "bukan-token-fernet", KUNCI, "belum_diatur"),
            ("kata sandi kini ditolak periksa_kata_sandi", rahasia.enkripsi(ditolak), KUNCI, "belum_diatur"),
            ("kunci server kosong", token, "", "tidak_tersedia"),
            ("kunci server bukan kunci Fernet", token, "bukan-kunci-fernet", "tidak_tersedia"),
        ]
        for keterangan, tersimpan, kunci_server, kode in kasus:
            with self.subTest(keterangan):
                with kunci(kunci_server), self.assertLogs("jatahku.laporan", "WARNING") as logs:
                    self.assertEqual(antrean_email.lampiran_untuk(self.atur(tersimpan)), (None, kode))
                teks = isi_log(logs.records)
                self.assertIn(str(self.uid), teks)   # hanya id user dan teks tetap
                for rahasia_ in (tersimpan, lama, ditolak, SANDI, KUNCI):
                    self.assertNotIn(rahasia_, teks)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class AntreanTests(unittest.IsolatedAsyncioTestCase):
    """`proses_antrean_email` dan `hidupkan_lagi` di SQLite berkas. User dibuat terverifikasi kecuali dinyatakan lain;
    laporan dibuat langsung dengan status antreannya (penerbitan diuji di `test_laporan_job`)."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        # NullPool: setiap sesi membuka koneksinya sendiri ke berkas yang sama (dua proses bersamaan tidak berbagi
        # satu koneksi seperti StaticPool in-memory).
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(folder) / 'antrean.db'}", poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)

        # Postgres menegakkan FK; tanpa ini SQLite meloloskan baris yatim.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.enterContext(patch.object(antrean_email, "AsyncSessionLocal", self.Session))
        self.pengirim = PengirimPalsu()
        self.enterContext(patch.object(email_service, "send_laporan_email", self.pengirim))
        self.enterContext(kunci(KUNCI))

    async def user(self, nama: str, *, email=_OTOMATIS, terverifikasi: bool = True, email_on: bool | None = None,
                   kata_sandi: str | None = None, token: str | None = None) -> uuid.UUID:
        """User baru beralamat `<nama>@contoh.id`. Baris `report_settings` hanya dibuat bila `email_on`, `kata_sandi`
        (dienkripsi dengan kunci tes), atau `token` (disimpan apa adanya) diberikan."""
        async with self.Session() as db:
            u = User(name=nama, email=f"{nama.lower()}@contoh.id" if email is _OTOMATIS else email)
            if terverifikasi:
                u.email_verified_at = T0 - 30 * HARI   # sesudah email: event model mengosongkannya saat email diisi
            db.add(u)
            await db.flush()
            if email_on is not None or kata_sandi is not None or token is not None:
                db.add(ReportSettings(
                    user_id=u.id, kata_sandi_enc=rahasia.enkripsi(kata_sandi) if kata_sandi is not None else token,
                    email_on=True if email_on is None else email_on, kuartalan_on=True, tahunan_on=True,
                ))
            await db.commit()
            return u.id

    async def laporan(self, user_id, *, status: str | None = "menunggu", alasan: str | None = None,
                      terbit: datetime = T0 - 5 * MENIT, percobaan: int = 0, terakhir: datetime | None = None,
                      bulan: int = 10, data: dict = DATA) -> uuid.UUID:
        async with self.Session() as db:
            mulai, akhir = periode(bulan)
            r = Report(user_id=user_id, household_id=None, jenis="bulanan", periode_mulai=mulai, periode_akhir=akhir,
                       payday_day=1, data=data, terbit_at=terbit, email_status=status, email_alasan=alasan,
                       email_percobaan=percobaan, email_terakhir_at=terakhir)
            db.add(r)
            await db.commit()
            return r.id

    async def baca(self, report_id) -> Report:
        async with self.Session() as db:
            return await db.get(Report, report_id)

    async def antrean(self, report_id) -> tuple:
        """(status, alasan, percobaan, waktu percobaan terakhir, waktu terkirim) satu laporan."""
        r = await self.baca(report_id)
        return (r.email_status, r.email_alasan, r.email_percobaan, utc(r.email_terakhir_at),
                utc(r.email_terkirim_at))

    async def jalan(self, sekarang: datetime = T0) -> dict:
        return await antrean_email.proses_antrean_email(sekarang)

    def tautan(self, report_id) -> str:
        return f"{get_settings().APP_URL}/laporan/{report_id}"

    # ------------------------------------------------------------------ siapa yang dikirimi

    async def test_laporan_tahap1_null_tidak_dikirim(self):
        # Keputusan rencana 7: laporan tahap 1 (`email_status` NULL) tidak pernah dikirim, walau penerimanya kini
        # terverifikasi dengan email_on. Status selain `menunggu` juga tidak disentuh. Laporan `menunggu` milik user
        # yang sama membuktikan antreannya memang berjalan.
        ani = await self.user("Ani", email_on=True)
        lain = {
            "tahap 1": (await self.laporan(ani, status=None, bulan=6), (None, None, 0, None, None)),
            "terkirim": (await self.laporan(ani, status="terkirim", bulan=7), ("terkirim", None, 0, None, None)),
            "gagal": (await self.laporan(ani, status="gagal", alasan="smtp", percobaan=3, terakhir=T0 - 2 * JAM,
                                         bulan=8), ("gagal", "smtp", 3, T0 - 2 * JAM, None)),
            "dilewati": (await self.laporan(ani, status="dilewati", alasan="dimatikan", bulan=9),
                         ("dilewati", "dimatikan", 0, None, None)),
        }
        menunggu = await self.laporan(ani, bulan=10)

        self.assertEqual(await self.jalan(), {**KOSONG, "terkirim": 1})

        [kiriman] = self.pengirim.kiriman
        self.assertIn(self.tautan(menunggu), kiriman.teks)
        for keterangan, (rid, harapan) in lain.items():
            with self.subTest(keterangan):
                self.assertEqual(await self.antrean(rid), harapan)

    async def test_kirim_dengan_lampiran_bila_kata_sandi_diatur(self):
        ani = await self.user("Ani", kata_sandi=SANDI)
        rid = await self.laporan(ani)

        self.assertEqual(await self.jalan(), {**KOSONG, "terkirim": 1})

        [kiriman] = self.pengirim.kiriman
        self.assertEqual((kiriman.tujuan, kiriman.subjek, kiriman.nama_file),
                         ("ani@contoh.id", "Laporan Oktober 2026 · Jatahku", "jatahku-laporan-2026-10.pdf"))
        self.assertIn(BARIS_TERLAMPIR, kiriman.teks)
        self.assertIn(f'href="{self.tautan(rid)}"', kiriman.html)   # tombol "Buka Laporan di Jatahku →"
        self.assertIn(f"Buka laporan di Jatahku: {self.tautan(rid)}", kiriman.teks)
        [token] = parse_qs(urlparse(kiriman.berhenti).query)["token"]
        self.assertEqual(surel.baca_token_berhenti(token), ani)   # berhenti berlangganan terikat ke penerima
        self.assertIn("Laporan Oktober 2026", teks_pdf(kiriman.pdf, SANDI))
        with self.assertRaises(PdfiumError):
            teks_pdf(kiriman.pdf, None)   # tanpa kata sandi tidak terbuka
        self.assertEqual(await self.antrean(rid), ("terkirim", None, 1, T0, T0))   # klaim = percobaan ke-1

    async def test_tanpa_kata_sandi_tanpa_lampiran(self):
        ani = await self.user("Ani")                        # tanpa baris pengaturan
        budi = await self.user("Budi", email_on=True)      # baris ada, kata sandi belum diatur
        rids = [await self.laporan(ani, terbit=T0 - 9 * MENIT), await self.laporan(budi, terbit=T0 - 8 * MENIT)]

        self.assertEqual(await self.jalan(), {**KOSONG, "terkirim": 2})

        self.assertEqual(self.pengirim.tujuan(), ["ani@contoh.id", "budi@contoh.id"])
        for kiriman, rid in zip(self.pengirim.kiriman, rids):
            self.assertEqual((kiriman.pdf, kiriman.nama_file), (None, None))
            self.assertIn(BARIS_ATUR_SANDI, kiriman.teks)
            self.assertNotIn(BARIS_TERLAMPIR, kiriman.teks)
            self.assertEqual(await self.antrean(rid), ("terkirim", None, 1, T0, T0))

    async def test_token_tak_terbaca_dan_kunci_hilang(self):
        # Keputusan rencana 6 / review focus 5: lampiran jatuh dengan anggun dan email tetap terkirim. Token tak
        # terbaca atau kata sandi yang kini ditolak = "atur kata sandi" (sama dengan 409 di unduh); kunci server hilang
        # atau galat PDF tak terduga = "unduh di aplikasi". Log hanya id dan teks tetap: tanpa token, kata sandi, kunci,
        # atau alamat (galat PDF memuat kata sandi di pesannya; yang dicatat hanya jenisnya).
        lama, ditolak = "sandi-lama-rahasia", "abc\x07def-rahasia"
        kasus = [
            # (nama user, token tersimpan, kunci server saat mengirim, galat buat_pdf, baris lampiran)
            ("Ani", Fernet(KUNCI_LAIN.encode()).encrypt(lama.encode()).decode(), KUNCI, None, BARIS_ATUR_SANDI),
            ("Budi", "bukan-token-fernet", KUNCI, None, BARIS_ATUR_SANDI),
            ("Citra", rahasia.enkripsi(ditolak), KUNCI, None, BARIS_ATUR_SANDI),
            ("Dewi", rahasia.enkripsi(SANDI), "", None, BARIS_UNDUH),
            ("Eko", rahasia.enkripsi(SANDI), KUNCI, RuntimeError(f"render gagal, kata sandi {SANDI}"), BARIS_UNDUH),
        ]
        for nama, token, kunci_server, galat_pdf, baris in kasus:
            with self.subTest(nama):
                uid = await self.user(nama, token=token)
                rid = await self.laporan(uid)
                self.pengirim.kiriman.clear()
                pdf_palsu = (patch.object(pdf, "buat_pdf", AsyncMock(side_effect=galat_pdf)) if galat_pdf
                             else contextlib.nullcontext())

                with kunci(kunci_server), pdf_palsu, self.assertLogs(level="INFO") as logs:
                    self.assertEqual(await self.jalan(), {**KOSONG, "terkirim": 1})

                [kiriman] = self.pengirim.kiriman
                self.assertEqual((kiriman.pdf, kiriman.nama_file), (None, None))
                self.assertIn(baris, kiriman.teks)
                self.assertNotIn(BARIS_TERLAMPIR, kiriman.teks)
                self.assertEqual((await self.baca(rid)).email_status, "terkirim")
                teks = isi_log(logs.records)
                peringatan = [c for c in logs.records if c.name == "jatahku.laporan" and c.levelno >= logging.WARNING]
                self.assertTrue(peringatan, teks)
                self.assertTrue(all(str(uid) in c.getMessage() or str(rid) in c.getMessage() for c in peringatan),
                                teks)
                for rahasia_ in (token, lama, ditolak, SANDI, KUNCI, kiriman.tujuan):
                    self.assertNotIn(rahasia_, teks)

    async def test_dibaca_ulang_saat_kirim(self):
        # Spec 6c: pengaturan yang berubah sesudah terbit dibaca ulang saat mengirim, SESUDAH klaim (ruling R-T3-2: setiap
        # klaim dihitung sebagai percobaan). Laporan terbit `menunggu`, lalu sebelum jalan antrean: Ani mengganti email
        # (event model mencabut verifikasi), Budi mematikan email laporan, Citra menghapus emailnya. Hanya Dewi dikirimi.
        ids = {nama: await self.user(nama, email_on=True) for nama in ("Ani", "Budi", "Citra", "Dewi")}
        rids = {nama: await self.laporan(uid, terbit=T0 - (9 - i) * MENIT) for i, (nama, uid) in enumerate(ids.items())}
        async with self.Session() as db:
            (await db.get(User, ids["Ani"])).email = "ani.baru@contoh.id"
            (await db.get(ReportSettings, ids["Budi"])).email_on = False
            (await db.get(User, ids["Citra"])).email = None
            await db.commit()

        self.assertEqual(await self.jalan(), {**KOSONG, "terkirim": 1, "dilewati": 3})

        self.assertEqual(self.pengirim.tujuan(), ["dewi@contoh.id"])
        harapan = {
            "Ani": ("dilewati", "belum_verifikasi", 1, T0, None),
            "Budi": ("dilewati", "dimatikan", 1, T0, None),
            "Citra": ("dilewati", "tanpa_email", 1, T0, None),
            "Dewi": ("terkirim", None, 1, T0, T0),
        }
        for nama, status in harapan.items():
            with self.subTest(nama):
                self.assertEqual(await self.antrean(rids[nama]), status)

        # Jalan berikutnya tidak menyentuh yang sudah dilewati atau terkirim.
        self.assertEqual(await self.jalan(T0 + JAM), KOSONG)
        self.assertEqual(len(self.pengirim.kiriman), 1)

    # ------------------------------------------------------------------ coba ulang

    async def test_gagal_dicoba_lagi_paling_cepat_55_menit(self):
        # Keputusan rencana 3: "paling cepat 1 jam" = jeda 55 menit sejak percobaan terakhir, karena job jalan tiap jam
        # di menit 30 dan 60 menit tepat bisa meleset beberapa detik. Jalan manual di antaranya tidak mencoba.
        rid = await self.laporan(await self.user("Ani"))
        self.pengirim.hasil = False

        self.assertEqual(await self.jalan(T0), {**KOSONG, "dicoba_lagi": 1})
        self.assertEqual(await self.antrean(rid), ("menunggu", None, 1, T0, None))

        for menit in (30, 54):
            with self.subTest(menit=menit):
                self.assertEqual(await self.jalan(T0 + menit * MENIT), KOSONG)
                self.assertEqual(len(self.pengirim.kiriman), 1)

        self.assertEqual(await self.jalan(T0 + 56 * MENIT), {**KOSONG, "dicoba_lagi": 1})
        self.assertEqual(len(self.pengirim.kiriman), 2)
        self.assertEqual(await self.antrean(rid), ("menunggu", None, 2, T0 + 56 * MENIT, None))

        # Percobaan ketiga berhasil: terkirim; setiap klaim tercatat sebagai percobaan.
        self.pengirim.hasil = True
        self.assertEqual(await self.jalan(T0 + 2 * JAM), {**KOSONG, "terkirim": 1})
        self.assertEqual(await self.antrean(rid), ("terkirim", None, 3, T0 + 2 * JAM, T0 + 2 * JAM))

    async def test_tiga_percobaan_lalu_gagal_smtp(self):
        # Review focus 3: SMTP mati berjam-jam → paling banyak tiga percobaan berjarak ≥ 55 menit, lalu `gagal`/`smtp`
        # dan satu logger.error dengan id laporan, tanpa alamat; sesudahnya tidak pernah dicoba lagi.
        rid = await self.laporan(await self.user("Ani"))
        self.pengirim.hasil = False

        for jam in (0, 1):
            self.assertEqual(await self.jalan(T0 + jam * JAM), {**KOSONG, "dicoba_lagi": 1})
        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await self.jalan(T0 + 2 * JAM), {**KOSONG, "gagal": 1})

        self.assertEqual(await self.antrean(rid), ("gagal", "smtp", 3, T0 + 2 * JAM, None))
        [catatan] = logs.records
        self.assertIn(str(rid), catatan.getMessage())
        self.assertNotIn("ani@contoh.id", isi_log(logs.records))
        for jam in (3, 4, 24):
            self.assertEqual(await self.jalan(T0 + jam * JAM), KOSONG)
        self.assertEqual(len(self.pengirim.kiriman), 3)

    async def test_mengirim_basi_kembali_menunggu(self):
        # Spec 6c: klaim `mengirim` yang lebih tua dari 30 menit (proses berhenti di tengah kiriman, atau hasilnya tidak
        # bisa dicatat) kembali `menunggu`; percobaannya sudah dihitung saat klaim, jadi tidak bertambah lagi. Yang
        # percobaannya sudah habis menjadi `gagal`/`smtp` dengan logger.error berisi id saja (ruling R-T3-2). Jeda 55
        # menit tetap dihitung dari klaim itu, jadi laporannya tidak dikirim di jalan yang sama.
        basi = await self.laporan(await self.user("Ani"), status="mengirim", percobaan=1, terakhir=T0 - 31 * MENIT)
        segar = await self.laporan(await self.user("Budi"), status="mengirim", percobaan=1, terakhir=T0 - 29 * MENIT)
        habis = await self.laporan(await self.user("Citra"), status="mengirim", percobaan=3, terakhir=T0 - 31 * MENIT)

        with self.assertLogs("jatahku.laporan", "WARNING") as logs:
            self.assertEqual(await self.jalan(T0), {**KOSONG, "gagal": 1})

        self.assertEqual(await self.antrean(basi), ("menunggu", None, 1, T0 - 31 * MENIT, None))
        self.assertEqual(await self.antrean(segar), ("mengirim", None, 1, T0 - 29 * MENIT, None))
        self.assertEqual(await self.antrean(habis), ("gagal", "smtp", 3, T0 - 31 * MENIT, None))
        self.assertEqual(self.pengirim.kiriman, [])
        peringatan = [c.getMessage() for c in logs.records if c.levelname == "WARNING"]
        galat = [c.getMessage() for c in logs.records if c.levelname == "ERROR"]
        self.assertEqual(peringatan, ["1 email laporan masih berstatus mengirim lebih dari 30 menit; dikembalikan ke "
                                      "antrean"])   # netral, angka saja
        self.assertEqual(len(galat), 1)
        self.assertIn(str(habis), galat[0])
        self.assertNotIn("citra@contoh.id", isi_log(logs.records))

        # 55 menit sesudah klaimnya laporan Ani dikirim sekali (klaim kedua = percobaan ke-2); laporan Budi kini basi,
        # tetapi jedanya belum lewat.
        with self.assertLogs("jatahku.laporan", "WARNING"):
            self.assertEqual(await self.jalan(T0 + 24 * MENIT), {**KOSONG, "terkirim": 1})
        self.assertEqual(self.pengirim.tujuan(), ["ani@contoh.id"])
        self.assertEqual(await self.antrean(basi), ("terkirim", None, 2, T0 + 24 * MENIT, T0 + 24 * MENIT))
        self.assertEqual(await self.antrean(segar), ("menunggu", None, 1, T0 - 29 * MENIT, None))

    # ------------------------------------------------------------------ keselamatan antrean

    async def test_dua_proses_bersamaan_satu_email(self):
        # Keputusan rencana 5 / review focus 4: jalan terjadwal dan jalan manual bersamaan → satu email per laporan.
        # Dua kiriman pertama saling menunggu di satu penghalang (di thread pengirim), jadi kedua proses pasti sedang
        # mengirim pada saat yang sama; yang memisahkan laporannya hanyalah klaim bersyarat di database.
        nama = ["Ani", "Budi", "Citra", "Dewi", "Eko", "Fajar"]
        rids = [await self.laporan(await self.user(n), terbit=T0 - (10 - i) * MENIT) for i, n in enumerate(nama)]
        penghalang = threading.Barrier(2, timeout=5)
        self.pengirim.sebelum_menjawab = lambda nomor: penghalang.wait() if nomor < 2 else None

        with self.assertNoLogs("jatahku.laporan", "WARNING"):
            hasil = await asyncio.gather(self.jalan(), self.jalan())

        self.assertEqual(sorted(self.pengirim.tujuan()), sorted(f"{n.lower()}@contoh.id" for n in nama))
        self.assertEqual(sum(h["terkirim"] for h in hasil), len(nama))
        self.assertEqual([{**h, "terkirim": 0} for h in hasil], [KOSONG, KOSONG])
        for rid in rids:
            self.assertEqual(await self.antrean(rid), ("terkirim", None, 1, T0, T0))   # klaim yang kalah tak dihitung

    async def test_klaim_memeriksa_jeda_lagi(self):
        # Jalan kedua memilih laporan ini sebelum percobaan jalan pertama gagal, lalu baru memprosesnya sesudahnya
        # (statusnya sudah kembali `menunggu`). Klaimnya memeriksa jeda lagi: tidak ada percobaan kedua dalam 55 menit
        # walau dua jalan bersamaan (review focus 3). `_proses_laporan` dipanggil langsung untuk meniru daftar antrean
        # jalan kedua yang sudah basi, karena urutan itu tidak bisa dipastikan lewat dua `proses_antrean_email`.
        rid = await self.laporan(await self.user("Ani"))
        self.pengirim.hasil = False
        self.assertEqual(await self.jalan(T0), {**KOSONG, "dicoba_lagi": 1})

        self.assertIsNone(await antrean_email._proses_laporan(rid, lambda: T0 + MENIT))

        self.assertEqual(len(self.pengirim.kiriman), 1)
        self.assertEqual(await self.antrean(rid), ("menunggu", None, 1, T0, None))

    async def test_satu_galat_tidak_menghentikan_antrean(self):
        # Galat tak terduga pada satu laporan sesudah klaim, sebelum terkirim (di sini isi email untuk laporan Budi gagal
        # dirakit) dicatat dengan id laporannya (logger.exception) dan antrean lanjut. Klaim itu dihitung sebagai
        # percobaan (ruling R-T3-2): laporan Budi kembali `menunggu`, dicoba tiap jam, dan sesudah tiga jalan `gagal`.
        rids = {n: await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT)
                for i, n in enumerate(("Ani", "Budi", "Citra"))}
        asli = surel.isi_email_laporan

        def isi_email(data, nama, *args):
            if nama == "Budi":
                raise RuntimeError("bentuk data tidak dikenal")
            return asli(data, nama, *args)

        self.enterContext(patch.object(surel, "isi_email_laporan", isi_email))

        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await self.jalan(T0), {**KOSONG, "terkirim": 2, "dicoba_lagi": 1})

        self.assertEqual(self.pengirim.tujuan(), ["ani@contoh.id", "citra@contoh.id"])
        [catatan] = logs.records
        self.assertIn(str(rids["Budi"]), catatan.getMessage())
        self.assertNotIn("budi@contoh.id", catatan.getMessage())
        self.assertIsNotNone(catatan.exc_info)   # logger.exception: jejak galat ikut dicatat
        self.assertEqual(await self.antrean(rids["Budi"]), ("menunggu", None, 1, T0, None))
        for n in ("Ani", "Citra"):
            self.assertEqual(await self.antrean(rids[n]), ("terkirim", None, 1, T0, T0))

        with self.assertLogs("jatahku.laporan", "ERROR"):
            self.assertEqual(await self.jalan(T0 + JAM), {**KOSONG, "dicoba_lagi": 1})
        self.assertEqual(await self.antrean(rids["Budi"]), ("menunggu", None, 2, T0 + JAM, None))
        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await self.jalan(T0 + 2 * JAM), {**KOSONG, "gagal": 1})
        self.assertEqual(await self.antrean(rids["Budi"]), ("gagal", "smtp", 3, T0 + 2 * JAM, None))
        self.assertTrue(all(str(rids["Budi"]) in c.getMessage() for c in logs.records))
        self.assertEqual(await self.jalan(T0 + 3 * JAM), KOSONG)
        self.assertEqual(len(self.pengirim.kiriman), 2)   # laporan Budi tidak pernah sampai ke pengirim

    async def test_galat_sesudah_klaim_tidak_menahan_antrean_selamanya(self):
        # Review T3 (C): laporan yang selalu galat sesudah klaim (di sini `data` berbentuk baru yang tidak bisa dirakit
        # `surel.isi_email_laporan`) dan memenuhi batas per jalan (dibatasi 2 di sini) menahan laporan yang lebih baru
        # paling lama tiga jalan, lalu `gagal`; sesudah itu antrean jalan lagi. Dulu tertahan selamanya.
        self.enterContext(patch.object(antrean_email, "KELOMPOK", 2))
        rusak = [await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT, data={"versi": 99})
                 for i, n in enumerate(("Ani", "Budi"))]
        baru = await self.laporan(await self.user("Citra"), terbit=T0 - MENIT)

        for jam_ke, hasil in ((0, {**KOSONG, "dicoba_lagi": 2}), (1, {**KOSONG, "dicoba_lagi": 2}),
                              (2, {**KOSONG, "gagal": 2})):
            with self.subTest(jam_ke=jam_ke), self.assertLogs("jatahku.laporan", "ERROR"):
                self.assertEqual(await self.jalan(T0 + jam_ke * JAM), hasil)
                self.assertEqual((await self.baca(baru)).email_status, "menunggu")
        for rid in rusak:
            self.assertEqual(await self.antrean(rid), ("gagal", "smtp", 3, T0 + 2 * JAM, None))

        self.assertEqual(await self.jalan(T0 + 3 * JAM), {**KOSONG, "terkirim": 1})
        self.assertEqual(self.pengirim.tujuan(), ["citra@contoh.id"])
        self.assertEqual(await self.antrean(baru), ("terkirim", None, 1, T0 + 3 * JAM, T0 + 3 * JAM))

    async def test_hasil_terkirim_tak_tercatat_paling_banyak_tiga_kiriman(self):
        # Review T3 (B): kiriman berhasil tetapi hasilnya tidak bisa disimpan (galat database yang menetap pada UPDATE
        # yang mencatat `terkirim`). Laporan tertahan di `mengirim`, kembali lewat aturan 30 menit, dan setiap klaim
        # dihitung: paling banyak tiga kiriman, lalu `gagal` (dulu: satu kiriman tiap jam tanpa akhir).
        rid = await self.laporan(await self.user("Ani"))

        def tolak_catat_terkirim(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE reports") and "email_terkirim_at" in statement:
                raise RuntimeError("disk penuh")

        event.listen(self.engine.sync_engine, "before_cursor_execute", tolak_catat_terkirim)
        self.addCleanup(event.remove, self.engine.sync_engine, "before_cursor_execute", tolak_catat_terkirim)

        for jam_ke in range(3):
            with self.subTest(jam_ke=jam_ke), self.assertLogs("jatahku.laporan", "ERROR"):
                self.assertEqual(await self.jalan(T0 + jam_ke * JAM), KOSONG)
                self.assertEqual(await self.antrean(rid), ("mengirim", None, jam_ke + 1, T0 + jam_ke * JAM, None))
        with self.assertLogs("jatahku.laporan", "ERROR") as logs:
            self.assertEqual(await self.jalan(T0 + 3 * JAM), {**KOSONG, "gagal": 1})

        self.assertEqual(await self.antrean(rid), ("gagal", "smtp", 3, T0 + 2 * JAM, None))
        self.assertEqual(len(self.pengirim.kiriman), 3)
        [catatan] = logs.records
        self.assertIn(str(rid), catatan.getMessage())
        for jam_ke in (4, 5, 24):
            self.assertEqual(await self.jalan(T0 + jam_ke * JAM), KOSONG)
        self.assertEqual(len(self.pengirim.kiriman), 3)

    async def test_hasil_lambat_tidak_menimpa_klaim_jalan_lain(self):
        # Minor review T3: setiap tulis hasil memeriksa pemilik klaim (`mengirim` + waktu klaimnya). Jalan A mengklaim
        # lalu tertahan di SMTP; jalan B 56 menit kemudian menganggap klaim A basi, mengklaim lagi, dan mengirim. Saat
        # kiriman A akhirnya gagal, hasilnya tidak ditulis (INFO, id saja): `terkirim` milik B tetap.
        rid = await self.laporan(await self.user("Ani"))
        mulai_kirim, lanjut = threading.Event(), threading.Event()

        def tahan_kiriman_pertama(nomor):
            if nomor == 0:
                mulai_kirim.set()
                lanjut.wait(5)

        self.pengirim.sebelum_menjawab = tahan_kiriman_pertama
        self.pengirim.hasil = [False, True]

        jalan_a = asyncio.create_task(self.jalan(T0))
        self.assertTrue(await asyncio.to_thread(mulai_kirim.wait, 5))
        with self.assertLogs("jatahku.laporan", "WARNING"):   # klaim A dianggap basi
            self.assertEqual(await self.jalan(T0 + 56 * MENIT), {**KOSONG, "terkirim": 1})
        lanjut.set()
        with self.assertLogs("jatahku.laporan", "INFO") as logs:
            self.assertEqual(await jalan_a, KOSONG)

        self.assertEqual(await self.antrean(rid), ("terkirim", None, 2, T0 + 56 * MENIT, T0 + 56 * MENIT))
        self.assertEqual(len(self.pengirim.kiriman), 2)
        [catatan] = logs.records
        self.assertEqual(catatan.levelname, "INFO")
        self.assertIn(str(rid), catatan.getMessage())
        self.assertNotIn("ani@contoh.id", catatan.getMessage())

    async def test_klaim_dan_terkirim_memakai_waktu_sebenarnya(self):
        # Minor review T3: klaim dan `email_terkirim_at` dicap dengan waktu saat itu, bukan awal jalan, supaya aturan
        # 30 menit mengukur umur klaimnya. Di sini setiap kiriman makan 10 menit.
        jam = JamPalsu(T0)
        self.enterContext(patch.object(antrean_email, "datetime", jam.kelas_datetime()))
        rids = [await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT)
                for i, n in enumerate(("Ani", "Budi"))]

        def kiriman_lambat(nomor):
            jam.waktu = jam.waktu + 10 * MENIT

        self.pengirim.sebelum_menjawab = kiriman_lambat

        self.assertEqual(await antrean_email.proses_antrean_email(), {**KOSONG, "terkirim": 2})

        self.assertEqual(await self.antrean(rids[0]), ("terkirim", None, 1, T0, T0 + 10 * MENIT))
        self.assertEqual(await self.antrean(rids[1]), ("terkirim", None, 1, T0 + 10 * MENIT, T0 + 20 * MENIT))

    async def test_paling_banyak_kelompok_per_putaran_terlama_dulu(self):
        n = antrean_email.KELOMPOK + 5
        urutan = list(range(n))
        random.Random(7).shuffle(urutan)   # dibuat acak: urutan kirim mengikuti `terbit_at`, bukan urutan simpan
        async with self.Session() as db:
            for i in urutan:
                u = User(name=f"U{i:03d}", email=f"u{i:03d}@contoh.id")
                u.email_verified_at = T0 - 30 * HARI
                db.add(u)
                await db.flush()
                db.add(Report(user_id=u.id, jenis="bulanan", periode_mulai=periode(10)[0], periode_akhir=periode(10)[1],
                              payday_day=1, data=DATA, terbit_at=T0 - (n - i) * MENIT, email_status="menunggu"))
            await db.commit()

        hasil, penuh = await antrean_email.putaran_antrean(lambda: T0)
        self.assertEqual(hasil, {**KOSONG, "terkirim": antrean_email.KELOMPOK})
        self.assertIs(penuh, True)
        self.assertEqual(self.pengirim.tujuan(), [f"u{i:03d}@contoh.id" for i in range(antrean_email.KELOMPOK)])

        hasil, penuh = await antrean_email.putaran_antrean(lambda: T0)
        self.assertEqual(hasil, {**KOSONG, "terkirim": 5})
        self.assertIs(penuh, False)
        self.assertEqual(self.pengirim.tujuan()[-1], f"u{n - 1:03d}@contoh.id")

    async def test_putaran_tanpa_jam_memakai_jam_sungguhan(self):
        # Ruling P1: `jam=None` = jam modul; `proses_antrean_email` mengembalikan hanya hasilnya.
        rid = await self.laporan(await self.user("Ani"))
        hasil, penuh = await antrean_email.putaran_antrean()
        self.assertEqual((hasil, penuh), ({**KOSONG, "terkirim": 1}, False))
        self.assertGreater(utc((await self.baca(rid)).email_terkirim_at), T0)

    async def test_sebelum_laporan_dipanggil_per_laporan(self):
        for i, n in enumerate(("Ani", "Budi", "Citra")):
            await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT)
        peristiwa = []

        async def pencatat():
            peristiwa.append(("sebelum", len(self.pengirim.kiriman)))

        hasil, penuh = await antrean_email.putaran_antrean(lambda: T0, sebelum_laporan=pencatat)
        self.assertEqual(hasil, {**KOSONG, "terkirim": 3})
        self.assertIs(penuh, False)
        # dipanggil 3 kali, masing-masing sebelum kiriman ke-n (n kiriman sudah keluar saat panggilan ke-n)
        self.assertEqual(peristiwa, [("sebelum", 0), ("sebelum", 1), ("sebelum", 2)])

    async def test_berhenti_tidak_mengklaim_lagi(self):
        rids = [await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT)
                for i, n in enumerate(("Ani", "Budi", "Citra"))]

        hasil, penuh = await antrean_email.putaran_antrean(lambda: T0, berhenti=lambda: len(self.pengirim.kiriman) >= 1)

        self.assertEqual(hasil, {**KOSONG, "terkirim": 1})
        self.assertIs(penuh, False)
        self.assertEqual(await self.antrean(rids[0]), ("terkirim", None, 1, T0, T0))
        for rid in rids[1:]:
            self.assertEqual(await self.antrean(rid), ("menunggu", None, 0, None, None))

    async def test_berhenti_saat_sebelum_laporan_tidak_mengklaim(self):
        # Ruling P2: permintaan berhenti yang datang selagi `sebelum_laporan` menunggu (mis. jeda pacu) dicek lagi
        # tepat sebelum klaim, jadi laporan itu tidak diklaim dan tidak dihitung percobaan.
        rids = [await self.laporan(await self.user(n), terbit=T0 - (9 - i) * MENIT)
                for i, n in enumerate(("Ani", "Budi"))]
        diminta = []

        async def pacu():
            if len(self.pengirim.kiriman) == 1:
                diminta.append(True)   # berhenti diminta selagi menunggu sebelum laporan ke-2

        hasil, penuh = await antrean_email.putaran_antrean(
            lambda: T0, sebelum_laporan=pacu, berhenti=lambda: bool(diminta))

        self.assertEqual(hasil, {**KOSONG, "terkirim": 1})
        self.assertIs(penuh, False)
        self.assertEqual(await self.antrean(rids[1]), ("menunggu", None, 0, None, None))

    # ------------------------------------------------------------------ dihidupkan lagi

    async def test_hidupkan_lagi_dalam_jendela(self):
        # Keputusan rencana 2: verifikasi berhasil atau email_on dinyalakan menghidupkan lagi laporan yang dilewati
        # karena alasan itu dan terbit paling lama JENDELA_TERBIT_HARI (7) hari lalu. Yang lebih tua, alasan lain,
        # status lain, dan laporan user lain tidak berubah. Tidak commit: pemanggil (route) yang commit.
        ani, budi = await self.user("Ani"), await self.user("Budi")
        dilewati = dict(status="dilewati")
        laporan = {
            # nama: (id, hidup oleh alasan verifikasi?, hidup oleh "dimatikan"?)
            "6 hari, belum_verifikasi": (await self.laporan(ani, **dilewati, alasan="belum_verifikasi",
                                                            terbit=T0 - 6 * HARI, bulan=3), True, False),
            "6 hari, tanpa_email": (await self.laporan(ani, **dilewati, alasan="tanpa_email", terbit=T0 - 6 * HARI,
                                                       bulan=4), True, False),
            "semenit sebelum 7 hari": (await self.laporan(ani, **dilewati, alasan="belum_verifikasi",
                                                          terbit=T0 - 7 * HARI + MENIT, bulan=5), True, False),
            "semenit lewat 7 hari": (await self.laporan(ani, **dilewati, alasan="belum_verifikasi",
                                                        terbit=T0 - 7 * HARI - MENIT, bulan=6), False, False),
            "8 hari": (await self.laporan(ani, **dilewati, alasan="belum_verifikasi", terbit=T0 - 8 * HARI, bulan=7),
                       False, False),
            "6 hari, dimatikan": (await self.laporan(ani, **dilewati, alasan="dimatikan", terbit=T0 - 6 * HARI,
                                                     bulan=8), False, True),
            "terkirim": (await self.laporan(ani, status="terkirim", terbit=T0 - 6 * HARI, bulan=9), False, False),
            "gagal smtp": (await self.laporan(ani, status="gagal", alasan="smtp", percobaan=3, terbit=T0 - 6 * HARI,
                                              bulan=10), False, False),
            "milik Budi": (await self.laporan(budi, **dilewati, alasan="belum_verifikasi", terbit=T0 - 6 * HARI,
                                              bulan=3), False, False),
        }
        sebelum = {nama: await self.antrean(rid) for nama, (rid, _, _) in laporan.items()}

        async with self.Session() as db:
            self.assertEqual(
                await antrean_email.hidupkan_lagi(db, ani, ("belum_verifikasi", "tanpa_email"), sekarang=T0), 3)
            await db.rollback()
        self.assertEqual({nama: await self.antrean(rid) for nama, (rid, _, _) in laporan.items()}, sebelum)

        async with self.Session() as db:
            self.assertEqual(
                await antrean_email.hidupkan_lagi(db, ani, ("belum_verifikasi", "tanpa_email"), sekarang=T0), 3)
            await db.commit()
        for nama, (rid, hidup, _) in laporan.items():
            with self.subTest(nama):
                status = await self.antrean(rid)
                self.assertEqual(status, ("menunggu", None, 0, None, None) if hidup else sebelum[nama])

        async with self.Session() as db:
            self.assertEqual(await antrean_email.hidupkan_lagi(db, ani, ("dimatikan",), sekarang=T0), 1)
            await db.commit()
        self.assertEqual(await self.antrean(laporan["6 hari, dimatikan"][0]), ("menunggu", None, 0, None, None))

        # Jalan antrean berikutnya mengirim keempatnya (Ani terverifikasi, tanpa baris pengaturan = email_on).
        self.assertEqual(await self.jalan(T0), {**KOSONG, "terkirim": 4})
        self.assertEqual(self.pengirim.tujuan(), ["ani@contoh.id"] * 4)


if __name__ == "__main__":
    unittest.main()
