# Mobile — progres sesi

Diubah **di PR sesi itu sendiri** (lihat `03-workflow.md` §2). Status: belum · berjalan · jeda · review · selesai · terhambat. Kolom sama dengan tracker "Tracker Mobile Jatahku" di claude.ai.

Jalur: O = pemilik produk, A = Dev A (server & web), B = Dev B (mobile). Minggu dihitung dari tanggal mulai di tracker. Detail tiap paket (file, kriteria selesai, dependensi): `03-workflow.md` §6 dan `01-kajian.md` bagian WBS.

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
| A07–A12 | 1.1 | A | Sesi per perangkat: auth_sessions, rotasi refresh, logout-all sungguhan | 2 | review | Pemilik produk + Claude | #116 | 2026-10-17 | |
| A13–A17 | 1.2 | A | Hapus akun sungguhan + halaman permintaan hapus di web | 2 | belum |  |  |  | |
| A18–A20 | 1.6 | A | Satu helper jualan untuk semua ajakan upgrade (web + bot) | 3 | belum |  |  |  | |
| A21–A22 | 1.7 | A | Izin eksplisit sebelum audio/foto dikirim ke Groq | 3 | belum |  |  |  | |
| A23–A24 | 1.8 | A | Amankan endpoint /auth/link/* | 3 | belum |  |  |  | |
| A25 | 1.9 | A | Bundel font lokal | 4 | belum |  |  |  | |
| A26–A29 | FS.5 | A | Korpus uji: sampel tersamarkan 8 bank, 4 e-wallet, 4 marketplace | 4 | belum |  |  |  | |
| A30–A34 | FS.1 | A | Kotak Struk: perluas receipt_scans, antrean tahan restart, worker OCR terpisah | 4 | belum |  |  |  | |
| A35–A37 | FS.2 | A | API Kotak Struk: unggah gambar/PDF/teks idempoten, daftar, lewati | 5 | belum |  |  |  | |
| A38–A40 | FS.3 | A | Pembaca PDF (teks langsung, render untuk pindaian), proses terpisah | 5 | belum |  |  |  | |
| A41–A44 | FS.4a | A | Klasifikasi dokumen + parser bukti transfer bank | 6 | belum |  |  |  | |
| A45–A48 | FS.4b | A | Parser e-wallet/QRIS dan tagihan/isi ulang | 6 | belum |  |  |  | |
| A49–A52 | FS.4c | A | Parser invoice marketplace (barang, ongkir, biaya, diskon) | 7 | belum |  |  |  | |
| A53–A55 | FS.6 | A | Deteksi duplikat dan bukan pengeluaran | 7 | belum |  |  |  | |
| A56–A57 | FS.7 | A | Saran amplop dan belajar untuk jenis dokumen baru | 7 | belum |  |  |  | |
| A58–A62 | FS.8 | A | UI Kotak Struk dan layar konfirmasi (dipakai web dan app) | 8 | belum |  |  |  | |
| A63–A64 | FS.10 | A | Notifikasi struk siap dicatat + pengingat harian | 8 | belum |  |  |  | |
| A65–A67 | FS.9 | A | Paritas kanal: PDF dan drag-and-drop di web, PDF di bot Telegram | 9 | belum |  |  |  | |
| A68 | FS.11 | A | Privasi: hapus file asli, tanpa nomor rekening; formulir toko | 9 | belum |  |  |  | |
| A69–A72 | 5.5a | A | Billing server: validasi Play dan App Store, hak per sumber, refund | 9 | belum |  |  |  | |
| A73–A74 | 6.1 | A | Token widget baca-saja + /widget/summary | 10 | belum |  |  |  | |
| A75–A77 | 6.4 | A | Tombol aksi "Catat ke amplop" di notifikasi struk | 10 | belum |  |  |  | |
| B01–B06 | 1.5 | B | Lapisan src/native/ versi web; pindahkan semua pemanggil | 1 | review | Pemilik produk + Claude | #120 | 2026-10-17 | |
| B07–B10 | 1.10 | B | Pemeriksaan tablet di web (md/lg, rotasi) | 1 | belum |  |  |  | |
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
