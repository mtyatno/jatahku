# Kajian Dashboard Kustomisasi & Sistem Plugin Jatahku

> Salinan dari dokumen Claude Docs "Kajian Dashboard Kustomisasi & Sistem Plugin Jatahku" per 31 Okt 2026 (https://claude.ai/artifact/GBThMvGCNTzqHMJPpspu2Q). Diagram dan grafik hanya ada di versi itu. Urutan kerja yang berlaku ada di `03-workflow.md`; keputusan yang berlaku ada di `02-adr.md`.

Oct 19, 2026 · @Mt Yatno

## Pembaruan 31 Oktober 2026

Pemilik produk mengambil tujuh keputusan yang mengubah sebagian kajian ini. Bagian yang terdampak sudah disesuaikan; rinciannya ada di `05-desain-buku-usaha.md` bagian B dan di `02-adr.md`.

- **Ruang terpisah disetujui.** Uang keluarga dan uang usaha dicatat di ruang berbeda. Menu inti sama di semua ruang, Fitur Tambahan hanya menambah, dan amplop tetap dipakai di ruang usaha.
- **Transaksi lewat chat hanya untuk ruang keluarga.** Telegram dan chat web tetap seperti sistem yang berjalan sekarang. Tidak ada transaksi Fitur Tambahan atau ruang usaha lewat chat, dan perintah `/ruang` dibatalkan.
- **Laporan usaha di chat hanya untuk admin.** Fitur Tambahan hanya mengirim laporan dan notifikasi ke chat; data seperti `/laba` hanya diterima admin ruang usaha.
- **Pencatatan di ruang usaha tetap cerdas.** Form web dan aplikasi tetap mendeteksi isi input dan belajar dari koreksi user.
- **Banyak anggota di satu ruang usaha.** Karyawan bekerja di ruang usaha sesuai Fitur Tambahan dan batasan dari admin, dan tetap punya ruang keluarga sendiri yang tidak terhubung ke ruang usaha.
- **Pikir-Pikir masuk inti ruang keluarga.** Sepadan?, Incaran, dan perintah chatnya seperti `/incaran` tetap jalan karena bukan Fitur Tambahan.
- **Buku Usaha menjadi plugin pertama.** Buku Usaha menggantikan modul pilot ringan karena desainnya sudah lengkap. Ruang usaha dibangun sebelum host plugin; urutan dan sesinya ada di [Rencana Development Plugin Buku Usaha](https://claude.ai/artifact/VuQVnfRG5fmUcdqCKBLs7s).

Sejak keputusan ketujuh, urutan kerja mengikuti rencana development itu; bagian roadmap di kajian ini adalah usulan awal. Rencana itu disetujui 31 Okt malam, bersama rekomendasi untuk keputusan no. 1, 3, 5, 6, 8, 10, 12, dan 13 di tabel keputusan; semuanya dicatat sebagai ADR di \`docs/plugin/02-adr.md\`.

## Ringkasan eksekutif

Rekomendasinya: jadikan Beranda kumpulan kartu yang bisa disembunyikan, digeser dengan drag and drop, dan diubah ukurannya; bangun sistem plugin buatan sendiri di atas pipa yang sama; lalu buka Paket Usaha untuk UMKM setelah konsep **ruang** memisahkan uang usaha dari uang rumah tangga. Perkiraannya, beta Paket Usaha berjalan di minggu ke-16–23 dan selesai di minggu ke-20–27, bila 1–2 developer mengerjakannya penuh.

### Tujuh rekomendasi inti

1. **Model tata letak "urutan + ukuran".** Satu daftar kartu berurutan dengan ukuran S, M, L, atau XL, disimpan per user per ruang di server. Satu tata letak berlaku di HP, tablet, dan layar lebar, dan urutan tampil selalu sama dengan urutan daftar.
2. **Mode Atur yang ramah semua orang.** Kartu digeser dengan drag and drop (pustaka `@dnd-kit/react` di balik adapter), dengan tombol Naik/Turun sebagai jalan setara yang diwajibkan WCAG 2.2 kriteria 2.5.7.
3. **Kartu bawaan dan kartu plugin sederajat.** Keduanya didaftarkan ke daftar kartu yang sama, angkanya dihitung server, dan seluruh Beranda dimuat dengan satu permintaan.
4. **Plugin buatan tim sendiri dulu.** Plugin adalah modul di dalam server Jatahku. Setiap plugin mendaftarkan diri lewat satu berkas manifest, hanya menyentuh data lewat satu pintu yang memeriksa izin, dan menyimpan datanya di tabel sendiri. Plugin boleh memberi peringatan tetapi tidak pernah menolak pencatatan yang jujur. Marketplace untuk pengembang luar belum perlu.
5. **Ruang sebagai fondasi usaha.** Uang usaha dipisah ke ruang kedua, setara household sekarang. Kode yang menganggap satu user hanya punya satu household (86 titik) diganti satu penentu ruang aktif. Uang yang diambil pemilik dari usaha (prive) menjadi transfer antar-ruang dan tidak mengurangi laba.
6. **Plugin pertama.** Buku Usaha, tanpa modul pilot (keputusan 31 Okt): omzet dibagi ke amplop Pajak, Prive, Laba Ditahan, dan Operasional. Pajak UMKM (PPh final 0,5% menurut PP 20/2026 dan PMK 81/2024) serta Faktur & Piutang menyusul sebagai sisa Paket Usaha v1. Pikir-Pikir masuk inti ruang keluarga.
7. **Satu mesin hak dan jualan.** Hak plugin dicatat bersama hak Pro per sumber pembayaran. Plugin baru masuk aplikasi Android dan iOS hanya lewat rilis toko yang direview, dan ajakan beli diatur server per platform.

### Urutan kerja

P0 keputusan (1–2 minggu) → P1 Beranda berbasis registry, tampilan tetap sama (3–4 minggu) → P2 Mode Atur (3–4 minggu) → P3 host plugin + modul pilot (5–7 minggu) → P4 ruang usaha + Paket Usaha v1 (8–10 minggu) → P5 perluasan. Kode fase memakai huruf P supaya tidak tertukar dengan fase F di rencana mobile. Rinciannya di bagian roadmap. Sejak 31 Okt urutan ini diganti: Beranda registry dan ruang usaha lebih dulu, lalu host plugin dengan Buku Usaha sebagai plugin pertama, sedangkan Mode Atur menyusul paralel.

### Apa saja plugin yang bisa dibuat

Katalog memuat 37 kandidat: 18 untuk keuangan usaha, 12 untuk rumah tangga, 7 horizontal, ditambah 6 paket vertikal seperti Paket Warung, Paket Kuliner, dan Paket Kos & Sewa.

### Yang dibutuhkan dari pemilik produk sekarang

Satu keputusan sebelum P1: model tata letak; cara memisahkan uang usaha sudah disetujui pada 31 Okt 2026. Keputusan lain menyusul sesuai fase dan tercantum dengan rekomendasinya di bagian terakhir.

## Titik berangkat: Jatahku hari ini

Fondasi Jatahku cukup matang untuk dijadikan platform, tetapi dua hal harus dibongkar dulu: Beranda yang tersusun mati di satu komponen, dan asumsi satu user hanya punya satu household. Fakta di bawah diambil dari repo `mtyatno/jatahku` (main `56e2a23`, PR #108, 17 Okt 2026) dan dokumen project.

| Area | Keadaan sekarang | Arti untuk dashboard kustomisasi dan plugin |
| --- | --- | --- |
| Stack | FastAPI + PostgreSQL + Redis (±28 ribu baris Python); React 18 + Vite 6 + Tailwind + Recharts (±22 ribu baris JS/JSX, tanpa TypeScript); bot python-telegram-bot; APScheduler; 77 file tes Python dan 37 file tes JS; CI di setiap PR; deploy otomatis tiap merge | Cukup untuk plugin buatan sendiri di dalam monolit. Frontend belum punya pustaka drag and drop maupun lapisan cache data server |
| Beranda | `Dashboard.jsx` (580 baris) memanggil ±15 endpoint dan menyusun 5 baris kartu dengan urutan tetap. Di layar lebar kartu berpasangan 1,65fr : 1fr, di HP bertumpuk | Kartu harus dipecah menjadi unit mandiri (data + tampilan) sebelum bisa disembunyikan atau digeser |
| Preferensi tampilan | Tidak ada tabel preferensi UI. Satu-satunya preferensi kartu, yaitu tab amplop terakhir, disimpan di `localStorage` | Tata letak harus disimpan di server supaya sama di web, Android, iOS, dan tablet |
| Navigasi | Sidebar 7 menu, bottom nav 5 item, menu Catat ▾ dengan 5 aksi, dan rute di `App.jsx`, semuanya ditulis langsung di kode | Plugin butuh titik resmi untuk menambah menu, rute, dan aksi cepat |
| Tenant | Amplop, pemasukan, dan cocokkan saldo milik household; amplop pribadi ditandai `owner_id`. `get_household_id` mengasumsikan satu user satu household. Asumsi itu ada di 86 titik dalam 31 file (36 panggilan helper dan 50 kueri keanggotaan langsung, di luar tes) | Uang usaha tidak bisa dipisah dari uang rumah tangga tanpa konsep "ruang" baru. Ini pekerjaan fondasi terbesar untuk plugin UMKM |
| Registry yang sudah ada | `bot_commands()` dan `bot_callbacks()` (satu daftar untuk Telegram dan chat web); flag fitur per platform di `/app/config`; flag per user di `AppSetting`; slot AI Advisor (`rules` → `select` → `render`); `notification_service.kirim`; job APScheduler | Cikal bakal titik ekstensi. Plugin cukup mendaftar ke registry ini, tidak membuat jalur baru |
| Kontrak yang wajib diwarisi | Satu sumber angka (`metrics.py`); teks hanya di `render.py`; paritas web ↔ Telegram lewat `expense_rules.py`; kontrak visibilitas household (`visibility.py`); API hanya bertambah (ADR-M9); jualan diatur server (ADR-M10) | Setiap plugin tunduk pada aturan yang sama. Kartu plugin membaca angka dari server, tidak menghitung di browser |
| Monetisasi | `user.plan` basic/pro. Basic: 6 amplop, 50 transaksi/bulan, 5 langganan. Pro Rp79.000 sekali bayar lewat transfer manual. Kajian mobile merencanakan hak Pro dicatat per sumber (transfer, promo, Play, App Store) | Hak plugin bisa memakai pola pencatatan hak yang sama, per plugin |
| Skala | Menurut `CLAUDE.md`: 29 user (angka lama). Cek paritas produksi 17 Okt mencakup 95 user, 54 di antaranya punya data (`docs/ai-advisor/05-verifikasi-rilis.md`); Pro gratis lewat promo berlaku untuk 100 user pertama | Marketplace pihak ketiga terlalu dini. Yang masuk akal: plugin buatan sendiri di atas arsitektur yang siap dibuka nanti |
| Fitur yang sedang dirancang | Pikir-Pikir (desain 15 Okt). Fase 1 mengubah aturan catat di inti. Fase 2–3 menambah tabel `wishlist_items` dan `transaction_reflections`, kartu "Sepadan?", perintah bot, job scheduler, dan tipe notifikasi baru. Aturan advisor PP-01 sampai PP-03 sudah ada di `rules/pikir.py` dan menunggu data Fase 2–3 | Fase 2–3 berbentuk persis sebuah modul. Pada 31 Okt diputuskan masuk inti supaya fitur chatnya tetap jalan, jadi titik ekstensi diuji langsung dengan kerangka Buku Usaha (sesi U1 di rencana development) |

**Catatan istilah.** Di `docs/mobile/`, kata "plugin" berarti plugin native Capacitor. Di kajian ini, "plugin" berarti paket fitur Jatahku yang bisa dipasang per ruang; plugin Capacitor disebut "plugin native".

## Visi dan prinsip desain

Jatahku bergerak dari aplikasi amplop rumah tangga menjadi platform: inti kecil yang stabil, ditambah plugin yang dipasang per ruang. Dashboard kustomisasi adalah wajah platform itu, tempat setiap plugin tampil tanpa memenuhi Beranda orang lain.

Dashboard kustomisasi menjadi fondasi plugin karena tiga alasan:

1. **Ruang tampil.** Setiap plugin membawa kartu. Tanpa tata letak per user, setiap plugin baru menumpuk di Beranda yang sama untuk semua orang.
2. **Persona berbeda.** Keluarga, pemilik warung, dan freelancer membutuhkan Beranda yang berbeda dari data yang sama.
3. **Pipa yang sama.** Refactor yang dibutuhkan kustomisasi (registry kartu, endpoint data per kartu, isolasi error per kartu) adalah pipa yang juga dibutuhkan plugin.

**Sepuluh prinsip yang mengikat dashboard dan plugin**

1. **Inti kecil, plugin di tepi.** Inti hanya memegang konsep yang dipakai semua user: ruang, anggota, amplop, transaksi, pemasukan, alokasi, dan langganan. Yang lain masuk plugin.
2. **Kartu bawaan dan kartu plugin sederajat.** Kartu bawaan didaftarkan lewat registry yang sama dengan kartu plugin. Kalau registry cukup untuk kartu bawaan, ia cukup untuk plugin.
3. **Server menghitung, klien menggambar.** Angka kartu plugin dihitung sekali di server, lalu dipakai web, bot, dan aplikasi. Ini perpanjangan aturan "satu sumber angka" AI Advisor.
4. **Cermin, bukan penjaga gerbang.** Plugin boleh memberi peringatan dan saran. Plugin tidak boleh menolak pencatatan pengeluaran yang jujur, sesuai prinsip Pikir-Pikir.
5. **Paritas antarkanal.** Pencatatan lewat chat (Telegram dan chat web) hanya untuk ruang keluarga dan memakai sumber aturan yang sama dengan web. Fitur Tambahan hanya mengirim laporan dan notifikasi ke chat; pencatatannya lewat web dan aplikasi, yang memakai kode yang sama.
6. **Data milik user.** Plugin bisa dinonaktifkan tanpa kehilangan data, dan baru dicopot setelah datanya bisa diekspor. Tidak ada yang terhapus diam-diam.
7. **Izin sesempit mungkin.** Plugin meminta izin per jenis data saat dipasang. Amplop pribadi anggota lain tidak pernah terlihat oleh plugin.
8. **Kontrak hanya bertambah.** API, event, dan format manifest hanya bertambah. Perubahan yang memutus lewat versi baru, sesuai ADR-M9.
9. **Bisa dimatikan dari server.** Setiap plugin dan kartu punya saklar di server, dan ajakan belinya mengikuti mode jualan per platform.
10. **Bawaan tetap rapi.** User yang tidak pernah mengatur apa pun tetap mendapat Beranda yang baik. Kustomisasi adalah pilihan, bukan pekerjaan rumah.

**Di luar cakupan tahun pertama:** marketplace plugin pihak ketiga, skrip atau kode buatan user, ERP lengkap, dan pembukuan untuk perusahaan yang wajib diaudit. Arsitekturnya disiapkan agar pintu ini bisa dibuka nanti tanpa membongkar ulang.

## Dashboard kustomisasi: pengalaman pengguna

User menyembunyikan, menampilkan, menambah, menggeser, dan mengubah ukuran kartu Beranda di dalam **Mode Atur**, lalu perubahan tersimpan otomatis di semua perangkat. Drag and drop dipakai di mouse dan layar sentuh, dengan tombol "Naik" dan "Turun" sebagai jalan setara untuk keyboard, pembaca layar, dan user yang sulit menyeret.

### Alur Mode Atur

1. **Masuk.** Tombol "Atur Beranda" di top bar (layar lebar) atau di bawah sapaan (HP). Di HP, tekan lama sebuah kartu juga membuka Mode Atur.
2. **Tampilan berubah.** Setiap kartu menampilkan pegangan geser, tombol sembunyikan, dan menu ⋯ (ukuran, pengaturan kartu, naik, turun). Isi kartu diredupkan dan tombol aksinya nonaktif supaya tidak tersentuh tanpa sengaja.
3. **Geser.** User menyeret pegangan. Kartu lain bergeser memberi tempat, bayangan menunjukkan posisi jatuh, dan halaman menggulir sendiri di tepi layar.
4. **Sembunyikan.** Kartu pindah ke laci "Kartu tersembunyi" di bagian bawah dan bisa dikembalikan dengan satu ketukan.
5. **Tambah.** Tombol "+ Tambah kartu" membuka Galeri Kartu, dikelompokkan menjadi Bawaan dan per plugin terpasang.
6. **Selesai.** Tombol "Selesai" keluar dari Mode Atur. "Urungkan" membatalkan perubahan satu per satu selama Mode Atur, dan "Kembalikan ke bawaan" meminta konfirmasi.

### Aturan perilaku

- **Menyembunyikan tampilan, bukan peringatan.** Kartu yang disembunyikan tidak membungkam bahaya. Insight danger tetap muncul di kartu AI Advisor; bila kartu itu juga disembunyikan, peringatan masuk ke lonceng notifikasi.
- **Simpan otomatis.** Setiap perubahan dikirim ke server setelah jeda singkat, lalu muncul toast kecil "Tata letak tersimpan". Tidak ada tombol Simpan yang bisa terlupa.
- **Satu tata letak per user per ruang.** Setiap anggota household mengatur Berandanya sendiri. Pemilik household boleh menetapkan Beranda bawaan untuk anggota baru.
- **Tampil di perangkat tertentu.** Setiap kartu bisa diatur tampil di semua perangkat, layar lebar saja (≥1024 px), atau layar kecil saja (HP dan tablet). Urutannya tetap satu, jadi tidak ada dua tata letak yang harus dirawat.
- **Kartu berpengaturan.** Sebagian kartu punya opsi, misalnya jumlah baris Transaksi terbaru atau amplop yang dipantau. Kartu tertentu boleh dipasang lebih dari sekali, misalnya "Pantau amplop" untuk Makan dan untuk Bensin.
- **Periode.** Navigator periode tetap satu untuk seluruh Beranda. Kartu yang hanya berlaku di periode berjalan, seperti AI Advisor dan status langganan, menampilkan "Hanya periode berjalan" saat user melihat periode lampau.
- **Kartu plugin ditawarkan, bukan dipaksakan.** Saat plugin dipasang, user melihat kartu rekomendasinya dengan centang. Yang dicentang masuk tepat di bawah kartu KPI.
- **Gagal sendiri-sendiri.** Kartu yang gagal memuat menampilkan pesan dan tombol "Coba lagi" di tempatnya. Kartu lain tetap tampil.
- **Plugin dinonaktifkan.** Kartunya hilang dari Beranda dan tercatat di laci dengan keterangan plugin asalnya. Saat plugin aktif lagi, posisi lamanya kembali.
- **Template.** Saat onboarding dan di Mode Atur tersedia template: Ringkas, Lengkap, Keluarga, dan Usaha. Template hanya titik awal yang bisa diubah.

### Ukuran dan tata letak responsif

Model yang direkomendasikan adalah **urutan + ukuran**: satu daftar kartu berurutan, masing-masing dengan ukuran S, M, L, atau XL. Kartu disusun baris demi baris sesuai urutan di grid 12 kolom. Bila kartu berikutnya tidak muat, kartu terakhir di baris itu melebar mengisi sisa baris, sehingga urutan tampil selalu sama dengan urutan daftar dan urutan baca keyboard serta pembaca layar. Model ini memenuhi "susun bebas" tanpa harus merawat posisi x-y terpisah untuk setiap lebar layar (perbandingannya di bagian teknis).

| Ukuran | HP (<768 px) | Tablet (768–1023 px) | Layar lebar (≥1024 px) | Contoh kartu |
| --- | --- | --- | --- | --- |
| S | penuh | 1/2 | 1/3 (4 kolom) | Kartu KPI, Target tabungan, Langganan |
| M | penuh | 1/2 | 1/2 (6 kolom) | Sepadan?, Piutang |
| L | penuh | penuh | 2/3 (8 kolom) | Pengeluaran harian, Amplop pengeluaran, Transaksi terbaru |
| XL | penuh | penuh | penuh (12 kolom) | Ke mana uangmu |

Mulai P2, rasio 1,65 : 1 di Beranda sekarang menjadi 2 : 1 (L + S); P1 mempertahankan tampilan lama persis. Kartu utama jadi sedikit lebih lebar, dan pasangan M + M tersedia untuk dua kartu setara.

### Kartu bawaan yang menjadi isi galeri

| Kartu | Ukuran bawaan | Ukuran lain | Periode lampau | Catatan |
| --- | --- | --- | --- | --- |
| Jatah hari ini, Sisa bebas, Terpakai, Income, Tagihan, Tabungan | S (masing-masing) | M | Ya, kecuali chip advisor | Enam kartu terpisah, jadi user bisa memilih KPI yang penting baginya |
| Pengeluaran harian | L | XL | Ya | Garis batas aman hanya di periode berjalan |
| AI Advisor | S | M | Tidak | Flag `advisor_v2_users` sudah `*` sejak 17 Okt; kartu Perlu perhatian lama dihapus di S10b |
| Ke mana uangmu | XL | L | Ya | — |
| Amplop pengeluaran | L | XL | Ya | Tab terakhir pindah dari `localStorage` ke pengaturan kartu |
| Target tabungan | S | M | Ya | — |
| Transaksi terbaru | L | M, XL | Ya | Pengaturan: jumlah baris |
| Langganan | S | M | Tidak | — |
| Papan disiplin | S | M | Tidak | Sekarang hanya di sidebar dan Beranda HP |
| Cocokkan saldo | S | — | Tidak | Sekarang berupa tautan di bawah KPI |
| Pantau amplop (baru) | S | M | Ya | Boleh lebih dari satu, pilih amplop |
| Sepadan? dan Incaran (Pikir-Pikir) | M | L | Tidak | Kartu inti ruang keluarga, setelah Pikir-Pikir Fase 2–3 |

Banner perayaan streak dan panduan onboarding tetap di atas grid sebagai banner sistem. Keduanya bisa ditutup, tetapi bukan kartu tata letak.

### Aksesibilitas dan sentuhan

- **Alternatif seret.** Setiap gerakan seret punya padanan satu ketukan (Naik, Turun, Pindah ke atas), sesuai WCAG 2.2 kriteria 2.5.7 *Dragging Movements*.
- **Keyboard.** Spasi mengangkat kartu, panah memindahkan, spasi menjatuhkan, Esc membatalkan. Pembaca layar mengumumkan posisi baru, misalnya "Tabungan dipindah ke posisi 3 dari 12".
- **Target sentuh.** Pegangan geser minimal 44 × 44 px di HP. WCAG 2.2 kriteria 2.5.8 hanya mensyaratkan 24 × 24 px, tetapi jari di HP butuh lebih.
- **Tidak berebut dengan gulir.** Di HP, kartu hanya bisa diseret lewat pegangan di dalam Mode Atur, jadi gerakan gulir biasa tidak pernah memindahkan kartu.
- **Getar halus di aplikasi.** Aplikasi Android dan iOS memberi umpan balik getar saat kartu terangkat dan jatuh, lewat lapisan `src/native/` yang direncanakan ADR-M6.

## Dashboard kustomisasi: arsitektur teknis

Kustomisasi dibangun dari tiga lapisan: registry definisi kartu di kode, tata letak per user per ruang di database, dan penyedia data per kartu di server. Beranda berubah dari satu komponen yang memanggil ±15 endpoint menjadi kerangka grid yang merender kartu dari daftar.

### Tiga konsep inti

| Konsep | Isi | Disimpan di |
| --- | --- | --- |
| Definisi kartu | `key` (mis. `core.kpi.jatah`, `faktur.piutang`), judul, deskripsi, asal (inti atau id plugin), ukuran yang didukung dan bawaannya, `supports_period`, `multi_instance`, skema pengaturan (JSON Schema), izin data, syarat paket atau hak plugin, platform, komponen (lazy import), versi | Kode: registry frontend dan registry penyedia data di backend |
| Instans kartu | `id` instans, `card`, `size`, `hidden`, `devices` (`all`; `wide` untuk ≥1024 px; `narrow` untuk <1024 px), `settings` | Di dalam dokumen tata letak |
| Tata letak | Daftar instans berurutan untuk satu user, satu ruang, satu permukaan (`beranda`) | Tabel `dashboard_layouts` |

### Penyimpanan tata letak

Tata letak disimpan sebagai **satu dokumen JSONB per user per ruang per permukaan**. Dokumen selalu dibaca dan ditulis utuh, ukurannya hanya beberapa KB, dan bentuknya bisa berevolusi lewat `schema_version`.

| Kolom | Tipe | Keterangan |
| --- | --- | --- |
| `id` | UUID | Kunci utama |
| `user_id` | UUID | Pemilik tata letak |
| `household_id` | UUID | Ruang; menjadi `ruang_id` setelah konsep ruang ada |
| `surface` | `String(30)` | `beranda` sekarang; kelak halaman lain atau Beranda plugin |
| `schema_version` | Integer | Versi bentuk dokumen |
| `items` | JSONB | Daftar instans berurutan |
| `parked` | JSONB | Instans dari plugin yang dinonaktifkan, supaya posisinya kembali saat plugin aktif lagi |
| `version` | Integer | Penanda konkurensi optimistis; naik setiap simpan |
| `updated_at` | Timestamp | — |

Indeks unik: `(user_id, household_id, surface)`. Tabel tambahan `dashboard_defaults` (per household) menyimpan Beranda bawaan yang ditetapkan pemilik household. Kolom memakai `String`, bukan `SAEnum`, sesuai catatan di `AGENTS.md`.

```json
{
  "schema_version": 1,
  "items": [
    {"id": "a1", "card": "core.kpi.jatah", "size": "S", "hidden": false, "devices": "all"},
    {"id": "a2", "card": "core.pengeluaran_harian", "size": "L", "devices": "wide"},
    {"id": "a3", "card": "core.pantau_amplop", "size": "S", "settings": {"envelope_id": "…"}},
    {"id": "a4", "card": "faktur.piutang", "size": "M", "settings": {"horizon_hari": 7}}
  ],
  "parked": []
}
```

### Tata letak efektif dihitung server

Server menyusun tata letak yang benar-benar tampil, supaya web, Android, dan iOS selalu sama.

1. Ambil tata letak tersimpan. Bila belum ada, pakai bawaan household atau template persona.
2. Pindahkan ke `parked` instans yang plugin-nya dijeda atau dicopot, atau yang definisinya sudah tidak ada.
3. Tandai instans yang tidak boleh tampil untuk user atau platform ini dengan `visible: false` beserta alasannya, misalnya hak plugin belum tersedia di iOS. Instans itu tetap ada di dokumen. Placeholder "buka dengan Fitur Tambahan X" hanya muncul bila mode jualan platform itu mengizinkan.
4. Kartu inti baru tidak disisipkan diam-diam. Kartu itu muncul di galeri dengan label "Baru".
5. Kembalikan dokumen lengkap, versi, dan katalog kartu yang boleh ditambahkan.

**Menyimpan dari satu perangkat tidak boleh menghapus kartu perangkat lain.** Klien selalu mengirim dokumen lengkap, termasuk instans `visible: false`. Server menolak `PUT` yang kehilangan instans tanpa disebut di daftar `removed`, dan tes otomatis memastikan menata ulang di iOS tidak menghapus kartu yang hanya tampil di web.

### API (semuanya endpoint baru, sesuai ADR-M9)

| Endpoint | Fungsi |
| --- | --- |
| `GET /dashboard/layout?surface=beranda` | Tata letak efektif, `version`, dan `parked` |
| `PUT /dashboard/layout` | Simpan seluruh dokumen dengan `if_version`; versi beda → 409, klien memuat ulang lalu menerapkan ulang perubahannya; instans yang sengaja dihapus disebut di removed |
| `POST /dashboard/layout/reset` | Kembali ke bawaan atau template tertentu |
| `GET /dashboard/cards` | Katalog kartu untuk user dan platform ini, beserta status hak aksesnya |
| `POST /dashboard/data` | Data banyak kartu sekaligus: masukan daftar instans dan periode, keluaran peta `instance_id` → `data` atau `error` |
| `GET /dashboard/data/{instance_id}` | Muat ulang satu instans kartu, misalnya salah satu dari dua kartu Pantau amplop |

Endpoint batch membuat tampilan pertama Beranda cukup satu permintaan data. Error satu penyedia hanya mengisi `error` milik kartu itu.

### Penyedia data dan satu sumber angka

- **Penyedia per kartu.** Setiap definisi kartu punya fungsi penyedia di backend, didaftarkan dengan `key` yang sama. Penyedia memakai layanan yang sudah ada: `metrics.py` dan `snapshot.py` untuk KPI, `envelope_balance.py` untuk amplop, `recurring_status.py` untuk langganan.
- **Satu snapshot per permintaan.** Endpoint batch memuat snapshot sekali, lalu membagikannya ke semua penyedia. Tidak ada rumus baru, dan tidak ada 14 kali baca database.
- **Cache dan invalidasi.** Cache kartu memakai mekanisme yang sudah ada: hook sesi SQLAlchemy (`advisor_cache.install()`) yang menghapus cache saat transaksi, pemasukan, alokasi, amplop, atau langganan berubah. Plugin mendaftarkan tabelnya ke hook yang sama.
- **Bentuk data deklaratif.** Kartu plugin mengembalikan salah satu bentuk standar (`kpi`, `progress`, `list`, `table`, `series`, `alert`) yang digambar komponen inti, misalnya `KpiTile`. Tampilan, mode gelap, dan aksesibilitas jadi seragam (rinciannya di bagian titik ekstensi).
- **Anggaran kinerja yang diusulkan.** Batch Beranda p95 ≤ 500 ms di server dan tiap penyedia plugin ≤ 150 ms. Penyedia yang melewati batas dicatat di log dengan nama kartunya.

### Frontend

- **`CardRegistry`.** Kartu inti didaftarkan di `src/cards/core/`, kartu plugin di `src/plugins/<id>/cards.js`. Komponen dimuat dengan `React.lazy`, jadi kode plugin hanya diunduh user yang memasangnya.
- **`DashboardGrid`.** Grid 12 kolom yang diisi baris demi baris sesuai urutan, tanpa `grid-auto-flow: dense`; kartu terakhir di tiap baris melebar mengisi sisa kolom. Setiap kartu dibungkus `CardFrame`: judul, menu, error boundary, `Suspense`, dan skeleton bertinggi tetap supaya halaman tidak melompat.
- **Penyegaran.** Kartu mendeklarasikan event yang membuatnya dimuat ulang (`jatahku:txn-added`, `jatahku:envelope-updated`, dan sejenisnya). Pola event ini sudah dipakai `Dashboard.jsx` sekarang, jadi tidak perlu pustaka state baru.
- **Mode Atur.** State lokal optimistis, simpan dengan jeda ±800 ms, dan tumpukan urungkan. Saat offline, Mode Atur dinonaktifkan dengan pesan, sementara Beranda tetap tampil dari cache lokal (`localCache.js`, yang perlu diperluas untuk respons batch).
- **Aplikasi.** Bundle sama dengan web (ADR-M2, ADR-M6). Getar lewat `src/native/`; komponen kartu tidak memeriksa platform.

### Pilihan pustaka drag and drop

| Pustaka | Versi (Okt 2026) | Cocok untuk model | Keyboard + pembaca layar | Sentuh | Ubah ukuran | Catatan |
| --- | --- | --- | --- | --- | --- | --- |
| `@dnd-kit/react` | 0.5.1 (15 Okt 2026) | Urutan + ukuran | Bawaan | Ya | Tidak | Jalur yang aktif dikembangkan, tetapi belum 1.0 |
| `@dnd-kit/core` + `sortable` | 6.3.1 / 10.0.0 (Des 2024) | Urutan + ukuran | Bawaan | Ya | Tidak | Kini disebut legacy; 22 bulan tanpa rilis |
| Pragmatic drag and drop | 4.0.0 (Sep 2026) | Urutan | Harus dibuat sendiri (tombol, menu, live region) | Ya | Tidak | Inti ±4,7 kB, tetapi naik tiga versi mayor dalam empat bulan |
| react-grid-layout | 2.3.0 (Okt 2026) | Grid bebas x-y | Tidak terdokumentasi | Lewat react-draggable | Ya | Ditulis ulang di v2 (Des 2025) |
| gridstack.js | 14.0.0 (Sep 2026) | Grid bebas x-y | Tidak | Ya | Ya | Ada wrapper React resmi sejak v13 |
| SortableJS | 1.15.7 (Feb 2026) | Urutan | Tidak | Ya | Tidak | Wrapper React-nya tidak dirawat sejak 2022 |

**Rekomendasi:** `@dnd-kit/react` dengan versi dikunci persis, dibungkus adapter tipis `src/lib/dnd/`. Adapter membatasi dampak bila API pra-1.0 berubah, dan memudahkan pindah pustaka. Tombol Naik/Turun tetap wajib apa pun pustakanya, karena WCAG 2.5.7 tidak menganggap keyboard saja sebagai pengganti seret.

### Kenapa bukan grid bebas x-y sekarang

| Aspek | Urutan + ukuran (direkomendasikan) | Grid bebas x-y-w-h |
| --- | --- | --- |
| Antarperangkat | Satu daftar dipakai semua lebar layar | Perlu tata letak per breakpoint (HP, tablet, layar lebar) atau penurunan otomatis |
| Celah kosong | Tidak ada; kartu terakhir di baris melebar mengisi sisa | Bisa muncul karena penempatan manual |
| Aksesibilitas | Naik/Turun cukup | Perpindahan dua dimensi sulit dibuat setara |
| Upaya | Kecil | Besar: ubah ukuran, tabrakan, pemadatan |
| Kebebasan | Urutan dan 4 ukuran | Posisi dan ukuran bebas |

Model urutan + ukuran bisa ditingkatkan ke grid bebas nanti, karena urutan bisa diterjemahkan menjadi posisi y. Arah sebaliknya jauh lebih sulit.

## Sistem plugin: pilihan arsitektur

Rekomendasinya modul buatan sendiri yang berjalan di dalam proses FastAPI yang sama (modular monolith), dengan manifest dan titik ekstensi yang sejak awal ditulis seolah untuk pihak ketiga. Sandbox dan marketplace baru dibangun bila ada pengembang luar yang nyata.

&#91;embedded content: arsitektur target · permukaan, API, inti, host plugin, plugin, data\]

Semua permukaan masuk lewat satu API. Plugin menyentuh inti hanya lewat `PluginContext`, dan inti mengabarkan perubahan kepada plugin lewat event outbox.

### Apa yang dimaksud plugin

Plugin adalah paket yang dipasang per ruang. Isinya sebagian atau semua dari daftar ini:

- entitas baru (tabel sendiri);
- penyedia data dan kartu Beranda;
- halaman, menu, dan aksi cepat di menu Catat ▾;
- field tambahan di form inti, misalnya "Proyek" di form transaksi;
- pendengar event, misalnya setelah transaksi tercatat atau periode berganti;
- job terjadwal;
- perintah dan tombol bot Telegram;
- aturan AI Advisor dan templat teksnya;
- tipe notifikasi;
- laporan dan format ekspor;
- halaman pengaturan.

### Empat tingkat kematangan

| Tingkat | Penulis plugin | Isolasi | Distribusi | Posisi Jatahku |
| --- | --- | --- | --- | --- |
| T0 Modul internal | Tim Jatahku | Tidak ada | Ikut rilis, dinyalakan flag | Sudah ada: AI Advisor dengan flag `advisor_v2_users` |
| T1 Plugin buatan sendiri dengan manifest | Tim Jatahku | Batas kode lewat SDK internal dan aturan CI | Ikut rilis, dipasang per ruang oleh user | Target fase berikutnya |
| T2 Plugin mitra terkurasi | Mitra tepercaya, misalnya kantor akuntan atau konsultan pajak | Proses terpisah atau aplikasi eksternal | Review dan kontrak | Setelah T1 matang dan ada permintaan nyata |
| T3 Marketplace terbuka | Siapa saja | Sandbox penuh | Review, tanda tangan, bagi hasil | Jauh; mungkin tidak pernah perlu |

### Tiga pilihan arsitektur

| Kriteria | A. Modul di dalam proses | B. Plugin di runtime terisolasi | C. Aplikasi eksternal lewat API |
| --- | --- | --- | --- |
| Bentuk | Paket Python `app/plugins/<id>/` + folder `frontend/src/plugins/<id>/`, dimuat saat start, aktif per ruang | Backend plugin di proses, kontainer, atau isolat terpisah; UI di iframe atau Web Worker | Plugin di-host pengembang; Jatahku menyediakan OAuth scope, webhook, dan kartu jarak jauh |
| Kecepatan membangun | Tinggi | Rendah | Sedang |
| Akses data | Lewat layanan inti (perlu disiplin) | Lewat API host | Lewat API publik + scope |
| Isolasi keamanan | Rendah: hanya untuk kode tepercaya | Tinggi | Tinggi, tetapi data keluar ke server pihak ketiga |
| Transaksi database atomik dengan inti | Ya | Tidak | Tidak |
| Beban di VPS 4 GB | Rendah | Tinggi: runtime tambahan | Rendah bagi Jatahku |
| Cocok untuk | Plugin buatan sendiri | Kode pihak ketiga yang tidak tepercaya | Integrasi mitra: akuntan, kasir, bank |
| Contoh | [Frappe apps](https://docs.frappe.io/framework/user/en/basics/apps), [Odoo modules](https://raw.githubusercontent.com/odoo/documentation/19.0/content/developer/reference/backend/module.rst) | [Figma plugins](https://developers.figma.com/docs/plugins/how-plugins-run), [Shopify UI extensions](https://shopify.dev/docs/api/checkout-ui-extensions) | [Shopify apps](https://shopify.dev/docs/apps/build/app-extensions), [Atlassian Forge](https://developer.atlassian.com/platform/forge/) |

### Rekomendasi: A sekarang, dengan garis batas yang membuka jalan ke B dan C

1. **Plugin hanya menyentuh inti lewat `PluginContext`.** SDK internal ini menyediakan baca amplop, catat transaksi lewat `expense_rules`, kirim notifikasi, dan simpan pengaturan. Aturan import-linter di CI menolak `app/plugins/**` mengimpor model atau route inti secara langsung.
2. **Data plugin di tabelnya sendiri.** Nama tabel berawalan `p_<id>_`, dan foreign key ke inti hanya ke tabel yang diizinkan.
3. **Kartu plugin memakai bentuk data deklaratif.** Komponen React kustom hanya untuk plugin buatan sendiri yang benar-benar membutuhkannya.
4. **Komunikasi lewat event dan aksi terdaftar.** Plugin tidak memanggil fungsi internal inti yang tidak tercantum di SDK.
5. **Izin manifest tetap diperiksa walau kodenya tepercaya.** Hasilnya audit yang jujur hari ini, dan sandbox yang tinggal dipasang kelak.

Garis batas ini juga menjaga kerja paralel tim: satu sesi Claude Code bisa membangun satu plugin tanpa menyentuh file inti, sama seperti pembagian kepemilikan file di `docs/ai-advisor/03-workflow.md`.

**Catatan kapasitas.** API berjalan di satu VPS 4 GB dengan satu worker uvicorn. Pekerjaan berat plugin, seperti membuat PDF laporan atau impor mutasi bank, harus dijalankan worker latar. Worker asinkron yang direncanakan untuk Kotak Struk (ADR-M16) bisa dipakai bersama.

## Manifest dan titik ekstensi

Setiap plugin membawa satu manifest yang menyatakan identitasnya, kebutuhannya, dan titik tempat ia muncul. Host membaca manifest saat start, dan tidak ada plugin yang muncul di permukaan mana pun tanpa tercantum di manifest, mirip [contribution points VS Code](https://code.visualstudio.com/api/references/contribution-points) yang statis.

### Isi manifest

| Bagian | Isi |
| --- | --- |
| Identitas | `id` (huruf kecil, unik, tidak pernah berubah), nama, versi semver, penerbit, deskripsi, ikon, kategori |
| Kompatibilitas | `engines.plugin_api` (rentang versi Plugin API), `requires` (plugin lain), `conflicts` |
| Jenis ruang | Ruang yang didukung: `rumah_tangga`, `usaha`, atau keduanya |
| Izin | Daftar scope data (bagian keamanan) |
| Entitas | Tabel milik plugin dan migrasinya |
| Kontribusi | Kartu, halaman, menu, aksi cepat, field form, event, job, perintah bot, aturan advisor, notifikasi, laporan, pengaturan |
| Hak dan harga | Gratis, ikut Pro, atau SKU plugin sendiri; masa uji coba |
| Platform | Ketersediaan di web, Android, iOS; ajakan beli mengikuti `sales_mode` di `/app/config` |
| Siklus data | Perilaku saat dinonaktifkan dan dicopot, masa simpan arsip, format ekspor |

Contoh manifest di bawah adalah plugin Faktur & Piutang. Plugin ini memakai data kontak milik Buku Usaha, jadi menyatakannya di `requires`; plugin hanya boleh merujuk tabel plugin lain yang tercantum di `requires`.

```json
{
  "id": "faktur",
  "name": "Faktur & Piutang",
  "version": "1.0.0",
  "publisher": "Jatahku",
  "engines": {"plugin_api": ">=1.0 <2.0"},
  "requires": ["buku_usaha"],
  "space_types": ["usaha"],
  "permissions": ["incomes:read", "incomes:write", "notifications:send", "reports:create"],
  "entities": ["p_faktur_faktur", "p_faktur_item", "p_faktur_pembayaran"],
  "contributes": {
    "cards": [
      {"key": "faktur.piutang", "shape": "list", "sizes": ["M", "L"]},
      {"key": "faktur.umur_piutang", "shape": "progress", "sizes": ["S", "M"]}
    ],
    "pages": [{"route": "/p/faktur", "title": "Faktur", "nav": "usaha"}],
    "quick_actions": [{"key": "faktur.baru", "label": "Faktur baru"}],
    "form_fields": [{"target": "income", "key": "faktur_id", "type": "reference",
                     "entity": "p_faktur_faktur", "label": "Pelunasan faktur"}],
    "events": ["income.recorded", "income.deleted"],
    "jobs": [{"key": "pengingat_jatuh_tempo", "schedule": "daily 08:00 user_tz"}],
    "bot_commands": [{"command": "faktur", "help": "Cek faktur", "kind": "read", "audience": "admin"}],
    "bot_callbacks": [{"prefix": "fk_"}],
    "advisor_rules": ["FK-01", "FK-02"],
    "notifications": ["faktur.jatuh_tempo"],
    "reports": [{"key": "umur_piutang", "formats": ["pdf", "csv"]}]
  },
  "entitlement": {"sku": "bundle.usaha", "trial_days": 14},
  "data_lifecycle": {"on_disable": "read_only", "on_uninstall": "archive_90_days",
                     "export": ["csv", "json"]}
}
```

### Katalog titik ekstensi

| Titik | Permukaan | Kontrak | Contoh | Aturan host |
| --- | --- | --- | --- | --- |
| `cards` | Beranda web dan aplikasi | Definisi kartu + penyedia data + bentuk deklaratif | Piutang jatuh tempo | Data dihitung server; gagal sendiri-sendiri |
| `pages` | Web dan aplikasi | Rute `/p/<plugin>/…` + komponen lazy | Daftar faktur | Semua rute plugin berawalan `/p/` |
| `nav` | Sidebar; di HP lewat menu "Lainnya" baru di bottom nav | Item menu + ikon + grup | Grup "Usaha" | Lima item bottom nav tetap milik inti |
| `quick_actions` | Menu Catat ▾ dan FAB | Aksi pembuka form | Faktur baru | Maksimal 2 per plugin |
| `form_fields` | Form transaksi, pemasukan, amplop | Field tambahan, disimpan di tabel plugin | Proyek, Pelanggan | Selalu opsional; kolom inti tidak bertambah |
| `entity_tabs` | Detail amplop dan transaksi | Tab tambahan | Faktur terkait | Hanya baca data yang diizinkan |
| `events` | Server | Pendengar setelah commit, lewat outbox | `income.recorded` → tandai faktur lunas | Isi event hanya ID; berlangganan butuh izin baca yang sesuai; tidak bisa membatalkan atau mengubah transaksi inti |
| `checks` | Server, di dalam `expense_rules` | Pemeriksaan sebelum simpan yang hanya mengembalikan peringatan | "Melewati anggaran proyek" | Tidak pernah menolak pencatatan |
| `jobs` | Scheduler dan worker | Jadwal + fungsi idempoten | Pengingat jatuh tempo | Mengikuti zona waktu user, seperti scheduler per jam yang ada |
| `bot_commands`, `bot_callbacks` | Telegram dan chat web | Didaftarkan ke `bot_commands()` dan `bot_callbacks()` | `/faktur` | Hanya perintah baca dengan penerima yang dinyatakan (data keuangan hanya untuk admin) dan callback navigasi; didaftarkan sekali saat start; prefix callback unik dan pendek (data callback Telegram maksimal 64 byte) |
| `advisor_rules` | Kartu dan chip AI Advisor, chat, notifikasi proaktif | Fungsi murni (metrik, sinyal) → insight; teks dari templat | BU-01 Piutang lewat jatuh tempo | `select.py` tetap memutuskan slot; batas insight plugin per slot |
| `notifications` | Lonceng, Telegram, email, push | Tipe notifikasi + preferensi | Faktur jatuh tempo besok | Lewat `notification_service.kirim`, setelah penyaring jam tenang dan batas harian seperti di proaktif.py (kirim sendiri tidak menyaring) |
| `reports` | Laporan dan ekspor | Generator yang berjalan di worker | Laba rugi PDF | Tidak berjalan di worker API |
| `settings` | Pengaturan → Plugin | JSON Schema → form otomatis | Nomor faktur awal | Divalidasi server |
| `importers` | Impor CSV dan mutasi bank | Parser terdaftar | Mutasi rekening CSV | Selalu menunggu konfirmasi user |
| `document_parsers` | Kotak Struk | Parser dokumen tambahan | Invoice pemasok | Tidak mencatat tanpa konfirmasi (aturan mobile #11) |

### Event inti yang disediakan

Event awal: `transaction.recorded`, `transaction.updated`, `transaction.deleted`, `income.recorded`, `income.updated`, `income.deleted`, `allocation.changed`, `envelope.created`, `envelope.updated`, `envelope.archived`, `subscription.paid`, `period.started`, `period.closed`, `balance_check.done`, `member.joined`, `member.left`, `plugin.enabled`, `plugin.disabled`.

- **Isi event hanya penanda:** `event_id`, `type`, `schema_version`, `ruang_id`, `actor_user_id`, `occurred_at`, dan ID objek yang berubah. Nominal dan deskripsi tidak ikut. Pendengar membaca ulang lewat `PluginContext`, sehingga izin dan `visibility.py` tetap berlaku. Berlangganan event butuh izin baca yang sesuai, misalnya `transactions:read` untuk event transaksi.
- **Transactional outbox:** event dan satu baris `event_deliveries` per plugin pendengar ditulis di transaksi database yang sama dengan perubahannya. Tidak ada event untuk perubahan yang batal.
- **Minimal sekali, tanpa efek ganda:** worker mengambil kiriman yang jatuh tempo dengan `FOR UPDATE SKIP LOCKED`, menjalankan pendengar, lalu menandai kiriman selesai dalam satu transaksi database. Bila worker mati di tengah jalan, semuanya batal dan dicoba lagi, jadi efek pendengar tidak tercatat dua kali. `app/services/idempotency.py` yang ada memakai Redis dengan masa simpan 2 hari, jadi tidak dipakai untuk ini.
- **Coba ulang terbatas:** jeda bertambah di setiap percobaan. Setelah batas percobaan, kiriman ditandai `dead` dan tampil di halaman admin.
- **Tanpa filter yang mengubah data inti.** WordPress membedakan [action dan filter](https://developer.wordpress.org/plugins/hooks/). Jatahku sengaja hanya memberi action dan pemeriksaan berisi peringatan, karena ledger keuangan tidak boleh diubah diam-diam oleh plugin.

### Bentuk data deklaratif untuk kartu

| Bentuk | Isi | Digambar oleh |
| --- | --- | --- |
| `kpi` | Nilai, satuan, akhiran, batang, footer, nada (ok, info, warn, danger), chip | `KpiTile` |
| `progress` | Daftar butir dengan nilai dan target | Komponen baris bar |
| `list` | Baris berisi judul, subjudul, nominal, status, tautan; maksimal 8 | Komponen daftar |
| `table` | Kolom dan baris; maksimal 10 baris | Komponen tabel |
| `series` | Label sumbu x, 1–3 seri, garis acuan opsional | Komponen grafik Recharts |
| `alert` | Nada, judul, isi, tombol aksi | Komponen peringatan |

Semua teks di dalam payload sudah dirakit server dari templat plugin, meneruskan aturan "teks hanya di `render.py`". Tombol aksi menunjuk aksi terdaftar: buka halaman, buka form, atau alur `/advisor/plan` → `/advisor/execute` untuk pemindahan dana.

### Contoh alur: pelunasan faktur

1. Admin mencatat pelunasan INV-012 sebesar Rp2,5 jt di form pemasukan ruang usaha, lewat web atau aplikasi; kotak Catat cepat bisa mengenali nomor faktur dan nominalnya. Pencatatan ruang usaha tidak lewat chat (keputusan 31 Okt 2026).
2. Jalur pemasukan inti mencatat pemasukan berjenis penjualan, lalu menulis event `income.recorded` dan baris kiriman untuk plugin Faktur di transaksi database yang sama.
3. Worker menjalankan pendengar Faktur & Piutang. Pendengar membaca pemasukan itu lewat `PluginContext`, mencocokkan INV-012, menandainya lunas, dan menandai kiriman selesai dalam satu transaksi.
4. Hook invalidasi menghapus cache kartu ruang itu.
5. Saat Beranda dibuka, kartu Piutang tidak lagi memuat INV-012, dan aturan FK-01 tidak lagi menyala.

## Entitas baru dan data plugin

Plugin buatan sendiri menyimpan entitasnya di tabel fisik sendiri yang dibuat migrasi, bukan di tabel generik. Pemisahan uang usaha dari uang rumah tangga diselesaikan dengan konsep **ruang**: household yang sekarang menjadi satu jenis ruang, dan plugin usaha dipasang di ruang usaha.

### Ruang: fondasi sebelum plugin usaha

Mencampur uang usaha dan uang pribadi adalah masalah klasik pemilik usaha kecil. Jatahku belum bisa memisahkannya karena `get_household_id` mengasumsikan satu user hanya punya satu household.

| Opsi | Cara | Kelebihan | Kekurangan |
| --- | --- | --- | --- |
| **1. Ruang usaha = household kedua (direkomendasikan)** | `households.type` (`rumah_tangga` / `usaha`); user boleh anggota beberapa ruang; ruang aktif dipilih per permintaan | Data, anggota, dan visibilitas terpisah rapi; semua aturan amplop langsung berlaku di ruang usaha | Refactor 86 titik di 31 file, konteks ruang di bot, dan kuota per ruang |
| 2. Usaha di household yang sama, lewat grup amplop "Usaha" | Tanpa perubahan model | Hampir tanpa kerja | Anggota keluarga melihat data usaha; laporan usaha tercampur; entitas akuntansi tidak cocok dengan amplop |
| 3. Akun kedua | Login terpisah | Tanpa kerja | Tidak ada tampilan gabungan; dua login; kuota ganda |

**Rincian opsi 1:**

- **Resolver tunggal untuk membaca.** `ruang_aktif(user, request)` menggantikan semua `get_household_id`. Web dan aplikasi mengirim header `X-Jatahku-Ruang`; tanpa header, server memakai ruang rumah tangga utama, jadi perilaku user yang hanya punya satu ruang tidak berubah.
- **Ruang dari objek saat menulis.** Penulisan tidak bergantung pada header: ruang ditentukan dari amplop atau objek yang ditulis, lalu keanggotaan user di ruang itu diperiksa. Antrean offline yang tidak menyimpan ruang tetap tersinkron ke ruang yang benar.
- **Satu PR, sekaligus.** Titik-titik itu memakai `scalar_one_or_none()`, yang langsung error begitu user punya dua keanggotaan. Karena itu refactor harus selesai seluruhnya sebelum ruang kedua bisa dibuat, dengan tes paritas: semua user lama harus mendapat angka identik sebelum dan sesudah refactor, memakai pola skrip `advisor_paritas`.
- **Bot.** Chat (Telegram dan chat web) selalu memakai ruang keluarga milik user; tidak ada perintah `/ruang`. Dari ruang usaha, chat hanya menerima laporan dan notifikasi yang diawali nama ruangnya, misalnya "\[Dapur Nusa\] Laba Oktober 2026" (keputusan 31 Okt 2026).
- **Pindah ruang di aplikasi.** Pemilih ruang di sidebar dan header HP. Tata letak Beranda dan menu plugin mengikuti ruang aktif.
- **Kuota per ruang.** Kuota Basic sekarang dihitung per user lintas household (`plan_limits.py`). Kuota harus dihitung per ruang, dan ruang usaha memakai hak Paket Usaha.
- **Prive (gaji pemilik).** Uang yang diambil pemilik dicatat dua sisi: keluar sebagai prive di ruang usaha dan masuk sebagai pemasukan di ruang rumah tangga, sebagai perluasan `fund_shift.py`. Prive bukan beban usaha, jadi tidak mengurangi laba. Ini fitur jualan utama untuk UMKM: uang usaha dan uang rumah tangga terpisah, tetapi tetap tersambung.
- **Jenis pemasukan.** Transfer antar-amplop (bernilai 0), top-up, dan penyesuaian cocokkan saldo sekarang tersimpan sebagai `Income` biasa. Inti menambah kolom aditif `incomes.kind` (String: pemasukan, transfer, top-up, penyesuaian), yang juga berguna untuk hitungan "ditambal N×" di Beranda. Di ruang usaha, Buku Usaha menambah jenis penjualan, modal pemilik, pinjaman, dan lain-lain. Omzet dan laba hanya menghitung penjualan.

### Strategi tabel

| Strategi | Cara | Kelebihan | Kekurangan | Dipakai untuk |
| --- | --- | --- | --- | --- |
| Tabel fisik per plugin | `p_<id>_<entitas>` dibuat migrasi Alembic | Kolom bertipe, foreign key, indeks, kueri laporan cepat | Butuh disiplin migrasi | Semua plugin buatan sendiri |
| Dokumen JSONB terkelola | `plugin_records(plugin_id, entity, household_id, data JSONB)` + validasi JSON Schema + [indeks GIN](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING) | Tanpa DDL per plugin | Tanpa foreign key; kueri agregat lebih lambat | Pengaturan, daftar kecil, dan kelak plugin mitra (T2) |
| Entity-attribute-value | Satu baris per atribut | Sangat fleksibel | Lambat dan sulit dijaga | Tidak dipakai |

**Memasang plugin tidak menjalankan DDL.** Tabel plugin dibuat lewat migrasi Alembic seperti tabel inti: dijalankan manual mengikuti checklist deploy di `AGENTS.md`, dan `deploy.sh` berhenti bila `alembic current` ≠ `alembic heads`. Memasang plugin di sebuah ruang hanya menulis satu baris instalasi. Catatan: `main.py` juga menjalankan `create_all` saat start, sehingga tabel baru bisa muncul sebelum migrasinya dijalankan; migrasi tetap satu-satunya jalur resmi, terutama untuk perubahan kolom.

### Aturan wajib untuk setiap tabel plugin

- **Kolom wajib:** `id` (UUID), `household_id`, `created_by`, `created_at`, `updated_at`, `deleted_at`. Di database namanya tetap `household_id`; `ruang_id` hanya nama di API dan SDK.
- **Indeks:** setiap indeks diawali `household_id`, karena hampir semua kueri dibatasi satu ruang.
- **Foreign key ke inti** hanya ke `households`, `users`, `envelopes`, `transactions`, dan `incomes`. Penghapusan baris inti tidak pernah dirambatkan dari tabel plugin; rujukan plugin menjadi `NULL` dan nilai penting (nominal, tanggal) disalin agar sejarah tetap utuh.
- **Rujukan antar-plugin** hanya ke tabel plugin yang tercantum di `requires`.
- **Tabel pendamping, bukan kolom baru.** Data plugin tentang transaksi disimpan di tabel 1:1, misalnya `p_buku_usaha_txn_meta(transaction_id, kontak_id, proyek)`. Alasannya sama dengan `transaction_reflections` milik Pikir-Pikir: tabel transaksi adalah tabel yang paling sering diakses.
- **Uang dan mata uang:** `Numeric(15, 2)` seperti inti; mata uang mengikuti `households.currency`.
- **Visibilitas:** entitas yang menyinggung transaksi pribadi tunduk pada `visibility.py` yang fail-closed.
- **Tipe JSON lintas database.** Tes integrasi berjalan di SQLite, jadi kolom JSON di model memakai `JSON().with_variant(JSONB(), "postgresql")`. CI perlu service PostgreSQL untuk tes migrasi dan fitur khusus PostgreSQL.
- **Pengaman berlapis (opsional di T1, wajib di T2):** [Row Level Security PostgreSQL](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) pada tabel plugin berdasarkan `household_id`, dengan nilai ruang di-set per transaksi database. Bug di kode plugin tidak bisa membaca ruang lain.
- **Kolom enum memakai `String`,** bukan `SAEnum`, sesuai pengalaman di `AGENTS.md`.

### Contoh entitas: Paket Usaha v1

| Plugin | Tabel | Kolom utama | Relasi ke inti |
| --- | --- | --- | --- |
| Buku Usaha | `p_buku_usaha_kontak` | nama, jenis (pelanggan/pemasok), telepon, catatan | — |
| Buku Usaha | `p_buku_usaha_income_meta` | jenis (penjualan, modal pemilik, pinjaman, lain-lain), kontak\_id | `income_id` → `incomes` (1:1) |
| Buku Usaha | `p_buku_usaha_txn_meta` | kontak\_id, proyek, akun | `transaction_id` → `transactions` (1:1) |
| Faktur & Piutang | `p_faktur_faktur` | kontak\_id, nomor, tanggal, jatuh\_tempo, total, status (draf, terkirim, sebagian, lunas, batal) | — |
| Faktur & Piutang | `p_faktur_item` | faktur\_id, deskripsi, jumlah, harga | — |
| Faktur & Piutang | `p_faktur_pembayaran` | faktur\_id, jumlah, tanggal | `income_id` → `incomes` (pelunasan menjadi pemasukan inti) |
| Tagihan Pemasok | `p_tagihan_pemasok_tagihan` | kontak\_id (pemasok), nomor, jatuh\_tempo, total, status | `transaction_id` → `transactions` saat dibayar |

Uang yang benar-benar masuk dan keluar tetap dicatat sebagai pemasukan dan transaksi inti. Plugin menambahkan konteks (siapa, faktur mana, proyek apa, jenis pemasukan) tanpa membuat ledger kedua.

### Siklus data saat plugin dinonaktifkan dan dicopot

| Status | Data plugin | Kartu dan menu | Event dan job | Kembali? |
| --- | --- | --- | --- | --- |
| Aktif | Baca-tulis | Tampil | Berjalan | — |
| Dijeda user | Tetap ada, baca-saja lewat halaman arsip dan ekspor | Kartu ke `parked`, menu hilang | Berhenti | Ya, seketika |
| Hak habis (uji coba atau langganan berakhir) | Sama dengan dijeda; banner perpanjang hanya bila mode jualan mengizinkan | Seperti dijeda | Berhenti | Ya, setelah hak aktif |
| Dicopot | Layar copot selalu menawarkan ekspor lebih dulu; data diarsipkan (`deleted_at`) dan bisa dipulihkan 90 hari | Hilang | Berhenti | Ya, dalam 90 hari |
| Dibersihkan | Dihapus permanen oleh job, dengan pemberitahuan 7 hari sebelumnya | — | — | Tidak |
| Anggota menghapus akun | Data plugin cakupan pribadinya dihapus permanen. Data plugin milik ruang tetap ada, dengan nama pencatat diganti "Mantan anggota", sesuai rekomendasi keputusan 5 kajian mobile | Tetap untuk anggota lain | Tetap | Tidak |
| Ruang dihapus atau anggota terakhir pergi | Semua data plugin ruang itu dihapus permanen | — | — | Tidak |

- **Data inti tetap.** Pemasukan dan transaksi yang dibuat lewat plugin adalah fakta keuangan, jadi tidak ikut terhapus saat plugin dicopot.
- **Catatan pajak.** UMKM pemakai PPh final diimbau mencatat omzet bulanan, dan catatan serta dokumen pendukungnya disimpan 10 tahun ([DDTC](https://news.ddtc.co.id/berita/nasional/1804802/setor-pph-final-umkm-tak-perlu-lapor-spt-masa-tapi-perlu-pencatatan)). Kewajiban itu milik wajib pajak, bukan Jatahku, tetapi layar copot harus mengingatkannya dan menyediakan ekspor lengkap.
- **Hapus akun yang sungguhan.** Kajian mobile menemukan hapus akun saat ini hanya anonimisasi yang tidak lengkap. Perbaikannya harus mengikuti tabel di atas untuk semua tabel `p_*` sejak plugin pertama, dan foreign key ke `users` di tabel plugin memakai `ON DELETE SET NULL` atau `CASCADE` sesuai cakupan datanya.

## Siklus hidup, versi, kompatibilitas, dan pengujian

Plugin bergerak di dua sumbu: status per ruang dan versi kode per rilis. Karena plugin buatan sendiri ikut rilis, versi kodenya sama untuk semua ruang; yang berbeda per ruang hanya status, pengaturan, dan versi datanya.

&#91;embedded content: siklus status plugin per ruang · 7 status\]

Mencopot plugin yang sedang aktif menjedanya dulu, lalu menawarkan ekspor. Hanya Dibersihkan yang tidak bisa dibalik.

### Status per ruang

| Status | Masuk lewat | Yang terjadi |
| --- | --- | --- |
| Tersedia | Plugin ada di katalog dan cocok dengan jenis ruang | Tampil di katalog; kartunya muncul di galeri dengan label plugin |
| Terpasang | Pemilik atau admin ruang menyetujui layar izin | Baris `plugin_installations` dibuat dengan status `installed`; langkah `on_install` per ruang berjalan idempoten, misalnya mengisi bagan akun bawaan; wizard singkat; tawaran kartu |
| Aktif | Wizard selesai atau dilewati | Status `active`; semua kontribusi tampil; event dan job berjalan |
| Dijeda | User menjeda, atau hak habis | Status `paused`; kontribusi hilang; data baca-saja |
| Dimatikan server | Admin memasukkan plugin ke saklar darurat di `AppSetting` saat insiden | Kontribusi disembunyikan di semua ruang tanpa mengubah status per ruang; user melihat "Sedang diperbaiki"; data aman |
| Dicopot | User mencopot setelah layar ekspor | Status `uninstalled`; data diarsipkan 90 hari |
| Dibersihkan | Job pembersih setelah 90 hari | Data dihapus permanen |

**Siapa yang boleh memasang.** Peran `owner` dan `admin` di household (`HouseholdRole` sudah ada) memasang plugin untuk ruang. Manifest boleh menyatakan cakupan `pribadi` untuk plugin yang hanya untuk pemasangnya, misalnya Portofolio Investasi, sehingga anggota lain tidak melihatnya.

### Tabel pengelola

| Tabel | Isi |
| --- | --- |
| `plugin_installations` | `household_id`, `plugin_id`, `owner_id` (terisi untuk cakupan pribadi), `status` (`installed`, `active`, `paused`, `uninstalled`), `installed_by`, `granted_permissions` (JSONB), `settings` (JSONB), `data_version`, `disabled_reason`; unik per `(household_id, plugin_id, owner_id)` |
| `entitlements` | Hak per user atau ruang: `sku` (`pro`, `plugin.buku_usaha`, `bundle.usaha`), `source` (transfer, promo, play, appstore, gateway), mulai, berakhir, status, rujukan eksternal yang unik per sumber. Satu tabel untuk Pro dan plugin, sesuai rancangan hak di kajian mobile |
| `event_outbox` | Event inti berurutan; isinya hanya ID |
| `event_deliveries` | Satu baris per event per plugin pendengar: status, jumlah percobaan, jadwal percobaan berikutnya |
| `plugin_audit_log` | Siapa memasang, mengubah izin, menjeda, mencopot; akses data sensitif oleh plugin |

Saklar darurat tidak disimpan sebagai status di tabel ini, supaya status asli tiap ruang tidak hilang saat saklar dimatikan lagi.

### Versi dan kompatibilitas

- **Plugin API ber-semver.** Di dalam satu versi mayor, perubahan hanya bertambah. Yang usang diberi tanda dan tetap hidup minimal dua rilis minor, sejalan dengan ADR-M9.
- **Migrasi skema tiga langkah.** Tabel plugin berubah dengan pola perluas → pindahkan data → persempit, karena aplikasi di HP bisa menjalankan bundle lama selama berminggu-minggu.
- **Migrasi data per ruang.** Langkah upgrade per ruang (`upgrade_steps`) dijalankan worker secara idempoten, tidak di tengah permintaan user. `data_version` mencatat langkah mana yang sudah jalan.
- **Versi klien minimum.** Manifest menyatakan `min_client` per platform. Server menyembunyikan kontribusi plugin untuk aplikasi yang terlalu lama, berdasarkan header `X-Jatahku-Client` (aturan mobile #3).
- **Rilis bertahap.** Setiap plugin punya flag rollout di `AppSetting`, seperti `advisor_v2_users`: daftar user dulu, lalu `*`.

### Pengujian

1. **Validator manifest di CI:** skema sah, `key` unik, prefix callback tidak bertabrakan, `requires` lengkap, dan setiap pemanggilan `PluginContext` sesuai izin yang dideklarasikan.
2. **Harness uji plugin:** fixture ruang + `PluginContext` palsu. Penyedia kartu dan aturan advisor diuji sebagai fungsi murni, sama seperti aturan AI Advisor sekarang.
3. **Tes paritas web ↔ Telegram:** kasus bersama dalam satu file JSON untuk fitur plugin yang bisa dipakai di dua kanal, meniru `parseAmount.cases.json`.
4. **Tes isolasi:** plugin yang dijeda tidak meninggalkan kartu, menu, perintah, atau job; data ruang lain dan isi event yang tidak diizinkan tidak pernah terbaca.
5. **Tes tata letak lintas perangkat:** menata ulang Beranda di iOS tidak menghapus kartu yang hanya tampil di web.
6. **Tes migrasi:** tambahkan service PostgreSQL di CI (`test.yml` sekarang tanpa PostgreSQL), lalu uji upgrade dan downgrade di sana.
7. **Tes kinerja penyedia:** data contoh 12 bulan; penyedia yang melewati anggaran waktu menggagalkan CI.
8. **Latihan saklar:** menyalakan saklar darurat benar-benar menyembunyikan plugin dalam satu siklus muat ulang.
9. **Skrip paritas sebelum `*`:** pola `advisor_paritas` dipakai ulang untuk memastikan angka inti tidak berubah setelah plugin aktif.

## Keamanan, izin, dan privasi

Plugin buatan sendiri tetap diperlakukan sebagai tamu: hanya menyentuh data yang izinnya diberikan saat dipasang, dan setiap akses penting tercatat. Disiplin ini murah sekarang, dan membuat sandbox serta plugin mitra aman kelak.

### Daftar izin

| Scope | Mengizinkan | Risiko | Teks di layar izin |
| --- | --- | --- | --- |
| `envelopes:read` | Daftar amplop, saldo, alokasi; amplop pribadi anggota lain tidak pernah | Rendah | Melihat amplop dan saldonya |
| `envelopes:write` | Membuat dan mengubah amplop; tidak menghapus | Sedang | Membuat dan mengubah amplop |
| `transactions:read` | Transaksi; deskripsi privat anggota lain tetap disamarkan | Sedang | Melihat transaksi |
| `transactions:write` | Mencatat transaksi lewat `expense_rules` | Tinggi | Mencatat transaksi atas namamu |
| `incomes:read`, `incomes:write` | Pemasukan dan alokasinya | Sedang–tinggi | Melihat dan mencatat pemasukan |
| `funds:move` | Memindah dana antar-amplop atau antar-ruang, selalu lewat rencana + konfirmasi | Tinggi | Mengusulkan pemindahan dana (kamu yang menyetujui) |
| `members:read` | Nama dan peran anggota ruang | Rendah | Melihat anggota ruang |
| `notifications:send` | Notifikasi, dibatasi jam tenang dan kuota harian | Rendah | Mengirim pengingat |
| `files:read`, `files:write` | Lampiran dan Kotak Struk | Sedang | Membaca dan menyimpan lampiran |
| `reports:create` | Membuat laporan dan ekspor | Rendah | Membuat laporan |
| `network:<domain>` | Memanggil layanan luar yang tercantum saja | Tinggi: data keluar | Menghubungi layanan \<nama> |
| `ai:analyze` | Mengirim data ke model AI pihak ketiga | Sangat tinggi | Mati bawaan; persetujuan terpisah |

`ai:analyze` sengaja dibuat paling ketat. Pemilik produk memutuskan AI Advisor hanya memakai aturan, tanpa LLM, demi privasi keuangan; plugin tidak boleh diam-diam melonggarkan keputusan itu.

### Penegakan

- **Di server, setiap panggilan.** `PluginContext` memeriksa scope di setiap pemanggilan, menolak yang tidak diizinkan, dan mencatatnya. Pemeriksaan di frontend hanya kosmetik.
- **Ruang tidak pernah dari body.** Pembacaan memakai `ruang_aktif`; penulisan menentukan ruang dari objek yang ditulis, misalnya amplop, lalu memeriksa keanggotaan. `ruang_id` dari body atau query tidak pernah dipercaya, sehingga celah IDOR tertutup sejak awal.
- **Event tanpa isi sensitif.** Payload event hanya berisi ID, dan berlangganan event butuh izin baca yang sesuai. Plugin yang hanya punya `notifications:send` tidak pernah melihat transaksi anggota lain.
- **Tulis yang aman.** Penulisan memakai `client_ref` untuk idempotensi dan masuk ke `plugin_audit_log`. Pemindahan dana selalu lewat pola rencana → eksekusi dengan konfirmasi, seperti aturan AI Advisor #5.
- **Kontrak visibilitas di dalam SDK.** Pembaca data di `PluginContext` memanggil `visibility.py`: agregat menghitung semua transaksi, deskripsi privat anggota lain disamarkan.
- **Batas laju.** Kuota tulis dan notifikasi per plugin per ruang, supaya bug di satu plugin tidak membanjiri database atau HP user.
- **Rahasia terenkripsi.** Pengaturan plugin yang berisi kunci API, misalnya payment gateway, dienkripsi di database, tidak pernah dikirim utuh ke frontend, dan tidak pernah disimpan di `localStorage` (aturan mobile #6).
- **Callback bot.** Setiap callback memeriksa bahwa objeknya milik ruang dan user yang menekan tombol.
- **Rantai pasok.** Dependensi plugin dikunci versinya dan diperiksa `pip-audit` serta `npm audit` di CI.
- **Menuju T2.** Untuk kode mitra kelak: kartu hanya bentuk deklaratif, UI tambahan di iframe ber-sandbox atau Web Worker seperti [Shopify UI extensions](https://shopify.dev/docs/api/checkout-ui-extensions), dan akses jaringan hanya ke domain yang dideklarasikan seperti [Figma](https://developers.figma.com/docs/plugins/manifest) dan [Atlassian Forge](https://developer.atlassian.com/platform/forge/manifest-reference/permissions/).

### Kepatuhan UU PDP

UU PDP No. 27/2022 berlaku penuh sejak 17 Okt 2024, dan PP 33/2026 sebagai aturan pelaksananya ditetapkan 16 Jul 2026 serta berlaku 16 Jan 2027 ([PwC](https://www.pwc.com/id/en/pwc-publications/services-publications/digital-publications/government-regulation-33-2026-personal-data-protection.html)). Lembaga PDP belum terbentuk dan Komdigi mengawasi sementara ([Bisnis](https://teknologi.bisnis.com/read/20260913/84/2003698/pembentukan-badan-pdp-dipercepat-implementasi-uu-pdp-dinilai-belum-efektif)).

| Kewajiban | Penerapan pada plugin |
| --- | --- |
| Persetujuan harus spesifik; persetujuan yang digabung dengan S&K dianggap ambigu ([Bisnis](https://teknologi.bisnis.com/read/20260829/84/1999753/aturan-turunan-uu-pdp-persetujuan-data-konsumen-lebih-ketat)) | Layar izin per plugin, terpisah dari S&K, menyebut data dan tujuannya; persetujuan terpisah lagi untuk `network:*` dan `ai:analyze` |
| Hak subjek data dipenuhi dalam 3 × 24 jam ([Hukumonline](https://pro.hukumonline.com/a/lt6a97c3fe4527c/pemerintah-akhirnya-terbitkan-kerangka-implementasi-pelindungan-data-pribadi--berlaku-mulai-16-januari-2027)) | Setiap plugin wajib menyediakan ekspor dan hapus otomatis (bagian `data_lifecycle` di manifest) |
| Notifikasi kegagalan pelindungan data paling lambat 3 × 24 jam ([Pasal 46](https://pasal.id/peraturan/uu/uu-no-27-tahun-2022/pasal-46)) | Audit log per plugin mempercepat penentuan data dan user yang terdampak |
| Pencatatan kegiatan pemrosesan | Daftar pemrosesan dibuat otomatis dari manifest: entitas, kategori data, tujuan, masa simpan |
| Minimalisasi data | Plugin hanya menyimpan yang perlu. NIK atau NPWP hanya untuk plugin pajak yang memerlukannya, dan dienkripsi |
| Peran pengendali dan prosesor | Untuk data pelanggan dan karyawan UMKM, pemilik usaha adalah pengendali dan Jatahku prosesor. S&K plugin usaha butuh klausul pemrosesan data |
| Sanksi administratif hingga 2% pendapatan tahunan | Alasan bisnis untuk tidak menunda semua hal di atas |

**Data keuangan dan data anak adalah data spesifik, jadi penilaian dampak wajib.** Pasal 4 ayat (2) UU PDP memasukkan data keuangan pribadi dan data anak ke dalam data pribadi spesifik ([pasal.id](https://pasal.id/peraturan/uu/uu-no-27-tahun-2022/pasal-4)). Pasal 34 mewajibkan penilaian dampak untuk pemrosesan berisiko tinggi, termasuk pemrosesan data pribadi spesifik ([Hukumonline](https://www.hukumonline.com/berita/a/memahami-data-protection-impact-assessments-dalam-pelindungan-data-pribadi-lt667615ca09b2e/)). Karena itu setiap plugin yang menyimpan jenis data baru membawa penilaian dampak tertulis, terutama Uang Saku Anak, Gaji Karyawan, dan Kas Komunitas.

Setiap plugin yang mengumpulkan jenis data baru juga mewajibkan pembaruan kebijakan privasi serta isian Data Safety (Play) dan App Privacy (Apple), yang sudah ditandai kajian mobile sebagai syarat rilis toko.

## Plugin di semua permukaan

Setiap plugin menyatakan kontribusinya per permukaan: web dan aplikasi untuk pencatatan, chat untuk laporan dan notifikasi (keputusan 31 Okt 2026). Aturan toko aplikasi menentukan cara plugin dikirim serta dijual di Android dan iOS.

### Telegram dan chat web

- **Chat untuk ruang keluarga (keputusan 31 Okt 2026).** Telegram dan chat web hanya mencatat ke ruang keluarga milik user, seperti sistem yang berjalan sekarang. Tidak ada transaksi Fitur Tambahan atau ruang usaha lewat chat, dan tidak ada perintah `/ruang`; ruang usaha dicatat lewat web dan aplikasi.
- **Laporan dan notifikasi.** Fitur Tambahan hanya mengirim laporan dan notifikasi ke chat, diawali nama ruangnya, misalnya "\[Dapur Nusa\] Laba Oktober 2026". Tombolnya hanya membuka halaman di Jatahku; tidak ada tombol yang mencatat atau mengubah data.
- **Perintah baca untuk admin.** Perintah seperti `/laba` hanya untuk admin ruang usaha. Menu perintah Telegram diperbarui per chat sesuai peran, memakai scope chat di Bot API, supaya karyawan tidak melihat perintah yang bukan haknya.
- **Daftar sekali, periksa saat dipanggil.** `create_bot_app()` mendaftarkan semua handler sekali saat start. Saat dipanggil, dispatcher memeriksa plugin aktif dan peran user; user yang tidak berhak mendapat jawaban bahwa laporan itu hanya untuk admin ruang.
- **Data callback lewat Redis.** Data callback Telegram dibatasi 64 byte, sedangkan UUID saja 36 karakter. Plugin memakai pola yang sudah ada: kunci pendek di callback, isi lengkap di Redis. Callback plugin hanya untuk navigasi baca, misalnya memilih ruang.
- **Teks dari templat plugin.** Balasan bot dan tampilan web memakai templat yang sama, meneruskan aturan teks satu sumber.

### AI Advisor

- **Aturan plugin = fungsi murni.** Setiap plugin punya `metrics.py` dan loader snapshot sendiri, lalu aturan `(metrik, sinyal) → insight[]` dengan id ber-namespace, misalnya BU-01 dan PJ-01.
- **Slot tetap diputuskan inti.** `select.py` menilai insight plugin bersama insight inti, dengan batas per plugin per slot supaya kartu AI Advisor tidak didominasi satu plugin.
- **Empat tempat tampil:** kartu AI Advisor, chip di kartu KPI plugin, jawaban chat untuk admin ("siapa yang belum bayar?"), dan notifikasi proaktif yang tetap tunduk pada batas 1 per hari dan jam tenang (`proaktif.py`).

### Kotak Struk, notifikasi, dan push

- **Parser dokumen tambahan.** Plugin menambah parser ke pipeline Kotak Struk (ADR-M16), misalnya nota pemasok menjadi tagihan, atau bukti setor pajak menjadi status lunas. Hasilnya selalu kandidat yang menunggu konfirmasi, dengan pencegah dobel berdasarkan hash dan nomor referensi.
- **Tipe notifikasi berupa teks.** `Notification.type` sekarang memakai `SAEnum`, sehingga setiap tipe baru butuh migrasi enum. Plugin membutuhkan kolom bertipe `String` (misalnya `kind`), sejalan dengan catatan di `AGENTS.md`.
- **Preferensi notifikasi umum.** `notification_preferences` sekarang menyimpan satu kolom per tipe per kanal. Plugin butuh tabel preferensi umum berisi user, jenis notifikasi, kanal, dan status nyala.
- **Penyaring tetap di pemanggil.** `notification_service.kirim` tidak menyaring jam tenang dan batas harian; pemanggilnya yang menyaring. Host plugin memakai penyaring yang sama dengan `proaktif.py` sebelum memanggil `kirim`.
- **Push ikut otomatis.** Kanal push FCM (ADR-M12) dipasang di `notification_service`, jadi notifikasi plugin mendapat push tanpa kerja tambahan.

### Aplikasi Android dan iOS: cara kode plugin dikirim

| Aturan | Isi | Dampak untuk plugin Jatahku |
| --- | --- | --- |
| [Apple 2.5.2](https://developer.apple.com/app-store/review/guidelines/) | Aplikasi harus mandiri; tidak boleh mengunduh kode yang menambah atau mengubah fitur | Kode UI plugin ikut di bundle aplikasi sebagai potongan lazy, bukan diunduh per plugin |
| [Apple 4.7](https://developer.apple.com/app-store/review/guidelines/) (pembaruan November 2025) | Mini app, chatbot, dan plug-in HTML5/JS di luar binary boleh, dengan syarat privasi, IAP untuk barang digital, persetujuan eksplisit, dan indeks dengan universal link | Pintu untuk plugin mitra kelak ada, tetapi tanggung jawab moderasi penuh ada di Jatahku |
| [Apple 2.5.19](https://developer.apple.com/app-store/review/guidelines/) (tercantum per Oktober 2026) | Tidak boleh ada fitur tersembunyi, tidur, atau tidak terdokumentasi | Katalog plugin terlihat di aplikasi; catatan review menjelaskan plugin; akun demo memakai plugin aktif; kode plugin yang belum diumumkan tidak ikut bundle |
| [Google Play: Device and Network Abuse](https://support.google.com/googleplay/android-developer/answer/9888379) | Tidak boleh mengunduh kode eksekusi dari luar Play, kecuali kode yang diinterpretasi seperti JavaScript di WebView | Lebih longgar dari Apple, tetapi Jatahku memakai aturan Apple sebagai batas bersama |
| ADR-M2 dan aturan mobile #8 | UI web diperbarui lewat OTA; perubahan native hanya lewat toko | OTA hanya untuk perbaikan plugin yang sudah lolos review. Plugin baru, termasuk yang berbayar, masuk aplikasi lewat rilis toko yang direview |

**Kesimpulannya:** plugin buatan sendiri adalah fitur di dalam bundle yang dinyalakan per ruang, dan setiap plugin baru masuk aplikasi lewat rilis toko yang direview. Di web, plugin baru tetap bisa langsung tayang setelah merge seperti biasa.

### Menjual plugin di aplikasi

- **Satu mesin hak.** Hak plugin dicatat di tabel `entitlements` yang sama dengan Pro, dengan sumber transfer, promo, Play, App Store, atau payment gateway (ADR-M10).
- **Mode jualan per platform.** Ajakan beli plugin membaca `sales_mode` di `/app/config` (`none`, `store`, `web`), lewat helper yang sama dengan Pro (aturan mobile #4).
- **iOS.** Membuka fitur berbayar wajib lewat in-app purchase (3.1.1). Hak yang dibeli di web hanya boleh dipakai di aplikasi bila item yang sama juga dijual sebagai IAP (3.1.3(b)). Karena itu, sampai produk IAP-nya ada, plugin berbayar disembunyikan di iOS, termasuk bagi user yang sudah membelinya di web.
- **Google Play.** User choice billing tersedia di Indonesia untuk aplikasi non-game, dengan potongan biaya layanan 4% ([Google](https://support.google.com/googleplay/android-developer/answer/13821247)). Mahkamah Agung menolak kasasi Google atas putusan KPPU pada 10 Mar 2026, sehingga putusan itu berkekuatan hukum tetap: Google harus berhenti mewajibkan Google Play Billing dan membuka user choice billing untuk semua developer dengan potongan minimal 5% selama satu tahun ([ASEAN Competition](https://www.asean-competition.org/read-news-supreme-court-rejects-googles-cassation-kppu-decision-on-google-play-billing-becomes-legally-binding)). Halaman Google belum mencerminkan angka 5%, jadi pelaksanaannya perlu dicek ulang sebelum jualan dimulai.
- **Komisi.** Apple Small Business Program 15% ([Apple](https://developer.apple.com/app-store/small-business-program/)), dan tier 15% Google seperti dicatat kajian mobile.
- **Sedikit SKU.** Plugin berbayar sebaiknya dijual dalam beberapa paket, misalnya Paket Usaha, supaya jumlah produk IAP, harga, dan pengujian pembelian tetap terkendali.

## Model bisnis dan monetisasi

Plugin memberi Jatahku pendapatan berulang tanpa membuat aplikasi rumah tangga menjadi rumit. Plugin keluarga sebaiknya gratis atau ikut Pro, sedangkan plugin usaha dijual berlangganan per ruang usaha, karena biayanya juga berulang: pembaruan aturan pajak, dukungan, dan akurasi laporan.

### Konteks pasar

- **Pasar besar dan sudah digital.** Kementerian UMKM menyebut 65,5 juta unit UMKM ([Antara](https://www.antaranews.com/berita/4968741/kementerian-umkm-)), sementara BPS mencatat sekitar 59 juta usaha pada 2023 ([Bisnis](https://ekonomi.bisnis.com/read/20260522/9/1975662/bps-jumlah-umkm-di-indonesia-mencapai-59-juta-usaha-tahun-2023)). Per Juni 2026 ada 44,86 juta merchant QRIS, 96,68% di antaranya UMKM ([Katadata](https://katadata.co.id/finansial/keuangan/6a9e3b775a371/bi-transaksi-qris-tembus-15-miliar-hingga-juli-2026)).
- **Aplikasi pencatat saja sulit bertahan.** BukuKas tutup pada Mei 2023 ([Bisnis](https://teknologi.bisnis.com/read/20231213/266/1723450/daftar-11-startup-tutup-dan-phk-di-ri-terbaru-ada-pegipegi/2)), dan BukuWarung kini berfokus pada QRIS dan pinjaman modal ([Bisnis](https://teknologi.bisnis.com/read/20260127/84/1947604/bukuwarung-cetak-60-juta-transaksi-pada-2025-punya-8-juta-pengguna)).
- **Posisi Jatahku.** Pesaing kuat di kasir dan akuntansi penuh (Majoo, Moka, Mekari Jurnal, Accurate, Kledo). Celah Jatahku adalah pengendalian: memisahkan uang usaha dari uang rumah tangga, menjatah dana usaha dengan amplop, dan pajak final yang sederhana, semuanya lewat chat Telegram.

| Pemain | Fokus | Status terakhir yang ditemukan |
| --- | --- | --- |
| BukuWarung | Pembukuan, kini QRIS dan pinjaman | Aktif, >8 juta pengguna (data 2025, terbit Jan 2026) |
| Majoo | Kasir, keuangan, HRIS | Aktif, >45.000 UMKM (Sep 2025, [majoo](https://majoo.id/news/more/majoo-rayakan-6-tahun-dengan-6perience-inovasi-digital-dan-penguatan-customer-experience)) |
| Mekari Jurnal | Akuntansi cloud | Aktif, >35.000 bisnis (2024, [detik](https://inet.detik.com/business/d-7514764/platform-mekari-jurnal-bantu-optimalkan-bisnis-dengan-sistem-terintegrasi)) |
| Kledo | Akuntansi | Aktif; paket Free sampai Rp399.900/bulan (Agu 2026, [HashMicro](https://www.hashmicro.com/id/blog/aplikasi-kledo/), sumber pesaing) |
| BukuKas | Pembukuan | Tutup Mei 2023 |

### Model harga per jenis plugin

| Model | Contoh plugin | Alasan |
| --- | --- | --- |
| Gratis untuk semua | Asuransi & Proteksi, Kendaraan & Rumah, Patungan & Split Bill, Akses Akuntan | Memperkuat kebiasaan mencatat; retensi inti |
| Ikut Pro | Arisan, Zakat & Donasi, Uang Saku Anak, Utang & Cicilan | Menambah nilai Pro yang sudah dibeli user rumah tangga |
| Langganan per ruang usaha (Paket Usaha) | Buku Usaha, Pajak UMKM, Stok, Gaji Karyawan | Biaya berulang; ruang usaha membutuhkan paket ini |
| Bundel vertikal | Paket Warung, Paket Jasa, Paket Kos | Satu harga untuk satu jenis usaha; lebih mudah dijual |
| Tambahan berbasis pemakaian | Pengingat WhatsApp, sinkron mutasi bank | Biaya pihak ketiga diteruskan per pemakaian |

**Hipotesis harga untuk diuji:** Paket Usaha Rp25.000–Rp50.000 per ruang per bulan, dengan diskon tahunan dan uji coba 14 hari. Angka ini sengaja jauh di bawah aplikasi akuntansi penuh, karena cakupannya juga lebih sempit.

### Aturan monetisasi

- **Keselamatan data tidak dijual.** Ekspor, hapus akun, dan catatan yang jujur tidak pernah berbayar.
- **Kuota Basic tidak berlaku di ruang usaha.** Ruang usaha mensyaratkan Paket Usaha, sehingga batas 6 amplop dan 50 transaksi hanya untuk ruang rumah tangga Basic.
- **User promo dihargai.** User yang mendapat Pro gratis lewat promo 100 user pertama mendapat uji coba Paket Usaha lebih panjang sebagai penguji awal.
- **Bayar berulang butuh gateway.** Transfer manual dengan unggah bukti dan persetujuan admin tidak cocok untuk langganan. Dibutuhkan payment gateway dengan tagihan berulang; kolom `midtrans_id` sudah ada di `payment_orders`.
- **Komisi toko.** Di aplikasi, harga plugin berbayar menanggung komisi toko 15% (lihat bagian permukaan). Pemilik produk memutuskan apakah harga toko sama dengan web atau dinaikkan.
- **Bagi hasil mitra (kelak, T2).** Sebagai pembanding, Shopify memungut 0% atas US$1 juta pertama lalu 15% ([Shopify](https://shopify.dev/apps/launch/distribution/revenue-share)), dan Atlassian memberi developer Forge 83% sejak 1 Okt 2026 ([Atlassian](https://developer.atlassian.com/market/faqs/pricing-payment-billing)).
- **Rujukan produk keuangan perlu kajian sendiri.** Menawarkan KUR atau pinjaman di dalam aplikasi menyentuh aturan OJK, jadi tidak dimasukkan ke rencana tanpa kajian hukum.

## Katalog plugin potensial

Ada 37 kandidat plugin dalam tiga kelompok, ditambah enam paket vertikal. Yang paling bernilai adalah plugin yang memakai kekuatan yang sudah dimiliki Jatahku: amplop, alokasi pemasukan, bot Telegram, dan scan struk.

**Cara membaca kolom.** Harga: Gratis, Pro, Paket Usaha, atau Tambahan (bayar per pemakaian). Kompleksitas: *Rendah* = 1–2 entitas dengan kartu dan bot sederhana, tanpa aturan regulasi; *Sedang* = beberapa entitas, job, bot, dan laporan; *Tinggi* = aturan pajak atau akuntansi, integrasi pihak luar, atau data karyawan dan anak.

### A. Keuangan usaha (dipasang di ruang usaha)

| Plugin | Untuk siapa | Entitas baru | Kartu Beranda | Bot dan permukaan lain | Harga | Kompleksitas |
| --- | --- | --- | --- | --- | --- | --- |
| Buku Usaha | Semua UMKM | Kontak, jenis pemasukan, akun usaha, aturan alokasi omzet, `txn_meta` | Laba rugi bulan ini; Kas usaha; Arus kas 13 minggu; Beban per akun | `/laba` untuk admin, laporan PDF | Paket Usaha | Sedang |
| Faktur & Piutang | Jasa, grosir, B2B | Faktur, item, pembayaran | Piutang jatuh tempo; Umur piutang | `/faktur` untuk admin (cek saja), PDF faktur, tombol bagikan via tautan WhatsApp | Paket Usaha | Sedang |
| Tagihan Pemasok | Usaha dengan pemasok tetap | Tagihan pemasok, jadwal bayar | Tagihan pemasok minggu ini | Nota pemasok dari Kotak Struk menjadi tagihan | Paket Usaha | Sedang |
| Pajak UMKM | OP, PT perorangan, koperasi beromzet ≤ Rp4,8 miliar | Profil pajak, rekap omzet, setoran | Omzet kumulatif vs Rp500 juta dan Rp4,8 miliar; PPh bulan ini dan tenggatnya | `/pajak` untuk admin, pengingat H-3, bukti setor dari Kotak Struk | Paket Usaha | Sedang |
| Stok & Persediaan | Toko, grosir, seller online | Produk, gudang, mutasi stok | Stok menipis; Nilai persediaan; Terlaris | Notifikasi stok menipis | Paket Usaha | Tinggi |
| Resep & HPP | Kuliner, kafe, katering | Bahan, resep, harga bahan | Margin per menu; Bahan naik harga | Nota bahan dari Kotak Struk memperbarui harga bahan | Paket Usaha | Sedang |
| Kasir Ringan | Warung tanpa mesin kasir | Penjualan, sesi kasir | Omzet hari ini; Omzet per metode bayar | Rekap tutup kasir dikirim ke admin | Paket Usaha | Sedang |
| Proyek & Cabang | Kontraktor, agensi, multi-outlet | Proyek atau cabang, anggaran proyek | Laba per proyek; Anggaran proyek terpakai | Field "Proyek" di form | Paket Usaha | Sedang |
| Gaji Karyawan & Kasbon | Usaha dengan karyawan | Karyawan, komponen gaji, kasbon, slip | Gaji bulan ini; Kasbon berjalan | Slip gaji PDF; PPh 21 TER dan BPJS | Paket Usaha | Tinggi |
| Reimburse & Persetujuan | Perusahaan kecil | Klaim, persetujuan, kebijakan | Klaim menunggu persetujuan | Foto struk dari Kotak Struk; persetujuan di aplikasi, notifikasi ke admin | Paket Usaha | Sedang |
| Rekonsiliasi Mutasi | Usaha dengan banyak transfer | Batch impor, pencocokan | Transaksi belum cocok | Impor CSV mutasi rekening dan e-wallet | Paket Usaha | Sedang |
| Penjualan Marketplace | Seller marketplace | Impor settlement, potongan | Dana belum cair; Potongan admin | Impor laporan CSV per marketplace | Paket Usaha | Sedang |
| Pinjaman Usaha | Peminjam KUR atau leasing | Pinjaman, jadwal angsuran | Angsuran bulan ini; Sisa pokok | Pengingat angsuran | Paket Usaha | Rendah |
| Aset & Penyusutan | Usaha dengan peralatan | Aset, penyusutan | Nilai buku aset | — | Paket Usaha | Rendah |
| Laporan SAK EMKM | UMKM yang mengajukan kredit | Tutup buku, jurnal penyesuaian | Status tutup buku | Laporan posisi keuangan dan laba rugi PDF | Paket Usaha | Tinggi |
| Izin & Kepatuhan Usaha | Kuliner, produsen | Dokumen (NIB, PIRT, halal), masa berlaku | Dokumen akan kedaluwarsa | Pengingat | Gratis sebagai pemikat | Rendah |
| Kos & Sewa | Pemilik kos dan kontrakan | Unit, penyewa, tagihan sewa, deposit | Tunggakan sewa; Kamar kosong | Pengingat ke penyewa via tautan | Paket Usaha | Sedang |
| Kas Komunitas | Pengurus RT/RW, masjid, arisan kantor | Anggota, iuran, laporan publik | Tunggakan iuran; Saldo kas | Tautan laporan baca-saja untuk warga, tanpa nama penyetor kecuali disetujui (UU PDP) | Paket Usaha | Sedang |

### B. Rumah tangga dan pribadi

| Plugin | Untuk siapa | Entitas baru | Kartu Beranda | Bot dan permukaan lain | Harga | Kompleksitas |
| --- | --- | --- | --- | --- | --- | --- |
| Pikir-Pikir | Semua user | `wishlist_items`, `transaction_reflections` | Sepadan?; Incaran siap diputuskan; Uang Selamat | `/incaran`, "cek 450k hiburan" | Inti ruang keluarga, gratis | Sedang, desain sudah ada |
| Utang & Cicilan | Rumah tangga dengan utang, termasuk paylater | Utang, jadwal cicilan | Total utang; Tanggal bebas utang | Pengingat cicilan; strategi bola salju | Pro | Rendah |
| Arisan | Keluarga, kantor, komunitas | Grup, anggota, putaran, setoran | Setoran berikutnya; Giliran dapat | Pengingat setoran; `/arisan` menampilkan jadwal | Pro | Rendah |
| Zakat, Infak & Donasi | Keluarga | Profil kewajiban, donasi rutin | Estimasi zakat; Donasi tahun ini | Kalkulator dan pengingat; bisa untuk perpuluhan atau dana punia | Pro | Rendah, isi perlu divalidasi ahli |
| Uang Saku Anak | Orang tua | Profil anak, jatah, tabungan anak | Sisa jatah anak | — | Pro | Sedang, data anak |
| Tujuan Besar & Proyeksi | Keluarga muda | Skenario proyeksi | Proyeksi DP rumah, pendidikan, haji | — | Pro | Rendah |
| Portofolio Investasi | Investor ritel | Aset investasi, nilai | Nilai portofolio; Alokasi aset | Harga dari API (izin `network:`) | Pro | Sedang |
| Asuransi & Proteksi | Keluarga | Polis, premi | Premi bulan ini | Pengingat jatuh tempo | Gratis | Rendah |
| Kendaraan & Rumah | Pemilik kendaraan atau rumah | Aset, jadwal pajak dan servis | Jatuh tempo berikutnya | Pengingat STNK, servis, PBB | Gratis | Rendah |
| Acara & Musim | Keluarga | Acara, anggaran acara | Anggaran acara vs realisasi | Templat Lebaran/THR, mudik, tahun ajaran, nikah | Pro | Rendah |
| Patungan & Split Bill | Anak muda, penghuni kos | Patungan, peserta | Piutang teman | Pengingat dan tautan tagihan untuk teman; dicatat di aplikasi | Gratis | Rendah |
| SPT Tahunan Pribadi | Karyawan, freelancer | Daftar harta dan utang | Daftar periksa SPT | Rekap untuk Coretax | Pro | Sedang |

Catatan 31 Okt 2026: Pikir-Pikir masuk sistem inti ruang keluarga (keputusan nomor 4), jadi `/incaran` dan "cek 450k hiburan" tetap jalan lewat chat. Plugin lain di tabel ini tetap Fitur Tambahan: di chat hanya pengingat dan perintah untuk melihat seperti `/arisan`, sedangkan mencatat dilakukan di aplikasi.

### C. Horizontal (semua jenis ruang)

| Plugin | Fungsi | Harga | Kompleksitas |
| --- | --- | --- | --- |
| Akses Akuntan | Mengundang akuntan atau konsultan pajak dengan akses baca-saja ke ruang usaha; sekaligus saluran pertumbuhan lewat mitra | Gratis | Sedang (peran baru) |
| Pengingat WhatsApp | Pengingat faktur, sewa, atau arisan lewat WhatsApp Business API | Tambahan per pesan | Sedang |
| Sinkron Spreadsheet | Ekspor terjadwal ke Google Sheets atau Excel | Pro | Sedang |
| Aturan Otomatis | Kategorisasi otomatis dan alokasi berulang yang selalu bisa dibatalkan | Pro | Sedang |
| Multi-mata Uang | Transaksi valas dengan kurs harian | Pro | Sedang |
| Laporan Kustom | Penyusun laporan bebas | Pro | Tinggi |
| Sinkron Rekening Otomatis | Lewat agregator open banking | Tambahan | Tinggi (regulasi dan biaya) |

### D. Paket vertikal

| Paket | Isi | Cocok untuk | Paling cepat |
| --- | --- | --- | --- |
| Paket Warung | Buku Usaha, Stok, Pajak UMKM; Kasir Ringan menyusul bila tidak lagi ditunda | Warung, toko kelontong | Gelombang 3 (menunggu Stok) |
| Paket Kuliner | Buku Usaha, Resep & HPP, Stok, Izin & Kepatuhan, Pajak UMKM | Kuliner, katering, kafe; relevan karena makanan dan minuman UMK wajib bersertifikat halal mulai 18 Okt 2026 ([BPJPH](https://bpjph.halal.go.id/read/bpjph-17-oktober-2026-produk-makanan-minuman-umk-harus-sudah-bersertifikat-halal-bagaimana-dengan-produk-luar-negeri), [Headline](https://www.headline.co.id/149006/wajib-halal-tetap-18-oktober-2026-bpjph-siapkan-aturan-umk/)) | Gelombang 3 |
| Paket Jasa | Buku Usaha, Faktur & Piutang, Pajak UMKM; Proyek & Cabang menyusul | Freelancer, agensi, bengkel | Gelombang 1 (tanpa Proyek) |
| Paket Toko Online | Buku Usaha, Penjualan Marketplace, Stok, Pajak UMKM | Seller marketplace | Gelombang 3 |
| Paket Kos & Sewa | Kos & Sewa, Buku Usaha, Pajak UMKM | Pemilik kos dan kontrakan | Gelombang 2 |
| Paket Komunitas | Kas Komunitas dengan laporan transparan | Pengurus komunitas | Belum dijadwalkan |

### Rincian tiga plugin unggulan

**1. Buku Usaha: amplop untuk uang usaha.** Inti idenya adalah alokasi omzet: setiap pemasukan penjualan otomatis dibagi ke amplop Pajak, Prive, Laba Ditahan, Operasional, dan Bahan, mirip metode Profit First. Fitur Alokasi yang sudah ada di Jatahku tinggal diberi aturan persentase.

- Jenis pemasukan (penjualan, modal pemilik, pinjaman, lain-lain) di setiap pemasukan ruang usaha; hanya penjualan yang dihitung sebagai omzet.
- Kas usaha dan laba rugi sederhana per bulan. Prive, modal, pinjaman, dan transfer tidak dihitung sebagai pendapatan atau beban.
- Prive sebagai transfer antar-ruang ke ruang rumah tangga.
- Kontak pelanggan dan pemasok yang bisa dipilih di form transaksi dan pemasukan.
- Aturan advisor: BU-01 kas usaha kurang dari kebutuhan dua minggu, BU-02 prive melebihi laba, BU-03 amplop Pajak belum terisi.
- Laporan bulanan PDF dan CSV untuk bank atau akuntan.

**2. Pajak UMKM: PPh final tanpa pusing.** Aturannya mengikuti PP 20/2026 dan PMK 81/2024 per Oktober 2026:

- **Tarif:** PPh final 0,5% dari omzet bruto setiap bulan, dihitung dari pemasukan berjenis penjualan.
- **Yang berhak:** OP, PT perorangan, dan koperasi dengan omzet ≤ Rp4,8 miliar setahun. OP dan PT perorangan tidak lagi punya batas waktu; koperasi maksimal 4 tahun; CV, firma, dan PT biasa yang terdaftar sebelum PP berlaku melanjutkan sampai jangka waktunya habis ([BPK](https://peraturan.bpk.go.id/Details/349415/pp-no-20-tahun-2026), [DDTC](https://news.ddtc.co.id/berita/nasional/1820074/memahami-pph-final-umkm-pasca-terbit-pp-202026)).
- **Ambang OP:** omzet sampai Rp500 juta setahun tidak dikenai pajak, jadi OP baru menyetor setelah omzet kumulatif melewati angka itu ([DDTC](https://news.ddtc.co.id/berita/nasional/1819941/aturan-pph-final-direvisi-omzet-rp500-juta-bebas-pajak-tetap-berlaku)).
- **Tenggat:** setor paling lambat tanggal 15 bulan berikutnya; setoran mandiri dianggap sudah lapor sehingga SPT Masa tidak perlu, sedangkan SPT Tahunan tetap wajib lewat Coretax ([Ortax](https://ortax.org/jatuh-tempo-pembayaran-pajak-masa-menurut-pmk-81-2024), [DDTC](https://news.ddtc.co.id/berita/nasional/1811337/pph-final-umkm-05-disetor-per-masa-pajak-kode-billing-lewat-coretax)).
- **Contoh hitung:** OP dengan omzet kumulatif Januari–Oktober Rp420 juta dan omzet November Rp100 juta. Bagian kena pajak di November adalah Rp20 juta, sehingga PPh final November 0,5% × Rp20 juta = Rp100.000, disetor paling lambat Selasa, 15 Desember 2026.
- **Parameter sebagai data.** Tarif, ambang, dan tenggat disimpan sebagai tabel berlaku-sejak, bukan di kode. Menteri Keuangan membuka opsi mengubah ambang Rp500 juta ([IKPI](https://ikpi.or.id/articles/purbaya-buka-opsi-ubah-batas-omzet-umkm-bebas-pph)), dan Bank Dunia mengusulkan batas PKP turun ke Rp500 juta ([DDTC](https://news.ddtc.co.id/berita/nasional/1821299/world-bank-usulkan-threshold-pkp-turun-ke-rp500-juta)); keduanya belum diputuskan.
- **Batas tanggung jawab.** Setiap angka diberi label "perkiraan" dan ajakan memeriksa dengan konsultan pajak. Plugin tidak membuat kode billing atau melapor atas nama user.

**3. Faktur & Piutang: uang yang belum masuk terlihat.** User membuat faktur di web atau aplikasi, lalu membagikan PDF atau tautannya lewat WhatsApp dari HP sendiri tanpa API berbayar. Pelunasan, termasuk cicilan sebagian, dicatat sebagai pemasukan inti yang merujuk faktur, sehingga amplop dan laporan tetap satu sumber. Kartu Umur piutang membagi tagihan ke kelompok 0–30, 31–60, dan lebih dari 60 hari. Aturan advisor: FK-01 piutang lewat jatuh tempo, FK-02 lebih dari separuh piutang ada di satu pelanggan.

### Yang sebaiknya tidak dibuat sekarang

- **Kasir penuh dengan perangkat keras.** Pasar sudah dikuasai pemain seperti Majoo dan Moka.
- **e-Faktur PPN untuk PKP dan integrasi langsung Coretax.** Rumit dan sensitif; lebih cocok untuk mitra di tingkat T2.
- **Simpan pinjam koperasi dan rujukan pinjaman atau KUR.** Butuh kajian regulasi tersendiri.
- **Payroll lengkap untuk puluhan karyawan.** Mulai dari kasbon dan slip sederhana; hitungan PPh 21 TER dan BPJS menyusul setelah ada permintaan nyata.
- **Jual-beli aset investasi.** Plugin Portofolio hanya mencatat dan menilai, tidak bertransaksi.

## Prioritas dan roadmap bertahap

Urutannya fondasi dulu, plugin kemudian: Beranda berbasis registry, lalu Mode Atur, lalu host plugin dengan satu modul pilot ringan, lalu ruang usaha dengan Paket Usaha v1. Sejak 31 Okt urutannya diganti: Beranda registry dan ruang usaha lebih dulu, lalu host plugin dengan Buku Usaha sebagai plugin pertama, sedangkan Mode Atur menyusul paralel. Rinciannya ada di Rencana Development Plugin Buku Usaha. Perkiraannya, beta Paket Usaha berjalan di minggu ke-16–23 dan P4 lulus gerbangnya di minggu ke-20–27, bila 1–2 developer mengerjakannya penuh dengan sesi Claude Code paralel.

&#91;embedded content: prioritas 20 kandidat plugin · dampak × upaya, warna = gelombang\]

Dampak berarti nilai bagi user ditambah potensi pendapatan berulang. Plugin yang memakai kekuatan Jatahku (amplop, alokasi, bot, struk) berada di baris atas dengan upaya sedang, sehingga dikerjakan lebih dulu.

### Gelombang plugin

1. **Gelombang 1, bersama P3–P4:** Buku Usaha sebagai plugin pertama, lalu Pajak UMKM dan Faktur & Piutang untuk melengkapi Paket Usaha v1.
2. **Gelombang 2:** Akses Akuntan, Utang & Cicilan, Arisan, Izin & Kepatuhan, Tagihan Pemasok, Kos & Sewa.
3. **Gelombang 3:** Stok & Persediaan, Resep & HPP, Gaji Karyawan & Kasbon, Laporan SAK EMKM, Rekonsiliasi Mutasi, Penjualan Marketplace.
4. **Ditunda dan dinilai ulang tiap tahun:** Kasir Ringan, Multi-mata Uang, Laporan Kustom, Sinkron Rekening Otomatis.
5. **Kandidat lain di katalog,** misalnya Proyek & Cabang, Reimburse, Pinjaman Usaha, dan Kas Komunitas, dinilai ulang setelah Gelombang 2 berdasarkan permintaan UMKM beta.

&#91;embedded content: roadmap P0–P5 · fase berurutan, tiap fase punya gerbang keluar\]

Total P0 sampai P4 adalah 20 minggu bila setiap fase memakai batas bawah perkiraannya, dan 27 minggu bila memakai batas atas. Beta 4 minggu dengan 10 UMKM berjalan di akhir P4.

### Paket kerja per fase

| Fase | Paket kerja utama | Gerbang keluar | Perkiraan |
| --- | --- | --- | --- |
| P0 Keputusan dan persiapan | Keputusan pemilik produk (bagian terakhir kajian); folder `docs/plugin/` berisi indeks, kajian, ADR, workflow, `PROGRESS.md`, `SESI-LOG.md`; mockup Mode Atur dan galeri kartu di canvas Design | Keputusan tercatat sebagai ADR | 1–2 minggu |
| P1 Beranda berbasis registry | Registry kartu, penyedia data, `POST /dashboard/data`, tabel `dashboard_layouts`; tampilan Beranda tetap sama persis, termasuk rasio 1,65 : 1 | Paritas angka dan tampilan untuk semua user; batch p95 ≤ 500 ms | 3–4 minggu |
| P2 Mode Atur | Sembunyikan, geser, ukuran S–XL, galeri, template, reset, Naik/Turun, keyboard, getar di aplikasi | Uji keyboard dan pembaca layar lulus; uji di HP Android kelas bawah; tes tata letak lintas perangkat lulus; flag menjadi `*` | 3–4 minggu |
| P3 Host plugin + kerangka Buku Usaha | Manifest, registry, `plugin_installations`, `entitlements`, `PluginContext`, outbox dan `event_deliveries`, titik ekstensi, validator CI, PostgreSQL di CI; kerangka Buku Usaha dibangun sebagai Fitur Tambahan pertama, setelah ruang usaha ada | Buku Usaha bisa dijeda dan dicopot bersih; tes isolasi lulus | 5–7 minggu |
| P4 Ruang usaha + Paket Usaha v1 | Resolver `ruang_aktif` di 86 titik; ruang dari objek saat menulis; pemilih ruang di web dan aplikasi (chat tetap ruang keluarga); kuota per ruang; `incomes.kind` dan prive; peran dan batasan anggota ruang usaha; Catat cepat dengan deteksi di ruang usaha; Buku Usaha, Pajak UMKM, Faktur & Piutang; payment gateway berulang | Paritas user lama 100%; nol kebocoran antar-ruang; 10 UMKM beta aktif selama 4 minggu | 8–10 minggu |
| P5 Perluasan | Gelombang 2 dan 3; jualan plugin di Play dan App Store mengikuti fase billing mobile | Gerbang uji P3 berlaku untuk setiap plugin | Berkelanjutan |

### Koordinasi dengan pekerjaan yang sedang berjalan

- **AI Advisor S10b dulu.** Flag `advisor_v2_users` sudah `*` sejak 17 Okt. S10b menghapus jalur lama, sehingga P1 hanya memigrasi satu varian Beranda, bukan dua (`AdvisorCard` dan `AttentionCard`).
- **Mobile berjalan paralel, tetapi berbagi file.** Paket mobile 1.10 (pemeriksaan tablet) juga menyentuh `Dashboard.jsx` dan `Layout.jsx`. Jadwalkan 1.10 sebelum P1 dimulai atau sesudah P2 selesai, bagi kepemilikan file per sesi seperti di `docs/ai-advisor/03-workflow.md`, dan pastikan semua perubahan API tetap aditif.
- **Kapasitas.** Perkiraan minggu di atas mengandaikan developernya tidak sedang mengerjakan rencana mobile. Bila developer yang sama mengerjakan keduanya, jadwal P1–P4 mundur sebesar porsi kerja mobile.
- **Pikir-Pikir tidak menunggu host plugin.** Sejak keputusan 31 Okt seluruh Pikir-Pikir masuk inti ruang keluarga. Fase 1 mengubah aturan catat (`expense_rules`); Fase 2–3 (Sepadan?, Incaran, Uang Selamat, perintah bot) dibangun di inti dan bisa berjalan paralel dengan P1–P3. Aturan PP-01 sampai PP-03 sudah menunggu di `rules/pikir.py`.

## Risiko dan mitigasi

Risiko terbesar bukan teknis, melainkan membangun platform terlalu besar untuk ±95 user, dan refactor ruang yang diam-diam mengubah angka user lama. Keduanya dijaga dengan gerbang per fase dan tes paritas.

| Risiko | Dampak | Kemungkinan | Mitigasi |
| --- | --- | --- | --- |
| Platform terlalu dini untuk skala sekarang | Tinggi | Tinggi | Berhenti di T1; setiap fase punya gerbang keluar; marketplace hanya bila ada mitra nyata |
| Refactor ruang mengubah angka user lama (86 titik) | Tinggi | Sedang | Satu PR fondasi; resolver tunggal; tes paritas untuk semua user; flag per user sebelum `*` |
| Omzet, laba, dan pajak salah hitung karena transfer, top-up, penyesuaian, dan prive ikut terhitung | Tinggi | Sedang | `incomes.kind` dan jenis pemasukan; omzet hanya dari penjualan; prive di luar laba; tes angka laporan dengan data contoh |
| Plugin merusak ledger | Tinggi | Rendah | Plugin hanya mendapat action dan pemeriksaan berisi peringatan; tulis lewat `expense_rules`; idempotensi dan audit log |
| Data bocor antar-ruang atau antar-anggota | Tinggi | Rendah | `ruang_aktif` tunggal; ruang dari objek saat menulis; payload event hanya ID; tes isolasi; `visibility.py` di dalam SDK; Row Level Security di T2 |
| Menyimpan tata letak dari satu perangkat menghapus kartu perangkat lain | Sedang | Sedang | Dokumen lengkap dengan `visible`; server menolak `PUT` yang kehilangan instans; tes lintas perangkat |
| Beranda melambat seiring bertambahnya kartu | Sedang | Sedang | Endpoint batch; snapshot sekali per permintaan; anggaran waktu per penyedia di CI; komponen lazy |
| Tampilan kartu plugin tidak seragam | Sedang | Sedang | Bentuk data deklaratif yang digambar komponen inti; review desain per plugin |
| Aturan pajak berubah | Tinggi | Tinggi | Parameter sebagai tabel berlaku-sejak; label "perkiraan"; tinjauan regulasi bulanan; batas tanggung jawab yang jelas |
| Penolakan review toko (2.5.2, 2.5.19, 3.1.1, 3.1.3(b)) | Sedang | Sedang | Kode plugin di bundle; plugin baru hanya lewat rilis toko; katalog terlihat; catatan review dan akun demo; plugin berbayar disembunyikan di iOS sampai IAP ada |
| Sesi paralel saling menimpa | Sedang | Sedang | Satu sesi satu PR; kepemilikan file; validator manifest di CI; paket mobile 1.10 dijadwalkan di luar P1–P2 |
| Kapasitas VPS 4 GB dengan satu worker | Sedang | Sedang | Pekerjaan berat di worker latar; pemantauan memori; rencana naik kelas server |
| User rumah tangga bingung oleh fitur usaha | Sedang | Sedang | Plugin usaha hanya di ruang usaha; template Beranda per persona; bawaan tetap rapi |
| Beban dukungan pertanyaan pajak dan akuntansi | Sedang | Tinggi | FAQ dalam aplikasi; plugin Akses Akuntan; kemitraan dengan kantor akuntan |
| UMKM enggan membayar | Tinggi | Sedang | Uji harga pada 10 UMKM beta; uji coba 14 hari; bundel vertikal; nilai yang jelas (pajak dan pemisahan uang) |
| Pustaka drag and drop pra-1.0 berubah | Rendah | Sedang | Adapter `src/lib/dnd/`; versi dikunci; tombol Naik/Turun tetap berfungsi tanpa pustaka |
| Data anak dan karyawan (data spesifik UU PDP) | Tinggi | Rendah | Penilaian dampak wajib; minimalisasi; enkripsi kolom sensitif; masa simpan tertulis |

## Metrik keberhasilan

Keberhasilan diukur di tiga tingkat: apakah user benar-benar mengatur Berandanya, apakah plugin dipakai setelah dipasang, dan apakah Paket Usaha menghasilkan pendapatan berulang. Semua target di bawah adalah usulan awal yang dikalibrasi ulang setelah 60 hari data.

| Area | Metrik | Definisi | Target usulan |
| --- | --- | --- | --- |
| Dashboard | Pemakaian Mode Atur | User aktif yang menyimpan minimal satu perubahan tata letak dalam 60 hari | ≥ 30% |
| Dashboard | Kartu bermasalah | Kartu yang menampilkan error dibagi total kartu yang dirender | < 0,5% |
| Dashboard | Kecepatan | p95 `POST /dashboard/data` di server | ≤ 500 ms |
| Dashboard | Aksesibilitas | Temuan kritis pada uji keyboard dan pembaca layar | 0 |
| Plugin | Adopsi | Ruang aktif yang memasang minimal satu plugin | ≥ 25% dalam 90 hari |
| Plugin | Aktivasi | Plugin terpasang yang dipakai minimal 3 hari dalam 14 hari pertama | ≥ 60% |
| Plugin | Copot dini | Plugin yang dicopot dalam 30 hari | < 10% |
| Plugin | Dampak retensi | Retensi 8 minggu ruang dengan plugin dibanding tanpa plugin | Lebih tinggi, selisih dipantau |
| Paket Usaha | Beta | UMKM beta yang aktif mencatat 4 minggu berturut-turut | ≥ 10 |
| Paket Usaha | Konversi | Uji coba yang menjadi berbayar | ≥ 20% |
| Paket Usaha | Churn | Ruang usaha yang berhenti berlangganan per bulan | < 5% |
| Kualitas | Paritas | Selisih angka inti sebelum dan sesudah refactor ruang | 0 |
| Kualitas | Kebocoran | Kejadian data terbaca lintas ruang atau lintas anggota | 0 |
| Kualitas | Saklar darurat | Waktu dari keputusan mematikan plugin sampai plugin hilang di semua permukaan | ≤ 15 menit |

Pengukuran memakai hitungan agregat (berapa kali, berapa ruang), tanpa isi transaksi, sejalan dengan prinsip minimalisasi data.

## Keputusan untuk pemilik produk

Tujuh belas keputusan menentukan arah pekerjaan, dan dua yang pertama dibutuhkan sebelum P1 dimulai karena memengaruhi kunci tabel tata letak. Kolom Status bisa langsung diubah di dokumen ini.

| No | Keputusan | Pilihan | Rekomendasi | Dibutuhkan sebelum | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Model tata letak Beranda | Urutan + ukuran; grid bebas x-y | Urutan + ukuran | P1 | Setuju |
| 2 | Cara memisahkan uang usaha | Ruang usaha sebagai household kedua; grup amplop; akun kedua | Ruang usaha sebagai household kedua | P1 (kunci tabel) dan P4 | Setuju |
| 3 | Tingkat plugin 12 bulan ke depan | T1 saja; buka T2 | T1 saja | P3 | Setuju |
| 4 | Posisi Pikir-Pikir | Fase 2–3 sebagai modul pilot, Fase 1 di inti; semuanya di inti | Fase 2–3 sebagai modul pilot, Fase 1 di inti. Keputusan 31 Okt: semuanya di inti agar fitur chatnya tetap jalan (keputusan 14); Buku Usaha menjadi plugin pertama sebagai ganti pilot P3 | Pikir-Pikir Fase 2 | Setuju dengan perubahan |
| 5 | Istilah di UI | Plugin; Fitur Tambahan; Modul | "Fitur Tambahan" di UI, "plugin" di kode dan dokumen | P2 | Setuju |
| 6 | Siapa yang memasang plugin | Pemilik dan admin; semua anggota | Pemilik dan admin; plugin cakupan pribadi boleh dipasang anggota. Disetujui 31 Okt untuk bagian pemilik dan admin; cakupan pribadi diputuskan saat ada plugin pertamanya | P3 | Setuju dengan perubahan |
| 7 | Beranda bawaan dari pemilik household | Ya; tidak | Ya | P2 | Belum diputuskan |
| 8 | Model dan harga Paket Usaha | Langganan per ruang; sekali bayar; ikut Pro | Langganan per ruang, hipotesis Rp25.000–Rp50.000 per bulan. Disetujui 31 Okt: per ruang; tingkat menurut jumlah anggota dinilai dari data beta | Beta P4 | Setuju dengan perubahan |
| 9 | Payment gateway untuk tagihan berulang | Pilih penyedia | Penyedia dengan QRIS, virtual account, dan tagihan berulang | P4 | Belum diputuskan |
| 10 | Kuota Basic di ruang usaha | Berlaku; tidak berlaku | Tidak berlaku; ruang usaha mensyaratkan Paket Usaha | P4 | Setuju |
| 11 | Harga plugin di toko aplikasi | Sama dengan web; dinaikkan untuk menutup komisi | Diputuskan bersama harga Pro di toko | Jualan P5 | Belum diputuskan |
| 12 | Plugin yang memakai LLM pihak ketiga | Dilarang; boleh dengan persetujuan terpisah | Dilarang di T1, konsisten dengan keputusan AI Advisor | P3 | Setuju |
| 13 | Masa arsip setelah plugin dicopot | 30, 90, atau 180 hari | 90 hari | P3 | Setuju |
| 14 | Transaksi lewat chat (Telegram dan chat web) | Chat untuk semua ruang lewat `/ruang`; chat hanya ruang keluarga | Chat hanya ruang keluarga; Fitur Tambahan hanya laporan dan notifikasi | P4 | Setuju |
| 15 | Penerima laporan usaha di chat, mis. `/laba` | Semua anggota ruang; admin saja | Admin saja | P4 | Setuju |
| 16 | Anggota ruang usaha | Pemilik saja; banyak anggota dengan peran | Banyak anggota dengan peran dan batasan dari admin; tiap anggota tetap punya ruang keluarga sendiri | P4 | Setuju |
| 17 | Pencatatan di ruang usaha | Form biasa; deteksi dan belajar seperti di chat | Deteksi dan belajar seperti di chat | P4 | Setuju |

Setelah keputusan diambil, hasilnya dicatat sebagai ADR di `docs/plugin/02-adr.md`, mengikuti pola `docs/mobile/02-adr.md`.

## Lampiran teknis

Lampiran ini memberi titik awal konkret untuk P1 dan P3: struktur folder, skema tabel platform, kontrak kartu, penyedia data, SDK plugin, dan bentuk event. Semua nama bisa disesuaikan saat ADR ditulis.

### Struktur folder

```text
app/plugins/
  sdk/                  # PluginContext, dekorator, bentuk kartu deklaratif
  host/                 # registry manifest, instalasi, izin, outbox, dispatcher
  buku_usaha/           # plugin pertama: Buku Usaha
    manifest.json
    models.py  metrics.py  rules.py  render.py
    cards.py  events.py  jobs.py  bot.py
    tests/
alembic/versions/       # migrasi plugin ikut riwayat utama, satu jalur
frontend/src/
  cards/core/           # definisi kartu bawaan
  plugins/buku_usaha/   # halaman dan kartu kustom (lazy)
  lib/dnd/              # adapter drag and drop
docs/plugin/            # 00-indeks, 01-kajian, 02-adr, 03-workflow, PROGRESS, SESI-LOG
```

### Skema tabel platform (PostgreSQL)

```sql
CREATE TABLE dashboard_layouts (
  id              UUID PRIMARY KEY,
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  household_id    UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  surface         VARCHAR(30) NOT NULL DEFAULT 'beranda',
  schema_version  INTEGER NOT NULL DEFAULT 1,
  items           JSONB NOT NULL DEFAULT '[]',
  parked          JSONB NOT NULL DEFAULT '[]',
  version         INTEGER NOT NULL DEFAULT 1,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, household_id, surface)
);

CREATE TABLE dashboard_defaults (            -- Beranda bawaan dari pemilik household
  household_id  UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  surface       VARCHAR(30) NOT NULL DEFAULT 'beranda',
  items         JSONB NOT NULL DEFAULT '[]',
  updated_by    UUID REFERENCES users(id) ON DELETE SET NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (household_id, surface)
);

CREATE TABLE plugin_installations (
  id                  UUID PRIMARY KEY,
  household_id        UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  plugin_id           VARCHAR(50) NOT NULL,
  owner_id            UUID REFERENCES users(id) ON DELETE CASCADE,   -- terisi hanya untuk cakupan pribadi
  status              VARCHAR(20) NOT NULL,   -- installed | active | paused | uninstalled
  installed_by        UUID REFERENCES users(id) ON DELETE SET NULL,
  granted_permissions JSONB NOT NULL DEFAULT '[]',
  settings            JSONB NOT NULL DEFAULT '{}',
  data_version        INTEGER NOT NULL DEFAULT 0,
  disabled_reason     VARCHAR(50),
  installed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  uninstalled_at      TIMESTAMPTZ,
  UNIQUE NULLS NOT DISTINCT (household_id, plugin_id, owner_id)   -- PostgreSQL 15+
);
-- Saklar darurat tidak di sini: daftar plugin yang dimatikan disimpan di AppSetting.

CREATE TABLE entitlements (
  id            UUID PRIMARY KEY,
  user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
  household_id  UUID REFERENCES households(id) ON DELETE CASCADE,
  sku           VARCHAR(60) NOT NULL,   -- pro | plugin.buku_usaha | bundle.usaha
  source        VARCHAR(20) NOT NULL,   -- transfer | promo | play | appstore | gateway
  status        VARCHAR(20) NOT NULL,   -- active | grace | expired | refunded
  starts_at     TIMESTAMPTZ NOT NULL,
  ends_at       TIMESTAMPTZ,            -- NULL = tanpa batas (Pro sekali bayar)
  external_ref  VARCHAR(200),           -- id pembelian toko atau gateway
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (user_id IS NOT NULL OR household_id IS NOT NULL),
  UNIQUE (source, external_ref)         -- struk toko yang dikirim ulang tidak membuat hak ganda
);

CREATE TABLE event_outbox (
  id              UUID PRIMARY KEY,      -- = event_id
  seq             BIGSERIAL UNIQUE,      -- urutan event
  type            VARCHAR(60) NOT NULL,
  schema_version  INTEGER NOT NULL DEFAULT 1,
  household_id    UUID NOT NULL,
  actor_user_id   UUID,
  payload         JSONB NOT NULL,        -- hanya ID, tanpa nominal atau deskripsi
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE event_deliveries (         -- ditulis bersama event, satu baris per plugin pendengar
  event_id         UUID NOT NULL REFERENCES event_outbox(id) ON DELETE CASCADE,
  plugin_id        VARCHAR(50) NOT NULL,
  status           VARCHAR(20) NOT NULL DEFAULT 'pending',   -- pending | done | dead
  attempts         INTEGER NOT NULL DEFAULT 0,
  next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error       TEXT,
  PRIMARY KEY (event_id, plugin_id)
);
CREATE INDEX ix_deliveries_due ON event_deliveries (next_attempt_at) WHERE status = 'pending';
-- Worker: SELECT ... WHERE status = 'pending' AND next_attempt_at <= now()
--         ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 50;
-- Pendengar dan UPDATE status = 'done' berjalan dalam satu transaksi database.

CREATE TABLE plugin_audit_log (
  id             BIGSERIAL PRIMARY KEY,
  household_id   UUID NOT NULL,
  plugin_id      VARCHAR(50) NOT NULL,
  actor_user_id  UUID,
  action         VARCHAR(60) NOT NULL,   -- install | grant | pause | uninstall | write:transactions
  detail         JSONB,
  at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Ubuntu 24.04 membawa PostgreSQL 16, jadi `UNIQUE NULLS NOT DISTINCT` tersedia; versi server tetap perlu dicek sebelum migrasi. Di model SQLAlchemy, kolom JSONB ditulis `JSON().with_variant(JSONB(), "postgresql")` karena tes integrasi berjalan di SQLite. Nama kolom di database tetap `household_id`; `ruang_id` hanya nama di API dan SDK.

### Kontrak kartu di frontend

```js
// src/cards/core/kpiJatah.js
registerCard({
  key: 'core.kpi.jatah',
  title: 'Jatah hari ini',
  description: 'Belanja hari ini dibanding jatah aman.',
  source: 'core',
  sizes: ['S', 'M'],
  defaultSize: 'S',
  supportsPeriod: true,
  multiInstance: false,
  shape: 'kpi',            // digambar KpiTile dari payload server
  refreshOn: ['jatahku:txn-added', 'jatahku:envelope-updated'],
  component: null,         // null = renderer bentuk deklaratif
});

// Kartu kustom plugin buatan sendiri:
// component: lazy(() => import('../../plugins/buku_usaha/ArusKasCard.jsx'))
```

### Penyedia data di backend

```python
# app/plugins/buku_usaha/cards.py
from app.plugins.sdk import card_provider, PluginContext, Kpi

@card_provider("buku_usaha.laba_rugi", permissions=["transactions:read", "incomes:read"])
async def laba_rugi(ctx: PluginContext, instance: dict, period) -> Kpi:
    m = await ctx.metrics("buku_usaha", period)        # satu sumber angka plugin
    return Kpi(
        value=m.laba,
        suffix="bulan ini",
        tone="danger" if m.laba < 0 else "ok",
        footer=ctx.render("laba_rugi.footer", m),       # teks dari templat plugin
    )
```

### SDK plugin

```python
class PluginContext(Protocol):
    ruang_id: UUID                                       # = household_id di database
    user_id: UUID
    plugin_id: str
    client: ClientInfo                                   # dari header X-Jatahku-Client

    async def envelopes(self) -> list[EnvelopeView]: ...                      # envelopes:read
    async def transactions(self, period, **flt) -> list[TxnView]: ...         # transactions:read, lewat visibility.py
    async def income(self, income_id: UUID) -> IncomeView: ...                # incomes:read
    async def record_expense(self, req: ExpenseRequest) -> RecordResult: ...  # transactions:write, lewat expense_rules
    async def record_income(self, req: IncomeRequest) -> RecordResult: ...    # incomes:write
    async def propose_fund_move(self, plan: FundPlan) -> PlanRef: ...         # funds:move, dikonfirmasi user
    async def notify(self, kind: str, data: dict) -> None: ...                # notifications:send, lewat penyaring jam tenang
    async def settings(self) -> dict: ...
    async def metrics(self, name: str, period) -> Any: ...
    def render(self, template: str, data) -> str: ...
```

### Bentuk event

```json
{
  "event_id": "5b1f…",
  "type": "income.recorded",
  "schema_version": 1,
  "ruang_id": "c0a8…",
  "actor_user_id": "9e2d…",
  "occurred_at": "2026-10-18T09:12:44+07:00",
  "data": {"income_id": "77aa…", "source": "telegram"}
}
```

Payload hanya berisi ID. Pendengar membaca nominal dan deskripsi lewat `PluginContext`, sehingga izin dan `visibility.py` tetap berlaku; nominal dari SDK berupa string desimal, bukan float, supaya tidak ada pembulatan diam-diam.

## Sumber

Fakta kode diambil dari repo `mtyatno/jatahku` (main `56e2a23`), fakta luar dari halaman yang dibuka pada 17–19 Okt 2026.

**Dokumen internal**

- [AGENTS.md](https://github.com/mtyatno/jatahku/blob/main/AGENTS.md), [CLAUDE.md](https://github.com/mtyatno/jatahku/blob/main/CLAUDE.md), [README.md](https://github.com/mtyatno/jatahku/blob/main/README.md)
- [Dashboard.jsx](https://github.com/mtyatno/jatahku/blob/main/frontend/src/pages/Dashboard.jsx), [models.py](https://github.com/mtyatno/jatahku/blob/main/app/models/models.py), [app\_config.py](https://github.com/mtyatno/jatahku/blob/main/app/services/app_config.py), [plan\_limits.py](https://github.com/mtyatno/jatahku/blob/main/app/services/plan_limits.py), [fund\_shift.py](https://github.com/mtyatno/jatahku/blob/main/app/services/fund_shift.py), [idempotency.py](https://github.com/mtyatno/jatahku/blob/main/app/services/idempotency.py), [notification\_service.py](https://github.com/mtyatno/jatahku/blob/main/app/services/notification_service.py), [intent\_learning.py](https://github.com/mtyatno/jatahku/blob/main/app/bot/intent_learning.py), [rules/pikir.py](https://github.com/mtyatno/jatahku/blob/main/app/services/advisor/rules/pikir.py), [test.yml](https://github.com/mtyatno/jatahku/blob/main/.github/workflows/test.yml)
- [Kajian mobile](https://github.com/mtyatno/jatahku/blob/main/docs/mobile/01-kajian.md), [ADR mobile](https://github.com/mtyatno/jatahku/blob/main/docs/mobile/02-adr.md), [indeks AI Advisor](https://github.com/mtyatno/jatahku/blob/main/docs/ai-advisor/00-indeks.md), [verifikasi rilis AI Advisor](https://github.com/mtyatno/jatahku/blob/main/docs/ai-advisor/05-verifikasi-rilis.md)
- Dokumen project claude.ai: `dashboard-amplop-tab.md`, `paritas-web-telegram.md`, `pikir-pikir-desain.md`

**Teknis**

- [dnd-kit (GitHub)](https://github.com/clauderic/dnd-kit), [aksesibilitas dnd-kit](https://dndkit.com/legacy/guides/accessibility), [panduan migrasi ke @dnd-kit/react](https://dndkit.com/react/guides/migration)
- [react-grid-layout CHANGELOG](https://github.com/react-grid-layout/react-grid-layout/blob/master/CHANGELOG.md), [gridstack.js CHANGES](https://github.com/gridstack/gridstack.js/blob/master/doc/CHANGES.md)
- [Pragmatic drag and drop](https://github.com/atlassian/pragmatic-drag-and-drop), [panduan aksesibilitasnya](https://atlassian.design/components/pragmatic-drag-and-drop/accessibility-guidelines/)
- [SortableJS](https://github.com/SortableJS/Sortable), [react-sortablejs](https://github.com/SortableJS/react-sortablejs)
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [2.5.7 Dragging Movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html), [2.5.8 Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- [Frappe apps](https://docs.frappe.io/framework/user/en/basics/apps), [Frappe DocType](https://docs.frappe.io/framework/user/en/basics/doctypes), [Frappe Workspace](https://docs.frappe.io/framework/user/en/desk/navigation/workspace.md)
- [Referensi modul Odoo](https://raw.githubusercontent.com/odoo/documentation/19.0/content/developer/reference/backend/module.rst)
- [Shopify app extensions](https://shopify.dev/docs/apps/build/app-extensions), [Shopify checkout UI extensions](https://shopify.dev/docs/api/checkout-ui-extensions), [Remote rendering di Shopify](https://shopify.engineering/remote-rendering-ui-extensibility)
- [Cara plugin Figma berjalan](https://developers.figma.com/docs/plugins/how-plugins-run), [manifest Figma](https://developers.figma.com/docs/plugins/manifest)
- [VS Code contribution points](https://code.visualstudio.com/api/references/contribution-points), [VS Code activation events](https://code.visualstudio.com/api/references/activation-events)
- [Atlassian Forge](https://developer.atlassian.com/platform/forge/), [izin manifest Forge](https://developer.atlassian.com/platform/forge/manifest-reference/permissions/)
- [WordPress hooks](https://developer.wordpress.org/plugins/hooks/)
- [PostgreSQL Row Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html), [indeks JSONB](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING)

**Kebijakan toko aplikasi dan marketplace**

- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), [ringkasan pembaruan 4.7 (November 2025)](https://dev.to/arshtechpro/apples-guideline-47-update-what-every-developer-hosting-html5-mini-apps-must-know-90), [Apple Small Business Program](https://developer.apple.com/app-store/small-business-program/)
- [Google Play: Device and Network Abuse](https://support.google.com/googleplay/android-developer/answer/9888379), [user choice billing untuk developer](https://support.google.com/googleplay/android-developer/answer/13821247), [user choice billing untuk user](https://support.google.com/googleplay/answer/11174377)
- [Putusan KPPU atas Google Play Billing berkekuatan tetap](https://www.asean-competition.org/read-news-supreme-court-rejects-googles-cassation-kppu-decision-on-google-play-billing-becomes-legally-binding)
- [Bagi hasil Shopify App Store](https://shopify.dev/apps/launch/distribution/revenue-share), [FAQ harga Atlassian Marketplace](https://developer.atlassian.com/market/faqs/pricing-payment-billing)

**Regulasi Indonesia**

- [PP 20/2026 (BPK)](https://peraturan.bpk.go.id/Details/349415/pp-no-20-tahun-2026), [DDTC: PPh final UMKM setelah PP 20/2026](https://news.ddtc.co.id/berita/nasional/1820074/memahami-pph-final-umkm-pasca-terbit-pp-202026), [DDTC: omzet Rp500 juta tetap bebas](https://news.ddtc.co.id/berita/nasional/1819941/aturan-pph-final-direvisi-omzet-rp500-juta-bebas-pajak-tetap-berlaku)
- [Ortax: jatuh tempo menurut PMK 81/2024](https://ortax.org/jatuh-tempo-pembayaran-pajak-masa-menurut-pmk-81-2024), [DDTC: kode billing Coretax dan SPT Masa](https://news.ddtc.co.id/berita/nasional/1811337/pph-final-umkm-05-disetor-per-masa-pajak-kode-billing-lewat-coretax), [DDTC: imbauan pencatatan omzet](https://news.ddtc.co.id/berita/nasional/1804802/setor-pph-final-umkm-tak-perlu-lapor-spt-masa-tapi-perlu-pencatatan)
- [IKPI: opsi mengubah ambang omzet](https://ikpi.or.id/articles/purbaya-buka-opsi-ubah-batas-omzet-umkm-bebas-pph), [DDTC: usulan Bank Dunia soal batas PKP](https://news.ddtc.co.id/berita/nasional/1821299/world-bank-usulkan-threshold-pkp-turun-ke-rp500-juta)
- [PwC: PP 33/2026](https://www.pwc.com/id/en/pwc-publications/services-publications/digital-publications/government-regulation-33-2026-personal-data-protection.html), [Hukumonline: kerangka PDP berlaku 16 Jan 2027](https://pro.hukumonline.com/a/lt6a97c3fe4527c/pemerintah-akhirnya-terbitkan-kerangka-implementasi-pelindungan-data-pribadi--berlaku-mulai-16-januari-2027), [Bisnis: aturan persetujuan](https://teknologi.bisnis.com/read/20260829/84/1999753/aturan-turunan-uu-pdp-persetujuan-data-konsumen-lebih-ketat), [Bisnis: pembentukan badan PDP](https://teknologi.bisnis.com/read/20260913/84/2003698/pembentukan-badan-pdp-dipercepat-implementasi-uu-pdp-dinilai-belum-efektif)
- [UU PDP Pasal 4](https://pasal.id/peraturan/uu/uu-no-27-tahun-2022/pasal-4), [UU PDP Pasal 46](https://pasal.id/peraturan/uu/uu-no-27-tahun-2022/pasal-46), [Hukumonline: penilaian dampak menurut Pasal 34](https://www.hukumonline.com/berita/a/memahami-data-protection-impact-assessments-dalam-pelindungan-data-pribadi-lt667615ca09b2e/)
- [BPJPH: wajib halal produk UMK](https://bpjph.halal.go.id/read/bpjph-17-oktober-2026-produk-makanan-minuman-umk-harus-sudah-bersertifikat-halal-bagaimana-dengan-produk-luar-negeri), [Headline: kewajiban halal tetap 18 Okt 2026](https://www.headline.co.id/149006/wajib-halal-tetap-18-oktober-2026-bpjph-siapkan-aturan-umk/)

**Pasar**

- [Antara: jumlah UMKM menurut Kementerian UMKM](https://www.antaranews.com/berita/4968741/kementerian-umkm-), [Bisnis: data BPS 2023](https://ekonomi.bisnis.com/read/20260522/9/1975662/bps-jumlah-umkm-di-indonesia-mencapai-59-juta-usaha-tahun-2023), [Katadata: statistik QRIS](https://katadata.co.id/finansial/keuangan/6a9e3b775a371/bi-transaksi-qris-tembus-15-miliar-hingga-juli-2026)
- [Bisnis: startup yang tutup, termasuk BukuKas](https://teknologi.bisnis.com/read/20231213/266/1723450/daftar-11-startup-tutup-dan-phk-di-ri-terbaru-ada-pegipegi/2), [Bisnis: BukuWarung 2025](https://teknologi.bisnis.com/read/20260127/84/1947604/bukuwarung-cetak-60-juta-transaksi-pada-2025-punya-8-juta-pengguna), [majoo](https://majoo.id/news/more/majoo-rayakan-6-tahun-dengan-6perience-inovasi-digital-dan-penguatan-customer-experience), [detik: Mekari Jurnal](https://inet.detik.com/business/d-7514764/platform-mekari-jurnal-bantu-optimalkan-bisnis-dengan-sistem-terintegrasi), [HashMicro: Kledo](https://www.hashmicro.com/id/blog/aplikasi-kledo/)
