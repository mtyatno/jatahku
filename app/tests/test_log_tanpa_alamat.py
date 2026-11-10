"""Log aplikasi tanpa alamat email (dan tanpa subjek atau tautan bertoken).

Semua pengirim di `email_service` dan jalur email di `notification_service` hanya mencatat teks tetap, id, dan nama jenis
galat. Pesan galat SMTP bisa memuat alamat penerima (`550 <alamat> ditolak`), jadi pesan galat tidak pernah dicatat.
Pola yang sama dengan `LogTanpaAlamatTests` di test_verifikasi_email_api.py. Semua alamat dan token di sini rekaan.
Run: python -m unittest app.tests.test_log_tanpa_alamat -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.models import NotificationType
from app.services import email_service, notification_service

ALAMAT = "rahasia.alamat@example.com"
NAMA = "Nama Rahasia"
SUBJEK = "Subjek Rahasia Rp54.000"
TOKEN = "token-rekaan-tidak-boleh-tercatat"
TAUTAN = f"https://jatahku.example/reset-password?token={TOKEN}"

# (nama, pemanggil) untuk setiap pengirim yang lewat `send_email` atau punya log sendiri.
PENGIRIM = (
    ("send_email", lambda: email_service.send_email(ALAMAT, SUBJEK, "<p>h</p>", "t")),
    ("welcome", lambda: email_service.send_welcome_email(ALAMAT, NAMA)),
    ("tg_reminder", lambda: email_service.send_tg_reminder_email(ALAMAT, NAMA)),
    ("budget_warning", lambda: email_service.send_budget_warning_email(ALAMAT, NAMA, "Makan", "🍚", 95, "Rp10.000")),
    ("subscription_due", lambda: email_service.send_subscription_due_email(ALAMAT, NAMA, "Netflix", "Rp54.000", "Hiburan")),
    ("password_reset", lambda: email_service.send_password_reset_email(ALAMAT, NAMA, TAUTAN)),
    ("password_changed", lambda: email_service.send_password_changed_email(ALAMAT, NAMA)),
    ("account_deletion", lambda: email_service.send_account_deletion_email(ALAMAT, NAMA, TAUTAN)),
    ("account_deleted", lambda: email_service.send_account_deleted_email(ALAMAT, NAMA)),
    ("data_backup", lambda: email_service.send_data_backup_email(ALAMAT, NAMA, {"x": 1}, "jatahku-backup.json")),
    ("verifikasi", lambda: email_service.send_verifikasi_email(ALAMAT, SUBJEK, "<p>h</p>", "t")),
    ("laporan", lambda: email_service.send_laporan_email(ALAMAT, SUBJEK, "<p>h</p>", "t", TAUTAN)),
)


class LogEmailServiceTests(unittest.TestCase):
    def jalankan(self, kirim, deliver):
        with patch.object(email_service, "_deliver", deliver), \
                self.assertLogs("jatahku.email", level="DEBUG") as cm:
            hasil = kirim()
        return hasil, "\n".join(cm.output)

    def periksa_bersih(self, log: str):
        self.assertNotIn("@", log)
        for rahasia in (ALAMAT, "rahasia.alamat", NAMA, SUBJEK, "Rp54.000", "Netflix", TOKEN):
            self.assertNotIn(rahasia, log)

    def test_sukses_tanpa_alamat_di_log(self):
        for nama, kirim in PENGIRIM:
            with self.subTest(pengirim=nama):
                deliver = MagicMock()
                hasil, log = self.jalankan(kirim, deliver)
                self.assertTrue(hasil)
                self.assertEqual(deliver.call_args.args[0], ALAMAT)   # email tetap dikirim ke alamatnya
                self.periksa_bersih(log)

    def test_gagal_tanpa_alamat_di_log(self):
        # Pesan galat SMTP memuat alamat penerima: yang dicatat hanya nama jenis galatnya.
        for nama, kirim in PENGIRIM:
            with self.subTest(pengirim=nama):
                galat = RuntimeError(f"550 <{ALAMAT}> ditolak: {SUBJEK}")
                hasil, log = self.jalankan(kirim, MagicMock(side_effect=galat))
                self.assertFalse(hasil)
                self.periksa_bersih(log)
                self.assertIn("ERROR:jatahku.email:", log)
                self.assertIn("RuntimeError", log)

    def test_tanpa_smtp_password_tidak_mencatat_alamat(self):
        # Jalur `_deliver` asli tanpa SMTP_PASSWORD (gagal tertutup): tetap tanpa alamat.
        tanpa_sandi = SimpleNamespace(SMTP_PASSWORD="", SMTP_FROM="noreply@jatahku.example", SMTP_FROM_NAME="Jatahku")
        with patch.object(email_service, "get_settings", return_value=tanpa_sandi), \
                self.assertLogs("jatahku.email", level="DEBUG") as cm:
            self.assertFalse(email_service.send_email(ALAMAT, SUBJEK, "<p>h</p>"))
            self.assertFalse(email_service.send_data_backup_email(ALAMAT, NAMA, {}, "jatahku-backup.json"))
        self.periksa_bersih("\n".join(cm.output))


class LogNotifikasiEmailTests(unittest.IsolatedAsyncioTestCase):
    async def kirim(self, send_email):
        user = SimpleNamespace(id=uuid4(), email=ALAMAT, telegram_id=None)
        prefs = SimpleNamespace(subscription_due_tg=False, subscription_due_web=False)
        hasil_prefs, hasil_user = MagicMock(), MagicMock()
        hasil_prefs.scalar_one_or_none = MagicMock(return_value=prefs)
        hasil_user.scalar_one_or_none = MagicMock(return_value=user)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[hasil_prefs, hasil_user])
        with patch.object(email_service, "send_email", send_email):
            await notification_service.send_notification(
                user.id, NotificationType.subscription_due, title="Jatuh tempo", message="Rp54.000", db=db)
        return user

    async def test_email_notifikasi_gagal_mencatat_id_bukan_alamat(self):
        galat = RuntimeError(f"550 <{ALAMAT}> ditolak")
        with self.assertLogs("jatahku.notify", level="DEBUG") as cm:
            user = await self.kirim(MagicMock(side_effect=galat))
        log = "\n".join(cm.output)
        self.assertNotIn("@", log)
        self.assertNotIn("rahasia.alamat", log)
        self.assertIn(str(user.id), log)
        self.assertIn("RuntimeError", log)

    async def test_email_notifikasi_sukses_tetap_dikirim_ke_alamatnya(self):
        kirim = MagicMock(return_value=True)
        with self.assertNoLogs("jatahku.notify", level="DEBUG"):
            await self.kirim(kirim)
        self.assertEqual(kirim.call_args.args[0], ALAMAT)


if __name__ == "__main__":
    unittest.main()
