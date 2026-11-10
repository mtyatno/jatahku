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
_KUNCI_GAGAL = "setelah_gagal"


def titip(db, langkah: Callable[[], Awaitable[None]]) -> None:
    db.info.setdefault(_KUNCI, []).append(langkah)


def titip_gagal(db, langkah: Callable[[], Awaitable[None]]) -> None:
    """Langkah bila permintaan gagal sebelum atau saat commit (mis. melepas kunci idempotensi, review #201 T5)."""
    db.info.setdefault(_KUNCI_GAGAL, []).append(langkah)


def buang(db) -> None:
    db.info.pop(_KUNCI, None)
    db.info.pop(_KUNCI_GAGAL, None)


async def _urut(langkah_list, pesan: str) -> None:
    for langkah in langkah_list:
        try:
            await langkah()
        except Exception:
            log.exception(pesan)


async def jalankan(db) -> None:
    """Sesudah commit berhasil: jalankan titipan berurutan (best-effort: galat dicatat, tidak pernah melempar)."""
    db.info.pop(_KUNCI_GAGAL, None)
    await _urut(db.info.pop(_KUNCI, []), "langkah sesudah commit gagal")


async def batal(db) -> None:
    """Permintaan gagal: buang titipan sukses, jalankan titipan gagal (best-effort, tidak pernah melempar)."""
    db.info.pop(_KUNCI, None)
    await _urut(db.info.pop(_KUNCI_GAGAL, []), "langkah sesudah gagal gagal")
