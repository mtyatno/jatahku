"""Plugin R2 — paritas ruang sebelum dan sesudah `ruang_aktif` (03-workflow.md, Gerbang R).

Hanya membaca. Untuk setiap user:
- **lama**: hasil kueri keanggotaan lama (`select household_id where user_id = …`, satu baris):
  household satu-satunya, None bila tidak ada, atau `ganda` bila lebih dari satu (kode lama
  langsung galat di titik itu);
- **baru**: `ruang_keluarga_id` (household `rumah_tangga` milik user), yang sekarang dipakai bot,
  job, penulisan, dan setiap permintaan web/aplikasi tanpa header `X-Jatahku-Ruang`.
User lama harus mendapat household yang sama persis; karena semua rumus menerima household itu
sebagai parameter, angka mereka identik. Sebagai uji asap, ringkasan amplop dan snapshot AI Advisor
dihitung dengan household baru dan tidak boleh crash.

Di VPS, sebelum dan sesudah merge R2:
    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas
    ... --user <user_id> [--user <user_id>]   # hanya user tertentu

Keluar dengan kode 1 bila ada user yang household-nya berbeda, punya lebih dari satu ruang
keluarga, atau crash.
"""
import argparse
import asyncio
import sys
import time
import uuid


async def periksa(user, db) -> dict:
    """Satu user → {"status": ok|beda|tanpa|crash, "lama", "baru", "ms", "pesan"}."""
    from sqlalchemy import select
    from app.models.models import Household, HouseholdMember, HouseholdType
    from app.services.advisor.snapshot import load_snapshot
    from app.services.envelope_balance import compute_envelope_summaries
    from app.services.ruang import ruang_keluarga_id

    mulai = time.perf_counter()
    try:
        baris = (await db.execute(
            select(HouseholdMember.household_id, Household.type)
            .join(Household, Household.id == HouseholdMember.household_id)
            .where(HouseholdMember.user_id == user.id)
        )).all()
        lama = baris[0][0] if len(baris) == 1 else (None if not baris else "ganda")
        keluarga = [h for h, t in baris if str(t) == HouseholdType.RUMAH_TANGGA]
        baru = await ruang_keluarga_id(db, user.id)
        await compute_envelope_summaries(user, db, household_id=baru)
        await load_snapshot(user, db, household_id=baru)
        ms = (time.perf_counter() - mulai) * 1000
    except Exception as e:  # noqa: BLE001 — laporkan, lanjut ke user berikutnya
        return {"status": "crash", "lama": None, "baru": None, "ms": (time.perf_counter() - mulai) * 1000,
                "pesan": f"{type(e).__name__}: {e}"}
    if len(keluarga) > 1:
        return {"status": "beda", "lama": lama, "baru": baru, "ms": ms,
                "pesan": f"{len(keluarga)} ruang keluarga; yang tertua dipakai"}
    if lama is None and baru is None:
        return {"status": "tanpa", "lama": None, "baru": None, "ms": ms, "pesan": "belum punya household"}
    if lama == "ganda":
        # Kode lama galat untuk user ini; yang baru memilih ruang keluarga. Bukan regresi.
        return {"status": "ok", "lama": lama, "baru": baru, "ms": ms,
                "pesan": f"{len(baris)} keanggotaan (lama: galat), baru: ruang keluarga"}
    if lama != baru:
        return {"status": "beda", "lama": lama, "baru": baru, "ms": ms, "pesan": "household berbeda"}
    return {"status": "ok", "lama": lama, "baru": baru, "ms": ms, "pesan": ""}


async def jalankan(user_ids: list[str]) -> int:
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.models import User

    async with AsyncSessionLocal() as db:
        q = select(User).order_by(User.created_at)
        if user_ids:
            q = q.where(User.id.in_([uuid.UUID(x) for x in user_ids]))
        users = (await db.execute(q)).scalars().all()

    hitung = {"ok": 0, "beda": 0, "tanpa": 0, "crash": 0}
    for u in users:
        async with AsyncSessionLocal() as db:  # sesi baru per user: crash tidak menular
            h = await periksa(u, db)
        hitung[h["status"]] += 1
        print(f"{h['status']:6} {h['ms']:7.0f} ms  {u.id}  {h['pesan']}")
    print(f"\n{len(users)} user · ok {hitung['ok']} · beda {hitung['beda']} · crash {hitung['crash']} · "
          f"tanpa household {hitung['tanpa']}")
    return 1 if hitung["beda"] or hitung["crash"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user", action="append", default=[], help="user_id (boleh berulang); kosong = semua user")
    args = p.parse_args(argv)
    return asyncio.run(jalankan(args.user))


if __name__ == "__main__":
    sys.exit(main())
