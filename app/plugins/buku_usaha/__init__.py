"""Buku Usaha — plugin pertama Jatahku (ADR-P7; docs/plugin/03-workflow.md U1–U6, 05-desain-buku-usaha.md).

U1 (kerangka): manifest, tabel `p_buku_usaha_*` (migrasi `u1b0k0u5aha1`), wizard pasang dengan 5 amplop bawaan,
dan Kontak (pelanggan dan pemasok). Semua data lewat `ctx.data()`; tidak ada angka laporan di sini — angka Buku Usaha
hanya dihitung di `metrics.py` (U3, aturan 6). Amplop bawaan dibuat klien lewat `POST /envelopes/` inti atas nama user;
fungsi `pengaturan` hanya melaporkan amplop mana yang sudah ada.

U2: aturan alokasi omzet (`/alokasi`), pratinjau dan pencatatan pemasukan usaha per jenis (`/penjualan`; pemasukan inti
lewat `ctx.catat_pemasukan`, `incomes:write`, satu commit dengan `income_meta`), dan field Pemasok + Akun beban di form
pengeluaran inti (`field_form` + `simpan_field` → `txn_meta`). Pembagian dihitung `alokasi.bagi` (pembantu murni).

U3: laba rugi per bulan kalender (`/laba-rugi`, angka dari `metrics.py`) dan laporan PDF/CSV (`/laporan`: plugin menyusun
`Laporan` di `laporan.py`, host menggambarnya). Butuh izin baca `transactions:read` + `incomes:read` (izin baru untuk
instalasi lama, disetujui lewat `POST …/izin`).

U4: delapan kartu Beranda (bentuk deklaratif; angka dari `metrics.py`, bentuk dan kalimat dari `kartu.py`/`teks.py`).
Tujuh kartu untuk pemilik dan admin; `penjualan_saya` untuk karyawan dan hanya membaca catatan karyawan itu sendiri
(`ctx.ringkas_pemasukan_saya`). Kartu memakai bulan kalender (`metrics.bulan_kartu`), bukan periode siklus Beranda.
"""
import re

from app.plugins.buku_usaha import alokasi as al
from app.plugins.buku_usaha import kartu as bentuk
from app.plugins.buku_usaha import laporan as lap
from app.plugins.buku_usaha import metrics
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


# ── U2: alokasi omzet ────────────────────────────────────────────────────
# Akun beban untuk laba rugi (U3 "beban per akun"); sama dengan `options` field `akun` di manifest.
AKUN_BEBAN = ("Bahan baku", "Gaji", "Sewa", "Listrik & air", "Transport", "Pemasaran", "Peralatan", "Lain-lain")


async def _amplop_bersama(ctx) -> dict:
    """{id teks: AmplopView} amplop bersama aktif ruang ini (alokasi dan pemasukan usaha tidak ke amplop pribadi)."""
    return {str(a.id): a for a in await ctx.envelopes() if not a.pribadi}


async def _aturan(ctx, amplop: dict | None = None) -> tuple[list[dict], bool]:
    """Aturan tersimpan yang masih berlaku: [{envelope_id, nama, emoji, persen}], dan apakah siap dipakai (ada, semua
    amplopnya masih ada, total 100). Amplop yang dihapus/diarsipkan sesudah aturan disimpan membuat aturan tidak siap."""
    amplop = amplop if amplop is not None else await _amplop_bersama(ctx)
    rows = await ctx.data("alokasi").cari(urut=("-persen", "created_at"), batas=50)
    aturan, hilang = [], False
    for r in rows:
        a = amplop.get(str(r["envelope_id"]))
        if a is None:
            hilang = True
            continue
        aturan.append({"envelope_id": a.id, "nama": a.nama, "emoji": a.emoji, "persen": r["persen"]})
    siap = bool(aturan) and not hilang and al.total_persen([(x["envelope_id"], x["persen"]) for x in aturan]) == al.SERATUS
    return aturan, siap


def _saran(amplop: dict) -> list[dict]:
    """Saran pertama (A3: 45/30/15/9/1) bila kelima amplop bawaan ada; selain itu kosong."""
    per_nama = {_rapi(a.nama): a for a in amplop.values()}
    hasil = []
    for nama, persen in al.SARAN_PERSEN.items():
        a = per_nama.get(_rapi(nama))
        if a is None:
            return []
        hasil.append({"envelope_id": a.id, "nama": a.nama, "emoji": a.emoji, "persen": persen})
    return hasil


@plugin.rute("GET", "/alokasi", izin=["envelopes:read"])
async def lihat_alokasi(ctx, req):
    amplop = await _amplop_bersama(ctx)
    aturan, siap = await _aturan(ctx, amplop)
    tersimpan = await ctx.data("alokasi").hitung() > 0
    return {
        "aturan": aturan,
        "siap": siap,
        "tersimpan": tersimpan,
        "saran": [] if tersimpan else _saran(amplop),
        "amplop": [{"envelope_id": a.id, "nama": a.nama, "emoji": a.emoji, "tujuan": a.tujuan}
                   for a in amplop.values()],
    }


@plugin.rute("PUT", "/alokasi", izin=["envelopes:read"])
async def simpan_alokasi(ctx, req):
    body = req.body if isinstance(req.body, dict) else {}
    if set(body) - {"aturan"}:
        raise NilaiTidakSah("Isian alokasi memuat kolom yang tidak dikenal.")
    baru = al.rapikan_aturan(body.get("aturan"))
    total = al.total_persen(baru)
    if total != al.SERATUS:
        raise GalatRute(422, "alokasi_bukan_100", f"Total alokasi harus 100%, sekarang {total.normalize():f}%.")
    amplop = await _amplop_bersama(ctx)
    for eid, _ in baru:
        if eid not in amplop:
            raise GalatRute(422, "amplop_tidak_ada", "Amplop tidak ditemukan di ruang ini.")
    tabel = ctx.data("alokasi")
    lama = {str(r["envelope_id"]): r for r in await tabel.cari(batas=50)}
    for eid, r in lama.items():
        if eid not in dict(baru):
            await tabel.hapus(r["id"])
    for eid, persen in baru:
        if eid in lama:
            if lama[eid]["persen"] != persen:
                await tabel.ubah(lama[eid]["id"], {"persen": persen})
        else:
            await tabel.tambah({"envelope_id": eid, "persen": persen})
    aturan, siap = await _aturan(ctx, amplop)
    return {"aturan": aturan, "siap": siap, "tersimpan": True, "saran": []}


# ── U2: penjualan dan jenis pemasukan ────────────────────────────────────
def _jenis(v) -> str:
    if v is None:
        return "penjualan"
    if v not in al.JENIS:
        raise GalatRute(422, "jenis_tidak_dikenal", "Jenis pemasukan harus penjualan, modal, pinjaman, atau lain.")
    return v


async def _pembagian(ctx, jenis: str, jumlah, envelope_id) -> list[dict]:
    """[{envelope_id, nama, emoji, persen, jumlah}] untuk satu pemasukan. Penjualan: menurut aturan alokasi (422
    `alokasi_belum_diatur` bila belum siap). Jenis lain: satu amplop (`envelope_id`, bawaan Laba ditahan)."""
    amplop = await _amplop_bersama(ctx)
    if jenis == "penjualan":
        if envelope_id is not None:
            raise NilaiTidakSah("Penjualan selalu dibagi menurut alokasi omzet.")
        aturan, siap = await _aturan(ctx, amplop)
        if not siap:
            raise GalatRute(422, "alokasi_belum_diatur",
                            "Atur alokasi omzet dulu (total 100%) di Buku Usaha › Alokasi omzet.")
        bagian = al.bagi(jumlah, [(a["envelope_id"], a["persen"]) for a in aturan])
        return [{**a, "jumlah": b} for a, b in zip(aturan, bagian)]
    if envelope_id is None:
        a = next((x for x in amplop.values() if _rapi(x.nama) == _rapi(al.AMPLOP_BAWAAN_NON_PENJUALAN)), None)
        if a is None:
            raise GalatRute(422, "amplop_wajib", "Pilih amplop tujuan pemasukan ini.")
    else:
        a = amplop.get(str(envelope_id))
        if a is None:
            raise GalatRute(422, "amplop_tidak_ada", "Amplop tidak ditemukan di ruang ini.")
    return [{"envelope_id": a.id, "nama": a.nama, "emoji": a.emoji, "persen": None, "jumlah": jumlah}]


def _isi_pemasukan(body) -> dict:
    if not isinstance(body, dict):
        raise NilaiTidakSah("Isian pemasukan tidak terbaca.")
    asing = set(body) - {"jumlah", "jenis", "envelope_id", "tanggal", "kontak_id", "keterangan", "client_ref"}
    if asing:
        raise NilaiTidakSah("Isian pemasukan memuat kolom yang tidak dikenal.")
    eid = body.get("envelope_id")
    if eid is not None and (not isinstance(eid, str) or len(eid) > 64):
        raise NilaiTidakSah("Amplop tidak dikenali.")
    return {"jumlah": al.jumlah_uang(body.get("jumlah")), "jenis": _jenis(body.get("jenis")), "envelope_id": eid}


@plugin.rute("POST", "/penjualan/pratinjau", izin=["envelopes:read"])
async def pratinjau_penjualan(ctx, req):
    """Pratinjau pembagian tanpa menyimpan apa pun (form penjualan menampilkannya sambil user mengetik)."""
    body = req.body if isinstance(req.body, dict) else {}
    isi = _isi_pemasukan({k: v for k, v in body.items() if k in ("jumlah", "jenis", "envelope_id")})
    return {"jenis": isi["jenis"], "jumlah": isi["jumlah"],
            "pembagian": await _pembagian(ctx, isi["jenis"], isi["jumlah"], isi["envelope_id"])}


@plugin.rute("POST", "/penjualan", izin=["envelopes:read", "incomes:write"])
async def catat_penjualan(ctx, req):
    """Satu pemasukan usaha: pemasukan inti dibagi ke amplop (`ctx.catat_pemasukan`) dan `income_meta` (jenis,
    pelanggan) dalam satu commit. Pelanggan hanya untuk penjualan. `client_ref` dari klien: kirim ulang yang sudah
    tercatat menjawab 200 dengan catatan lama, tanpa menulis apa pun (review #201 T5)."""
    isi = _isi_pemasukan(req.body)
    jenis, jumlah = isi["jenis"], isi["jumlah"]
    kontak = None
    kid = req.body.get("kontak_id")
    if kid is not None:
        if jenis != "penjualan":
            raise NilaiTidakSah("Pelanggan hanya untuk penjualan.")
        kontak = await ctx.data("kontak").ambil(kid) if isinstance(kid, str) else None
        if kontak is None or kontak["peran"] != "pelanggan":
            raise GalatRute(422, "kontak_tidak_ada", "Pelanggan tidak ditemukan.")
    tgl = al.tanggal(req.body.get("tanggal"))
    ket = al.keterangan(jenis, req.body.get("keterangan"), kontak["nama"] if kontak else None)
    bagian = await _pembagian(ctx, jenis, jumlah, isi["envelope_id"])
    hasil = await ctx.catat_pemasukan(jumlah=jumlah, keterangan=ket, tanggal=tgl,
                                      pembagian=[(b["envelope_id"], b["jumlah"]) for b in bagian],
                                      client_ref=req.body.get("client_ref"))
    if hasil["ulang"]:
        return await _penjualan_lama(ctx, hasil)
    await ctx.data("income_meta").tambah({"income_id": hasil["income_id"], "jenis": jenis,
                                          "kontak_id": kontak["id"] if kontak else None})
    return Jawaban({
        "income_id": hasil["income_id"], "jenis": jenis, "jumlah": jumlah, "tanggal": hasil["tanggal"],
        "keterangan": ket, "kontak": {"id": kontak["id"], "nama": kontak["nama"]} if kontak else None,
        "pembagian": bagian, "ulang": False,
    }, 201)


async def _penjualan_lama(ctx, hasil) -> Jawaban:
    """Jawaban kirim ulang: catatan yang sudah tersimpan (jenis dan pelanggan dari `income_meta`)."""
    meta = (await ctx.data("income_meta").cari(saring={"income_id": hasil["income_id"]}, batas=1) or [None])[0]
    jenis = meta["jenis"] if meta else "penjualan"
    kontak = await ctx.data("kontak").ambil(meta["kontak_id"]) if meta and meta["kontak_id"] else None
    amplop = await _amplop_bersama(ctx)
    return Jawaban({
        "income_id": hasil["income_id"], "jenis": jenis, "jumlah": hasil["jumlah"], "tanggal": hasil["tanggal"],
        "keterangan": None, "kontak": {"id": kontak["id"], "nama": kontak["nama"]} if kontak else None,
        "pembagian": [{"envelope_id": b["envelope_id"], "nama": b["nama"],
                       "emoji": getattr(amplop.get(str(b["envelope_id"])), "emoji", None), "persen": None,
                       "jumlah": b["jumlah"]} for b in hasil["pembagian"]],
        "ulang": True,
    }, 200)


# ── U2: pemasok dan akun beban di form pengeluaran ───────────────────────
@plugin.field_form("transaction", "pemasok")
async def field_pemasok(ctx, nilai):
    k = await ctx.data("kontak").ambil(nilai)
    if k is None or k["peran"] != "pemasok":
        raise NilaiTidakSah("pemasok tidak ditemukan.")
    return k["id"]


@plugin.field_form("transaction", "akun")
async def field_akun(ctx, nilai):
    if nilai not in AKUN_BEBAN:          # host sudah mencocokkan `options`; lapis kedua
        raise NilaiTidakSah("akun beban tidak dikenali.")
    return nilai


@plugin.simpan_field("transaction")
async def simpan_field_pengeluaran(ctx, transaction_id, nilai):
    """Satu baris `txn_meta` per transaksi (unik di antara baris hidup), di commit yang sama dengan transaksinya."""
    await ctx.data("txn_meta").tambah({"transaction_id": transaction_id, "kontak_id": nilai.get("pemasok"),
                                       "akun": nilai.get("akun")})


# ── U3: laba rugi dan laporan ────────────────────────────────────────────
FORMAT_LAPORAN = ("pdf", "csv")


@plugin.rute("GET", "/laba-rugi", izin=["transactions:read", "incomes:read"])
async def laba_rugi(ctx, req):
    """Laba rugi satu bulan kalender (`?periode=YYYY-MM`, bawaan bulan ini) dan banding bulan sebelumnya."""
    hari = metrics.hari_ini(ctx)
    th, bl = metrics.periode(req.query.get("periode"), hari)
    return await metrics.laba_rugi(ctx, th, bl, hari)


@plugin.rute("GET", "/laporan", izin=["envelopes:read", "transactions:read", "incomes:read"])
async def unduh_laporan(ctx, req):
    """Laporan laba rugi satu bulan sebagai berkas (`?periode=YYYY-MM&format=pdf|csv`); host menggambar dan
    mengirimnya sebagai lampiran."""
    fmt = req.query.get("format") or "pdf"
    if fmt not in FORMAT_LAPORAN:
        raise GalatRute(422, "format_tidak_dikenal", "Format laporan harus pdf atau csv.")
    hari = metrics.hari_ini(ctx)
    th, bl = metrics.periode(req.query.get("periode"), hari)
    return await lap.laba_rugi(ctx, th, bl, fmt, hari)


# ── U4: kartu Beranda ────────────────────────────────────────────────────
BACA_ANGKA = ["transactions:read", "incomes:read"]


async def _laba_rugi_kartu(ctx, periode) -> dict:
    hari = metrics.hari_ini(ctx)
    th, bl = metrics.bulan_kartu(periode, hari)
    return await metrics.laba_rugi(ctx, th, bl, hari)


@plugin.kartu("buku_usaha.omzet", izin=BACA_ANGKA)
async def kartu_omzet(ctx, pengaturan, periode):
    return bentuk.omzet(await _laba_rugi_kartu(ctx, periode))


@plugin.kartu("buku_usaha.laba", izin=BACA_ANGKA)
async def kartu_laba(ctx, pengaturan, periode):
    return bentuk.laba(await _laba_rugi_kartu(ctx, periode))


@plugin.kartu("buku_usaha.kas", izin=["envelopes:read"])
async def kartu_kas(ctx, pengaturan, periode):
    """Sisa amplop bersama saat ini (bukan per periode yang dipilih di Beranda)."""
    return bentuk.kas(await metrics.kas_usaha(ctx))


@plugin.kartu("buku_usaha.arus_kas_13", izin=BACA_ANGKA)
async def kartu_arus_kas(ctx, pengaturan, periode):
    return bentuk.arus_kas(await metrics.arus_kas_13(ctx, metrics.hari_ini(ctx)))


@plugin.kartu("buku_usaha.alokasi_omzet", izin=["envelopes:read", *BACA_ANGKA])
async def kartu_alokasi(ctx, pengaturan, periode):
    amplop = await _amplop_bersama(ctx)
    aturan, siap = await _aturan(ctx, amplop)
    if not siap:
        return bentuk.alokasi([])
    th, bl = metrics.bulan_kartu(periode, metrics.hari_ini(ctx))
    aturan = [{"envelope_id": str(a["envelope_id"]), "nama": a["nama"], "persen": a["persen"],
               "tujuan": amplop[str(a["envelope_id"])].tujuan} for a in aturan]
    return bentuk.alokasi(metrics.alokasi_omzet(aturan, await metrics.omzet_penjualan(ctx, th, bl),
                                                await metrics.terpakai_per_amplop(ctx, th, bl)))


@plugin.kartu("buku_usaha.beban_akun", izin=BACA_ANGKA)
async def kartu_beban(ctx, pengaturan, periode):
    return bentuk.beban(await _laba_rugi_kartu(ctx, periode))


@plugin.kartu("buku_usaha.pelanggan_teratas", izin=["incomes:read"])
async def kartu_pelanggan(ctx, pengaturan, periode):
    th, bl = metrics.bulan_kartu(periode, metrics.hari_ini(ctx))
    baris = await metrics.pelanggan_bulan(ctx, th, bl)
    kontak = ctx.data("kontak")
    nama = {}
    for b in baris:
        k = await kontak.ambil(b["kontak_id"])
        if k is not None:
            nama[b["kontak_id"]] = k["nama"]
    return bentuk.pelanggan(baris, nama)


@plugin.kartu("buku_usaha.penjualan_saya", izin=["incomes:read"])
async def kartu_penjualan_saya(ctx, pengaturan, periode):
    """Kartu karyawan: hanya penjualan yang dicatat karyawan itu sendiri bulan ini; tidak ada angka ruang."""
    th, bl = metrics.bulan_kartu(periode, metrics.hari_ini(ctx))
    return bentuk.penjualan_saya(await metrics.penjualan_saya_bulan(ctx, th, bl), metrics.kunci(th, bl))
