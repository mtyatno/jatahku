# Mobile — progres sesi

Diubah **di PR sesi itu sendiri** (lihat `03-workflow.md` §2). Status: belum · berjalan · jeda · review · selesai · terhambat. Kolom sama dengan tracker "Tracker Mobile Jatahku" di claude.ai.

Jalur: O = pemilik produk, A = Dev A (server & web), B = Dev B (mobile). Minggu dihitung dari tanggal mulai di tracker. Detail tiap paket (file, kriteria selesai, dependensi): `03-workflow.md` §6 dan `01-kajian.md` bagian WBS.

Paket FS dipecah menjadi **FS-1** (rilis 1) dan **FS-2** (menyusul, minggu belum ditetapkan) pada 26 Okt 2026; rinciannya di `03-workflow.md` §6. Paket FS-1 Bagian A tayang 28 Okt 2026 (PR #130, verifikasi versi yang tayang lulus) dan ditandai `selesai`, kecuali A68 (sisa `privacy.html`, DPIA, formulir toko). Bagian B (PWA dan web) selesai di kode di branch `feat/bagikan-ke-jatahku-web`, dalam PR yang menunggu merge: A58–A59 dan A66–A67 ditandai `review`, dan menjadi `selesai` bersama rilis yang menyalakan saklar `receipt_inbox` (fiturnya baru terlihat user setelah saklar menyala; menu Bagikan Android setelah PR kecil `share_target` di-merge); A29 (sampel marketplace) dan A60–A62 (sisa FS.8) ikut FS-2, dan A75–A77 serta B62–B67 bergantung pada FS.10 (FS-2, belum dijadwalkan). A28 (kalibrasi, A14 di rencana) `terhambat` menunggu sampel dari pemilik produk.

| Kode sesi | WBS | Jalur | Paket | Minggu | Status | Pemilik | PR | Mulai | Selesai |
|---|---|---|---|---|---|---|---|---|---|
| O01 | 0.1 | O | Setujui ADR-M1–M16; pindahkan kajian ke docs/mobile di repo; aturan mobile ke AGENTS.md | 1 | selesai | Pemilik produk + Claude | #100 | 2026-10-17 | 2026-10-17 |
| O02 | 0.2 | O | Daftar Google Play Console dan Apple Developer Program | 1 | belum |  |  |  | |
| O03 | 0.3 | O | Daftar PSE: NIB perorangan dan TD PSE lewat OSS | 1 | belum |  |  |  | |
| O04 | 0.5 | O | Rekrut 15–20 penguji closed test | 1 | belum |  |  |  | |
| O05–O07 | 0.4 | O | Kebijakan privasi, syarat, dan DPIA ringkas | 2 | belum |  |  |  | |
| O08 | 0.6 | O | Jalur build iOS (runner macOS atau Codemagic) dan sertifikat Apple | 2 | belum |  |  |  | |
| O09–O10 | 4.1 | O | Buat aplikasi di Play Console; listing, ikon, screenshot HP dan tablet | 5 | belum |  |  |  | |
| O11 | 4.2 | O | Data safety, deklarasi fitur keuangan, rating konten, akun demo | 5 | belum |  |  |  | |
| O12–O13 | 4.3 | O | Internal test lalu closed test ≥12 penguji × 14 hari; pantau harian | 6 | belum |  |  |  | |
| O14 | 4.4 | O | Ajukan produksi Play, rilis bertahap 20% → 100% | 10 | belum |  |  |  | |
| O15–O17 | 5.7 | O | App Store Connect: label privasi, rating usia, screenshot iPhone dan iPad, catatan review; ajukan review | 11 | belum |  |  |  | |
| A01–A03 | 1.3 | A | Header X-Jatahku-Client, GET /app/config, layar perlu update | 1 | selesai | Claude | #109 | 2026-10-17 | 2026-10-17 |
| A04–A06 | 1.4 | A | CI untuk PR: pytest, tes node, cek OpenAPI yang memutus | 1 | selesai | Dev A + Claude | #112 (uji merah: #114) | 2026-10-17 | 2026-10-17 |
| A78–A83 | 1.4b | A | `response_model` untuk endpoint yang dipakai aplikasi (Cek API bisa melihat field respons) | 3–4 | belum |  |  |  | |
| A07–A12 | 1.1 | A | Sesi per perangkat: auth_sessions, rotasi refresh, logout-all sungguhan | 2 | selesai | Pemilik produk + Claude | #116 | 2026-10-17 | 2026-10-17 |
| A13–A17 | 1.2 | A | Hapus akun sungguhan + halaman permintaan hapus di web | 2 | selesai | Pemilik produk + Claude | #119 | 2026-10-17 | 2026-10-17 |
| A18–A20 | 1.6 | A | Satu helper jualan untuk semua ajakan upgrade (web + bot) | 3 | belum |  |  |  | |
| A21–A22 | 1.7 | A | Izin eksplisit sebelum audio/foto dikirim ke Groq | 3 | belum |  |  |  | |
| A23–A24 | 1.8 | A | Amankan endpoint /auth/link/* | 3 | belum |  |  |  | |
| A25 | 1.9 | A | Bundel font lokal | 4 | belum |  |  |  | |
| A26–A27 | FS.5 | A | **FS-1** Korpus uji dan gerbang rilis: alat `kotak_corpus`, 6 sampel sintetis, tes gerbang (dilewati sampai A28) | 4 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A28 | FS.5 | A | **FS-1** Kalibrasi dengan sampel nyata (8 bank, 4 e-wallet): label per aplikasi dan titik yang diparkir — menunggu sampel dari pemilik produk; saklar `receipt_inbox` tetap mati sampai gerbang nyata lulus | 4 | terhambat | Pemilik produk (sampel) + Claude |  |  | |
| A30–A33 | FS.1 | A | **FS-1** Kotak Struk: perluas receipt_scans, antrean tahan restart, worker OCR di proses API (tanpa service terpisah) | 4 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A35–A37 | FS.2 | A | **FS-1** API Kotak Struk: unggah gambar/PDF/teks idempoten, daftar, lewati | 5 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A38–A40 | FS.3 | A | **FS-1** Pembaca PDF (teks langsung, render untuk pindaian), proses terpisah | 5 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A41–A44 | FS.4a | A | **FS-1** Klasifikasi dokumen + parser bukti transfer bank | 6 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A45–A46 | FS.4b | A | **FS-1** Parser e-wallet/QRIS (bagian QRIS/transfer dari FS.4b) | 6 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A53–A55 | FS.6 | A | **FS-1** Deteksi duplikat dan bukan pengeluaran | 7 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A56–A57 | FS.7 | A | **FS-1** Saran amplop dan belajar untuk jenis dokumen baru | 7 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A58–A59 | FS.8 | A | **FS-1** `ProofCard` dan banner "Bukti menunggu" di web (sebagian FS.8) — Bagian B, selesai di branch `feat/bagikan-ke-jatahku-web`, menunggu merge; `selesai` setelah saklar `receipt_inbox` menyala | 8 | review | Claude |  | 2026-10-28 | |
| A65 | FS.9 | A | **FS-1** Paritas kanal, sisi server: PDF di bot Telegram dan di `scan-receipt` | 9 | selesai | Claude | #130 | 2026-10-26 | 2026-10-28 |
| A66–A67 | FS.9 | A | **FS-1** Paritas kanal, sisi web: tombol PDF di form Catat; Web Share Target PWA (kini wajib) — Bagian B, selesai di branch `feat/bagikan-ke-jatahku-web`, menunggu merge; `share_target` di manifest menyusul di PR kecil saat saklar `receipt_inbox` menyala, lalu `selesai` | 9 | review | Claude |  | 2026-10-28 | |
| A68 | FS.11 | A | **FS-1** Privasi, sisi server: file asli dihapus, tanpa nomor rekening — sisi server tayang 2026-10-28 (#130); sisa: `privacy.html`, DPIA, dan formulir toko, sebelum saklar `receipt_inbox` menyala | 9 | berjalan | Claude | #130 | 2026-10-26 | |
| A69–A72 | 5.5a | A | Billing server: validasi Play dan App Store, hak per sumber, refund | 9 | belum |  |  |  | |
| A73–A74 | 6.1 | A | Token widget baca-saja + /widget/summary | 10 | belum |  |  |  | |
| A75–A77 | 6.4 | A | Tombol aksi "Catat ke amplop" di notifikasi struk | 10 | belum |  |  |  | |
| A29 | FS.5 | A | **FS-2** Korpus uji: sampel 4 marketplace | – | belum |  |  |  | |
| A34 | FS.1 | A | **FS-2** Worker OCR sebagai service terpisah (systemd), keluar dari proses API | – | belum |  |  |  | |
| A47–A48 | FS.4b | A | **FS-2** Parser tagihan dan isi ulang (sisa FS.4b) | – | belum |  |  |  | |
| A49–A52 | FS.4c | A | **FS-2** Parser invoice marketplace (barang, ongkir, biaya, diskon) | – | belum |  |  |  | |
| A60–A62 | FS.8 | A | **FS-2** UI Kotak Struk, sisanya: invoice per barang, ongkir dan biaya sebagai penambah | – | belum |  |  |  | |
| A63–A64 | FS.10 | A | **FS-2** Notifikasi struk siap dicatat + pengingat harian | – | belum |  |  |  | |
| – | FS.9 | A | **FS-2** Drag-and-drop PDF di desktop (sisa FS.9; kode sesi menyusul) | – | belum |  |  |  | |
| – | baru | A | **FS-2** Invoice umum: pembaca LLM umum sebagai pembaca terakhir di registri (belum diestimasi; kode sesi menyusul) | – | belum |  |  |  | |
| – | 6.7 | A | **FS-2** Opsional: terusan email invoice ke alamat khusus per user, masuk ke Kotak Struk (±2 hk, di luar total; kode sesi menyusul) | – | belum |  |  |  | |
| B01–B06 | 1.5 | B | Lapisan src/native/ versi web; pindahkan semua pemanggil | 1 | selesai | Pemilik produk + Claude | #120 | 2026-10-17 | 2026-10-17 |
| B07–B10 | 1.10 | B | Pemeriksaan tablet di web (md/lg, rotasi) | 1 | jeda | Pemilik produk + Claude | #121 | 2026-10-17 | |
| B11–B16 | 2.1 | B | Spike Capacitor di Android, iPhone, tablet: semua butir tersulit | 2 | belum |  |  |  | |
| B17–B19 | 3.1 | B | Scaffold mobile/: Capacitor 8, appId, android/ di-commit, safe area, tombol kembali | 3 | belum |  |  |  | |
| B20–B22 | 3.2 | B | Adapter capacitor.js: Keystore, antrean native, file, cetak, tautan luar | 3 | belum |  |  |  | |
| B23–B24 | 3.3 | B | Login Google native (multi client ID di server) | 3 | belum |  |  |  | |
| B25 | 3.4 | B | App Links: assetlinks.json, /auth/tg, /reset-password | 4 | belum |  |  |  | |
| B26–B29 | 3.5 | B | Push Android: Firebase, device_tokens, kanal push | 4 | belum |  |  |  | |
| B30 | 3.6 | B | Kunci biometrik opsional | 4 | belum |  |  |  | |
| B31–B32 | 3.7 | B | Penandatanganan, versi, workflow AAB + APK | 4 | belum |  |  |  | |
| B33–B35 | 3.8 | B | OTA: live update, kanal beta/stable, rollback | 5 | belum |  |  |  | |
| B36–B37 | 3.9 | B | Paritas Android di Samsung, HP kelas bawah, tablet | 5 | belum |  |  |  | |
| B38–B40 | 5.1 | B | iOS: cap add ios, capabilities, izin, privacy manifest, universal iPad | 5 | belum |  |  |  | |
| B41–B43 | 5.2 | B | Sign in with Apple + pencabutan token saat hapus akun | 6 | belum |  |  |  | |
| B44–B45 | 5.3 | B | Universal Links dan APNs lewat FCM | 6 | belum |  |  |  | |
| B46–B47 | 5.4 | B | Penyesuaian iOS: mp4, simpan file, cetak, keyboard | 6 | belum |  |  |  | |
| B48–B50 | 5.6 | B | CI iOS: Fastlane ke TestFlight | 7 | belum |  |  |  | |
| B51–B55 | BUF1 | B | Perbaikan temuan closed test | 7 | belum |  |  |  | |
| B56–B58 | 3.10 | B | Terima share di Android (gambar, PDF, teks) → Kotak Struk | 8 | belum |  |  |  | |
| B59–B61 | BUF2 | B | Perbaikan closed test + paritas share Android | 8 | belum |  |  |  | |
| B62–B67 | 5.8 | B | Share Extension iOS: unggah latar, App Group, konfirmasi lewat push | 9 | belum |  |  |  | |
| B68–B71 | 5.5b | B | Billing klien: tombol beli, pulihkan, sandbox kedua toko | 10 | belum |  |  |  | |
| B72–B74 | BUF3 | B | Perbaikan temuan review Apple | 11 | belum |  |  |  | |
| B75–B80 | 6.2 | B | Widget Android (Glance) | 12 | belum |  |  |  | |
| B81–B86 | 6.3 | B | Widget iOS (WidgetKit) + lock screen | 13 | belum |  |  |  | |
| B87–B90 | 6.5 | B | Pintasan dan App Intents "Catat pengeluaran" | 14 | belum |  |  |  | |
| B91 | 6.6 | B | Minta ulasan dari dalam aplikasi | 14 | belum |  |  |  | |
