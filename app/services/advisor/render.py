"""Teks AI Advisor v2 — SATU-SATUNYA tempat kalimat insight (02-aturan.md §10, AGENTS.md "AI Advisor v2" #2).

Aturan mengembalikan data (`insight.Insight`); modul ini merakit chip, judul, isi,
fakta, label aksi, dan dasar. Hasilnya sama untuk web, chat web, dan Telegram
(`teks_telegram`). Format angka:
- chip & judul: `rp_ringkas` (Rp153 rb, Rp1,68 jt — dipotong, sama dengan `rpCompact` web);
- fakta: `rp_penuh` (persis, tanpa pembulatan);
- proyeksi diberi "±"; tanggal "24 Okt"; hari "Kamis 15 Okt"; rasio "1,8×".

Bahasa: "kamu", kalimat aktif, isi ≤ 2 kalimat, tanpa kata yang menghakimi.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.services.advisor.insight import Insight, Konteks

ZERO = Decimal("0")
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
TONE_EMOJI = {"danger": "🔴", "warn": "🟡", "info": "🔵", "ok": "🟢"}
MINUS = "–"
DISMISS_PILIHAN = ["nanti", "periode", "tidak_relevan"]


# ── format ──────────────────────────────────────────────────────────────
def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _ribuan(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def rp_penuh(v) -> str:
    """Rp1.685.200 — persis ke rupiah (setengah ke atas)."""
    n = int(_d(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{MINUS if n < 0 else ''}Rp{_ribuan(abs(n))}"


def rp_ringkas(v) -> str:
    """Rp1,68 jt · Rp525 rb · Rp800 (dipotong ke bawah, seperti `rpCompact` di web)."""
    x = _d(v)
    tanda = MINUS if x < 0 else ""
    a = abs(x)
    if a >= 1_000_000:
        jt = (a / 10_000).to_integral_value(rounding=ROUND_FLOOR) / 100
        teks = f"{jt:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{tanda}Rp{teks} jt"
    if a >= 1_000:
        return f"{tanda}Rp{_ribuan(int(a / 1000))} rb"
    return f"{tanda}Rp{_ribuan(int((a / 100).to_integral_value(rounding=ROUND_FLOOR) * 100))}"


def tgl(d: date | None) -> str:
    return f"{d.day} {BULAN[d.month - 1]}" if d else ""


def hari_tgl(d: date) -> str:
    return f"{HARI[d.weekday()]} {tgl(d)}"


def rasio(v) -> str:
    return f"{_d(v).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}".replace(".", ",") + "×"


def persen(v) -> str:
    return f"{int((_d(v) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))}%"


def _kalimat(*bagian: str) -> str:
    return " ".join(b for b in bagian if b)


# ── template per aturan: (ins, ctx, kpi) → {chip, judul, isi, fakta} ─────
def _har01(ins: Insight, ctx: Konteks, kpi: str | None) -> dict:
    d = ins.data
    r = d["rasio"]
    besar = r is not None and ins.tone == "danger"
    chip = f"{rasio(r)} jatah" if besar else f"Lewat {rp_ringkas(d['lebih'])}"
    judul = f"Belanja hari ini {rasio(r)} jatah" if r is not None else "Belanja hari ini lewat jatah"
    p = d.get("penyumbang")
    penyumbang = ""
    if p:
        nama = f"Struk {p['nama']}" if p["jenis"] == "struk" else p["nama"]
        penyumbang = f"{nama} menyumbang {persen(p['porsi'])}."
    fakta = [{"label": "Jatah hari ini sejak pagi", "nilai": rp_penuh(d["j0"])},
             {"label": "Belanja hari ini", "nilai": rp_penuh(d["t5"])}]
    if d.get("j1") is not None:
        fakta.append({"label": f"Aman {d['r']} hari ke depan", "nilai": f"{rp_penuh(d['j1'])}/hari"})
        if d["j0"] > d["j1"]:
            fakta.append({"label": "Aman per hari turun", "nilai": f"{rp_penuh(d['j0'] - d['j1'])}/hari"})
    tb = d.get("terbesar")
    if tb:
        fakta.append({"label": "Terbesar hari ini", "nilai": f"{tb['nama']} {rp_penuh(tb['jumlah'])} ({persen(tb['porsi'])})"})
    _fakta_batas(fakta, d, ctx)
    return {"chip": chip, "judul": judul, "isi": _kalimat(f"Lewat {rp_penuh(d['lebih'])}.", penyumbang),
            "fakta": fakta}


def _fakta_batas(fakta: list, d: dict, ctx: Konteks) -> None:
    eid, batas = d.get("batas_amplop_id"), d.get("batas")
    if eid and batas is not None and batas > 0:
        fakta.append({"label": f"Batas aman {ctx.nama.get(eid, '')}", "nilai": f"{rp_penuh(batas)}/hari"})


def _har02(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"Sisa {rp_ringkas(d['sisa'])} hari ini", "judul": "Belanja hari ini mendekati jatah",
            "isi": f"Sudah {rp_penuh(d['t5'])} dari jatah {rp_penuh(d['j0'])} hari ini.",
            "fakta": [{"label": "Jatah hari ini sejak pagi", "nilai": rp_penuh(d["j0"])},
                      {"label": "Sisa hari ini", "nilai": rp_penuh(d["sisa"])}]}


def _har03(ins, ctx, kpi):
    d = ins.data
    isi = "Tidak dihitung sebagai kebiasaan harian."
    if d.get("j1") is not None:
        isi += f" Aman {d['r']} hari ke depan jadi {rp_penuh(d['j1'])}/hari."
    return {"chip": f"Belanja besar {rp_ringkas(d['jumlah'])}",
            "judul": f"Belanja besar {rp_ringkas(d['jumlah'])} di {d['amplop']}", "isi": isi,
            "fakta": [{"label": "Belanja satu kali", "nilai": f"{d['amplop']} {rp_penuh(d['jumlah'])}"}]}


def _har04(ins, ctx, kpi):
    d = ins.data
    if d["j0"] <= 0:
        return {"chip": "Jatah Rp0", "judul": "Belum ada jatah hari ini",
                "isi": "Sisa bebas belanja sudah habis, jadi jatah hari ini Rp0.", "fakta": []}
    return {"chip": f"Sisa {rp_ringkas(d['sisa'])} hari ini", "judul": "Hari ini masih dalam jatah",
            "isi": f"Belanja {rp_penuh(d['t5'])} dari jatah {rp_penuh(d['j0'])}.",
            "fakta": [{"label": "Jatah hari ini sejak pagi", "nilai": rp_penuh(d["j0"])},
                      {"label": "Sisa hari ini", "nilai": rp_penuh(d["sisa"])}]}


def _har05(ins, ctx, kpi):
    return {"chip": "Belum ada catatan", "judul": "Belum ada catatan hari ini",
            "isi": "Biasanya kamu mencatat setiap hari. Ada belanja yang belum dicatat?", "fakta": []}


def _per01(ins, ctx, kpi):
    d = ins.data
    if kpi == "terpakai":
        chip = f"Lewat ±{rp_ringkas(d['t9'])}"
    else:
        chip = f"Habis ±{tgl(d['habis'])}" if d.get("habis") else f"Kurang ±{rp_ringkas(d['t9'])}"
    awal = []
    har = d.get("har01")
    if har and har.get("rasio") is not None:
        awal.append(f"Hari ini {rasio(har['rasio'])} jatah")
    if d["lewat7"]:
        awal.append(f"{d['lewat7']} dari 7 hari terakhir lewat jatah")
    pembuka = ""
    if awal:
        pembuka = "; ".join(awal) + "."
        pembuka = pembuka[0].upper() + pembuka[1:]
    isi = _kalimat(pembuka, f"Kalau tetap {rp_ringkas(d['t4'])}/hari, dana belanja kurang ±{rp_ringkas(d['t9'])} "
                            f"sebelum {tgl(d['pe'])}.")
    fakta = [
        {"label": "Sisa bebas", "nilai": f"{rp_penuh(d['t3'])} ÷ {d['r']} hari = {rp_penuh(d['j1'] or 0)}/hari"},
        {"label": "Rata-rata 7 hari terakhir", "nilai": f"{rp_penuh(d['t4'])}/hari"},
    ]
    if d.get("proyeksi_akhir") is not None:
        fakta.append({"label": "Perkiraan terpakai akhir periode",
                      "nilai": f"±{rp_penuh(d['proyeksi_akhir'])} dari dana {rp_penuh(d['dana'])}"})
    if d.get("habis"):
        fakta.append({"label": "Perkiraan habis", "nilai": f"±{tgl(d['habis'])}"})
    for p in d["penyumbang"]:
        fakta.append({"label": f"Penyumbang: {p['nama']}", "nilai": f"{rp_penuh(p['jumlah'])} ({persen(p['porsi'])})"})
    if d["tagihan_sisa"] > 0:
        fakta.append({"label": "Tagihan belum dibayar", "nilai": rp_penuh(d["tagihan_sisa"])})
    for a in d["tagihan_minus"]:
        fakta.append({"label": f"Amplop tagihan minus: {a['nama']}", "nilai": rp_penuh(a["sisa"])})
    _fakta_batas(fakta, d, ctx)
    return {"chip": chip, "judul": f"Rem belanja harian ke {rp_ringkas(d['j1'] or 0)}", "isi": isi, "fakta": fakta}


def _per02(ins, ctx, kpi):
    d = ins.data
    if d["r"] > 0:
        isi = f"Sisa bebas amplop belanja kurang {rp_penuh(d['minus'])}, padahal masih {d['r']} hari sampai {tgl(d['pe'])}."
    else:
        isi = f"Sisa bebas amplop belanja kurang {rp_penuh(d['minus'])} di hari terakhir periode."
    fakta = [{"label": f"Minus: {a['nama']}", "nilai": rp_penuh(a["sisa"])} for a in d["amplop_minus"]]
    if d["tagihan_sisa"] > 0:
        fakta.append({"label": "Tagihan belum dibayar", "nilai": rp_penuh(d["tagihan_sisa"])})
    return {"chip": f"Minus {rp_ringkas(d['minus'])}", "judul": f"Dana belanja sudah minus {rp_ringkas(d['minus'])}",
            "isi": isi, "fakta": fakta}


def _per03(ins, ctx, kpi):
    d = ins.data
    x, y = persen(d["persen_dana"]), persen(d["persen_waktu"])
    return {"chip": f"{x} dana, {y} waktu", "judul": "Belanja lebih cepat dari waktu",
            "isi": f"Belanja harian sudah {x} dari dana belanja, padahal periode baru berjalan {y}.",
            "fakta": [{"label": "Hari ke", "nilai": f"{d['hari_ke']} dari {d['hari_total']}"}]}


def _per04(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"Laju turun {persen(d['turun'])}", "judul": "Laju belanja membaik",
            "isi": f"Kalau bertahan, cukup sampai {tgl(d['pe'])} dengan sisa ±{rp_ringkas(d['sisa'])}.",
            "fakta": [{"label": "Rata-rata 7 hari terakhir", "nilai": f"{rp_penuh(d['laju7'])}/hari"},
                      {"label": "Rata-rata sejak awal periode", "nilai": f"{rp_penuh(d['laju_periode'])}/hari"}]}


def _per05(ins, ctx, kpi):
    d = ins.data
    fakta = [{"label": "Rata-rata 7 hari terakhir", "nilai": f"{rp_penuh(d['t4'])}/hari"}]
    if d.get("j1") is not None:
        fakta.append({"label": f"Aman {d['r']} hari ke depan", "nilai": f"{rp_penuh(d['j1'])}/hari"})
    return {"chip": "Sesuai jalur" if kpi == "terpakai" else f"Cukup s/d {tgl(d['pe'])}",
            "judul": "Cukup sampai akhir periode",
            "isi": f"Perkiraan sisa ±{rp_ringkas(d['sisa'])} di akhir periode.", "fakta": fakta}


def _per06(ins, ctx, kpi):
    d = ins.data
    if d["non_rollover"]:
        nama = ", ".join(a["nama"] for a in d["non_rollover"])
        isi = f"{rp_penuh(d['hangus'])} di {nama} akan kembali ke 0 saat periode berganti."
    else:
        isi = f"Perkiraan sisa ±{rp_ringkas(d['jumlah'])} di akhir periode {tgl(d['pe'])}."
    fakta = [{"label": f"Sisa {a['nama']}", "nilai": rp_penuh(a["bebas"])} for a in d["non_rollover"]]
    return {"chip": f"Sisa ±{rp_ringkas(d['jumlah'])}",
            "judul": f"Sisa ±{rp_ringkas(d['jumlah'])} — pindahkan ke tabungan?", "isi": isi, "fakta": fakta}


def _per07(ins, ctx, kpi):
    d = ins.data
    lalu = d.get("lalu")
    bagian = []
    if lalu:
        if lalu["minus"]:
            bagian.append(f"{lalu['minus']} amplop minus")
        if lalu["tambalan"]:
            bagian.append(f"ditambal {lalu['tambalan']}×")
        if lalu.get("terbesar_nama"):
            bagian.append(f"terbesar {lalu['terbesar_nama']}")
    judul = "Periode baru: " + ", ".join(bagian) if bagian else "Periode baru dimulai"
    fakta = []
    if lalu and lalu.get("terbesar_nama"):
        fakta.append({"label": f"Terpakai terbesar periode lalu: {lalu['terbesar_nama']}",
                      "nilai": rp_penuh(lalu["terbesar"])})
    return {"chip": "Periode baru", "judul": judul,
            "isi": f"Periode {tgl(d['ps'])} – {tgl(d['pe'])} baru berjalan {d['hari_ke']} hari. "
                   "Proyeksi muncul mulai hari ke-3.",
            "fakta": fakta}


# ── C. Amplop ───────────────────────────────────────────────────────────
def _amp01(ins, ctx, kpi):
    d = ins.data
    tambal = f", sudah ditambal {d['tambalan_n']}×" if d["tambalan_n"] else ""
    return {"chip": f"Minus {rp_ringkas(d['minus'])}", "judul": f"Tutup minus {d['nama']} {rp_ringkas(d['minus'])}",
            "isi": f"Lewat {rp_penuh(d['minus'])} dari dananya{tambal}.",
            "fakta": [{"label": "Dana periode ini", "nilai": rp_penuh(d["dana"])},
                      {"label": "Terpakai", "nilai": rp_penuh(d["terpakai"])}]}


def _amp_fakta(d, ctx) -> list:
    fakta = [{"label": "Sisa bebas", "nilai": rp_penuh(d["bebas"])},
             {"label": "Rata-rata belanja", "nilai": f"{rp_penuh(d['laju'])}/hari"},
             {"label": f"Perlu sampai {tgl(d['pe'])}", "nilai": f"±{rp_penuh(d['perlu'])}"}]
    if d.get("batas") is not None and d["bebas"] > 0:
        fakta.append({"label": "Maksimal per hari", "nilai": f"{rp_penuh(d['batas'])}/hari"})
    return fakta


def _amp02(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Habis", "judul": f"Geser ±{rp_ringkas(d['kurang'])} ke {d['nama']}",
            "isi": f"{d['nama']} sudah habis. Perlu ±{rp_penuh(d['perlu'])} sampai {tgl(d['pe'])}.",
            "fakta": _amp_fakta(d, ctx)}


def _amp03(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"Habis ±{tgl(d['habis'])}",
            "judul": f"{d['nama']}: maksimal {rp_ringkas(d.get('batas') or 0)}/hari",
            "isi": f"Kalau tetap {rp_ringkas(d['laju'])}/hari, {d['nama']} habis ±{tgl(d['habis'])} "
                   f"dan kurang ±{rp_ringkas(d['kurang'])} sebelum {tgl(d['pe'])}.",
            "fakta": _amp_fakta(d, ctx)}


def _amp04(ins, ctx, kpi):
    d = ins.data
    sumber = d["sumber"]
    kalimat = [f"Jatah awal {rp_penuh(d['jatah_awal'])}"]
    if d.get("kebutuhan"):
        kalimat[0] += f", kebutuhannya ±{rp_penuh(d['kebutuhan'])} per periode."
    else:
        kalimat[0] += "."
    if sumber:
        nama = sumber[0]["nama"] or "amplop lain"
        kata = "semuanya dari" if len(sumber) == 1 else "terbesar dari"
        menipis = ", yang juga menipis" if sumber[0]["menipis"] else ""
        kalimat.append(f"Total tambalan {rp_penuh(d['total'])} ({d['n']}×), {kata} {nama}{menipis}.")
    else:
        kalimat.append(f"Total tambalan {rp_penuh(d['total'])} ({d['n']}×).")
    fakta = [{"label": f"Tambalan dari {x['nama'] or 'amplop lain'}", "nilai": rp_penuh(x["jumlah"])} for x in sumber]
    if d.get("saran"):
        fakta.append({"label": f"Saran jatah mulai {tgl(d['mulai'])}", "nilai": rp_penuh(d["saran"])})
    return {"chip": f"Ditambal {d['n']}×", "judul": f"{d['nama']} ditambal {d['n']}× — jatahnya kekecilan",
            "isi": _kalimat(*kalimat), "fakta": fakta}


def _amp05(ins, ctx, kpi):
    d = ins.data
    if d["alasan"] == "tambalan":
        isi = f"{d['periode_ditambal']} dari 3 periode terakhir ditambal berulang; terpakai rata-rata {rp_penuh(d['median'])}."
    else:
        isi = f"3 periode terakhir terpakai rata-rata {rp_penuh(d['median'])}, jatahnya {rp_penuh(d['jatah'])}."
    return {"chip": "Jatah kekecilan", "judul": f"Naikkan jatah {d['nama']} ke {rp_ringkas(d['saran'])}",
            "isi": isi, "fakta": [{"label": "Terpakai rata-rata (median 3 periode)", "nilai": rp_penuh(d["median"])},
                                  {"label": "Jatah", "nilai": rp_penuh(d["jatah"])}]}


def _amp06(ins, ctx, kpi):
    d = ins.data
    sisa = f", sisanya ke {d['tabungan']}" if d.get("tabungan") else ""
    return {"chip": "Jatah kebesaran", "judul": f"Turunkan jatah {d['nama']} ke {rp_ringkas(d['saran'])}{sisa}",
            "isi": f"3 periode terakhir hanya terpakai rata-rata {persen(d['porsi'])} dari jatah.",
            "fakta": [{"label": "Terpakai rata-rata (median 3 periode)", "nilai": rp_penuh(d["median"])},
                      {"label": "Jatah", "nilai": rp_penuh(d["jatah"])}]}


def _amp07(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Jarang terpakai", "judul": f"{d['nama']} jarang terpakai periode ini",
            "isi": f"Baru terpakai {rp_penuh(d['terpakai'])} dari {rp_penuh(d['dana'])}.",
            "fakta": [{"label": "Sisa bebas", "nilai": rp_penuh(d["bebas"])}]}


def _amp08(ins, ctx, kpi):
    d = ins.data
    chip = f"{rasio(d['kali'])} biasanya" if d.get("kali") else "Lonjakan"
    return {"chip": chip, "judul": f"{d['nama']} melonjak {rasio(d['kali']) if d.get('kali') else ''}".strip(),
            "isi": f"{d['nama']} 7 hari terakhir {rp_penuh(d['v7'])}, biasanya {rp_penuh(d['median'])}.",
            "fakta": [{"label": "7 hari terakhir", "nilai": rp_penuh(d["v7"])},
                      {"label": "Biasanya per 7 hari", "nilai": rp_penuh(d["median"])}]}


def _amp09(ins, ctx, kpi):
    d = ins.data
    isi = f"Jatahnya {rp_penuh(d['jatah'])}, tapi belum ada dana periode ini."
    if d["tagihan"]:
        isi += " Ada tagihan di amplop ini."
    return {"chip": "Belum didanai", "judul": f"Alokasikan {rp_ringkas(d['jatah'])} ke {d['nama']}", "isi": isi,
            "fakta": []}


def _amp10(ins, ctx, kpi):
    d = ins.data
    fakta = [{"label": "Batas sekarang", "nilai": f"{rp_penuh(d['batas_lama'])}/hari"}]
    _fakta_batas(fakta, d, ctx)
    return {"chip": f"Batas lewat {d['n']}×", "judul": f"Batas harian {d['nama']} sering terlewat",
            "isi": f"Batas {rp_penuh(d['batas_lama'])}/hari terlewat {d['n']} dari {d['hari']} hari; "
                   f"rata-rata belanjanya {rp_penuh(d['rata'])}.", "fakta": fakta}


def _amp11(ins, ctx, kpi):
    d = ins.data
    tanda = "+" if d["arah"] == "naik" else MINUS
    x = persen(abs(d["persen"]))
    return {"chip": f"{tanda}{x} vs lalu", "judul": f"{d['nama']} {tanda}{x} dibanding periode lalu",
            "isi": f"{tanda}{x} dibanding periode lalu di hari yang sama.",
            "fakta": [{"label": "Periode ini", "nilai": rp_penuh(d["terpakai"])},
                      {"label": "Periode lalu, hari yang sama", "nilai": rp_penuh(d["lalu"])}]}


# ── D. Tagihan ──────────────────────────────────────────────────────────
def _tag_fakta(d) -> list:
    fakta = [{"label": "Nominal", "nilai": rp_penuh(d["nominal"])},
             {"label": "Jatuh tempo", "nilai": tgl(d["jatuh_tempo"])},
             {"label": f"Sisa amplop {d['amplop']}", "nilai": rp_penuh(d["sisa_amplop"])}]
    if d["perlu"] > 0:
        fakta.append({"label": "Perlu digeser", "nilai": rp_penuh(d["perlu"])})
    return fakta


def _tag_kurang(d) -> str:
    if d["perlu"] <= 0:
        return ""
    kata = "minus" if d["sisa_amplop"] < 0 else "sisa"
    return f"Amplop {d['amplop']} {kata} {rp_penuh(abs(d['sisa_amplop']))}, jadi perlu {rp_penuh(d['perlu'])}."


def _tag01(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{d['nama']} telat {d['telat']} hari", "judul": f"Lunasi {d['nama']} — telat {d['telat']} hari",
            "isi": _kalimat(f"{rp_penuh(d['nominal'])}, jatuh tempo {tgl(d['jatuh_tempo'])}.", _tag_kurang(d)),
            "fakta": _tag_fakta(d)}


def _tag02(ins, ctx, kpi):
    d = ins.data
    kapan = "hari ini" if d["lagi"] == 0 else f"{d['lagi']} hari lagi"
    return {"chip": f"{d['nama']} {kapan}", "judul": f"Siapkan {d['nama']} — jatuh tempo {kapan}",
            "isi": _kalimat(f"{rp_penuh(d['nominal'])}, jatuh tempo {tgl(d['jatuh_tempo'])}.", _tag_kurang(d)),
            "fakta": _tag_fakta(d)}


def _tag03(ins, ctx, kpi):
    d = ins.data
    kapan = "hari ini" if d["lagi"] == 0 else f"{d['lagi']} hari lagi"
    return {"chip": f"{d['nama']} {kapan}", "judul": f"Bayar {d['nama']} — jatuh tempo {kapan}",
            "isi": f"{rp_penuh(d['nominal'])}, dana di {d['amplop']} cukup.", "fakta": _tag_fakta(d)}


def _tag04(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{d['nama']} {tgl(d['jatuh_tempo'])}", "judul": f"Siapkan {d['nama']} tahunan",
            "isi": f"Butuh {rp_penuh(d['nominal'])} pada {tgl(d['jatuh_tempo'])}; terkumpul {rp_penuh(d['terkumpul'])}. "
                   f"Sisihkan {rp_penuh(d['per_bulan'])}/bulan.",
            "fakta": [{"label": "Kurang", "nilai": rp_penuh(d["kurang"])}]}


def _tag05(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"Tagihan {persen(d['beban'])}", "judul": "Tinjau langganan — beban tagihan tinggi",
            "isi": f"Tagihan rutin {rp_penuh(d['per_bulan'])}/bulan, {persen(d['beban'])} dari dana belanja.",
            "fakta": [{"label": "Dana belanja", "nilai": rp_penuh(d["dana"])}]}


def _tag06(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Nominal berubah", "judul": f"Perbarui nominal {d['nama']} jadi {rp_ringkas(d['dibayar'])}",
            "isi": f"Pembayaran terakhir {rp_penuh(d['dibayar'])}, tercatat {rp_penuh(d['nominal'])}.",
            "fakta": [{"label": "Selisih", "nilai": rp_penuh(d["selisih"])}]}


FREKUENSI = {"weekly": "mingguan", "monthly": "bulanan", "yearly": "tahunan", "biweekly": "dua mingguan",
             "quarterly": "tiga bulanan"}


def _tag07(ins, ctx, kpi):
    d = ins.data
    frek = FREKUENSI.get(d["frekuensi"], d["frekuensi"])
    return {"chip": "Pola rutin", "judul": f"Jadikan {d['deskripsi']} langganan {frek}",
            "isi": f"{d['deskripsi']} {rp_penuh(d['nominal'])} tercatat {d['kemunculan']}× dengan pola {frek}.",
            "fakta": ([{"label": "Perkiraan berikutnya", "nilai": tgl(d["berikutnya"])}] if d.get("berikutnya") else [])}


def _tag08(ins, ctx, kpi):
    d = ins.data
    nama = " dan ".join(d["nama"])
    return {"chip": "Langganan ganda", "judul": f"Cek langganan ganda: {nama}",
            "isi": "Dua langganan aktif mirip nama dan nominalnya.",
            "fakta": [{"label": n, "nilai": rp_penuh(j)} for n, j in zip(d["nama"], d["jumlah"])]}


def _tag09(ins, ctx, kpi):
    d = ins.data
    if not d["ada"]:
        return {"chip": "Tidak ada tagihan", "judul": "Belum ada tagihan rutin",
                "isi": "Belum ada langganan aktif.", "fakta": []}
    b = d.get("berikut")
    if b:
        return {"chip": f"Berikutnya {b['nama']} {tgl(b['tanggal'])}", "judul": "Tagihan aman",
                "isi": f"Berikutnya {b['nama']} {rp_penuh(b['nominal'])} pada {tgl(b['tanggal'])}.",
                "fakta": [{"label": "Belum dibayar periode ini", "nilai": rp_penuh(d["sisa"])}]}
    return {"chip": "Lunas semua", "judul": "Semua tagihan periode ini lunas",
            "isi": f"Tidak ada tagihan tersisa sampai {tgl(d['pe'])}.", "fakta": []}


# ── E. Pemasukan ────────────────────────────────────────────────────────
def _inc01(ins, ctx, kpi):
    d = ins.data
    isi = f"Biasanya masuk sekitar tgl {d['hari_biasa'].day}"
    isi += f", ±{rp_ringkas(d['biasa'])}." if d.get("biasa") else "."
    return {"chip": "Belum masuk", "judul": "Catat pemasukan periode ini", "isi": isi,
            "fakta": [{"label": "Lewat dari biasanya", "nilai": f"{d['telat']} hari"}]}


def _inc02(ins, ctx, kpi):
    d = ins.data
    fakta = [{"label": f"Masuk ke amplop bersama dari {d['nama']}", "nilai": rp_penuh(d["jumlah"])}] \
        if d.get("jumlah") else []
    return {"chip": f"Terisi dari {d['nama']}", "judul": f"Amplop bersama terisi dari {d['nama']}",
            "isi": f"Belum ada pemasukan atas namamu, tapi amplop bersama sudah terisi dari pemasukan {d['nama']}. "
                   "Tidak perlu dicatat ulang.", "fakta": fakta}


def _inc03(ins, ctx, kpi):
    d = ins.data
    kurang = f" ({MINUS}{persen(d['persen'])})" if d.get("persen") is not None else ""
    return {"chip": f"{MINUS}{persen(d['persen'])} dari biasa" if d.get("persen") is not None else "Lebih kecil",
            "judul": "Sesuaikan alokasi dengan pemasukan baru",
            "isi": f"Pemasukan periode ini {rp_penuh(d['pemasukan'])}, biasanya {rp_penuh(d['biasa'])}{kurang}.",
            "fakta": [{"label": "Kurang dari biasa", "nilai": rp_penuh(d["kurang"])}]}


def _inc04(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{rp_ringkas(d['jumlah'])} belum dibagi", "judul": f"Bagi {rp_ringkas(d['jumlah'])} ke amplop",
            "isi": f"{rp_penuh(d['jumlah'])} dari pemasukanmu belum dibagi ke amplop.", "fakta": []}


def _inc05(ins, ctx, kpi):
    d = ins.data
    if d["rate"] is None:
        if d["kosong"]:
            return {"chip": "Belum ada pemasukan", "judul": "Belum ada pemasukan periode ini",
                    "isi": "Catat pemasukan supaya bisa dibagi ke amplop.", "fakta": []}
        return {"chip": "Belum ada atas namamu", "judul": "Belum ada pemasukan atas namamu",
                "isi": "Pemasukan rumah tangga sudah tercatat.", "fakta": []}
    fakta = [{"label": "Pemasukanmu periode ini", "nilai": rp_penuh(d["pemasukan"])}]
    if d.get("median") is not None:
        fakta.append({"label": "Saving rate biasanya", "nilai": persen(d["median"])})
    isi = f"{persen(d['rate'])} pemasukanmu masuk ke tabungan."
    if d["turun"]:
        isi += f" Biasanya {persen(d['median'])}."
    return {"chip": f"Saving rate {persen(d['rate'])}", "judul": "Saving rate periode ini", "isi": isi, "fakta": fakta}


def _inc06(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Gajian bergeser", "judul": f"Ubah Tanggal Gajian ke tgl {d['tanggal']}?",
            "isi": f"2 dari 3 periode terakhir pemasukan masuk sekitar tgl {d['tanggal']}, "
                   f"sedangkan pengaturan tgl {d['payday_day']}.", "fakta": []}


# ── F. Tabungan ─────────────────────────────────────────────────────────
TUNDA = "Sisa bebas periode ini sedang kurang, jadi setoran dijadwalkan periode depan."


def bulan(v) -> str:
    return f"{_d(v).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}".replace(".", ",") + " bln"


def _tab01(ins, ctx, kpi):
    d = ins.data
    if d["ada_target"] and d.get("progres") is not None:
        chip = f"Darurat {persen(d['progres'])}"
        isi = f"{rp_penuh(d['saldo'])} dari {rp_penuh(d['target'])}; setara {bulan(d['cakupan'])} belanja."
    else:
        chip = f"Darurat {bulan(d['cakupan'])}"
        isi = f"{rp_penuh(d['saldo'])}, setara {bulan(d['cakupan'])} belanja."
    if ins.tone == "ok":
        judul = f"{d['nama']} cukup {bulan(d['cakupan'])}"
    elif d.get("progres") is not None:
        judul = f"{d['nama']} baru {persen(d['progres'])}"
    else:
        judul = f"{d['nama']} baru {bulan(d['cakupan'])}"
    if d["tunda"] and ins.tone != "ok":
        isi = _kalimat(isi, TUNDA)
    fakta = [{"label": "Saldo", "nilai": rp_penuh(d["saldo"])}, {"label": "Target", "nilai": rp_penuh(d["target"])}]
    if d["saran"] > 0:
        fakta.append({"label": "Setoran saran per bulan", "nilai": rp_penuh(d["saran"])})
    return {"chip": chip, "judul": judul, "isi": isi, "fakta": fakta}


def _tab02(ins, ctx, kpi):
    d = ins.data
    isi = f"Perlu {rp_penuh(d['butuh'])}/bulan sampai {tgl(d['tenggat'])}, biasanya {rp_penuh(d['biasa'])}."
    if d["tunda"]:
        isi = _kalimat(isi, TUNDA)
    return {"chip": f"{d['nama']} tertinggal", "judul": f"Kejar target {d['nama']}", "isi": isi,
            "fakta": [{"label": "Kurang periode ini", "nilai": rp_penuh(d["kurang"])}]}


def _tab03(ins, ctx, kpi):
    d = ins.data
    isi = f"Dua periode terakhir belum ada setoran ke {d['nama']}."
    if d["tunda"]:
        isi = _kalimat(isi, TUNDA)
    return {"chip": "Belum disetor", "judul": f"Setor ke {d['nama']}", "isi": isi,
            "fakta": [{"label": "Saldo", "nilai": f"{rp_penuh(d['saldo'])} dari {rp_penuh(d['target'])}"},
                      {"label": "Setoran saran per bulan", "nilai": rp_penuh(d["saran"])}]}


def _tab04(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"Kurang {rp_ringkas(d['kurang'])}", "judul": f"{d['nama']} hampir tercapai",
            "isi": f"Sudah {persen(d['progres'])}: {rp_penuh(d['saldo'])} dari {rp_penuh(d['target'])}.", "fakta": []}


def _tab05(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{d['nama']} tercapai", "judul": f"Target {d['nama']} tercapai",
            "isi": f"{rp_penuh(d['saldo'])} dari target {rp_penuh(d['target'])}.", "fakta": []}


def _tab06(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{d['n']} target paralel", "judul": "Atur prioritas target",
            "isi": f"Setoran tersebar ke {d['n']} target, jadi yang terpenting naik pelan.",
            "fakta": [{"label": "Progres tengah", "nilai": persen(d["median"])}]}


def _tab07(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"+{rp_ringkas(d['setoran'])} periode ini", "judul": "Setoran tabungan periode ini",
            "isi": f"Setoran periode ini {rp_penuh(d['setoran'])}; total tabungan {rp_penuh(d['saldo'])}.",
            "fakta": []}


# ── G. Kebersihan data ──────────────────────────────────────────────────
def _dat01(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Cocokkan saldo", "judul": "Cocokkan saldo",
            "isi": f"Terakhir {d['hari']} hari lalu, sudah {d['n']} transaksi sejak itu.", "fakta": []}


def _dat02(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Selisih besar", "judul": "Cocokkan saldo lebih sering",
            "isi": f"Cocokkan terakhir selisih {rp_penuh(d['selisih'])}. Cocokkan lebih sering supaya analisa tetap akurat.",
            "fakta": [{"label": "Tanggal", "nilai": tgl(d["tanggal"])}]}


def _dat03(ins, ctx, kpi):
    d = ins.data
    if d["jenis"] == "struk":
        return {"chip": "Struk dobel?", "judul": f"Struk {d['toko']} sepertinya tercatat dua kali ({d['n']} barang)",
                "isi": f"Dua struk {d['toko']} yang sama tercatat berdekatan, total {rp_penuh(d['total'])}.",
                "fakta": [{"label": "Diduga dobel", "nilai": rp_penuh(d["total"])}]}
    return {"chip": "Dobel?", "judul": f"{d['deskripsi']} {rp_ringkas(d['jumlah'])} tercatat {d['n']}×",
            "isi": f"{d['n']} transaksi {d['deskripsi']} {rp_penuh(d['jumlah'])} di {d['amplop']} tercatat berdekatan.",
            "fakta": [{"label": "Diduga dobel", "nilai": rp_penuh(d["total"])}]}


def _dat04(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Lupa catat?", "judul": "Catat belanja yang terlewat",
            "isi": f"Sudah {d['hari']} hari tanpa catatan, padahal biasanya kamu mencatat hampir setiap hari.",
            "fakta": []}


def _dat05(ins, ctx, kpi):
    d = ins.data
    return {"chip": "Belum diklasifikasi", "judul": f"Klasifikasikan {d['n']} amplop",
            "isi": "Klasifikasi membantu AI memilih sumber dana yang aman.",
            "fakta": [{"label": "Amplop", "nilai": ", ".join(d["nama"])}]}


def _dat06(ins, ctx, kpi):
    d = ins.data
    return {"chip": f"{d['nama']} sudah dibayar?", "judul": f"Tandai {d['nama']} lunas",
            "isi": f"Transaksi {d['deskripsi']} {rp_penuh(d['jumlah'])} nominalnya sama dengan tagihan {d['nama']}. "
                   "Sisa bebas sudah menghitungnya lunas, tapi tagihannya masih tercatat belum dibayar.",
            "fakta": []}


TEMPLATE = {
    "HAR-01": _har01, "HAR-02": _har02, "HAR-03": _har03, "HAR-04": _har04, "HAR-05": _har05,
    "PER-01": _per01, "PER-02": _per02, "PER-03": _per03, "PER-04": _per04, "PER-05": _per05,
    "PER-06": _per06, "PER-07": _per07,
    "AMP-01": _amp01, "AMP-02": _amp02, "AMP-03": _amp03, "AMP-04": _amp04, "AMP-05": _amp05, "AMP-06": _amp06,
    "AMP-07": _amp07, "AMP-08": _amp08, "AMP-09": _amp09, "AMP-10": _amp10, "AMP-11": _amp11,
    "TAG-01": _tag01, "TAG-02": _tag02, "TAG-03": _tag03, "TAG-04": _tag04, "TAG-05": _tag05, "TAG-06": _tag06,
    "TAG-07": _tag07, "TAG-08": _tag08, "TAG-09": _tag09,
    "INC-01": _inc01, "INC-02": _inc02, "INC-03": _inc03, "INC-04": _inc04, "INC-05": _inc05, "INC-06": _inc06,
    "TAB-01": _tab01, "TAB-02": _tab02, "TAB-03": _tab03, "TAB-04": _tab04, "TAB-05": _tab05, "TAB-06": _tab06,
    "TAB-07": _tab07,
    "DAT-01": _dat01, "DAT-02": _dat02, "DAT-03": _dat03, "DAT-04": _dat04, "DAT-05": _dat05, "DAT-06": _dat06,
}


# ── aksi ────────────────────────────────────────────────────────────────
def _label_aksi(a: dict, ins: Insight, ctx: Konteks) -> tuple[str, dict]:
    kode, p = a.get("kode"), dict(a.get("payload") or {})
    if kode == "batas_harian":
        return f"Batas harian {ctx.nama.get(p.get('amplop_id'), '')} {rp_ringkas(p.get('jumlah', 0))}", p
    if kode == "pindah_tabungan":
        return f"Pindahkan ke {ins.data.get('tujuan', 'tabungan')}", p
    if kode in ("setor", "setor_darurat", "setor_sisanya"):
        jumlah = (p.get("kebutuhan") or [{}])[0].get("jumlah", 0)
        nama = ins.data.get("nama", "")
        teks_ = {"setor": f"Setor {rp_ringkas(jumlah)}", "setor_darurat": f"Setor {rp_ringkas(jumlah)} ke {nama}",
                 "setor_sisanya": f"Setor sisanya {rp_ringkas(jumlah)}"}[kode]
        return teks_, p
    if kode in ("geser_amplop", "geser_sisa_periode", "geser_sekarang"):
        jumlah = (p.get("kebutuhan") or [{}])[0].get("jumlah", 0)
        return f"Geser {rp_ringkas(jumlah)}", p
    if kode == "geser_bayar":
        return f"Geser & bayar {ins.data.get('nama', '')}", p
    if kode in ("naikkan_jatah", "turunkan_jatah"):
        kata = "Naikkan" if kode == "naikkan_jatah" else "Turunkan"
        mulai = f" mulai {tgl(ins.data['mulai'])}" if ins.data.get("mulai") else ""
        return f"{kata} jatah jadi {rp_ringkas(p.get('jumlah', 0))}{mulai}", p
    if kode == "sesuaikan_batas":
        return f"Sesuaikan batas jadi {rp_ringkas(p.get('jumlah', 0))}", p
    if kode == "tanya_hari_ini":
        return "Tanya di chat", {"teks": "Kenapa belanja hari ini lewat jatah?", **p}
    if kode == "tanya_kekurangan":
        return "Tanya di chat", {"teks": "Kenapa dana belanja kurang?", **p}
    if kode == "hapus_duplikat":
        return f"Hapus duplikat ({len(p.get('txn_ids') or [])} barang)", p
    return LABEL.get(kode, kode or a["kind"]), p


LABEL = {
    "lihat_transaksi_hari_ini": "Lihat transaksi hari ini",
    "catat_pemasukan": "Catat pemasukan",
    "tutup_minus": "Tutup minus",
    "bagi_pemasukan": "Bagi pemasukan",
    "lihat_periode_lalu": "Lihat periode lalu",
    "catat": "Catat",
    "tutup_minus_amplop": "Tutup minus",
    "lihat_transaksi_amplop": "Lihat transaksi",
    "alokasikan": "Alokasikan",
    "biarkan": "Biarkan",
    "bayar": "Bayar sekarang",
    "bayar_saja": "Bayar saja",
    "atur_sisihan": "Atur sisihan",
    "tinjau_langganan": "Tinjau langganan",
    "perbarui_nominal": "Perbarui nominal",
    "jadikan_langganan": "Jadikan langganan",
    "lihat_keduanya": "Lihat keduanya",
    "ingatkan_besok": "Ingatkan besok",
    "catat_pemasukanku": "Catat pemasukanku",
    "sesuaikan_alokasi": "Sesuaikan alokasi",
    "bagi_sekarang": "Bagi sekarang",
    "ubah_tanggal_gajian": "Ubah Tanggal Gajian",
    "rencanakan_alokasi": "Rencanakan di alokasi berikutnya",
    "lihat_target": "Lihat target",
    "mundurkan_tenggat": "Mundurkan tenggat",
    "atur_prioritas": "Atur prioritas",
    "cocokkan_saldo": "Cocokkan saldo",
    "hapus_salah_satu": "Hapus salah satu",
    "bukan_dobel": "Bukan dobel",
    "klasifikasikan": "Klasifikasikan",
    "tandai_lunas": "Tandai lunas",
    "bukan_tagihan": "Bukan pembayaran tagihan",
}


# ── insight → JSON kontrak ──────────────────────────────────────────────
def _dasar(ins: Insight) -> dict:
    if ins.dasar_hari:
        teks = f"Dari {ins.dasar_hari} hari data"
    elif ins.domain == "HAR":
        teks = "Dari catatan hari ini"
    else:
        teks = "Dari data periode ini"
    return {"teks": teks, "keyakinan": ins.keyakinan}


def _kemungkinan(isi: str) -> str:
    return f"Kemungkinan: {isi[0].lower()}{isi[1:]}" if isi else isi


def teks(ins: Insight, ctx: Konteks, kpi: str | None = None) -> dict:
    out = TEMPLATE[ins.aturan](ins, ctx, kpi)
    if ins.keyakinan == "rendah":
        out["isi"] = _kemungkinan(out["isi"])
    return out


def judul_pendek(ins: Insight, ctx: Konteks) -> str:
    return teks(ins, ctx)["judul"]


def render_insight(ins: Insight, ctx: Konteks, kpi: str | None = None) -> dict:
    t = teks(ins, ctx, kpi)
    aksi = []
    for a in ins.aksi:
        label, payload = _label_aksi(a, ins, ctx)
        aksi.append({"kind": a["kind"], "label": label, "payload": payload})
    out = {
        "id": ins.id, "aturan": ins.aturan, "tone": ins.tone, "chip": t["chip"], "judul": t["judul"],
        "isi": t["isi"], "fakta": t["fakta"], "aksi": aksi, "dasar": _dasar(ins),
        "dismiss": {"kunci": ins.id, "pilihan": list(DISMISS_PILIHAN)},
        "skor": float(round(ins.skor, 1)),
    }
    if ins.rincian:
        out["rincian"] = [{"id": r.id, "aturan": r.aturan, "judul": teks(r, ctx)["judul"], "isi": teks(r, ctx)["isi"]}
                          for r in ins.rincian]
    return out


# ── grafik harian (§7) ──────────────────────────────────────────────────
def baris_dasar_amplop(d: dict) -> dict:
    """Strip halaman Amplop (§7 "Halaman lain: Amplop") bila tidak ada insight untuk amplop itu.
    `d` dari `halaman.dasar_amplop`: jenis `aman` (belanja, bebas > 0), `terpakai` (belanja,
    bebas ≤ 0 tanpa aturan yang menyala), atau `tabungan`. Bentuk sama dengan `render_insight`
    tanpa dismiss (bukan aturan, tidak bisa disembunyikan)."""
    nama, jenis = d["nama"], d["jenis"]
    aksi = []
    if jenis == "aman":
        jumlah = rp_ringkas(d["batas"])
        judul = f"Aman, {jumlah} tersedia hari ini" if d["hari_terakhir"] else f"Aman, ±{jumlah}/hari tersedia"
        out = {"tone": "ok", "chip": "Aman", "judul": judul,
               "isi": f"Sisa bebas {rp_penuh(d['bebas'])} sampai {tgl(d['pe'])}.",
               "fakta": [{"label": "Sisa bebas", "nilai": rp_penuh(d["bebas"])},
                         {"label": "Maksimal per hari", "nilai": f"{rp_penuh(d['batas'])}/hari"}]}
    elif jenis == "terpakai":
        out = {"tone": "info", "chip": "Terpakai semua", "judul": f"Dana {nama} sudah terpakai semua",
               "isi": f"Sisa bebas {rp_penuh(d['bebas'])} sampai {tgl(d['pe'])}.",
               "fakta": [{"label": "Sisa bebas", "nilai": rp_penuh(d["bebas"])}]}
        aksi.append({"kind": "fund", "label": "Isi dana", "payload": {"amplop_id": d["amplop_id"]}})
    else:
        saldo = rp_ringkas(d["saldo"])
        out = {"tone": "ok", "chip": f"Saldo {saldo}", "judul": f"{nama}: saldo {saldo}",
               "isi": "Sesuai rencana." if d["ada_target"] else "Tambahkan target biar terarah.",
               "fakta": [{"label": "Saldo", "nilai": rp_penuh(d["saldo"])}]}
        if d["boleh_setor"]:
            aksi.append({"kind": "fund", "label": "Setor", "payload": {"amplop_id": d["amplop_id"]}})
    return {"id": None, "aturan": None, **out, "aksi": aksi,
            "dasar": {"teks": "Dari data periode ini", "keyakinan": "tinggi"}, "dismiss": None}


def teks_grafik(m, s) -> dict:
    """Baris analisa grafik: S6 "{n} dari 7 hari terakhir lewat jatah" + puncaknya."""
    akhir = m.harian[-7:]
    if not akhir:
        return {"teks": "", "aksi": None}
    mulai = akhir[0]["tanggal"]
    lewat = [h for h in s.lewat_jatah if mulai <= h["tanggal"] <= m.today]
    if not lewat:
        return {"teks": "Semua hari dalam jatah minggu ini", "aksi": None}
    puncak = max(lewat, key=lambda h: (h["variabel"], h["tanggal"]))
    return {
        "teks": f"{len(lewat)} dari {len(akhir)} hari terakhir lewat jatah, tertinggi {hari_tgl(puncak['tanggal'])} "
                f"{rp_ringkas(puncak['variabel'])}",
        "aksi": {"kind": "route", "label": f"Lihat {tgl(puncak['tanggal'])}",
                 "payload": {"path": f"/transactions?date={puncak['tanggal'].isoformat()}"}},
    }


# ── perencana dana (§8): alasan per sumber ──────────────────────────────
ALASAN_RENCANA = {
    "a": "Amplop keinginan, masih lebih {surplus} sampai akhir periode",
    "b": "Kebutuhan, masih lebih {surplus} menurut belanja periode lalu",
    "c": "Cek dulu: belum ada riwayat belanja, perkiraan lebih {surplus}",
    "d": "Tabungan, dipakai karena kamu memilihnya",
    "e": "Dana darurat, dipakai karena kamu memilihnya",
}


def alasan_rencana(tingkat: str, surplus) -> str:
    return ALASAN_RENCANA[tingkat].format(surplus=rp_penuh(surplus))


# ── halaman Alokasi (§7, S14): alasan per amplop di rekomendasi ─────────
def alasan_alokasi(ins: Insight, ctx: Konteks) -> str:
    """Satu kalimat kenapa rekomendasi amplop ini disesuaikan (AMP-01/04/05/06, TAG-04, TAB-02)."""
    d = ins.data
    if ins.aturan == "AMP-01":
        return f"Menutup minus {rp_penuh(d['minus'])} periode ini dulu."
    if ins.aturan == "AMP-04":
        butuh = f"; kebutuhannya ±{rp_penuh(d['kebutuhan'])} per periode" if d.get("kebutuhan") else ""
        return f"Ditambal {d['n']}× periode ini{butuh}."
    if ins.aturan == "AMP-05":
        return f"3 periode terakhir terpakai rata-rata {rp_penuh(d['median'])}, di atas jatah {rp_penuh(d['jatah'])}."
    if ins.aturan == "AMP-06":
        return (f"3 periode terakhir hanya terpakai {persen(d['porsi'])} dari jatah; "
                f"cukup {rp_penuh(d['saran'])}.")
    if ins.aturan == "TAG-04":
        return f"Menyisihkan {rp_penuh(d['per_bulan'])}/bulan untuk {d['nama']} {tgl(d['jatuh_tempo'])}."
    if ins.aturan == "TAB-02":
        if d.get("tunda"):
            return f"Target {d['nama']} tertinggal, tapi didahulukan setelah sisa bebas tidak defisit."
        return f"Mengejar target {d['nama']}: perlu {rp_penuh(d['butuh'])}/bulan sampai {tgl(d['tenggat'])}."
    return teks(ins, ctx)["isi"]


# ── Telegram / chat (S9 memakai ini) ────────────────────────────────────
def teks_telegram(item: dict) -> str:
    """Insight yang sudah dirender → teks Telegram: 🔴 judul, lalu isi."""
    return f"{TONE_EMOJI.get(item['tone'], '')} {item['judul']}\n{item['isi']}".strip()


# ── Chat web & Telegram (S9) ────────────────────────────────────────────
# Balasan bot (`/status`, "sisa", "limit harian", "kapan habis", "pengeluaran hari ini",
# "kenapa …", "aman beli …") dan ringkasan harian/mingguan. Format HTML Telegram (sama di
# chat web, `format: html`); semua teks dari user (nama amplop, deskripsi) di-escape.
# Angka dari `Metrics` saja (paritas §13): KPI web, chat "sisa", /status, dan ringkasan
# harian memakai `blok_angka` yang sama.
GARIS = "─────────────────"


def _e(v) -> str:
    import html
    return html.escape("" if v is None else str(v), quote=False)


def _bar(bagian, total, lebar: int = 6) -> str:
    """▰▰▰▱▱▱ — rasio tampilan saja (bukan angka periode)."""
    total = _d(total)
    if total <= 0:
        return ""
    isi = round(min(max(float(_d(bagian) / total), 0.0), 1.0) * lebar)
    return "▰" * isi + "▱" * (lebar - isi)


def _emoji(ctx: Konteks, eid) -> str:
    env = next((e for e in ctx.snap.envelopes if e.id == eid), None)
    return (env.emoji if env and env.emoji else "📁")


def _amplop_label(ctx: Konteks, eid) -> str:
    return f"{_e(_emoji(ctx, eid))} {_e(ctx.nama.get(eid, '—'))}"


def periode_label(m) -> str:
    return f"{tgl(m.period_start)} – {tgl(m.period_end)}"


def teks_insight_html(item: dict, fakta: bool = False, rincian: bool = False) -> str:
    """Insight yang sudah dirender (`render_insight`) → HTML Telegram: 🔴 judul, isi,
    lalu (opsional) fakta = cara hitung, dan rincian = insight yang diserap."""
    baris = [f"{TONE_EMOJI.get(item['tone'], '')} <b>{_e(item['judul'])}</b>".strip()]
    if item.get("isi"):
        baris.append(_e(item["isi"]))
    if fakta and item.get("fakta"):
        baris.append("")
        baris += [f"• {_e(f['label'])}: <b>{_e(f['nilai'])}</b>" for f in item["fakta"]]
    if rincian and item.get("rincian"):
        baris.append("")
        baris.append("Rincian:")
        baris += [f"• {_e(r['judul'])} — {_e(r['isi'])}" for r in item["rincian"]]
    return "\n".join(baris)


def teks_chip_html(item: dict) -> str:
    """Satu baris chip KPI: 🟢 chip · judul."""
    return f"{TONE_EMOJI.get(item['tone'], '')} <b>{_e(item['chip'])}</b> · {_e(item['judul'])}".strip()


def blok_angka(ctx: Konteks) -> list[str]:
    """Angka KPI Beranda (paritas §13): dana belanja, terpakai, disisihkan tagihan,
    sisa bebas (T3), aman/hari (J1), jatah hari ini (J0) & belanja hari ini (T5).
    Dana − terpakai − disisihkan = sisa bebas."""
    m = ctx.m
    persen_ = f" {persen(m.terpakai_belanja / m.dana_belanja)}" if m.dana_belanja > 0 else ""
    baris = [
        f"Dana belanja  <b>{rp_penuh(m.dana_belanja)}</b>",
        f"Terpakai  <b>{rp_penuh(m.terpakai_belanja)}</b>  {_bar(m.terpakai_belanja, m.dana_belanja)}{persen_}".rstrip(),
    ]
    disisihkan = m.tagihan_sisa + m.sisihan
    if disisihkan > 0:
        baris.append(f"Disisihkan tagihan  <b>{rp_penuh(disisihkan)}</b>")
    baris.append(f"Sisa bebas  <b>{rp_penuh(m.sisa_bebas)}</b>")
    if m.j1 is not None:
        baris.append(f"Aman {m.sisa_hari} hari ke depan  <b>{rp_penuh(m.j1)}/hari</b>")
    else:
        baris.append("Hari terakhir periode: sisa bebas = jatah hari ini")
    baris.append(f"Jatah hari ini  <b>{rp_penuh(m.j0)}</b> · belanja <b>{rp_penuh(m.belanja_hari_ini)}</b>")
    return baris


def baris_amplop(ctx: Konteks) -> list[str]:
    """Daftar amplop terlihat viewer: belanja = sisa bebas (M6), tabungan = saldo (G1)."""
    m = ctx.m
    baris = []
    for eid, a in m.amplop.items():
        if a.kelompok != "belanja":
            continue
        label = _amplop_label(ctx, eid)
        if a.bebas < 0:
            baris.append(f"🔴 {label} · <b>minus {rp_penuh(-a.bebas)}</b>")
        elif a.bebas == 0 and a.tagihan_sisa + a.sisihan > 0:
            baris.append(f"⚪ {label} · <b>Rp0</b> bebas, disisihkan tagihan {rp_penuh(a.tagihan_sisa + a.sisihan)}")
        elif a.bebas == 0:
            baris.append(f"⚪ {label} · <b>habis</b>")
        elif a.dana > 0 and a.terpakai > 0:
            r = a.terpakai / a.dana
            tanda = "🔴" if r >= Decimal("0.9") else ("🟡" if r >= Decimal("0.7") else "🟢")
            baris.append(f"{tanda} {label} · <b>{rp_penuh(a.bebas)}</b>  {_bar(a.terpakai, a.dana)} {persen(r)}")
        else:
            baris.append(f"🟢 {label} · <b>{rp_penuh(a.bebas)}</b>")
    tabungan = [(eid, a) for eid, a in m.amplop.items() if a.kelompok == "tabungan"]
    if tabungan:
        baris.append("")
        for eid, a in tabungan:
            baris.append(f"💰 {_amplop_label(ctx, eid)} · <b>{rp_penuh(m.saldo_tabungan.get(eid, a.sisa))}</b>")
    return baris


def chat_status(ctx: Konteks, judul: str, chip: dict | None, utama: dict | None) -> str:
    """`/status` dan "sisa": angka KPI + daftar amplop + chip kartu + item #1 daftar."""
    baris = [f"<b>{_e(judul)} · {_e(periode_label(ctx.m))}</b>", "", *blok_angka(ctx), GARIS, *baris_amplop(ctx)]
    if chip or utama:
        baris.append(GARIS)
    if chip:
        baris.append(teks_chip_html(chip))
    if utama:
        if chip:
            baris.append("")
        baris.append(teks_insight_html(utama))
    return "\n".join(baris)


def chat_limit_harian(ctx: Konteks, chip: dict | None) -> str:
    """"Limit harian": J0, belanja hari ini, J1, dan maksimal/hari per amplop
    (bebas_setelah_rencana, penekanan 8)."""
    m = ctx.m
    if m.j1 is not None:
        kepala = f"📅 <b>Jatah harian · {m.sisa_hari} hari lagi</b>"
    else:
        kepala = "📅 <b>Jatah harian · hari terakhir periode</b>"
    baris = [kepala, "", f"Jatah hari ini sejak pagi  <b>{rp_penuh(m.j0)}</b>",
             f"Belanja hari ini  <b>{rp_penuh(m.belanja_hari_ini)}</b>"]
    if m.belanja_hari_ini > m.j0:
        baris.append(f"Lewat jatah  <b>{rp_penuh(m.belanja_hari_ini - m.j0)}</b>")
    else:
        baris.append(f"Sisa hari ini  <b>{rp_penuh(m.j0 - m.belanja_hari_ini)}</b>")
    if m.j1 is not None:
        baris.append(f"Aman {m.sisa_hari} hari ke depan  <b>{rp_penuh(m.j1)}/hari</b>")
    per_amplop = [(eid, v) for eid, v in ctx.batas.items()
                  if eid in m.amplop and m.amplop[eid].kelompok == "belanja" and v > 0]
    if per_amplop:
        baris += ["", "Maksimal per hari:" if m.j1 is not None else "Sisa bebas hari ini:"]
        baris += [f"{_amplop_label(ctx, eid)} · <b>{rp_penuh(v)}</b>" for eid, v in per_amplop]
    if chip:
        baris += [GARIS, teks_chip_html(chip)]
    return "\n".join(baris)


def chat_proyeksi(ctx: Konteks, sisa_bebas: dict | None) -> str:
    """"Kapan habis": T10, T9, T4, T8 — atau penjelasan bila d < 3."""
    from app.services.advisor.metrics import perkiraan_sisa
    m = ctx.m
    if not m.proyeksi_valid:
        baris = [f"⏳ <b>Belum ada proyeksi</b>",
                 f"Periode {_e(periode_label(m))} baru berjalan {m.hari_ke} hari. Proyeksi muncul mulai hari ke-3.",
                 "", f"Sisa bebas  <b>{rp_penuh(m.sisa_bebas)}</b>"]
        if m.j1 is not None:
            baris.append(f"Aman {m.sisa_hari} hari ke depan  <b>{rp_penuh(m.j1)}/hari</b>")
        return "\n".join(baris)
    if m.kekurangan and m.kekurangan > 0:
        kepala = (f"🟡 <b>Perkiraan habis ±{tgl(m.tanggal_habis)}</b>" if m.tanggal_habis
                  else "🔴 <b>Sisa bebas sudah habis</b>")
        ket = f"Kalau tetap {rp_ringkas(m.laju_total)}/hari, dana belanja kurang ±{rp_ringkas(m.kekurangan)} " \
              f"sebelum {tgl(m.period_end)}."
    else:
        kepala = f"🟢 <b>Cukup sampai {tgl(m.period_end)}</b>"
        ket = f"Perkiraan sisa ±{rp_ringkas(perkiraan_sisa(m) or 0)} di akhir periode."
    baris = [kepala, _e(ket), "",
             f"Rata-rata 7 hari terakhir  <b>{rp_penuh(m.laju_total)}/hari</b>",
             f"Sisa bebas  <b>{rp_penuh(m.sisa_bebas)}</b> · {m.sisa_hari} hari lagi"]
    if m.j1 is not None:
        baris.append(f"Aman {m.sisa_hari} hari ke depan  <b>{rp_penuh(m.j1)}/hari</b>")
    if m.proyeksi_akhir is not None:
        baris.append(f"Perkiraan terpakai akhir periode  <b>±{rp_penuh(m.proyeksi_akhir)}</b> "
                     f"dari {rp_penuh(m.dana_belanja)}")
    if sisa_bebas:
        baris += [GARIS, teks_chip_html(sisa_bebas)]
    return "\n".join(baris)


def chat_hari_ini(ctx: Konteks, per_amplop: dict, transaksi: list, chip: dict | None) -> str:
    """"Pengeluaran hari ini": T5 (variabel) dibanding J0, per amplop, lalu tagihan &
    lainnya, dan 5 transaksi terakhir (deskripsi sudah disamarkan snapshot)."""
    m = ctx.m
    baris = [f"🧾 <b>Pengeluaran · {hari_tgl(m.today)}</b>"]
    lain = m.harian[-1]["tagihan"] + m.harian[-1]["outlier"] + m.harian[-1]["penyesuaian"] if m.harian else ZERO
    if m.belanja_hari_ini <= 0 and lain <= 0:
        baris += ["", "🌱 Belum ada pengeluaran hari ini.", f"Jatah hari ini  <b>{rp_penuh(m.j0)}</b>"]
        return "\n".join(baris)
    baris += ["", f"💸 Belanja harian  <b>{rp_penuh(m.belanja_hari_ini)}</b> dari jatah <b>{rp_penuh(m.j0)}</b>"]
    if m.belanja_hari_ini > m.j0:
        baris.append(f"⚠️ Lewat jatah <b>{rp_penuh(m.belanja_hari_ini - m.j0)}</b>")
    else:
        baris.append(f"✅ Sisa jatah hari ini <b>{rp_penuh(m.j0 - m.belanja_hari_ini)}</b>")
    if lain > 0:
        baris.append(f"Tagihan & lainnya  <b>{rp_penuh(lain)}</b> (tidak dihitung ke jatah harian)")
    if per_amplop:
        baris.append(GARIS)
        for eid, jumlah in sorted(per_amplop.items(), key=lambda x: (-x[1], x[0])):
            baris.append(f"{_amplop_label(ctx, eid)}  {_bar(jumlah, m.belanja_hari_ini)} <b>{rp_penuh(jumlah)}</b> "
                         f"({persen(jumlah / m.belanja_hari_ini)})")
    if transaksi:
        baris += [GARIS, f"{len(transaksi)} terakhir:"]
        baris += [f"{_e(_emoji(ctx, x.envelope_id))} {_e(x.description or '—')} — <b>{rp_penuh(x.amount)}</b>"
                  for x in transaksi]
    if chip:
        baris += [GARIS, teks_chip_html(chip)]
    return "\n".join(baris)


def chat_kenapa(item: dict | None, tambahan: list[dict] | None = None) -> str:
    """"Kenapa boros?" / "kenapa {amplop} habis?": insight lengkap dengan fakta (cara
    hitung) dan rincian, lalu judul insight lain yang terkait."""
    if item is None:
        return "🟢 <b>Belum ada yang perlu dijelaskan</b>\nAngka periode ini belum menunjukkan masalah."
    baris = [teks_insight_html(item, fakta=True, rincian=True)]
    if item.get("dasar"):
        baris.append(f"\n<i>{_e(item['dasar']['teks'])} · keyakinan {_e(item['dasar']['keyakinan'])}</i>")
    for t in tambahan or []:
        baris.append(f"\n{TONE_EMOJI.get(t['tone'], '')} {_e(t['judul'])}")
    return "\n".join(baris)


def chat_amplop_aman(ctx: Konteks, eid: str) -> str:
    """"Kenapa {amplop} habis?" padahal tidak ada AMP-01/02/03 untuk amplop itu."""
    a = ctx.m.amplop[eid]
    baris = [f"🟢 <b>{_e(a.nama)} masih aman</b>",
             f"Sisa bebas {rp_penuh(a.bebas)} dari dana {rp_penuh(a.dana)}.", "",
             f"• Terpakai: <b>{rp_penuh(a.terpakai)}</b>"]
    if a.tagihan_sisa + a.sisihan > 0:
        baris.append(f"• Disisihkan tagihan: <b>{rp_penuh(a.tagihan_sisa + a.sisihan)}</b>")
    if a.laju is not None:
        baris.append(f"• Rata-rata belanja: <b>{rp_penuh(a.laju)}/hari</b>")
    batas = ctx.batas.get(eid)
    if batas and batas > 0 and ctx.m.j1 is not None:
        baris.append(f"• Maksimal per hari: <b>{rp_penuh(batas)}/hari</b>")
    return "\n".join(baris)


def chat_aman_beli(ctx: Konteks, sim: dict) -> str:
    """SIM-01: ✅ / ⚠️ / ❌ dengan angka sebelum → sesudah (dari `simulasi_belanja`)."""
    tanda = {"aman": "✅", "turun": "⚠️", "kurang": "❌"}[sim["hasil"]]
    kata = {"aman": "Aman", "turun": "Bisa, tapi jatah harian turun", "kurang": "Belum cukup"}[sim["hasil"]]
    nama = _amplop_label(ctx, sim["amplop_id"])
    baris = [f"{tanda} <b>{kata}</b> · beli {rp_penuh(sim['jumlah'])} dari {nama}", "",
             f"Sisa bebas {_e(ctx.nama.get(sim['amplop_id'], ''))}  {rp_penuh(sim['bebas'])} → "
             f"<b>{rp_penuh(sim['bebas_baru'])}</b>",
             f"Sisa bebas total  {rp_penuh(sim['t3'])} → <b>{rp_penuh(sim['t3_baru'])}</b>"]
    if sim["j1"] is not None and sim["j1_baru"] is not None:
        baris.append(f"Aman {ctx.m.sisa_hari} hari ke depan  {rp_penuh(sim['j1'])} → "
                     f"<b>{rp_penuh(sim['j1_baru'])}/hari</b>")
    if sim.get("habis") or sim.get("habis_baru") or sim.get("habis_sekarang"):
        sebelum = f"±{tgl(sim['habis'])}" if sim.get("habis") else "cukup"
        sesudah = "habis sekarang" if sim.get("habis_sekarang") else \
            (f"±{tgl(sim['habis_baru'])}" if sim.get("habis_baru") else "cukup")
        baris.append(f"Perkiraan habis  {sebelum} → <b>{sesudah}</b>")
    if sim.get("ditebak"):
        baris += ["", "<i>Amplop ditebak dari belanja 7 hari terbesar. Sebut nama amplopnya untuk cek amplop lain.</i>"]
    return "\n".join(baris)


def ringkasan_harian(ctx: Konteks, per_amplop: dict, chip: dict | None, utama: dict | None) -> str:
    """Ringkasan harian (§7 "Chat web & Telegram") = chip Jatah hari ini + item #1 daftar,
    dengan angka KPI yang sama dengan Beranda."""
    m = ctx.m
    baris = [f"📋 <b>Ringkasan · {hari_tgl(m.today)}</b>", ""]
    if m.belanja_hari_ini > 0:
        teratas = sorted(per_amplop.items(), key=lambda x: (-x[1], x[0]))
        bagian = [f"{_amplop_label(ctx, eid)} {rp_ringkas(v)}" for eid, v in teratas[:2]]
        sisa = m.belanja_hari_ini - sum((v for _, v in teratas[:2]), ZERO)
        if len(teratas) > 2 and sisa > 0:
            bagian.append(f"+{len(teratas) - 2} lain {rp_ringkas(sisa)}")
        baris.append(f"💸 Belanja harian <b>{rp_penuh(m.belanja_hari_ini)}</b> dari jatah {rp_penuh(m.j0)}")
        baris.append("  " + " · ".join(bagian))
    else:
        baris.append("✨ Belum ada belanja harian hari ini.")
    if chip:
        baris.append(teks_chip_html(chip))
    baris += [GARIS, f"📦 <b>Periode {_e(periode_label(m))}</b> · {m.sisa_hari} hari lagi", *blok_angka(ctx)]
    baris.append(GARIS)
    baris.append(teks_insight_html(utama) if utama else "🟢 <b>Semua aman</b>")
    return "\n".join(baris)


def ringkasan_mingguan(ctx: Konteks, minggu: dict, status: dict | None, struktural: dict | None) -> str:
    """Ringkasan mingguan (§7) = rekap minggu + angka periode + 1 aturan struktural
    (AMP-04/05/06 atau TAB-02). `minggu` = {"label", "total", "n", "bagian", "hari_catat"}
    disusun pemanggil dari transaksi 7 hari (bukan rumus periode)."""
    m = ctx.m
    baris = [f"📊 <b>Minggu ini · {_e(minggu['label'])}</b>", ""]
    if minggu["n"]:
        baris.append(f"💸 Total keluar <b>{rp_penuh(minggu['total'])}</b> ({minggu['n']} transaksi)")
        if minggu.get("bagian"):
            baris.append("  " + " · ".join(minggu["bagian"]))
    else:
        baris.append("✨ Tidak ada pengeluaran minggu ini.")
    baris.append(f"Rata-rata belanja harian 7 hari  <b>{rp_penuh(m.laju_total)}/hari</b>")
    baris += [GARIS, f"📅 <b>Periode {_e(periode_label(m))}</b> · hari ke-{m.hari_ke} dari {m.hari_total}",
              *blok_angka(ctx)]
    if status:
        baris.append(teks_chip_html(status))
    if struktural:
        baris += [GARIS, teks_insight_html(struktural)]
    return "\n".join(baris)
