"""Keadaan di balik `PluginContext`, milik host (Plugin H2; review keamanan PR #186 temuan 3, 4, 6).

`PluginContext` (`app/plugins/sdk/context.py`) tidak menyimpan apa pun di dirinya sendiri: sesi DB, ruang, peran,
izin, dan penghitung kiriman ada di `Keadaan` yang dipetakan dari identitas objek konteks (`id` + `weakref`, bukan
`__hash__`/`__eq__` yang bisa ditiru). Pemeriksaan izin dan penolakan (`perlu`, `tolak`) juga fungsi modul ini, bukan
metode konteks, dan kelas konteks tidak bisa ditambal atau diturunkan (review ulang #186 temuan 1, 3). Kode plugin
tidak boleh mengimpor `app.plugins.host` (validator AST, `kode.py`). Konteks yang tidak dibuat `buat()` gagal.

Modul ini juga memegang sesi tambahan dan audit plugin (dulu di SDK, yang boleh diimpor plugin).
"""
from __future__ import annotations

import asyncio
import logging
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

log = logging.getLogger("jatahku.plugins")


@dataclass(frozen=True)
class Keadaan:
    db: Any
    plugin_id: str
    nama_plugin: str
    ruang_id: UUID
    nama_ruang: str
    jenis_ruang: str
    viewer: Any                       # sdk.PenggunaView atau None (job)
    peran: str
    izin: frozenset[str]
    jenis_notifikasi: frozenset[str]
    pengaturan: dict = field(default_factory=dict)
    sumber: str = ""
    penghitung: dict = field(default_factory=lambda: {"notify": 0})
    sekarang: Any = None              # jam acuan (job: jam jadwalnya); None = jam sungguhan


_KEADAAN: dict[int, tuple["weakref.ref", Keadaan, Any]] = {}


class KonteksTidakSah(RuntimeError):
    """`PluginContext` yang tidak dibuat host."""


def buat(**isi) -> Any:
    from app.plugins.sdk.context import PluginContext
    ctx = object.__new__(PluginContext)
    kunci = id(ctx)

    def _buang(ref, kunci=kunci):
        ada = _KEADAAN.get(kunci)
        if ada is not None and ada[0] is ref:
            del _KEADAAN[kunci]

    _KEADAAN[kunci] = (weakref.ref(ctx, _buang), Keadaan(**isi), _task())
    return ctx


def _task():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def tutup(ctx) -> None:
    """Konteks selesai dipakai (host memanggilnya sesudah setiap fungsi plugin): keadaannya dibuang, jadi konteks yang
    disimpan plugin gagal `KonteksTidakSah` di panggilan berikutnya."""
    ada = _KEADAAN.get(id(ctx))
    if ada is not None and ada[0]() is ctx:
        del _KEADAAN[id(ctx)]


def ambil(ctx) -> Keadaan:
    """Keadaan konteks buatan host. Hanya objek `PluginContext` persis (bukan subkelas atau peniru) yang identitasnya
    terdaftar, dan hanya di task asyncio yang membuatnya: konteks permintaan lain yang sedang berjalan bersamaan tidak
    bisa dipinjam (review ulang ketiga #186 no. 1)."""
    from app.plugins.sdk.context import PluginContext
    if type(ctx) is not PluginContext:
        raise KonteksTidakSah("PluginContext hanya dibuat host")
    ada = _KEADAAN.get(id(ctx))
    if ada is None or ada[0]() is not ctx or ada[2] is not _task():
        raise KonteksTidakSah("PluginContext hanya dibuat host")
    return ada[1]


# ── izin (dipanggil metode PluginContext) ────────────────────────────────
IZIN_KEUANGAN = ("envelopes:read", "transactions:read", "incomes:read")


def karyawan(k: Keadaan) -> bool:
    return k.jenis_ruang == "usaha" and k.peran == "member"


async def tolak(k: Keadaan, izin: str, alasan: str):
    """Catat penolakan (sekali per jam per kunci) lalu lempar `IzinDitolak`."""
    from app.plugins.sdk.context import IzinDitolak
    if tolak_perlu_dicatat((k.ruang_id, k.plugin_id, izin, alasan, k.sumber)):
        await catat_audit(k.ruang_id, k.plugin_id, k.viewer.id if k.viewer is not None else None,
                          f"tolak:{izin}", alasan=alasan, sumber=k.sumber)
    log.warning("plugin %s ditolak %s (%s) di %s", k.plugin_id, izin, alasan, k.sumber)
    raise IzinDitolak(izin, alasan)


async def perlu(k: Keadaan, izin: str) -> None:
    if izin not in k.izin:
        await tolak(k, izin, "tanpa_izin")
    if izin in IZIN_KEUANGAN and karyawan(k):
        await tolak(k, izin, "khusus_admin")


# ── sesi DB tambahan (audit, notifikasi, job) ────────────────────────────
_SESI = None


def sesi():
    """Pabrik sesi untuk tulisan host yang harus berdiri sendiri. Tes menggantinya lewat `pakai_sesi`."""
    if _SESI is not None:
        return _SESI()
    from app.core.database import AsyncSessionLocal
    return AsyncSessionLocal()


@contextmanager
def pakai_sesi(pabrik):
    global _SESI
    lama, _SESI = _SESI, pabrik
    try:
        yield
    finally:
        _SESI = lama


# ── audit ────────────────────────────────────────────────────────────────
_TOLAK_TERCATAT: dict[tuple, float] = {}
_TOLAK_MAKS = 10_000
TOLAK_JEDA_DETIK = 3600


def tolak_perlu_dicatat(kunci: tuple) -> bool:
    """Penolakan yang sama dicatat sekali per jam per proses. Bila tabel penuh, entri tertua dibuang."""
    sekarang = time.monotonic()
    if sekarang - _TOLAK_TERCATAT.get(kunci, -1e9) < TOLAK_JEDA_DETIK:
        return False
    if len(_TOLAK_TERCATAT) >= _TOLAK_MAKS:
        for k in sorted(_TOLAK_TERCATAT, key=_TOLAK_TERCATAT.get)[:_TOLAK_MAKS // 10]:
            del _TOLAK_TERCATAT[k]
    _TOLAK_TERCATAT[kunci] = sekarang
    return True


async def catat_audit(household_id, plugin_id: str, actor_id, aksi: str, **detail) -> None:
    """Satu baris `plugin_audit_log` lewat sesi sendiri. Gagal → log, tidak pernah melempar."""
    from app.models.models import PluginAuditLog
    try:
        async with sesi() as db:
            db.add(PluginAuditLog(household_id=household_id, plugin_id=plugin_id, actor_id=actor_id,
                                  action=aksi[:30], detail=detail))
            await db.commit()
    except Exception:
        log.exception("audit plugin %s %s gagal dicatat", plugin_id, aksi)
