"""Validator manifest untuk CI (Plugin H1; 01-kajian.md "Pengujian" no. 1).

    python -m app.plugins.host.validator            # semua plugin di app/plugins/
    python -m app.plugins.host.validator <folder>   # folder lain (tes)

Kode keluar 0 = semua manifest sah; 1 = ada galat (dicetak satu per baris). Dijalankan di workflow "Tes"
(langkah "Validator manifest plugin") dan lewat `app/tests/test_plugin_host.py`.

Pemeriksaan bahwa setiap pemanggilan `PluginContext` sesuai izin yang dideklarasikan menyusul di H2,
bersama `PluginContext` itu sendiri.
"""
import pathlib
import sys

from app.plugins.host.registry import FOLDER_PLUGIN, ManifestTidakSah, muat


def main(argv: list[str]) -> int:
    folder = pathlib.Path(argv[0]) if argv else FOLDER_PLUGIN
    try:
        reg = muat(folder, ketat=True)
    except ManifestTidakSah as e:
        for g in e.galat:
            print(f"GALAT {g}")
        return 1
    print(f"OK: {len(reg.plugins)} plugin sah ({', '.join(reg.plugins) or 'belum ada'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
