"""Kredensial SMTP datang dari Settings (.env), bukan dari kode (app/services/email_service.py).

Password SMTP pernah ditulis langsung di email_service.py di repo publik. Tes ini mengunci bahwa
setiap pengiriman membaca host/port/user/password/pengirim dari get_settings(), dan bahwa tanpa
SMTP_PASSWORD tidak ada koneksi SMTP sama sekali (gagal tertutup, dicatat di log)."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import email_service


def _settings(**overrides):
    base = dict(
        SMTP_HOST="mail.test", SMTP_PORT=2525, SMTP_USER="kirim@contoh.test",
        SMTP_PASSWORD="rahasia-dari-env", SMTP_FROM="kirim@contoh.test", SMTP_FROM_NAME="Jatahku",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _smtp_mock():
    server = MagicMock()
    smtp_cls = MagicMock()
    smtp_cls.return_value.__enter__.return_value = server
    return smtp_cls, server


class SmtpSettingsTests(unittest.TestCase):
    def test_send_email_uses_settings_credentials(self):
        smtp_cls, server = _smtp_mock()
        with patch.object(email_service, "get_settings", return_value=_settings()), \
                patch.object(email_service.smtplib, "SMTP", smtp_cls):
            ok = email_service.send_email("a@b.test", "Halo", "<p>x</p>")
        self.assertTrue(ok)
        smtp_cls.assert_called_once_with("mail.test", 2525)
        server.login.assert_called_once_with("kirim@contoh.test", "rahasia-dari-env")
        from_addr, to_addr, raw = server.sendmail.call_args.args
        self.assertEqual(from_addr, "kirim@contoh.test")
        self.assertEqual(to_addr, "a@b.test")
        self.assertIn("From: Jatahku <kirim@contoh.test>", raw)

    def test_backup_email_uses_settings_credentials(self):
        smtp_cls, server = _smtp_mock()
        with patch.object(email_service, "get_settings", return_value=_settings()), \
                patch.object(email_service.smtplib, "SMTP", smtp_cls):
            ok = email_service.send_data_backup_email("a@b.test", "Budi", {"x": 1}, "backup.json")
        self.assertTrue(ok)
        smtp_cls.assert_called_once_with("mail.test", 2525)
        server.login.assert_called_once_with("kirim@contoh.test", "rahasia-dari-env")

    def test_missing_password_never_connects(self):
        for send in (
            lambda: email_service.send_email("a@b.test", "Halo", "<p>x</p>"),
            lambda: email_service.send_data_backup_email("a@b.test", "Budi", {}, "backup.json"),
        ):
            smtp_cls, _server = _smtp_mock()
            with patch.object(email_service, "get_settings", return_value=_settings(SMTP_PASSWORD="")), \
                    patch.object(email_service.smtplib, "SMTP", smtp_cls), \
                    self.assertLogs("jatahku.email", level="ERROR") as logs:
                self.assertFalse(send())
            smtp_cls.assert_not_called()
            self.assertTrue(any("SMTP_PASSWORD" in line for line in logs.output))

    def test_module_holds_no_credentials(self):
        # Tidak ada konstanta kredensial tingkat modul yang bisa ter-commit lagi.
        for name in ("SMTP_PASS", "SMTP_PASSWORD", "SMTP_USER", "SMTP_HOST", "SMTP_PORT"):
            self.assertFalse(hasattr(email_service, name), name)


class StartupWarningTests(unittest.TestCase):
    def test_warns_at_startup_when_password_missing(self):
        with patch.object(email_service, "get_settings", return_value=_settings(SMTP_PASSWORD="")), \
                self.assertLogs("jatahku.email", level="WARNING") as logs:
            self.assertFalse(email_service.check_configured())
        self.assertTrue(any("SMTP_PASSWORD" in line for line in logs.output))

    def test_silent_when_configured(self):
        with patch.object(email_service, "get_settings", return_value=_settings()):
            with self.assertNoLogs("jatahku.email", level="WARNING"):
                self.assertTrue(email_service.check_configured())

    def test_lifespan_calls_check(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
        self.assertIn("email_service.check_configured()", src)


class SmtpSettingsDefaultsTests(unittest.TestCase):
    def test_password_has_no_default(self):
        from app.core.config import Settings
        fields = Settings.model_fields
        for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_FROM_NAME"):
            self.assertIn(name, fields)
        self.assertEqual(fields["SMTP_PASSWORD"].default, "")
        self.assertEqual(fields["SMTP_HOST"].default, "localhost")
        self.assertEqual(fields["SMTP_PORT"].default, 587)


if __name__ == "__main__":
    unittest.main()
