# Plugin dan Buku Usaha — alur kerja development dan daftar sesi

**Status:** disetujui pemilik produk 31 Okt 2026, bersama ADR-P8 sampai P19 (`02-adr.md`). Dibuka oleh sesi F0 (#137). Versi dengan diagram ada di dokumen Claude Docs "Rencana Development Plugin Buku Usaha" (https://claude.ai/artifact/VuQVnfRG5fmUcdqCKBLs7s). Perubahan rencana dibuat di file ini lewat PR, lalu disalin ke dokumen itu.

**Tracker:** artifact "Tracker Plugin Jatahku" di claude.ai untuk manusia; sumber kebenaran untuk Claude Code tetap `PROGRESS.md`.

Buku Usaha menjadi plugin pertama Jatahku (ADR-P7). Karena Buku Usaha hanya hidup di ruang usaha, urutan kerjanya menjadi Beranda berbasis registry, ruang usaha, host plugin, lalu Buku Usaha: 23 sesi Claude Code, sekitar 74,5 jam kerja aktif, belum termasuk review keamanan terpisah.

## Keputusan 31 Okt dan dampaknya

Pemilik produk memilih Buku Usaha sebagai plugin pertama, menggantikan "modul pilot ringan" di roadmap kajian, karena desainnya sudah lengkap di kanvas (10 artboard). Buku Usaha hanya bisa dipasang di ruang usaha, jadi ruang usaha harus ada sebelum host plugin bisa diuji.

| Roadmap kajian | Rencana ini | Alasan |
| --- | --- | --- |
| P1 Beranda registry, P2 Mode Atur, P3 host + pilot, P4 ruang usaha + Paket Usaha v1 | Beranda registry dan ruang usaha (dua jalur), lalu host plugin, lalu Buku Usaha, lalu beta | Plugin pertama butuh ruang usaha dan registry kartu sekaligus |
| Mode Atur sebelum plugin | Mode Atur keluar dari jalur kritis; boleh paralel setelah B3 | Kartu Buku Usaha cukup masuk tata letak bawaan; menata ulang bukan syarat |
| Gerbang P3 diuji dengan modul pilot ringan | Gerbang host diuji dengan kerangka Buku Usaha di sesi U1 | Host diuji pada irisan tipis Buku Usaha sebelum fiturnya ditambah |
| Paket Usaha v1: Buku Usaha, Pajak UMKM, Faktur & Piutang | Rilis pertama hanya Buku Usaha; Pajak UMKM dan Faktur & Piutang menyusul | Beta bisa jalan lebih cepat dengan satu plugin |
| Outbox event dibangun di P3 | Ditunda ke Faktur & Piutang | Buku Usaha v1 tidak punya pendengar event; job terjadwal sudah cukup |

Risikonya, host plugin pertama kali diuji oleh plugin besar, sehingga bug host dan bug plugin bisa tercampur. Karena itu U1 hanya berisi kerangka (manifest, tabel, Kontak), dan U2 baru dimulai setelah gerbang host lulus.

## Urutan fase dan gerbang

(Di dokumen Claude Docs berupa diagram.)

1. **Fase 0 · Persiapan** (F0, O1 · 2 jam): folder `docs/plugin`, aturan di `AGENTS.md`, perintah sesi, CI migrasi, issue; keputusan tersisa menjadi ADR.
2. Dua jalur yang tidak saling bergantung:
   - **Fase 1 · Beranda registry** (B1–B3 · 9 jam): kartu menjadi registry, data lewat satu permintaan, tampilan Beranda tetap sama untuk semua user; Mode Atur boleh menyusul paralel. **Gerbang B:** angka dan tampilan sama untuk semua user; batch data p95 ≤ 500 ms.
   - **Fase 2 · Ruang usaha** (R1–R8 · 30 jam): `ruang_aktif` di 86 titik; ruang dari objek saat menulis, kuota per ruang; pemilih ruang, peran, batasan, persetujuan; Catat cepat, kamus per ruang, prive. **Gerbang R:** angka user lama identik; nol kebocoran antar-ruang; chat tetap ruang keluarga.
3. **Fase 3 · Host plugin** (H1–H3 · 11,5 jam): manifest dan validator CI, instalasi per ruang, PluginContext, titik ekstensi, halaman Fitur Tambahan.
4. **U1 · Kerangka Buku Usaha** (3,5 jam): manifest, tabel, 5 amplop bawaan, dan Kontak sebagai irisan tipis untuk menguji host. **Gerbang H:** Buku Usaha bisa dipasang, dijeda, dicopot, dan dipulihkan bersih; tes isolasi lulus.
5. **Fase 4 · Fitur Buku Usaha** (U2–U6 · 16,5 jam): penjualan dan alokasi omzet, laba rugi dan laporan, kartu Beranda, arus kas 13 minggu; Catat cepat versi usaha, aturan AI Advisor BU, `/laba` dan pengingat untuk admin. **Gerbang rilis:** review keamanan terpisah lulus; angka ruang keluarga tetap identik; flag per ruang siap.
6. **Beta** (V1 · 2 jam, lalu 4 minggu): 10 UMKM memakai ruang usaha dan Buku Usaha; Pajak UMKM serta Faktur & Piutang menyusul. **Gerbang beta:** 10 UMKM aktif selama 4 minggu tanpa insiden data; setelah itu rilis berbayar.

Beranda registry dan ruang usaha tidak saling bergantung, jadi bisa dikerjakan dua orang sekaligus. Bila dikerjakan sendiri, mulai dari Beranda registry: lebih kecil, di balik flag, dan B2 dibutuhkan R6 untuk Beranda karyawan.

## Cakupan Buku Usaha v1

Rilis pertama adalah semua yang sudah digambar di kanvas desain (https://claude.ai/artifact/NFHnjALwuskpZz8pxB3Z8k), kecuali Mode Atur.

| Fitur | Artboard di kanvas | Sesi |
| --- | --- | --- |
| Ruang usaha terpisah dan pemilih ruang | Beranda ruang usaha, Pemilih ruang, Beranda usaha di HP | R1–R4 |
| Anggota, peran, batasan, antrean persetujuan | Admin: anggota dan batasan; Karyawan: Beranda | R5, R6 |
| Catat cepat dengan deteksi dan belajar per ruang | Karyawan: Catat cepat | R7, U5 |
| Prive ke ruang keluarga | Menu Catat dan FAB | R8 |
| Fitur Tambahan: katalog, pasang, jeda, copot | Fitur Tambahan | H1–H3, U1 |
| Kontak pelanggan dan pemasok | Halaman Buku Usaha, tab Kontak | U1 |
| Penjualan, jenis pemasukan, alokasi omzet | Form penjualan; tab Alokasi omzet | U2 |
| Laba rugi dan laporan PDF/CSV | Halaman Buku Usaha, tab Laba rugi | U3 |
| Kartu Beranda: Omzet, Laba, Kas usaha, Arus kas 13 minggu, Alokasi omzet, Beban per akun, Pelanggan teratas | Beranda ruang usaha (desktop dan HP) | U4 |
| Saran AI Advisor dari Buku Usaha (BU-*) | Kartu AI Advisor | U5 |
| `/laba` dan pengingat kas untuk admin di chat | Chat: laporan Dapur Nusa | U6 |

Menyusul setelah beta: Mode Atur dan Galeri kartu (artboard Atur Beranda), Pajak UMKM, Faktur & Piutang beserta outbox event, dan pembayaran Paket Usaha. Aplikasi Android dan iOS memakai bundle yang sama dengan web, jadi Buku Usaha ikut tampil di sana tanpa sesi tambahan; menjualnya di toko aplikasi menunggu keputusan kajian no. 11 (belum diputuskan, lihat `02-adr.md`).

## Daftar sesi

Satu sesi adalah satu duduk Claude Code selama 2–4 jam dengan satu PR. Tanda "migrasi" berarti sesi itu menambah migrasi Alembic; "review" berarti PR-nya wajib direview sesi keamanan terpisah sebelum merge. File di kolom terakhir menjadi milik sesi itu selama berjalan.

### Fase 0 · Persiapan

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| O1 | — | Keputusan pemilik produk yang tersisa | — | — | Selesai 31 Okt: semua rekomendasi di tabel keputusan dipakai, dicatat sebagai ADR |
| F0 | #137 | Bootstrap repo dan CI migrasi | 2 | O1 | `docs/plugin/` (00-indeks, 01-kajian, 02-adr, 03-workflow, 04-kontrak-api, 05-desain-buku-usaha, PROGRESS, SESI-LOG); bagian "Plugin dan ruang" di `AGENTS.md`; `.claude/commands/sesi-plugin.md` dan `tutup-sesi-plugin.md`; workflow "Migrasi" (`alembic upgrade`, `check`, `downgrade` di PostgreSQL); `04-kontrak-api.md` v0; label, milestone, satu issue per sesi (#137–#158) |

### Fase 1 · Beranda berbasis registry

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| B1 (migrasi) | #138 | Registry kartu dan data batch | 3,5 | F0 | `app/services/dashboard/`: registry dan penyedia data per kartu inti yang memanggil `metrics.py`, `snapshot.py`, `envelope_balance.py`, `recurring_status.py` tanpa rumus baru; `app/api/routes/dashboard.py`: `GET` dan `PUT /dashboard/layout`, `GET /dashboard/cards`, `POST /dashboard/data`; tabel `dashboard_layouts`; tes paritas angka dan anggaran p95 |
| B2 | #139 | Beranda dari registry | 3,5 | B1 | `frontend/src/cards/core/`, `CardRegistry`, `DashboardGrid`, `CardFrame`; `Dashboard.jsx` membaca tata letak; `localCache.js` untuk respons batch; flag `beranda_registry_users` |
| B3 | #140 | Verifikasi dan rilis Beranda registry | 2 | B2 | Skrip paritas pola `advisor_paritas` untuk semua user; perbandingan tampilan desktop dan HP; flag menjadi `*` |

### Fase 2 · Ruang usaha

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| R1 (migrasi) | #141 | Model ruang | 2,5 | F0 | `households.type` (`rumah_tangga`, `usaha`), `incomes.kind` beserta backfill, satu user boleh menjadi anggota beberapa household; model dan skema API; belum ada perubahan perilaku |
| R2 (review) | #142 | Resolver `ruang_aktif` (2 sesi, 1 PR) | 7 | R1 | `ruang_aktif(user, request)` dan header `X-Jatahku-Ruang` menggantikan dua `get_household_id` (`envelope_balance.py`, `bot/handlers.py`) dan kueri keanggotaan di 31 file; bot memakai `ruang_keluarga(user)`; tes paritas semua user lama |
| R3 (review) | #143 | Ruang dari objek saat menulis | 3 | R2 | Penulisan menentukan ruang dari amplop atau objek, lalu memeriksa keanggotaan; `ruang_id` dari body atau query ditolak; tes IDOR lintas ruang; kuota per ruang di `plan_limits.py` |
| R4 | #144 | Membuat dan berpindah ruang | 3,5 | R3 | `GET` dan `POST /ruang` (pemilik, flag `ruang_usaha_users`); pemilih ruang di sidebar dan header HP (`Layout.jsx`); `api.js` mengirim header; menu dan Beranda mengikuti ruang aktif |
| R5 (migrasi, review) | #145 | Peran, batasan, persetujuan di server | 4 | R3 | Undangan ke ruang usaha; tabel batasan per anggota (jenis catatan, amplop, batas nominal, foto nota, jendela ubah, lihat saldo, jam kerja); penegakan di `expense_rules.py` dan jalur pemasukan; antrean persetujuan berupa draf terpisah yang baru menjadi transaksi saat disetujui; log audit |
| R6 | #146 | Halaman Anggota dan batasan, Beranda karyawan | 3,5 | R4, R5, B2 | Halaman admin sesuai artboard; menu disaring per peran; template Beranda "Karyawan" |
| R7 (migrasi, review) | #147 | Catat cepat dan kamus per ruang | 4 | R3, R6 | `txn_nlp.py` dan `suggest-envelope(s)` memakai ruang tempat mencatat; kata yang dipelajari diberi cakupan ruang; urutan cocok: kata user, kamus ruang, kamus kategori; tawaran "pengeluaran pribadi"; lembar Catat cepat; daftar dan hapus kata di halaman admin |
| R8 | #148 | Prive dua sisi | 2,5 | R3 | Perluasan `fund_shift.py`: keluar sebagai prive di ruang usaha (hanya pemilik) dan masuk sebagai pemasukan di ruang keluarga pemilik dalam satu transaksi database; tidak mengurangi laba |

### Fase 3 · Host plugin

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| H1 (migrasi, review) | #149 | Host inti | 4 | B1, R3 | `app/plugins/host/`: skema manifest, pemuat saat start, validator di CI; tabel `plugin_installations`, `entitlements`, `plugin_audit_log`; status terpasang, aktif, dijeda, dicopot, dan arsip 90 hari; saklar darurat di `AppSetting`; endpoint daftar, pasang, jeda, lanjut, copot |
| H2 (review) | #150 | PluginContext dan titik ekstensi server | 4 | H1 | `app/plugins/sdk/`: `PluginContext` memeriksa izin di setiap panggilan, membaca lewat `visibility.py`, dan mencatat audit; titik `cards` ke registry B1, `checks` di `expense_rules.py`, `advisor_rules` ke `select.py` dengan batas per plugin, `bot_commands` baca dengan `audience`, `notifications` lewat penyaring `proaktif.py`, `jobs`, `nlp_kamus` di `txn_nlp.py`, `form_fields` |
| H3 | #151 | Host di frontend dan halaman Fitur Tambahan | 3,5 | H2, B2, R4 | `GET /plugins/contributions` per ruang; grup menu Usaha, aksi di menu Catat, rute `/p/<id>` lazy, kartu dari `src/plugins/<id>/cards.js`; halaman Fitur Tambahan: katalog, layar izin, pasang, jeda, copot dengan tawaran ekspor |

### Fase 4 · Buku Usaha

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| U1 (migrasi, review) | #152 | Kerangka Buku Usaha dan Kontak | 3,5 | H3, R5 | `app/plugins/buku_usaha/`: manifest, tabel `p_buku_usaha_kontak`, `p_buku_usaha_income_meta`, `p_buku_usaha_txn_meta`, dan aturan alokasi; wizard pasang dengan 5 amplop bawaan; Kontak dan tab Kontak; gerbang host: pasang, jeda, lanjut, copot, pulihkan, tes isolasi |
| U2 | #153 | Penjualan dan alokasi omzet | 3,5 | U1 | Jenis pemasukan (penjualan, modal pemilik, pinjaman, lain-lain); form penjualan dengan pelanggan dan pratinjau pembagian; pembagian otomatis ke amplop dalam transaksi database yang sama; tab Alokasi omzet dengan validasi 100%; pemasok dan akun di form pengeluaran |
| U3 | #154 | Laba rugi dan laporan | 3,5 | U2, R8 | `app/plugins/buku_usaha/metrics.py`: omzet hanya dari penjualan, beban per akun, laba, margin, banding bulan lalu, prive di luar laba rugi; tab Laba rugi; laporan PDF/CSV di worker dengan escape dari PR #136 |
| U4 | #155 | Kartu Beranda dan arus kas | 3,5 | U3, B3 | Penyedia kartu Omzet, Laba bersih, Kas usaha, Arus kas 13 minggu, Alokasi omzet, Beban per akun, Pelanggan teratas, dan Penjualan saya untuk karyawan; bentuk deklaratif; maksimal 150 ms per penyedia; tawaran kartu saat pasang |
| U5 | #156 | Catat cepat versi usaha dan AI Advisor | 3,5 | U2, R7 | Kamus usaha lewat `nlp_kamus` (penjualan, kontak, satuan); aturan BU-* sebagai fungsi murni dengan teks dari templat; batas insight plugin per slot |
| U6 | #157 | Chat dan notifikasi admin | 2,5 | U3, R5 | `/laba` hanya untuk admin, dicek saat dipanggil, dengan menu perintah per chat; pesan berawalan nama ruang; pengingat kas harian; pemberitahuan antrean persetujuan; tombol hanya membuka Jatahku |

### Fase 5 · Beta

| Sesi | Issue | Nama | Jam | Butuh | Hasil dan file |
| --- | --- | --- | --- | --- | --- |
| V1 | #158 | Verifikasi dan rilis beta | 2 | Semua | Paritas ulang ruang keluarga, tes kebocoran antar-ruang, sesi review keamanan terpisah, flag `ruang_usaha_users` dan `plugin_buku_usaha_users` untuk 10 UMKM, hak uji coba Paket Usaha |

Total 23 sesi dan 74,5 jam: Fase 0 2 jam, Fase 1 9 jam, Fase 2 30 jam, Fase 3 11,5 jam, Fase 4 20 jam, Fase 5 2 jam. Tujuh PR bertanda review menambah sekitar 1 jam review masing-masing.

## Keputusan pendukung

Dua belas keputusan pendukung disetujui pemilik produk pada 31 Okt 2026 (O1) dan menjadi ADR. Kolom terakhir menunjukkan sesi yang paling dulu memakainya.

| ADR | Keputusan | Dipakai sejak |
| --- | --- | --- |
| ADR-P8 | Tata letak Beranda: urutan + ukuran | B1 |
| ADR-P9 | Hanya plugin T1 (buatan sendiri, ikut rilis) | H1 |
| ADR-P11 | Pemilik dan admin ruang yang memasang plugin | H1 |
| ADR-P14 | Plugin dilarang memakai LLM pihak ketiga | H1 |
| ADR-P15 | Arsip 90 hari setelah plugin dicopot | H1 |
| ADR-P10 | "Fitur Tambahan" di UI, "plugin" di kode | H3 |
| ADR-P13 | Kuota Basic tidak berlaku di ruang usaha; butuh Paket Usaha | R3 |
| ADR-P16 | Tombol chat disembunyikan untuk karyawan di ruang usaha | R4 |
| ADR-P17 | Jam akses ruang usaha: pilihan per karyawan, bawaan mati | R5 |
| ADR-P18 | Antrean persetujuan bagian inti ruang usaha | R5 |
| ADR-P19 | Notifikasi operasional untuk karyawan bila admin mengizinkan | U6 |
| ADR-P12 | Paket Usaha langganan per ruang, hipotesis Rp25.000–Rp50.000 per bulan | V1 |

Keputusan kajian no. 7 (Beranda bawaan dari pemilik), no. 9 (payment gateway), dan no. 11 (harga di toko aplikasi) belum diputuskan dan tidak menghalangi rencana ini.

## Keamanan lebih dulu

Temuan keamanan di sesi mana pun dikerjakan sebelum fitur dilanjutkan. Tujuh PR bertanda review (R2, R3, R5, R7, H1, H2, U1) diperiksa dulu oleh sesi Claude Code terpisah yang hanya mereview, dengan perintah "review PR #N terhadap 03-workflow.md bagian keamanan".

| Gerbang | Yang diuji | Sesi |
| --- | --- | --- |
| Ruang tidak pernah dari body | Setiap endpoint tulis menentukan ruang dari objeknya; tes IDOR: user ruang A tidak bisa membaca atau menulis objek ruang B walau tahu ID-nya | R2, R3 |
| Batasan ditegakkan di server | Batas nominal, amplop terkunci, foto nota, dan jendela ubah juga berlaku lewat aplikasi, antrean offline, dan kirim ulang (`client_ref`); pemeriksaan di frontend hanya tampilan | R5 |
| Karyawan tidak melihat laporan | Laba, kas, omzet, dan saldo yang tidak diizinkan tidak bocor lewat endpoint mana pun, termasuk `/dashboard/data`, ekspor, dan `/laba` | R5, B1, U3, U6 |
| Ruang keluarga tetap pribadi | Tidak ada kueri lintas ruang selain Prive; kamus per ruang tidak terbawa; tawaran "pengeluaran pribadi" tidak tercatat untuk admin | R7, R8 |
| Plugin sebagai tamu | `PluginContext` memeriksa izin di setiap panggilan dan mencatat audit; validator CI menolak perintah bot yang menulis | H1, H2 |
| Isolasi plugin | Plugin yang dijeda atau dicopot tidak meninggalkan kartu, menu, perintah, atau job; saklar darurat bekerja dalam satu siklus muat ulang | U1 |
| Laporan aman | Ekspor PDF dan CSV memakai escape HTML, CSP, dan anti formula-injection dari PR #136 | U3 |
| Rahasia | Repo publik: kunci dan kredensial hanya di `.env` server, tidak pernah di kode atau `localStorage` | Semua |

Data pelanggan dan karyawan UMKM adalah data pribadi: pemilik usaha sebagai pengendali, Jatahku sebagai prosesor. Sebelum beta, S&K ruang usaha perlu klausul pemrosesan data, dan penilaian dampak ringkas sesuai UU PDP perlu ditulis.

## Cara kerja

Polanya sama dengan `docs/mobile/03-workflow.md` dan `docs/ai-advisor/03-workflow.md`, supaya tim tidak memakai dua cara kerja. Yang khusus untuk plugin:

- **Repo adalah memori.** F0 membuat `docs/plugin/`: 00-indeks (peta dan fase sekarang), 01-kajian (salinan kajian), 02-adr (keputusan sebagai ADR-P1 dan seterusnya), 03-workflow (dokumen ini), 04-kontrak-api (bentuk respons `/dashboard/*`, `/ruang`, `/plugins/*`, dan header `X-Jatahku-Ruang`, supaya frontend dan backend bisa paralel), 05-desain-buku-usaha (mockup, keputusan ruang usaha, tautan kanvas), `PROGRESS.md`, dan `SESI-LOG.md`.
- **Satu sesi, satu branch, satu PR.** Branch `plugin/<kode>-<slug>` dari `main` terbaru, mis. `plugin/r2-ruang-aktif`; PR berjudul `Plugin <kode>: <nama>`, squash merge. R2 memakai dua sesi di satu branch dan satu PR, karena refactor 86 titik harus selesai seluruhnya sebelum ruang kedua bisa dibuat.
- **Ritual.** `/sesi-plugin <kode>` membuka sesi: baca indeks, ADR, baris sesi di dokumen ini, dan entri terakhir `SESI-LOG.md`; cek dependensi; buat atau lanjutkan branch; rangkum scope; lalu tunggu "lanjut". `/tutup-sesi-plugin` menutup: tes, `PROGRESS.md`, entri `SESI-LOG.md`, commit, push, PR, dan satu baris status untuk tracker. `/cek-deploy <PR>` tetap dipakai setelah merge.
- **Merge berarti deploy produksi.** Setiap PR harus aman untuk user hari ini. Yang belum siap disembunyikan lewat flag di `AppSetting`: `beranda_registry_users` (B2–B3), `ruang_usaha_users` (sejak R4), `plugin_buku_usaha_users` (sejak U1), dan saklar darurat plugin (H1).
- **Migrasi.** Sesi bertanda migrasi mengikuti checklist deploy di `AGENTS.md` dan diberi label `migrasi`; merge hanya oleh orang yang bisa menjalankan migrasinya di VPS pada jam yang sama. Workflow "Migrasi" (`.github/workflows/migrasi.yml`, dibuat F0) berjalan di setiap PR yang menyentuh model atau migrasi: skema awal meniru produksi (`create_all` dari model `main` + stamp), lalu migrasi PR dinaikkan, dicocokkan dengan model lewat `alembic check`, diturunkan, dan dinaikkan lagi. Jalankan lokal dengan `.github/scripts/cek-migrasi.sh origin/main` di database kosong.
- **Koordinasi.** PR yang masih terbuka di `Dashboard.jsx` dan `Layout.jsx` di-merge dulu sebelum B2 dan R4. Sesi mobile yang menyentuh file yang sama dijadwalkan sebelum atau sesudahnya, dan perubahan API tetap aditif.
- **Tracker.** Tracker di claude.ai untuk manusia (dibuat di F0) dan `PROGRESS.md` untuk Claude Code, dengan kolom yang sama: Sesi, Status, Pemilik, PR, Mulai, Selesai.

## Template PR

Judul PR: `Plugin <kode>: <nama>`. Isi:

```
## Plugin <kode> — <nama>
Closes #<issue>
ADR: P… · Rencana: 03-workflow.md baris <kode> · Desain: 05-desain-buku-usaha.md §…
### Yang berubah
- …
### Cara mencoba
- …
### Tes
- unittest: … · node --test: … · build: ok · Migrasi (PostgreSQL): ok / tidak berlaku
### Catatan untuk reviewer
- Risiko / keputusan kecil / yang sengaja ditunda
### Checklist
- [ ] Ruang untuk membaca dari `ruang_aktif`, untuk menulis dari objek; tidak ada `ruang_id` dari body atau query
- [ ] Batasan peran ditegakkan di server, bukan hanya di frontend
- [ ] Yang belum siap tersembunyi di balik flag; API hanya bertambah
- [ ] Migrasi? → label `migrasi`, checklist deploy di `AGENTS.md`, workflow "Migrasi" hijau
- [ ] Bertanda review? → sudah direview sesi Claude Code terpisah
- [ ] `PROGRESS.md` dan `SESI-LOG.md` diperbarui
```

## Aturan kerja untuk AGENTS.md

F0 menambahkan bagian "Plugin dan ruang (WAJIB untuk semua sesi plugin)" berisi sembilan aturan:

1. **Ruang dari server, bukan dari klien.** Membaca memakai `ruang_aktif`; menulis menentukan ruang dari objek yang ditulis, lalu memeriksa keanggotaan. `ruang_id` dari body atau query tidak pernah dipercaya.
2. **Chat selalu ruang keluarga.** Handler bot memakai `ruang_keluarga(user)`. Tidak ada transaksi ruang usaha atau Fitur Tambahan lewat chat; perintah plugin hanya membaca dan menyatakan `audience`.
3. **Batasan peran ditegakkan di server** pada setiap jalur tulis: web, aplikasi, antrean offline, dan kirim ulang. Frontend hanya menampilkan.
4. **Plugin hanya lewat `PluginContext`.** Kode di `app/plugins/<id>/` tidak mengimpor model inti dan tidak menulis ke tabel inti secara langsung.
5. **Tabel plugin** memakai awalan `p_<id>_`, kolom wajib (`household_id`, `created_by`, waktu, `deleted_at`), indeks diawali `household_id`, enum sebagai `String`, JSON lewat `JSON().with_variant(JSONB(), "postgresql")`, dan tidak ada DDL saat plugin dipasang.
6. **Satu sumber angka.** Angka Buku Usaha hanya dihitung di `app/plugins/buku_usaha/metrics.py`. Kartu, laporan, chat, dan AI Advisor membacanya; frontend hanya memformat.
7. **Teks dari templat.** Kalimat untuk web, chat web, dan Telegram dirakit dari templat yang sama, seperti aturan `render.py` di AI Advisor.
8. **Tidak ada kueri lintas ruang** selain Prive. Data ruang keluarga tidak pernah dipakai di ruang usaha, dan sebaliknya.
9. **Ekspor memakai escape dari PR #136** (HTML, CSP, anti formula-injection) untuk setiap laporan dan CSV baru.
