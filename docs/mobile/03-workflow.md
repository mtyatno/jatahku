# Mobile — alur kerja development & jadwal sesi

**Status:** disetujui pemilik produk 16 Okt 2026. Dibuka oleh sesi O01 (17 Okt 2026). Pola kerjanya sama dengan `docs/ai-advisor/03-workflow.md`, supaya tim tidak memakai dua cara kerja.

**Tracker:** artifact "Tracker Mobile Jatahku" di claude.ai (privat; dibagikan pemilik produk ke anggota tim). Sumber kebenaran untuk Claude Code tetap `PROGRESS.md` di repo.

---

## 1. Repo adalah memori

Sesi Claude Code mulai dari nol, laptop dipakai bergantian, dan jeda bisa berhari-hari. Karena itu semua yang perlu diketahui sesi berikutnya ada di repo:

- `00-indeks.md` — peta dokumen dan fase sekarang.
- `01-kajian.md` — kajian lengkap: kondisi, kebutuhan, opsi, kesiapan toko, Pro, fitur Bagikan ke Jatahku, WBS, risiko.
- `02-adr.md` — ADR-M1 sampai M16.
- `03-workflow.md` — dokumen ini.
- `PROGRESS.md` — status tiap paket, diubah di PR sesi itu sendiri.
- `SESI-LOG.md` — catatan serah-terima; entri terakhir dibaca di awal setiap sesi.
- `AGENTS.md` bagian "Aplikasi mobile" — 11 aturan pengaman.

## 2. Satu sesi = satu paket = satu branch = satu PR

- **Sesi** = satu duduk Claude Code, 3–4 jam. Kode sesi `A07–A12` = paket itu butuh 6 sesi di jalur A. Paket multi-sesi tetap satu branch dan satu PR.
- **Branch** `mobile/<wbs>-<slug>` dari `main` terbaru, mis. `mobile/1.3-app-config`. **PR** berjudul `Mobile <wbs>: <nama paket>`, squash merge.
- **Jeda aman:** push branch, buka PR draft berawalan `WIP`, tulis "Status jeda" di deskripsi dan entri di `SESI-LOG.md`. Siapa pun (termasuk Claude Code di laptop lain) bisa melanjutkan.
- **Merge ke `main` = deploy produksi.** Setiap PR harus aman untuk web hari ini: fitur mobile disembunyikan lewat `/app/config` sampai siap; `mobile/` tidak ikut deploy web.
- **Review** oleh orang yang tidak menulisnya; kalau sendirian, buka sesi Claude Code terpisah khusus review.

## 3. Ritual pembuka & penutup

Perintah di `.claude/commands/` (dipakai di Claude Code mana pun yang membuka repo ini):

- `/sesi A01` — pembuka: cari paket untuk kode itu di `PROGRESS.md`, baca dokumen yang relevan dan entri terakhir `SESI-LOG.md`, buat atau lanjutkan branch, rangkum scope, lalu tunggu "lanjut".
- `/tutup-sesi` — penutup: tes, `PROGRESS.md`, entri `SESI-LOG.md`, commit, push, PR, dan satu baris status untuk tracker.

Setelah `/tutup-sesi`, ubah status paket di tracker claude.ai (satu menit).

## 4. Template PR

```
## Mobile <wbs> — <nama paket> (sesi <kode>)
ADR: M… · Kajian: 01-kajian.md §…
### Yang berubah
- …
### Cara mencoba
- …
### Tes
- unittest: … · node --test: … · build: ok · perangkat: …
### Catatan untuk reviewer
- Risiko / keputusan kecil / yang sengaja ditunda
### Checklist
- [ ] API hanya bertambah (tidak ada field/endpoint yang dihapus atau berubah arti)
- [ ] Tidak ada cek platform di komponen; perbedaan platform hanya di src/native/
- [ ] Fitur yang belum siap tersembunyi lewat /app/config
- [ ] PROGRESS.md & SESI-LOG.md diperbarui
- [ ] Migrasi? → langkah manual di deskripsi + label `migrasi`
```

## 5. Berjalan bersama AI Advisor

AI Advisor v2 sedang dikembangkan paralel (lihat `docs/ai-advisor/PROGRESS.md`). Aturannya:

- **File milik sesi AI Advisor yang belum selesai tidak disentuh sesi mobile.** Paket yang ditandai di kolom "Koordinasi" pada §6 baru dikerjakan setelah sesi AI Advisor pemilik file itu berstatus selesai, atau setelah disepakati di issue.
- **Paket mobile yang aman dikerjakan sekarang:** dokumen dan akun (O), `1.3` (route baru `/app/config`), `1.1`/`1.2` (auth & hapus akun), `1.8`, `1.9`, dan seluruh FS server (`FS.1`–`FS.7`), karena berkasnya terpisah dari `app/services/advisor/` dan `bot/advisor_cmd.py`.
- **Satu deploy dalam satu waktu** sudah dijamin antrean `deploy.yml`; tetap hindari merge dua PR yang sama-sama bermigrasi di hari yang sama.

## 6. Daftar paket & jadwal sesi

Asumsi: 8 sesi per developer per minggu; pemilik produk sesuai kebutuhan. Total 185 sesi (O 17, A 77, B 91), termasuk 17 sesi fitur native v1.x. Dengan dua developer paralel, Android tayang sekitar minggu ke-10 dan iOS minggu ke-12 (satu pengembang penuh waktu: minggu ke-14 dan 17, lihat `01-kajian.md`). Minggu 1 dimulai pada tanggal yang diisi di tracker.

| Kode sesi | WBS | Paket | Sesi | Minggu | Butuh | Selesai bila | Koordinasi AI Advisor |
|---|---|---|---|---|---|---|---|
| **Pemilik produk** | | | | | | | |
| O01 | 0.1 | Setujui ADR-M1–M16; pindahkan kajian ke docs/mobile di repo; aturan mobile ke AGENTS.md | 1 | 1 | – | ADR ada di repo dan dirujuk AGENTS.md |  |
| O02 | 0.2 | Daftar Google Play Console dan Apple Developer Program | 1 | 1 | Keputusan jenis akun | Kedua akun aktif |  |
| O03 | 0.3 | Daftar PSE: NIB perorangan dan TD PSE lewat OSS | 1 | 1 | – | Nomor TD PSE terbit |  |
| O04 | 0.5 | Rekrut 15–20 penguji closed test | 1 | 1 | – | ≥15 email Google penguji terkumpul |  |
| O05–O07 | 0.4 | Kebijakan privasi, syarat, dan DPIA ringkas | 3 | 2 | – | Halaman baru tayang |  |
| O08 | 0.6 | Jalur build iOS (runner macOS atau Codemagic) dan sertifikat Apple | 1 | 2 | 0.2 | Build iOS kosong dari CI |  |
| O09–O10 | 4.1 | Buat aplikasi di Play Console; listing, ikon, screenshot HP dan tablet | 2 | 5 | 3.7 | Semua kolom wajib terisi |  |
| O11 | 4.2 | Data safety, deklarasi fitur keuangan, rating konten, akun demo | 1 | 5 | 0.4, 1.2 | Formulir lolos tanpa peringatan |  |
| O12–O13 | 4.3 | Internal test lalu closed test ≥12 penguji × 14 hari; pantau harian | 2 | 6 | 3.9 | 14 hari terpenuhi |  |
| O14 | 4.4 | Ajukan produksi Play, rilis bertahap 20% → 100% | 1 | 10 | 4.3, 3.10 | Android tayang |  |
| O15–O17 | 5.7 | App Store Connect: label privasi, rating usia, screenshot iPhone dan iPad, catatan review; ajukan review | 3 | 11 | 5.1–5.6, 5.8 | iOS tayang |  |
| **Dev A · server & web** | | | | | | | |
| A01–A03 | 1.3 | Header X-Jatahku-Client, GET /app/config, layar perlu update | 3 | 1 | 0.1 | Web mengirim header; config ter-cache |  |
| A04–A06 | 1.4 | CI untuk PR: pytest, tes node, cek OpenAPI yang memutus | 3 | 1 | 0.1 | PR yang menghapus field gagal di CI | `.github/workflows/test.yml` (sudah ada dari AI Advisor S0) |
| A07–A12 | 1.1 | Sesi per perangkat: auth_sessions, rotasi refresh, logout-all sungguhan | 6 | 2 | 0.1 | Token lama ditolak; web tetap login |  |
| A13–A17 | 1.2 | Hapus akun sungguhan + halaman permintaan hapus di web | 5 | 2 | 1.1 | Data terhapus; sesi tercabut |  |
| A18–A20 | 1.6 | Satu helper jualan untuk semua ajakan upgrade (web + bot) | 3 | 3 | 1.3 | Mode none: tanpa teks beli | `bot/*` (AI Advisor S9/S17) |
| A21–A22 | 1.7 | Izin eksplisit sebelum audio/foto dikirim ke Groq | 2 | 3 | 0.4 | Tanpa izin, data tidak dikirim | `ChatPanel.jsx` |
| A23–A24 | 1.8 | Amankan endpoint /auth/link/* | 2 | 3 | – | Panggilan tanpa secret ditolak |  |
| A25 | 1.9 | Bundel font lokal | 1 | 4 | – | Tampilan sama saat offline |  |
| A26–A29 | FS.5 | Korpus uji: sampel tersamarkan 8 bank, 4 e-wallet, 4 marketplace | 4 | 4 | 1.4 | Gerbang akurasi jalan di CI |  |
| A30–A34 | FS.1 | Kotak Struk: perluas receipt_scans, antrean tahan restart, worker OCR terpisah | 5 | 4 | F1 | Item bertahan saat restart |  |
| A35–A37 | FS.2 | API Kotak Struk: unggah gambar/PDF/teks idempoten, daftar, lewati | 3 | 5 | FS.1 | Unggahan ganda tidak membuat item baru |  |
| A38–A40 | FS.3 | Pembaca PDF (teks langsung, render untuk pindaian), proses terpisah | 3 | 5 | FS.1 | PDF rusak tidak menjatuhkan worker |  |
| A41–A44 | FS.4a | Klasifikasi dokumen + parser bukti transfer bank | 4 | 6 | FS.5 | Sampel bank lolos target |  |
| A45–A48 | FS.4b | Parser e-wallet/QRIS dan tagihan/isi ulang | 4 | 6 | FS.4a | Sampel e-wallet dan tagihan lolos |  |
| A49–A52 | FS.4c | Parser invoice marketplace (barang, ongkir, biaya, diskon) | 4 | 7 | FS.4a | Sampel invoice lolos |  |
| A53–A55 | FS.6 | Deteksi duplikat dan bukan pengeluaran | 3 | 7 | FS.4a | Skenario uji lulus |  |
| A56–A57 | FS.7 | Saran amplop dan belajar untuk jenis dokumen baru | 2 | 7 | FS.4a | Penerima yang sama langsung disarankan |  |
| A58–A62 | FS.8 | UI Kotak Struk dan layar konfirmasi (dipakai web dan app) | 5 | 8 | FS.2, FS.6 | Konfirmasi satu ketukan bila yakin |  |
| A63–A64 | FS.10 | Notifikasi struk siap dicatat + pengingat harian | 2 | 8 | 3.5 | Push tiba; bisa dimatikan | `notification_service.py` (AI Advisor S16) |
| A65–A67 | FS.9 | Paritas kanal: PDF dan drag-and-drop di web, PDF di bot Telegram | 3 | 9 | FS.2 | Hasil sama di web, bot, app | `bot/*` (AI Advisor S17) |
| A68 | FS.11 | Privasi: hapus file asli, tanpa nomor rekening; formulir toko | 1 | 9 | FS.1, 0.4 | Tidak ada file asli tersisa |  |
| A69–A72 | 5.5a | Billing server: validasi Play dan App Store, hak per sumber, refund | 4 | 9 | 1.6 | Validasi sandbox lulus |  |
| A73–A74 | 6.1 | Token widget baca-saja + /widget/summary | 2 | 10 | 1.1 | Token bisa dicabut |  |
| A75–A77 | 6.4 | Tombol aksi "Catat ke amplop" di notifikasi struk | 3 | 10 | FS.10 | Tercatat dari notifikasi, bisa dibatalkan |  |
| **Dev B · mobile** | | | | | | | |
| B01–B06 | 1.5 | Lapisan src/native/ versi web; pindahkan semua pemanggil | 6 | 1 | 1.3 | Perilaku web identik | `lib/api.js`, `ChatPanel.jsx` (AI Advisor S8/S11) |
| B07–B10 | 1.10 | Pemeriksaan tablet di web (md/lg, rotasi) | 4 | 1 | – | Tangkapan layar tablet diperiksa | `Layout.jsx`, `Dashboard.jsx` (AI Advisor S6–S8) |
| B11–B16 | 2.1 | Spike Capacitor di Android, iPhone, tablet: semua butir tersulit | 6 | 2 | 0.2, 0.6 | Laporan lulus/gagal per butir |  |
| B17–B19 | 3.1 | Scaffold mobile/: Capacitor 8, appId, android/ di-commit, safe area, tombol kembali | 3 | 3 | F1, 2.1 | App login ke produksi |  |
| B20–B22 | 3.2 | Adapter capacitor.js: Keystore, antrean native, file, cetak, tautan luar | 3 | 3 | 3.1 | Ekspor dan cetak jalan |  |
| B23–B24 | 3.3 | Login Google native (multi client ID di server) | 2 | 3 | 3.2 | Login Google di Android |  |
| B25 | 3.4 | App Links: assetlinks.json, /auth/tg, /reset-password | 1 | 4 | 3.1 | Link bot membuka app |  |
| B26–B29 | 3.5 | Push Android: Firebase, device_tokens, kanal push | 4 | 4 | 3.2 | Pengingat uji tiba |  |
| B30 | 3.6 | Kunci biometrik opsional | 1 | 4 | 3.2 | Tidak terkunci saat sensor gagal |  |
| B31–B32 | 3.7 | Penandatanganan, versi, workflow AAB + APK | 2 | 4 | 0.2 | Build bertanda tangan dari CI |  |
| B33–B35 | 3.8 | OTA: live update, kanal beta/stable, rollback | 3 | 5 | 1.3, 3.1 | Rollback teruji |  |
| B36–B37 | 3.9 | Paritas Android di Samsung, HP kelas bawah, tablet | 2 | 5 | 3.1–3.8 | Semua butir lulus |  |
| B38–B40 | 5.1 | iOS: cap add ios, capabilities, izin, privacy manifest, universal iPad | 3 | 5 | F3 | Jalan di iPhone dan iPad |  |
| B41–B43 | 5.2 | Sign in with Apple + pencabutan token saat hapus akun | 3 | 6 | 1.2 | Daftar, masuk, hapus lewat Apple |  |
| B44–B45 | 5.3 | Universal Links dan APNs lewat FCM | 2 | 6 | 3.4, 3.5 | Push tiba di iPhone |  |
| B46–B47 | 5.4 | Penyesuaian iOS: mp4, simpan file, cetak, keyboard | 2 | 6 | 5.1 | Paritas iOS lulus |  |
| B48–B50 | 5.6 | CI iOS: Fastlane ke TestFlight | 3 | 7 | 0.6 | Build TestFlight otomatis |  |
| B51–B55 | BUF1 | Perbaikan temuan closed test | 5 | 7 | 4.3 | Tidak ada crash berulang |  |
| B56–B58 | 3.10 | Terima share di Android (gambar, PDF, teks) → Kotak Struk | 3 | 8 | FS.2, FS.8 | Share sampai ke layar konfirmasi |  |
| B59–B61 | BUF2 | Perbaikan closed test + paritas share Android | 3 | 8 | 3.10 | Paritas share lulus |  |
| B62–B67 | 5.8 | Share Extension iOS: unggah latar, App Group, konfirmasi lewat push | 6 | 9 | FS.2, FS.10, 5.3 | Notifikasi siap dicatat tiba |  |
| B68–B71 | 5.5b | Billing klien: tombol beli, pulihkan, sandbox kedua toko | 4 | 10 | 5.5a | Beli, pulihkan, refund teruji |  |
| B72–B74 | BUF3 | Perbaikan temuan review Apple | 3 | 11 | 5.7 | Lolos review |  |
| B75–B80 | 6.2 | Widget Android (Glance) | 6 | 12 | 6.1 | Benar setelah reboot dan ganti hari |  |
| B81–B86 | 6.3 | Widget iOS (WidgetKit) + lock screen | 6 | 13 | 6.1 | Setara Android |  |
| B87–B90 | 6.5 | Pintasan dan App Intents "Catat pengeluaran" | 4 | 14 | F5 | Catat lewat pintasan |  |
| B91 | 6.6 | Minta ulasan dari dalam aplikasi | 1 | 14 | F5 | Sesuai aturan toko |  |

**Gerbang** (detail di `01-kajian.md` bagian Roadmap): G0 rencana disetujui (minggu 1) · G1 fondasi tayang di web + spike lulus (3) · G2 closed test dimulai (5) · G3 Kotak Struk tayang di web dan Telegram (9) · G4 Android tayang (10) · G5 iOS tayang (12). Fase berikutnya hanya dimulai setelah gerbangnya lulus.

**Urutan yang tidak boleh ditukar:** 1.3 → 1.5 → 3.1; 2.1 (spike) sebelum 3.1; F3 → closed test; FS.2 + FS.8 → 3.10 → produksi Play; 5.5a → 5.5b → review Apple.

## 7. Ritme tim

- **Senin, 30 menit:** buka tracker, sepakati paket minggu ini per jalur, bereskan yang terhambat, cek bentrok dengan AI Advisor.
- **Akhir setiap sesi:** `/tutup-sesi` lalu update tracker.
- **Di setiap gerbang:** pemilik produk mengecek syarat lulus dan mengubah status gerbang di tracker.
