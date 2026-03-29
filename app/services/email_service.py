import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

logger = logging.getLogger("jatahku.email")

SMTP_HOST = "localhost"
SMTP_PORT = 587
SMTP_USER = "noreply@jatahku.com"
SMTP_PASS = "Jatahku2026!"
SMTP_FROM = "noreply@jatahku.com"
SMTP_FROM_NAME = "Jatahku"


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    """Send email via authenticated SMTP (exim4)."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jatahku.com")
        msg["List-Unsubscribe"] = "<mailto:noreply@jatahku.com?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        # Always attach plain text (improves deliverability)
        plain = text_body or "Buka email ini dengan client yang mendukung HTML untuk melihat konten."
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed to {to_email}: {e}")
        return False


def email_template(title: str, body_html: str, cta_text: str = None, cta_url: str = None):
    """Generate branded HTML email."""
    cta_block = ""
    if cta_text and cta_url:
        cta_block = f'''
        <tr><td style="padding:24px 0 0">
          <a href="{cta_url}" style="display:inline-block;background:#0F6E56;color:#fff;padding:12px 32px;border-radius:12px;text-decoration:none;font-weight:600;font-size:14px">{cta_text}</a>
        </td></tr>'''

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;padding:0;background:#FAFAF6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}</style>
</head><body>
<table width="100%" cellpadding="0" cellspacing="0" style="background:#FAFAF6;padding:32px 16px">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;border:1px solid #E8E8E4;overflow:hidden">
  <tr><td style="background:#0F6E56;padding:24px 32px">
    <span style="color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.5px">Jatah<span style="color:#9FE1CB">ku</span></span>
  </td></tr>
  <tr><td style="padding:32px">
    <h2 style="margin:0 0 16px;font-size:20px;color:#2C2C2A;font-weight:600">{title}</h2>
    <div style="color:#5F5E5A;font-size:14px;line-height:1.7">{body_html}</div>
    {cta_block}
  </td></tr>
  <tr><td style="padding:24px 32px;border-top:1px solid #E8E8E4;text-align:center">
    <p style="margin:0;font-size:12px;color:#888780">Setiap rupiah ada jatahnya.</p>
    <p style="margin:4px 0 0;font-size:11px;color:#B4B2A9">
      <a href="https://jatahku.com" style="color:#0F6E56;text-decoration:none">jatahku.com</a> · 
      <a href="https://t.me/JatahkuBot" style="color:#0F6E56;text-decoration:none">@JatahkuBot</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>'''


def send_welcome_email(to_email: str, name: str):
    html = email_template(
        f"Selamat datang, {name}! 🎉",
        f'''<p>Hai {name},</p>
        <p>Akun Jatahku kamu sudah aktif. Sekarang kamu bisa mulai mengatur keuangan dengan metode envelope budgeting.</p>
        <p><strong>3 langkah untuk mulai:</strong></p>
        <p>1️⃣ Setup budget di <a href="https://jatahku.com" style="color:#0F6E56">jatahku.com</a><br>
        2️⃣ Hubungkan Telegram di Settings<br>
        3️⃣ Kirim "kopi 35k" di Telegram — selesai!</p>
        <p>Tips: Hubungkan Telegram supaya bisa catat pengeluaran secepat kirim chat. ⚡</p>''',
        "Buka Jatahku",
        "https://jatahku.com"
    )
    return send_email(to_email, "Selamat datang di Jatahku! 🎉", html)


def send_tg_reminder_email(to_email: str, name: str):
    html = email_template(
        f"{name}, hubungkan Telegram kamu! 📱",
        f'''<p>Hai {name},</p>
        <p>Kamu belum menghubungkan akun Telegram. Dengan Telegram, kamu bisa:</p>
        <p>⚡ Catat pengeluaran dalam 3 detik<br>
        🔔 Dapat notifikasi budget otomatis<br>
        📊 Terima ringkasan harian &amp; mingguan<br>
        🔄 Sync real-time dengan WebApp</p>
        <p>Caranya mudah: buka Settings di jatahku.com, klik "Generate Link Telegram", dan ikuti instruksinya.</p>''',
        "Hubungkan Telegram Sekarang",
        "https://jatahku.com/settings"
    )
    return send_email(to_email, f"{name}, hubungkan Telegram! 📱", html)


def send_budget_warning_email(to_email: str, name: str, envelope_name: str, emoji: str, spent_pct: int, remaining: str):
    severity = "hampir habis! 🔴" if spent_pct >= 90 else "mulai menipis 🟡"
    html = email_template(
        f"{emoji} {envelope_name} {severity}",
        f'''<p>Hai {name},</p>
        <p>Amplop <strong>{emoji} {envelope_name}</strong> sudah terpakai <strong>{spent_pct}%</strong>.</p>
        <p>Sisa: <strong>{remaining}</strong></p>
        <p>Cek budget kamu di dashboard untuk detail lengkap.</p>''',
        "Cek Dashboard",
        "https://jatahku.com"
    )
    return send_email(to_email, f"{emoji} {envelope_name} {severity}", html)


def send_subscription_due_email(to_email: str, name: str, desc: str, amount: str, envelope_name: str):
    html = email_template(
        f"🔔 Jatuh tempo: {desc}",
        f'''<p>Hai {name},</p>
        <p>Langganan <strong>{desc}</strong> jatuh tempo hari ini.</p>
        <p>Jumlah: <strong>{amount}</strong><br>
        Amplop: {envelope_name}</p>
        <p>Buka Telegram dan konfirmasi pembayaran, atau cek di halaman Langganan.</p>''',
        "Cek Langganan",
        "https://jatahku.com/langganan"
    )
    return send_email(to_email, f"🔔 Jatuh tempo: {desc} — {amount}", html)
