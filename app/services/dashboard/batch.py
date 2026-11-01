"""`POST /dashboard/data`: data banyak kartu dalam satu permintaan (04-kontrak-api.md §4).

Satu `Sumber` per permintaan (satu snapshot), penyedia dijalankan berurutan di satu sesi
database. Galat satu penyedia hanya mengisi `error` kartunya. Anggaran: batch p95 ≤ 500 ms,
penyedia ≤ 150 ms; yang lewat dicatat di log dengan nama kartunya (01-kajian.md, "Penyedia data").
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.dashboard import registry
from app.services.dashboard.providers import PROVIDERS
from app.services.dashboard.sources import Periode, Sumber, SumberGagal, daftar_periode

logger = logging.getLogger("jatahku.dashboard")

ANGGARAN_BATCH_MS = 500
ANGGARAN_PENYEDIA_MS = 150

PESAN = {
    "kartu_tidak_dikenal": "Kartu ini tidak tersedia.",
    "gagal_memuat": "Data kartu ini belum bisa dimuat. Coba lagi sebentar.",
}


class PeriodeTidakDikenal(ValueError):
    pass


def _tz(user) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(user, "timezone", None) or "Asia/Jakarta")
    except Exception:
        return ZoneInfo("Asia/Jakarta")


async def tentukan_periode(user, periode: str | None) -> Periode:
    """`periode` = `period_start` salah satu periode dari `GET /analytics/periods`, atau null
    untuk periode berjalan. Rentang bebas dari klien tidak diterima."""
    daftar = await daftar_periode(user)
    if not daftar:
        raise PeriodeTidakDikenal("Periode tidak ditemukan.")
    sekarang = daftar[-1]
    if periode is None or periode == sekarang["period_start"]:
        return Periode(date.fromisoformat(sekarang["period_start"]),
                       date.fromisoformat(sekarang["period_end"]), True)
    for p in daftar:
        if p["period_start"] == periode:
            return Periode(date.fromisoformat(p["period_start"]), date.fromisoformat(p["period_end"]), False)
    raise PeriodeTidakDikenal("Periode itu tidak tersedia. Pilih periode dari daftar.")


def _galat(kode: str, detail: str | None = None) -> dict:
    return {"error": {"kode": kode, "detail": detail or PESAN[kode]}}


async def satu_kartu(sumber: Sumber, item: dict) -> dict:
    """Data satu instans, atau `{"error": {...}}`. Tidak pernah melempar."""
    definisi = registry.get(item.get("card"))
    penyedia = PROVIDERS.get(item.get("card"))
    if definisi is None or penyedia is None:
        return _galat("kartu_tidak_dikenal")
    try:
        settings = definisi.validasi(item.get("settings") or {})
    except registry.PengaturanTidakSah as exc:
        return _galat("pengaturan_tidak_sah", str(exc))
    mulai = time.perf_counter()
    try:
        data = await penyedia(sumber, settings)
    except SumberGagal:
        data = _galat("gagal_memuat")
    except Exception:
        logger.exception("dashboard penyedia %s gagal", definisi.key)
        data = _galat("gagal_memuat")
    ms = (time.perf_counter() - mulai) * 1000
    if ms > ANGGARAN_PENYEDIA_MS:
        logger.warning("dashboard penyedia %s %.0f ms (anggaran %d ms)", definisi.key, ms, ANGGARAN_PENYEDIA_MS)
    return data


async def jalankan(user, db, periode: Periode, items: list[dict], *, household_id) -> dict:
    mulai = time.perf_counter()
    sumber = Sumber(user=user, db=db, periode=periode, hid=household_id)
    data = {item["id"]: await satu_kartu(sumber, item) for item in items}
    ms = (time.perf_counter() - mulai) * 1000
    if ms > ANGGARAN_BATCH_MS:
        logger.warning("dashboard batch %d kartu %.0f ms (anggaran %d ms) user=%s",
                       len(items), ms, ANGGARAN_BATCH_MS, user.id)
    return {
        "generated_at": datetime.now(_tz(user)).isoformat(timespec="seconds"),
        "periode": {"start": periode.start.isoformat(), "end": periode.end.isoformat(),
                    "berjalan": periode.berjalan},
        "data": data,
    }
