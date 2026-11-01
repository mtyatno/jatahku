# Plugin — progres sesi

Diubah **di PR sesi itu sendiri** (lihat `03-workflow.md`, "Cara kerja"). Status: belum · berjalan · jeda · review · selesai · terhambat. Kolom Status sampai Selesai sama dengan artifact "Tracker Plugin Jatahku" di claude.ai.

Rincian tiap sesi (file, hasil, gerbang) ada di `03-workflow.md`, "Daftar sesi", dan di issue GitHub-nya. Tanda "migrasi" berarti PR-nya menambah migrasi Alembic (label `migrasi`, checklist deploy di `AGENTS.md`); "review" berarti PR-nya wajib direview sesi keamanan terpisah sebelum merge (label `review-keamanan`).

Dua jalur boleh berjalan bersamaan setelah F0: Beranda registry (B1–B3) dan ruang usaha (R1–R8). Bila dikerjakan sendiri, mulai dari B1. Gerbang host (Gerbang H) diuji di U1; U2 baru dimulai setelah gerbang itu lulus.

| Sesi | Issue | Nama | Fase | Jam | Butuh | Status | Pemilik | PR | Mulai | Selesai |
|---|---|---|---|---|---|---|---|---|---|---|
| O1 | — | Keputusan pemilik produk yang tersisa (12 rekomendasi menjadi ADR-P8–P19) | 0 Persiapan | — | — | selesai | Pemilik produk + Claude | — | 2026-10-31 | 2026-10-31 |
| F0 | #137 | Bootstrap repo dan CI migrasi | 0 Persiapan | 2 | O1 | selesai | Pemilik produk + Claude | #159 | 2026-10-31 | 2026-10-31 |
| B1 (migrasi) | #138 | Registry kartu dan data batch | 1 Beranda registry | 3,5 | F0 | selesai | Pemilik produk + Claude | #162 | 2026-11-01 | 2026-11-01 |
| B2 | #139 | Beranda dari registry | 1 Beranda registry | 3,5 | B1 | selesai | Pemilik produk + Claude | #165 | 2026-11-01 | 2026-11-01 |
| B3 | #140 | Verifikasi dan rilis Beranda registry | 1 Beranda registry | 2 | B2 | berjalan | Pemilik produk + Claude | #PR | 2026-11-01 | |
| R1 (migrasi) | #141 | Model ruang | 2 Ruang usaha | 2,5 | F0 | selesai | Pemilik produk + Claude | #161 | 2026-11-01 | 2026-11-01 |
| R2 (review) | #142 | Resolver `ruang_aktif` (2 sesi, 1 PR) | 2 Ruang usaha | 7 | R1 | review | Pemilik produk + Claude | #166 | 2026-11-01 | |
| R3 (review) | #143 | Ruang dari objek saat menulis | 2 Ruang usaha | 3 | R2 | belum | | | | |
| R4 | #144 | Membuat dan berpindah ruang | 2 Ruang usaha | 3,5 | R3 | belum | | | | |
| R5 (migrasi, review) | #145 | Peran, batasan, persetujuan di server | 2 Ruang usaha | 4 | R3 | belum | | | | |
| R6 | #146 | Halaman Anggota dan batasan, Beranda karyawan | 2 Ruang usaha | 3,5 | R4, R5, B2 | belum | | | | |
| R7 (migrasi, review) | #147 | Catat cepat dan kamus per ruang | 2 Ruang usaha | 4 | R3, R6 | belum | | | | |
| R8 | #148 | Prive dua sisi | 2 Ruang usaha | 2,5 | R3 | belum | | | | |
| H1 (migrasi, review) | #149 | Host inti | 3 Host plugin | 4 | B1, R3 | belum | | | | |
| H2 (review) | #150 | PluginContext dan titik ekstensi server | 3 Host plugin | 4 | H1 | belum | | | | |
| H3 | #151 | Host di frontend dan halaman Fitur Tambahan | 3 Host plugin | 3,5 | H2, B2, R4 | belum | | | | |
| U1 (migrasi, review) | #152 | Kerangka Buku Usaha dan Kontak | 4 Buku Usaha | 3,5 | H3, R5 | belum | | | | |
| U2 | #153 | Penjualan dan alokasi omzet | 4 Buku Usaha | 3,5 | U1 | belum | | | | |
| U3 | #154 | Laba rugi dan laporan | 4 Buku Usaha | 3,5 | U2, R8 | belum | | | | |
| U4 | #155 | Kartu Beranda dan arus kas | 4 Buku Usaha | 3,5 | U3, B3 | belum | | | | |
| U5 | #156 | Catat cepat versi usaha dan AI Advisor | 4 Buku Usaha | 3,5 | U2, R7 | belum | | | | |
| U6 | #157 | Chat dan notifikasi admin | 4 Buku Usaha | 2,5 | U3, R5 | belum | | | | |
| V1 | #158 | Verifikasi dan rilis beta | 5 Beta | 2 | Semua | belum | | | | |

## Gerbang

| Gerbang | Syarat lulus | Diuji di | Status |
|---|---|---|---|
| B | Angka dan tampilan Beranda sama untuk semua user; `POST /dashboard/data` p95 ≤ 500 ms | B3 | alat siap (PR #PR); menunggu `beranda_paritas` di VPS + banding tampilan, lalu flag `*` |
| R | Angka user lama identik sebelum dan sesudah refactor; nol kebocoran antar-ruang (tes IDOR); chat tetap ruang keluarga | R2, R3, R8 | sebagian: bagian R2 lulus di tes (paritas tanpa header untuk 40 endpoint GET, IDOR baca/tulis, bot ruang keluarga); produksi `ruang_paritas` setelah merge; R3, R8 menyusul |
| H | Buku Usaha bisa dipasang, dijeda, dilanjutkan, dicopot, dan dipulihkan bersih; tes isolasi lulus | U1 | belum |
| Rilis | Review keamanan terpisah lulus; angka ruang keluarga tetap identik; flag per ruang siap | V1 | belum |
| Beta | 10 UMKM aktif selama 4 minggu tanpa insiden data | V1 + 4 minggu | belum |
