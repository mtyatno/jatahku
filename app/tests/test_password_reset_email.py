"""Tests for password reset email builders (app/services/email_service.py).

Run from repo root:  python -m unittest app.tests.test_password_reset_email -v
"""
import unittest
from unittest.mock import patch

from app.services import email_service


class TestSendPasswordResetEmail(unittest.TestCase):
    @patch.object(email_service, "send_email", return_value=True)
    def test_html_contains_reset_url_and_expiry_note(self, mock_send):
        url = "https://jatahku.com/reset-password?token=abc123"
        result = email_service.send_password_reset_email("a@b.com", "Budi", url)
        self.assertTrue(result)
        to_email, subject, html = mock_send.call_args.args[:3]
        self.assertEqual(to_email, "a@b.com")
        self.assertIn("Reset password", subject)
        self.assertIn(url, html)
        self.assertIn("30 menit", html)
        self.assertIn("Budi", html)


class TestSendPasswordChangedEmail(unittest.TestCase):
    @patch.object(email_service, "send_email", return_value=True)
    def test_html_mentions_change_and_recovery_hint(self, mock_send):
        result = email_service.send_password_changed_email("a@b.com", "Budi")
        self.assertTrue(result)
        to_email, subject, html = mock_send.call_args.args[:3]
        self.assertEqual(to_email, "a@b.com")
        self.assertIn("diubah", subject)
        self.assertIn("Lupa password", html)
        self.assertIn("Budi", html)


if __name__ == "__main__":
    unittest.main()
