"""Satu sumber angka Buku Usaha (Plugin U3; AGENTS.md "Plugin dan ruang" aturan 6).

Tab Laba rugi, laporan PDF/CSV, kartu Beranda (U4), `/laba` (U6), dan aturan BU-* (U5) membaca angka dari sini;
frontend hanya memformat. Angka diambil lewat `ctx.ringkas_transaksi` / `ctx.ringkas_pemasukan` (agregat di
database, tidak terpotong), satu kueri masing-masing untuk bulan diminta dan bulan sebelumnya.

Periode = **bulan kalender** (keputusan A U3): pembukuan usaha per bulan, bukan siklus gajian keluarga.

Aturan (keputusan C U3, 04-kontrak-api.md §6 "Laba rugi"):

- **Omzet** = pemasukan berjenis `penjualan` (`income_meta`, dari form Penjualan U2), ditambah pemasukan inti tanpa
  jenis (`incomes.kind` pemasukan atau top-up, tanpa `income_meta`, mis. penjualan karyawan lewat Catat cepat inti).
  Yang tanpa jenis dilaporkan terpisah (`omzet_tanpa_jenis`) supaya pemilik bisa memeriksanya.
- **Di luar laba rugi**: modal pemilik, pinjaman, dan pemasukan lain (`income_meta`), serta prive (`kind` prive; R8:
  sisi keluar bernominal 0 dengan alokasi negatif, jadi jumlahnya = −alokasi). Transfer antar-amplop dan penyesuaian
  saldo bukan pemasukan dan tidak dihitung.
- **Beban** = semua transaksi di amplop **bersama** ruang ini (amplop pribadi tidak). Transaksi privat anggota tetap
  dihitung nominalnya supaya laba cocok dengan saldo amplop, tetapi akunnya tidak terbaca (masuk "Belum berakun").
  Akun dari `txn_meta.akun` (U2); tanpa akun = "Belum berakun".
- **Laba** = omzet − beban. **Margin** = laba / omzet (None bila omzet 0). Perubahan = (sekarang − lalu) / |lalu|
  (None bila lalu 0). Rasio dibulatkan 4 desimal (0,2539 = 25,39%).
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.plugins.sdk import NilaiTidakSah

NOL = Decimal("0")
RASIO = Decimal("0.0001")
BELUM_BERAKUN = "Belum berakun"
KIND_TANPA_JENIS = ("pemasukan", "top-up")
KIND_PRIVE = "prive"
DI_LUAR = ("prive", "modal", "pinjaman", "lain")
_PERIODE = r"^(\d{4})-(\d{2})$"


# ── periode ──────────────────────────────────────────────────────────────
def periode(teks, hari_ini: date) -> tuple[int, int]:
    """`?periode=YYYY-MM` → (tahun, bulan); kosong = bulan ini. Tidak boleh sesudah bulan ini atau sebelum 2000."""
    if teks is None or teks == "":
        return hari_ini.year, hari_ini.month
    m = re.fullmatch(_PERIODE, teks) if isinstance(teks, str) else None
    if m is None:
        raise NilaiTidakSah("Periode harus berbentuk YYYY-MM.")
    th, bl = int(m.group(1)), int(m.group(2))
    if not 1 <= bl <= 12 or th < 2000:
        raise NilaiTidakSah("Periode harus berbentuk YYYY-MM.")
    if (th, bl) > (hari_ini.year, hari_ini.month):
        raise NilaiTidakSah("Periode tidak boleh sesudah bulan ini.")
    return th, bl


def rentang(th: int, bl: int) -> tuple[date, date]:
    return date(th, bl, 1), date(th, bl, monthrange(th, bl)[1])


def bulan_lalu(th: int, bl: int) -> tuple[int, int]:
    return (th - 1, 12) if bl == 1 else (th, bl - 1)


def kunci(th: int, bl: int) -> str:
    return f"{th:04d}-{bl:02d}"


# ── hitungan murni ───────────────────────────────────────────────────────
def rasio(bagian: Decimal, total: Decimal) -> Decimal | None:
    if not total:
        return None
    return (Decimal(bagian) / Decimal(total)).quantize(RASIO, rounding=ROUND_HALF_UP)


def perubahan(sekarang: Decimal, lalu: Decimal) -> Decimal | None:
    if not lalu:
        return None
    return ((Decimal(sekarang) - Decimal(lalu)) / abs(Decimal(lalu))).quantize(RASIO, rounding=ROUND_HALF_UP)


def hitung_bulan(bulan: str, transaksi, pemasukan) -> dict:
    """Angka satu bulan dari baris ringkasan.

    `transaksi`: `RingkasanView` dengan kunci (bulan, akun). `pemasukan`: kunci (bulan, kind, jenis income_meta).
    Baris bulan lain diabaikan."""
    omzet = tanpa_jenis = NOL
    banyak_penjualan = banyak_tanpa_jenis = 0
    luar = {j: [NOL, 0] for j in DI_LUAR}
    for r in pemasukan:
        bln, kind, jenis = r.kunci
        if bln != bulan:
            continue
        if jenis == "penjualan":
            omzet += r.jumlah
            banyak_penjualan += r.banyak
        elif jenis in ("modal", "pinjaman", "lain"):
            luar[jenis][0] += r.jumlah
            luar[jenis][1] += r.banyak
        elif jenis is None and kind in KIND_TANPA_JENIS:
            tanpa_jenis += r.jumlah
            banyak_tanpa_jenis += r.banyak
        elif jenis is None and kind == KIND_PRIVE:
            luar["prive"][0] += -r.dialokasikan
            luar["prive"][1] += r.banyak
    omzet_total = omzet + tanpa_jenis

    akun: dict[str, list] = {}
    for r in transaksi:
        bln, nama = r.kunci
        if bln != bulan:
            continue
        nama = nama or BELUM_BERAKUN
        a = akun.setdefault(nama, [NOL, 0])
        a[0] += r.jumlah
        a[1] += r.banyak
    beban_total = sum((a[0] for a in akun.values()), NOL)
    beban = [{"akun": n, "jumlah": a[0], "banyak": a[1], "porsi": rasio(a[0], beban_total)}
             for n, a in akun.items()]
    beban.sort(key=lambda b: (b["akun"] == BELUM_BERAKUN, -b["jumlah"], b["akun"]))

    laba = omzet_total - beban_total
    return {
        "omzet": omzet_total,
        "jumlah_penjualan": banyak_penjualan + banyak_tanpa_jenis,
        "omzet_tanpa_jenis": {"jumlah": tanpa_jenis, "banyak": banyak_tanpa_jenis},
        "beban": beban,
        "beban_total": beban_total,
        "laba": laba,
        "margin": rasio(laba, omzet_total),
        "di_luar_laba_rugi": [{"jenis": j, "jumlah": luar[j][0], "banyak": luar[j][1]} for j in DI_LUAR],
    }


def susun(th: int, bl: int, sekarang: dict, lalu: dict, hari_ini: date) -> dict:
    """Bentuk jawaban `GET /p/buku_usaha/laba-rugi` (04-kontrak-api.md §6)."""
    mulai, akhir = rentang(th, bl)
    lth, lbl = bulan_lalu(th, bl)
    prive = next(x["jumlah"] for x in sekarang["di_luar_laba_rugi"] if x["jenis"] == "prive")
    return {
        "periode": kunci(th, bl),
        "mulai": mulai,
        "akhir": akhir,
        "berjalan": (th, bl) == (hari_ini.year, hari_ini.month),
        **sekarang,
        "prive_dari_laba": rasio(prive, sekarang["laba"]) if sekarang["laba"] > 0 else None,
        "banding": {
            "periode": kunci(lth, lbl),
            "omzet": lalu["omzet"],
            "beban_total": lalu["beban_total"],
            "laba": lalu["laba"],
            "margin": lalu["margin"],
        },
        "perubahan": {
            "omzet": perubahan(sekarang["omzet"], lalu["omzet"]),
            "beban_total": perubahan(sekarang["beban_total"], lalu["beban_total"]),
            "laba": perubahan(sekarang["laba"], lalu["laba"]),
        },
    }


# ── dari data ────────────────────────────────────────────────────────────
async def laba_rugi(ctx, th: int, bl: int, hari_ini: date) -> dict:
    """Laba rugi bulan (th, bl) dan banding bulan sebelumnya: dua kueri agregat."""
    lth, lbl = bulan_lalu(th, bl)
    mulai, akhir = rentang(lth, lbl)[0], rentang(th, bl)[1]
    transaksi = await ctx.ringkas_transaksi(mulai, akhir, per=("bulan", "txn_meta.akun"), hanya_bersama=True)
    pemasukan = await ctx.ringkas_pemasukan(mulai, akhir, per=("bulan", "jenis", "income_meta.jenis"))
    return susun(th, bl, hitung_bulan(kunci(th, bl), transaksi, pemasukan),
                 hitung_bulan(kunci(lth, lbl), transaksi, pemasukan), hari_ini)


def hari_ini(ctx) -> date:
    """Tanggal hari ini di zona waktu user pemicu (bawaan Asia/Jakarta)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    zona = "Asia/Jakarta"
    if ctx.viewer is not None and ctx.viewer.zona_waktu:
        zona = ctx.viewer.zona_waktu
    try:
        return datetime.now(ZoneInfo(zona)).date()
    except Exception:
        return datetime.now(ZoneInfo("Asia/Jakarta")).date()
