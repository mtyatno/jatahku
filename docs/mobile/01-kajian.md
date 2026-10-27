# Kajian & Rencana Aplikasi Mobile Jatahku

Disusun 16 Okt 2026 · disetujui pemilik produk 16 Okt 2026. Sumber asli: dokumen "Kajian & Rencana Aplikasi Mobile Jatahku" di claude.ai (diagram hanya ada di sana). Perubahan rencana dibuat di file ini lewat PR.

## Ringkasan eksekutif

Rekomendasinya: bangun aplikasi Android dan iOS dengan **Capacitor 8** di atas bundle React yang sama dengan web. Sebelum menulis shell, bereskan dulu hal yang mahal diubah: identitas aplikasi, sesi per perangkat, kompatibilitas API, penjualan Pro, dan penghapusan akun. Dengan begitu Jatahku tidak perlu migrasi shell seperti Alurik, karena push, widget, Share Extension, billing, dan tablet sudah punya jalur di shell yang sama sejak awal.

Soal format: Play Store memakai AAB (APK hanya untuk sideload dan uji), dan App Store memakai IPA. DMG adalah installer macOS di luar App Store dan tidak dibutuhkan.

Fitur **"Bagikan ke Jatahku"** (bukti transfer, e-wallet, tagihan, dan invoice marketplace) masuk rilis pertama. Fitur ini butuh Kotak Struk asinkron dan parser baru di server, yang lebih dulu dipakai web dan Telegram sebelum aplikasi rilis.

| Fase | Hasil utama | Estimasi |
| --- | --- | --- |
| F0 Keputusan, akun, legal | ADR disetujui; akun Play dan Apple; PSE; kebijakan privasi baru; penguji direkrut | ±4 hk + waktu tunggu |
| F1 Fondasi server dan web | Sesi per perangkat, hapus akun sungguhan, `/app/config`, CI cek API, lapisan `native`, helper jualan, izin AI, tablet di web | ±17,5 hk |
| F2 Spike dua OS | Hal tersulit terbukti di Android, iPhone, dan tablet | ±3 hk |
| F3 Shell Android | Aplikasi setara web, plus login Google native, push, App Links, OTA, dan terima share | ±12 hk |
| FS Bagikan ke Jatahku | Kotak Struk, PDF, parser transfer/e-wallet/tagihan/invoice, deteksi duplikat, UI konfirmasi | ±21,5 hk |
| F4 Google Play | Closed test 14 hari, lalu produksi bertahap | ±3 hk + 14 hari |
| F5 iOS dan billing | Aplikasi iOS universal, Sign in with Apple, Share Extension, Play Billing dan IAP | ±15 hk |
| F6 Native v1.x | Widget, tombol aksi di notifikasi, pintasan | ±11 hk |

Totalnya sekitar 76 hari kerja sampai kedua toko (rentang 66–86). Untuk satu pengembang, Android dengan fitur share tayang di Play Store sekitar minggu ke-14 dan iOS sekitar minggu ke-17, termasuk waktu review toko. Waktunya sekitar 3 minggu lebih cepat bila jalur server/web dan jalur mobile dikerjakan paralel.

Prasyarat di luar kode yang menentukan jadwal: akun Google Play (US$25) dan Apple Developer (US$99/tahun), keputusan jenis akun, 15–20 penguji closed test, perangkat uji (termasuk iPad dan tablet Android), registrasi PSE, dan kebijakan privasi baru.

## Pelajaran dari Alurik

Yang mahal di Alurik bukan fitur barunya, melainkan pekerjaan yang harus dibongkar dan diulang. Contohnya shell Tauri Android, skrip patch, jembatan polling file, penyimpanan token, dan data lokal pengguna yang tidak bisa dibawa. Dua belas akar masalah di bawah diambil dari roadmap migrasi Alurik (fakta repo per 15 Okt 2026), yang memperkirakan migrasi itu ±57–74 hari kerja. Masing-masing akar masalah menjadi aturan Jatahku sejak hari pertama.

| # | Akar masalah di Alurik | Akibatnya | Aturan untuk Jatahku |
| --- | --- | --- | --- |
| 1 | Shell dipilih sebelum kebutuhan native jangka panjang dipetakan | Tauri mobile tidak punya widget, push, unduhan, dan terima-share; semuanya ditulis sendiri lalu ditinggalkan | Shell dipilih dari daftar kebutuhan 2–3 tahun (lihat bagian Kebutuhan); fitur tersulit diuji di kedua OS sebelum berkomitmen |
| 2 | Proyek Android dibuat ulang setiap build lalu ditambal lewat skrip string | Rapuh, sulit di-review, setiap upgrade berisiko | Proyek Android dan iOS di-commit dan di-review seperti kode lain |
| 3 | Cek platform tersebar di UI (`__TAURI__` di 5 titik, `API_BASE` di 7 titik) | Setiap shell baru menyentuh banyak titik di kode UI | Satu lapisan `native` sejak awal; komponen dilarang mengecek platform |
| 4 | Alamat API ditebak dari host halaman; masih ada `fetch` relatif | Di origin shell baru (`localhost`) semua panggilan API patah | Satu klien API dengan base URL eksplisit; tes otomatis untuk origin native |
| 5 | Token di file plaintext, JWT 72 jam tanpa refresh, token di URL | Auth di server dan klien harus didesain ulang | Auth mobile (Keychain/Keystore, refresh token, tanpa token di URL) didesain sebelum rilis pertama |
| 6 | Fitur web yang tidak jalan di WebView baru ketahuan belakangan | `<a download>`, `new Notification()`, dan cek versi tidak berjalan di APK; service worker tidak pernah diverifikasi | Inventaris API web Jatahku terhadap WebView Android dan iOS dibuat di tahap kajian (lihat bagian Kondisi) |
| 7 | Tidak ada skema versi; versi 4.0.0 tetap | `versionCode` sama untuk semua build | Skema versi tunggal sebelum build pertama; `versionCode` selalu naik |
| 8 | Keystore dibuat di CI dan hanya ada di Secrets | Kunci hilang berarti pengguna harus uninstall; ID aplikasi lama terkunci | ID aplikasi final ditetapkan sekali; Play App Signing sejak rilis pertama; kunci upload dicadangkan di dua tempat |
| 9 | Data lokal terikat origin WebView | Ganti shell = data IndexedDB dan antrean offline yang belum terkirim hilang | Origin dan skema app dipilih sekali dan tidak pernah diganti; server tetap sumber kebenaran |
| 10 | Konfigurasi disuntik saat build (flag AI) | Mengubah perilaku butuh build dan rilis ulang | Konfigurasi dibaca dari server dengan cache lokal |
| 11 | Urusan toko ditunda: tanpa AAB, tanpa iOS, tanpa halaman privasi, akun belum ada | Closed testing 14 hari dan verifikasi akun menjadi jalur kritis | Akun, kebijakan privasi, hapus akun, dan penguji dimulai di Fase 0, paralel dengan kode |
| 12 | APK disebar ke pengguna sebelum shell dan identitas final | Pengguna APK lama harus dimigrasi dan diminta sinkron dulu | APK sideload hanya untuk penguji internal sampai rilis toko pertama |

Prinsip umumnya: hal yang mahal diubah (shell, ID aplikasi, origin, auth, billing) diputuskan sekali di depan. Hal yang murah diubah (fitur, tampilan) boleh menyusul.

## Kondisi Jatahku saat ini

Fondasi web Jatahku lebih siap daripada Alurik saat migrasinya dimulai: alamat API sudah eksplisit di klien utama, refresh token sudah ada, dan suara ditranskripsi di server. Yang wajib dibereskan sebelum rilis toko ada tujuh: pencabutan sesi, login Google, unduhan dan cetak, hapus akun yang belum benar-benar menghapus, kebijakan privasi, keamanan penautan Telegram, dan rilis harian tanpa kompatibilitas mundur API. Pembayaran Pro manual butuh keputusan tersendiri (bagian Paket Pro). Fakta di bawah diambil dari repo `mtyatno/jatahku` (main `31eb446`, PR #55, 16 Okt 2026) dan dokumen proyek.

| Area | Keadaan sekarang | Dampak di aplikasi toko | Kategori |
| --- | --- | --- | --- |
| Frontend | React 18 + Vite 6 + Tailwind; PWA lewat `vite-plugin-pwa` (injectManifest); SPA dengan rute `/`, `/transactions`, `/settings`, `/auth/tg`, `/reset-password`, dan lainnya | Dipakai utuh sebagai bundle aplikasi | Siap |
| Klien API | Satu `ApiClient` di `src/lib/api.js`; `API_URL` = `https://api.jatahku.com` di build produksi. Di luar klien ada dua `fetch`: unggah bukti bayar (cadangan ke URL penuh) dan unggah foto profil, yang menebak alamat dari hostname (`localhost` → `http://localhost:8000`) | Di aplikasi hostname selalu `localhost`, sehingga unggah foto profil akan patah, persis pola Alurik #4. Keduanya dipindah ke `ApiClient`, lalu header platform dan versi cukup ditambah di satu tempat | Adaptasi |
| CORS | `allow_origins` hanya `jatahku.com` dan `localhost:5173` | Origin aplikasi (`https://localhost` di Android, `capacitor://localhost` di iOS) ditolak sampai ditambahkan | Adaptasi |
| Token & sesi | Access JWT 30 menit + refresh JWT 30 hari di `localStorage`; refresh otomatis saat 401. Refresh tidak dirotasi atau dicatat. `POST /user/logout-all` hanya menaikkan `updated_at`, padahal token tidak memuat `iat` dan tidak dicek, jadi tidak mencabut apa pun | HP hilang berarti sesi tidak bisa dicabut. Perlu Keychain/Keystore dan refresh token per perangkat yang bisa dicabut | Wajib sebelum rilis |
| Login Google | Tombol Google Identity Services (`GoogleButton.jsx`); server mencocokkan `aud` dengan satu `GOOGLE_CLIENT_ID` | Tombol web ini tidak bisa dipakai di WebView aplikasi; perlu login Google native dan server yang menerima client ID Android dan iOS. Di iOS memicu aturan login pihak ketiga (lihat bagian kesiapan toko) | Wajib sebelum rilis |
| Login Telegram & reset sandi | Bot mengirim link sekali pakai `jatahku.com/auth/tg?token=…` (5 menit); email reset menuju `/reset-password` | Tanpa App Links/Universal Links, link terbuka di browser, bukan di aplikasi | Adaptasi |
| Offline | Service worker menyimpan shell; antrean transaksi IndexedDB `jatahku-offline` dikirim lewat satu `POST /transactions/batch` saat app dibuka, event online, dan Background Sync; cache baca di `localStorage` (TTL 24 jam). Tiap item antrean menyimpan access token | Di aplikasi, service worker tidak perlu (aset sudah di paket) dan Background Sync tidak ada di WebView; sinkron saat app aktif kembali. Token tidak boleh lagi ikut disimpan di item antrean | Adaptasi |
| Suara | `getUserMedia` + `MediaRecorder` (webm/mp4), transkripsi di server (Groq Whisper) | Tidak bergantung Web Speech API, yang tidak ada di WebView (sumber `SpeechBridge.kt` Alurik). Cukup izin mikrofon native dan uji format mp4 di iOS | Adaptasi |
| Foto struk | `<input type="file" accept="image/*">`, dikompres di klien, OCR di server | Berjalan di WebView; perlu teks izin kamera dan foto di iOS | Adaptasi |
| Scan struk | Sinkron: foto diunggah dan hasilnya kembali di respons yang sama. Hanya JPEG/PNG/WebP; PDF ditolak di API dan bot ("File belum didukung"). Parser khusus struk belanja (toko, total, cek pembayaran, barang). Satu OCR berjalan, maksimal 4 antre lalu 503, dan 1 scan per user; Basic 15 scan per bulan; foto tidak disimpan | Fondasi yang baik untuk "Bagikan ke Jatahku", tetapi share bisa berisi banyak file, PDF, bukti transfer, dan invoice. Perlu Kotak Struk asinkron dan parser baru | Adaptasi |
| Unduhan & cetak | CSV dan ekspor JSON lewat blob + `<a download>`; laporan PDF berupa HTML di iframe dengan tombol Simpan dan `print()`; hapus akun mengunduh data dulu | Ketiganya tidak berfungsi di WebView, sama dengan Alurik | Wajib sebelum rilis |
| Tautan keluar | `target="_blank"` dan `window.open` ke `t.me/JatahkuBot` dan tautan di chat bot | Harus dibuka di browser atau aplikasi Telegram, bukan menimpa WebView | Adaptasi |
| Notifikasi | Lonceng in-app polling tiap 30 detik; kanal keluar Telegram (3 dari 29 user) dan email; tanpa push. Semua lewat `notification_service.send_notification` | Push menjadi kanal baru di titik yang sama, plus tabel token perangkat dan preferensi push | Fitur baru |
| Paket Pro | Rp79.000 sekali bayar lewat transfer bank manual + unggah bukti, disetujui admin; kode promo; 29 user saat ini Pro (promo 100 user pertama). Ajakan upgrade ada di Settings, halaman `/upgrade`, tautan `/upgrade` di chat, dan 6 file backend/bot, termasuk pesan kuota seperti "Upgrade di jatahku.com/settings" | Penjualan fitur digital di dalam aplikasi wajib lewat billing toko; ajakan upgrade harus bisa dimatikan per platform dari server | Keputusan |
| Hapus akun | Ada di Settings (`DELETE /user/account`), tetapi berupa anonimisasi: transaksi hanya ditandai `is_deleted`, pemasukan tetap ada, dan baris user tetap ada sehingga refresh token lama masih berlaku | Bertentangan dengan kebijakan privasi sendiri ("dihapus permanen") dan syarat kedua toko | Wajib sebelum rilis |
| Kebijakan privasi | `jatahku.com/privacy.html` (24 Mar 2026), tidak ada di repo. Tidak menyebut Google, Groq (audio dan foto struk), email, hosting, masa simpan, atau UU PDP | Isian Data Safety (Play) dan App Privacy (Apple) harus cocok dengan kebijakan ini | Wajib sebelum rilis |
| Keamanan penautan | Endpoint `/auth/link/*` menerima `telegram_id` tanpa autentikasi bot (temuan 15 Okt) | Risiko pengambilalihan akun naik seiring bertambahnya user | Wajib sebelum rilis |
| Ritme rilis | Setiap merge ke main langsung men-deploy API dan web bersamaan; 30 PR (#26–#55) tayang antara 15 Okt 00.35 dan 16 Okt 09.39 WIB, dari beberapa agen; API tanpa versi | Aplikasi terpasang menjalankan kode lama berminggu-minggu; perubahan API yang tidak kompatibel mundur akan mematahkannya. Ini risiko terbesar | Wajib sebelum rilis |
| Aset luar | Font dari `fonts.googleapis.com` | Tanpa internet, tampilan jatuh ke font cadangan; font sebaiknya ikut dibundel | Adaptasi |

## Kebutuhan mobile 2–3 tahun ke depan

Tiga belas dari enam belas kebutuhan di bawah butuh kode native. Empat di antaranya (widget, push, berbagi ke aplikasi, dan unduhan) persis yang tidak dimiliki Tauri dan memaksa Alurik pindah shell. Daftar ini dibuat lebih dulu supaya shell dipilih dari kebutuhan, bukan sebaliknya.

| Kebutuhan | Rilis | Butuh native? | Kenapa penting untuk Jatahku |
| --- | --- | --- | --- |
| Tampilan HP dan tablet: iPhone, iPad, HP dan tablet Android, layar lipat | v1 | Konfigurasi native: dukungan iPad, orientasi | Android 16 mengabaikan kunci orientasi `portrait` di layar ≥600dp; Apple meminta aplikasi iPhone berjalan di iPad bila memungkinkan (2.4.1) |
| Login email/sandi, Google, dan link Telegram | v1 | Ya: Google native, App Links | Tombol Google versi web tidak berjalan di WebView |
| Sign in with Apple | v1 iOS | Ya | Wajib bila login Google atau Telegram ditawarkan di iOS (Guideline 4.8) |
| Sesi aman dan kunci biometrik | v1 | Ya: Keychain/Keystore, biometrik | Data keuangan; skenario HP hilang |
| Catat offline tanpa pernah hilang | v1 | Ya: penyimpanan native | iOS dapat menghapus storage WebView; `AGENTS.md` melarang membuang transaksi |
| Catat dengan suara | v1 | Izin mikrofon saja | Transkripsi sudah di server |
| Foto struk dari kamera | v1 | Izin kamera saja | OCR sudah di server |
| Bagikan bukti transfer, bukti bayar e-wallet, tagihan, dan invoice marketplace (gambar, PDF, atau teks) ke Jatahku, lalu konfirmasi amplop | v1 | Ya: intent filter Android, Share Extension iOS | Permintaan pemilik produk (16 Okt 2026); bukti bayar sudah ada di HP saat user selesai membayar, cocok dengan prinsip "cermin" |
| Simpan CSV/PDF, cetak laporan, ekspor data | v1 | Ya: file, share sheet, print | `<a download>` dan `print()` tidak berjalan di WebView |
| Push: tagihan, gajian, check-in 21.00, struk siap dicatat, "Sepadan?", Incaran | v1 | Ya: FCM/APNs | Hanya 3 dari 29 user terhubung Telegram; "Sepadan?" (Pikir-Pikir Fase 2) dan struk yang dibagikan dari iOS butuh kanal yang menjangkau semua user |
| Tautan yang membuka aplikasi: login Telegram, reset sandi, notifikasi | v1 | Ya: App Links/Universal Links | Tanpa ini alur login terlempar ke browser |
| Beli Pro di aplikasi | Sebelum rilis iOS | Ya: Play Billing, StoreKit | Transfer manual dilarang untuk fitur digital di aplikasi toko |
| Widget layar utama: "aman per hari" + tombol catat | v1.x | Ya: Glance, WidgetKit | Angka yang paling sering dicek; alasan Alurik pindah shell |
| Pintasan dan asisten ("catat kopi 25rb") | v1.x | Ya: App Shortcuts, App Intents | Lebih cepat daripada membuka aplikasi |
| Ulasan dan pembaruan dari dalam aplikasi | v1.x | Ya | Rating toko; mendorong user ke versi yang masih didukung |
| Baca notifikasi bank/e-wallet untuk catat otomatis (Android) | Kandidat | Ya: NotificationListener | Sesuai prinsip "cermin"; butuh kajian kebijakan Play dan privasi tersendiri. "Bagikan ke Jatahku" adalah versi eksplisit yang lebih aman dari ide ini |

Kesimpulannya, shell harus punya jalur native yang matang di Android dan iOS sejak hari pertama; WebView saja tidak cukup.

## Opsi teknologi dan penilaiannya

Capacitor adalah satu-satunya opsi yang memakai ulang seluruh UI React, melayani Android dan iOS dengan satu shell, dan punya jalur ke semua kebutuhan di bagian sebelumnya. Opsi lain gagal di salah satu dari tiga syarat itu.

| Opsi | Pakai ulang UI web | Android + iOS satu shell | Jalur ke fitur native | Risiko pindah shell lagi | Catatan |
| --- | --- | --- | --- | --- | --- |
| **Capacitor 8** (WebView + plugin) | Penuh | Ya | Lengkap: plugin resmi dan komunitas, plus kode native sendiri di proyek yang di-commit | Rendah | Versi 8.5.3 (7 Okt 2026); Capacitor 9 diperkirakan akhir Nov 2026. Tetap open source walau produk komersial Ionic (Appflow) berhenti dijual sejak Feb 2025 |
| TWA (Bubblewrap), Android saja | Penuh, berjalan di Chrome | Tidak; iOS butuh shell kedua | Terbatas pada API web; aplikasi induk tidak bisa membaca data TWA, jadi widget sulit | Tinggi: pindah ke Capacitor nanti berarti ganti origin dan login ulang, pola yang sama dengan Alurik | Murah untuk mulai, dan login Google web serta unduhan tetap berfungsi karena memakai Chrome |
| PWABuilder iOS | Penuh | Tidak | Minim | Tinggi | Repo pengemas iOS diarsipkan 11 Sep 2025 |
| React Native / Expo | Tidak; UI ditulis ulang | Ya | Lengkap | Rendah | Menulis ulang 111 file frontend dan merawat dua basis UI |
| Flutter | Tidak; UI ditulis ulang dalam Dart | Ya | Lengkap | Rendah | Sama dengan React Native, ditambah bahasa kedua |
| Tauri 2 mobile | Penuh | Ya | Tanpa plugin resmi untuk push, berbagi, dan widget | Tinggi | Ini kasus Alurik |

TWA sempat menjadi kandidat jalur cepat untuk Android. Opsi ini ditolak karena membuat Android dan iOS memakai shell berbeda, dan peralihannya nanti mengulang masalah origin Alurik.

Fitur "Bagikan ke Jatahku" memperkuat pilihan ini. Android cukup memakai intent filter di proyek yang di-commit, sedangkan iOS butuh target Share Extension di proyek Xcode. Keduanya tidak tersedia di TWA dan tidak punya plugin resmi di Tauri.

Keputusan kedua adalah cara aplikasi mendapat kode web. Pilihannya menentukan seberapa jauh aplikasi tertinggal dari web dan API.

| Cara memuat UI | Offline | Selisih versi dengan API | Kepatuhan toko | Catatan |
| --- | --- | --- | --- | --- |
| Dibundel, diperbarui hanya lewat toko | Ya | Besar (minggu) | Aman | Tidak cocok dengan ritme rilis Jatahku (puluhan PR per minggu) |
| **Dibundel + pembaruan OTA** (dipilih) | Ya | Kecil (jam sampai hari) | Aman selama OTA hanya mengganti HTML/JS/CSS dan tidak mengubah tujuan utama aplikasi (Apple 2.5.2 dan DPLA 3.3.1(B); Play mengecualikan JavaScript di WebView) | Butuh host bundle, versi native minimum, dan rollback |
| Memuat `jatahku.com` langsung (`server.url`) | Tidak andal | Nol | Risiko 4.2 tertinggi | Dokumentasi Capacitor menyebut opsi ini bukan untuk produksi; jembatan native juga terbuka untuk konten jarak jauh |

## Keputusan yang direkomendasikan

Enam belas keputusan di bawah adalah hal yang mahal diubah. Setelah disetujui, semuanya dicatat sebagai ADR di repo, dan setiap PR mobile wajib merujuknya.

| ID | Keputusan | Alasan | Biaya kalau diubah nanti |
| --- | --- | --- | --- |
| ADR-M1 | Shell: Capacitor 8 untuk Android dan iOS; naik ke Capacitor 9 setelah versi stabilnya berjalan sekitar 1 bulan | Bagian opsi teknologi | Migrasi shell, seperti Alurik |
| ADR-M2 | UI web dibundel di aplikasi dan diperbarui lewat OTA untuk perubahan HTML/JS/CSS; perubahan native hanya lewat toko | Ritme rilis Jatahku dan kebutuhan offline | Sedang |
| ADR-M3 | ID aplikasi `com.jatahku.app` di Play dan App Store dengan nama "Jatahku"; tidak pernah diganti | ID adalah identitas permanen di toko | Aplikasi baru; user pindah manual |
| ADR-M4 | Play App Signing sejak rilis pertama; kunci upload dicadangkan di 2 tempat; APK sideload hanya diunduh dari Play Console (ditandatangani kunci yang sama dengan Play) | Kunci hilang berarti tidak bisa update; registrasi verifikasi developer Android butuh kunci | User harus uninstall |
| ADR-M5 | Origin bawaan Capacitor (`https://localhost` dan `capacitor://localhost`) dikunci di config dan tidak pernah diubah | Mengganti skema sama dengan pindah domain: data lokal dan login hilang | Data lokal hilang |
| ADR-M6 | Satu lapisan `src/native/` (implementasi web dan Capacitor); komponen dilarang mengecek platform | Pelajaran Alurik #3 | Refactor tersebar di banyak file |
| ADR-M7 | Sesi per perangkat di server: refresh token dirotasi, dicatat, dan bisa dicabut; token di Keychain/Keystore; widget dan Share Extension memakai token terbatas terpisah (baca-saja untuk widget, unggah-saja untuk share) | Aplikasi keuangan; banyak proses (app, widget, ekstensi) memakai sesi yang sama | Desain ulang auth |
| ADR-M8 | Login Google native (Credential Manager di Android, Google Sign-In di iOS) dan Sign in with Apple di iOS; link login Telegram dan reset sandi lewat App Links/Universal Links | Google Identity Services tidak mendukung WebView; Guideline 4.8 | Sedang |
| ADR-M9 | API hanya berubah secara aditif; setiap request membawa header `X-Jatahku-Client`; `/app/config` memegang versi minimum per platform; CI menolak perubahan API yang memutus | Aplikasi lama tetap berjalan berminggu-minggu | Aplikasi terpasang patah |
| ADR-M10 | Hak Pro dicatat server dari semua sumber (transfer, promo, Play, App Store); mode jualan per platform diatur dari server | Aturan tiap toko berbeda dan berubah | Banyak layar dan pesan bot diubah |
| ADR-M11 | Antrean offline di aplikasi disimpan di penyimpanan native, bukan IndexedDB; service worker hanya untuk web | iOS bisa menghapus storage WebView | Transaksi hilang |
| ADR-M12 | Push lewat FCM (Android langsung, iOS lewat APNs) sebagai kanal baru di `notification_service` | Memakai satu titik notifikasi yang sudah ada | Sedang |
| ADR-M13 | Versi aplikasi native memakai semver terpisah dari web; `versionCode` dan build number naik otomatis dari CI | Pelajaran Alurik #7 | Build tidak bisa diunggah |
| ADR-M14 | Distribusi awal hanya untuk Indonesia | Menghindari kewajiban trader DSA di EU dan urusan pajak lintas negara | Rendah |
| ADR-M15 | HP dan tablet didukung sejak rilis pertama: aplikasi iOS universal (iPhone + iPad), Android termasuk tablet dan layar lipat; tata letak responsif yang ada dipakai dan rotasi tidak dikunci di tablet | Android 16 mengabaikan kunci orientasi di layar ≥600dp; Apple 2.4.1; Jatahku sudah punya tata letak `md` (768 px) dan `lg` (1024 px) | Sedang: menambah iPad belakangan butuh screenshot 13 inci, uji ulang, dan rilis baru |
| ADR-M16 | Semua struk dan bukti bayar dari share, unggah web, dan Telegram masuk ke satu Kotak Struk di server; diproses asinkron oleh worker dengan status di database; OCR dan parser tetap di server; tidak ada yang tercatat tanpa konfirmasi user | Satu metode untuk semua kanal (aturan paritas); satu share bisa berisi banyak file; Share Extension iOS tidak bisa membuka aplikasinya | Tinggi: pipeline kedua di HP akan menyimpang dari web dan bot |

## Arsitektur target

> Diagram: arsitektur target · 3 shell, 1 server (lihat dokumen claude.ai)

Ketiga shell memuat bundle web yang sama; yang berbeda hanya implementasi `src/native/`. Semua kanal, termasuk bot Telegram, memakai satu server dan satu Kotak Struk.

| Lokasi | Isi | Catatan |
| --- | --- | --- |
| `frontend/` | Tetap satu bundle untuk web dan aplikasi. Baru: `src/native/` (`index.js` sebagai antarmuka, `web.js`, `capacitor.js`) | Build mode native mematikan service worker dan prompt instal |
| `mobile/` (baru) | `package.json` Capacitor dan plugin, `capacitor.config.ts` (appId, webDir, skema), `android/` dan `ios/` yang di-commit termasuk target Share Extension dan widget, `scripts/version.mjs` | Tidak pernah dibuat ulang saat build |
| `app/` | `auth_sessions`, `/app/config`, `device_tokens` dan pengirim push, Kotak Struk dan worker OCR, verifikasi pembelian Play dan App Store, `/widget/summary` | Semua perubahan aditif |
| `.github/workflows/` | `ci.yml` (tes dan cek OpenAPI pada PR), `mobile-android.yml`, `mobile-ios.yml` (tag `mobile-v*`), publikasi bundle OTA | Deploy web tetap seperti sekarang |
| nginx `jatahku.com` | `/.well-known/assetlinks.json`, `/.well-known/apple-app-site-association`, halaman permintaan hapus akun | Path App Links dibatasi ke `/auth/tg`, `/reset-password`, dan tautan notifikasi |
| `docs/` | `docs/adr/` untuk ADR-M1 sampai M16, dan `docs/mobile-release.md` sebagai runbook rilis | Dirujuk dari `AGENTS.md` |

## Prinsip dan aturan pengaman

Sebelas aturan ini dimasukkan ke `AGENTS.md`, supaya berlaku untuk semua agen yang mengubah repo (Claude, Codex, DeepSeek). PR yang melanggar ditolak.

1. **Satu bundle, satu UI.** Web, Android, dan iOS memakai `frontend/` yang sama. Perbedaan platform hanya boleh ada di `src/native/`; komponen React tidak boleh memeriksa `Capacitor`, user agent, atau `display-mode`.
2. **API hanya bertambah.** Field dan endpoint lama tidak dihapus atau diubah artinya sebelum `min_supported_version` di `/app/config` dinaikkan dan user sudah melihat banner pembaruan. CI memeriksa perbedaan OpenAPI pada setiap PR. Deploy web tetap berjalan seperti sekarang dan tidak menunggu aplikasi.
3. **Aplikasi selalu menyebut dirinya.** Setiap request membawa `X-Jatahku-Client: <platform>/<versi>/<build>`. Server boleh mengubah perilaku (teks jualan, fitur) berdasarkan header ini, tidak pernah berdasarkan tebakan.
4. **Jualan diatur server.** Tombol, tautan, dan teks ajakan beli, termasuk pesan kuota dari bot, datang dari satu helper yang membaca mode jualan per platform. Teks "upgrade" tidak boleh ditulis langsung di komponen atau handler.
5. **Tidak ada transaksi yang hilang.** Di aplikasi, antrean offline disimpan di penyimpanan native. Item yang ditolak tetap disimpan, sesuai aturan antrean yang sudah berlaku di web.
6. **Rahasia hanya di Keychain/Keystore.** Di aplikasi, token tidak disimpan di `localStorage`, IndexedDB, item antrean, atau URL.
7. **Proyek native di-commit dan di-review.** `mobile/android/` dan `mobile/ios/` tidak dibuat ulang saat build dan tidak ditambal dengan skrip.
8. **OTA hanya untuk web.** Bundle OTA hanya berisi hasil build `frontend/` dan membawa versi native minimum. Perubahan plugin, izin, atau kode native wajib lewat rilis toko.
9. **Identitas tidak pernah berubah.** ID aplikasi, skema/origin, dan kunci penandatanganan dicatat di ADR. Mengubahnya butuh keputusan tertulis dari pemilik produk.
10. **Paritas diuji, bukan diasumsikan.** Daftar periksa paritas (lampiran WBS) dijalankan di perangkat nyata sebelum setiap rilis toko, termasuk di satu Android kelas bawah.
11. **Struk tidak pernah tercatat diam-diam atau dua kali.** Dokumen dari share, unggahan, atau Telegram selalu menunggu konfirmasi user. Hash file, nomor referensi, dan `client_ref` mencegah pencatatan ganda; transfer yang gagal tidak bisa dicatat.

## Kesiapan Google Play, App Store, dan regulasi Indonesia

Sebagian besar penundaan rilis datang dari akun, kebijakan, dan masa tunggu, bukan dari kode. Karena itu closed testing 14 hari di Play, verifikasi akun, perbaikan hapus akun, dan registrasi PSE dimulai sejak Fase 0, paralel dengan pekerjaan kode.

| Butir | Google Play | App Store | Keadaan Jatahku | Aksi |
| --- | --- | --- | --- | --- |
| Akun dan biaya | US$25 sekali; verifikasi identitas sekitar 3 hari kerja; akun organisasi butuh D-U-N-S | US$99/tahun; akun perorangan menampilkan nama legal sebagai penjual; organisasi butuh badan hukum dan D-U-N-S | Belum ada | F0: pilih perorangan atau organisasi, lalu daftar |
| Uji sebelum produksi | Akun personal baru: closed test dengan ≥12 penguji yang ikut 14 hari berturut-turut | TestFlight, tanpa syarat jumlah penguji | Belum ada penguji | F0: rekrut 15–20 penguji dari user yang ada |
| Format dan penandatanganan | AAB wajib, dengan Play App Signing | Build dari Xcode 26 dengan SDK iOS 26 (wajib sejak 28 Apr 2026) | Tidak ada | CI Android dan macOS |
| Target sistem | API 36 (Android 16) sejak 31 Agu 2026, perpanjangan sampai 1 Nov 2026; edge-to-edge tidak bisa dimatikan di Android 16 | Target minimum iOS 13; Capacitor 8 memakai iOS 15 | – | Capacitor 8 sudah memakai API 36 |
| Tablet | Kunci orientasi dan ukuran diabaikan di layar ≥600dp untuk aplikasi API 36; screenshot tablet 7 dan 10 inci disarankan untuk listing di tablet | 2.4.1: aplikasi iPhone sebaiknya berjalan di iPad; bila mendukung iPad, wajib ada screenshot iPad 13 inci | Manifest PWA mengunci `portrait`; tata letak `md` dan `lg` sudah ada | Uji tablet di F3 dan F5; siapkan screenshot tablet |
| Kebijakan privasi | URL publik wajib, dicocokkan dengan formulir Data safety | URL publik wajib, dicocokkan dengan label App Privacy | Ada, tetapi tidak menyebut pihak ketiga dan masa simpan | F0: perbarui |
| Hapus akun | Dari dalam aplikasi dan dari halaman web; data harus dihapus, bukan dibekukan | Dari dalam aplikasi; menonaktifkan saja tidak cukup | Anonimisasi; data tetap tersimpan | F1: perbaiki |
| Login pihak ketiga | – | 4.8: bila login Google atau Telegram menjadi akun utama, wajib ada opsi setara yang menjaga privasi email | Google dan link Telegram | F5: Sign in with Apple |
| Data ke AI pihak ketiga | Diungkap di formulir Data safety | 5.1.2(i): ungkap dan minta izin eksplisit sebelum data pribadi dikirim ke AI pihak ketiga | Audio dan foto struk dikirim ke Groq tanpa izin khusus | F1: layar izin |
| Struk yang dibagikan | Data safety mencantumkan foto, file, dan info keuangan yang diproses | Label App Privacy untuk foto dan konten user; Share Extension butuh App Group dan privacy manifest sendiri | Belum ada | FS.11 dan 5.8 |
| Fitur keuangan | Deklarasi fitur keuangan wajib untuk semua aplikasi; untuk aplikasi anggaran, pilihan "Other" + deskripsi lebih aman | – | – | F4 |
| Fungsi minimum | – | 4.2: harus lebih dari website yang dikemas | PWA | Push, biometrik, Sign in with Apple, Share Extension, offline; widget di v1.x |
| Rating usia | Kuesioner rating konten | Kuesioner usia baru (13+/16+/18+) | – | F4 dan F5 |
| Wilayah | – | Status trader DSA wajib bila tersedia di EU | – | Rilis untuk Indonesia saja |
| Verifikasi developer Android | Sejak 30 Sep 2026, instal dari toko yang ikut program di wilayah awal (termasuk Indonesia) wajib dari developer terverifikasi; APK sideload menyusul pada 2027 | – | – | Daftarkan paket lewat Play Console; APK sideload hanya dari Play Console |

Regulasi Indonesia berlaku untuk Jatahku dengan atau tanpa aplikasi toko, tetapi rilis di toko menaikkan visibilitas dan risikonya.

| Aturan | Kewajiban yang relevan | Aksi |
| --- | --- | --- |
| UU PDP (UU 27/2022), berlaku penuh 17 Okt 2024 | Data keuangan termasuk data pribadi spesifik, sehingga wajib DPIA. Persetujuan harus eksplisit; pemberitahuan memuat dasar hukum, tujuan, masa simpan, dan hak user. Permintaan akses atau koreksi dijawab dalam 3×24 jam, kebocoran dilaporkan dalam 3×24 jam, dan pengiriman data ke luar negeri (Groq, AS) harus memenuhi Pasal 56. Bukti transfer yang dibagikan memuat data pihak ketiga (nama dan rekening penerima), sehingga minimisasi data wajib dirancang | F0–F1: kebijakan privasi, DPIA ringkas, izin AI, prosedur kebocoran |
| PP 33/2026 (pelaksana UU PDP) | Diundangkan 16 Jul 2026, berlaku 16 Jan 2027; isi diketahui dari sumber sekunder karena teks resminya belum terbit di JDIH | Pantau, lalu sesuaikan sebelum Jan 2027 |
| PSE Lingkup Privat (Permenkominfo 5/2020 jo. 10/2021) | Wajib terdaftar sebelum layanan dipakai. Pada 27 Sep 2026 Komdigi memperingatkan 7 PSE yang belum terdaftar, termasuk aplikasi kalori FatSecret | F0: NIB dan TD PSE lewat OSS |
| OJK | Aplikasi pencatat yang tidak memindahkan uang berada di luar cakupan POJK 3/2024 | Tidak perlu izin; ditinjau ulang bila menambah pembayaran, pinjaman, atau saran investasi |
| Pajak penjualan di toko | Google memungut PPN atas pembelian lewat Play; di Apple, developer lokal menanggung PPN sendiri; kedua toko meminta formulir pajak AS (W-8BEN) | F5: siapkan sebelum billing aktif |

## Paket Pro di aplikasi toko

Rekomendasinya: rilis Android pertama tanpa penjualan di aplikasi, dengan Pro yang dibeli di web tetap aktif. Sebelum aplikasi iOS rilis, Pro mulai dijual lewat Play Billing dan in-app purchase Apple. Di semua tahap, server menjadi satu-satunya sumber hak Pro.

| Opsi | Google Play | App Store | Catatan |
| --- | --- | --- | --- |
| A. Tanpa jualan di aplikasi; Pro yang dibeli di web tetap aktif | Boleh ("consumption-only"); boleh menyebut situs tanpa tautan langsung | Berisiko: 3.1.3(b) meminta item yang dibeli di web juga tersedia sebagai IAP; pengecualian 3.1.3(f) untuk aplikasi pendamping gratis diputuskan reviewer | Paling cepat untuk rilis Android pertama |
| B. Billing toko (Play Billing + IAP Apple) untuk Pro sekali bayar | Wajib bila menjual di aplikasi; Indonesia ikut program user choice billing (biaya turun 4% bila user memilih billing developer) | Wajib (3.1.1), termasuk mekanisme pulihkan pembelian | Komisi 15% lewat Small Business Program Apple dan tier 15% Google; keduanya harus didaftarkan |
| C. Tombol atau tautan ke pembayaran web dari dalam aplikasi | Tidak boleh di Indonesia; program tautan keluar hanya untuk AS dan EEA | Tidak boleh di Indonesia; tautan pembelian luar hanya di AS, EU, Jepang, Brasil, dan beberapa negara lain | – |
| D. Transfer bank manual di dalam aplikasi | Tidak boleh | Tidak boleh | Tetap berjalan di web |

**Desain hak akses.** Rancangan ini dibuat sekarang walau billing baru aktif di Fase 5, supaya tidak ada layar atau pesan yang harus dibongkar.

- Setiap hak Pro dicatat dengan sumbernya: `transfer`, `promo`, `play`, atau `appstore`. Status `user.plan` dihitung dari catatan itu, bukan diubah langsung.
- Pembelian divalidasi di server: Google Play Developer API (pembelian wajib di-acknowledge dalam 3 hari) dan App Store Server API. Notifikasi refund atau pembatalan dari kedua toko mencabut hak yang bersangkutan.
- `/app/config` mengirim mode jualan per platform: `none` (tanpa jualan, teks kuota netral), `store` (tombol beli memanggil billing toko), atau `web` (khusus web).
- Pesan kuota dari bot di chat aplikasi mengikuti mode yang sama, karena server tahu platform dari header `X-Jatahku-Client`.
- 29 user yang sudah Pro lewat promo tetap Pro di semua platform.

**Harga.** Harga web Rp79.000. Di toko dipakai titik harga terdekat. Bila harga toko Rp79.000 sudah termasuk PPN 11%, hasil bersih setelah komisi 15% sekitar Rp60.500 per penjualan; angka persisnya mengikuti laporan tiap toko, dan di Apple PPN untuk developer lokal menjadi tanggungan developer. Harga di toko boleh disamakan dengan web (lebih sederhana bagi user) atau dinaikkan untuk menutup komisi; ini keputusan pemilik produk.

**Kuota scan dihapus (K4, spec Bagikan ke Jatahku, 26 Okt 2026).** Struk, PDF, bukti bayar, dan teks yang dibagikan tidak dihitung sebagai scan, untuk semua paket dan platform; kuota scan Basic (15 per bulan) hilang. Satu-satunya batas bulanan adalah kuota transaksi (Basic 50 per bulan), yang dicek sekali di awal input. Jatahku tidak pernah menolak fakta pengeluaran, dan kebiasaan mencatat tidak boleh terganggu. Beban OCR dijaga batas gabungan 30 bukti per jam per user, bukan kuota bulanan.

## Fitur "Bagikan ke Jatahku"

Fitur ini layak menjadi fitur inti rilis pertama, karena cocok dengan prinsip Jatahku sebagai cermin: user mencatat setelah membayar, dan bukti bayarnya sudah ada di HP. Fitur ini menuntut tujuh perubahan sistem. Di server ada empat: Kotak Struk asinkron dengan worker OCR terpisah, pembaca PDF, parser untuk bukti transfer, e-wallet, tagihan, dan invoice, serta deteksi duplikat dan bukan pengeluaran. Di aplikasi ada tiga: penerima share di Android, Share Extension iOS dengan token unggah-saja, dan notifikasi "siap dicatat".

### Dokumen yang ditangani

| Jenis | Contoh sumber | Format masuk | Yang dibaca | Pemeriksaan silang | Catatan |
| --- | --- | --- | --- | --- | --- |
| Bukti transfer bank | BCA, Livin' by Mandiri, BRImo, BNI, BSI, Jago, SeaBank, blu | Gambar, kadang PDF | Nominal, biaya admin, total, tanggal dan jam, penerima dan bank, berita, nomor referensi, status | Nominal + biaya = total; status harus "berhasil" | Transfer ke rekening sendiri dan top-up e-wallet bukan pengeluaran |
| Bukti bayar e-wallet dan QRIS | GoPay, OVO, DANA, ShopeePay, QRIS dari m-banking | Gambar | Merchant, nominal, tanggal, ID transaksi, metode bayar | Nominal dibanding total dibayar | Top-up saldo bukan pengeluaran |
| Tagihan dan isi ulang | PLN, BPJS, PDAM, pulsa dan paket data | Gambar | Jenis tagihan, nominal, biaya admin, ID pelanggan (disamarkan) | Nominal + admin = total | Jenis tagihan langsung menyarankan amplop, mis. Listrik atau Pulsa |
| Invoice marketplace | Shopee, Tokopedia/TikTok Shop, Lazada, Blibli | PDF berteks atau screenshot | Nomor invoice, barang (nama, qty, harga), ongkir, biaya layanan dan asuransi, diskon dan voucher, total dibayar | Σ barang + ongkir + biaya − diskon = total, perluasan dari rekonsiliasi yang sudah ada | Dicatat per barang, sama seperti struk belanja |
| Struk belanja (sudah ada) | Indomaret, Alfamart, dan toko lain | Foto | Toko, tanggal, total, barang | Tunai − kembali, atau non-tunai | Tetap memakai parser sekarang |
| Teks | Pesan "Transfer berhasil Rp150.000 ke …" dari aplikasi lain | Teks | Nominal dan keterangan | – | Memakai parser teks yang sudah dipakai web dan bot |

### Alur dari share sampai tercatat

Semua kanal masuk ke satu Kotak Struk di server, lalu diproses dengan satu pipeline yang sama. Android membuka layar konfirmasi langsung; iOS mengandalkan notifikasi karena Share Extension tidak boleh membuka aplikasinya.

> Diagram: alur Bagikan ke Jatahku · 3 kanal masuk, 1 Kotak Struk, konfirmasi wajib (lihat dokumen claude.ai)

Yang baru dibanding scan struk sekarang adalah jalur share, worker asinkron, dan pemeriksaan otomatis. Kartu konfirmasi dan pencatatan per barang memakai yang sudah ada.

### Rancangan per bagian

- **Menerima share di Android.** Intent filter `ACTION_SEND` dan `ACTION_SEND_MULTIPLE` untuk `image/*`, `application/pdf`, dan `text/plain` di proyek Android yang di-commit. App menyalin file dari URI sementara ke cache, mengunggahnya ke Kotak Struk, lalu langsung membuka layar konfirmasi. Saat offline, file dan metadatanya disimpan di antrean native dan dikirim saat online.
- **Menerima share di iOS.** Share Extension (target Swift kecil) menerima gambar, PDF, dan teks, mengecilkan gambar besar, lalu mengunggah lewat sesi latar URLSession dengan token unggah-saja dari Keychain bersama. Di iOS hanya ekstensi Today dan iMessage yang boleh membuka aplikasi induknya, jadi konfirmasi amplop terjadi lewat notifikasi atau Kotak Struk di aplikasi. Belum login: ekstensi meminta user masuk dulu. Offline: file disimpan di App Group dan dikirim aplikasi saat dibuka.
- **Kotak Struk di server.** Satu tempat untuk semua kanal: share Android dan iOS, unggah di web (termasuk drag-and-drop PDF di desktop), dan Telegram (foto dan dokumen PDF). Status item: `diterima` → `diproses` → `siap`, `perlu dicek`, `duplikat`, atau `gagal` → `tercatat` atau `dilewati`. Status disimpan di database, sehingga restart karena deploy tidak menghilangkan pekerjaan. Item yang dibagikan di HP bisa dikonfirmasi di web desktop, dan sebaliknya.
- **Pemrosesan.** OCR dan parser tetap di server, satu metode untuk semua kanal sesuai aturan paritas web–Telegram. OCR dipindah ke worker terpisah yang membaca antrean. Ini menggantikan batas sinkron sekarang (1 OCR berjalan, maksimal 4 antre lalu 503, dan 1 scan per user), karena satu share bisa berisi beberapa gambar. PDF berteks dibaca langsung tanpa OCR; PDF hasil pindaian dirender per halaman lalu di-OCR.
- **Parser.** Jenis dokumen diklasifikasi dari kata kunci, lalu dibaca parser per jenis dengan pemeriksaan silang di tabel atas. Jalur utama tetap tanpa LLM. Fallback LLM tetap mati secara default; bila dinyalakan, wajib ada izin eksplisit (Apple 5.1.2(i), UU PDP). Belajar dari koreksi diperluas dari label total per toko menjadi label per templat aplikasi (mis. BCA, GoPay), dengan syarat yang sama: disetujui ≥2 user berbeda.
- **Konfirmasi amplop.** Layar konfirmasi memakai ulang kartu struk yang sudah ada: satu amplop untuk transfer, e-wallet, dan tagihan; amplop per barang untuk invoice. Saran amplop diambil dari kata kunci penerima, merchant, berita, dan jenis tagihan, dipelajari per user seperti sekarang. Tidak ada yang tercatat tanpa ketukan user. Tombol "Bukan pengeluaran" tersedia untuk top-up, transfer ke rekening sendiri, dan tarik tunai.
- **Notifikasi.** Push "Transfer Rp150.000 ke Siti siap dicatat — pilih amplop" dikirim saat item siap dan user tidak sedang membuka aplikasi. Item yang belum dicatat diingatkan sekali sehari, digabung dengan check-in 21.00, dan jumlahnya tampil sebagai lencana di aplikasi. Di v1.x ditambah tombol "Catat ke Makan" langsung di notifikasi, hanya untuk item berkeyakinan tinggi tanpa peringatan duplikat.
- **Duplikat dan bukan pengeluaran.** File dengan hash yang sama atau nomor referensi yang sama ditandai duplikat. Transaksi dengan nominal sama dalam ±1 hari dan keterangan mirip memunculkan peringatan "sepertinya sudah tercatat", begitu juga invoice dan bukti bayar untuk pembelian yang sama. Transfer berstatus gagal atau masih diproses tidak bisa dicatat. Pencatatan memakai `client_ref` dari id item, sehingga kirim ulang tidak menggandakan.
- **Kuota dan paket.** Tidak ada kuota scan (K4): share tidak dihitung sebagai scan di paket mana pun. Yang berlaku hanya kuota transaksi Basic (50 per bulan), dicek sekali di awal input, sesuai prinsip "cermin, bukan penjaga gerbang". Teks kuota transaksi mengikuti mode jualan per platform.
- **Privasi dan keamanan.** Bukti transfer memuat data pihak ketiga, yaitu nama dan rekening penerima. File asli dihapus begitu selesai diproses. Yang disimpan hanya pratinjau kecil (±2 KB, seperti di chat) dan field yang dibutuhkan, tanpa nomor rekening; teks OCR tetap dihapus setelah feedback atau 24 jam seperti sekarang. File dari luar dianggap tidak tepercaya: ada batas ukuran dan halaman, cek tipe dari isi file, perlindungan bom dekompresi (sudah ada), dan parsing PDF di proses terpisah dengan batas waktu.
- **Kanal tambahan (opsional).** Web Share Target untuk PWA di Android berbasis Chromium, dan terusan email invoice ke alamat khusus per user. Keduanya memakai Kotak Struk yang sama.

### Perubahan pada sistem dan rencana

| Bagian dokumen | Perubahan karena fitur ini |
| --- | --- |
| Kondisi saat ini | Baris "Scan struk": sinkron, gambar saja, parser struk belanja; PDF ditolak di API dan bot |
| Kebutuhan | "Bagikan ke Jatahku" naik dari v1.x ke v1 dan diperluas ke bukti transfer, e-wallet, tagihan, dan invoice |
| Opsi teknologi | Butuh intent filter Android dan target Share Extension di Xcode, yang hanya mungkin bila proyek native di-commit |
| Keputusan | ADR-M16 (Kotak Struk satu pipeline); ADR-M7 diperluas dengan token unggah-saja untuk Share Extension |
| Arsitektur | Jalur share → Kotak Struk → worker OCR → push → konfirmasi |
| Aturan pengaman | Aturan 11: tidak ada struk yang tercatat diam-diam atau dua kali |
| Toko dan regulasi | Data safety dan App Privacy mencantumkan foto dan file; DPIA mencakup data pihak ketiga; privacy manifest untuk Share Extension |
| Paket Pro | Kuota scan dihapus untuk semua input dan paket (K4); yang berlaku hanya kuota transaksi Basic (50 per bulan) |
| WBS | Fase baru FS (±21,5 hk), 3.10 Android (1,5 hk), 5.8 iOS (3 hk); di F6, 6.4 menjadi tombol aksi di notifikasi |
| Jadwal | Android rilis dengan fitur ini sekitar minggu ke-14 dan iOS sekitar minggu ke-17 untuk satu pengembang, termasuk review toko; sekitar 3 minggu lebih cepat bila jalur server/web dan mobile dikerjakan paralel |
| Risiko | Enam risiko baru: templat beragam, pencatatan ganda, data pihak ketiga, lonjakan OCR, batas Share Extension, file berbahaya |

### Kriteria selesai fitur

Angka di bawah adalah target usulan untuk gerbang rilis, diuji dengan korpus FS.5.

- [ ] Bukti transfer dari 8 aplikasi bank teratas terbaca benar (nominal, tanggal, status) pada ≥95% sampel uji
- [ ] Invoice PDF Shopee dan Tokopedia: total cocok dengan Σ barang + biaya − diskon pada ≥90% sampel uji
- [ ] Share satu gambar dari Android, saat app tertutup maupun terbuka, sampai ke layar konfirmasi dalam ≤5 detik saat online
- [ ] Share dari iOS menghasilkan notifikasi "siap dicatat" dalam ≤30 detik saat online
- [ ] Dokumen yang sama dibagikan dua kali tidak pernah tercatat dua kali
- [ ] Transfer berstatus gagal tidak bisa dicatat; top-up dan transfer ke rekening sendiri disarankan "bukan pengeluaran"
- [ ] Tidak ada file asli yang tersisa di server setelah item selesai diproses

## Roadmap per fase dan gerbang keluar

Untuk satu pengembang, Android dengan fitur share tayang sekitar minggu ke-14 dan iOS sekitar minggu ke-17, termasuk waktu review toko. Jalur kritisnya ditentukan kalender, bukan kode: closed test 14 hari dimulai di minggu ke-8. Selama masa tunggu itu, pipeline share dikerjakan dan lebih dulu tayang di web dan Telegram.

> Diagram: roadmap · 8 fase, 2 rilis toko (lihat dokumen claude.ai)

Fase berikutnya hanya dimulai setelah gerbang fase sebelumnya lulus. Bila satu butir spike F2 gagal, rencana direvisi sebelum shell dibangun, bukan sesudahnya; di titik inilah Alurik kehilangan waktu.

| Gerbang | Minggu | Syarat lulus | Diperiksa oleh |
| --- | --- | --- | --- |
| G0 Rencana disetujui | 1 | ADR-M1 sampai M16 disetujui; jenis akun diputuskan; akun Play dan Apple diajukan; ≥15 penguji bersedia | Pemilik produk |
| G1 Fondasi tayang dan spike lulus | 5 | Sesi per perangkat dan hapus akun sungguhan tayang di web tanpa regresi; CI menolak perubahan API yang memutus; kebijakan privasi baru tayang; semua butir spike lulus di 1 Android, 1 iPhone, dan 1 tablet | CI dan pemilik produk |
| G2 Closed test dimulai | 8 | Paritas Android lulus di 3 perangkat; build bertanda tangan keluar dari CI; OTA dan rollback teruji; listing dan formulir Play lengkap | Pemilik produk |
| G3 Kotak Struk tayang di web dan Telegram | 12 | Korpus uji lolos target; invoice PDF memberi hasil sama di web dan bot; deteksi duplikat lulus; tidak ada file asli tersisa di server | CI dan pemilik produk |
| G4 Android tayang | 14 | Closed test 14 hari terpenuhi; share Android lulus paritas; target crash-free ≥99% sesi selama closed test; produksi disetujui Google | Google dan pemilik produk |
| G5 iOS tayang | 17 | Paritas iPhone dan iPad lulus; Sign in with Apple, Share Extension, serta beli, pulihkan, dan refund Pro teruji di sandbox; lolos review Apple | Apple dan pemilik produk |

## WBS detail

Total sampai kedua toko sekitar 76 hari kerja efektif (rentang 66–86), termasuk fitur "Bagikan ke Jatahku" (fase FS), ditambah sekitar 11 hari kerja untuk fitur native v1.x. Estimasi dihitung untuk satu pengembang yang sudah mengenal repo. Setiap paket kerja menjadi satu PR kecil dengan kriteria selesai yang diperiksa sebelum merge.

### F0 — Keputusan, akun, dan legal (±4 hk + waktu tunggu)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Tulis dan setujui ADR-M1 sampai M16 | `docs/adr/` (baru), `AGENTS.md` | Disetujui pemilik; dirujuk PR berikutnya | 0,5 | – |
| 0.2 | Daftar Google Play Console dan Apple Developer Program | Konsol toko | Kedua akun aktif dan terverifikasi | 0,5 + tunggu 3–7 hari (D-U-N-S s.d. 30 hari) | Keputusan jenis akun |
| 0.3 | Daftar PSE: NIB perorangan dan TD PSE lewat OSS | OSS | Nomor TD PSE terbit | 0,5 + tunggu | – |
| 0.4 | Perbarui kebijakan privasi dan syarat (pihak ketiga, masa simpan, hak UU PDP, URL hapus akun, cakupan aplikasi); susun DPIA ringkas | `privacy.html`, `terms.html` (dimasukkan ke repo) | Halaman tayang; DPIA tersimpan | 1,5 | – |
| 0.5 | Rekrut 15–20 penguji closed test dan kumpulkan email Google mereka | – | ≥15 penguji bersedia | 0,5 | – |
| 0.6 | Siapkan jalur build iOS: runner macOS GitHub (gratis untuk repo publik) atau Codemagic, plus sertifikat Apple | `.github/workflows/`, Apple Developer | Build iOS kosong berhasil dari CI | 0,5 | 0.2 |

### F1 — Fondasi server dan web (±17,5 hk, dideploy ke web tanpa regresi)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 1.1 | Sesi per perangkat: tabel `auth_sessions`, rotasi refresh token dengan deteksi reuse dan masa tenggang beberapa detik, `sid` di access token, logout dan `logout-all` benar-benar mencabut | `core/security.py`, `core/deps.py`, `routes/auth.py`, `routes/user_settings.py`, alembic | Tes: token lama ditolak; logout-all memutus semua perangkat; web tetap login | 3 | 0.1 |
| 1.2 | Hapus akun sungguhan sesuai kebijakan amplop bersama, halaman permintaan hapus di web dengan konfirmasi email, dan pencabutan semua sesi | `routes/user_settings.py`, halaman web baru | Tes: data terhapus atau teranonim penuh; refresh token lama ditolak; halaman web berfungsi tanpa login | 2,5 | 1.1 |
| 1.3 | Header `X-Jatahku-Client`, `GET /app/config` (versi minimum, mode jualan, fitur, URL privasi, bundle OTA), layar "perlu update", endpoint laporan error klien | `api.js`, route baru, `Layout.jsx` | Web mengirim header; config dibaca dengan cache lokal | 1,5 | 0.1 |
| 1.4 | CI untuk PR: pytest, tes node, dan cek perubahan OpenAPI yang memutus; aturan mobile di `AGENTS.md` | `.github/workflows/ci.yml` (baru), `AGENTS.md` | PR yang menghapus field gagal di CI | 1,5 | 0.1 |
| 1.5 | Lapisan `src/native/` versi web: token, penyimpanan antrean, simpan dan bagikan file, cetak, tautan luar, info platform. Semua pemanggil dipindah, termasuk dua `fetch` di luar `ApiClient` (bukti bayar, foto profil). Service worker dan prompt instal hanya di web | `src/native/*`, `api.js`, `ExportButtons.jsx`, `Settings.jsx`, `Upgrade.jsx`, `ChatPanel.jsx`, `TelegramPrompt.jsx`, `PWAPrompt.jsx`, `main.jsx`, `offlineQueue.js` | Perilaku web identik; tes unit adapter web; tidak ada lagi alamat API yang ditebak dari hostname | 3 | 1.3 |
| 1.6 | Satu helper jualan untuk semua ajakan upgrade: Settings, halaman Upgrade, tautan di chat, dan 6 file backend/bot | `services/plan_limits.py`, `routes/transactions.py`, `bot/handlers.py`, `bot/receipt_cmd.py`, `bot/batch_cmd.py`, `bot/help_cmd.py`, `Settings.jsx`, `chatFormat.js` | Pada mode `none` tidak ada teks atau tautan beli di layar maupun pesan bot | 1,5 | 1.3 |
| 1.7 | Izin eksplisit sebelum audio atau foto struk dikirim ke Groq | `VoiceInput.jsx`, `ReceiptInput.jsx`, `ChatPanel.jsx`, setelan user | Izin tercatat; tanpa izin, data tidak dikirim | 1 | 0.4 |
| 1.8 | Amankan endpoint `/auth/link/*` dengan secret bersama bot atau panggilan in-process | `routes/link.py`, `bot/link_cmd.py` | Panggilan tanpa secret ditolak; alur link tetap jalan | 1 | – |
| 1.9 | Bundel font lokal; berhenti memuat dari `fonts.googleapis.com` | `index.html`, `index.css`, `public/fonts/` | Tampilan sama saat offline | 0,5 | – |
| 1.10 | Pemeriksaan tablet di web: rentang `md` (768–1023 px) dan `lg` lanskap; dialog, bottom sheet chat, dan grid Beranda; rotasi | `Layout.jsx`, `Dashboard.jsx`, `ChatPanel.jsx` | Tangkapan layar iPad dan tablet Android, potret dan lanskap, sudah diperiksa | 2 | – |

### F2 — Spike teknis di kedua OS (±3 hk)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 2.1 | Aplikasi Capacitor minimal di Android dan iOS untuk menguji hal tersulit: login Google native, rekam suara (webm/mp4) dan transkripsi, kamera, simpan/bagikan/cetak, deep link, token push, antrean di penyimpanan native, safe area Android 16 dan iPhone, keyboard dengan bottom sheet chat, tombol kembali, iPad dan tablet Android | `mobile-spike/` (dibuang setelah selesai) | Laporan lulus/gagal per butir di 1 HP Android, 1 iPhone, dan 1 tablet; keputusan lanjut atau ubah rencana | 3 | 0.2, 0.6 |

### F3 — Shell Android sampai siap closed test (±12 hk)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 3.1 | Scaffold `mobile/`: Capacitor 8, appId `com.jatahku.app`, build frontend mode native, `android/` di-commit; ikon, splash, SystemBars dan variabel `--safe-area-inset-*`, status bar per tema, keyboard, tombol kembali (tutup sheet/modal, lalu riwayat, lalu minimize) | `mobile/*`, `frontend/vite.config.js`, CSS | App membuka UI dan login ke produksi | 1,5 | F1, 2.1 |
| 3.2 | Adapter `src/native/capacitor.js`: Keychain/Keystore, Preferences untuk antrean, Filesystem + Share, Printer, tautan luar (Telegram terbuka di aplikasinya), sinkron antrean saat app aktif dan saat online | `src/native/capacitor.js` | Tes unit dengan mock; ekspor, cetak, dan `t.me` diuji manual | 1,5 | 3.1 |
| 3.3 | Login Google native; server menerima client ID web, Android, dan iOS | `GoogleButton.jsx` lewat adapter, `services/google_auth.py` | Login Google berhasil di Android; web tetap jalan | 1 | 3.2 |
| 3.4 | App Links: `assetlinks.json` di nginx; `/auth/tg`, `/reset-password`, dan tautan notifikasi membuka aplikasi | nginx HestiaCP, `AndroidManifest.xml`, adapter | Link login dari bot membuka aplikasi dan langsung masuk | 0,5 | 3.1 |
| 3.5 | Push Android: proyek Firebase, plugin, tabel `device_tokens` dan API, kanal push di `send_notification`, preferensi push, ketuk notifikasi membuka layar terkait | `services/notification_service.py`, `models.py`, `Settings.jsx` | Pengingat langganan uji tiba; opt-out bekerja | 2 | 3.2 |
| 3.6 | Kunci biometrik opsional saat membuka aplikasi, dengan cadangan PIN perangkat | adapter, `Settings.jsx` | Bisa diaktifkan dan dimatikan; user tidak terkunci saat sensor gagal | 0,5 | 3.2 |
| 3.7 | Penandatanganan dan versi: Play App Signing, kunci upload di Secrets dan dicadangkan di 2 tempat, skrip versi, workflow AAB + APK pada tag `mobile-v*` | `mobile/android/app/build.gradle`, `.github/workflows/mobile-android.yml` | Build bertanda tangan keluar dari CI; `versionCode` naik otomatis | 1 | 0.2 |
| 3.8 | OTA: plugin live update, host bundle, kanal beta/stable, versi native minimum, rollback otomatis bila app gagal start | adapter, `/app/config`, `deploy.sh` | Perubahan web tiba di HP tanpa rilis toko; rollback teruji | 1,5 | 1.3, 3.1 |
| 3.9 | Daftar periksa paritas di Samsung, satu HP kelas bawah (Oppo, Vivo, Xiaomi, atau Infinix), dan satu tablet Android | Perangkat fisik | Semua butir lulus, atau tercatat lalu diperbaiki | 1 | 3.1–3.8 |
| 3.10 | Terima share di Android: intent filter gambar, PDF, dan teks (satu atau banyak file), saat app tertutup maupun terbuka; unggah ke Kotak Struk lalu buka layar konfirmasi; antrean native saat offline | `AndroidManifest.xml`, `MainActivity`, adapter | Share dari aplikasi bank, e-wallet, dan marketplace sampai ke layar konfirmasi | 1,5 | FS.2, FS.8 |

### FS — Pipeline "Bagikan ke Jatahku": server, web, dan Telegram (±21,5 hk)

Fase ini dikerjakan selama closed test Android berjalan. Hasilnya langsung bisa dipakai di web dan Telegram, sehingga data koreksi untuk belajar sudah terkumpul sebelum aplikasi rilis.

**Dipecah menjadi FS-1 dan FS-2 (26 Okt 2026).** Tabel di bawah adalah rencana awal. Rilis 1 (FS-1) mengerjakan FS.1 tanpa service terpisah, FS.2, FS.3, FS.4a dan bagian QRIS/transfer dari FS.4b, FS.5, FS.6, FS.7, sebagian FS.8 (`ProofCard` + banner), FS.9 (Web Share Target kini wajib, PDF di bot), dan FS.11. FS-2 menyusul: tagihan (sisa FS.4b), FS.4c marketplace, invoice umum, worker sebagai service terpisah, FS.10 notifikasi push, dan 6.7 email. Pembagian kode sesi dan status: `03-workflow.md` §6 dan `PROGRESS.md`; ADR-M17 di `02-adr.md`.

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| FS.1 | Kotak Struk: perluas `receipt_scans` (sumber, jenis dokumen, status, hash file, hash nomor referensi, kedaluwarsa, transaksi terkait) dan antrean tahan restart; worker OCR sebagai service systemd terpisah | `models.py`, `services/receipt_scan.py`, service baru | Item bertahan saat API di-restart; proses API tidak lagi memuat model OCR | 2,5 | F1 |
| FS.2 | API Kotak Struk: unggah gambar, PDF, dan teks (idempoten per id unggahan dan hash), daftar, detail, lewati; batas ukuran dan cek tipe dari isi file | `routes/receipts.py` (baru) | Unggahan ganda tidak membuat item baru; file berbahaya ditolak | 1,5 | FS.1 |
| FS.3 | PDF: teks dibaca langsung untuk PDF digital, halaman dirender untuk PDF pindaian; berjalan di proses terpisah dengan batas waktu dan halaman | `services/receipt_pdf.py` (baru); paket Python baru dipasang manual di venv | Invoice PDF terbaca tanpa OCR; PDF rusak tidak menjatuhkan worker | 1,5 | FS.1 |
| FS.4 | Klasifikasi dokumen dan parser baru: transfer bank, e-wallet/QRIS, tagihan dan isi ulang, invoice marketplace (barang, ongkir, biaya layanan, diskon), lengkap dengan status dan nomor referensi | `services/receipt_parser.py` dan modul per jenis | Korpus uji FS.5 lolos sesuai target | 6 | FS.5 |
| FS.5 | Korpus uji: ≥5 sampel tersamarkan per templat teratas (8 bank, 4 e-wallet, 4 marketplace) yang dikumpulkan dengan izin; disimpan sebagai baris OCR atau teks PDF, tanpa gambar asli | `app/tests/fixtures/` | Gerbang akurasi berjalan di CI | 2 | 1.4 |
| FS.6 | Deteksi duplikat dan bukan pengeluaran: hash, nomor referensi, transaksi mirip ±1 hari, invoice vs bukti bayar, top-up, transfer ke rekening sendiri, status gagal | `services/receipt_dedupe.py` (baru) | Skenario uji duplikat dan bukan pengeluaran lulus | 1,5 | FS.4 |
| FS.7 | Saran amplop dan belajar untuk jenis baru: kata kunci penerima, merchant, berita, dan jenis tagihan; feedback membawa jenis dokumen dan penerima/merchant; label per templat dengan aturan ≥2 user | `services/receipt_scan.py`, `user_envelope_keywords` | Struk kedua untuk penerima yang sama langsung disarankan ke amplop yang benar | 1 | FS.4 |
| FS.8 | UI Kotak Struk di web, dipakai juga di aplikasi: daftar dan layar konfirmasi yang memakai ulang kartu struk; ongkir dan biaya sebagai penambah; tombol "Bukan pengeluaran"; lencana jumlah (tanpa kuota scan, K4) | `ReceiptCard.jsx`, `receiptSplit.js`, halaman baru | Konfirmasi selesai dengan satu ketukan bila sarannya yakin | 2,5 | FS.2, FS.6 |
| FS.9 | Paritas kanal: tombol Struk di web menerima PDF dan drag-and-drop; bot Telegram menerima PDF dan dokumen gambar lewat Kotak Struk; opsional Web Share Target untuk PWA Android | `ReceiptInput.jsx`, `bot/receipt_cmd.py`, `bot/handlers.py`, `manifest.json` | Invoice PDF yang sama memberi hasil sama di web, bot, dan aplikasi | 1,5 | FS.2 |
| FS.10 | Notifikasi struk: push "siap dicatat" saat user tidak di aplikasi, pengingat harian digabung check-in, dan preferensinya | `services/notification_service.py`, scheduler | Push tiba; pengingat bisa dimatikan | 1 | 3.5 |
| FS.11 | Privasi: file asli dihapus setelah diproses, pratinjau ±2 KB, nomor rekening tidak disimpan; kebijakan privasi, DPIA, dan formulir toko diperbarui | worker, `privacy.html` | Tidak ada file asli tersisa di server setelah diproses | 0,5 | FS.1, 0.4 |

### F4 — Google Play (±3 hk + 14 hari closed test + review)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 4.1 | Buat aplikasi di Play Console dengan Play App Signing; listing bahasa Indonesia: deskripsi, ikon 512, feature graphic, screenshot HP dan tablet | Play Console | Semua kolom wajib terisi | 1 | 3.7 |
| 4.2 | Data safety, deklarasi fitur keuangan, rating konten, akses aplikasi (akun demo), pernyataan tanpa iklan | Play Console | Formulir lolos tanpa peringatan | 0,5 | 0.4, 1.2 |
| 4.3 | Internal test, lalu closed test ≥12 penguji selama 14 hari, dimulai dari build pertama yang layak; perbaikan dikirim ke track yang sama | Play Console | 14 hari terpenuhi tanpa crash berulang | 1 + 14 hari | 3.4 |
| 4.4 | Ajukan produksi, rilis bertahap 20% lalu 100%, pantau Android Vitals, aktifkan pembaruan dari dalam aplikasi | Play Console | Rilis 100% | 0,5 + review s.d. 7 hari | 4.3, 3.9, 3.10 |

### F5 — iOS dan billing (±15 hk)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 5.1 | `cap add ios` (SPM) dan commit; bundle ID; Associated Domains, Push, App Groups, Keychain Sharing; teks izin mikrofon, kamera, dan foto; privacy manifest; aplikasi universal iPhone + iPad dengan semua orientasi di iPad; safe area dan swipe-back | `mobile/ios/*` | Berjalan di iPhone dan iPad; paritas dasar lulus | 1,5 | F3 |
| 5.2 | Sign in with Apple: plugin, verifikasi token di server, penautan ke akun yang ada, pencabutan token saat hapus akun (TN3194) | `routes/auth.py`, adapter, `Login.jsx` | Daftar, masuk, dan hapus akun lewat Apple berfungsi | 1,5 | 1.2 |
| 5.3 | Universal Links (AASA) dan APNs lewat FCM | nginx, Xcode, adapter | Link bot membuka aplikasi; push tiba di iPhone | 1 | 3.4, 3.5 |
| 5.4 | Penyesuaian iOS: rekaman mp4, simpan file lewat share sheet dan Files, cetak, keyboard dan viewport, penyimpanan | adapter | Daftar periksa paritas iOS lulus | 1 | 5.1 |
| 5.5 | Billing: produk Pro sekali bayar di Play dan App Store, plugin billing, validasi di server, catatan hak per sumber, notifikasi refund, pulihkan pembelian, mode jualan `store` | `routes/payment.py` + modul baru, `Upgrade.jsx`, adapter | Beli, pulihkan, dan refund teruji di sandbox kedua toko | 4 | 1.6, F3 |
| 5.6 | CI iOS: Fastlane match, gym, dan pilot ke TestFlight dari tag | `.github/workflows/mobile-ios.yml`, `mobile/fastlane/` | Build TestFlight keluar otomatis | 1,5 | 0.6 |
| 5.7 | App Store Connect: label privasi, rating usia, catatan review dan akun demo, screenshot iPhone dan iPad 13 inci, ketersediaan Indonesia, pendaftaran Small Business Program; paritas di 1 iPhone dan 1 iPad; ajukan review | App Store Connect | Lolos review; rilis bertahap | 1,5 | 5.1–5.6, 5.8 |
| 5.8 | Share Extension iOS: terima gambar, PDF, dan teks; kecilkan gambar; unggah latar dengan token unggah-saja dari Keychain bersama; simpan di App Group saat offline; konfirmasi lewat push dan Kotak Struk | `mobile/ios/JatahkuShare/` | Share dari aplikasi bank di iPhone menghasilkan notifikasi "siap dicatat" | 3 | FS.2, FS.10, 5.3 |

### F6 — Fitur native v1.x (±11 hk, setelah rilis kedua toko)

| ID | Pekerjaan | File / komponen | Selesai bila | hk | Tergantung |
| --- | --- | --- | --- | --- | --- |
| 6.1 | Token widget baca-saja per perangkat dan endpoint `/widget/summary` (aman per hari, sisa, status) | route baru | Token bisa dicabut; respons kecil dan cepat | 1 | 1.1 |
| 6.2 | Widget Android (Glance): aman per hari dan tombol catat; ukuran kecil dan sedang; rapi di tablet | `mobile/android/.../widget/` | Benar setelah transaksi, pergantian hari, dan reboot | 3 | 6.1 |
| 6.3 | Widget iOS (WidgetKit + App Group) dan widget lock screen | `mobile/ios/JatahkuWidget/` | Setara dengan Android | 3 | 6.1 |
| 6.4 | Tombol aksi di notifikasi struk: "Catat ke \<amplop>" untuk item berkeyakinan tinggi tanpa peringatan duplikat | push, adapter, `services/notification_service.py` | Struk tercatat dari notifikasi tanpa membuka aplikasi, dan tetap bisa dibatalkan | 1,5 | FS.10 |
| 6.5 | Pintasan: quick action di ikon aplikasi dan App Intents iOS "Catat pengeluaran" | native | Catat lewat pintasan berhasil | 2 | F5 |
| 6.6 | Minta ulasan dari dalam aplikasi pada momen yang tepat | adapter | Muncul sesuai aturan toko | 0,5 | F5 |
| 6.7 | Opsional: terusan email invoice ke alamat khusus per user, masuk ke Kotak Struk | Exim, route baru | Invoice yang diteruskan muncul di Kotak Struk | 2 (di luar total) | FS.2 |

### Lampiran — daftar periksa paritas

Dijalankan per perangkat sebelum setiap rilis toko. Satu butir gagal berarti rilis ditahan.

- [ ] Login email/sandi, Google, dan Apple (iOS); tutup lalu buka lagi, sesi masih aktif
- [ ] Link login dari bot Telegram dan link reset sandi dari email membuka aplikasi dan langsung masuk
- [ ] Mode pesawat: catat lewat QuickAdd, multi-item, dan struk; matikan paksa app; buka lagi, antrean utuh; setelah online terkirim sekali, dan yang ditolak tetap tampil
- [ ] Rekam suara di QuickAdd dan chat; foto struk dari kamera dan galeri
- [ ] Bagikan bukti transfer, bukti bayar e-wallet, dan invoice PDF dari aplikasinya masing-masing, saat Jatahku tertutup dan terbuka; Android sampai ke layar konfirmasi, iOS memunculkan notifikasi "siap dicatat"
- [ ] Dokumen yang sama dibagikan dua kali tidak tercatat dua kali; transfer gagal tidak bisa dicatat; top-up disarankan "bukan pengeluaran"
- [ ] Simpan CSV, laporan PDF (simpan dan cetak), dan ekspor data; file terbuka di aplikasi lain
- [ ] Push pengingat langganan dan check-in tiba; ketukan membuka layar terkait; mematikan di Settings menghentikannya
- [ ] Tautan `t.me` membuka aplikasi Telegram; tautan luar membuka browser, bukan menimpa aplikasi
- [ ] Tombol kembali Android dan swipe iOS menutup sheet atau modal dulu, tidak keluar mendadak
- [ ] Tema terang dan gelap; status bar dan safe area benar di Android 16, iPhone dengan Dynamic Island, dan iPad
- [ ] Tablet: potret dan lanskap, layar terbagi atau jendela di iPad, keyboard fisik
- [ ] Kunci biometrik: aktif, gagal, dan cadangan PIN
- [ ] Mode jualan `none`: tidak ada teks atau tautan beli; mode `store`: beli dan pulihkan berhasil di sandbox
- [ ] Hapus akun dari aplikasi: data hilang dan sesi di perangkat lain terputus
- [ ] OTA: bundle baru terpasang setelah restart; bundle rusak di-rollback
- [ ] HP kelas bawah: waktu buka dingin dan pemakaian memori dicatat

## Risiko dan mitigasi

Risiko terbesar bukan teknis, melainkan perubahan API yang memutus aplikasi lama di tengah ritme rilis harian. Mitigasinya (header klien, versi minimum, cek OpenAPI di CI, dan OTA) dibangun di F1, sebelum ada aplikasi yang terpasang di HP user.

| Risiko | Dampak | Kemungkinan | Mitigasi |
| --- | --- | --- | --- |
| Perubahan API memutus aplikasi lama (puluhan PR per minggu dari beberapa agen) | Aplikasi gagal menyimpan atau crash bagi user yang belum update | Tinggi | ADR-M9: cek OpenAPI di CI, header `X-Jatahku-Client`, versi minimum, OTA |
| Beban review dan uji manual di pemilik produk | Jadwal molor | Tinggi | Fase kecil dengan gerbang jelas; CI otomatis; Android tetap bernilai walau iOS tertunda |
| Bukti transfer dan invoice tidak terbaca karena templat beragam atau berubah setelah update aplikasi bank | User mengetik manual; kepercayaan turun | Sedang | Korpus uji per templat di CI, parser label–nilai generik sebagai cadangan, pantauan akurasi per templat di Admin, belajar dari koreksi |
| Pencatatan ganda: invoice dan bukti bayar untuk pembelian yang sama, atau top-up e-wallet lalu belanja dengan e-wallet | Pengeluaran tercatat dua kali; saldo amplop salah | Sedang | Deteksi duplikat dan "bukan pengeluaran" (FS.6); konfirmasi selalu wajib |
| Data pihak ketiga di bukti transfer (nama dan rekening penerima) | Risiko UU PDP | Sedang | File asli dihapus setelah diproses; rekening tidak disimpan; DPIA mencakup fitur share |
| Lonjakan OCR karena share berisi banyak file | Antrean lama | Rendah–sedang | Worker terpisah, antrean tahan restart, pemantauan waktu tunggu; worker ditambah bila perlu |
| Share Extension iOS: batas memori ekstensi dan tidak bisa membuka aplikasi | Unggahan gagal atau alur membingungkan | Sedang | Ekstensi hanya mengunggah (tanpa OCR), gambar dikecilkan, sesi unggah latar, konfirmasi lewat push |
| File berbahaya (PDF atau gambar rusak) | Worker crash atau celah keamanan | Rendah | Batas ukuran dan halaman, cek tipe dari isi file, proses terpisah dengan batas waktu |
| Edge-to-edge Android 16 dan safe area | Konten tertutup status bar atau navigasi | Tinggi bila diabaikan | Variabel `--safe-area-inset-*` Capacitor 8; diuji di spike |
| Tampilan tablet janggal atau rusak saat rotasi | Ulasan buruk; bisa ditolak Apple bila rusak di iPad | Sedang | Android 16 memaksa rotasi di layar ≥600dp; pemeriksaan tablet di F1, spike, dan daftar paritas |
| Ditolak Apple 4.2 (dianggap website dikemas) | iOS mundur 1–3 minggu | Sedang | Push, biometrik, Sign in with Apple, Share Extension, offline sungguhan; catatan review dan akun demo; widget menyusul |
| Ditolak Apple 3.1.x karena urusan Pro | iOS mundur | Sedang bila tanpa IAP | Billing toko aktif sebelum rilis iOS |
| Closed test gagal (penguji aktif kurang dari 12 selama 14 hari) | Produksi Play mundur | Sedang | Rekrut 15–20 penguji sejak F0, pantau harian, mulai dari build pertama yang layak |
| Antrean offline hilang di iOS karena storage WebView dihapus sistem | Transaksi hilang, melanggar aturan antrean | Sedang | ADR-M11: penyimpanan native |
| Balapan rotasi refresh token antara app, widget, ekstensi, dan proses latar | User keluar paksa secara acak | Sedang | Masa tenggang rotasi beberapa detik; token terbatas terpisah untuk widget dan Share Extension |
| WebView usang di HP murah | Tampilan rusak atau lambat | Sedang | Uji di HP kelas bawah; `minSdk` 24 dari Capacitor 8; target build Vite dicek |
| Kunci upload hilang | Rilis terhambat | Rendah | Play App Signing (kunci upload bisa di-reset); cadangan di 2 tempat |
| Aturan toko atau regulasi berubah (putusan KPPU, tautan pembelian Apple, verifikasi developer 2027, PP PDP Jan 2027) | Perlu penyesuaian alur jualan atau privasi | Sedang | Mode jualan dari server; tinjauan kebijakan setiap kuartal |
| Belum terdaftar PSE | Teguran sampai pemblokiran | Rendah–sedang | Daftar di F0 |
| Capacitor 9 rilis di tengah proyek (perkiraan akhir Nov 2026) | Pekerjaan upgrade tambahan | Sedang | Mulai di Capacitor 8; naik ke 9 setelah stabil, sebelum rilis iOS bila aman |
| Rate limit per IP dan CGNAT operator seluler | Login atau scan ditolak padahal sah | Rendah | Rate limit per user untuk endpoint yang sudah login |

## Biaya dan sumber daya

Biaya uang di luar tenaga kerja kecil: US$124 di tahun pertama untuk dua akun toko, ditambah opsional US$9–14 per bulan bila OTA memakai layanan pihak ketiga. Biaya terbesar adalah tenaga, sekitar 76 hari kerja sampai kedua toko.

| Pos | Biaya | Kapan | Catatan |
| --- | --- | --- | --- |
| Google Play Console | US$25 | Sekali, F0 | – |
| Apple Developer Program | US$99 per tahun | F0 | Ditampilkan dalam rupiah saat mendaftar |
| Build iOS (macOS) | Rp0 selama repo publik | Per build | Runner standar GitHub gratis untuk repo publik; repo privat US$0,062 per menit macOS; alternatifnya Codemagic atau Mac sendiri |
| Pembaruan OTA | Rp0 bila di-host sendiri di VPS, atau US$9–14 per bulan | Bulanan | Capawesome Cloud Starter US$9 (1K MAU) atau Capgo Solo US$14 (2K MAU) |
| Push (FCM) | Rp0 | – | – |
| Worker OCR untuk share | Tidak ada biaya tambahan saat ini | – | Model OCR (±340 MB) pindah dari proses API ke worker; RAM VPS 4 GB dipantau saat share ramai |
| Fallback LLM struk | Rp0 selama mati; maksimal Rp100.000 per bulan bila dinyalakan | Bulanan | Plafon biaya sudah ada di konfigurasi |
| D-U-N-S (bila organisasi) | Gratis, proses hingga 30 hari | F0 | – |
| NIB dan TD PSE | Gratis | F0 | – |
| Perangkat uji | 1 iPhone, 1 iPad, 1 HP Samsung, 1 HP Android kelas bawah, 1 tablet Android | F2 | Bisa dipinjam |
| Komisi toko | 15% dari tiap penjualan Pro | Setelah billing aktif | Wajib mendaftar Small Business Program (Apple) dan tier 15% (Google) |
| Tenaga kerja | ±76 hari kerja sampai kedua toko; ±11 hari kerja untuk v1.x | – | Satu pengembang; lebih cepat bila jalur server/web dan jalur mobile dikerjakan paralel |

## Keputusan yang dibutuhkan dari pemilik produk

Dua belas keputusan ini dibutuhkan sebelum Fase 0 berjalan penuh. Masing-masing sudah diberi rekomendasi, jadi cukup disetujui atau diganti.

1. **Jenis akun developer.** Perorangan (cepat, tetapi nama pribadi tampil sebagai penjual di App Store dan Play mewajibkan closed test 14 hari) atau badan usaha (butuh badan hukum dan D-U-N-S, proses hingga 30 hari). Rekomendasi: badan usaha bila memang direncanakan dalam 6 bulan; selain itu perorangan.
2. **ID aplikasi.** Rekomendasi `com.jatahku.app`. ID ini tidak bisa diganti setelah rilis.
3. **Penjualan Pro di aplikasi.** Rekomendasi: rilis Android pertama tanpa jualan; Play Billing dan IAP Apple aktif sebelum iOS rilis. Harga di toko disamakan dengan web (Rp79.000) atau dinaikkan untuk menutup komisi 15%.
4. **Login di iOS.** Rekomendasi: tambah Sign in with Apple. Alternatifnya menyembunyikan login Google dan Telegram di iOS, yang merugikan user yang sudah memakainya.
5. **Hapus akun dan amplop bersama.** Bila anggota household menghapus akun, apakah transaksinya di amplop bersama dihapus atau dianonimkan? Rekomendasi: dianonimkan (pencatat menjadi "Mantan anggota", keterangan dihapus, nominal tetap) supaya saldo bersama tidak berubah, dan dicantumkan di kebijakan privasi.
6. **Layanan OTA.** Rekomendasi: host sendiri di VPS, tanpa biaya bulanan dan tanpa pihak ketiga baru. Alternatifnya Capawesome Cloud atau Capgo.
7. **Wilayah distribusi.** Rekomendasi: Indonesia saja di awal.
8. **Tablet.** Rekomendasi: iPad dan tablet Android didukung sejak rilis pertama (ADR-M15).
9. **Share: kuota dan bukan pengeluaran.** Diputuskan (K4, 26 Okt 2026): tidak ada kuota scan untuk share maupun input lain. Top-up e-wallet dan transfer ke rekening sendiri hanya ditawarkan sebagai "bukan pengeluaran", tidak pernah otomatis; user memutuskan.
10. **Share: fallback LLM untuk templat yang belum dikenal.** Rekomendasi: tetap mati di rilis pertama, lalu dinilai ulang dari data akurasi per templat.
11. **Perangkat dan penguji.** Siapa yang menyediakan 1 iPhone, 1 iPad, dan 3 perangkat Android, dan siapa 15–20 penguji closed test.
12. **Pemegang akun dan kunci.** Rekomendasi: pemilik produk memegang akun toko dan kunci upload, dengan cadangan di pengelola sandi dan di penyimpanan terenkripsi terpisah.

## Sumber

Fakta kode diambil dari repo [mtyatno/jatahku](https://github.com/mtyatno/jatahku) (main `31eb446`, 16 Okt 2026) dan dokumen proyek Jatahku; pelajaran Alurik dari "Roadmap & WBS Migrasi Mobile Alurik: Tauri → Capacitor" (fakta repo per 15 Okt 2026). Kebijakan toko dan regulasi dicek pada 16 Okt 2026, dan perlu dicek ulang saat Fase 0 karena berubah setiap tahun.

**Google Play dan Android**

- [Target API level requirements](https://support.google.com/googleplay/android-developer/answer/11926878)
- [App testing requirements for new personal developer accounts](https://support.google.com/googleplay/android-developer/answer/14151465)
- [Android developer verification FAQ](https://developer.android.com/developer-verification/guides/faq)
- [User choice billing](https://support.google.com/googleplay/android-developer/answer/13821247)
- [Payments policy](https://support.google.com/googleplay/android-developer/answer/9858738)
- [Account deletion requirements](https://support.google.com/googleplay/android-developer/answer/13327111)
- [Data safety form](https://support.google.com/googleplay/android-developer/answer/10787469)
- [Financial features declaration](https://support.google.com/googleplay/android-developer/answer/13849271)
- [Play App Signing dan APK universal bertanda tangan](https://support.google.com/googleplay/android-developer/answer/9842756)
- [Android 16 behavior changes](https://developer.android.google.cn/about/versions/16/behavior-changes-16?hl=en)
- [Putusan KPPU atas Google Play Billing berkekuatan hukum tetap](https://asean-competition.org/read-news-supreme-court-rejects-googles-cassation-kppu-decision-on-google-play-billing-becomes-legally-binding)

**Apple App Store**

- [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)
- [External purchase (StoreKit)](https://developer.apple.com/documentation/storekit/external-purchase)
- [App Store Small Business Program](https://developer.apple.com/app-store/small-business-program/)
- [Apple Developer Program enrollment](https://developer.apple.com/programs/enroll/)
- [Screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications)
- [TN3194: account deletion and Sign in with Apple tokens](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple)
- [NSExtensionContext open(\_:completionHandler:)](<https://developer.apple.com/documentation/foundation/nsextensioncontext/open(_:completionhandler:)>)

**Capacitor dan platform web**

- [Updating to Capacitor 8](https://capacitorjs.com/docs/updating/8-0)
- [Capacitor configuration](https://capacitorjs.com/docs/config)
- [Capacitor storage guide](https://capacitorjs.com/docs/guides/storage)
- [The road to Capacitor 9](https://ionic.io/blog/the-road-to-capacitor-9)
- [Ionic commercial products announcement](https://ionic.io/blog/?p=6282)
- [Google Identity Services: supported browsers](https://developers.google.com/identity/gsi/web/guides/supported-browsers)
- [Capgo social login plugin](https://github.com/Cap-go/capacitor-social-login)
- [Capawesome Live Update](https://capawesome.io/docs/sdks/capacitor/live-update/) dan [harga Capawesome](https://capawesome.io/pricing/)
- [PWABuilder iOS (diarsipkan)](https://github.com/pwa-builder/pwabuilder-ios)
- [Web Share Target: receive shared files](https://web.dev/patterns/files/receive-shared-files)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

**Regulasi Indonesia**

- [UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi](https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022)
- [Ringkasan PP 33/2026 (sumber sekunder)](https://legaltrans.id/insight/pp-33-2026-pelindungan-data-pribadi-bisnis)
- [Permenkominfo 5/2020 tentang PSE Lingkup Privat](https://jdih.komdigi.go.id/produk_hukum/view/id/759/t/peraturan+menteri+komunikasi+dan+informatika+nomor+5+tahun+2020)
- [Komdigi memperingatkan 7 PSE yang belum terdaftar (CNN Indonesia, 27 Sep 2026)](https://www.cnnindonesia.com/teknologi/20260927181303-213-1408809/belum-mendaftar-7-pse-terancam-diblokir-komdigi)
- [POJK 3/2024 tentang Inovasi Teknologi Sektor Keuangan](https://ojk.go.id/id/regulasi/Pages/POJK-3-2024-Penyelenggaraan-Inovasi-Teknologi-Sektor-Keuangan.aspx)
- [Kebijakan privasi Jatahku](https://jatahku.com/privacy.html)
