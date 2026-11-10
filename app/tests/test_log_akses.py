"""Access log uvicorn tanpa token dan alamat email (`app/core/log_akses.py`).

Tautan bertoken dibuka lewat API host (`/auth/verifikasi-email?token=`, `/laporan/berhenti-email?token=`,
`/auth/tg-login?token=`), dan uvicorn mencatat path beserta query ke journald. Filter di logger `uvicorn.access`
menyamarkan nilainya sebelum baris log dibentuk. Semua nilai di sini rekaan.
Run: python -m unittest app.tests.test_log_akses -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import logging
import unittest
from unittest.mock import patch

from app.core import log_akses
from app.core.log_akses import SamarkanQueryRahasia, samarkan_query

FORMAT_UVICORN = '%s - "%s %s HTTP/%s" %d'   # uvicorn/protocols/http/*_impl.py
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.tanda-tangan_rekaan"


class SamarkanQueryTests(unittest.TestCase):
    def test_token_disamarkan_path_utuh(self):
        self.assertEqual(samarkan_query(f"/auth/verifikasi-email?token={TOKEN}"),
                         "/auth/verifikasi-email?token=***")

    def test_parameter_lain_utuh_dan_urutan_tetap(self):
        self.assertEqual(samarkan_query(f"/laporan/berhenti-email?a=1&token={TOKEN}&b=dua%20kata"),
                         "/laporan/berhenti-email?a=1&token=***&b=dua%20kata")

    def test_tanpa_query_atau_tanpa_rahasia_tidak_berubah(self):
        for path in ("/health", "/transactions/?limit=20&offset=0", "/envelopes/summary?", "/a%20b?x=1&y", ""):
            with self.subTest(path=path):
                self.assertEqual(samarkan_query(path), path)

    def test_code_disamarkan(self):
        # Kode undangan household dan kode OAuth GitHub (CMS) juga lewat query.
        self.assertEqual(samarkan_query("/household/join?code=ABCD1234"), "/household/join?code=***")
        self.assertEqual(samarkan_query("/auth/cms-oauth/callback?code=gh-rekaan&state=x"),
                         "/auth/cms-oauth/callback?code=***&state=x")

    def test_nama_parameter_tak_peka_huruf_dan_ter_encode(self):
        self.assertEqual(samarkan_query("/x?Token=abc&TOKEN=def"), "/x?Token=***&TOKEN=***")
        self.assertEqual(samarkan_query("/x?%74oken=abc"), "/x?%74oken=***")

    def test_token_berulang_semuanya_disamarkan(self):
        self.assertEqual(samarkan_query("/x?token=satu&token=dua"), "/x?token=***&token=***")

    def test_nilai_kosong_tetap_kosong(self):
        self.assertEqual(samarkan_query("/auth/verifikasi-email?token="), "/auth/verifikasi-email?token=")

    def test_nilai_berisi_alamat_email_disamarkan(self):
        # Mis. admin mencari user dengan alamatnya: GET /admin/users?search=…
        self.assertEqual(samarkan_query("/admin/users?search=ani%40example.com&limit=5"),
                         "/admin/users?search=***&limit=5")
        self.assertEqual(samarkan_query("/admin/users?search=ani@example.com"), "/admin/users?search=***")
        self.assertEqual(samarkan_query("/admin/users?search=ani&plan=pro"), "/admin/users?search=ani&plan=pro")

    def test_tanda_tanya_kedua_tetap_bagian_query(self):
        self.assertEqual(samarkan_query("/x?a=1?token=abc&token=def"), "/x?a=1?token=abc&token=***")


class FilterTests(unittest.TestCase):
    def rekam(self, *args) -> logging.LogRecord:
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, FORMAT_UVICORN, args, None)

    def test_baris_uvicorn_tersamar(self):
        rekaman = self.rekam("127.0.0.1:5000", "GET", f"/auth/verifikasi-email?token={TOKEN}", "1.1", 200)
        self.assertIs(SamarkanQueryRahasia().filter(rekaman), True)
        self.assertEqual(rekaman.getMessage(), '127.0.0.1:5000 - "GET /auth/verifikasi-email?token=*** HTTP/1.1" 200')
        self.assertEqual(len(rekaman.args), 5)   # AccessFormatter uvicorn membongkar tepat lima argumen

    def test_baris_tanpa_rahasia_tidak_disentuh(self):
        args = ("127.0.0.1:5000", "GET", "/transactions/?limit=20", "1.1", 200)
        rekaman = self.rekam(*args)
        self.assertIs(SamarkanQueryRahasia().filter(rekaman), True)
        self.assertEqual(rekaman.args, args)

    def test_bentuk_args_lain_tidak_membuat_galat(self):
        saring = SamarkanQueryRahasia()
        for args in (None, (), ("satu",), ("a", "b", 3, "1.1", 200), ({"kunci": "nilai"},)):
            with self.subTest(args=args):
                rekaman = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "pesan", args, None)
                self.assertIs(saring.filter(rekaman), True)

    def test_galat_penyamaran_membuang_seluruh_query(self):
        # Gagal-tertutup: bila penyamaran sendiri galat, query dibuang seluruhnya; baris log tetap terbit.
        rekaman = self.rekam("127.0.0.1:5000", "GET", f"/laporan/berhenti-email?token={TOKEN}", "1.1", 200)
        with patch.object(log_akses, "samarkan_query", side_effect=RuntimeError("rekaan")):
            self.assertIs(SamarkanQueryRahasia().filter(rekaman), True)
        self.assertEqual(rekaman.getMessage(), '127.0.0.1:5000 - "GET /laporan/berhenti-email?*** HTTP/1.1" 200')


class PemasanganTests(unittest.TestCase):
    """Keadaan logger dikembalikan sesudah tiap tes, jadi `terpasang` hanya lolos bila impor `app.main` sendiri yang
    memasang filter (bukan sisa `pasang()` dari tes lain)."""

    def setUp(self):
        import app.main   # noqa: F401
        logger = logging.getLogger("uvicorn.access")
        semula = logger.filters[:]
        self.addCleanup(setattr, logger, "filters", semula)

    def terpasang(self) -> list:
        return [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, SamarkanQueryRahasia)]

    def test_terpasang_setelah_app_main_diimpor(self):
        self.assertEqual(len(self.terpasang()), 1)

    def test_pasang_ulang_tidak_menggandakan(self):
        log_akses.pasang()
        log_akses.pasang()
        self.assertEqual(len(self.terpasang()), 1)

    def test_baris_access_log_tersamar_lewat_logger_uvicorn(self):
        logger = logging.getLogger("uvicorn.access")
        with self.assertLogs("uvicorn.access", level="INFO") as cm:
            for metode, path in (("GET", f"/auth/verifikasi-email?token={TOKEN}"),
                                 ("POST", f"/auth/verifikasi-email?token={TOKEN}"),
                                 ("GET", f"/laporan/berhenti-email?token={TOKEN}"),
                                 ("POST", f"/laporan/berhenti-email?token={TOKEN}"),
                                 ("GET", f"/auth/tg-login?token={TOKEN}")):
                logger.info(FORMAT_UVICORN, "127.0.0.1:5000", metode, path, "1.1", 200)
        keluaran = "\n".join(cm.output)
        self.assertEqual(len(cm.output), 5)
        self.assertNotIn(TOKEN, keluaran)
        self.assertNotIn("eyJ", keluaran)
        self.assertEqual(keluaran.count("token=***"), 5)
        self.assertIn('"POST /laporan/berhenti-email?token=*** HTTP/1.1" 200', keluaran)


if __name__ == "__main__":
    unittest.main()
