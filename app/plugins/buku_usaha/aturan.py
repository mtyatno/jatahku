"""Aturan AI Advisor Buku Usaha: BU-01, BU-02, BU-03 (Plugin U5; 01-kajian.md "Buku Usaha"; AGENTS.md "Plugin dan
ruang" aturan 6 dan 7).

Fungsi murni: angka dari `metrics.py` → daftar `Saran` (kosong = aturan tidak menyala), dengan kalimat dari templat
`teks.py`. Tidak ada kueri dan tidak ada hitungan angka baru di sini; yang ada hanya syarat menyala, nada, dan urgensi.
Host memeriksa hasilnya (`titik.ke_insight`), menaruhnya di kartu AI Advisor (paling banyak satu saran per Fitur
Tambahan di daftar utama, sisanya di "lainnya"), dan tidak pernah memanggil aturan untuk karyawan (ADR-P3).

- **BU-01** kas usaha di bawah kebutuhan dua minggu.
- **BU-02** prive bulan itu melebihi laba.
- **BU-03** sudah ada omzet, tetapi amplop Pajak belum terisi.
"""
from __future__ import annotations

from decimal import Decimal

from app.plugins.buku_usaha import metrics, teks
from app.plugins.sdk import AksiRoute, Saran

NOL = Decimal("0")
SATU = Decimal("1")
HALAMAN = "/p/buku_usaha"
HARI_MERAH = 7                  # kas cukup kurang dari seminggu = merah
CATATAN_CUKUP = 10              # pengeluaran sebanyak ini dalam 28 hari: rata-ratanya layak dipercaya


def _laba_rugi() -> AksiRoute:
    return AksiRoute(teks.t("aksi_laba_rugi"), HALAMAN + "/laba-rugi")


def bu01(kas: dict, beban: dict) -> list[Saran]:
    """`kas` dari `metrics.kas`, `beban` dari `metrics.beban_jendela`."""
    butuh = metrics.kebutuhan(beban["jumlah"])
    sekarang = Decimal(kas["jumlah"])
    if butuh["jumlah"] <= 0 or sekarang >= butuh["jumlah"]:
        return []
    hari = metrics.cukup_hari(sekarang, butuh["harian"])
    kurang = butuh["jumlah"] - max(sekarang, NOL)
    judul = teks.t("bu01_judul_habis") if hari == 0 else teks.t("bu01_judul", hari=hari)
    return [Saran(
        entitas="kas", tone="danger" if hari < HARI_MERAH else "warn", chip=teks.t("bu01_chip"), judul=judul,
        isi=teks.t("bu01_isi", kas=teks.rupiah(sekarang), butuh=teks.rupiah(butuh["jumlah"])),
        fakta=((teks.t("bu01_fakta_kas"), teks.rupiah(sekarang)),
               (teks.t("bu01_fakta_butuh"), teks.rupiah(butuh["jumlah"]))),
        aksi=(_laba_rugi(),), rupiah=kurang,
        urgensi=(Decimal("0.5") + kurang / butuh["jumlah"] / 2).quantize(Decimal("0.01")),
        keyakinan="tinggi" if beban["banyak"] >= CATATAN_CUKUP else "sedang",
    )]


def bu02(lr: dict) -> list[Saran]:
    """`lr` dari `metrics.laba_rugi` untuk bulan `metrics.bulan_prive`."""
    prive, laba = metrics.prive(lr), Decimal(lr["laba"])
    if prive <= 0 or prive <= laba:
        return []
    selisih = prive - max(laba, NOL)
    return [Saran(
        entitas="prive-" + lr["periode"], tone="warn", chip=teks.t("bu02_chip"),
        judul=teks.t("bu02_judul", bulan=teks.nama_bulan(lr["periode"])),
        isi=teks.t("bu02_isi", prive=teks.rupiah(prive), laba=teks.rupiah(laba), selisih=teks.rupiah(selisih)),
        fakta=((teks.t("bu02_fakta_prive"), teks.rupiah(prive)), (teks.t("bu02_fakta_laba"), teks.rupiah(laba))),
        aksi=(_laba_rugi(),), rupiah=selisih, urgensi=Decimal("0.5"),
    )]


def bu03(pajak, lr: dict) -> list[Saran]:
    """`pajak` dari `metrics.amplop_pajak` (dengan saldo), `lr` dari `metrics.laba_rugi` bulan ini."""
    if pajak is None or (pajak.sisa or NOL) > 0:
        return []
    omzet, periode = Decimal(lr["omzet"]), lr["periode"]
    if omzet <= 0:
        omzet, periode = Decimal(lr["banding"]["omzet"]), lr["banding"]["periode"]
    if omzet <= 0:
        return []
    return [Saran(
        entitas="pajak", tone="info", chip=teks.t("bu03_chip"), judul=teks.t("bu03_judul"),
        isi=teks.t("bu03_isi", bulan=teks.nama_bulan(periode), omzet=teks.rupiah(omzet)),
        aksi=(AksiRoute(teks.t("aksi_alokasi"), HALAMAN + "/alokasi"),), urgensi=Decimal("0.3"),
    )]
