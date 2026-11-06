"""Buku Usaha — plugin pertama Jatahku (ADR-P7; docs/plugin/03-workflow.md U1–U6, 05-desain-buku-usaha.md).

U1 (kerangka): manifest, tabel `p_buku_usaha_*` (migrasi `u1b0k0u5aha1`), wizard pasang dengan 5 amplop bawaan,
dan Kontak (pelanggan dan pemasok). Semua data lewat `ctx.data()`; tidak ada angka di sini — angka Buku Usaha hanya
dihitung di `metrics.py` (U3, aturan 6). Amplop bawaan dibuat klien lewat `POST /envelopes/` inti atas nama user
(plugin tidak menulis data inti di U1); fungsi `pengaturan` hanya melaporkan amplop mana yang sudah ada.
"""
import re

from app.plugins.sdk import GalatRute, Jawaban, NilaiTidakSah, Plugin

plugin = Plugin("buku_usaha")

PERAN_KONTAK = ("pelanggan", "pemasok")
# Amplop bawaan ruang usaha (05-desain-buku-usaha.md A3: alokasi omzet Bahan, Operasional, Prive, Laba ditahan, Pajak).
# `tujuan` = purpose amplop inti: Bahan dan Operasional amplop belanja (butuh anggaran bulanan), tiga lainnya cadangan
# (`saving`, tanpa anggaran) yang diisi dari alokasi omzet (U2) dan ditarik lewat prive (R8).
AMPLOP_BAWAAN = (
    {"nama": "Bahan", "emoji": "🥬", "tujuan": "expense", "keterangan": "Bahan baku dan barang dagangan"},
    {"nama": "Operasional", "emoji": "🔧", "tujuan": "expense", "keterangan": "Sewa, listrik, gaji, dan biaya harian"},
    {"nama": "Prive", "emoji": "👤", "tujuan": "saving", "keterangan": "Jatah pemilik yang ditarik ke ruang keluarga"},
    {"nama": "Laba ditahan", "emoji": "🏦", "tujuan": "saving", "keterangan": "Cadangan dan modal pengembangan"},
    {"nama": "Pajak", "emoji": "🧾", "tujuan": "saving", "keterangan": "PPh final dan kewajiban pajak"},
)
_TELEPON = r"^\+?[0-9][0-9 .\-]{4,28}$"


def _rapi(nama: str) -> str:
    return " ".join(nama.split()).strip().lower()


def _kontak(r: dict) -> dict:
    return {"id": r["id"], "nama": r["nama"], "peran": r["peran"], "telepon": r["telepon"], "catatan": r["catatan"],
            "dibuat": r["created_at"], "diubah": r["updated_at"]}


def _isi_kontak(body, *, baru: bool) -> dict:
    if not isinstance(body, dict):
        raise NilaiTidakSah("Isian kontak tidak terbaca.")
    asing = set(body) - {"nama", "peran", "telepon", "catatan"}
    if asing:
        raise NilaiTidakSah("Isian kontak memuat kolom yang tidak dikenal.")
    isi = {}
    if baru or "nama" in body:
        nama = body.get("nama")
        if not isinstance(nama, str) or not nama.strip():
            raise NilaiTidakSah("Nama kontak wajib diisi.")
        nama = " ".join(nama.split())
        if len(nama) > 120:
            raise NilaiTidakSah("Nama kontak paling banyak 120 karakter.")
        isi["nama"] = nama
    if baru or "peran" in body:
        peran = body.get("peran")
        if peran not in PERAN_KONTAK:
            raise NilaiTidakSah("Peran kontak harus pelanggan atau pemasok.")
        isi["peran"] = peran
    if "telepon" in body:
        telepon = body.get("telepon")
        if telepon is not None:
            if not isinstance(telepon, str):
                raise NilaiTidakSah("Nomor telepon tidak terbaca.")
            telepon = telepon.strip()
            if telepon and not re.fullmatch(_TELEPON, telepon):
                raise NilaiTidakSah("Nomor telepon tidak sah.")
        isi["telepon"] = telepon or None
    if "catatan" in body:
        catatan = body.get("catatan")
        if catatan is not None and not isinstance(catatan, str):
            raise NilaiTidakSah("Catatan tidak terbaca.")
        catatan = (catatan or "").strip()
        if len(catatan) > 500:
            raise NilaiTidakSah("Catatan paling banyak 500 karakter.")
        isi["catatan"] = catatan or None
    return isi


async def _kembar(ctx, nama: str, peran: str, kecuali=None) -> bool:
    """Nama yang sama (tanpa peka huruf dan spasi) dengan peran yang sama sudah ada?"""
    for r in await ctx.data("kontak").cari(saring={"peran": peran}, teks=nama, kolom_teks=("nama",), batas=50):
        if _rapi(r["nama"]) == _rapi(nama) and str(r["id"]) != str(kecuali):
            return True
    return False


@plugin.rute("GET", "/pengaturan", izin=["envelopes:read"])
async def pengaturan(ctx, req):
    """Wizard pasang dan kepala halaman: amplop bawaan mana yang sudah ada di ruang ini, dan jumlah kontak."""
    amplop = {_rapi(a.nama): a for a in await ctx.envelopes() if not a.pribadi}
    bawaan = []
    for b in AMPLOP_BAWAAN:
        ada = amplop.get(_rapi(b["nama"]))
        bawaan.append({**b, "ada": ada is not None, "envelope_id": ada.id if ada is not None else None})
    kontak = ctx.data("kontak")
    return {
        "ruang": ctx.nama_ruang,
        "amplop_bawaan": bawaan,
        "jumlah_kontak": {"pelanggan": await kontak.hitung(saring={"peran": "pelanggan"}),
                          "pemasok": await kontak.hitung(saring={"peran": "pemasok"})},
    }


@plugin.rute("GET", "/kontak")
async def daftar_kontak(ctx, req):
    peran = req.query.get("peran")
    if peran and peran not in PERAN_KONTAK:
        raise GalatRute(422, "peran_tidak_dikenal", "Peran kontak harus pelanggan atau pemasok.")
    q = (req.query.get("q") or "").strip()
    rows = await ctx.data("kontak").cari(saring={"peran": peran} if peran else None, teks=q or None,
                                         kolom_teks=("nama", "telepon"), urut=("nama", "created_at"), batas=200)
    return [_kontak(r) for r in rows]


@plugin.rute("POST", "/kontak")
async def tambah_kontak(ctx, req):
    isi = _isi_kontak(req.body, baru=True)
    if await _kembar(ctx, isi["nama"], isi["peran"]):
        raise GalatRute(409, "kontak_ganda", f"{isi['nama']} sudah ada sebagai {isi['peran']}.")
    return Jawaban(_kontak(await ctx.data("kontak").tambah(isi)), 201)


@plugin.rute("PATCH", "/kontak/{id}")
async def ubah_kontak(ctx, req):
    kontak = ctx.data("kontak")
    lama = await kontak.ambil(req.path["id"])
    if lama is None:
        raise GalatRute(404, "kontak_tidak_ada", "Kontak tidak ditemukan.")
    isi = _isi_kontak(req.body, baru=False)
    if not isi:
        return _kontak(lama)
    nama, peran = isi.get("nama", lama["nama"]), isi.get("peran", lama["peran"])
    if ("nama" in isi or "peran" in isi) and await _kembar(ctx, nama, peran, kecuali=lama["id"]):
        raise GalatRute(409, "kontak_ganda", f"{nama} sudah ada sebagai {peran}.")
    baru = await kontak.ubah(lama["id"], isi)
    return _kontak(baru if baru is not None else lama)


@plugin.rute("DELETE", "/kontak/{id}")
async def hapus_kontak(ctx, req):
    if not await ctx.data("kontak").hapus(req.path["id"]):
        raise GalatRute(404, "kontak_tidak_ada", "Kontak tidak ditemukan.")
    return Jawaban(None, 204)
