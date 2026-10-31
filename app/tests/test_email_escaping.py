"""Teks dari user di email HTML harus di-escape (app/services/email_service.py dan pemanggilnya).

Nama amplop bersama dan deskripsi langganan bisa ditulis anggota household lain, dan nama user
masuk ke email admin. Tanpa escape, isi itu bisa menyisipkan tautan/tombol palsu ke email resmi
Jatahku (phishing). Body yang memang HTML dari admin (broadcast) tidak termasuk."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.models import NotificationType
from app.services import email_service

EVIL = '<a href="https://phish.test">Klik</a>'
EVIL_ESC = "&lt;a href=&quot;https://phish.test&quot;&gt;Klik&lt;/a&gt;"
# Template sendiri berisi <a href="https://jatahku.com">, jadi yang dicek adalah tautan sisipan.


def _captured(send_mock) -> str:
    _to, _subject, html = send_mock.call_args.args[:3]
    return html


class EmailTemplateTests(unittest.TestCase):
    def test_title_and_cta_text_are_text(self):
        html = email_service.email_template(f"Halo {EVIL}", "<p>isi</p>", f"Buka {EVIL}", "https://jatahku.com")
        self.assertNotIn("phish.test\">", html)
        self.assertIn(f"Halo {EVIL_ESC}", html)
        self.assertIn(f"Buka {EVIL_ESC}", html)
        self.assertIn("<p>isi</p>", html)  # body tetap HTML

    def test_cta_url_cannot_break_out_of_attribute(self):
        html = email_service.email_template("Judul", "<p>x</p>", "Buka", 'https://jatahku.com/"><script>x</script>')
        self.assertNotIn("<script>", html)
        self.assertIn('href="https://jatahku.com/&quot;&gt;&lt;script&gt;x&lt;/script&gt;"', html)


class EmailBuilderTests(unittest.TestCase):
    @patch.object(email_service, "send_email", return_value=True)
    def test_budget_warning_escapes_envelope_and_name(self, send):
        email_service.send_budget_warning_email("a@b.test", EVIL, EVIL, "<b>", 95, "Rp1.000")
        html = _captured(send)
        self.assertNotIn('<a href="https://phish.test', html)
        self.assertNotIn("<b>", html)
        self.assertIn(EVIL_ESC, html)

    @patch.object(email_service, "send_email", return_value=True)
    def test_subscription_due_escapes_desc_and_envelope(self, send):
        email_service.send_subscription_due_email("a@b.test", "Budi", EVIL, "Rp50.000", EVIL)
        html = _captured(send)
        self.assertNotIn('<a href="https://phish.test', html)
        self.assertEqual(html.count(EVIL_ESC), 3)  # judul, langganan, amplop

    @patch.object(email_service, "send_email", return_value=True)
    def test_name_is_escaped_in_account_emails(self, send):
        for fn in (
            lambda: email_service.send_welcome_email("a@b.test", EVIL),
            lambda: email_service.send_tg_reminder_email("a@b.test", EVIL),
            lambda: email_service.send_password_reset_email("a@b.test", EVIL, "https://jatahku.com/r"),
            lambda: email_service.send_password_changed_email("a@b.test", EVIL),
            lambda: email_service.send_account_deletion_email("a@b.test", EVIL, "https://jatahku.com/h"),
            lambda: email_service.send_account_deleted_email("a@b.test", EVIL),
        ):
            send.reset_mock()
            fn()
            html = _captured(send)
            self.assertNotIn("<a href=\"https://phish.test", html)
            self.assertIn(EVIL_ESC, html)

    def test_backup_email_escapes_name_and_filename(self):
        sent = {}

        def fake_deliver(to_email, msg):
            sent["raw"] = msg.as_string()

        with patch.object(email_service, "_deliver", side_effect=fake_deliver), \
                patch.object(email_service, "get_settings",
                             return_value=SimpleNamespace(SMTP_FROM="n@j.test", SMTP_FROM_NAME="Jatahku")):
            email_service.send_data_backup_email("a@b.test", EVIL, {}, "<i>x</i>.json")
        import email
        msg = email.message_from_string(sent["raw"])
        html = next(part.get_payload(decode=True).decode() for part in msg.walk()
                    if part.get_content_type() == "text/html")
        self.assertNotIn("<a href=\"https://phish.test", html)
        self.assertNotIn("<i>x</i>", html)
        self.assertIn(EVIL_ESC, html)


class NotificationEmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_due_notification_email_escapes_message(self):
        from app.services.notification_service import send_notification
        user = SimpleNamespace(id=uuid4(), email="a@b.test", telegram_id=None)
        prefs = SimpleNamespace(subscription_due_tg=False, subscription_due_web=False)
        prefs_res, user_res = MagicMock(), MagicMock()
        prefs_res.scalar_one_or_none = MagicMock(return_value=prefs)
        user_res.scalar_one_or_none = MagicMock(return_value=user)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[prefs_res, user_res])
        with patch.object(email_service, "send_email", return_value=True) as send:
            await send_notification(user.id, NotificationType.subscription_due,
                                    title=f"Jatuh tempo: {EVIL}", message=f"Rp50.000 — Amplop: {EVIL}", db=db)
        html = _captured(send)
        self.assertNotIn('<a href="https://phish.test', html)
        self.assertEqual(html.count(EVIL_ESC), 2)


def _one_row_db(*rows):
    """db.execute() mengembalikan baris-baris ini berurutan (scalar_one_or_none)."""
    results = []
    for row in rows:
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=row)
        results.append(r)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=results)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


class AdminEmailRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_email_escapes_user_name_but_keeps_admin_html_body(self):
        from app.api.routes.admin import DirectEmailRequest, send_email_to_user
        target = SimpleNamespace(id=uuid4(), name=EVIL, email="t@b.test", telegram_id=None)
        req = DirectEmailRequest(user_id=target.id, subject="Info", body="<p><b>Isi dari admin</b></p>")
        with patch.object(email_service, "send_email", return_value=True) as send:
            out = await send_email_to_user(req, admin=SimpleNamespace(id=uuid4()), db=_one_row_db(target))
        self.assertEqual(out["results"]["email"], "sent")
        html = _captured(send)
        self.assertNotIn('<a href="https://phish.test', html)
        self.assertIn(f"Hai {EVIL_ESC},", html)
        self.assertIn("<p><b>Isi dari admin</b></p>", html)

    async def test_approve_payment_escapes_user_name(self):
        from app.api.routes.admin import approve_payment
        order = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="waiting_confirmation")
        u = SimpleNamespace(id=order.user_id, name=EVIL, email="t@b.test", plan="basic")
        with patch.object(email_service, "send_email", return_value=True) as send:
            await approve_payment(order.id, admin=SimpleNamespace(id=uuid4()), db=_one_row_db(order, u))
        html = _captured(send)
        self.assertNotIn('<a href="https://phish.test', html)
        self.assertIn(f"Hai {EVIL_ESC},", html)


class PaymentProofEmailTests(unittest.TestCase):
    def test_upload_proof_source_escapes_user_name_and_email(self):
        # upload_proof menulis berkas ke disk, jadi dicek di sumbernya: interpolasi nama/email
        # ke HTML email admin harus lewat h(). Baris persis ini yang dipakai di payment.py.
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "api/routes/payment.py").read_text()
        self.assertIn('f"<p><strong>{h(user.name)}</strong> ({h(user.email)}) baru saja upload bukti transfer.</p>"', src)
        self.assertNotIn("{user.name}</strong>", src)


if __name__ == "__main__":
    unittest.main()
