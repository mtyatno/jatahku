"""Isi email laporan, halaman berhenti, dan kiriman MIME (tahap 2, Task 2).
Run: python -m unittest app.tests.test_laporan_surel -v
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import email
import unittest
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core import security
from app.core.config import get_settings
from app.services import email_service
from app.services.laporan import hitung, pdf, surel
from app.tests.test_laporan_susun import bahan, semua_uang
from app.services.laporan.susun import susun_bulanan

TL, TB = "https://jatahku.com/laporan/abc", "https://api.jatahku.com/laporan/berhenti-email?token=t"


def data_dasar():
    return susun_bulanan(bahan())


def isi(data=None, nama="Ani", lampiran=surel.LAMPIRAN_TERLAMPIR):
    return surel.isi_email_laporan(data or data_dasar(), nama, TL, TB, lampiran)


class IsiLaporan(unittest.TestCase):
    def test_subjek_dan_body_tanpa_nominal(self):
        data = data_dasar()
        subjek, html, teks = isi(data)
        self.assertEqual(subjek, "Laporan Oktober 2026 · Jatahku")
        self.assertIn("Laporan Oktober 2026 sudah terbit.", teks)
        self.assertIn("Hai Ani,", teks)
        semua = subjek + html + teks
        self.assertNotIn("Rp", semua)
        uangs = {u for u in semua_uang(data) if abs(Decimal(u)) >= 1000}  # nol dan receh tak bisa dibedakan dari angka lain
        self.assertTrue(uangs)
        for u in uangs:
            for bentuk in (u, hitung.uang(Decimal(u)), pdf.rupiah(u), pdf.rupiah(u)[2:]):
                self.assertNotIn(bentuk, semua)

    def test_baris_ringkasan(self):
        _, html, teks = isi()
        self.assertIn("Anggaran terpakai: 65%", teks)
        self.assertIn("Amplop aman: 1 · Lewat batas: 0", teks)
        self.assertIn("Pengeluaran turun 16% dibanding periode lalu", teks)
        self.assertIn("2 amplop tidak pernah lewat batas", teks)
        self.assertIn("Anggaran terpakai: 65%", html)
        self.assertIn(TL, teks)
        self.assertIn("Lihat laporan", html)
        self.assertIn(TB, html)
        self.assertIn("Berhenti berlangganan", html)
        self.assertIn("Tidak ingin menerima laporan lewat email?", html)

    def test_persen_dan_tren_null_dan_variasi(self):
        d = data_dasar()
        d["email"]["persen_terpakai"] = None
        d["email"]["tren_persen"] = None
        _, html, teks = isi(d)
        self.assertIn("Anggaran terpakai: —", teks)
        self.assertNotIn("Pengeluaran", teks)
        self.assertNotIn("Pengeluaran", html)
        for nilai, harap in ((-12, "Pengeluaran turun 12% dibanding periode lalu"),
                             (5, "Pengeluaran naik 5% dibanding periode lalu"),
                             (0, "Pengeluaran sama dengan periode lalu")):
            d["email"]["tren_persen"] = nilai
            self.assertIn(harap, isi(d)[2])

    def test_baris_lampiran_per_kode(self):
        for kode, baris in (
            (surel.LAMPIRAN_TERLAMPIR, "PDF laporan terlampir. Buka dengan kata sandi laporanmu."),
            (surel.LAMPIRAN_BELUM_DIATUR,
             "Atur kata sandi laporan di Pengaturan → Laporan untuk menerima PDF di email berikutnya."),
            (surel.LAMPIRAN_TIDAK_TERSEDIA, "PDF laporan bisa diunduh di aplikasi."),
        ):
            _, html, teks = isi(lampiran=kode)
            self.assertIn(baris, teks)
            self.assertIn(baris, html)
            for lain in ("PDF laporan terlampir.", "Atur kata sandi laporan", "PDF laporan bisa diunduh"):
                if not baris.startswith(lain):
                    self.assertNotIn(lain, teks)

    def test_nama_di_escape(self):
        _, html, teks = isi(nama="<b>x</b>")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
        self.assertNotIn("<b>x</b>", html)

    def test_judul_di_escape(self):
        d = data_dasar()
        d["judul"] = "<i>J</i>"
        _, html, _ = isi(d)
        self.assertNotIn("<i>J</i>", html)

    def test_verifikasi(self):
        subjek, html, teks = surel.isi_email_verifikasi("<b>Ani</b>", "a@b.id", "https://x/v?t=1")
        self.assertEqual(subjek, "Verifikasi email Jatahku kamu")
        self.assertIn("Klik tombol di bawah untuk memverifikasi a@b.id sebagai alamat penerima laporan Jatahku. "
                      "Tautan berlaku 24 jam.", teks)
        self.assertIn("Kalau kamu tidak meminta ini, abaikan email ini.", teks)
        self.assertIn("https://x/v?t=1", teks)
        self.assertIn("Verifikasi email", html)
        self.assertIn("&lt;b&gt;Ani&lt;/b&gt;", html)
        self.assertNotIn("<b>Ani</b>", html)


class TautanBerhenti(unittest.TestCase):
    def test_bolak_balik(self):
        uid = uuid.uuid4()
        url = surel.tautan_berhenti(uid)
        awal = f"{get_settings().API_URL}/laporan/berhenti-email?token="
        self.assertTrue(url.startswith(awal))
        self.assertEqual(surel.baca_token_berhenti(url[len(awal):]), uid)

    def test_token_lain_ditolak(self):
        uid = str(uuid.uuid4())
        tok = security.create_purpose_token(uid, "verifikasi_email", berlaku=timedelta(hours=1), email="a@b.id")
        self.assertIsNone(surel.baca_token_berhenti(tok))
        self.assertIsNone(surel.baca_token_berhenti("sampah"))
        self.assertIsNone(surel.baca_token_berhenti(
            security.create_purpose_token("bukan-uuid", surel.TUJUAN_BERHENTI, berlaku=None)))

    def test_halaman_tanpa_skrip_dan_token_di_escape(self):
        token = '"><script>alert(1)</script>'
        konf = surel.halaman_konfirmasi_berhenti(token)
        for hal in (konf, surel.halaman_berhenti_selesai(), surel.halaman_tautan_tak_berlaku()):
            self.assertIn("<!DOCTYPE html>", hal)
            self.assertNotIn("<script", hal.lower())
        self.assertNotIn(token, konf)
        self.assertIn("%22%3E%3Cscript%3Ealert%281%29%3C%2Fscript%3E", konf)
        self.assertIn("Berhenti menerima email laporan?", konf)
        self.assertIn("Email laporan Jatahku untuk akun ini akan dimatikan. Laporan tetap terbit di aplikasi.", konf)
        self.assertIn('method="post"', konf.lower())
        self.assertIn("Email laporan dimatikan", surel.halaman_berhenti_selesai())
        self.assertIn("Laporan tetap terbit di aplikasi. Kamu bisa menyalakannya lagi di Pengaturan → Laporan.",
                      surel.halaman_berhenti_selesai())
        self.assertIn("Tautan tidak berlaku", surel.halaman_tautan_tak_berlaku())
        self.assertIn("Buka Pengaturan → Laporan di aplikasi Jatahku untuk mengatur email laporan.",
                      surel.halaman_tautan_tak_berlaku())


class KirimLaporan(unittest.TestCase):
    URL = "https://api.jatahku.com/laporan/berhenti-email?token=t"

    def kirim(self, **kw):
        tangkap = []
        with patch.object(email_service, "_deliver", lambda to, msg: tangkap.append((to, msg))):
            hasil = email_service.send_laporan_email("a@b.id", "Subjek", "<p>h</p>", "teks", self.URL, **kw)
        return hasil, tangkap

    def test_mime_dengan_lampiran(self):
        hasil, t = self.kirim(pdf_bytes=b"%PDF-1.7 x", filename="laporan.pdf")
        self.assertTrue(hasil)
        to, msg = t[0]
        self.assertEqual(to, "a@b.id")
        msg = email.message_from_string(msg.as_string())
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        self.assertEqual(msg["Subject"], "Subjek")
        tipe = [p.get_content_type() for p in msg.walk()]
        self.assertEqual(tipe.count("application/pdf"), 1)
        self.assertIn("text/plain", tipe)
        self.assertIn("text/html", tipe)
        self.assertIn("multipart/alternative", tipe)
        pdf_part = [p for p in msg.walk() if p.get_content_type() == "application/pdf"][0]
        self.assertEqual(pdf_part.get_filename(), "laporan.pdf")
        self.assertEqual(pdf_part.get_payload(decode=True), b"%PDF-1.7 x")
        lu = msg["List-Unsubscribe"]
        self.assertIn(f"<{self.URL}>", lu)
        self.assertIn(f"<mailto:{get_settings().SMTP_FROM}?subject=unsubscribe>", lu)
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_mime_tanpa_lampiran(self):
        hasil, t = self.kirim()
        self.assertTrue(hasil)
        msg = email.message_from_string(t[0][1].as_string())
        tipe = [p.get_content_type() for p in msg.walk()]
        self.assertNotIn("application/pdf", tipe)
        self.assertIn("text/plain", tipe)
        self.assertIn("text/html", tipe)
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_galat_smtp_mengembalikan_false_tanpa_alamat_di_log(self):
        def gagal(to, msg):
            raise OSError(f"ditolak untuk {to}")
        with patch.object(email_service, "_deliver", gagal):
            with self.assertLogs("jatahku.email", level="DEBUG") as log:
                hasil = email_service.send_laporan_email("rahasia@b.id", "S", "<p>h</p>", "t", self.URL)
                email_service.logger.info("penanda")
        self.assertFalse(hasil)
        self.assertNotIn("rahasia@b.id", "\n".join(log.output))
        self.assertTrue(any(r.levelname == "ERROR" for r in log.records))

    def test_smtp_macet_berhenti_di_batas_waktu_dan_mengembalikan_false(self):
        # Ruling R-T3-1: `_deliver` menyambung dengan batas waktu; batas waktu yang terlampaui (di sini dilempar
        # tiruan `smtplib.SMTP`) menjadi False biasa, tanpa alamat di log, jadi antrean menghitungnya sebagai percobaan.
        smtp_cls = MagicMock(side_effect=TimeoutError("timed out"))
        setelan = SimpleNamespace(SMTP_HOST="mail.test", SMTP_PORT=2525, SMTP_USER="kirim@contoh.test",
                                  SMTP_PASSWORD="rahasia-smtp", SMTP_FROM="kirim@contoh.test", SMTP_FROM_NAME="Jatahku")
        with patch.object(email_service, "get_settings", return_value=setelan), \
                patch.object(email_service.smtplib, "SMTP", smtp_cls), \
                self.assertLogs("jatahku.email", level="ERROR") as log:
            hasil = email_service.send_laporan_email("rahasia@b.id", "S", "<p>h</p>", "t", self.URL)
        self.assertFalse(hasil)
        self.assertEqual(smtp_cls.call_args.kwargs.get("timeout"), 30)
        self.assertNotIn("rahasia@b.id", "\n".join(log.output))
        self.assertIn("TimeoutError", "\n".join(log.output))

    def test_log_sukses_tanpa_alamat(self):
        with patch.object(email_service, "_deliver", lambda to, msg: None):
            with self.assertLogs("jatahku.email", level="DEBUG") as log:
                email_service.send_laporan_email("rahasia@b.id", "S", "<p>h</p>", "t", self.URL)
                email_service.logger.info("penanda")
        self.assertNotIn("rahasia@b.id", "\n".join(log.output))


class Template(unittest.TestCase):
    def test_footer_html_opsional_dan_kompatibel(self):
        polos = email_service.email_template("J", "<p>x</p>", "Tombol", "https://u")
        dgn = email_service.email_template("J", "<p>x</p>", "Tombol", "https://u", footer_html='<a href="https://f">Foot</a>')
        self.assertNotIn("Foot", polos)
        self.assertIn('<a href="https://f">Foot</a>', dgn)
        self.assertLess(dgn.index("Foot"), dgn.index("Setiap rupiah ada jatahnya."))


if __name__ == "__main__":
    unittest.main()
