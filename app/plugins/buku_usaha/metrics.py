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
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.plugins.buku_usaha import alokasi as al
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


# ── U4: angka kartu Beranda ──────────────────────────────────────────────
MINGGU_ARUS_KAS = 13
PELANGGAN_TERATAS = 5


def bulan_kartu(periode, hari: date) -> tuple[int, int]:
    """Bulan kalender yang ditampilkan kartu (keputusan B U4): Beranda mengirim periode siklus, Buku Usaha memakai
    bulan kalender. Periode berjalan = bulan ini; periode lampau = bulan tanggal akhirnya; tidak pernah sesudah
    bulan ini."""
    if periode is None or periode.berjalan:
        return hari.year, hari.month
    return min((periode.end.year, periode.end.month), (hari.year, hari.month))


def minggu(hari: date, banyak: int = MINGGU_ARUS_KAS) -> list[tuple[date, date]]:
    """`banyak` minggu Senin–Minggu berurutan; yang terakhir adalah minggu berjalan."""
    senin = hari - timedelta(days=hari.weekday())
    return [(senin - timedelta(weeks=i), senin - timedelta(weeks=i) + timedelta(days=6))
            for i in range(banyak - 1, -1, -1)]


def arus_kas(daftar_minggu, transaksi, pemasukan) -> list[dict]:
    """Uang masuk dan keluar per minggu (keputusan D U4: aktual, tanpa proyeksi).

    `transaksi`: kunci (tanggal,) dari amplop bersama. `pemasukan`: kunci (tanggal, kind). Masuk = semua pemasukan
    (`kind` pemasukan atau top-up: penjualan, modal, pinjaman, lain-lain). Keluar = pengeluaran + prive (−alokasi).
    Transfer antar-amplop dan penyesuaian saldo bukan arus kas."""
    hasil = [{"mulai": a, "akhir": b, "masuk": NOL, "keluar": NOL} for a, b in daftar_minggu]
    if not hasil:
        return hasil
    awal = hasil[0]["mulai"]

    def kotak(tgl):
        i = (tgl - awal).days // 7 if tgl is not None else -1
        return hasil[i] if 0 <= i < len(hasil) else None

    for r in transaksi:
        k = kotak(r.kunci[0])
        if k is not None:
            k["keluar"] += r.jumlah
    for r in pemasukan:
        tgl, kind = r.kunci
        k = kotak(tgl)
        if k is None:
            continue
        if kind in KIND_TANPA_JENIS:
            k["masuk"] += r.jumlah
        elif kind == KIND_PRIVE:
            k["keluar"] += -r.dialokasikan
    return hasil


def kas(amplop) -> dict:
    """Kas usaha (keputusan C U4) = jumlah sisa semua amplop **bersama** ruang ini (`AmplopView.sisa`, rumus saldo
    inti); amplop pribadi tidak ikut. `minus` = banyak amplop bersama yang sisanya di bawah nol."""
    bersama = [a for a in amplop if not a.pribadi]
    sisa = [a.sisa or NOL for a in bersama]
    return {"jumlah": sum(sisa, NOL), "amplop": len(bersama), "minus": sum(1 for s in sisa if s < 0)}


def alokasi_omzet(aturan, omzet_penjualan: Decimal, terpakai: dict) -> list[dict]:
    """Jatah tiap amplop dari omzet penjualan bulan itu menurut aturan alokasi (pembagian persis `alokasi.bagi`,
    sama dengan form Penjualan), dibanding pengeluaran amplop itu. Aturan kosong atau bukan 100% = []."""
    pasangan = [(a["envelope_id"], a["persen"]) for a in aturan]
    if not pasangan or al.total_persen(pasangan) != al.SERATUS:
        return []
    jatah = al.bagi(Decimal(omzet_penjualan), pasangan) if omzet_penjualan > 0 else [NOL] * len(pasangan)
    hasil = []
    for a, j in zip(aturan, jatah):
        pakai = Decimal(terpakai.get(a["envelope_id"], NOL))
        hasil.append({"envelope_id": a["envelope_id"], "nama": a["nama"], "persen": a["persen"],
                      "tujuan": a.get("tujuan") or "expense", "jatah": j, "terpakai": pakai,
                      "lewat": max(pakai - j, NOL)})
    return hasil


def pelanggan_teratas(baris, batas: int = PELANGGAN_TERATAS) -> list[dict]:
    """Pelanggan dengan penjualan terbesar. `baris`: kunci (income_meta.jenis, income_meta.kontak_id); hanya
    penjualan yang punya pelanggan."""
    hasil = [{"kontak_id": r.kunci[1], "jumlah": r.jumlah, "banyak": r.banyak}
             for r in baris if r.kunci[0] == "penjualan" and r.kunci[1] is not None]
    hasil.sort(key=lambda x: (-x["jumlah"], -x["banyak"], str(x["kontak_id"])))
    return hasil[:batas]


def penjualan_saya(baris) -> dict:
    """Penjualan yang dicatat viewer sendiri. `baris`: kunci (kind, income_meta.jenis) dari
    `ctx.ringkas_pemasukan_saya`. Sama dengan aturan omzet: berjenis penjualan, atau pemasukan inti tanpa jenis."""
    jumlah, banyak = NOL, 0
    for r in baris:
        kind, jenis = r.kunci
        if jenis == "penjualan" or (jenis is None and kind in KIND_TANPA_JENIS):
            jumlah += r.jumlah
            banyak += r.banyak
    return {"jumlah": jumlah, "banyak": banyak}


async def kas_usaha(ctx) -> dict:
    return kas(await ctx.envelopes(saldo=True))


async def arus_kas_13(ctx, hari: date) -> list[dict]:
    daftar = minggu(hari)
    mulai, akhir = daftar[0][0], daftar[-1][1]
    transaksi = await ctx.ringkas_transaksi(mulai, akhir, per=("tanggal",), hanya_bersama=True)
    pemasukan = await ctx.ringkas_pemasukan(mulai, akhir, per=("tanggal", "jenis"))
    return arus_kas(daftar, transaksi, pemasukan)


async def omzet_penjualan(ctx, th: int, bl: int) -> Decimal:
    """Omzet berjenis penjualan saja (tanpa pemasukan tanpa jenis): dasar jatah alokasi."""
    mulai, akhir = rentang(th, bl)
    baris = await ctx.ringkas_pemasukan(mulai, akhir, per=("income_meta.jenis",))
    return sum((r.jumlah for r in baris if r.kunci[0] == "penjualan"), NOL)


async def terpakai_per_amplop(ctx, th: int, bl: int) -> dict:
    mulai, akhir = rentang(th, bl)
    baris = await ctx.ringkas_transaksi(mulai, akhir, per=("amplop",), hanya_bersama=True)
    return {str(r.kunci[0]): r.jumlah for r in baris}


async def pelanggan_bulan(ctx, th: int, bl: int) -> list[dict]:
    mulai, akhir = rentang(th, bl)
    return pelanggan_teratas(await ctx.ringkas_pemasukan(
        mulai, akhir, per=("income_meta.jenis", "income_meta.kontak_id")))


async def penjualan_saya_bulan(ctx, th: int, bl: int) -> dict:
    mulai, akhir = rentang(th, bl)
    return penjualan_saya(await ctx.ringkas_pemasukan_saya(mulai, akhir, per=("jenis", "income_meta.jenis")))


# ── U5: angka aturan BU-* ────────────────────────────────────────────────
JENDELA_KEBUTUHAN = 28          # hari yang dirata-rata untuk kebutuhan kas
HARI_KEBUTUHAN = 14             # "kebutuhan dua minggu"
AKHIR_AWAL_BULAN = 14           # sampai tanggal ini, prive dinilai untuk bulan lalu yang sudah utuh
SEN = Decimal("0.01")
NAMA_AMPLOP_PAJAK = "pajak"


def jendela_kebutuhan(hari: date) -> tuple[date, date]:
    """28 hari terakhir yang sudah lewat (sampai kemarin): hari ini belum selesai, jadi tidak ikut dirata-rata."""
    return hari - timedelta(days=JENDELA_KEBUTUHAN), hari - timedelta(days=1)


def kebutuhan(beban: Decimal) -> dict:
    """Kebutuhan kas dua minggu (keputusan U5) = rata-rata pengeluaran harian amplop bersama selama 28 hari terakhir
    × 14. Prive tidak ikut (bukan kebutuhan usaha). `harian` dua desimal, `jumlah` dibulatkan ke rupiah."""
    beban = Decimal(beban)
    return {"harian": (beban / JENDELA_KEBUTUHAN).quantize(SEN, rounding=ROUND_HALF_UP),
            "jumlah": (beban * HARI_KEBUTUHAN / JENDELA_KEBUTUHAN).quantize(Decimal(1), rounding=ROUND_HALF_UP)}


def cukup_hari(kas_sekarang: Decimal, harian: Decimal) -> int | None:
    """Kas cukup untuk berapa hari pengeluaran rata-rata (dibulatkan ke bawah). None bila tidak ada pengeluaran."""
    if harian <= 0:
        return None
    if kas_sekarang <= 0:
        return 0
    return int(Decimal(kas_sekarang) // Decimal(harian))


def bulan_prive(hari: date) -> tuple[int, int]:
    """Bulan yang dinilai BU-02. Sampai tanggal 14 laba bulan berjalan masih terlalu kecil untuk dibandingkan
    dengan prive yang biasanya ditarik di awal bulan, jadi yang dinilai bulan lalu yang sudah utuh."""
    if hari.day <= AKHIR_AWAL_BULAN:
        return bulan_lalu(hari.year, hari.month)
    return hari.year, hari.month


def prive(lr: dict) -> Decimal:
    """Prive bulan itu dari jawaban `laba_rugi`."""
    return next((x["jumlah"] for x in lr["di_luar_laba_rugi"] if x["jenis"] == KIND_PRIVE), NOL)


def amplop_pajak(amplop):
    """Amplop bersama bernama "Pajak" (amplop bawaan wizard pasang); None bila tidak ada atau sudah diganti nama."""
    return next((a for a in amplop if not a.pribadi and " ".join(a.nama.split()).lower() == NAMA_AMPLOP_PAJAK), None)


async def beban_jendela(ctx, hari: date) -> dict:
    """Pengeluaran amplop bersama selama jendela kebutuhan: {"jumlah", "banyak"}."""
    mulai, akhir = jendela_kebutuhan(hari)
    baris = await ctx.ringkas_transaksi(mulai, akhir, per=("bulan",), hanya_bersama=True)
    return {"jumlah": sum((r.jumlah for r in baris), NOL), "banyak": sum(r.banyak for r in baris)}


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
