"""SDK plugin Jatahku (Plugin H2; 03-workflow.md baris H2, AGENTS.md "Plugin dan ruang" aturan 4).

Kode di `app/plugins/<id>/` hanya mengimpor dari modul ini (dan paketnya sendiri). Validator CI menolak impor
`app.models`, `app.api`, `app.services`, `app.bot`, `app.core`, `app.plugins.host`, dan kode plugin lain.

Titik ekstensi server dan bentuknya:

| Dekorator | Fungsi | Dipanggil oleh |
| --- | --- | --- |
| `plugin.kartu(key)` | `async (ctx, pengaturan, periode) -> dict` bentuk kartu | `POST /dashboard/data` (registry B1) |
| `plugin.cek(key)` | `async (ctx, RencanaPengeluaran) -> list[str]` peringatan | `expense_rules.peringatan_plugin` |
| `plugin.aturan_advisor(kode)` | `async (ctx) -> list[Saran]` | AI Advisor (`select.py`, batas per plugin) |
| `plugin.perintah_bot(cmd)` | `async (ctx) -> str` | Telegram dan chat web, hanya baca |
| `plugin.job(key)` | `async (ctx) -> None`, idempoten | scheduler tiap jam |
| `plugin.field_form(target, key)` | `async (ctx, nilai) -> nilai` | `titik.periksa_field` (disambungkan ke form di U2) |

`ctx.notify(...)` mengirim notifikasi (`notifications:send`); kamus Catat cepat (`nlp_kamus`) cukup data di manifest.
"""
from app.plugins.sdk.context import (
    AksiRoute, AmplopView, AnggotaView, IzinDitolak, NilaiTidakSah, PemasukanView, PluginContext,
    RencanaPengeluaran, Saran, TransaksiView,
)
from app.plugins.sdk.plugin import Plugin

__all__ = [
    "AksiRoute", "AmplopView", "AnggotaView", "IzinDitolak", "NilaiTidakSah", "PemasukanView", "Plugin",
    "PluginContext", "RencanaPengeluaran", "Saran", "TransaksiView",
]
