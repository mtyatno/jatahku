"""AI Advisor v2 S10 — cek sebelum flag `advisor_v2_users` = `*` (03-workflow.md §5, 02-aturan.md §13).

Hanya membaca (tidak menulis DB, tidak menyimpan cache). Untuk setiap user, flag diabaikan
(dianggap aktif) lalu:
- Beranda (`dashboard._hitung`) dan chat/Telegram (`chat.muat`) dihitung lewat jalur masing-masing;
- angka KPI web (dana belanja, sisa bebas, jatah hari ini, belanja hari ini) harus muncul persis
  di chat "sisa", `/status`, dan ringkasan harian (paritas §13);
- nama amplop pribadi anggota lain tidak boleh muncul di payload Beranda maupun teks chat
  (skenario 7);
- tidak boleh crash; waktu hitung dicatat (target < 150 ms, §13 "Performa").

Di VPS:
    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.advisor_paritas
    ... --user <user_id> [--user <user_id>]   # hanya user tertentu

Keluar dengan kode 1 bila ada user yang crash atau angkanya berbeda.
"""
import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from datetime import datetime

TARGET_MS = 150


def polos(teks: str) -> str:
    """HTML Telegram → teks biasa."""
    return re.sub(r"<[^>]+>", "", teks).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def baris_wajib(metrics: dict) -> list[str]:
    """Baris angka dari `blok_angka` yang harus sama di semua permukaan, dibangun dari KPI web."""
    from app.services.advisor.render import rp_penuh
    return [
        f"Dana belanja  {rp_penuh(metrics['dana_belanja'])}",
        f"Sisa bebas  {rp_penuh(metrics['sisa_bebas'])}",
        f"Jatah hari ini  {rp_penuh(metrics['j0'])} · belanja {rp_penuh(metrics['belanja_hari_ini'])}",
    ]


async def nama_amplop_pribadi_lain(user, db, snap) -> set[str]:
    """Nama amplop pribadi anggota lain di household ini, kecuali yang namanya sama dengan amplop
    yang memang terlihat viewer (nama kembar bukan kebocoran)."""
    from sqlalchemy import select
    from app.models.models import Envelope
    rows = (await db.execute(
        select(Envelope.name).where(Envelope.household_id == uuid.UUID(str(snap.household_id)),
                                    Envelope.owner_id.is_not(None), Envelope.owner_id != user.id)
    )).scalars().all()
    terlihat = {e.name for e in snap.envelopes}
    return {n for n in rows if n and n not in terlihat}


async def periksa(user, db, now: datetime | None = None, pengaturan: dict | None = None) -> dict:
    """Satu user → {"status": ok|beda|lewati|crash, "ms", "beda": [...], "pesan"}."""
    from app.services.advisor import chat
    from app.services.advisor.dashboard import FLAG_KEY, _hitung, _tz, muat_pengaturan

    if pengaturan is None:
        pengaturan = await muat_pengaturan(db)
    paksa = {**pengaturan, FLAG_KEY: str(user.id)}          # seolah user ada di flag
    now_local = (now or datetime.now(_tz(user))).astimezone(_tz(user))
    mulai = time.perf_counter()
    try:
        from app.services.ruang import ruang_keluarga
        hid = await ruang_keluarga(user, db)  # Beranda tanpa header dan chat = ruang keluarga
        payload, _meta, snap = await _hitung(user, db, now_local, paksa, household_id=hid)
        ms = (time.perf_counter() - mulai) * 1000
        if not snap.household_id or not snap.envelopes:
            return {"status": "lewati", "ms": ms, "beda": [], "pesan": "belum ada household/amplop"}
        a = await chat.muat(user, db, now=now_local, pengaturan=paksa, household_id=hid)
        if a is None:
            return {"status": "beda", "ms": ms, "beda": ["chat.muat None padahal dashboard terisi"], "pesan": ""}
        teks = {"sisa": chat.jawab_sisa(a), "status": chat.jawab_status(a), "ringkasan": chat.ringkasan_harian(a)}
        rahasia = await nama_amplop_pribadi_lain(user, db, snap)
    except Exception as e:  # noqa: BLE001 — laporkan semua, lanjut ke user berikutnya
        return {"status": "crash", "ms": (time.perf_counter() - mulai) * 1000, "beda": [],
                "pesan": f"{type(e).__name__}: {e}"}
    beda = [f"{nama}: tidak memuat '{b}'"
            for nama, isi in teks.items() for b in baris_wajib(payload["metrics"]) if b not in polos(isi)]
    semua = {"beranda": json.dumps(payload, ensure_ascii=False), **{k: polos(v) for k, v in teks.items()}}
    beda += [f"{nama}: memuat amplop pribadi anggota lain '{n}'"
             for nama, isi in semua.items() for n in rahasia if n in isi]
    return {"status": "beda" if beda else "ok", "ms": ms, "beda": beda, "pesan": ""}


async def jalankan(user_ids: list[str]) -> int:
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.models import User
    from app.services.advisor.dashboard import muat_pengaturan

    async with AsyncSessionLocal() as db:
        q = select(User).order_by(User.created_at)
        if user_ids:
            q = q.where(User.id.in_([uuid.UUID(x) for x in user_ids]))
        users = (await db.execute(q)).scalars().all()
        pengaturan = await muat_pengaturan(db)

    hitung = {"ok": 0, "beda": 0, "lewati": 0, "crash": 0}
    lambat = 0
    for u in users:
        async with AsyncSessionLocal() as db:             # sesi baru per user: crash tidak menular
            h = await periksa(u, db, pengaturan=pengaturan)
        hitung[h["status"]] += 1
        lambat += h["ms"] > TARGET_MS and h["status"] != "crash"
        print(f"{h['status']:6} {h['ms']:7.0f} ms  {u.id}  {h['pesan']}")
        for b in h["beda"]:
            print(f"         - {b}")
    print(f"\n{len(users)} user · ok {hitung['ok']} · beda {hitung['beda']} · crash {hitung['crash']} · "
          f"lewati {hitung['lewati']} · > {TARGET_MS} ms: {lambat}")
    return 1 if hitung["beda"] or hitung["crash"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user", action="append", default=[], help="user_id (boleh berulang); kosong = semua user")
    args = p.parse_args(argv)
    return asyncio.run(jalankan(args.user))


if __name__ == "__main__":
    sys.exit(main())
