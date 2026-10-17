---
description: Tutup sesi kerja mobile Jatahku (tes, progres, catatan serah-terima, PR)
---

Tutup sesi kerja mobile ini, walau paketnya belum selesai.

1. Jalankan tes: `python -m unittest discover -s app/tests -t .` dan `cd frontend && node --test src/lib/*.test.js && npm run build` (kembalikan `frontend/dist/` sebelum commit). Untuk `mobile/`, jalankan tes/ build yang relevan. Laporkan hasilnya.
2. Perbarui `docs/mobile/PROGRESS.md` untuk paket ini (status: berjalan / jeda / review / selesai / terhambat, pemilik, PR, tanggal).
3. Tambahkan entri di atas `docs/mobile/SESI-LOG.md`: kode sesi, paket, tanggal, siapa — selesai, digantung, jebakan, keputusan kecil, perintah untuk melanjutkan.
4. Stage file satu per satu (**jangan `git add -A`**), commit, push. Buka PR dengan template di `docs/mobile/03-workflow.md` §4; bila belum selesai, PR draft berjudul `WIP` dengan "Status jeda" di deskripsi.
5. Bila PR paket ini (atau PR sebelumnya yang belum dicek) sudah di-merge, jalankan langkah `/cek-deploy <nomor PR>` dan sertakan hasilnya. Jangan menulis "tidak bisa dicek produksi": deploy diverifikasi lewat hasil workflow `deploy.yml` di GitHub.
6. Beri saya satu baris untuk tracker claude.ai: `<kode sesi> · <wbs> · status · link PR · deploy (terverifikasi / belum di-merge / gagal) · catatan singkat`.
