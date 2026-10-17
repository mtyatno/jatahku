# Mobile — catatan serah-terima

Entri terbaru di atas. Format: **Kode sesi · paket · tanggal · siapa** — selesai · digantung · jebakan · keputusan kecil · cara melanjutkan.

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
