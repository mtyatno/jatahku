"""Isi email laporan berkala, email verifikasi, halaman berhenti berlangganan (tahap 2, Task 2), dan halaman konfirmasi
verifikasi email (Ruling F-4).

Semua fungsi murni (tanpa DB atau SMTP). Email laporan hanya memuat `data.judul`, `data.periode` (tanggal),
`data.email` (persen, hitungan amplop, tren) dan `data.sorotan.beruntun_terpanjang` (jumlah hari): tidak ada nominal
rupiah. Isi dari user atau data selalu lewat `email_service.h`.
"""
from datetime import date
from urllib.parse import quote
from uuid import UUID

from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.services.email_service import email_template, h
from app.services.laporan.hitung import BLN

LAMPIRAN_TERLAMPIR = "terlampir"
LAMPIRAN_BELUM_DIATUR = "belum_diatur"
LAMPIRAN_TIDAK_TERSEDIA = "tidak_tersedia"
TUJUAN_BERHENTI = "berhenti_email_laporan"
KONTAK_BANTUAN = "hi@jatahku.com"
# Beruntun satu hari bukan rekor, jadi baris "Rekor mencatat" baru tampil mulai dua hari.
REKOR_MINIMAL_HARI = 2

_AKHIR_PEMBUKA = {LAMPIRAN_TERLAMPIR: "Rincian lengkapnya tersedia dalam berkas PDF terlampir."}
_AKHIR_PEMBUKA_LAIN = "Rincian lengkapnya dapat dilihat di aplikasi."
_KOTAK_PDF = {
    LAMPIRAN_TERLAMPIR: (
        "🔒 Membuka berkas PDF",
        "Berkas PDF terlampir dilindungi kata sandi laporan yang Anda atur di Pengaturan → Laporan. Demi keamanan, "
        "kata sandi tidak pernah dikirim lewat email. Lupa kata sandi? Atur ulang di Pengaturan → Laporan, lalu unduh "
        "PDF dari halaman laporan.",
    ),
    LAMPIRAN_BELUM_DIATUR: (
        "🔒 Berkas PDF",
        "PDF belum dilampirkan karena kata sandi laporan belum diatur. Atur di Pengaturan → Laporan agar laporan "
        "berikutnya disertai PDF terkunci.",
    ),
    LAMPIRAN_TIDAK_TERSEDIA: (
        "🔒 Berkas PDF",
        "PDF tidak dapat dilampirkan kali ini. Rincian lengkap tetap tersedia di aplikasi.",
    ),
}
_CATATAN_OTOMATIS = "(Email ini dibuat secara otomatis oleh sistem, mohon tidak membalas email ini.)"
_KETERANGAN = (
    "Surat elektronik ini dibuat secara komputerisasi sehingga tidak memerlukan tanda tangan.",
    "Apabila Anda bukan pemilik akun Jatahku yang dimaksud, mohon abaikan dan hapus email ini beserta lampirannya.",
)
_BANTUAN_AWAL = "Untuk bantuan, hubungi "


def _periode(periode) -> tuple[str, int] | tuple[None, None]:
    """("27 Sep – 26 Okt 2026", tahun akhir); tahun ditulis sekali bila sama. (None, None) bila periode tak terbaca."""
    try:
        mulai, akhir = date.fromisoformat(periode["mulai"]), date.fromisoformat(periode["akhir"])
    except (TypeError, KeyError, ValueError):
        return None, None
    awal = f"{mulai.day} {BLN[mulai.month]}" + ("" if mulai.year == akhir.year else f" {mulai.year}")
    return f"{awal} – {akhir.day} {BLN[akhir.month]} {akhir.year}", akhir.year


def _ringkasan(data: dict) -> list[list[tuple[str, bool]]]:
    """Baris kotak ringkasan sebagai potongan (teks, tebal). Tren dan rekor yang tidak ada datanya tidak ditampilkan."""
    ringkas = data.get("email") or {}
    persen = ringkas.get("persen_terpakai")
    baris = [
        [("Anggaran terpakai: ", False), ("—" if persen is None else f"{persen}%", True)],
        [("Amplop aman: ", False), (str(ringkas.get("amplop_aman", 0)), True), (" · Lewat batas: ", False),
         (str(ringkas.get("amplop_lewat_batas", 0)), True)],
    ]
    tren = ringkas.get("tren_persen")
    if tren is not None:
        if tren == 0:
            baris.append([("Pengeluaran: ", False), ("sama", True), (" dengan periode sebelumnya", False)])
        else:
            arah = f"turun {abs(tren)}%" if tren < 0 else f"naik {tren}%"
            baris.append([("Pengeluaran: ", False), (arah, True), (" dibanding periode sebelumnya", False)])
    rekor = (data.get("sorotan") or {}).get("beruntun_terpanjang")
    if isinstance(rekor, int) and rekor >= REKOR_MINIMAL_HARI:
        baris.append([("Rekor mencatat: ", False), (f"{rekor} hari", True), (" berturut-turut", False)])
    return baris


def isi_email_laporan(data: dict, nama: str, tautan_laporan: str, tautan_berhenti: str,
                      lampiran: str) -> tuple[str, str, str]:
    """(subjek, html, teks) email laporan, bergaya pernyataan resmi (sapaan Bapak/Ibu, Anda). Tanpa nominal: hanya
    judul, tanggal periode, persen/hitungan/tren dari `data['email']`, dan rekor beruntun (lihat docstring modul)."""
    judul = data["judul"]
    nama = (nama or "").strip()
    periode, tahun = _periode(data.get("periode"))
    akhir_pembuka = _AKHIR_PEMBUKA.get(lampiran, _AKHIR_PEMBUKA_LAIN)
    judul_kotak, isi_kotak = _KOTAK_PDF.get(lampiran, _KOTAK_PDF[LAMPIRAN_TIDAK_TERSEDIA])
    ringkasan = _ringkasan(data)
    hak_cipta = f"© {tahun} Jatahku.com" if tahun else None

    pembuka_html = (f"Laporan keuangan periodik Anda untuk periode <strong>{h(periode)}</strong> telah terbit. "
                    if periode else "Laporan keuangan periodik Anda telah terbit. ") + h(akhir_pembuka)
    baris_html = "".join(
        '<p style="margin:4px 0 0;color:#2C2C2A">'
        + "".join(f"<strong>{h(t)}</strong>" if tebal else h(t) for t, tebal in potongan) + "</p>"
        for potongan in ringkasan
    )
    isi_html = (
        f'<p style="margin:0 0 12px">Yth. Bapak/Ibu{f" <strong>{h(nama)}</strong>" if nama else ""},</p>'
        f'<p style="margin:0 0 20px">{pembuka_html}</p>'
        '<div style="margin:0 0 16px;padding:16px 20px;background:#F1F8F5;border:1px solid #D5EBE2;'
        'border-radius:12px">'
        '<p style="margin:0 0 4px;font-size:12px;font-weight:700;letter-spacing:0.5px;color:#0F6E56">'
        f"RINGKASAN PERIODE</p>{baris_html}</div>"
        '<div style="padding:16px 20px;background:#FFF8E6;border:1px solid #F3DFA9;border-radius:12px">'
        f'<p style="margin:0 0 6px;font-weight:700;color:#7A4E00">{h(judul_kotak)}</p>'
        f'<p style="margin:0;color:#7A4E00">{h(isi_kotak)}</p></div>'
    )
    penutup = (
        f'<p style="margin:24px 0 16px;font-size:12px;font-style:italic;color:#888780">{h(_CATATAN_OTOMATIS)}</p>'
        '<p style="margin:0 0 4px;font-size:12px;font-weight:600;color:#5F5E5A">Keterangan:</p>'
        '<ol style="margin:0;padding-left:18px;font-size:12px;line-height:1.6;color:#5F5E5A">'
        + "".join(f"<li>{h(k)}</li>" for k in _KETERANGAN)
        + f'<li>{h(_BANTUAN_AWAL)}<a href="mailto:{KONTAK_BANTUAN}" style="color:#0F6E56">{KONTAK_BANTUAN}</a>.</li>'
        "</ol>"
    )
    kaki = (
        '<p style="margin:0 0 12px;font-size:12px;color:#888780">Tidak ingin menerima laporan lewat email? '
        f'<a href="{h(tautan_berhenti)}" style="color:#0F6E56">Berhenti berlangganan</a></p>'
    )
    html = email_template(judul, isi_html, "Buka Laporan di Jatahku →", tautan_laporan, footer_html=kaki,
                          penutup_html=penutup, hak_cipta=hak_cipta)

    pembuka_teks = (f"Laporan keuangan periodik Anda untuk periode {periode} telah terbit. " if periode
                    else "Laporan keuangan periodik Anda telah terbit. ") + akhir_pembuka
    keterangan = [*_KETERANGAN, f"{_BANTUAN_AWAL}{KONTAK_BANTUAN}."]
    teks = "\n".join([
        f"Yth. Bapak/Ibu{f' {nama}' if nama else ''},", "", pembuka_teks, "",
        "RINGKASAN PERIODE", *("".join(t for t, _ in potongan) for potongan in ringkasan), "",
        judul_kotak, isi_kotak, "",
        f"Buka laporan di Jatahku: {tautan_laporan}", "",
        _CATATAN_OTOMATIS, "",
        "Keterangan:", *(f"{i}. {k}" for i, k in enumerate(keterangan, 1)), "",
        f"Tidak ingin menerima laporan lewat email? Berhenti berlangganan: {tautan_berhenti}",
        *([hak_cipta] if hak_cipta else []),
    ])
    return f"{judul} · Jatahku", html, teks


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
