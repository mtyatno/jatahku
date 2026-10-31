import smtplib
import logging
import json as _json
from html import escape as _escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formatdate, make_msgid

from app.core.config import get_settings

logger = logging.getLogger("jatahku.email")



def h(value) -> str:
    """Teks dari user (nama, nama amplop, deskripsi) → aman di HTML email. Pakai untuk SETIAP
    interpolasi ke body_html; judul dan teks tombol sudah di-escape oleh email_template."""
    return _escape("" if value is None else str(value), quote=True)


def _from_header() -> str:
    s = get_settings()
    return f"{s.SMTP_FROM_NAME} <{s.SMTP_FROM}>"


def _deliver(to_email: str, msg) -> None:
    """Kirim lewat SMTP terautentikasi. Kredensial dari .env (SMTP_*, app/core/config.py);
    tanpa SMTP_PASSWORD tidak pernah menyambung ke server."""
    s = get_settings()
    if not s.SMTP_PASSWORD:
        raise RuntimeError("SMTP_PASSWORD kosong di .env, email tidak dikirim")
    with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(s.SMTP_USER, s.SMTP_PASSWORD)
        server.sendmail(s.SMTP_FROM, to_email, msg.as_string())


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    """Send email via authenticated SMTP (exim4)."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = _from_header()
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jatahku.com")
        msg["List-Unsubscribe"] = f"<mailto:{get_settings().SMTP_FROM}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        # Always attach plain text (improves deliverability)
        plain = text_body or "Buka email ini dengan client yang mendukung HTML untuk melihat konten."
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        _deliver(to_email, msg)

        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed to {to_email}: {e}")
        return False


def email_template(title: str, body_html: str, cta_text: str = None, cta_url: str = None):
    """Generate branded HTML email. `title`, `cta_text`, `cta_url` = teks biasa (di-escape di sini);
    `body_html` = HTML, jadi pemanggil wajib meng-escape isinya dengan h()."""
    cta_block = ""
    if cta_text and cta_url:
        cta_block = f'''
        <tr><td style="padding:24px 0 0">
          <a href="{h(cta_url)}" style="display:inline-block;background:#0F6E56;color:#fff;padding:12px 32px;border-radius:12px;text-decoration:none;font-weight:600;font-size:14px">{h(cta_text)}</a>
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
    <h2 style="margin:0 0 16px;font-size:20px;color:#2C2C2A;font-weight:600">{h(title)}</h2>
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
        f'''<p>Hai {h(name)},</p>
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
        f'''<p>Hai {h(name)},</p>
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
        f'''<p>Hai {h(name)},</p>
        <p>Amplop <strong>{h(emoji)} {h(envelope_name)}</strong> sudah terpakai <strong>{spent_pct}%</strong>.</p>
        <p>Sisa: <strong>{h(remaining)}</strong></p>
        <p>Cek budget kamu di dashboard untuk detail lengkap.</p>''',
        "Cek Dashboard",
        "https://jatahku.com"
    )
    return send_email(to_email, f"{emoji} {envelope_name} {severity}", html)


def send_subscription_due_email(to_email: str, name: str, desc: str, amount: str, envelope_name: str):
    html = email_template(
        f"🔔 Jatuh tempo: {desc}",
        f'''<p>Hai {h(name)},</p>
        <p>Langganan <strong>{h(desc)}</strong> jatuh tempo hari ini.</p>
        <p>Jumlah: <strong>{h(amount)}</strong><br>
        Amplop: {h(envelope_name)}</p>
        <p>Buka Telegram dan konfirmasi pembayaran, atau cek di halaman Langganan.</p>''',
        "Cek Langganan",
        "https://jatahku.com/langganan"
    )
    return send_email(to_email, f"🔔 Jatuh tempo: {desc} — {amount}", html)


def send_data_backup_email(to_email: str, name: str, data: dict, filename: str) -> bool:
    """Send backup JSON as attachment before a data reset."""
    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = _from_header()
        msg["To"] = to_email
        msg["Subject"] = "Backup data Jatahku kamu sebelum reset"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jatahku.com")

        html_body = email_template(
            "Backup data kamu tersedia",
            f"""<p>Hai {h(name)},</p>
            <p>Data Jatahku kamu terlampir sebagai file <strong>{h(filename)}</strong>.</p>
            <p>Ini adalah salinan lengkap semua data kamu sebelum reset dilakukan.
            Simpan sebagai referensi jika sewaktu-waktu diperlukan.</p>""",
        )
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(f"Backup data Jatahku kamu terlampir: {filename}", "plain"))
        body_part.attach(MIMEText(html_body, "html"))
        msg.attach(body_part)

        json_bytes = _json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        attachment = MIMEApplication(json_bytes, _subtype="json")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

        _deliver(to_email, msg)

        logger.info(f"Backup email sent to {to_email}: {filename}")
        return True
    except Exception as e:
        logger.error(f"Backup email failed to {to_email}: {e}")
        return False


def send_password_reset_email(to_email: str, name: str, reset_url: str) -> bool:
    html = email_template(
        "Reset password kamu 🔑",
        f'''<p>Hai {h(name)},</p>
        <p>Kami menerima permintaan reset password untuk akun Jatahku kamu.
        Klik tombol di bawah untuk membuat password baru.</p>
        <p>Link ini berlaku <strong>30 menit</strong> dan hanya bisa dipakai sekali.</p>
        <p>Kalau kamu tidak merasa meminta reset, abaikan email ini —
        password kamu tetap aman.</p>''',
        "Reset Password",
        reset_url,
    )
    return send_email(to_email, "Reset password Jatahku kamu", html)


def send_password_changed_email(to_email: str, name: str) -> bool:
    html = email_template(
        "Password kamu baru saja diubah 🔒",
        f'''<p>Hai {h(name)},</p>
        <p>Password akun Jatahku kamu baru saja diubah.</p>
        <p>Kalau ini kamu, tidak perlu melakukan apa-apa.</p>
        <p>Kalau ini <strong>bukan</strong> kamu, segera amankan akun:
        buka halaman login lalu klik "Lupa password?" untuk membuat password baru.</p>''',
        "Buka Jatahku",
        "https://jatahku.com",
    )
    return send_email(to_email, "Password kamu baru saja diubah", html)


def send_account_deletion_email(to_email: str, name: str, confirm_url: str) -> bool:
    html = email_template(
        "Konfirmasi hapus akun Jatahku",
        f'''<p>Hai {h(name)},</p>
        <p>Kami menerima permintaan untuk <strong>menghapus permanen</strong> akun Jatahku kamu
        beserta semua datanya (amplop, transaksi, pemasukan, langganan).</p>
        <p>Klik tombol di bawah untuk melanjutkan. Link ini berlaku <strong>1 jam</strong>
        dan hanya bisa dipakai sekali. Penghapusan tidak bisa dibatalkan.</p>
        <p>Kalau kamu tidak merasa meminta ini, abaikan email ini — akun kamu tetap aman.</p>''',
        "Lanjutkan hapus akun",
        confirm_url,
    )
    return send_email(to_email, "Konfirmasi hapus akun Jatahku", html)


def send_account_deleted_email(to_email: str, name: str) -> bool:
    html = email_template(
        "Akun Jatahku kamu sudah dihapus",
        f'''<p>Hai {h(name)},</p>
        <p>Akun Jatahku kamu dan semua datanya sudah dihapus permanen, dan semua perangkat
        sudah keluar. Catatan kamu di amplop bersama household tetap ada tanpa nama
        ("Mantan anggota") supaya saldo anggota lain tidak berubah.</p>
        <p>Terima kasih sudah memakai Jatahku.</p>''',
    )
    return send_email(to_email, "Akun Jatahku kamu sudah dihapus", html)
