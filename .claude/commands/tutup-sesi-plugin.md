---
description: Tutup sesi kerja plugin dan ruang usaha Jatahku (tes, progres, catatan serah-terima, PR)
---

Tutup sesi kerja plugin ini, walau sesinya belum selesai.

1. Jalankan tes: `python -m unittest discover -s app/tests -t .` dan `cd frontend && node --test src/lib/*.test.js && npm run build` (kembalikan `frontend/dist/` dengan `git checkout -- frontend/dist` sebelum commit). Bila sesi menyentuh model atau migrasi, jalankan juga `.github/scripts/cek-migrasi.sh origin/main` di database PostgreSQL kosong (lihat `AGENTS.md`, "Database Schema"). Laporkan hasilnya.
2. Cocokkan pekerjaan dengan checklist di `docs/plugin/03-workflow.md`, "Template PR", dan gerbang keamanan sesi ini di "Keamanan lebih dulu". Yang belum terpenuhi ditulis apa adanya di PR.
3. Perbarui baris sesi ini di `docs/plugin/PROGRESS.md` (status: berjalan / jeda / review / selesai / terhambat, pemilik, PR, tanggal) dan tabel Gerbang bila sesi ini menguji gerbang. Bila bentuk API berubah, pastikan `docs/plugin/04-kontrak-api.md` ikut diperbarui.
4. Tambahkan entri di atas `docs/plugin/SESI-LOG.md`: kode sesi, nama, tanggal, siapa — selesai, digantung, jebakan, keputusan kecil, perintah untuk melanjutkan.
5. Stage file satu per satu (**jangan `git add -A`**), commit, push. Buka PR berjudul `Plugin <kode>: <nama>` dengan template di `docs/plugin/03-workflow.md` ("Template PR"), `Closes #<issue>`, label `plugin` (plus `migrasi` dan `review-keamanan` sesuai tanda sesi). Bila belum selesai, PR draft berjudul `WIP Plugin <kode>: <nama>` dengan "Status jeda" di deskripsi dan tanpa `Closes`. PR bertanda review: sebutkan bahwa PR menunggu review sesi keamanan terpisah ("review PR #N terhadap 03-workflow.md bagian keamanan"). Jangan merge.
6. Bila PR sesi ini (atau PR plugin sebelumnya yang belum dicek) sudah di-merge, jalankan langkah `/cek-deploy <nomor PR>` dan sertakan hasilnya. Untuk PR bermigrasi, ingatkan "Urutan merge PR bermigrasi" di `AGENTS.md`.
7. Beri saya satu baris untuk tracker "Tracker Plugin Jatahku" di claude.ai: `<kode sesi> · status · pemilik · link PR · mulai · selesai · deploy (terverifikasi / belum di-merge / gagal) · catatan singkat`.
