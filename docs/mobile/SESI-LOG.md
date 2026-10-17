# Mobile — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · paket · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

---

## B01–B06 · 1.5 Lapisan src/native/ versi web · 2026-10-17 · pemilik produk + Claude

**Selesai** (paket selesai dalam satu sesi; status review, PR #120)
- `frontend/src/native/index.js` (antarmuka, didokumentasikan di kepala file) + `web.js` (`createWebNative`, global browser bisa disuntik untuk tes) + `web.test.js` (16 tes). Isi: `init`, `platform` (`apiUrl` dari build: prod `https://api.jatahku.com`, dev `/api`), `tokens`, `queue` (store, `withAuth`, `requestBackgroundSync`, `onBackgroundSynced`), `files.save/share`, `print.pdf`, `openExternal`, `externalLinkProps(url, onClick, {appUrl})`, `onInstallPrompt`.
- Pemanggil dipindah: `api.js` (alamat API + token; `api.token` jadi getter), `Upgrade.jsx` dan `Settings.jsx` (dua `fetch` manual → `api.request` FormData; tebakan hostname hilang), `ExportButtons.jsx`, `Settings.jsx` (unduh data, tautan Telegram), `ChatPanel.jsx`, `TelegramPrompt.jsx`, `PWAPrompt.jsx`, `main.jsx` (render setelah `native.init()`), `offlineQueue.js`, `OfflineQueueCenter.jsx`.
- `.github/workflows/test.yml`: `node --test` juga menjalankan `src/native/*.test.js`.
- Tes: unittest 1064 OK, node 331 lulus, build ok. Chromium + API tiruan: token lama terbaca, SW terdaftar, header `Bearer` + `X-Jatahku-Client` di semua request, unggah foto profil, unduh data, CSV, Simpan PDF, Print.

**Digantung (di luar scope, dicatat)**
- Tombol toko di `UpdateRequired.jsx` dan tautan di `Admin.jsx` masih `<a target=_blank>` biasa → pakai `native.externalLinkProps` (3.2).
- `navigator.clipboard` (Settings, Upgrade, Admin) belum lewat native; cek di WebView saat spike 2.1.
- Pratinjau PDF di `ExportButtons` memakai `<iframe>` blob — kemungkinan tidak tampil di WebView Android (spike 2.1 / 3.2; `print.pdf` sudah menerima `url`).
- Preferensi UI (tema, tab, prompt Telegram, `pwa-dismissed`) tetap di `localStorage`: bukan rahasia, tidak dipindah.
- Gerbang "perlu update" masih di `Layout`, belum di `App.jsx`.
- Antrean offline dan tautan `t.me` belum diuji di browser (tes unit saja).

**Jebakan**
- `vite preview` melayani `dist/index.html` hasil build; kalau `git checkout -- frontend/dist` dijalankan sebelum preview, halaman kosong (aset lama). Kembalikan `dist/` setelah selesai menguji.
- Container cloud baru belum punya dependensi Python: `pip install -r requirements.txt -r requirements-test.txt` sebelum unittest (tanpa itu 65 modul gagal import, juga di main).
- `externalLinkProps` menjalankan `onClick` pemanggil dulu; bila pemanggil `preventDefault()` (mis. kode Telegram kedaluwarsa), tautan tidak dibuka. Di `ChatPanel`, klik link ditangani `externalLinkProps`, `openLink` hanya membuka tautan luar bila dipanggil tanpa event (jangan buka dua kali).

**Keputusan kecil**
- Antarmuka token sinkron + `init()` async sebelum render (aplikasi memuat Keystore di `init`, lalu cache di memori), supaya `useAuth` tidak perlu diubah.
- Item antrean web tetap membawa token (service worker butuh); di aplikasi `queue.withAuth` tidak menambahkan token (aturan #6).
- `index.js` sekarang selalu memakai web; 3.2 memilih `capacitor.js` dari `CLIENT.platform` (build), bukan deteksi runtime.

**Cara melanjutkan**
- Review dan merge #120, lalu `/cek-deploy 120`. Setelah tayang: coba login tetap bertahan, ganti foto profil, bukti bayar di Upgrade.
- Paket berikutnya jalur B: `/sesi B07` (1.10, pemeriksaan tablet). 3.1 butuh 2.1 (spike) dan F1.

---

## A13 · 1.2 Hapus akun sungguhan · 2026-10-17 · pemilik produk + Claude

**Selesai** (kriteria paket terpenuhi dalam 1 dari 5 sesi; status review)
- `app/services/account_deletion.py`: hapus permanen user, `auth_sessions` (semua perangkat keluar), notifikasi, preferensi, streak, kata kunci amplop, scan struk, suara belajar struk, order pembayaran, transaksi tertunda; file `/uploads/...` (foto profil, bukti bayar) dihapus di background setelah commit.
- Household hanya berisi user → dihapus utuh (amplop, transaksi, pemasukan, alokasi, langganan, target, snapshot, cocokkan saldo, grup). Household bersama → amplop pribadi user dihapus; transaksi/cocokkan saldo di amplop bersama pindah ke user "Mantan anggota" (keterangan diganti, nominal tetap); pemasukan dipangkas ke jumlah yang masih teralokasi (0 → dihapus); owner pindah ke anggota tertua (`household_members.created_at`).
- "Mantan anggota": satu baris `users` bersama, id tetap `00000000-0000-4000-8000-00000000d31e`, email `deleted_mantan-anggota@jatahku.com` (dilewati scheduler/admin lewat konvensi `deleted_`), tanpa sandi, bukan anggota household; tidak bisa dihapus.
- `DELETE /user/account` memakai layanan ini (respons tetap `{"status": "deleted"}`) + email "akun sudah dihapus".
- Endpoint publik baru (rate limit 3/5 per menit): `POST /user/account/deletion-request` (email → link `jatahku.com/hapus-akun?token=…`, jawaban seragam) dan `POST /user/account/deletion-confirm` (token Redis `acctdel:*` sekali pakai, 1 jam).
- Web: halaman `/hapus-akun` tanpa login (`pages/HapusAkun.jsx`: form email → cek email → konfirmasi ketik "HAPUS" → selesai); teks di Pengaturan diperbarui. Nginx tidak perlu diubah (semua path sudah jatuh ke SPA, dicek dengan curl).
- Tes: `app/tests/test_account_deletion.py` (12; SQLite dengan `PRAGMA foreign_keys=ON`, terbukti menangkap urutan hapus yang salah lewat mutasi). Dicoba di Chromium dengan API tiruan: keempat tampilan halaman.
- `PROGRESS.md`: 1.1 selesai (#116).

**Digantung**
- Akun yang "dihapus" cara lama (email `deleted_<uuid>@jatahku.com`, data masih ada) belum dibersihkan: perlu skrip sekali jalan yang memanggil `account_deletion.delete_account` untuk tiap akun itu (di VPS, dengan cadangan DB dulu).
- URL hapus akun (`https://jatahku.com/hapus-akun`) perlu dicantumkan di kebijakan privasi (0.4) dan formulir Play (4.2).
- Pencabutan token Sign in with Apple saat hapus akun → paket 5.2 (panggil dari `account_deletion.delete_account`).
- Sisa data di Redis (cache advisor, kunci per user) tidak dihapus; semuanya ber-TTL.

**Jebakan**
- SQLite tidak menegakkan FK secara bawaan; tanpa pragma, urutan hapus yang salah lolos di tes tapi gagal di Postgres. Banyak FK ke `users`/`envelopes` tanpa CASCADE, jadi tabel baru yang menunjuk ke `users` wajib ditambahkan ke `account_deletion.py`.
- `npm run build` mengubah `frontend/dist/index.html` yang ter-track; kembalikan sebelum commit.

**Keputusan kecil** (perlu dikonfirmasi pemilik produk saat review)
- Order pembayaran ikut dihapus (beserta bukti transfer). Bila perlu disimpan untuk pembukuan, ganti jadi anonimisasi ke "Mantan anggota".
- Admin akan melihat satu user tambahan "Mantan anggota" setelah anggota household bersama pertama menghapus akun.
- Link email hanya membuka halaman; penghapusan butuh POST + ketik "HAPUS", jadi pemindai link email tidak bisa memicu hapus.
- Tidak perlu migrasi.

**Cara melanjutkan**
- Review PR di sesi terpisah; setelah merge, `/cek-deploy <nomor PR>` lalu coba `/hapus-akun` di produksi dengan akun uji.
- Paket berikut yang terbuka di jalur A: `/sesi A18` (1.6 helper jualan), `/sesi A23` (1.8), atau `/sesi A78` (1.4b). Jalur B: 5.2 kini tidak lagi menunggu 1.2.

---

## A07 · 1.1 Sesi per perangkat · 2026-10-17 · pemilik produk + Claude

**Selesai** (kriteria paket terpenuhi dalam 1 dari 6 sesi; status review)
- Tabel `auth_sessions` + `users.tokens_revoked_at`, migrasi `d3b8f1a6c2e9` (down: `c5e9a2d7f4b1`). Model `AuthSession` di `models.py`; logika di `app/services/auth_sessions.py`.
- Access token membawa `sid`, refresh token `sid` + `jti`. `deps.get_current_user` menolak sesi yang dicabut/kedaluwarsa; dependency baru `get_current_session_id`.
- `/auth/refresh` merotasi `jti`; `jti` sebelumnya diterima `REFRESH_GRACE` = 30 detik (dua tab), selain itu = dipakai ulang → sesi dicabut (`revoked_reason="reuse"`).
- Token lama tanpa sid: access diterima sampai kedaluwarsa; refresh ditukar sekali jadi sesi (`legacy_token_hash` mencegah tukar ulang); keduanya ditolak setelah logout-all.
- Endpoint baru: `POST /auth/logout` (refresh token di body atau access token; selalu 200), `GET /auth/sessions`, `DELETE /auth/sessions/{id}`. `/user/logout-all` mencabut semua sesi (respons lama tetap).
- Reset sandi: cabut semua lalu login di sini. Ganti sandi: cabut perangkat lain. `/auth/link/claim-telegram` juga lewat `start_session`.
- Web: `api.logout()` memanggil `/auth/logout` (keepalive, tidak ditunggu) lewat `src/lib/authLogout.js`.
- Tes: `app/tests/test_auth_sessions.py` (18, SQLite + httpx ASGITransport), `frontend/src/lib/authLogout.test.js`.

**Digantung**
- UI daftar perangkat di Settings (endpoint sudah ada) — belum diminta; bisa diambil sisa jatah A08–A12 atau paket 1.5/3.x.
- Hapus akun belum mencabut sesi → paket 1.2 (`auth_sessions.revoke_all`).
- Kode token lama (cabang tanpa sid di `deps.py`, `_upgrade_legacy`, kolom `legacy_token_hash`) bisa dibuang ≥30 hari setelah deploy.

**Jebakan**
- **Migrasi wajib manual saat merge**: `users.tokens_revoked_at` dipetakan model, jadi semua query User 500 (termasuk login) sampai `alembic upgrade head` jalan. `deploy.sh` hanya memperingatkan.
- `bcrypt` tidak di-pin di `requirements.txt`; instal baru dapat bcrypt 5 yang patah dengan passlib 1.7.4 (`hash_password` ValueError). Di tes hash dipalsukan. Produksi patah bila venv dipasang ulang — perlu pin ke versi yang terpasang di VPS (mis. `bcrypt<5`; di luar scope, belum dikerjakan).
- Tes SQLite: bila `asyncSetUp` gagal sebelum `engine.dispose`, thread aiosqlite membuat proses menggantung — dispose didaftarkan via `addAsyncCleanup` sejak awal.
- `frontend/dist/index.html` ter-track; kembalikan setelah `npm run build`.

**Keputusan kecil**
- Masa tenggang 30 detik (kajian: "beberapa detik"; jaringan HP lambat). Sesi geser: setiap refresh memperpanjang 30 hari.
- `jti` disimpan apa adanya (tanpa hash): tidak berguna tanpa `JWT_SECRET`. IP tidak dicatat (privasi); hanya `X-Jatahku-Client` dan user agent.
- Satu commit per login: `_tokens()` meng-commit perubahan user + sesi sekaligus.
- FK `auth_sessions.user_id` `ON DELETE CASCADE`, jadi `merge_users` tidak perlu diubah.

**Cara melanjutkan**
- Review PR di sesi terpisah; saat merge jalankan migrasi (langkah di deskripsi PR).
- Paket berikut yang terbuka: `/sesi A13` (1.2, butuh 1.1 merge).

---

## A05 · 1.4 penutupan: bukti Cek API merah · 2026-10-17 · pemilik produk + Claude

**Selesai**
- PR uji #114 (draft, `JANGAN MERGE`) menghapus `emoji` dari `EnvelopeResponse`. Workflow **Cek API** merah di CI sungguhan: langkah "Bandingkan OpenAPI dengan base" exit 1, anotasi "PR ini memutus API untuk aplikasi lama" ([run](https://github.com/mtyatno/jatahku/actions/runs/39044816908/job/117431333178)). #114 ditutup tanpa merge. Kriteria selesai 1.4 terpenuhi.
- Paket baru **1.4b** (A78–A83, minggu 3–4): `response_model` untuk endpoint yang dipakai aplikasi, karena 119 dari 145 respons 2xx belum punya skema sehingga Cek API tidak melihat field respons yang hilang. Kode A78–A83 dipilih supaya kode sesi A lain tidak bergeser.

**Digantung**
- Branch `mobile/1.4-uji-cek-api` belum terhapus di GitHub (proxy sesi menolak hapus ref). Hapus lewat tombol "Delete branch" di #114.
- Menjadikan "Cek API" required check di `main`: pengaturan pemilik repo di GitHub (Settings → Branches/Rules). Beri tahu tim AI Advisor dulu; perubahan memutus yang disengaja lewat label `api-memutus`.

**Cara melanjutkan**
- A06 tidak perlu dipakai untuk 1.4; jalur A lanjut ke `/sesi A07` (1.1 sesi per perangkat) atau 1.4b (`/sesi A78`) sebelum G2.

---

## A04 · 1.4 CI untuk PR (cek OpenAPI) · 2026-10-17 · Dev A + Claude

**Selesai**
- `app/scripts/openapi_cek.py`: ekspor OpenAPI (`app.openapi()`, tanpa DB) dari commit dasar lewat `git worktree` dan dari kode sekarang, lalu dibandingkan. Gagal (exit 1): path/method hilang, kode respons 2xx hilang, field respons hilang / tidak lagi selalu ada / tipe berubah atau bisa `null`, body/field/parameter request jadi wajib, tipe request menyempit, nilai enum request hilang, content-type request hilang. Peringatan saja: nilai enum respons baru, `response_model` dilepas. Exit 2 bila skema tidak bisa diekspor.
- `.github/workflows/openapi.yml` ("Cek API"): jalan di setiap PR (termasuk saat label berubah), membandingkan commit merge PR dengan induk pertamanya (= base). Label PR `api-memutus` meloloskan perubahan memutus yang disengaja. Laporan masuk ringkasan job.
- `app/tests/test_openapi_cek.py`: 32 tes (aditif lolos, memutus gagal, skema rekursif, skema app vs dirinya bersih).
- `AGENTS.md` aturan mobile #2 menunjuk ke cek ini. `PROGRESS.md`: O01 selesai (#100).
- Dicoba lokal: hapus `emoji` + `is_rollover` jadi nullable di `EnvelopeResponse` → 11 temuan di 4 endpoint, exit 1. Terhadap 40 commit terakhir `main`: tanpa positif palsu.

**Digantung**
- Bukti di CI sungguhan: commit uji di PR ini yang menghapus field harus membuat "Cek API" merah, lalu di-revert. Ini kriteria selesai paket.
- Menjadikan "Cek API" required check di branch protection `main` (pemilik repo, di GitHub).

**Jebakan**
- 119 dari 145 respons 2xx tidak punya `response_model` (skema `{}`), jadi field yang dihapus di respons itu tidak terlihat oleh cek. Menambah `response_model` bisa mengubah keluaran (field disaring) → usul paket terpisah, tidak dikerjakan di sini.
- Job checkout memakai `fetch-depth: 2`; `HEAD^1` hanya benar untuk commit merge `pull_request`. Jangan pakai cek ini di `push`.
- `npm run build` mengubah `frontend/dist/index.html` yang ter-track di git; kembalikan sebelum commit.

**Keputusan kecil**
- Workflow terpisah `openapi.yml`, bukan `ci.yml` seperti di kajian: tes lain sudah ada di `test.yml` (AI Advisor S0) dan cek ini perlu jalan ulang saat label berubah tanpa mengulang seluruh tes.
- Field request yang dihapus tidak dianggap memutus (Pydantic mengabaikan field ekstra); `integer` → `number` dianggap aman.

**Cara melanjutkan**
- `/sesi A05`, branch `mobile/1.4-ci-openapi`. Push commit uji yang menghapus satu field di `EnvelopeResponse`, pastikan "Cek API" merah, revert, pastikan hijau, lalu ubah PR dari draft ke siap review.
- Lokal: `python -m app.scripts.openapi_cek` (bawaan dibandingkan dengan `origin/main`).

---

## A01–A03 · 1.3 penutupan: verifikasi produksi · 2026-10-17 · Claude

**Selesai**
- #109 merge dan deploy Actions berhasil. Diverifikasi langsung di produksi (commit `fe77ea2`, sudah memuat #109): `/health` healthy; `GET /app/config` benar per header (android/ios → `sales_mode: none`, web dan tanpa header → `web`, tanpa header → `platform: unknown`); `Cache-Control: public, max-age=300` + `Vary: X-Jatahku-Client`; `POST /app/errors` memvalidasi isi (422 untuk `{}`); preflight CORS dari jatahku.com mengizinkan `x-jatahku-client`; bundle web yang tayang mengirim `web/0.1.0/<commit7>`.
- `PROGRESS.md`: 1.3 selesai. `00-indeks.md`: baris "Fase sekarang" diperbarui (O01 tidak lagi "di review").

**Digantung**
- Isi log `jatahku.client_errors` di VPS belum dilihat (laporan error web aktif sejak #109). Bila terlalu ramai: AppSetting `app_config` = `{"error_reporting": {"enabled": false}}`.
- Temuan di luar scope dari entri di bawah tetap berlaku (CORS Capacitor sebelum 3.1, `fetch` tanpa header di 1.5, gerbang update di `App.jsx`, tautan toko di 3.2).

**Jebakan**
- Sandbox Claude Code awalnya menolak `api.jatahku.com`/`jatahku.com` (proxy 403); setelah domain ditambahkan di Network access environment, verifikasi langsung bisa.
- Branch PR yang sudah merge tidak dipakai lagi: penutupan ini di branch baru `mobile/1.3-tutup` dari `origin/main` (force push ke branch lama ditolak, dan memang tidak perlu).

**Cara melanjutkan**
- `/sesi B01` (1.5, lapisan `src/native/`) atau `/sesi A18` (1.6, helper jualan: baca `sales_mode` lewat `useAppConfig()` di web dan `build_config(client_of(request))` di server).

---

## A01–A03 · 1.3 Header klien, /app/config, layar perlu update · 2026-10-17 · Claude

**Selesai** (paket selesai dalam satu sesi; status review)
- Server: `app/core/client.py` (parser `X-Jatahku-Client`; header kosong/rusak = `unknown`, diperlakukan seperti web), `app/services/app_config.py` (isi config + bawaan), `app/api/routes/app_config.py` (`GET /app/config`, `POST /app/errors`), router di `app/main.py`.
- `/app/config`: `config_version`, `client`, `update` (status ok/recommended/required, versi minimum/terbaru, store_url), `versions` per platform, `sales_mode` (none/store/web), `features` (semua mati), `links`, `ota` (slot kosong), `error_reporting`. Bawaan ditimpa tanpa deploy lewat AppSetting `app_config` (JSON, lihat docstring service).
- Web: `lib/clientInfo.js` (header dari konstanta build), `apiFetch` di `api.js` (semua 10 `fetch` membawa header), `lib/appConfig.js` (cache lokal, TTL 1 jam, tidak pernah memblokir), `lib/errorReporter.js` (maks 5 laporan/muat, dedupe), `hooks/useAppConfig.jsx` (loader + context `useAppConfig()`), `components/UpdateRequired.jsx`, gerbang di `Layout.jsx`. `vite.config.js` menanam `__APP_VERSION__` (package.json) dan `__APP_PLATFORM__` (env `JATAHKU_PLATFORM`, bawaan `web`).
- Tes: `app/tests/test_app_config.py` (19), `appConfig/clientInfo/errorReporter.test.js`. Dicoba di Chromium dengan API tiruan: config ok → web normal; required → layar "Perlu pembaruan"; header `web/0.1.0/<commit7>` di setiap request.
- `PROGRESS.md`: O01 ditandai selesai (#100 sudah merge).

**Digantung (dicatat, di luar scope)**
- CORS `allow_origins` belum memuat origin Capacitor (`https://localhost`, `capacitor://localhost`) — perlu sebelum 3.1.
- `fetch` tanpa header: `sw.js` (background sync; terbaca `unknown` = web), `Upgrade.jsx` (bukti bayar), `Settings.jsx` (foto profil) — dipindah di 1.5.
- Gerbang "perlu update" ada di `Layout`, jadi halaman login tidak tertutup; lebih tepat di `App.jsx` (1.5 atau 3.1).
- Tombol toko di `UpdateRequired` memakai `<a target=_blank>`; diganti adapter tautan luar di 3.2.
- `00-indeks.md` masih menyebut O01 "di review".

**Jebakan**
- Header kustom membuat request yang dulu "simple" (mis. `GET /auth/google/config`, `tg-login`) kini butuh preflight CORS. `allow_headers=["*"]` sudah menutupnya.
- `pkill -f "vite preview"` di satu perintah Bash ikut membunuh shell itu sendiri; jalankan terpisah.
- `npm run build` mengubah `frontend/dist/index.html` yang di-commit; kembalikan dengan `git checkout -- frontend/dist`.

**Keputusan kecil**
- Mode jualan bawaan: web `web`, android/ios `none`. Laporan error bawaan server `enabled: true, sample_rate: 1.0` (aktif untuk web begitu merge; matikan lewat AppSetting bila log terlalu ramai).
- Cache config disimpan bersama nilai header klien; setelah aplikasi diperbarui, status "required" milik versi lama tidak terbawa.
- Versi tak terbaca tidak pernah menghasilkan "required".
- Isi `/app/config` = kontrak: field hanya boleh ditambah.

**Cara melanjutkan**
- Review PR `Mobile 1.3`, merge, lalu cek `curl -H "X-Jatahku-Client: android/1.0.0/1" https://api.jatahku.com/app/config`.
- Paket berikutnya yang terbuka: B01–B06 (1.5, butuh 1.3) dan A18–A20 (1.6, membaca `sales_mode` lewat `useAppConfig()` di web dan `build_config(client_of(request))` di server).

---

## O01 · 0.1 Bootstrap dokumen · 2026-10-17 · pemilik produk + Claude

**Selesai**
- Kajian yang disetujui 16 Okt 2026 masuk repo: `docs/mobile/00-indeks.md`, `01-kajian.md`, `02-adr.md` (ADR-M1–M16), `03-workflow.md` (alur kerja + daftar 62 paket, kode sesi O/A/B), `PROGRESS.md`, file ini.
- `AGENTS.md`: bagian baru "Aplikasi mobile" (11 aturan), ditambahkan di akhir file supaya tidak bentrok dengan sesi AI Advisor.
- `CLAUDE.md`: satu baris penunjuk ke `docs/mobile/`.
- Perintah Claude Code `.claude/commands/sesi.md` (`/sesi <kode>`) dan `tutup-sesi.md` (`/tutup-sesi`).

**Digantung**
- Paket 0.2 (akun toko), 0.3 (PSE), 0.4 (privasi), 0.5 (penguji), 0.6 (build iOS) — pekerjaan pemilik produk di luar repo; status diubah di tracker dan `PROGRESS.md`.

**Keputusan kecil**
- Mengikuti pola `docs/ai-advisor/` (indeks, workflow, PROGRESS, SESI-LOG) supaya tim memakai satu cara kerja.
- Paket 1.4 diperkecil: `.github/workflows/test.yml` sudah ada (AI Advisor S0); yang tersisa cek perubahan OpenAPI yang memutus.
- Temuan baru sejak kajian: unggah foto profil di `Settings.jsx` menebak alamat API dari hostname (`localhost` → `http://localhost:8000`); di aplikasi akan patah. Masuk paket 1.5.

**Cara melanjutkan**
- Pemilik produk: isi tanggal mulai minggu 1 di tracker, kerjakan O02–O05.
- Sesi kode pertama yang aman paralel dengan AI Advisor: `/sesi A01` (paket 1.3, `/app/config`).
