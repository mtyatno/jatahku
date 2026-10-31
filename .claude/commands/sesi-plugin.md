---
description: Buka sesi kerja plugin dan ruang usaha Jatahku untuk satu kode sesi (mis. B1, R2, U3)
argument-hint: <kode sesi, mis. B1>
---

Buka sesi kerja plugin dan ruang usaha Jatahku dengan kode sesi **$ARGUMENTS**.

1. Cari baris `$ARGUMENTS` di `docs/plugin/PROGRESS.md` (kolom Sesi diawali kode itu, mis. `R5 (migrasi, review)`). Sebutkan nama sesi, fase, nomor issue, tandanya (migrasi, review), dan apakah sesi ini sedang jeda atau baru dimulai. R2 memakai dua sesi di satu branch dan satu PR: sebutkan sesi ke berapa. Kalau kode tidak ditemukan, berhenti dan tanyakan.
2. Baca: `docs/plugin/00-indeks.md`; `docs/plugin/03-workflow.md` bagian "Urutan fase dan gerbang", baris sesi ini di "Daftar sesi", "Keamanan lebih dulu", "Cara kerja", dan "Template PR"; `docs/plugin/02-adr.md`; bagian "Plugin dan ruang" di `AGENTS.md`; entri terakhir `docs/plugin/SESI-LOG.md` (terutama untuk sesi ini); issue GitHub sesi ini; dan bagian `docs/plugin/04-kontrak-api.md`, `05-desain-buku-usaha.md`, atau `01-kajian.md` yang disebut baris sesinya.
3. Cek dependensi di kolom "Butuh": bila ada yang belum `selesai` di `PROGRESS.md`, atau gerbang yang disyaratkan belum lulus (mis. U2 butuh Gerbang H), berhenti dan laporkan. Cek juga PR terbuka (mis. `gh api "repos/mtyatno/jatahku/pulls?state=open"`) dan baris `berjalan` di `docs/mobile/PROGRESS.md` serta `docs/ai-advisor/PROGRESS.md` yang menyentuh file yang sama (`Dashboard.jsx`, `Layout.jsx`, `api.js`, `bot/handlers.py`, `plan_limits.py`); bila ada, laporkan sebelum mulai.
4. `git fetch origin main`, lalu lanjutkan branch `plugin/<kode>-*` bila sudah ada di remote, atau buat baru dari `origin/main` dengan nama `plugin/<kode huruf kecil>-<slug>` (mis. `plugin/r2-ruang-aktif`).
5. Rangkum dalam maksimal 6 baris: target sesi ini, file yang boleh disentuh, tes yang harus hijau (termasuk workflow "Migrasi" bila sesi bertanda migrasi), ADR yang berlaku, flag yang menyembunyikan pekerjaan yang belum siap, dan risiko keamanan. **Tunggu "lanjut" sebelum mengubah kode.**
6. Selama bekerja: jalankan tes setiap kali satu bagian selesai; jangan menyentuh file di luar scope tanpa bertanya; temuan di luar scope dicatat, tidak dikerjakan diam-diam. Temuan keamanan dilaporkan segera dan dikerjakan sebelum fitur dilanjutkan. Bentuk API baru atau yang berubah ditulis di `04-kontrak-api.md` di PR yang sama.
