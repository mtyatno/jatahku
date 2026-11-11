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
| B3 | #140 | Verifikasi dan rilis Beranda registry | 1 Beranda registry | 2 | B2 | selesai | Pemilik produk + Claude | #167, #168, #172 | 2026-11-01 | 2026-11-01 |
| R1 (migrasi) | #141 | Model ruang | 2 Ruang usaha | 2,5 | F0 | selesai | Pemilik produk + Claude | #161 | 2026-11-01 | 2026-11-01 |
| R2 (review) | #142 | Resolver `ruang_aktif` (2 sesi, 1 PR) | 2 Ruang usaha | 7 | R1 | selesai | Pemilik produk + Claude | #166 | 2026-11-01 | 2026-11-01 |
| R3 (review) | #143 | Ruang dari objek saat menulis | 2 Ruang usaha | 3 | R2 | selesai | Pemilik produk + Claude | #171 | 2026-11-01 | 2026-11-01 |
| R4 | #144 | Membuat dan berpindah ruang | 2 Ruang usaha | 3,5 | R3 | selesai | Pemilik produk + Claude | #174 | 2026-11-01 | 2026-11-01 |
| R5 (migrasi, review) | #145 | Peran, batasan, persetujuan di server | 2 Ruang usaha | 4 | R3 | selesai | Pemilik produk + Claude | #175 | 2026-11-01 | 2026-11-04 |
| R6 | #146 | Halaman Anggota dan batasan, Beranda karyawan | 2 Ruang usaha | 3,5 | R4, R5, B2 | selesai | Pemilik produk + Claude | #185 | 2026-11-04 | 2026-11-04 |
| R7 (migrasi, review) | #147 | Catat cepat dan kamus per ruang | 2 Ruang usaha | 4 | R3, R6 | selesai | Pemilik produk + Claude | #191 | 2026-11-04 | 2026-11-05 |
| R8 | #148 | Prive dua sisi | 2 Ruang usaha | 2,5 | R3 | selesai | Pemilik produk + Claude | #177 | 2026-11-01 | 2026-11-04 |
| H1 (migrasi, review) | #149 | Host inti | 3 Host plugin | 4 | B1, R3 | selesai | Pemilik produk + Claude | #176 | 2026-11-01 | 2026-11-04 |
| H2 (review) | #150 | PluginContext dan titik ekstensi server | 3 Host plugin | 4 | H1 | selesai | Pemilik produk + Claude | #186 | 2026-11-04 | 2026-11-04 |
| H3 | #151 | Host di frontend dan halaman Fitur Tambahan | 3 Host plugin | 3,5 | H2, B2, R4 | selesai | Pemilik produk + Claude | #192 | 2026-11-04 | 2026-11-05 |
| U1 (migrasi, review) | #152 | Kerangka Buku Usaha dan Kontak | 4 Buku Usaha | 3,5 | H3, R5 | selesai | Pemilik produk + Claude | #196 | 2026-11-05 | 2026-11-09 |
| U2 | #153 | Penjualan dan alokasi omzet | 4 Buku Usaha | 3,5 | U1 | selesai | Pemilik produk + Claude | #201, #202 (review keamanan) | 2026-11-09 | 2026-11-10 |
| U3 | #154 | Laba rugi dan laporan | 4 Buku Usaha | 3,5 | U2, R8 | review | Pemilik produk + Claude | #204, #207 (review keamanan) | 2026-11-10 | |
| U4 | #155 | Kartu Beranda dan arus kas | 4 Buku Usaha | 3,5 | U3, B3 | belum | | | | |
| U5 | #156 | Catat cepat versi usaha dan AI Advisor | 4 Buku Usaha | 3,5 | U2, R7 | belum | | | | |
| U6 | #157 | Chat dan notifikasi admin | 4 Buku Usaha | 2,5 | U3, R5 | belum | | | | |
| V1 | #158 | Verifikasi dan rilis beta | 5 Beta | 2 | Semua | belum | | | | |

## Gerbang

| Gerbang | Syarat lulus | Diuji di | Status |
|---|---|---|---|
| B | Angka dan tampilan Beranda sama untuk semua user; `POST /dashboard/data` p95 ≤ 500 ms | B3 | lulus 1 Nov (keputusan pemilik): paritas produksi 105 user ok, 0 beda/crash, p95 231 ms; Beranda registry menyala untuk pemilik; perluasan flag ke `*` oleh pemilik; banding tampilan otomatis tidak dijalankan |
| R | Angka user lama identik sebelum dan sesudah refactor; nol kebocoran antar-ruang (tes IDOR); chat tetap ruang keluarga | R2, R3, R8 | **lulus 4 Nov** (R2, R3, R8 lulus; produksi `ruang_paritas` 109/109 ok, 0 beda/crash, sesudah deploy R8 #177 dan R6 #185): R2 lulus (tes paritas 40 endpoint GET, IDOR, bot ruang keluarga; produksi `ruang_paritas` 105/105 ok, 1 Nov); R3 lulus (tulis dari objek, IDOR tulis + buat dengan 404 persis, lintas ruang, antrean offline, kuota per ruang; review keamanan #171; produksi `ruang_paritas` 105/105 ok sesudah deploy, 1 Nov); R4 menambah saklar flag ruang usaha (tes `test_ruang_r4.py`); R5 menambah tolak-bawaan karyawan, batasan, dan persetujuan (tes `test_ruang_peran.py`); R8 di tes (prive hanya owner, karyawan 403 `khusus_admin` lewat R5, tujuan ruang keluarga dari server, ruang orang lain 404, satu commit, idempoten); deploy R8 terverifikasi 4 Nov (run 41785622123), paritas produksi sesudahnya 109/109 ok; R6 tidak mengubah angka ruang keluarga (katalog dan template Beranda umum sama, tes `test_dashboard_registry.py`) dan menambah tes Beranda karyawan tanpa kartu umum (`test_ruang_r6.py`), deploy terverifikasi 4 Nov (run 41811270106), uji dua akun di produksi sesuai checklist; R7 menambah tes kamus ruang tidak terbawa ke ruang keluarga, ruang usaha lain, atau bot, tawaran pengeluaran pribadi tanpa kueri lintas ruang, dan satu `client_ref` = satu catatan (`test_ruang_r7.py`; review keamanan #191 dua putaran, lulus 5 Nov); deploy R7 terverifikasi 5 Nov (run 41924470565, sesudah migrasi `d7r7k4a1m9c3`), paritas produksi sesudahnya 109/109 ok, 0 beda/crash |
| H | Buku Usaha bisa dipasang, dijeda, dilanjutkan, dicopot, dan dipulihkan bersih; tes isolasi lulus | U1 | **lulus 9 Nov** (produksi, oleh pemilik: migrasi `u1b0k0u5aha1`, `ruang_paritas` 0, checklist "Plugin U1" langkah 4–5: pasang → wizard → Kontak → jeda/lanjut → unduh JSON/CSV → copot → pulihkan → saklar darurat → akun karyawan 403 → audit; sebelumnya `test_plugin_u1` dan browser lokal 5 Nov, review keamanan #196 dengan temuan 1–5 diperbaiki). Flag `plugin_buku_usaha_users` = pemilik sampai beta |
| Rilis | Review keamanan terpisah lulus; angka ruang keluarga tetap identik; flag per ruang siap | V1 | belum |
| Beta | 10 UMKM aktif selama 4 minggu tanpa insiden data | V1 + 4 minggu | belum |
