# AI Advisor v2 — catatan serah-terima

Entri terbaru di atas. Format: **Sesi · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## S0 · 2026-10-16 · pemilik produk + Claude

**Selesai**
- `docs/ai-advisor/` dibuat: 00-indeks, 01-desain, 02-aturan (revisi 1, disetujui), 03-workflow, 04-kontrak-api, PROGRESS, SESI-LOG.
- `AGENTS.md`: bagian "AI Advisor v2" (6 aturan kerja); bagian "Advisor Insights Engine" lama diperbarui (path `advisor.py` sudah jadi paket).
- CI tes baru `.github/workflows/test.yml`: unittest backend + `node --test` + build frontend di setiap PR dan push ke `main`. Deploy tetap di `deploy.yml`.
- `requirements-test.txt`: `slowapi`, `email-validator`, `aiosqlite` (dipakai app/tes tapi tidak tercantum di `requirements.txt`).
- Issue GitHub per sesi (S1–S19) + label `ai-advisor`, `migrasi`, `paralel` + milestone Fase 1–4.

**Jebakan**
- Di `main` per `31eb446`, 14 tes merah: `test_income_type_safe_daily` (13) dan `test_prediction_rollover` (1). Penyebabnya mock `db_with(...)` kurang satu hasil untuk query `_income_totals` yang ditambahkan ke `/analytics/prediction`. Sudah diperbaiki di tes saja (tanpa mengubah kode app). Mock berurutan seperti ini rapuh: sesi S1/S3 yang memindah prediction ke `metrics.py` sebaiknya menulis tes baru berbasis fixture snapshot, bukan menambah urutan mock.
- Tanpa `slowapi`/`email-validator` terpasang, 10 modul tes gagal import. Di VPS keduanya terpasang manual. Pasang dari `requirements-test.txt` untuk menjalankan tes lokal.
- Repo publik: nama anggota keluarga di contoh spesifikasi diganti fiktif ("Rina"). Jangan menaruh data user nyata di fixture atau dokumen.

**Baseline tes:** backend 582 tes OK · frontend 240 tes OK · build OK.

**Lanjut ke S1:** prompt pembuka di `03-workflow.md` §3 dengan SN = S1, issue "AI Advisor S1". Baca `02-aturan.md` §1, §3, §14 dan `app/services/advisor/context.py` (loader yang diperluas jadi `snapshot.py`).
