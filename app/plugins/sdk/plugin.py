"""Pendaftaran kode plugin (Plugin H2; 01-kajian.md "Lampiran teknis", "SDK plugin").

Setiap plugin yang punya kode server membuat SATU objek `Plugin` di `app/plugins/<id>/__init__.py`, lalu
mendaftarkan fungsinya dengan dekorator. Host (`app/plugins/host/registry.py`) mengimpor paket itu saat start,
mengambil atribut `plugin`, dan mencocokkannya dengan manifest:

- setiap kontribusi server di manifest (kartu, cek, aturan advisor, perintah bot, job, field form) harus punya
  fungsi, dan setiap fungsi harus tercantum di manifest (tidak ada yang muncul tanpa manifest);
- `izin=` tiap fungsi harus bagian dari `permissions` manifest. Saat dipanggil, `PluginContext` hanya membuka izin
  yang ada di ketiganya sekaligus: izin yang disetujui saat pasang, manifest, dan `izin=` fungsi itu.

    plugin = Plugin("buku_usaha")

    @plugin.kartu("buku_usaha.omzet", izin=["incomes:read"])
    async def omzet(ctx, pengaturan, periode):
        ...
        return {"value": total, "unit": "rp", "tone": "ok"}

Bentuk masukan dan keluaran tiap jenis: `app/plugins/sdk/__init__.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# jenis pendaftaran → nama bagian `contributes` di manifest
JENIS = {
    "kartu": "cards",
    "cek": "checks",
    "aturan_advisor": "advisor_rules",
    "perintah_bot": "bot_commands",
    "job": "jobs",
    "field_form": "form_fields",
}


@dataclass(frozen=True)
class Pendaftaran:
    jenis: str
    kunci: str
    fn: Callable
    izin: tuple[str, ...]


class _KelasBeku(type):
    """Kelas SDK (`Plugin`, `PluginContext`) tidak bisa ditambal (`Plugin.ambil = …`) atau diturunkan
    (review ulang #186). Menambal kelas mengubah perilaku semua plugin sekaligus."""

    def __setattr__(cls, nama, nilai):
        raise TypeError(f"{cls.__name__} tidak bisa diubah")

    def __delattr__(cls, nama):
        raise TypeError(f"{cls.__name__} tidak bisa diubah")


class Plugin(metaclass=_KelasBeku):
    """Kumpulan fungsi server satu plugin. Hanya didaftarkan; host yang memanggil."""

    def __init_subclass__(cls, **kw):
        raise TypeError("Plugin tidak bisa diturunkan")

    def __init__(self, plugin_id: str):
        self.id = plugin_id
        self._daftar: dict[tuple[str, str], Pendaftaran] = {}

    def _dekor(self, jenis: str, kunci: str, izin) -> Callable:
        if isinstance(izin, str):
            raise TypeError("izin= harus daftar, mis. izin=['incomes:read']")

        def daftar(fn: Callable) -> Callable:
            if (jenis, kunci) in self._daftar:
                raise ValueError(f"{self.id}: {jenis} '{kunci}' didaftarkan dua kali")
            self._daftar[(jenis, kunci)] = Pendaftaran(jenis, kunci, fn, tuple(izin))
            return fn
        return daftar

    # ── titik ekstensi ──
    def kartu(self, key: str, *, izin=()):
        """`async fn(ctx, pengaturan: dict, periode) -> dict` (field bentuk kartu, 04-kontrak-api.md §4)."""
        return self._dekor("kartu", key, izin)

    def cek(self, key: str, *, izin=()):
        """`async fn(ctx, rencana: RencanaPengeluaran) -> list[str]`: peringatan sebelum simpan, tidak pernah menolak."""
        return self._dekor("cek", key, izin)

    def aturan_advisor(self, kode: str, *, izin=()):
        """`async fn(ctx) -> list[Saran]` untuk kartu AI Advisor (slot `daftar`)."""
        return self._dekor("aturan_advisor", kode, izin)

    def perintah_bot(self, command: str, *, izin=()):
        """`async fn(ctx) -> str`: perintah baca di chat; teks polos, host menambah nama ruang."""
        return self._dekor("perintah_bot", command, izin)

    def job(self, key: str, *, izin=()):
        """`async fn(ctx) -> None` per ruang yang memasang plugin, sesuai `schedule` di manifest. Wajib idempoten."""
        return self._dekor("job", key, izin)

    def field_form(self, target: str, key: str, *, izin=()):
        """`async fn(ctx, nilai) -> nilai_bersih` atau `raise NilaiTidakSah("pesan")`. Validasi saja (disimpan di U2)."""
        return self._dekor("field_form", f"{target}.{key}", izin)

    # ── dibaca host ──
    def ambil(self, jenis: str, kunci: str) -> Pendaftaran | None:
        return self._daftar.get((jenis, kunci))

    def semua(self, jenis: str | None = None) -> list[Pendaftaran]:
        return [p for (j, _), p in sorted(self._daftar.items()) if jenis is None or j == jenis]
