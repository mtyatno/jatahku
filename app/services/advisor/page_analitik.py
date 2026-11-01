"""`GET /advisor/page/analitik` — ringkasan AI halaman Analitik (S15, 02-aturan.md §7).

- Ringkasan maksimal 3 poin dari PER-03/04, AMP-08/11, hari terboros (S6), dan TAB-06.
  Calon dikelompokkan: periode (PER-03/04), amplop (AMP-08/11), hari terboros, tabungan
  (TAB-06). Dari tiap kelompok diambil satu yang terbaik (tone dulu, skor). Calon-calon itu
  diurutkan menurut tone, lalu urutan kelompok, dan diambil 3. Bila kurang dari 3, sisa
  AMP-08/11 amplop lain mengisi.
- Hari terboros = hari dengan belanja variabel tertinggi periode ini (deret `metrics.harian`,
  sama dengan grafik), dibandingkan dengan jatah J0 hari itu (S6). Bukan aturan, jadi tidak
  bisa disembunyikan (`render.poin_hari_terboros`).
- `harian` + `grafik` = deret metrik dan baris analisa yang sama dengan grafik Beranda (S6),
  supaya grafik Analitik periode berjalan menunjuk angka yang sama dengan Beranda, chat, dan
  Telegram (bukan `/analytics/daily-spending`, §3).
- Insight yang di-dismiss viewer tidak tampil (sama dengan Beranda, §9).

Murni sampai `susun_halaman`; `get_halaman_analitik` mengurus flag, jam, dan DB. Teks dari
`render.py`; angka dari metrics/signals lewat `analisa`.
"""
from __future__ import annotations

from datetime import datetime

from app.services.advisor import advisor_cache
from app.services.advisor.dashboard import (
    FLAG_KEY, KONSTANTA_KEY, KA_DEFAULT, KM_DEFAULT, KS_DEFAULT, _tz, analisa, bangun_konstanta, flag_aktif,
    muat_pengaturan,
)
from app.services.advisor.insight import TONE_URUT, Insight, kunci_urut
from app.services.advisor.render import poin_hari_terboros, render_insight, teks_grafik

MAKS_POIN = 3
# Urutan kelompok = urutan di §7; dipakai sebagai pemecah seri sesudah tone.
KELOMPOK = (("periode", {"PER-03", "PER-04"}), ("amplop", {"AMP-08", "AMP-11"}), ("hari", set()),
            ("tabungan", {"TAB-06"}))
URUT_KELOMPOK = {nama: i for i, (nama, _) in enumerate(KELOMPOK)}


def hari_terboros(m, s) -> dict | None:
    """Hari dengan belanja variabel tertinggi periode ini (yang terakhir bila seri) + jumlah
    hari lewat jatah (S6). None bila belum ada belanja variabel."""
    calon = [h for h in m.harian if h["variabel"] > 0]
    if not calon:
        return None
    puncak = max(calon, key=lambda h: (h["variabel"], h["tanggal"]))
    return {"tanggal": puncak["tanggal"], "variabel": puncak["variabel"], "jatah": puncak["jatah"],
            "lebih": puncak["variabel"] - puncak["jatah"], "lewat": puncak["lewat"],
            "n_lewat": len(s.lewat_jatah), "hari_ke": m.hari_ke}


def pilih_ringkasan(ctx, sel) -> list[dict]:
    """Ringkasan ≤ 3 poin (bentuk render_insight), urut tampil."""
    terlihat = [i for i in sel.semua if i.di_slot("analitik") and i.id not in sel.disembunyikan]
    calon: list[tuple[int, int, dict]] = []    # (tone, kelompok, poin)
    cadangan: list[Insight] = []
    for nama, aturan in KELOMPOK:
        if nama == "hari":
            h = hari_terboros(ctx.m, ctx.s)
            if h:
                p = poin_hari_terboros(h)
                calon.append((TONE_URUT[p["tone"]], URUT_KELOMPOK[nama], p))
            continue
        grup = sorted((i for i in terlihat if i.aturan in aturan), key=kunci_urut)
        if grup:
            calon.append((TONE_URUT[grup[0].tone], URUT_KELOMPOK[nama], render_insight(grup[0], ctx)))
            if nama == "amplop":
                cadangan = grup[1:]
    calon.sort(key=lambda c: (c[0], c[1]))
    poin = [p for _, _, p in calon[:MAKS_POIN]]
    for ins in cadangan:
        if len(poin) >= MAKS_POIN:
            break
        poin.append(render_insight(ins, ctx))
    return poin


def susun_halaman(snap, *, now_local: datetime, dismiss: dict | None = None,
                  km=KM_DEFAULT, ks=KS_DEFAULT, ka=KA_DEFAULT) -> dict:
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    m = ctx.m
    return {
        "enabled": True,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "period_start": m.period_start.isoformat(),
        "period_end": m.period_end.isoformat(),
        "hari_ini": m.today.isoformat(),
        "ringkasan": pilih_ringkasan(ctx, sel),
        "harian": m.to_api()["harian"],
        "grafik": teks_grafik(m, ctx.s),
    }


async def get_halaman_analitik(user, db, now: datetime | None = None, *, household_id) -> dict:
    from app.services.advisor.snapshot import load_snapshot
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date(), household_id=household_id)
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    return susun_halaman(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
