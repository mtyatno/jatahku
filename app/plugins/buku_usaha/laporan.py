"""Laporan laba rugi Buku Usaha sebagai berkas (Plugin U3; keputusan D–E): isi laporan untuk `GET /laporan`.

Plugin hanya menyusun `Laporan` (ringkasan, tabel, catatan); host menggambarnya menjadi PDF atau CSV dengan escape
dan batas yang sama untuk semua plugin (`app/plugins/host/berkas.py`). Angka dari `metrics.py` (aturan 6), kalimat dari
`teks.py` (aturan 7). Daftar penjualan dan pengeluaran per baris memakai `ctx.incomes` / `ctx.transactions` (paling
banyak 1.000 baris terbaru); bila terpotong, laporan mengatakannya, dan totalnya tetap dari agregat.
"""
from __future__ import annotations

from datetime import date

from app.plugins.buku_usaha import metrics, teks
from app.plugins.sdk import Laporan, TabelLaporan

LABEL_JENIS_OMZET = {"penjualan": "Penjualan", None: "Tanpa jenis"}


def _kontak_dari(meta) -> str | None:
    if not meta or not meta.get("kontak_id"):
        return None
    return str(meta["kontak_id"])


async def _nama_kontak(ctx, ids: set[str]) -> dict[str, str]:
    """{id: nama} kontak hidup ruang ini yang dipakai catatan bulan itu (kontak terhapus tidak bernama)."""
    if not ids:
        return {}
    nama = {str(k["id"]): k["nama"] for k in await ctx.data("kontak").cari(batas=1000)}
    for kid in list(ids - set(nama))[:200]:
        k = await ctx.data("kontak").ambil(kid)
        if k is not None:
            nama[kid] = k["nama"]
    return nama


async def laba_rugi(ctx, th: int, bl: int, fmt: str, hari_ini: date) -> Laporan:
    lr = await metrics.laba_rugi(ctx, th, bl, hari_ini)
    mulai, akhir = metrics.rentang(th, bl)
    pemasukan = await ctx.incomes(mulai, akhir, pendamping="income_meta")
    transaksi = await ctx.transactions(mulai, akhir, pendamping="txn_meta", hanya_bersama=True)
    amplop = {str(a.id): a.nama for a in await ctx.envelopes()}
    ids = {k for k in (_kontak_dari(x.meta) for x in [*pemasukan, *transaksi]) if k}
    return susun(lr, pemasukan, transaksi, amplop, await _nama_kontak(ctx, ids), ruang=ctx.nama_ruang, fmt=fmt)


def _omzet(p) -> str | None | bool:
    """Jenis omzet sebuah pemasukan: "penjualan", None (tanpa jenis), atau False (bukan omzet)."""
    jenis = (p.meta or {}).get("jenis")
    if jenis == "penjualan":
        return "penjualan"
    if p.meta is None and p.jenis in metrics.KIND_TANPA_JENIS:
        return None
    return False


def susun(lr: dict, pemasukan, transaksi, amplop: dict, kontak: dict, *, ruang: str, fmt: str) -> Laporan:
    """Isi laporan dari angka `metrics.laba_rugi` dan baris catatan bulan itu (murni; diuji tanpa database)."""
    bulan = teks.nama_bulan(lr["periode"])
    bulan_lalu = teks.nama_bulan(lr["banding"]["periode"])
    lalu = lr["banding"]

    ringkasan = (
        ("Omzet", lr["omzet"]),
        ("Beban", lr["beban_total"]),
        ("Laba bersih", lr["laba"]),
        ("Margin", teks.persen(lr["margin"])),
        ("Penjualan", lr["jumlah_penjualan"]),
        ("Prive", next(x["jumlah"] for x in lr["di_luar_laba_rugi"] if x["jenis"] == "prive")),
    )
    pokok = TabelLaporan(
        judul="Laba rugi",
        kolom=("Pos", bulan, bulan_lalu),
        baris=(
            ("Omzet", lr["omzet"], lalu["omzet"]),
            ("Beban", lr["beban_total"], lalu["beban_total"]),
            ("Laba bersih", lr["laba"], lalu["laba"]),
            ("Margin", teks.persen(lr["margin"]), teks.persen(lalu["margin"])),
        ),
    )
    beban = TabelLaporan(
        judul="Beban per akun",
        kolom=("Akun", "Catatan", "Jumlah", "Porsi"),
        baris=tuple((b["akun"], b["banyak"], b["jumlah"], teks.persen(b["porsi"])) for b in lr["beban"]),
        total=("Total beban", sum(b["banyak"] for b in lr["beban"]), lr["beban_total"], None) if lr["beban"] else None,
    )
    luar = TabelLaporan(
        judul="Di luar laba rugi",
        kolom=("Jenis", "Catatan", "Jumlah"),
        baris=tuple((teks.LABEL_DI_LUAR[x["jenis"]], x["banyak"], x["jumlah"]) for x in lr["di_luar_laba_rugi"]),
    )

    jual = [(p, _omzet(p)) for p in reversed(pemasukan)]
    jual = [(p, j) for p, j in jual if j is not False]
    penjualan = TabelLaporan(
        judul="Penjualan",
        kolom=("Tanggal", "Keterangan", "Pelanggan", "Jenis", "Jumlah"),
        baris=tuple((p.tanggal, p.deskripsi, kontak.get(_kontak_dari(p.meta)), LABEL_JENIS_OMZET[j], p.jumlah)
                    for p, j in jual),
        total=("Total", None, None, None, lr["omzet"]) if jual else None,
    )
    keluar = list(reversed(transaksi))
    pengeluaran = TabelLaporan(
        judul="Pengeluaran",
        kolom=("Tanggal", "Keterangan", "Amplop", "Akun", "Pemasok", "Jumlah"),
        baris=tuple((t.tanggal, t.deskripsi, amplop.get(str(t.amplop_id), "Amplop diarsipkan"),
                     (t.meta or {}).get("akun") or metrics.BELUM_BERAKUN, kontak.get(_kontak_dari(t.meta)),
                     t.jumlah) for t in keluar),
        total=("Total", None, None, None, None, lr["beban_total"]) if keluar else None,
    )

    catatan = [teks.t("aturan")]
    if lr["berjalan"]:
        catatan.insert(0, teks.t("berjalan"))
    tj = lr["omzet_tanpa_jenis"]
    if tj["banyak"]:
        catatan.append(teks.t("tanpa_jenis", banyak=tj["banyak"], jumlah=teks.rupiah(tj["jumlah"])))
    if any(b["akun"] == metrics.BELUM_BERAKUN for b in lr["beban"]):
        catatan.append(teks.t("belum_berakun"))
    total_keluar = sum(b["banyak"] for b in lr["beban"])
    if len(jual) < lr["jumlah_penjualan"]:
        catatan.append(teks.t("terpotong", apa="penjualan", tampil=len(jual), total=lr["jumlah_penjualan"]))
    if len(keluar) < total_keluar:
        catatan.append(teks.t("terpotong", apa="pengeluaran", tampil=len(keluar), total=total_keluar))

    return Laporan(
        format=fmt,
        nama_berkas=f"buku-usaha-laba-rugi-{lr['periode']}",
        judul=teks.t("judul_laba_rugi", bulan=bulan),
        subjudul=teks.t("subjudul_laba_rugi", ruang=ruang, mulai=teks.tanggal(lr["mulai"]),
                        akhir=teks.tanggal(lr["akhir"])),
        ringkasan=ringkasan,
        tabel=(pokok, beban, luar, penjualan, pengeluaran),
        catatan=tuple(catatan),
    )
