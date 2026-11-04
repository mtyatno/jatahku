"""Keadaan di balik `PluginContext`, milik host (Plugin H2; review keamanan PR #186 temuan 3, 4, 6).

`PluginContext` (`app/plugins/sdk/context.py`) tidak menyimpan apa pun di dirinya sendiri: sesi DB, ruang, peran,
izin, dan penghitung kiriman ada di `Keadaan` yang dipetakan dari objek konteks lewat `WeakKeyDictionary` di modul
ini. Kode plugin tidak boleh mengimpor `app.plugins.host` (validator AST, `kode.py`), jadi plugin tidak bisa
mengganti izin atau ruangnya (mis. `dataclasses.replace`, `object.__setattr__`) dan tidak bisa mencapai sesi DB.
Konteks yang tidak dibuat `buat()` tidak punya keadaan dan setiap metodenya gagal.

Modul ini juga memegang sesi tambahan dan audit plugin (dulu di SDK, yang boleh diimpor plugin).
"""
from __future__ import annotations

import logging
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

log = logging.getLogger("jatahku.plugins")


@dataclass
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
    notify_dipakai: int = 0


_KEADAAN: "weakref.WeakKeyDictionary[Any, Keadaan]" = weakref.WeakKeyDictionary()


class KonteksTidakSah(RuntimeError):
    """`PluginContext` yang tidak dibuat host."""


def buat(**isi) -> Any:
    from app.plugins.sdk.context import PluginContext
    ctx = object.__new__(PluginContext)
    _KEADAAN[ctx] = Keadaan(**isi)
    return ctx


def ambil(ctx) -> Keadaan:
    try:
        return _KEADAAN[ctx]
    except (KeyError, TypeError):
        raise KonteksTidakSah("PluginContext hanya dibuat host") from None


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
