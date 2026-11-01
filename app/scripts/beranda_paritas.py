"""Plugin B3 — cek Gerbang B sebelum flag `beranda_registry_users` = `*` (docs/plugin/03-workflow.md baris B3).

Hanya membaca: tidak menulis DB dan tidak menyimpan cache AI Advisor. Untuk setiap user yang punya
household, dengan template Beranda (14 kartu), untuk periode berjalan dan periode sebelumnya:
- `POST /dashboard/data` (jalur yang dipakai Beranda registry) tidak boleh crash dan tidak boleh ada
  kartu yang `error`;
- setiap `sumber` harus sama persis dengan endpoint lama yang dipanggil Beranda lama, dihitung ulang
  di sesi database terpisah (paritas angka Gerbang B);
- nilai KPI (`value`) sama dengan angka di sumbernya;
- nama amplop pribadi anggota lain tidak boleh muncul di respons;
- waktu batch dicatat; Gerbang B: p95 ≤ 500 ms (dicetak di akhir).

Keluaran hanya id user, status, waktu, dan nama kartu/sumber yang beda — tanpa nama amplop, nominal,
atau deskripsi, supaya aman ditempel di PR.

Di VPS:
    cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.beranda_paritas
    ... --user <user_id> [--user <user_id>]   # hanya user tertentu

Keluar dengan kode 1 bila ada user yang crash atau beda, atau p95 > 500 ms.
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from contextlib import contextmanager
from unittest.mock import patch

TARGET_P95_MS = 500

# Nama sumber → pemanggil metode `Sumber` (app/services/dashboard/sources.py).
METODE = {
    "ringkasan_amplop": lambda s: s.ringkasan_amplop(),
    "harian": lambda s: s.harian(),
    "rincian": lambda s: s.rincian(),
    "transaksi": lambda s: s.transaksi(10),
    "prediksi": lambda s: s.prediksi(),
    "tagihan": lambda s: s.tagihan(),
    "advisor": lambda s: s.advisor(),
    "insights": lambda s: s.insights(),
    "pemasukan": lambda s: s.pemasukan(),
    "target": lambda s: s.target(),
    "langganan": lambda s: s.langganan(),
    "saldo_cek": lambda s: s.saldo_cek(),
    "papan": lambda s: s.papan(),
}

# Nilai KPI (`value`) yang langsung diambil dari sumber (04-kontrak-api.md §4, tabel kartu).
def _value_harapan(card: str, sumber: dict):
    adv = sumber.get("advisor") or {}
    m = adv.get("metrics") if adv.get("enabled") else None
    if card == "core.kpi.jatah":
        return m.get("belanja_hari_ini") if m else None
    if card == "core.kpi.sisa_bebas":
        if not m:
            return None
        return m["sisa_bebas_harian"] if m.get("sisa_bebas_harian") is not None else m.get("sisa_bebas")
    if card == "core.kpi.terpakai":
        return m.get("terpakai") if m else None
    if card == "core.kpi.income":
        if m and m.get("pemasukan_rumah_tangga") is not None:
            return m["pemasukan_rumah_tangga"]
        return (sumber.get("prediksi") or {}).get("total_income")
    if card == "core.kpi.tagihan":
        return (sumber.get("tagihan") or {}).get("amount_due")
    return None


@contextmanager
def tanpa_tulis_cache():
    """Batch memanggil GET /advisor/dashboard, yang menyimpan cache Redis. Skrip ini tidak boleh
    mengubah apa pun: penyimpanan cache diganti no-op, dan cache yang ada tidak dibaca (dihitung
    segar, supaya yang dicek adalah angka hari ini)."""
    async def tidak(*_a, **_k):
        return None
    with patch("app.services.advisor.advisor_cache.simpan", tidak), \
            patch("app.services.advisor.advisor_cache.ambil", tidak):
        yield


async def nama_amplop_pribadi_lain(user, db, hid) -> set[str]:
    """Nama amplop pribadi anggota lain, kecuali yang kembar dengan amplop yang memang terlihat user."""
    from sqlalchemy import select
    from app.models.models import Envelope
    rows = (await db.execute(select(Envelope.name, Envelope.owner_id).where(Envelope.household_id == hid))).all()
    terlihat = {n for n, owner in rows if owner is None or owner == user.id}
    return {n for n, owner in rows if owner is not None and owner != user.id and n and n not in terlihat}


async def periksa(user, Session) -> dict:
    """Satu user → {"status": ok|beda|lewati|crash, "ms": [per periode], "beda": [...], "pesan"}."""
    from app.services.dashboard import batch, registry
    from app.services.dashboard.sources import Periode, Sumber
    from app.services.ruang import ruang_keluarga

    items = [{"id": i["id"], "card": i["card"], "settings": {}} for i in registry.template("beranda")]
    beda, ms = [], []
    try:
        async with Session() as db:
            # Beranda tanpa header X-Jatahku-Ruang = ruang keluarga (R2, ruang_aktif tanpa header).
            hid = await ruang_keluarga(user, db)
            if not hid:
                return {"status": "lewati", "ms": [], "beda": [], "pesan": "belum ada household"}
            rahasia = await nama_amplop_pribadi_lain(user, db, hid)
        daftar = await batch.daftar_periode(user)
        periode_list = [None] + ([daftar[-2]["period_start"]] if len(daftar) >= 2 else [])
        for kode in periode_list:
            label = "berjalan" if kode is None else "lalu"
            async with Session() as db:
                p = await batch.tentukan_periode(user, kode)
                mulai = time.perf_counter()
                hasil = await batch.jalankan(user, db, p, items, household_id=hid)
                ms.append((time.perf_counter() - mulai) * 1000)
            data = hasil["data"]
            for item in items:
                entri = data.get(item["id"]) or {}
                if "error" in entri:
                    beda.append(f"{label} {item['card']}: error {entri['error'].get('kode')}")
                    continue
                if entri.get("shape") == "kpi":
                    harap = _value_harapan(item["card"], entri.get("sumber") or {})
                    if item["card"] != "core.kpi.tabungan" and entri.get("value") != harap:
                        beda.append(f"{label} {item['card']}: value tidak sama dengan sumbernya")
            # Paritas: setiap sumber di setiap kartu dibandingkan dengan endpoint lama yang dihitung
            # ulang di sesi terpisah (tanpa memo bersama). `advisor` dipotong per kartu, jadi hanya
            # salinan utuh di kartu AI Advisor yang dibandingkan.
            ref_cache, salah = {}, set()
            for item in items:
                sumber = (data.get(item["id"]) or {}).get("sumber") or {}
                for nama, isi in sorted(sumber.items()):
                    if nama == "advisor" and item["card"] != "core.advisor":
                        continue
                    if nama not in ref_cache:
                        async with Session() as db2:
                            ref_cache[nama] = await METODE[nama](
                                Sumber(user=user, db=db2, periode=Periode(p.start, p.end, p.berjalan), hid=hid))
                    ref = ref_cache[nama]
                    if nama == "advisor" and isi and ref:
                        # generated_at berbeda detik; bandingkan isinya.
                        isi, ref = {**isi, "generated_at": None}, {**ref, "generated_at": None}
                    if isi != ref and (nama, item["card"]) not in salah:
                        salah.add((nama, item["card"]))
                        beda.append(f"{label} sumber {nama} di {item['card']}: beda dengan endpoint lama")
            teks = json.dumps(data, ensure_ascii=False)
            bocor = sum(1 for n in rahasia if n in teks)
            if bocor:
                beda.append(f"{label}: {bocor} nama amplop pribadi anggota lain muncul di respons")
    except Exception as e:  # noqa: BLE001 — laporkan semua, lanjut ke user berikutnya
        return {"status": "crash", "ms": ms, "beda": beda, "pesan": f"{type(e).__name__}: {e}"}
    return {"status": "beda" if beda else "ok", "ms": ms, "beda": beda, "pesan": ""}


def p95(nilai: list[float]) -> float:
    if not nilai:
        return 0.0
    urut = sorted(nilai)
    return urut[max(0, int(round(0.95 * len(urut))) - 1)]


async def jalankan(user_ids: list[str], Session=None) -> int:
    from sqlalchemy import select
    from app.models.models import User
    if Session is None:
        from app.core.database import AsyncSessionLocal as Session

    async with Session() as db:
        q = select(User).order_by(User.created_at)
        if user_ids:
            q = q.where(User.id.in_([uuid.UUID(x) for x in user_ids]))
        users = (await db.execute(q)).scalars().all()

    hitung = {"ok": 0, "beda": 0, "lewati": 0, "crash": 0}
    semua_ms = []
    with tanpa_tulis_cache():
        # Pemanasan (tidak dihitung): impor tertunda dan koneksi pertama di proses baru, yang di API
        # yang sedang berjalan sudah terjadi, jangan masuk p95.
        for u in users[:1]:
            await periksa(u, Session)
        for u in users:
            h = await periksa(u, Session)
            hitung[h["status"]] += 1
            semua_ms += h["ms"]
            waktu = " / ".join(f"{x:.0f}" for x in h["ms"]) or "-"
            print(f"{h['status']:6} {waktu:>13} ms  {u.id}  {h['pesan']}")
            for b in h["beda"]:
                print(f"         - {b}")
    nilai_p95 = p95(semua_ms)
    print(f"\n{len(users)} user · ok {hitung['ok']} · beda {hitung['beda']} · crash {hitung['crash']} · "
          f"lewati {hitung['lewati']} · batch p95 {nilai_p95:.0f} ms (Gerbang B ≤ {TARGET_P95_MS} ms)")
    gagal = hitung["beda"] or hitung["crash"] or nilai_p95 > TARGET_P95_MS
    print("Gerbang B: " + ("BELUM LULUS" if gagal else "LULUS"))
    return 1 if gagal else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user", action="append", default=[], help="user_id (boleh berulang); kosong = semua user")
    args = p.parse_args(argv)
    return asyncio.run(jalankan(args.user))


if __name__ == "__main__":
    sys.exit(main())
