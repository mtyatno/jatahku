"""Plugin Jatahku (Fitur Tambahan di UI, ADR-P10).

- `host/` — manifest, pemuat, validator, siklus status per ruang, saklar darurat (H1).
- `sdk/` — `PluginContext` dan titik ekstensi server (H2).
- `<id>/` — satu folder per plugin, berisi `manifest.json` (mis. `buku_usaha/`, U1).

Hanya plugin tingkat T1 (buatan Jatahku sendiri, ikut rilis; ADR-P9). Aturan: `AGENTS.md`,
"Plugin dan ruang"; rencana: `docs/plugin/`.
"""
