# Laporan berkala — desain

**Tanggal:** 1 Nov 2026
**Status:** desain disetujui pemilik produk di chat, bagian 1–5 (1 Nov 2026); spec tertulis disetujui 1 Nov 2026. Tahap 2 (email) diimplementasi 5 Nov 2026 di branch `feat/laporan-berkala-email` (belum tayang; menunggu review akhir dan merge).
**Tahap 1 tayang 5 Nov 2026:** PR #190 (squash `56ddf74`), revisi alembic `967a27d0c15d` dan checklist deploy di
`AGENTS.md` ("Laporan berkala tahap 1") dijalankan pemilik; job pertama (5 Nov 04.30 WIB) menerbitkan 21 laporan, semuanya
diberi tahu, dan unduh PDF berkata sandi dicoba pemilik. Perilaku final tahap 1: `docs/laporan-berkala.md`. Yang berubah dari desain ini tercatat di "Penyesuaian saat
menyusun rencana" dan "Penyesuaian saat eksekusi" di bawah; keputusan pemilik produk 1–12 tidak berubah. Tahap 3
belum dimulai; tahap 2 lihat Status di atas. Rencana tahap 1: `docs/superpowers/plans/2026-11-01-laporan-berkala-tahap-1.md`.
**Dasar:** `main` setelah siklus household (#169) dan penandaan checklist-nya (#173). Siklus anggaran milik household
(`households.payday_day`, penulis tunggal `app/services/household_cycle.py`, lihat `docs/siklus-household.md`), dan
`monthly_snapshots.allocated_amount`/`spent_amount` terisi untuk seluruh riwayat.

## Penyesuaian saat menyusun rencana (1 Nov 2026)

Membaca kode saat menyusun rencana tahap 1 menghasilkan tujuh keputusan berikut (rencana, bagian "Keputusan rencana").
Bagian 1–13 di bawah tetap rancangan yang disetujui; bila berbeda, butir di sini dan di "Penyesuaian saat eksekusi"
yang berlaku.

1. **Batas frekuensi** (bagian 8) memakai slowapi di memori proses API dengan kunci per user pola
   `/transactions/transcribe`, bukan penghitung Redis baru. Kuncinya diganti saat eksekusi (R11/R12).
2. **Langganan terbayar** (bagian 2d) = transaksi di jendela laporan yang keterangannya diawali penanda tombol Bayar
   (`BILL_MARKER` `"🔄 "`, `app/services/advisor/snapshot.py`), bukan `compute_bills`, yang membaca `next_run` saat ini dan
   tidak cocok untuk periode yang sudah tutup.
3. **`email_status` dibiarkan NULL di tahap 1** (bagian 6c); tahap 2 hanya mengisi status untuk laporan yang terbit
   setelah tahap 2 tayang, jadi tidak ada email tertunda untuk laporan lama.
4. **FK** (bagian 2a–2b): `reports.user_id` ON DELETE CASCADE, `reports.household_id` ON DELETE SET NULL (laporan mantan
   anggota tetap ada saat household dihapus), `report_settings.user_id` CASCADE; ditambah penanganan eksplisit di hapus
   dan gabung akun (bagian 8).
5. **`data.email`** (ringkasan tanpa nominal, bagian 6b) sudah dihitung dan dibekukan bersama laporan sejak tahap 1.
6. **Prasyarat snapshot** (bagian 3 langkah 3) = ada ≥ 1 snapshot kunci periode itu di antara amplop household (aktif
   atau tidak); job snapshot menulis satu household di bawah `household_lock` yang sama.
7. **Kata sandi tersimpan yang tidak terbaca** (kunci diganti; bagian 4 dan 9) diperlakukan seperti belum diatur (409
   `kata_sandi_belum_diatur`) dan dicatat sebagai warning.

## Penyesuaian saat eksekusi (1–4 Nov 2026)

Review per tugas menghasilkan keputusan berikut ("ruling" di catatan eksekusi; daftar lengkap R1–R16 di lampiran
rencana; R15 dan R16 dari review akhir seluruh branch). Yang di sini mengubah perilaku dari bagian di bawah atau dari
rencana, dan diuji di tugasnya.

- **R2, tagihan berikut** (bagian 2c butir 6): `langganan.jatuh_tempo` hanya untuk amplop yang menjadi baris laporan;
  tagihan di amplop yang dibuat sesudah periode tutup tidak ikut (jarang dalam jendela 7 hari).
- **R3, total pembanding** (bagian 2c butir 3, 2d): total periode lalu dan rata-rata 3 periode dijumlahkan dari semua
  amplop lingkup yang punya snapshot periode itu, bukan dari baris laporan sekarang, supaya tren tidak melompat saat
  amplop dibuat atau ditutup; angka per amplop tetap per baris.
- **R4/R9, refresh snapshot sebelum membangun** (bagian 3 langkah 4, 2e): di dalam `household_lock`, sebelum memuat
  bahan, job menulis ulang snapshot periode yang baru tutup (`create_monthly_snapshots(..., force=True)` untuk household
  itu) dan mengosongkan cache advisor-nya. Snapshot dibekukan 00:05, sedangkan mutasi membaca transaksi hidup, jadi
  transaksi bertanggal mundur memecah Σ mutasi = terpakai. R9: hanya bila masih ada calon penerima dan household punya
  transaksi atau alokasi di jendela; refresh yang error menunda household itu ke jam berikutnya.
- **R5, persen terpakai** (bagian 2c butir 1, 6b): `ringkasan.persen_terpakai` (dan `email.persen_terpakai`) tanpa
  amplop tabungan (`saving`/`sinking_fund`, `hitung.adalah_tabungan`) di pembilang dan penyebut, sama dengan Beranda;
  total rupiah tetap atas semua baris.
- **R6, amplop aman** (bagian 2c butir 7): `sorotan.amplop_aman` juga mengecualikan amplop berstatus `lewat_batas`.
- **R7, streak saat terbit** (bagian 2c butir 7): dari `streak.get_streak` (0 bila sudah putus), sama dengan layar
  aplikasi, bukan `user_streaks.current_streak` mentah.
- **R8, amplop yang dibuat sesudah periode** (bagian 2d): amplop yang tanggal UTC `created_at`-nya sesudah akhir periode
  tidak menjadi baris walau punya snapshot kunci itu (refresh R4 memberinya snapshot nol).
- **R10, validasi kata sandi** (bagian 4): disimpan dalam bentuk NFC dan diperiksa `pdf.periksa_kata_sandi`; ditolak (422,
  kalimat siap tampil) bila memuat karakter kontrol atau dua arah bercampur, hanya karakter tak kasatmata, lebih dari 127
  byte UTF-8, atau berubah oleh SASLprep (hanya terbuka di sebagian pembaca PDF). Kata sandi tersimpan yang kini ditolak
  diperlakukan seperti token tak terbaca (409).
- **R11/R12, kunci batas frekuensi** (bagian 8, penyesuaian rencana 1): kuncinya user yang terautentikasi (`user:<sub>`
  dari access token yang sah, `kunci_per_user` di `app/core/rate_limit.py`; selainnya alamat IP), bukan hash teks header
  Authorization, yang bisa diakali dengan menulis ulang header atau login ulang. Kunci yang sama dipasang untuk
  `/transactions/transcribe` dan chat web lewat PR keamanan terpisah (#187) sebelum fitur ini.
- **R14, karyawan ruang usaha** (bagian 6): `/laporan` dan `/laporan/:id` tetap terbuka saat ruang usaha aktif dan
  user berperan karyawan (Plugin R6 mengalihkan halaman lain ke Beranda), supaya tautan notifikasi laporan berfungsi;
  endpoint laporan tidak membaca ruang aktif. Menu karyawan tidak berubah.
- **R15, anggota yang menghapus akun di laporan beku** (bagian 2c, 2e, 8): baris `data` yang memuat nama atau teks
  seorang pencatat (`terbesar[]`, `langganan.terbayar[]`, `mutasi[]`) membawa `pencatat_id` (id user, tambahan di versi
  1; `versi` tetap 1), tidak pernah ditampilkan. Hapus akun menulis ulang persis baris yang `pencatat_id`-nya akun itu di
  laporan milik user lain seperti catatan hidupnya ("Mantan anggota", "Transaksi mantan anggota"/"Pemasukan mantan
  anggota"; "Transaksi privat" tetap; angka tidak berubah), dan gabung akun mengalihkan `pencatat_id` sumber ke target
  (`app/services/laporan/pencatat.py`). Ini satu-satunya pengecualian yang disetujui untuk "beku" (bagian 2e): janji hapus
  akun (#170) mendahului; nama tidak unik, jadi tanpa id baris itu tak pernah bisa dianonimkan kelak. Benda rumah tanpa
  pembuat tersimpan (amplop, target, langganan jatuh tempo) dibiarkan, sama dengan hapus akun di aplikasi.
- **R16, keandalan dan tampilan** (bagian 3, 5, 6d): lonceng dan `notified_at` disimpan dalam satu transaksi (klaim
  `notified_at IS NULL`), Telegram sekali sesudahnya, best-effort; di akhir setiap jalan job menyapu laporan yang belum
  diberi tahu dan terbit ≤ 7 hari lalu (tanpa lonceng kedua, tanpa Telegram berulang). Snapshot yang belum ada di hari
  terakhir jendela dicatat WARNING bila household beraktivitas. Arsip `/laporan` memuat 24 per halaman dengan "Tampilkan
  lebih banyak", dan Pengaturan → Laporan punya tautan "Lihat laporan" (pintu masuk di HP selain notifikasi).

## Penyesuaian saat menyusun rencana tahap 2 (5 Nov 2026)

Membaca kode saat menyusun rencana tahap 2 menghasilkan tujuh keputusan berikut (rencana
`docs/superpowers/plans/2026-11-05-laporan-berkala-tahap-2.md`, bagian "Keputusan rencana"). Bagian 6 dan 7 di bawah tetap
rancangan yang disetujui; bila berbeda, butir di sini dan di "Penyesuaian saat eksekusi tahap 2" yang berlaku.

1. **Saklar lewat `PATCH /user/laporan-pengaturan`** (body semua opsional, 30/jam per user), bukan PUT: `PUT` tetap hanya
   kata sandi (5/jam); batas 5/jam untuk kata sandi tidak boleh ikut memakan saklar. API tetap hanya bertambah; tahap 3
   menambah `kuartalan_on`/`tahunan_on` ke PATCH ini. Spec bagian 7 menulis keduanya di PUT.
2. **Laporan yang dilewati dihidupkan lagi** (bagian 6b: dikirim bila email terverifikasi, `email_on`, dan belum pernah
   dikirim): verifikasi berhasil → laporan `dilewati` dengan alasan `belum_verifikasi` atau `tanpa_email` yang terbit ≤
   `JENDELA_TERBIT_HARI` (7) hari lalu kembali `menunggu`; `email_on` dinyalakan → alasan `dimatikan` begitu juga. Yang
   lebih tua tidak dikirim.
3. **Jeda coba ulang 55 menit** untuk "paling cepat 1 jam" (bagian 6c): job jalan tiap jam di menit 30, jadi 60 menit tepat
   bisa meleset beberapa detik dan menunda satu jam lagi.
4. **`GET /laporan/berhenti-email` tidak pernah mengubah apa pun**: pemindai tautan di layanan email membuka GET. Hanya
   POST (tombol halaman dan one-click RFC 8058) mematikan `email_on`.
5. **Klaim kirim** `menunggu → mengirim` dengan `UPDATE … WHERE email_status = 'menunggu'` (cek rowcount), pola klaim
   notifikasi R16: job terjadwal dan jalan manual dari shell tidak mengirim dua kali.
6. **Lampiran jatuh dengan anggun:** token kata sandi tak terbaca atau kata sandi yang kini ditolak → tanpa lampiran,
   baris "atur kata sandi" (sama dengan 409 di unduh); kunci server tidak ada atau galat PDF tak terduga → tanpa lampiran,
   baris "unduh di aplikasi". Email tetap terkirim.
7. **Laporan tahap 1 (`email_status` NULL) tidak pernah dikirim** (keputusan rencana tahap 1 butir 3).

## Penyesuaian saat eksekusi tahap 2 (5 Nov 2026)

Review per tugas (Task 1–8, subagent-driven) dan review akhir (F-n) menghasilkan keputusan berikut; diuji di tugasnya dan
dijabarkan di `docs/laporan-berkala.md` bagian "Email laporan".

- **R-T3-1, batas waktu SMTP 30 detik** untuk setiap email (`email_service.SMTP_TIMEOUT`, di `_deliver`): antrean berjalan
  di dalam job per jam (`max_instances=1`), jadi server SMTP yang macet harus gagal cepat dan tidak menahan jam berikutnya.
- **R-T3-2, setiap klaim adalah satu percobaan** (mengganti "percobaan tidak bertambah saat klaim basi dikembalikan" di
  rencana): UPDATE klaim mengisi `mengirim`, `email_terakhir_at` = waktu sebenarnya, dan `email_percobaan` + 1, sehingga
  `email_percobaan` menghitung klaim (kiriman pertama yang berhasil terbaca 1). Klaim `mengirim` basi (> 30 menit) atau
  gagal yang sudah mencapai 3 percobaan menjadi `gagal`/`smtp` dengan satu log error; tulis hasil hanya mendarat bila
  klaimnya masih milik jalan itu. Paling banyak 3 kiriman per laporan.
- **Email verifikasi lewat `email_service.send_verifikasi_email`** (log tanpa alamat), bukan `send_email`, yang mencatat
  "Email sent to <alamat>".
- **`GET` dan `POST /laporan/berhenti-email`** masing-masing 30/menit per IP dalam ember terpisah: GET pemindai tautan tidak
  bisa menghabiskan jatah POST one-click.
- **Saklar "Kirim laporan ke email" selalu tampil dan bisa dinyalakan**, juga tanpa email atau tanpa email terverifikasi
  (pilihan user tersimpan untuk saat emailnya siap).
- **Pesan `?email_verifikasi=` tampil sekali:** reload ambil-alih service worker (`controllerchange`) atau browser yang
  logout (dialihkan ke login) dapat menghilangkannya; verifikasinya sudah berhasil dan baris status di kartu menunjukkan
  hasilnya. Dicatat di "Batasan yang diketahui" dokumen operasional.
- **F-4, tautan verifikasi: GET menampilkan konfirmasi, POST (tombol "Verifikasi email") memverifikasi** (mengganti GET
  yang memverifikasi di bagian 6a dan 7): pemindai tautan di layanan email membuka GET; pola berhenti berlangganan.
- **F-2, `berlaku` token bertujuan wajib disebut** (`berlaku=None` = tanpa `exp`) dan tujuan `access`/`refresh` ditolak:
  argumen yang terlupa tidak pernah mencetak token tanpa kedaluwarsa.
- **F-3, tanpa `Referrer-Policy: no-referrer` per halaman:** header global `strict-origin-when-cross-origin` selalu
  menimpanya dan sudah membuang path dan query bertoken lintas origin; halaman bertoken tetap `Cache-Control: no-store`.
- **F-6, verifikasi lewat Google juga menghidupkan lagi laporan yang dilewati** (keputusan rencana 2): login atau tautan
  Google yang memverifikasi alamat akun yang sudah ada menjalankan `hidupkan_lagi` seperti tombol "Verifikasi email".

## 1. Tujuan dan keputusan

**Tujuan.** Setiap periode anggaran, user mendapat refleksi keuangan yang enak dibaca — "hadiah" yang membuatnya
kembali ke Jatahku, bukan fitur berbayar. Laporan bulanan untuk semua user; laporan kuartalan dan tahunan nilai tambah
Pro.

**Keputusan pemilik produk** (31 Okt dan 1 Nov 2026):

1. Laporan mengikuti siklus anggaran household (tanggal gajian rumah). User berpenghasilan harian tetap mendapatkannya.
2. Laporan **bulanan** untuk semua user (Basic dan Pro).
3. Laporan **kuartalan dan tahunan** hanya untuk Pro, **bawaan menyala**, bisa dimatikan di Pengaturan.
4. Dikirim lewat email: **PDF berpassword** sebagai lampiran, ringkasan di body.
5. Password PDF = **kata sandi laporan yang diatur user** (opsi A). Tanpa kata sandi, email tanpa lampiran dan berisi
   ajakan mengaturnya.
6. Email laporan **hanya ke alamat terverifikasi** (syarat keamanan).
7. Body email **tanpa nominal rupiah** (opsi A): persentase, status amplop, tren, satu sorotan.
8. Isi laporan bagian **1–8** (bagian 2c), tanpa catatan advisor (opsi A).
9. Halaman laporan lengkap **hanya layar besar**; di HP layar ringkas dengan tombol unduh PDF.
10. Notifikasi di hari laporan (lonceng + Telegram).
11. Pendekatan 1: laporan **dibekukan** saat terbit, PDF **dibuat saat diminta**, tanpa file di server.
12. Tombol top bar "Laporan" (ekspor manual PDF/CSV) diganti nama **"Ekspor"**.

**Kriteria sukses.** Di hari gajian, setiap user aktif mendapat laporan periode yang baru tutup. Angka di halaman, PDF,
dan email sama, dan cocok dengan snapshot (buku besar). PDF tidak bisa dibuka tanpa kata sandi. Tidak ada laporan
dobel, dan tidak ada email laporan ke alamat yang belum terverifikasi.

## 2. Data laporan

### 2a. Tabel `reports`

Satu baris per laporan yang terbit.

| Kolom | Isi |
|---|---|
| `id` | UUID |
| `user_id` | penerima (FK `users`) |
| `household_id` | ruang keluarga saat terbit (FK `households`) |
| `jenis` | `String(16)`: `bulanan` / `kuartalan` / `tahunan` |
| `periode_mulai`, `periode_akhir` | jendela laporan (untuk kuartalan/tahunan: awal periode pertama, akhir periode terakhir) |
| `payday_day` | tanggal gajian rumah saat terbit |
| `data` | JSON beku (bagian 2c), dengan `versi` skema |
| `terbit_at` | waktu terbit |
| `notified_at` | waktu notifikasi terkirim |
| `email_status` | `String(16)`: `menunggu` / `mengirim` / `terkirim` / `gagal` / `dilewati` |
| `email_alasan` | `String(32)`: alasan `dilewati`/`gagal` (`belum_verifikasi`, `dimatikan`, `tanpa_email`, `smtp`) |
| `email_percobaan`, `email_terakhir_at`, `email_terkirim_at` | antrean dan coba ulang (bagian 6c) |

Unik `(user_id, jenis, periode_mulai)`. Indeks `(email_status, email_terakhir_at)` untuk antrean.

### 2b. Tabel `report_settings` dan kolom `users.email_verified_at`

`report_settings` (satu baris per user, dibuat saat pertama kali diubah; tanpa baris = bawaan):

| Kolom | Bawaan |
|---|---|
| `user_id` (PK, FK `users`) | — |
| `kata_sandi_enc` (`Text`, NULL = belum diatur) | NULL |
| `email_on` (`Boolean`) | `true` |
| `kuartalan_on`, `tahunan_on` (`Boolean`) | `true` (hanya berlaku untuk Pro) |
| `updated_at` | — |

`users.email_verified_at` (`DateTime`, nullable): waktu email terakhir diverifikasi. Semua kolom dan tabel dibuat di
tahap 1 (bagian 11), sehingga tahap 2 dan 3 tanpa migrasi.

### 2c. Lingkup dan isi

**Lingkup per user:** amplop bersama ruang keluarga (`owner_id` NULL) dan amplop pribadi milik user (`owner_id` = user).
Amplop pribadi anggota lain tidak muncul. Deskripsi transaksi lewat `visibility.py` (`present_transaction` /
`masked_description`): transaksi privat anggota lain → "Transaksi privat". Agregat menghitung semua transaksi, termasuk
yang privat. Ruang usaha tidak ikut.

**Isi `data` (versi 1)** — uang disimpan sebagai string desimal, tanggal ISO:

1. `ringkasan`: pemasukan, dialokasikan, terpakai, sisa, dibawa ke periode berikut, `persen_terpakai`.
2. `amplop[]`: id, nama, emoji, `jenis` (bersama/pribadi), `tujuan` (`purpose`), awal, alokasi, terpakai, akhir,
   rollover, `status` (`aman` / `hampir_habis` / `lewat_batas` / `tabungan` / `kosong`), `pernah_lewat_batas`,
   `ditutup` (amplop yang ditutup di tengah periode).
3. `banding`: total dan per amplop untuk periode lalu dan rata-rata 3 periode sebelumnya.
4. `harian[]` (terpakai per hari) dan `hari_terboros`. Untuk kuartalan/tahunan: `per_periode[]` menggantikan `harian`.
5. `terbesar[]`: 5 pengeluaran terbesar (tanggal, amplop, keterangan tersamar, jumlah, pencatat).
6. `langganan`: terbayar di periode ini, dan yang jatuh tempo di periode berikutnya.
7. `sorotan`: hari mencatat, catat beruntun terpanjang di periode, streak saat terbit, amplop yang tidak pernah lewat
   batas, progres target tabungan.
8. `mutasi[]`: semua pemasukan (yang dicatat user) dan pengeluaran di lingkup, berurutan tanggal, keterangan tersamar,
   pencatat, `penyesuaian` untuk baris cocokkan saldo.

Plus `judul`, `periode` (mulai, akhir, gajian, `periode_tercakup[]` untuk kuartalan/tahunan), `penerima` (nama, nama
rumah), `angka_per` (tanggal terbit), dan `email` (ringkasan tanpa nominal yang sudah dirakit untuk body, bagian 6b).

### 2d. Sumber angka (tanpa rumus baru)

- **Per amplop:** `monthly_snapshots` periode itu (`allocated_amount`, `spent_amount`, `opening_balance`,
  `closing_balance`, `rollover_amount`) — buku besar yang sama dengan rantai rollover. Amplop yang ditutup di tengah
  periode tidak punya snapshot: angkanya dihitung dengan fungsi yang dipakai penulis snapshot
  (`rollover.calculate_envelope_balance` dan `snapshot_values`), sehingga total = jumlah baris.
- **Pemasukan:** definisi `analytics._income_totals` (pemasukan household yang dicatat user, `amount > 0`, tanpa
  penyesuaian cocokkan saldo). Fungsi itu dipindah ke satu fungsi layanan bersama yang dipakai analitik dan laporan.
- **Langganan terbayar:** `advisor.metrics.compute_bills` untuk jendela periode itu. **Jatuh tempo:** langganan aktif di
  lingkup dengan `next_run` di periode berikutnya.
- **Pembanding:** snapshot periode sebelumnya dan 3 periode sebelumnya (amplop tanpa snapshot di periode itu tidak
  dihitung dalam rata-rata).
- **Harian, terbesar, mutasi, hari mencatat, beruntun:** transaksi periode itu (`is_deleted` = false). Himpunan
  transaksi pengeluaran sama dengan yang dihitung `calculate_envelope_balance`, sehingga jumlah mutasi keluar per amplop
  = terpakai amplop itu (diuji). Hari mencatat dan beruntun memakai transaksi yang dicatat user sendiri.
- **Status amplop:** ambang yang sama dengan bar amplop di Beranda (`frontend/src/lib/kpiVisuals.js`): `tabungan` bila
  `purpose` `saving`/`sinking_fund`; `lewat_batas` bila saldo akhir < 0; `hampir_habis` bila terpakai ≥ 70% dari saldo
  awal; `kosong` bila tanpa alokasi dan tanpa saldo awal; selain itu `aman`. Ambang 70% jadi satu konstanta di modul
  laporan.
- **Tidak pernah lewat batas:** saldo harian = saldo awal + alokasi (menurut `income_date`) − pengeluaran (menurut
  `transaction_date`) sepanjang periode; tidak pernah < 0.
- **Target tabungan:** `goals` milik amplop di lingkup; terkumpul = saldo akhir amplopnya.
- Laporan tidak menghitung angka advisor (dana belanja, sisa bebas, laju, proyeksi); aturan "satu sumber angka"
  (`AGENTS.md`, AI Advisor v2 aturan 1) tetap terjaga.

### 2e. Beku

Setelah terbit, `data` tidak pernah diubah. Transaksi bertanggal mundur, edit, atau recompute riwayat sesudahnya tidak
mengubah laporan yang sudah terbit; laporan mencantumkan "angka per [tanggal terbit]". Deskripsi ikut beku: transaksi
yang ditandai privat belakangan tidak disamarkan di laporan lama (catatan di bagian 13).

## 3. Penerbitan

**Job `laporan_job`, tiap jam pada menit ke-30, idempoten.** Untuk setiap household `rumah_tangga` yang punya anggota:

1. Di dalam `household_lock(hid)`, baca tanggal gajian dengan `current_payday(hid)` (None → lewati).
2. Periode yang paling baru tutup: `get_closed_periods(payday, today, 1)` dengan tanggal server, sama dengan job
   snapshot. Lewati bila periode itu berakhir lebih dari **7 hari** yang lalu.
3. Prasyarat: snapshot periode itu sudah ada untuk amplop aktif household. Belum ada → lewati dan coba jam berikutnya.
4. Untuk setiap anggota yang belum punya laporan `bulanan` periode itu: bangun `data`, sisipkan baris (bentrok kunci
   unik = sudah ada, lewati).
5. Bila awal periode itu jatuh di bulan **Maret, Juni, September, atau Desember**: laporan `kuartalan` untuk anggota Pro
   dengan `kuartalan_on`, mencakup 3 periode yang dimulai di bulan-bulan kuartal itu. Bila jatuh di **Desember**:
   laporan `tahunan` untuk anggota Pro dengan `tahunan_on`, mencakup 12 periode yang dimulai Januari–Desember tahun itu.
   Riwayat yang belum lengkap: memakai periode yang ada, laporan menulis "data mulai [tanggal]".
6. Commit, lepas kunci, lalu notifikasi (bagian 6d) dan antrean email (bagian 6c) per laporan baru. Langkah 1–5
   berjalan di dalam kunci supaya data tidak dibaca di tengah recompute riwayat; notifikasi dan email di luar kunci.

**Dilewati:** akun terhapus atau diblokir (awalan email `deleted_`/`banned_`), akun yang dibuat setelah periode berakhir,
dan user yang di lingkupnya tidak ada aktivitas sama sekali (tanpa alokasi dan tanpa pengeluaran) — tidak ada laporan
kosong.

**Jam terbit.** Job snapshot jalan 00:05 waktu server (UTC, 07:05 WIB); laporan normalnya terbit ±07:30 WIB
(08:30 WITA, 09:30 WIT) di hari gajian. Jam lokal per user tidak dipakai.

**Batas 7 hari.** Server mati beberapa hari → laporan tertinggal tetap terbit selama periodenya tutup ≤ 7 hari. Saat
fitur tayang, periode yang tutup ≤ 7 hari sebelumnya ikut terbit (household gajian tanggal 1 langsung mendapat laporan
Oktober 2026), periode lebih lama tidak.

**Isolasi.** Kegagalan satu household dicatat (`logger.exception`) dan tidak menghentikan household lain.

**Jendela kuartal dan tahun** jadi fungsi murni di `app/core/period.py` (gerbang periode yang sama): kuartal = 3 kunci
periode dengan bulan awal di kuartal itu; tahun = 12 kunci dengan bulan awal Januari–Desember. Contoh gajian 25:
K4 2026 = 25 Okt 2026 – 24 Jan 2027; tahun anggaran 2026 = 25 Jan 2026 – 24 Jan 2027.

**Judul.** Periode = bulan kalender (gajian tanggal 1): "Laporan Oktober 2026". Selain itu: "Laporan 25 Sep – 24 Okt
2026". Kuartalan: "Laporan Kuartal IV 2026". Tahunan: "Laporan Tahunan 2026". Kuartal dan tahun mengikuti bulan awal
periode.

## 4. Kata sandi dan PDF

**Kata sandi laporan.** Diatur di Pengaturan → Laporan, 6–64 karakter. Disimpan terenkripsi (Fernet) dengan kunci
`REPORT_SECRET_KEY` yang hanya ada di `/opt/jatahku/.env`. API tidak pernah mengembalikannya (hanya `kata_sandi_diatur`),
log tidak pernah memuatnya. `cryptography` ditulis eksplisit di `requirements.txt`. Mengganti kata sandi berlaku untuk
unduhan dan email berikutnya; PDF yang sudah terkirim tetap dengan kata sandi lama. Tanpa `REPORT_SECRET_KEY`: API tetap
jalan, mengatur kata sandi dan membuat PDF ditolak dengan pesan jelas, startup mencatat peringatan (pola
`email_service.check_configured`).

**PDF.** **fpdf2 2.8.9** (mendukung `EncryptionMethod.AES_256`, dipatok di `requirements.txt` bersama
`cryptography==50.0.2`), A4 tegak:

- Kata sandi user = kata sandi laporan; kata sandi pemilik acak per file; mencetak dan menyalin diizinkan.
- Font Noto Sans Regular dan Bold (OFL, beserta lisensinya) di `app/assets/fonts/`; karakter di luar font (emoji)
  dibuang.
- Header: Jatahku, judul, periode, nama, nama rumah, "angka per [tanggal]". Bagian 1–7, grafik batang digambar dengan
  primitif fpdf2 (tanpa library grafik). Lampiran mutasi: tabel lintas halaman dengan judul kolom berulang. Footer
  "Halaman x dari y" dan "Dibuat otomatis oleh Jatahku".
- Teks digambar sebagai teks PDF, bukan HTML, jadi tidak ada risiko injeksi markup.
- Dibuat di thread (`asyncio.to_thread`), paling banyak 2 sekaligus (semaphore), tidak pernah disimpan ke disk.
- Nama file memuat jenis dan periode, mis. `jatahku-laporan-2026-10.pdf`, `jatahku-laporan-K4-2026.pdf`.

## 5. Halaman web dan HP

**Desktop (≥ 1024 px):**

- Menu baru **"Laporan"** di sidebar (khusus desktop, seperti Analitik).
- `/laporan`: arsip, daftar laporan per periode dan jenis (terbaru di atas).
- `/laporan/:id`: laporan lengkap bagian 1–8. Grafik recharts seperti di Analitik. Tombol "Unduh PDF". Mutasi
  ditampilkan bertahap (tidak memuat ratusan baris sekaligus).
- Frontend hanya memformat `data`; tidak menghitung ulang.
- Tombol "Laporan" di top bar (`ExportButtons`) diganti nama "Ekspor".

**HP dan tablet (< 1024 px):**

- `/laporan/:id` tampil sebagai layar ringkas: judul, periode, 3–4 angka utama, sorotan, dan tombol besar **"Unduh PDF"**.
  Notifikasi lonceng dan tautan Telegram membuka layar ini; unduhan menunggu satu ketukan (browser memblokir unduhan
  tanpa ketukan, dan kata sandi mungkin belum diatur).
- Kata sandi belum diatur → tombol membuka formulir singkat untuk mengaturnya, lalu langsung mengunduh.
- Unduhan lewat lapisan `native.files.save` (aturan mobile 1: beda platform hanya di lapisan native), sehingga aplikasi
  Android/iOS nanti memakai jalur yang sama.
- `/laporan`: daftar sederhana yang membuka layar ringkas.

Lebar layar dibaca lewat satu hook bersama `useMediaQuery` (sekarang hanya ada versi lokal di `Envelopes.jsx`).

**Banner** di halaman laporan dan layar ringkas bila email belum terverifikasi atau kata sandi belum diatur, dengan
tautan ke Pengaturan → Laporan.

**Pengaturan → bagian baru "Laporan":** status email (terverifikasi, atau belum + tombol "Kirim tautan verifikasi"),
kata sandi laporan (atur/ganti), "Kirim laporan ke email", "Laporan kuartalan", "Laporan tahunan". Dua yang terakhir:
label Pro; user non-Pro tidak bisa menyalakannya.

## 6. Email, verifikasi, notifikasi

### 6a. Verifikasi email

- **Satu tempat** yang menjaga `email_verified_at`: setiap perubahan `users.email` mengosongkannya (atribut event
  SQLAlchemy atau satu helper; diuji di semua jalur yang sekarang menulis email: ganti email di Pengaturan, reset data,
  tautan akun, login Google).
- **Login Google:** set `email_verified_at` bila klaim Google `email_verified` true dan alamatnya sama dengan email akun.
- **Email/password:** tombol "Kirim tautan verifikasi" mengirim tautan bertanda tangan (JWT dengan `type`
  `verifikasi_email`, terikat user dan alamat email saat itu, berlaku 24 jam; token login menolak `type` selain
  `access`, dan pemeriksa token verifikasi menolak `type` lain). Dibatasi 3 kali per jam per user. Membuka tautan
  menandai email terverifikasi bila alamatnya masih sama, lalu mengarahkan ke Pengaturan dengan pesan.
- Email verifikasi tidak memuat data keuangan.
- Akun tanpa email (hanya Telegram): laporan tetap terbit di aplikasi dan Telegram.

### 6b. Email laporan

Dikirim bila email terverifikasi, `email_on`, dan laporan belum pernah dikirim.

- **Subjek:** "Laporan Oktober 2026 · Jatahku" (judul laporan), tanpa angka.
- **Body** (`email_template` + `h()`): persentase anggaran terpakai, jumlah amplop aman dan lewat batas, tren
  dibanding periode lalu (naik/turun %), satu sorotan, tombol "Lihat laporan" (`/laporan/<id>`). **Tanpa nominal
  rupiah** — dirakit dari `data.email` saat terbit.
- **Kata sandi diatur:** lampiran PDF berpassword (`MIMEMultipart("mixed")`, pola `send_data_backup_email`).
- **Kata sandi belum diatur:** tanpa lampiran, dengan ajakan "Atur kata sandi laporan untuk menerima PDF".
- Kuartalan dan tahunan: pola yang sama, satu email per laporan.
- **Berhenti berlangganan:** footer berisi tautan bertanda tangan (`type` `berhenti_email_laporan`, tanpa kedaluwarsa,
  terikat user) ke halaman konfirmasi dengan satu tombol; header `List-Unsubscribe` dan `List-Unsubscribe-Post:
  List-Unsubscribe=One-Click` menuju endpoint POST sungguhan. Hanya mematikan `email_on`; laporan di aplikasi tetap
  terbit; email bisa dinyalakan lagi di Pengaturan.

### 6c. Antrean dan coba ulang

- Saat terbit: `email_status` = `menunggu`, atau `dilewati` dengan alasan (`belum_verifikasi`, `dimatikan`,
  `tanpa_email`).
- Job yang sama memproses `menunggu` satu per satu: simpan `mengirim` + waktu (commit), kirim di thread (SMTP sinkron),
  lalu `terkirim`. Gagal → kembali `menunggu`, `email_percobaan` + 1, coba lagi paling cepat 1 jam kemudian; setelah 3
  percobaan → `gagal` (alasan `smtp`) dan `logger.error`.
- `mengirim` lebih lama dari 30 menit (server mati saat mengirim) dianggap `menunggu`. Akibatnya email bisa terkirim dua
  kali dalam kasus sangat jarang — dipilih daripada email hilang.
- Pengaturan yang berubah setelah terbit dibaca ulang saat mengirim (email dimatikan atau berubah alamat → `dilewati`).

### 6d. Notifikasi

`notification_service.kirim(user, NotificationType.system, judul, pesan, link="/laporan/<id>")`: lonceng selalu,
Telegram bila tertaut. Judul "Laporan Oktober 2026 siap"; pesan tanpa nominal. Tipe `system` seperti notifikasi siklus
(tanpa migrasi enum). Tidak ada notifikasi tambahan untuk ajakan verifikasi atau kata sandi (cukup banner, bagian 5).

## 7. API

| Endpoint | Perilaku |
|---|---|
| `GET /laporan` | daftar laporan milik sendiri (id, jenis, judul, periode, terbit), terbaru dulu, berhalaman |
| `GET /laporan/{id}` | `data` laporan milik sendiri; milik user lain atau tidak ada → 404 |
| `GET /laporan/{id}/pdf` | PDF berpassword; kata sandi belum diatur → 409 `{"kode": "kata_sandi_belum_diatur"}`; dibatasi 10/menit per user |
| `GET /user/laporan-pengaturan` | `kata_sandi_diatur`, `email`, `email_terverifikasi`, `email_on`, `kuartalan_on`, `tahunan_on`, `pro` |
| `PUT /user/laporan-pengaturan` | ubah toggle dan/atau kata sandi; toggle kuartalan/tahunan untuk non-Pro → 403; dibatasi 5/jam per user untuk kata sandi |
| `POST /user/email/verifikasi` | kirim tautan verifikasi (3/jam per user) |
| `GET /auth/verifikasi-email?token=` | tandai terverifikasi, arahkan ke Pengaturan |
| `GET`/`POST /laporan/berhenti-email?token=` | halaman konfirmasi / one-click |

Nama tidak bentrok dengan rencana Buku Usaha (`/p/buku_usaha/laporan`). API hanya bertambah (`openapi_cek`).

## 8. Keamanan dan privasi

- Endpoint laporan hanya melayani laporan milik pemanggil; tes IDOR (anggota satu rumah pun tidak bisa membuka laporan
  anggota lain).
- Nominal hanya di aplikasi dan di PDF AES-256; email dan Telegram tanpa nominal.
- `REPORT_SECRET_KEY` dan kata sandi laporan tidak pernah di log, respons, atau repo. Token verifikasi dan berhenti
  langganan bertanda tangan dengan `type` sendiri.
- Pembatasan frekuensi: unduh PDF, kirim verifikasi, ubah kata sandi (per user, Redis).
- Hapus akun dan gabung akun: `reports` dan `report_settings` dimasukkan ke daftar eksplisit di
  `services/account_deletion.py` dan `services/merge.py`, dengan tes.
- Visibilitas household lewat `visibility.py`; agregat menghitung semua transaksi.
- Tidak ada file laporan di disk; tidak ada laporan untuk ruang usaha.

## 9. Migrasi, paket, dan deploy

- Satu revisi alembic + DDL idempoten di `lifespan` (pola siklus household): tabel `reports`, `report_settings`, kolom
  `users.email_verified_at`. Workflow "Migrasi" harus hijau.
- **Sebelum merge tahap 1** (checklist di `AGENTS.md`):
  - `sudo -u jatahku /opt/jatahku/venv/bin/pip install fpdf2==2.8.9 cryptography==50.0.2` (deploy tidak menjalankan
    `pip install`; 2.8.9 dirilis 29 Sep 2026 dan mendukung AES-256 — diperiksa 1 Nov 2026: `EncryptionMethod.AES_256`,
    PDF tidak terbuka di `pypdfium2` tanpa kata sandi dan terbuka dengannya; 2.9.0 baru berumur 3 hari, tidak dipakai);
  - buat `REPORT_SECRET_KEY` di `/opt/jatahku/.env`:
    `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`;
  - cek pemilik tabel `users` (query di checklist Kotak Struk).
- Kunci hilang atau diganti = kata sandi laporan yang tersimpan tidak terbaca; user diminta mengatur ulang (rotasi kunci
  di luar cakupan).

## 10. Pengujian

- **Fungsi murni** (fixture, tanpa DB): pembangun `data` per bagian; jendela kuartal dan tahun untuk gajian 1–31,
  termasuk Februari dan pergantian tahun; status amplop dan "tidak pernah lewat batas"; judul; ringkasan email (body
  tidak memuat "Rp" dan tidak memuat nominal apa pun dari `data`).
- **Konsistensi:** jumlah baris amplop = ringkasan; mutasi keluar per amplop = terpakai amplop.
- **PDF:** dibuka dengan `pypdfium2` (sudah terpasang): dengan kata sandi terbuka dan teks memuat judul serta nama
  amplop; tanpa kata sandi gagal.
- **Job:** jalan dua kali = satu laporan; batas 7 hari; snapshot belum ada → tidak terbit, jam berikutnya terbit; user
  tanpa aktivitas dilewati; akun baru/terhapus dilewati; kuartalan/tahunan hanya Pro dengan toggle; isolasi kegagalan
  household; kunci household dipegang saat membangun.
- **Email:** lampiran bila kata sandi diatur; tanpa lampiran bila belum; tidak terkirim ke email belum terverifikasi;
  status dan coba ulang; `mengirim` basi; berhenti berlangganan.
- **API:** IDOR; 409 tanpa kata sandi; kata sandi tidak pernah dikembalikan; 403 toggle Pro untuk Basic; token salah,
  kedaluwarsa, `type` lain, atau email sudah berganti; semua jalur penulis email mengosongkan verifikasi.
- **Hapus akun dan gabung akun** dengan laporan dan pengaturan.
- **Frontend:** helper murni (`node --test`): pemformatan, pilihan layar lengkap vs ringkas, banner; build.
- **Migrasi:** `cek-migrasi.sh` di PostgreSQL nyata.

## 11. Tahapan

Tiga PR, masing-masing direview, dengan checklist deploy sendiri:

1. **Inti (bermigrasi):** tabel dan kolom (semua, bagian 2a–2b), pembangun `data`, job dan notifikasi, halaman desktop
   dan layar ringkas HP, kata sandi dan unduh PDF, Pengaturan → Laporan (kata sandi), ganti nama "Ekspor", menu sidebar.
2. **Email:** verifikasi email, email laporan dengan lampiran, antrean dan coba ulang, berhenti berlangganan, toggle
   "Kirim laporan ke email".
3. **Kuartalan dan tahunan (Pro):** jendela, agregasi, toggle, tata letak PDF per periode; daftar fitur Pro di halaman
   Upgrade dan landing diperbarui ("Laporan kuartalan & tahunan").

## 12. Di luar cakupan

- Laporan ruang usaha (bagian dari Buku Usaha).
- PDF dikirim sebagai file lewat bot Telegram atau chat web (bot belum bisa mengirim dokumen; paritas chat web).
- Push notification ke HP (FCM/APNs belum dibangun).
- Isi laporan yang bisa dipilih per user; banyak alamat email per user.
- Jam kirim per zona waktu user (semua zona Indonesia jatuh di pagi hari).
- Rotasi `REPORT_SECRET_KEY`.
- Laporan untuk periode yang tutup lebih dari 7 hari sebelum job berjalan.

## 13. Risiko dan catatan

- **Jam server UTC.** "Tutup" mengikuti tanggal server, sama dengan job snapshot; transaksi bertanggal hari gajian yang
  dicatat sebelum 07:00 WIB tetap masuk periode baru (berbasis tanggal).
- **Deskripsi beku.** Transaksi yang ditandai privat setelah laporan terbit tetap terbaca di laporan lama penerima lain
  (sebelumnya pun sudah terbaca olehnya).
- **Perubahan tanggal gajian** dalam 7 hari setelah periode tutup: laporan yang sudah terbit tetap; laporan berikutnya
  mengikuti siklus baru.
- **SMTP sinkron dan PDF di proses API:** dijalankan di thread dengan batas konkurensi; skala sekarang (29 user)
  ringan. Bila membesar, pindah ke worker terpisah (pola Kotak Struk).
- **Password PDF** hanya penghalang akses santai; perlindungan utama adalah email terverifikasi dan body tanpa nominal.
