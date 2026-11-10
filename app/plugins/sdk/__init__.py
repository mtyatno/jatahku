"""SDK plugin Jatahku (Plugin H2; 03-workflow.md baris H2, AGENTS.md "Plugin dan ruang" aturan 4).

Kode di `app/plugins/<id>/` hanya mengimpor nama di `__all__` modul ini (`from app.plugins.sdk import …`, bukan
submodulnya) dan paketnya sendiri. Validator CI menolak impor `app.models`, `app.api`, `app.services`, `app.bot`,
`app.core`, `app.plugins.host`, kode plugin lain di luar `requires`, dan jalan pintas introspeksi (`app/plugins/host/kode.py`).
Izin per jenis fungsi: kartu, cek, aturan advisor, perintah bot, dan field form hanya membaca; `notifications:send`
hanya untuk job.

Titik ekstensi server dan bentuknya:

| Dekorator | Fungsi | Dipanggil oleh |
| --- | --- | --- |
| `plugin.kartu(key)` | `async (ctx, pengaturan, PeriodeView) -> dict` bentuk kartu | `POST /dashboard/data` (registry B1) |
| `plugin.cek(key)` | `async (ctx, RencanaPengeluaran) -> list[str]` peringatan | `expense_rules.peringatan_plugin` |
| `plugin.aturan_advisor(kode)` | `async (ctx) -> list[Saran]` | AI Advisor (`select.py`, batas per plugin) |
| `plugin.perintah_bot(cmd)` | `async (ctx) -> str` | Telegram dan chat web, hanya baca |
| `plugin.job(key)` | `async (ctx) -> None`, idempoten | scheduler tiap jam |
| `plugin.field_form(target, key)` | `async (ctx, nilai) -> nilai` | `titik.periksa_field` (disambungkan ke form di U2) |
| `plugin.rute(metode, pola)` | `async (ctx, Permintaan) -> data atau Jawaban` | `/p/<id>/<pola>` (U1; owner/admin, plugin aktif) |

`ctx.notify(...)` mengirim notifikasi dari job (`notifications:send`); kamus Catat cepat (`nlp_kamus`) cukup data di
manifest. `ctx.data("<entitas>")` (U1) membaca dan menulis tabel plugin sendiri (`entities` manifest) di ruang konteks;
tulis hanya dari `rute` non-GET. Galat dari `rute`: `GalatRute(status, kode, detail)` atau `NilaiTidakSah` (422).
"""
from app.plugins.sdk.context import (
    AksiRoute, AmplopView, AnggotaView, DataPlugin, GalatRute, IzinDitolak, Jawaban, NilaiTidakSah, PemasukanView,
    PenggunaView, PeriodeView, Permintaan, PluginContext, RencanaPengeluaran, Saran, TransaksiView,
)
from app.plugins.sdk.plugin import Plugin

__all__ = [
    "AksiRoute", "AmplopView", "AnggotaView", "DataPlugin", "GalatRute", "IzinDitolak", "Jawaban", "NilaiTidakSah",
    "PemasukanView", "PenggunaView", "PeriodeView", "Permintaan", "Plugin", "PluginContext", "RencanaPengeluaran",
    "Saran", "TransaksiView",
]
