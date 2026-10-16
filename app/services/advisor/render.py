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


# ── Telegram / chat (S9 memakai ini) ────────────────────────────────────
def teks_telegram(item: dict) -> str:
    """Insight yang sudah dirender → teks Telegram: 🔴 judul, lalu isi."""
    return f"{TONE_EMOJI.get(item['tone'], '')} {item['judul']}\n{item['isi']}".strip()
