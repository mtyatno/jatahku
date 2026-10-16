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


TEMPLATE = {
    "HAR-01": _har01, "HAR-02": _har02, "HAR-03": _har03, "HAR-04": _har04, "HAR-05": _har05,
    "PER-01": _per01, "PER-02": _per02, "PER-03": _per03, "PER-04": _per04, "PER-05": _per05,
    "PER-06": _per06, "PER-07": _per07,
}


# ── aksi ────────────────────────────────────────────────────────────────
def _label_aksi(a: dict, ins: Insight, ctx: Konteks) -> tuple[str, dict]:
    kode, p = a.get("kode"), dict(a.get("payload") or {})
    if kode == "batas_harian":
        return f"Batas harian {ctx.nama.get(p.get('amplop_id'), '')} {rp_ringkas(p.get('jumlah', 0))}", p
    if kode == "pindah_tabungan":
        return f"Pindahkan ke {ins.data.get('tujuan', 'tabungan')}", p
    if kode == "tanya_hari_ini":
        return "Tanya di chat", {"teks": "Kenapa belanja hari ini lewat jatah?", **p}
    if kode == "tanya_kekurangan":
        return "Tanya di chat", {"teks": "Kenapa dana belanja kurang?", **p}
    return LABEL.get(kode, kode or a["kind"]), p


LABEL = {
    "lihat_transaksi_hari_ini": "Lihat transaksi hari ini",
    "catat_pemasukan": "Catat pemasukan",
    "tutup_minus": "Tutup minus",
    "bagi_pemasukan": "Bagi pemasukan",
    "lihat_periode_lalu": "Lihat periode lalu",
    "catat": "Catat",
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
