"""Langkah yang baru boleh berjalan sesudah commit milik pemanggil (Plugin U2).

Jalur inti seperti `catat_pemasukan` biasanya meng-commit sendiri lalu mengirim notifikasi (goal tercapai). Saat
dipanggil dari plugin (`ctx.catat_pemasukan`), pemasukan dan data plugin harus masuk dalam SATU commit milik route
`/p/<id>/…`, jadi langkah sesudah-commit dititipkan di `db.info` dan dijalankan route itu sesudah commit-nya
berhasil. Bila permintaan gagal sebelum commit, titipan ikut dibuang bersama sesinya.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

log = logging.getLogger("jatahku")

_KUNCI = "setelah_commit"


def titip(db, langkah: Callable[[], Awaitable[None]]) -> None:
    db.info.setdefault(_KUNCI, []).append(langkah)


def buang(db) -> None:
    db.info.pop(_KUNCI, None)


async def jalankan(db) -> None:
    """Jalankan titipan berurutan (best-effort: galat dicatat, tidak pernah melempar)."""
    for langkah in db.info.pop(_KUNCI, []):
        try:
            await langkah()
        except Exception:
            log.exception("langkah sesudah commit gagal")
