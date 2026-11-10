"""Galat SQL di log tanpa nilai parameter kueri (`hide_parameters` di app/core/database.py).

Insiden 2026-10-17 (AGENTS.md): setiap kueri `User` 500 sampai migrasi dijalankan. Traceback galat seperti itu masuk
journal, dan tanpa `hide_parameters` pesannya memuat parameter kueri: alamat email yang dipakai login.
Run: python -m unittest app.tests.test_log_parameter_sql -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest

ALAMAT = "rahasia.alamat@example.com"


class ParameterSqlTests(unittest.TestCase):
    """Galat SQL yang tak tertangani masuk journal sebagai traceback. Tanpa `hide_parameters`, pesannya memuat nilai
    parameter kueri (alamat email saat login, keterangan transaksi)."""

    def test_keputusan_per_lingkungan(self):
        from app.core.database import sembunyikan_parameter
        self.assertTrue(sembunyikan_parameter("production"))
        self.assertTrue(sembunyikan_parameter("staging"))
        self.assertTrue(sembunyikan_parameter(""))
        self.assertFalse(sembunyikan_parameter("development"))

    def test_engine_produksi_menyembunyikan_parameter(self):
        from app.core.database import engine, settings
        self.assertEqual(settings.APP_ENV, "production")   # bawaan kode; tes tidak mengisi APP_ENV
        self.assertTrue(engine.sync_engine.hide_parameters)

    def test_pesan_galat_sql_tanpa_nilai_parameter(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import DBAPIError
        from app.core.database import sembunyikan_parameter
        mesin = create_engine("sqlite://", hide_parameters=sembunyikan_parameter("production"))
        with mesin.connect() as conn, self.assertRaises(DBAPIError) as cm:
            conn.execute(text("SELECT * FROM tabel_tidak_ada WHERE email = :email"), {"email": ALAMAT})
        self.assertNotIn(ALAMAT, str(cm.exception))
        self.assertNotIn("@", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
