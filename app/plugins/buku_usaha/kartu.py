"""Bentuk kartu Beranda Buku Usaha (Plugin U4; 04-kontrak-api.md §4 "Bentuk deklaratif", §6 "Kartu Beranda").

Fungsi murni: angka dari `metrics.py` (aturan 6) → field bentuk deklaratif, dengan kalimat dari `teks.py` (aturan 7).
Host memeriksa hasilnya (`titik.rapikan_kartu`) sebelum dikirim; web hanya memformat.
"""
from __future__ import annotations

from decimal import Decimal

from app.plugins.buku_usaha import teks

SERATUS = Decimal("100")


def _banding(lr: dict, kunci: str) -> str:
    """Chip naik/turun dari bulan lalu, hanya untuk bulan yang sudah selesai: bulan berjalan belum utuh, jadi
    bandingannya dengan bulan lalu yang utuh selalu tampak anjlok. Angka bulan lalu tetap ada di kaki kartu."""
    return "" if lr.get("berjalan") else teks.perubahan(lr["perubahan"][kunci])


def omzet(lr: dict) -> dict:
    return {
        "value": lr["omzet"], "unit": "rp",
        "suffix": teks.t("kartu_banyak_penjualan", banyak=lr["jumlah_penjualan"]),
        "chip": _banding(lr, "omzet"),
        "footer": teks.t("kartu_omzet_kaki", bulan=teks.nama_bulan(lr["periode"]),
                         lalu=teks.rupiah(lr["banding"]["omzet"])),
    }


def laba(lr: dict) -> dict:
    return {
        "value": lr["laba"], "unit": "rp",
        "suffix": teks.t("kartu_margin", margin=teks.persen(lr["margin"])) if lr["margin"] is not None else "",
        "chip": _banding(lr, "laba"),
        "tone": "danger" if lr["laba"] < 0 else None,
        "footer": teks.t("kartu_laba_kaki", bulan=teks.nama_bulan(lr["periode"]), omzet=teks.rupiah(lr["omzet"]),
                         beban=teks.rupiah(lr["beban_total"])),
    }


def kas(k: dict) -> dict:
    return {
        "value": k["jumlah"], "unit": "rp",
        "suffix": teks.t("kartu_kas_amplop", banyak=k["amplop"]),
        "tone": "danger" if k["jumlah"] < 0 else None,
        "footer": teks.t("kartu_kas_minus", minus=k["minus"]) if k["minus"] else teks.t("kartu_kas_kaki"),
    }


def arus_kas(minggu: list[dict]) -> dict:
    return {
        "x": [teks.hari_bulan(m["mulai"]) for m in minggu],
        "series": [{"nama": teks.t("kartu_masuk"), "values": [m["masuk"] for m in minggu]},
                   {"nama": teks.t("kartu_keluar"), "values": [m["keluar"] for m in minggu]}],
    }


def alokasi(baris: list[dict]) -> dict:
    """Amplop belanja: terpakai dibanding jatahnya dari omzet (merah bila lewat). Amplop cadangan (prive, laba
    ditahan, pajak): jatahnya saja, karena uangnya keluar lewat prive atau tetap disimpan, bukan lewat pengeluaran."""
    items = []
    for b in baris:
        label = teks.t("kartu_alokasi_label", nama=b["nama"], persen=teks.persen(Decimal(b["persen"]) / SERATUS))
        if b["tujuan"] == "expense":
            items.append({"label": label[:60], "value": b["terpakai"], "target": b["jatah"],
                          "tone": "danger" if b["lewat"] > 0 else None})
        else:
            items.append({"label": label[:60], "value": b["jatah"]})
    return {"items": items}


def beban(lr: dict) -> dict:
    return {"items": [{"label": b["akun"][:60], "value": b["jumlah"], "target": lr["beban_total"]}
                      for b in lr["beban"][:10]]}


def pelanggan(baris: list[dict], nama: dict) -> dict:
    return {"items": [{"judul": (nama.get(b["kontak_id"]) or teks.t("kartu_kontak_terhapus"))[:80],
                       "subjudul": teks.t("kartu_banyak_penjualan", banyak=b["banyak"]), "nominal": b["jumlah"]}
                      for b in baris]}


def penjualan_saya(p: dict, periode: str) -> dict:
    return {
        "value": p["jumlah"], "unit": "rp",
        "suffix": teks.t("kartu_banyak_penjualan", banyak=p["banyak"]),
        "footer": teks.t("kartu_saya_kaki", bulan=teks.nama_bulan(periode)),
    }
