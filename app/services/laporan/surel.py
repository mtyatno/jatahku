"""Isi email laporan berkala, email verifikasi, halaman berhenti berlangganan (tahap 2, Task 2), dan halaman konfirmasi
verifikasi email (Ruling F-4).

Semua fungsi murni (tanpa DB atau SMTP). Email laporan hanya memuat `data.judul` dan `data.email` (persen, hitungan
amplop, tren, sorotan): tidak ada nominal rupiah. Isi dari user atau data selalu lewat `email_service.h`.
"""
from urllib.parse import quote
from uuid import UUID

from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.services.email_service import email_template, h

LAMPIRAN_TERLAMPIR = "terlampir"
LAMPIRAN_BELUM_DIATUR = "belum_diatur"
LAMPIRAN_TIDAK_TERSEDIA = "tidak_tersedia"
TUJUAN_BERHENTI = "berhenti_email_laporan"

_BARIS_LAMPIRAN = {
    LAMPIRAN_TERLAMPIR: "PDF laporan terlampir. Buka dengan kata sandi laporanmu.",
    LAMPIRAN_BELUM_DIATUR: "Atur kata sandi laporan di Pengaturan → Laporan untuk menerima PDF di email berikutnya.",
    LAMPIRAN_TIDAK_TERSEDIA: "PDF laporan bisa diunduh di aplikasi.",
}


def _teks_tren(persen) -> str:
    """Sama dengan `trenTeks` di frontend/src/lib/laporanView.js."""
    if persen is None:
        return ""
    if persen < 0:
        return f"Pengeluaran turun {abs(persen)}% dibanding periode lalu"
    if persen > 0:
        return f"Pengeluaran naik {persen}% dibanding periode lalu"
    return "Pengeluaran sama dengan periode lalu"


def isi_email_laporan(data: dict, nama: str, tautan_laporan: str, tautan_berhenti: str,
                      lampiran: str) -> tuple[str, str, str]:
    """(subjek, html, teks) email laporan. Tanpa nominal: hanya `data['judul']` dan `data['email']`."""
    judul = data["judul"]
    ringkas = data.get("email") or {}
    persen = ringkas.get("persen_terpakai")
    baris = [
        f"Anggaran terpakai: {'—' if persen is None else f'{persen}%'}",
        f"Amplop aman: {ringkas.get('amplop_aman', 0)} · Lewat batas: {ringkas.get('amplop_lewat_batas', 0)}",
    ]
    tren = _teks_tren(ringkas.get("tren_persen"))
    if tren:
        baris.append(tren)
    sorotan = ringkas.get("sorotan") or ""
    if sorotan:
        baris.append(sorotan)
    baris_lampiran = _BARIS_LAMPIRAN.get(lampiran, _BARIS_LAMPIRAN[LAMPIRAN_TIDAK_TERSEDIA])

    subjek = f"{judul} · Jatahku"
    isi_html = (
        f"<p>Hai {h(nama)},</p><p>{h(judul)} sudah terbit.</p>"
        f"<p>{'<br>'.join(h(b) for b in baris)}</p>"
        f"<p>{h(baris_lampiran)}</p>"
    )
    kaki = (
        '<p style="margin:0 0 12px;font-size:12px;color:#888780">Tidak ingin menerima laporan lewat email? '
        f'<a href="{h(tautan_berhenti)}" style="color:#0F6E56">Berhenti berlangganan</a></p>'
    )
    html = email_template(judul, isi_html, "Lihat laporan", tautan_laporan, footer_html=kaki)
    teks = "\n".join([
        f"Hai {nama},", "", f"{judul} sudah terbit.", "", *baris, "", baris_lampiran, "",
        f"Lihat laporan: {tautan_laporan}", "",
        f"Tidak ingin menerima laporan lewat email? Berhenti berlangganan: {tautan_berhenti}",
    ])
    return subjek, html, teks


def isi_email_verifikasi(nama: str, email: str, tautan: str) -> tuple[str, str, str]:
    """(subjek, html, teks) email verifikasi alamat penerima laporan; tanpa data keuangan."""
    inti = (f"Klik tombol di bawah untuk memverifikasi {email} sebagai alamat penerima laporan Jatahku. "
            "Tautan berlaku 24 jam.")
    tutup = "Kalau kamu tidak meminta ini, abaikan email ini."
    html = email_template(
        "Verifikasi email kamu",
        f"<p>Hai {h(nama)},</p><p>{h(inti)}</p><p>{h(tutup)}</p>",
        "Verifikasi email", tautan,
    )
    teks = f"Hai {nama},\n\n{inti}\n\nVerifikasi email: {tautan}\n\n{tutup}"
    return "Verifikasi email Jatahku kamu", html, teks


def tautan_berhenti(user_id) -> str:
    """Tautan berhenti berlangganan di setiap email laporan; token terikat user dan tidak pernah kedaluwarsa."""
    token = create_purpose_token(str(user_id), TUJUAN_BERHENTI, berlaku=None)
    return f"{get_settings().API_URL}/laporan/berhenti-email?token={quote(token, safe='')}"


def baca_token_berhenti(token: str) -> UUID | None:
    klaim = decode_purpose_token(token, TUJUAN_BERHENTI)
    if klaim is None:
        return None
    try:
        return UUID(klaim["sub"])
    except ValueError:
        return None


def _halaman(judul: str, isi_html: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{h(judul)} · Jatahku</title>
<style>body{{margin:0;background:#FAFAF6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2C2C2A}}
main{{max-width:480px;margin:48px auto;padding:32px;background:#fff;border:1px solid #E8E8E4;border-radius:16px}}
h1{{font-size:20px;margin:0 0 12px}}p{{color:#5F5E5A;font-size:14px;line-height:1.7}}
button{{background:#0F6E56;color:#fff;border:0;border-radius:12px;padding:12px 32px;font-weight:600;font-size:14px;cursor:pointer}}</style>
</head><body><main><h1>{h(judul)}</h1>{isi_html}</main></body></html>'''


def halaman_konfirmasi_berhenti(token: str) -> str:
    """Halaman GET: hanya meminta konfirmasi. Tombol mengirim POST ke alamat yang sama (token di query)."""
    aksi = h(f"/laporan/berhenti-email?token={quote(token, safe='')}")
    return _halaman(
        "Berhenti menerima email laporan?",
        f'<p>{h("Email laporan Jatahku untuk akun ini akan dimatikan. Laporan tetap terbit di aplikasi.")}</p>'
        f'<form method="post" action="{aksi}"><button type="submit">{h("Berhenti berlangganan")}</button></form>',
    )


def halaman_konfirmasi_verifikasi(token: str, email: str) -> str:
    """Halaman GET tautan verifikasi (Ruling F-4): hanya meminta konfirmasi, karena pemindai tautan di layanan email
    membuka GET. Tombol mengirim POST ke alamat yang sama (token di query), dan hanya POST yang memverifikasi."""
    aksi = h(f"/auth/verifikasi-email?token={quote(token, safe='')}")
    inti = f"Klik tombol di bawah untuk memverifikasi {email} sebagai alamat penerima laporan Jatahku."
    return _halaman(
        "Verifikasi email kamu",
        f'<p>{h(inti)}</p>'
        f'<form method="post" action="{aksi}"><button type="submit">{h("Verifikasi email")}</button></form>',
    )


def halaman_berhenti_selesai() -> str:
    return _halaman(
        "Email laporan dimatikan",
        f'<p>{h("Laporan tetap terbit di aplikasi. Kamu bisa menyalakannya lagi di Pengaturan → Laporan.")}</p>',
    )


def halaman_tautan_tak_berlaku() -> str:
    return _halaman(
        "Tautan tidak berlaku",
        f'<p>{h("Buka Pengaturan → Laporan di aplikasi Jatahku untuk mengatur email laporan.")}</p>',
    )
