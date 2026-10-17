"""Halaman di luar Beranda (02-aturan.md §7 "Halaman lain"; 04-kontrak-api.md).

`GET /advisor/page/langganan` (S12): TAG-* + ringkasan K4. Memakai analisa yang sama dengan
Beranda (`dashboard.analisa`: metrik, sinyal, semua aturan, seleksi, dismiss), lalu memilah
insight per baris langganan. `susun_langganan` murni (dites dengan fixture).

Keputusan kecil S12 (juga di SESI-LOG.md):
- Per baris = satu insight terbaik (urut tone lalu skor) dari TAG-01/02/03/04/06 dan DAT-06
  untuk langganan itu. TAG-07 (pola rutin) → `pola`, TAG-08 (ganda) → `lain` dengan
  `recurring_ids`, TAG-05/TAG-09 → `ringkasan.insight` (TAG-05 bila menyala, selain itu TAG-09).
- Insight yang di-dismiss tidak tampil (sama dengan Beranda) dan masuk `disembunyikan`.
- Tanpa cache Redis: halaman ini jarang dibuka, dan cache Beranda tidak boleh tertimpa.
"""
from __future__ import annotations

from datetime import datetime

from app.services.advisor.insight import Insight, kunci_urut
from app.services.advisor.metrics import rupiah
from app.services.advisor.render import judul_pendek, render_insight

BARIS = {"TAG-01", "TAG-02", "TAG-03", "TAG-04", "TAG-06", "DAT-06"}


def _per_baris(insights: list[Insight]) -> dict[str, Insight]:
    out: dict[str, Insight] = {}
    for ins in sorted(insights, key=kunci_urut):
        rid = ins.data.get("recurring_id")
        if ins.aturan in BARIS and rid and rid not in out:
            out[rid] = ins
    return out


def susun_langganan(ctx, sel, *, now_local: datetime, dismiss: dict | None = None) -> dict:
    m = ctx.m
    hidden = set(sel.disembunyikan)
    halaman = [i for i in sel.semua if i.di_slot("langganan")]
    terlihat = [i for i in halaman if i.id not in hidden]

    tag05 = next((i for i in terlihat if i.aturan == "TAG-05"), None)
    tag09 = next((i for i in terlihat if i.aturan == "TAG-09"), None)
    ringkas = tag05 or tag09
    belum = [b for b in m.tagihan if b.sisa > 0]
    return {
        "enabled": True,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "ringkasan": {
            "beban_bulanan": rupiah(m.beban_tagihan_bulanan),
            "beban_persen": round(float(m.beban_tagihan) * 100) if m.beban_tagihan is not None else None,
            "dana_belanja": rupiah(m.dana_belanja),
            "tagihan_sisa": rupiah(m.tagihan_sisa),
            "belum": len(belum),
            "lunas": len([b for b in m.tagihan if b.lunas_oleh]),
            "insight": render_insight(ringkas, ctx) if ringkas else None,
        },
        "per_langganan": {rid: render_insight(ins, ctx) for rid, ins in _per_baris(terlihat).items()},
        "pola": [render_insight(i, ctx) for i in sorted(terlihat, key=kunci_urut) if i.aturan == "TAG-07"],
        "lain": [{**render_insight(i, ctx), "recurring_ids": i.entitas.split("+")}
                 for i in sorted(terlihat, key=kunci_urut) if i.aturan == "TAG-08"],
        "disembunyikan": [{"kunci": i.id, "judul_pendek": judul_pendek(i, ctx),
                           "pilihan": (dismiss or {}).get(i.id, {}).get("pilihan", "nanti")}
                          for i in sorted((i for i in halaman if i.id in hidden), key=kunci_urut)],
    }


async def get_page_langganan(user, db, now: datetime | None = None) -> dict:
    from app.services.advisor import advisor_cache
    from app.services.advisor.dashboard import (
        FLAG_KEY, KONSTANTA_KEY, _tz, analisa, bangun_konstanta, flag_aktif, muat_pengaturan,
    )
    from app.services.advisor.snapshot import load_snapshot
    pengaturan = await muat_pengaturan(db)
    if not flag_aktif(pengaturan.get(FLAG_KEY), user.id):
        return {"enabled": False}
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    snap = await load_snapshot(user, db, today=now_local.date())
    km, ks, ka = bangun_konstanta(pengaturan.get(KONSTANTA_KEY))
    dismiss = await advisor_cache.muat_dismiss(snap.viewer_id)
    ctx, sel = analisa(snap, now_local=now_local, dismiss=dismiss, km=km, ks=ks, ka=ka)
    return susun_langganan(ctx, sel, now_local=now_local, dismiss=dismiss)
