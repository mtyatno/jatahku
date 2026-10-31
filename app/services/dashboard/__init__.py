"""Beranda berbasis registry (Plugin B1): registry kartu, penyedia data, tata letak, batch.

Peta: `registry.py` (definisi kartu + template), `providers.py` (penyedia per kartu inti),
`sources.py` (endpoint lama yang dimuat sekali per permintaan), `batch.py` (`POST /dashboard/data`),
`layout.py` (`GET`/`PUT /dashboard/layout`). Kontrak: docs/plugin/04-kontrak-api.md §4.
"""
