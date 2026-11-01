"""Laporan berkala tahap 1, Task 7: API laporan, unduh PDF, dan pengaturan kata sandi (`app/api/routes/laporan.py`;
spec 2026-11-01-laporan-berkala-design bagian 4, 7, dan 8).

Route asli lewat HTTP (httpx ASGITransport, satu event loop dengan mesin async) di atas SQLite in-memory; `get_db` dan
`get_current_user` diganti, jadi pemanggil ditentukan tes (`self.current`). Kunci Fernet ditambal lewat
`rahasia.get_settings`. PDF dibuka dengan `pypdfium2` hanya di thread event loop (pdfium tidak aman antar-thread);
render PDF sendiri jalan di thread kerja `buat_pdf` dan tidak memakai pdfium.

Yang dijaga: laporan hanya untuk pemiliknya (anggota satu household pun 404, jawaban sama dengan "tidak ada" sampai ke
jumlah kueri), kata sandi dan tokennya tidak pernah ada di respons atau log (termasuk galat validasi 422, yang
bawaannya memantulkan masukan), 409 dan 503 membawa `kode`, batas frekuensi per user.
Butuh `aiosqlite`; dilewati bila tidak ada.
Run: python -m unittest app.tests.test_laporan_api -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import importlib.util
import io
import json
import logging
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pypdfium2 as pdfium
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pypdfium2 import PdfiumError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import configure_mappers

from app.api.routes import auth as auth_route, laporan as laporan_route
from app.core.database import Base, get_db
from app.core.deps import get_current_user
from app.core.rate_limit import kunci_per_user
from app.core.security import create_access_token
from app.models.models import (
    JENIS_BULANAN, Household, HouseholdMember, HouseholdRole, Report, ReportSettings, User,
)
from app.services import auth_sessions
from app.services.laporan import rahasia
from app.services.laporan.susun import susun_bulanan
from app.tests.test_laporan_susun import bahan

configure_mappers()
HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None

KUNCI = Fernet.generate_key().decode()
KUNCI_LAIN = Fernet.generate_key().decode()
SANDI = "rahasia-é123"   # NFC, dengan huruf bertanda supaya jalur non-ASCII ikut teruji

# Teks respons persis seperti di Global Constraints (sengaja ditulis ulang di sini, bukan diimpor dari route).
GALAT_404 = {"detail": "Laporan tidak ditemukan"}
GALAT_409 = {"detail": "Atur kata sandi laporan dulu untuk mengunduh PDF.", "kode": "kata_sandi_belum_diatur"}
GALAT_503 = {
    "detail": "Kata sandi laporan belum bisa dipakai di server. Coba lagi nanti.", "kode": "kunci_belum_diatur",
}
GALAT_PANJANG = {"detail": "Kata sandi laporan harus 6–64 karakter."}   # PUT: `detail` selalu kalimat siap tampil

JUN = (date(2026, 6, 1), date(2026, 6, 30))
JUL = (date(2026, 7, 1), date(2026, 7, 31))
AGS = (date(2026, 8, 1), date(2026, 8, 31))
SEP = (date(2026, 9, 1), date(2026, 9, 30))
OKT = (date(2026, 10, 1), date(2026, 10, 31))
T1, T2, T3, T4 = (datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc) + timedelta(days=n) for n in range(4))

BENTUK_RINGKAS = {"id", "jenis", "judul", "periode_mulai", "periode_akhir", "terbit_at", "nama_file"}
BENTUK_PENGATURAN = {
    "kata_sandi_diatur", "email", "email_terverifikasi", "email_on", "kuartalan_on", "tahunan_on", "pro",
}


def _kunci_palsu(kunci: str):
    """Tambal pembacaan setelan: `rahasia` hanya membaca kunci lewat get_settings()."""
    return patch.object(rahasia, "get_settings", return_value=SimpleNamespace(REPORT_SECRET_KEY=kunci))


def masuk(token: str, skema: str = "Bearer", sisa: str = "") -> dict:
    """Header Authorization untuk `token` asli (`create_access_token`). `skema` dan `sisa` membuat varian yang tetap
    lolos autentikasi: HTTPBearer menerima huruf besar-kecil apa pun pada skema, dan PyJWT mengabaikan karakter di
    luar abjad base64url di ujung token."""
    return {"Authorization": f"{skema} {token}{sisa}"}


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class ApiDasar(unittest.IsolatedAsyncioTestCase):
    """Database, aplikasi, klien, dan pembantu bersama (tanpa tes sendiri). Ani dan Budi satu household, Cici di
    household lain, Dewi Pro dengan email terverifikasi."""

    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addAsyncCleanup(self.engine.dispose)

        # Postgres menegakkan FK; tanpa ini SQLite meloloskan urutan yang salah.
        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_on(conn, _record):
            conn.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.statements = []   # semua SQL yang dijalankan (jumlah dan bentuk kueri)
        event.listen(self.engine.sync_engine, "before_cursor_execute",
                     lambda conn, cur, statement, *_a: self.statements.append(statement))

        async with self.Session() as db:
            self.rumah, self.rumah_lain = Household(name="Rumah Ani"), Household(name="Rumah Cici")
            self.ani = User(name="Ani", email="ani@example.com")
            self.budi = User(name="Budi", email="budi@example.com")
            self.cici = User(name="Cici", email="cici@example.com")
            self.dewi = User(name="Dewi", email="dewi@example.com", plan="pro",
                             email_verified_at=datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc))
            db.add_all([self.rumah, self.rumah_lain, self.ani, self.budi, self.cici, self.dewi])
            await db.flush()
            db.add_all([
                HouseholdMember(user_id=self.ani.id, household_id=self.rumah.id, role=HouseholdRole.owner),
                HouseholdMember(user_id=self.budi.id, household_id=self.rumah.id, role=HouseholdRole.member),
                HouseholdMember(user_id=self.cici.id, household_id=self.rumah_lain.id, role=HouseholdRole.owner),
            ])
            await db.commit()

        self.current = self.ani
        app = FastAPI()
        app.state.limiter = auth_route.limiter   # seperti main.py: slowapi membutuhkannya untuk jawaban 429
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(laporan_route.router, prefix="/laporan")
        app.include_router(laporan_route.pengaturan_router, prefix="/user")

        async def _db():
            async with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.app = app

        # Batas frekuensi mati kecuali tes yang memeriksanya; keadaan semula dipulihkan apa pun hasilnya.
        limiter = auth_route.limiter
        self.addCleanup(setattr, limiter, "enabled", limiter.enabled)
        self.addCleanup(limiter.reset)
        limiter.enabled = False

        self.klien = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.klien.aclose)
        kunci = _kunci_palsu(KUNCI)
        kunci.start()
        self.addCleanup(kunci.stop)

    # --- pembantu ------------------------------------------------------

    async def buat_laporan(self, user, periode, terbit=T1, data=None) -> uuid.UUID:
        """Laporan bulanan `user` untuk `periode` dengan `data` v1 asli dari `susun_bulanan`."""
        ps, pe = periode
        if data is None:
            data = susun_bulanan(bahan(penerima_nama=user.name, periode_mulai=ps, periode_akhir=pe))
        async with self.Session() as db:
            baris = Report(user_id=user.id, household_id=self.rumah.id, jenis=JENIS_BULANAN, periode_mulai=ps,
                           periode_akhir=pe, payday_day=1, data=data, terbit_at=terbit)
            db.add(baris)
            await db.commit()
            return baris.id

    async def simpan_token(self, user, token):
        """Tulis token apa adanya ke `report_settings` (tanpa lewat PUT), mis. token rusak atau dari kunci lain."""
        async with self.Session() as db:
            baris = await db.get(ReportSettings, user.id)
            if baris is None:
                db.add(ReportSettings(user_id=user.id, kata_sandi_enc=token))
            else:
                baris.kata_sandi_enc = token
            await db.commit()

    async def baris_pengaturan(self, user):
        async with self.Session() as db:
            return await db.get(ReportSettings, user.id)

    async def jumlah_pengaturan(self) -> int:
        async with self.Session() as db:
            return (await db.execute(select(func.count()).select_from(ReportSettings))).scalar()

    async def atur_sandi(self, sandi=SANDI, user=None, headers=None):
        """Atur kata sandi lewat PUT yang asli."""
        if user is not None:
            self.current = user
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)

    async def unduh(self, id_laporan, headers=None):
        return await self.klien.get(f"/laporan/{id_laporan}/pdf", headers=headers)


def buka_pdf(isi: bytes, kata_sandi: str | None = None) -> pdfium.PdfDocument:
    return pdfium.PdfDocument(io.BytesIO(isi), password=kata_sandi)


def teks_halaman_pertama(isi: bytes, kata_sandi: str) -> str:
    doc = buka_pdf(isi, kata_sandi)
    try:
        halaman = doc[0]
        teks = halaman.get_textpage()
        hasil = " ".join(teks.get_text_range().split())
        teks.close()
        halaman.close()
        return hasil
    finally:
        doc.close()


class DaftarDanDetailTests(ApiDasar):
    async def test_daftar_hanya_milik_sendiri_terurut(self):
        # Urutan: terbit_at menurun, lalu periode_mulai menurun. `jun` periodenya paling tua tetapi terbit paling
        # akhir (laporan tertinggal) dan harus di atas: periode bukan penentu utama. `jul` dan `ags` terbit
        # bersamaan (satu transaksi job), jadi periode_mulai yang menentukan.
        jul = await self.buat_laporan(self.ani, JUL, terbit=T1)
        ags = await self.buat_laporan(self.ani, AGS, terbit=T1)
        sep = await self.buat_laporan(self.ani, SEP, terbit=T2)
        okt = await self.buat_laporan(self.ani, OKT, terbit=T3)
        jun = await self.buat_laporan(self.ani, JUN, terbit=T4)
        punya_budi = await self.buat_laporan(self.budi, OKT, terbit=T4)   # satu household dengan Ani
        punya_cici = await self.buat_laporan(self.cici, OKT, terbit=T4)

        r = await self.klien.get("/laporan")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["id"] for x in r.json()], [str(i) for i in (jun, okt, sep, ags, jul)])
        for item in r.json():
            self.assertEqual(set(item), BENTUK_RINGKAS)   # tanpa `data`: daftar tidak membawa angka keuangan
        pertama = r.json()[0]
        self.assertEqual(pertama["jenis"], "bulanan")
        self.assertEqual(pertama["judul"], "Laporan Juni 2026")
        self.assertEqual(pertama["periode_mulai"], "2026-06-01")
        self.assertEqual(pertama["periode_akhir"], "2026-06-30")
        self.assertEqual(pertama["nama_file"], "jatahku-laporan-2026-06.pdf")
        self.assertEqual(datetime.fromisoformat(pertama["terbit_at"]).replace(tzinfo=None), T4.replace(tzinfo=None))

        self.current = self.budi
        self.assertEqual([x["id"] for x in (await self.klien.get("/laporan")).json()], [str(punya_budi)])
        self.current = self.cici
        self.assertEqual([x["id"] for x in (await self.klien.get("/laporan")).json()], [str(punya_cici)])

    async def test_daftar_kosong_bila_belum_ada_laporan(self):
        r = await self.klien.get("/laporan")
        self.assertEqual((r.status_code, r.json()), (200, []))

    async def test_daftar_halaman_dan_batas(self):
        dasar = susun_bulanan(bahan())
        ids = []
        for n in range(26):   # 2024-09 sampai 2026-10, terbit berurutan
            tahun, bulan = 2024 + (8 + n) // 12, (8 + n) % 12 + 1
            ps = date(tahun, bulan, 1)
            pe = (date(tahun + (bulan == 12), bulan % 12 + 1, 1)) - timedelta(days=1)
            ids.append(await self.buat_laporan(self.ani, (ps, pe), terbit=T1 + timedelta(days=n),
                                               data={**dasar, "judul": f"Laporan nomor {n}"}))
        terbaru_dulu = [str(i) for i in reversed(ids)]

        async def ambil(**query):
            r = await self.klien.get("/laporan", params=query)
            self.assertEqual(r.status_code, 200, r.text)
            return [x["id"] for x in r.json()]

        self.assertEqual(await ambil(), terbaru_dulu[:24])                       # bawaan 24
        self.assertEqual(await ambil(limit=100), terbaru_dulu)
        self.assertEqual(await ambil(limit=5), terbaru_dulu[:5])
        self.assertEqual(await ambil(limit=5, offset=5), terbaru_dulu[5:10])
        self.assertEqual(await ambil(limit=10, offset=20), terbaru_dulu[20:])    # halaman terakhir lebih pendek
        self.assertEqual(await ambil(limit=10, offset=26), [])
        for query in ({"limit": 0}, {"limit": 101}, {"limit": -1}, {"offset": -1}, {"limit": "banyak"}):
            with self.subTest(query):
                self.assertEqual((await self.klien.get("/laporan", params=query)).status_code, 422)

    async def test_daftar_tidak_memuat_kolom_data_utuh(self):
        # `data` bisa ratusan baris mutasi; daftar hanya butuh `judul`, jadi hanya kunci itu yang dibaca database.
        await self.buat_laporan(self.ani, OKT)
        self.statements.clear()
        r = await self.klien.get("/laporan")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()[0]["judul"], "Laporan Oktober 2026")
        self.assertEqual(len(self.statements), 1, self.statements)
        self.assertEqual(self.statements[0].count("reports.data"), 1, self.statements[0])
        self.assertIn("JSON_EXTRACT(reports.data", self.statements[0])

    async def test_detail_milik_sendiri_memuat_data_dan_nama_file(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        r = await self.klien.get(f"/laporan/{id_laporan}")
        self.assertEqual(r.status_code, 200, r.text)
        isi = r.json()
        self.assertEqual(set(isi), BENTUK_RINGKAS | {"data"})
        self.assertEqual(isi["id"], str(id_laporan))
        self.assertEqual(isi["judul"], "Laporan Oktober 2026")
        self.assertEqual(isi["nama_file"], "jatahku-laporan-2026-10.pdf")
        harapan = json.loads(json.dumps(susun_bulanan(bahan(penerima_nama="Ani", periode_mulai=OKT[0],
                                                           periode_akhir=OKT[1]))))
        self.assertEqual(isi["data"], harapan)
        self.assertEqual(isi["data"]["judul"], isi["judul"])

    async def test_nama_file_periode_bukan_bulan_kalender_memuat_tanggal_awal(self):
        id_laporan = await self.buat_laporan(self.ani, (date(2026, 9, 25), date(2026, 10, 24)))
        r = await self.klien.get(f"/laporan/{id_laporan}")
        self.assertEqual(r.json()["nama_file"], "jatahku-laporan-2026-09-25.pdf")
        self.assertEqual(r.json()["judul"], "Laporan 25 Sep – 24 Okt 2026")

    async def test_detail_milik_orang_lain_404(self):
        # Budi satu household dengan Ani dan menebak (atau mendapat) id laporannya; Cici di household lain. Sama saja:
        # keanggotaan household tidak memberi akses ke laporan orang.
        punya_ani = await self.buat_laporan(self.ani, OKT)
        for pemanggil in (self.budi, self.cici):
            self.current = pemanggil
            for jalur in (f"/laporan/{punya_ani}", f"/laporan/{punya_ani}/pdf"):
                with self.subTest(pemanggil=pemanggil.name, jalur=jalur):
                    r = await self.klien.get(jalur)
                    self.assertEqual((r.status_code, r.json()), (404, GALAT_404))
        # Pemiliknya tetap bisa (kontrol: 404 di atas karena kepemilikan, bukan karena route rusak).
        self.current = self.ani
        self.assertEqual((await self.klien.get(f"/laporan/{punya_ani}")).status_code, 200)

    async def test_tidak_ada_dan_milik_orang_lain_tak_bisa_dibedakan(self):
        # Jawaban, header, dan kueri yang dijalankan sama persis: tidak ada kueri tambahan yang waktunya membedakan
        # "ada tapi bukan milikmu" dari "tidak ada".
        punya_ani = await self.buat_laporan(self.ani, OKT)
        self.current = self.budi
        for pola in ("/laporan/{}", "/laporan/{}/pdf"):
            jawaban = []
            for id_laporan in (punya_ani, uuid.uuid4()):
                self.statements.clear()
                r = await self.klien.get(pola.format(id_laporan))
                jawaban.append((r.status_code, r.json(), dict(r.headers), list(self.statements)))
            with self.subTest(pola):
                self.assertEqual(jawaban[0], jawaban[1])
                self.assertEqual(len(jawaban[0][3]), 1, jawaban[0][3])
                self.assertEqual(jawaban[0][:2], (404, GALAT_404))

    async def test_id_bukan_uuid_422_bukan_500(self):
        for jalur in ("/laporan/bukan-uuid", "/laporan/bukan-uuid/pdf"):
            self.assertEqual((await self.klien.get(jalur)).status_code, 422)


class UnduhPdfTests(ApiDasar):
    async def test_pdf_tanpa_kata_sandi_409_dengan_kode(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock()) as buat, \
                self.assertNoLogs("jatahku.laporan", level="WARNING"):   # belum diatur itu keadaan biasa, bukan galat
            r = await self.unduh(id_laporan)                              # tanpa baris report_settings
            self.assertEqual((r.status_code, r.json()), (409, GALAT_409))
            async with self.Session() as db:                              # baris ada, kata sandinya belum
                db.add(ReportSettings(user_id=self.ani.id, email_on=False))
                await db.commit()
            r = await self.unduh(id_laporan)
            self.assertEqual((r.status_code, r.json()), (409, GALAT_409))
        buat.assert_not_called()
        self.assertNotIn("content-disposition", r.headers)

    async def test_pdf_tanpa_kunci_503(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi()   # kata sandi tersimpan, lalu kunci server hilang
        for nama, kunci in [("kosong", ""), ("bukan kunci Fernet", "bukan-kunci")]:
            with self.subTest(nama), _kunci_palsu(kunci), \
                    patch.object(laporan_route.pdf, "buat_pdf", AsyncMock()) as buat:
                r = await self.unduh(id_laporan)
                self.assertEqual((r.status_code, r.json()), (503, GALAT_503))
                buat.assert_not_called()
        # Tanpa kunci dan tanpa kata sandi: 503 yang berlaku (pengguna tak bisa mengaturnya sebelum server siap).
        self.current = self.budi
        punya_budi = await self.buat_laporan(self.budi, OKT)
        with _kunci_palsu(""):
            self.assertEqual((await self.unduh(punya_budi)).json(), GALAT_503)

    async def test_pdf_milik_orang_lain_404_walau_kunci_hilang(self):
        # Kepemilikan diperiksa lebih dulu: laporan orang lain tidak pernah menjawab 503 atau 409.
        punya_ani = await self.buat_laporan(self.ani, OKT)
        self.current = self.budi
        with _kunci_palsu(""), patch.object(laporan_route.pdf, "buat_pdf", AsyncMock()) as buat:
            r = await self.unduh(punya_ani)
        self.assertEqual((r.status_code, r.json()), (404, GALAT_404))
        buat.assert_not_called()

    async def test_pdf_token_tak_terbaca_409(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        asli = rahasia.enkripsi("sandi-lama-rahasia")
        for nama, token in [
            ("dari kunci lain", Fernet(KUNCI_LAIN.encode()).encrypt(b"sandi-lama-rahasia").decode()),
            ("bukan token Fernet", "bukan-token-fernet"),
            ("terpotong", asli[:-8]),
            ("bukan ASCII", "token-é-rusak"),
        ]:
            with self.subTest(nama):
                await self.simpan_token(self.ani, token)
                with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock()) as buat, \
                        self.assertLogs("jatahku.laporan", level="WARNING") as tangkap:
                    r = await self.unduh(id_laporan)
                self.assertEqual((r.status_code, r.json()), (409, GALAT_409))   # seperti belum diatur
                buat.assert_not_called()
                catatan = "\n".join(tangkap.output)
                self.assertIn(str(self.ani.id), catatan)         # operator tahu siapa yang perlu mengatur ulang
                for rahasia_ in (token, "sandi-lama-rahasia", KUNCI, KUNCI_LAIN):
                    self.assertNotIn(rahasia_, catatan)

    async def test_pdf_kata_sandi_tersimpan_tidak_valid_untuk_pdf_409(self):
        # Kata sandi yang kini ditolak `periksa_kata_sandi` (mis. aturan diperketat setelah tersimpan) tidak boleh
        # menjadi 500 dan tidak boleh menghasilkan PDF tanpa kata sandi: 409, seperti belum diatur.
        id_laporan = await self.buat_laporan(self.ani, OKT)
        for nama, sandi in [
            ("karakter kontrol", "abc\x07def-rahasia"),
            ("spasi tak terputus", "abc\N{NO-BREAK SPACE}def-rahasia"),
            ("hanya karakter tak kasatmata", "\N{SOFT HYPHEN}" * 8),
        ]:
            with self.subTest(nama):
                await self.simpan_token(self.ani, rahasia.enkripsi(sandi))
                with self.assertLogs("jatahku.laporan", level="WARNING") as tangkap:
                    r = await self.unduh(id_laporan)
                self.assertEqual((r.status_code, r.json()), (409, GALAT_409))
                self.assertNotIn("application/pdf", r.headers.get("content-type", ""))
                catatan = "\n".join(tangkap.output)
                self.assertIn(str(self.ani.id), catatan)
                self.assertNotIn("rahasia", catatan)

    async def test_pdf_berhasil(self):
        sep = await self.buat_laporan(self.ani, SEP, terbit=T1)
        okt = await self.buat_laporan(self.ani, OKT, terbit=T2)
        await self.atur_sandi()
        r = await self.unduh(okt)
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertEqual(r.headers["content-disposition"], 'attachment; filename="jatahku-laporan-2026-10.pdf"')
        self.assertEqual(r.headers["cache-control"], "no-store")
        # Berkas terenkripsi: tidak terbuka tanpa atau dengan kata sandi salah, terbuka dengan kata sandi laporan.
        for salah in (None, "salah-sandi", SANDI.upper()):
            with self.subTest(salah):
                with self.assertRaises(PdfiumError) as ctx:
                    buka_pdf(r.content, salah)
                self.assertRegex(str(ctx.exception), r"(?i)password")   # gagal karena kata sandi, bukan berkas rusak
        teks = teks_halaman_pertama(r.content, SANDI)
        self.assertIn("Laporan Oktober 2026", teks)
        self.assertNotIn("Laporan September 2026", teks)

        # Laporan lain milik Ani: PDF-nya dari datanya sendiri, nama berkasnya mengikuti periodenya.
        r = await self.unduh(sep)
        self.assertEqual(r.headers["content-disposition"], 'attachment; filename="jatahku-laporan-2026-09.pdf"')
        self.assertIn("Laporan September 2026", teks_halaman_pertama(r.content, SANDI))

    async def test_pdf_memakai_kata_sandi_user_pemanggil(self):
        # Dua user, dua kata sandi: PDF Budi hanya terbuka dengan kata sandi Budi.
        await self.atur_sandi("sandi-milik-ani-1", user=self.ani)
        await self.atur_sandi("sandi-milik-budi-2", user=self.budi)
        punya_budi = await self.buat_laporan(self.budi, OKT)
        r = await self.unduh(punya_budi)
        self.assertEqual(r.status_code, 200)
        with self.assertRaises(PdfiumError):
            buka_pdf(r.content, "sandi-milik-ani-1")
        self.assertIn("Laporan Oktober 2026", teks_halaman_pertama(r.content, "sandi-milik-budi-2"))

    async def test_pdf_kata_sandi_nfd_dibuka_dengan_bentuk_nfc(self):
        # PUT menyimpan bentuk NFC; PDF-nya terbuka dengan yang diketik keyboard ("é" utuh), juga di pembaca
        # berbasis pdfium yang tidak melakukan SASLprep.
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi("cafe\N{COMBINING ACUTE ACCENT}-123")
        r = await self.unduh(id_laporan)
        self.assertEqual(r.status_code, 200)
        nfc = "caf\N{LATIN SMALL LETTER E WITH ACUTE}-123"
        self.assertIn("Laporan Oktober 2026", teks_halaman_pertama(r.content, nfc))

    async def test_pdf_koneksi_database_dilepas_sebelum_render(self):
        # Render menunggu giliran semaphore (maks 2 sekaligus) dan makan ratusan milidetik; koneksi dari kolam
        # (5 + 10 untuk seluruh API) tidak boleh tertahan selama itu.
        from sqlalchemy.ext.asyncio import AsyncSession
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi()
        urutan = []
        asli_tutup = AsyncSession.close

        async def tutup(sesi):
            urutan.append("tutup")
            return await asli_tutup(sesi)

        async def render(data, kata_sandi):
            urutan.append("render")
            return b"%PDF-1.7 palsu"

        with patch.object(AsyncSession, "close", tutup), patch.object(laporan_route.pdf, "buat_pdf", render):
            r = await self.unduh(id_laporan)
        self.assertEqual(r.status_code, 200)
        self.assertLess(urutan.index("tutup"), urutan.index("render"), urutan)

    async def test_pdf_kata_sandi_tidak_masuk_log(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        tangkap = _TangkapLog()
        log = logging.getLogger("jatahku.laporan")
        log.addHandler(tangkap)
        self.addCleanup(log.removeHandler, tangkap)
        peringkat = log.level
        log.setLevel(logging.DEBUG)
        self.addCleanup(log.setLevel, peringkat)
        await self.atur_sandi()
        self.assertEqual((await self.unduh(id_laporan)).status_code, 200)
        token = (await self.baris_pengaturan(self.ani)).kata_sandi_enc
        with _kunci_palsu(KUNCI_LAIN):                       # token jadi tak terbaca
            self.assertEqual((await self.unduh(id_laporan)).status_code, 409)
        for rekaman in tangkap.rekaman:
            teks = rekaman.getMessage() + repr(rekaman.args) + str(rekaman.exc_text)
            for rahasia_ in (SANDI, token, KUNCI, KUNCI_LAIN):
                self.assertNotIn(rahasia_, teks)


class _TangkapLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.rekaman = []

    def emit(self, rekaman):
        self.rekaman.append(rekaman)


class PengaturanTests(ApiDasar):
    async def test_get_pengaturan_bawaan_dan_pro(self):
        r = await self.klien.get("/user/laporan-pengaturan")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {
            "kata_sandi_diatur": False, "email": "ani@example.com", "email_terverifikasi": False,
            "email_on": True, "kuartalan_on": True, "tahunan_on": True, "pro": False,
        })
        self.assertEqual(await self.jumlah_pengaturan(), 0, "GET tidak boleh membuat baris")

        self.current = self.dewi   # Pro dengan email terverifikasi
        r = await self.klien.get("/user/laporan-pengaturan")
        self.assertEqual(r.json(), {
            "kata_sandi_diatur": False, "email": "dewi@example.com", "email_terverifikasi": True,
            "email_on": True, "kuartalan_on": True, "tahunan_on": True, "pro": True,
        })
        self.assertEqual(await self.jumlah_pengaturan(), 0)

    async def test_get_pengaturan_akun_tanpa_email(self):
        async with self.Session() as db:
            telegram = User(name="Tono", email=None, telegram_id="123")
            db.add(telegram)
            await db.commit()
        self.current = telegram
        r = await self.klien.get("/user/laporan-pengaturan")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["email"])
        self.assertFalse(r.json()["email_terverifikasi"])

    async def test_get_pengaturan_membaca_baris_yang_ada(self):
        async with self.Session() as db:
            db.add(ReportSettings(user_id=self.ani.id, email_on=False, kuartalan_on=False, tahunan_on=False))
            await db.commit()
        r = await self.klien.get("/user/laporan-pengaturan")
        self.assertEqual(r.json(), {
            "kata_sandi_diatur": False, "email": "ani@example.com", "email_terverifikasi": False,
            "email_on": False, "kuartalan_on": False, "tahunan_on": False, "pro": False,
        })

    async def test_pengaturan_bawaan_sama_dengan_bawaan_kolom(self):
        # Tanpa baris, GET menjawab bawaan route; dengan baris baru, bawaan kolom. Keduanya harus sama.
        kolom = ReportSettings.__table__.c
        self.assertEqual(set(laporan_route.BAWAAN_PENGATURAN), {"email_on", "kuartalan_on", "tahunan_on"})
        for nama, nilai in laporan_route.BAWAAN_PENGATURAN.items():
            self.assertEqual(kolom[nama].default.arg, nilai, nama)

    async def test_put_menyimpan_terenkripsi(self):
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": SANDI})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {
            "kata_sandi_diatur": True, "email": "ani@example.com", "email_terverifikasi": False,
            "email_on": True, "kuartalan_on": True, "tahunan_on": True, "pro": False,
        })
        baris = await self.baris_pengaturan(self.ani)
        self.assertIsNotNone(baris)
        self.assertNotEqual(baris.kata_sandi_enc, SANDI)
        self.assertNotIn(SANDI, baris.kata_sandi_enc)
        self.assertEqual(rahasia.dekripsi(baris.kata_sandi_enc), SANDI)
        # Respons PUT dan GET sesudahnya tidak memuat kata sandi, token, atau nama kolomnya.
        r_get = await self.klien.get("/user/laporan-pengaturan")
        self.assertTrue(r_get.json()["kata_sandi_diatur"])
        for teks in (r.text, r_get.text):
            for rahasia_ in (SANDI, baris.kata_sandi_enc, "kata_sandi_enc", "gAAAA"):
                self.assertNotIn(rahasia_, teks)

    async def test_put_menormalkan_nfc_sebelum_disimpan(self):
        await self.atur_sandi("cafe\N{COMBINING ACUTE ACCENT}-123")
        tersimpan = rahasia.dekripsi((await self.baris_pengaturan(self.ani)).kata_sandi_enc)
        self.assertEqual(tersimpan, "caf\N{LATIN SMALL LETTER E WITH ACUTE}-123")
        self.assertEqual(len(tersimpan), 8)

    async def test_put_kata_sandi_pendek_422(self):
        for sandi in ["rhs-1", "", "a"]:
            with self.subTest(sandi):
                r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi})
                self.assertEqual((r.status_code, r.json()), (422, GALAT_PANJANG))
        self.assertEqual(await self.jumlah_pengaturan(), 0)

    async def test_put_batas_panjang_6_sampai_64_karakter(self):
        for sandi, harapan in [("a" * 5, 422), ("a" * 6, 200), ("a" * 64, 200), ("a" * 65, 422)]:
            with self.subTest(panjang=len(sandi)):
                r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi})
                self.assertEqual(r.status_code, harapan, r.text)
                if harapan == 422:
                    self.assertEqual(r.json(), GALAT_PANJANG)

    async def test_put_panjang_dihitung_per_karakter_bukan_unit_utf16(self):
        # Formulir (HTML `minLength`) menghitung unit UTF-16: tiga emoji = 6 unit, lolos formulir, padahal hanya tiga
        # karakter. Jawabannya tetap kalimat siap tampil, bukan daftar galat pydantic berbahasa Inggris.
        tiga = "\N{KEY}" * 3
        self.assertEqual(len(tiga.encode("utf-16-le")) // 2, 6)
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": tiga})
        self.assertEqual((r.status_code, r.json()), (422, GALAT_PANJANG))
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": "\N{KEY}" * 6})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_put_pendek_setelah_nfc_ditolak(self):
        # Enam titik kode, tetapi setelah NFC tinggal tiga huruf: yang dihitung adalah kata sandi yang tersimpan.
        sandi = "e\N{COMBINING ACUTE ACCENT}" * 3
        self.assertEqual(len(sandi), 6)
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi})
        self.assertEqual((r.status_code, r.json()), (422, GALAT_PANJANG))
        self.assertEqual(await self.jumlah_pengaturan(), 0)

    async def test_put_menolak_kata_sandi_yang_tak_bisa_dipakai_di_pdf(self):
        # Semua lolos 6-64 karakter, tetapi tak akan terbuka dengan benar di pembaca PDF (atau malah menghasilkan PDF
        # tanpa kata sandi). Ditolak di muka dengan pesan siap tampil; tidak ada yang tersimpan.
        for nama, sandi in [
            ("karakter kontrol", "abc\x07def-rhs"),
            ("NUL", "abc\x00def-rhs"),
            ("spasi tak terputus", "abc\N{NO-BREAK SPACE}def-rhs"),
            ("spasi lebar", "abc\N{IDEOGRAPHIC SPACE}def-rhs"),
            ("tanda hubung lunak di tengah", "abc\N{SOFT HYPHEN}def-rhs"),
            ("huruf lebar penuh", "\N{FULLWIDTH LATIN SMALL LETTER K}opi-susu"),
            ("angka berlingkar", "kopi-susu-\N{CIRCLED DIGIT ONE}"),
            ("ligatur", "\N{LATIN SMALL LIGATURE FI}le-susu-123"),
            ("hanya karakter tak kasatmata", "\N{SOFT HYPHEN}" * 8),
            ("lebih dari 127 byte UTF-8", "中" * 43),
        ]:
            with self.subTest(nama):
                r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi})
                self.assertEqual(r.status_code, 422, r.text)
                detail = r.json()["detail"]
                self.assertIsInstance(detail, str)
                self.assertTrue(detail.startswith("Kata sandi"), detail)
                self.assertNotIn("rhs", r.text)
                self.assertNotIn("susu", r.text)
                self.assertNotIn("中", r.text)
        self.assertEqual(await self.jumlah_pengaturan(), 0)

    async def test_put_kata_sandi_wajar_diterima(self):
        for sandi in ["Sandi Rahasia #1 & 2!", "🔑🔑🔑🔑🔑🔑", "kopi-é123", "é" * 63 + "a", "a" * 64]:
            with self.subTest(sandi[:10]):
                r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": sandi})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(rahasia.dekripsi((await self.baris_pengaturan(self.ani)).kata_sandi_enc), sandi)

    async def test_put_galat_validasi_tidak_memantulkan_masukan(self):
        # FastAPI memantulkan nilai yang ditolak di galat 422 (`input`); untuk badan berisi kata sandi, itu berarti
        # kata sandinya kembali di respons. (Panjang yang salah dijawab kalimat tetap: tes lain di atas.)
        json_rusak = {"content": b'{"kata_sandi": "rahasia-rusak', "headers": {"content-type": "application/json"}}
        percobaan = [
            ("bukan teks", {"json": {"kata_sandi": 123456789}}, "123456789"),
            ("badan berupa daftar", {"json": ["rahasia-daftar"]}, "rahasia-daftar"),
            ("kolom lain saja", {"json": {"sandi": "rahasia-salah-kolom"}}, "rahasia-salah-kolom"),
            ("JSON rusak", json_rusak, "rahasia-rusak"),
        ]
        for nama, kirim, rahasia_ in percobaan:
            with self.subTest(nama):
                r = await self.klien.put("/user/laporan-pengaturan", **kirim)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertNotIn(rahasia_, r.text)
                galat = r.json()["detail"]
                self.assertIsInstance(galat, list)
                self.assertTrue(galat)
                for satu in galat:   # tetap berguna: jenis, lokasi, dan pesan galatnya ada
                    self.assertEqual(set(satu), {"type", "loc", "msg"})
        self.assertEqual(await self.jumlah_pengaturan(), 0)

    async def test_put_tanpa_kunci_503(self):
        with _kunci_palsu(""):
            r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": SANDI})
        self.assertEqual((r.status_code, r.json()), (503, GALAT_503))
        self.assertEqual(await self.jumlah_pengaturan(), 0)
        with _kunci_palsu("bukan-kunci"):
            r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": SANDI})
        self.assertEqual((r.status_code, r.json()), (503, GALAT_503))
        self.assertNotIn(SANDI, r.text)

    async def test_put_dua_kali_memperbarui_satu_baris(self):
        await self.atur_sandi("sandi-pertama-1")
        pertama = (await self.baris_pengaturan(self.ani)).kata_sandi_enc
        async with self.Session() as db:   # tandai baris tua supaya pembaruan `updated_at` terlihat pasti
            await db.execute(update(ReportSettings).values(updated_at=datetime(2020, 1, 1)))
            await db.commit()
        await self.atur_sandi("sandi-kedua-22")
        self.assertEqual(await self.jumlah_pengaturan(), 1)
        baris = await self.baris_pengaturan(self.ani)
        self.assertNotEqual(baris.kata_sandi_enc, pertama)
        self.assertEqual(rahasia.dekripsi(baris.kata_sandi_enc), "sandi-kedua-22")
        self.assertGreater(baris.updated_at.replace(tzinfo=None), datetime.now(timezone.utc).replace(tzinfo=None)
                           - timedelta(minutes=1))

    async def test_put_hanya_menyentuh_baris_pemanggil(self):
        await self.atur_sandi("sandi-milik-budi-2", user=self.budi)
        token_budi = (await self.baris_pengaturan(self.budi)).kata_sandi_enc
        await self.atur_sandi("sandi-milik-ani-1", user=self.ani)
        self.assertEqual((await self.baris_pengaturan(self.budi)).kata_sandi_enc, token_budi)
        self.assertEqual(await self.jumlah_pengaturan(), 2)
        self.current = self.budi
        self.assertTrue((await self.klien.get("/user/laporan-pengaturan")).json()["kata_sandi_diatur"])
        self.current = self.cici
        self.assertFalse((await self.klien.get("/user/laporan-pengaturan")).json()["kata_sandi_diatur"])

    async def test_put_mempertahankan_pengaturan_lain(self):
        async with self.Session() as db:
            db.add(ReportSettings(user_id=self.ani.id, email_on=False, kuartalan_on=False, tahunan_on=True))
            await db.commit()
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": SANDI})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["email_on"], r.json()["kuartalan_on"], r.json()["tahunan_on"]),
                         (False, False, True))
        baris = await self.baris_pengaturan(self.ani)
        self.assertEqual((baris.email_on, baris.kuartalan_on, baris.tahunan_on), (False, False, True))

    async def test_put_mengunci_baris_user_supaya_simpan_pertama_bersamaan_tidak_bertabrakan(self):
        # Dua simpan pertama yang bersamaan sama-sama tidak menemukan baris lalu INSERT, dan yang kalah gagal di kunci
        # utama. Di Postgres, kueri ini menyerialkannya per user (pola fund_shift: FOR NO KEY UPDATE).
        from sqlalchemy.dialects import postgresql
        stmt = laporan_route._kunci_user(self.ani.id)
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR NO KEY UPDATE", sql)
        self.assertIn("users", sql)
        self.statements.clear()
        await self.atur_sandi()
        kunci = [i for i, s in enumerate(self.statements) if "FROM users" in s]
        baca = [i for i, s in enumerate(self.statements) if "FROM report_settings" in s]
        self.assertEqual(len(kunci), 1, self.statements)
        self.assertTrue(baca, self.statements)
        self.assertLess(kunci[0], baca[0], self.statements)   # kunci dulu, baru cari baris yang mungkin belum ada


class BatasFrekuensiTests(ApiDasar):
    """Batas frekuensi lewat `get_current_user` yang ASLI dan token asli (ruling R11): kunci batas adalah user yang
    terautentikasi (klaim `sub`), bukan teks header. Hanya `get_db` yang diganti."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.app.dependency_overrides.pop(get_current_user)
        self.token_ani = create_access_token(str(self.ani.id))
        self.token_budi = create_access_token(str(self.budi.id))
        self.h_ani, self.h_budi = masuk(self.token_ani), masuk(self.token_budi)

    def nyalakan_limiter(self):
        auth_route.limiter.reset()
        auth_route.limiter.enabled = True

    async def varian_header(self, user, token) -> dict:
        """Semua bentuk header yang lolos autentikasi sebagai `user` yang sama: skema berbeda huruf, karakter di ujung
        yang diabaikan PyJWT, dan token dari login ulang (sesi dan token baru)."""
        async with self.Session() as db:
            login_ulang = (await auth_sessions.start_session(db, user)).access_token
        self.assertNotEqual(login_ulang, token)
        return {
            "skema kecil": masuk(token, skema="bearer"),
            "skema besar": masuk(token, skema="BEARER"),
            "skema campur": masuk(token, skema="BeArEr"),
            "sisa karakter yang diabaikan PyJWT": masuk(token, sisa="!!!!"),
            "token dari login ulang": masuk(login_ulang),
            "login ulang, skema besar dan sisa": masuk(login_ulang, skema="BEARER", sisa="!!"),
        }

    async def test_batas_frekuensi_pdf(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi(headers=self.h_ani)
        self.nyalakan_limiter()
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock(return_value=b"%PDF-1.7 palsu")):
            for n in range(10):
                r = await self.unduh(id_laporan, headers=self.h_ani)
                self.assertEqual(r.status_code, 200, f"panggilan ke-{n + 1}: {r.text}")
            r = await self.unduh(id_laporan, headers=self.h_ani)
            self.assertEqual(r.status_code, 429, r.text)
            self.assertNotIn("%PDF", r.text)

            # Batasnya per user: Budi dengan tokennya sendiri tidak ikut terkena.
            punya_budi = await self.buat_laporan(self.budi, OKT)
            await self.atur_sandi("sandi-milik-budi-2", headers=self.h_budi)
            r = await self.unduh(punya_budi, headers=self.h_budi)
            self.assertEqual(r.status_code, 200, r.text)

    async def test_batas_frekuensi_pdf_berlaku_untuk_semua_laporan_satu_user(self):
        # slowapi menghitung `limit()` per URL persis, jadi tanpa ember bersama batas 10/menit berlaku per laporan:
        # user dengan 12 laporan bisa memicu 120 render semenit. Sebelas laporan berbeda: yang ke-11 ditolak.
        ids = []
        for bulan in range(1, 12):   # Januari sampai November 2026: sebelas laporan berbeda
            akhir = date(2026, bulan + 1, 1) - timedelta(days=1)
            ids.append(await self.buat_laporan(self.ani, (date(2026, bulan, 1), akhir)))
        await self.atur_sandi(headers=self.h_ani)
        self.nyalakan_limiter()
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock(return_value=b"%PDF-1.7 palsu")):
            for n, id_laporan in enumerate(ids[:10]):
                r = await self.unduh(id_laporan, headers=self.h_ani)
                self.assertEqual(r.status_code, 200, f"laporan ke-{n + 1}: {r.text}")
            for id_laporan in (ids[10], ids[0]):   # laporan baru maupun yang sudah pernah diunduh
                r = await self.unduh(id_laporan, headers=self.h_ani)
                self.assertEqual(r.status_code, 429, r.text)

    async def test_batas_frekuensi_pdf_tidak_bisa_dihindari_dengan_varian_header(self):
        # Yang dilaporkan review: setelah 10 unduhan, mengganti huruf skema, menambah karakter di ujung token, atau
        # login ulang memberi ember baru. Kunci batasnya user, jadi semuanya tetap ditolak.
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi(headers=self.h_ani)
        varian = await self.varian_header(self.ani, self.token_ani)
        for nama, header in varian.items():   # premis: setiap varian lolos autentikasi sebagai Ani (404 = id acak)
            with self.subTest("lolos autentikasi", varian=nama):
                self.assertEqual((await self.unduh(uuid.uuid4(), headers=header)).status_code, 404)
        self.nyalakan_limiter()
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock(return_value=b"%PDF-1.7 palsu")):
            for n in range(10):
                r = await self.unduh(id_laporan, headers=self.h_ani)
                self.assertEqual(r.status_code, 200, f"panggilan ke-{n + 1}: {r.text}")
            for nama, header in varian.items():
                with self.subTest(varian=nama):
                    r = await self.unduh(id_laporan, headers=header)
                    self.assertEqual(r.status_code, 429, r.text)

    async def test_batas_frekuensi_pdf_menghitung_semua_bentuk_header_dalam_satu_ember(self):
        # Sepuluh unduhan yang bergantian memakai semua bentuk header (dan dua token) menghabiskan satu ember; yang
        # ke-11, bentuk apa pun, ditolak. Bila tiap bentuk punya ember sendiri, jumlah ini tidak akan pernah tercapai.
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi(headers=self.h_ani)
        bentuk = [self.h_ani, *(await self.varian_header(self.ani, self.token_ani)).values()]
        self.nyalakan_limiter()
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock(return_value=b"%PDF-1.7 palsu")):
            for n in range(10):
                r = await self.unduh(id_laporan, headers=bentuk[n % len(bentuk)])
                self.assertEqual(r.status_code, 200, f"panggilan ke-{n + 1}: {r.text}")
            for n, header in enumerate(bentuk):
                r = await self.unduh(id_laporan, headers=header)
                self.assertEqual(r.status_code, 429, f"bentuk ke-{n + 1}: {r.text}")

    async def test_batas_frekuensi_pdf_juga_untuk_404(self):
        # Menebak id tetap dihitung: tidak ada jalur gratis untuk menyapu id (atau menahan koneksi tanpa batas).
        self.nyalakan_limiter()
        for n in range(10):
            r = await self.unduh(uuid.uuid4(), headers=self.h_ani)
            self.assertEqual(r.status_code, 404, f"panggilan ke-{n + 1}")
        self.assertEqual((await self.unduh(uuid.uuid4(), headers=self.h_ani)).status_code, 429)

    async def test_batas_frekuensi_pdf_tidak_dibagi_dengan_simpan_kata_sandi(self):
        # Dua rute, dua ember: menghabiskan jatah unduhan tidak menutup pengaturan kata sandi (dan sebaliknya).
        self.nyalakan_limiter()
        for _ in range(10):
            await self.unduh(uuid.uuid4(), headers=self.h_ani)
        self.assertEqual((await self.unduh(uuid.uuid4(), headers=self.h_ani)).status_code, 429)
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": SANDI}, headers=self.h_ani)
        self.assertEqual(r.status_code, 200, r.text)

    async def test_batas_frekuensi_simpan_kata_sandi(self):
        self.nyalakan_limiter()
        for n in range(5):
            r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": f"sandi-ke-{n}-xx"},
                                     headers=self.h_ani)
            self.assertEqual(r.status_code, 200, f"simpan ke-{n + 1}: {r.text}")
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": "sandi-ke-6-xx"},
                                 headers=self.h_ani)
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(rahasia.dekripsi((await self.baris_pengaturan(self.ani)).kata_sandi_enc), "sandi-ke-4-xx")
        # Membaca status tidak dibatasi.
        r = await self.klien.get("/user/laporan-pengaturan", headers=self.h_ani)
        self.assertEqual(r.status_code, 200)

    async def test_batas_frekuensi_simpan_tidak_bisa_dihindari_dengan_varian_header(self):
        varian = await self.varian_header(self.ani, self.token_ani)
        for nama, header in varian.items():   # premis: setiap varian lolos autentikasi (batas belum menyala)
            with self.subTest("lolos autentikasi", varian=nama):
                await self.atur_sandi(headers=header)
        self.nyalakan_limiter()
        for n in range(5):
            await self.atur_sandi(f"sandi-ke-{n}-xx", headers=self.h_ani)
        for nama, header in varian.items():
            with self.subTest(varian=nama):
                r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": "sandi-lain-yy"},
                                         headers=header)
                self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(rahasia.dekripsi((await self.baris_pengaturan(self.ani)).kata_sandi_enc), "sandi-ke-4-xx")

    async def test_batas_frekuensi_simpan_per_user(self):
        self.nyalakan_limiter()
        for n in range(5):
            await self.atur_sandi(f"sandi-ke-{n}-xx", headers=self.h_ani)
        r = await self.klien.put("/user/laporan-pengaturan", json={"kata_sandi": "sandi-ke-6-xx"}, headers=self.h_ani)
        self.assertEqual(r.status_code, 429, r.text)
        await self.atur_sandi("sandi-milik-budi-2", headers=self.h_budi)   # ember Budi sendiri (menegaskan 200)

    async def test_tanpa_token_sah_kunci_jatuh_ke_ip(self):
        # Di jalur nyata permintaan tanpa token sah ditolak 401 sebelum batas diperiksa. Bila sampai (di sini
        # autentikasinya diganti), satu-satunya identitas adalah alamat IP: pemanggil dari alamat yang sama berbagi
        # ember, apa pun isi header-nya.
        self.app.dependency_overrides[get_current_user] = lambda: self.current
        id_laporan = await self.buat_laporan(self.ani, OKT)
        await self.atur_sandi(user=self.ani)
        self.nyalakan_limiter()
        with patch.object(laporan_route.pdf, "buat_pdf", AsyncMock(return_value=b"%PDF-1.7 palsu")):
            for n in range(10):
                r = await self.unduh(id_laporan)   # tanpa header
                self.assertEqual(r.status_code, 200, f"panggilan ke-{n + 1}: {r.text}")
            self.current = self.budi
            for nama, header in {
                "tanpa header": None,
                "token tak sah": {"Authorization": "Bearer bukan-token"},
                "skema lain": masuk("x", skema="Basic"),
            }.items():
                with self.subTest(nama):
                    r = await self.unduh(uuid.uuid4(), headers=header)
                    self.assertEqual(r.status_code, 429, r.text)

    async def test_daftar_dan_detail_tidak_dibatasi_seperti_pdf(self):
        id_laporan = await self.buat_laporan(self.ani, OKT)
        self.nyalakan_limiter()
        for _ in range(15):
            for jalur in ("/laporan", f"/laporan/{id_laporan}"):
                r = await self.klien.get(jalur, headers=self.h_ani)
                self.assertEqual(r.status_code, 200, jalur)


@unittest.skipUnless(HAS_AIOSQLITE, "butuh aiosqlite")
class TanpaLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_semua_endpoint_butuh_login(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                     connect_args={"check_same_thread": False})
        self.addAsyncCleanup(engine.dispose)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        app = FastAPI()
        app.state.limiter = auth_route.limiter
        app.include_router(laporan_route.router, prefix="/laporan")
        app.include_router(laporan_route.pengaturan_router, prefix="/user")

        async def _db():
            async with Session() as db:
                yield db
        app.dependency_overrides[get_db] = _db   # `get_current_user` tidak diganti: yang asli menolak tanpa token
        sebelumnya = auth_route.limiter.enabled
        auth_route.limiter.enabled = False
        self.addCleanup(setattr, auth_route.limiter, "enabled", sebelumnya)
        klien = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(klien.aclose)
        uid = uuid.uuid4()
        for metode, jalur in [
            ("GET", "/laporan"), ("GET", f"/laporan/{uid}"), ("GET", f"/laporan/{uid}/pdf"),
            ("GET", "/user/laporan-pengaturan"), ("PUT", "/user/laporan-pengaturan"),
        ]:
            with self.subTest(metode=metode, jalur=jalur):
                kirim = {"json": {"kata_sandi": SANDI}} if metode == "PUT" else {}
                for header in ({}, {"Authorization": "Bearer bukan-token"}):
                    r = await klien.request(metode, jalur, headers=header, **kirim)
                    self.assertEqual(r.status_code, 401, r.text)


class PemasanganTests(unittest.TestCase):
    def test_rute_terdaftar_di_aplikasi(self):
        from fastapi.routing import APIRoute
        from app.main import app
        terdaftar = {(m, r.path): r for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
        for harapan in [
            ("GET", "/laporan"), ("GET", "/laporan/{report_id}"), ("GET", "/laporan/{report_id}/pdf"),
            ("GET", "/user/laporan-pengaturan"), ("PUT", "/user/laporan-pengaturan"),
        ]:
            with self.subTest(harapan):
                self.assertIn(harapan, terdaftar)
                self.assertIn("laporan", terdaftar[harapan].tags)

    def test_batas_frekuensi_terpasang_di_dua_rute_yang_tepat(self):
        # Batas dipasang di fungsi route (slowapi mendaftarkannya menurut modul dan nama fungsi).
        batas = auth_route.limiter._route_limits
        pdf_batas = batas[f"{laporan_route.__name__}.unduh_pdf_laporan"]
        simpan_batas = batas[f"{laporan_route.__name__}.simpan_pengaturan_laporan"]
        self.assertEqual([str(b.limit) for b in pdf_batas], ["10 per 1 minute"])
        self.assertEqual([str(b.limit) for b in simpan_batas], ["5 per 1 hour"])
        # Ember unduhan tetap per user untuk semua laporan (bukan per URL); simpan kata sandi tidak punya parameter
        # path, jadi URL-nya satu dan ember per user sudah terjadi dengan sendirinya.
        self.assertEqual([b.scope for b in pdf_batas], [laporan_route.SCOPE_BATAS_PDF])
        for b in (*pdf_batas, *simpan_batas):
            self.assertIs(b.key_func, kunci_per_user)
        for nama in ("daftar_laporan", "detail_laporan", "ambil_pengaturan_laporan"):
            self.assertNotIn(f"{laporan_route.__name__}.{nama}", batas)


if __name__ == "__main__":
    unittest.main()
