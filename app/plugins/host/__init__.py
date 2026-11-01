"""Host plugin (Plugin H1; docs/plugin/03-workflow.md baris H1, 04-kontrak-api.md §5).

- `manifest.py` — skema manifest, daftar izin, aturan T1 (ADR-P9, P14).
- `registry.py` — memuat `app/plugins/<id>/manifest.json` saat start dan memeriksa aturan antarplugin.
- `validator.py` — `python -m app.plugins.host.validator`: gagal (kode keluar 1) bila ada manifest tidak sah.
- `siklus.py` — status per ruang (pasang, lanjut, jeda, copot, pulihkan, bersihkan), audit, saklar darurat,
  flag rollout, hak. Satu-satunya penulis `plugin_installations` dan `plugin_audit_log`.
"""
