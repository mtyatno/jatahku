# Memory: Deployment & Code Safety Rules

> Shared cross-agent memory. This repo is developed by multiple agents
> (Claude, OpenAI/Codex, DeepSeek). Keep critical rules here so every agent
> reads them — agent-specific memory stores are not shared.

## ⚠️ Incident History — DO NOT REPEAT

- **Landing page wiped → site down (≈2026-06-29).** `landing.html` was
  deleted/corrupted during a deploy, so `jatahku.com` served a **blank page and
  users could not log in**. Recovered by rollback/restore (`5964e01 restore
  landing.html`; hardened in `ebed770 robust deploy - backup landing files,
  clean dist before pull`).
- **Root causes:** (1) `git add -A` staged and corrupted `landing.html` into
  ~71KB of null bytes; (2) a dirty `frontend/dist/` conflicted on `git pull`,
  so the deploy failed silently and clobbered the landing page.
- **Rules that prevent recurrence:** never `git add -A`; never commit
  `frontend/dist/`; never delete/overwrite public files (`landing.html`,
  `app.html`) without confirming first; deploy.sh must back up landing and
  clean `dist` before pull; after any frontend/landing deploy, verify
  `jatahku.com` is not blank and login works.

## Git & File Management
- **NEVER use `git add -A`** — always stage specific files with `git add file1 file2 ...`
- Staging all files can corrupt binary files (landing.html became 71KB of null bytes) and commit unwanted files (.superpowers/, temporary_file/, AGENTS.md, frontend/dist/)
- `frontend/dist/` should not be committed to git

## Deploy Script (`deploy.sh`)
- Located at `/opt/jatahku/app/deploy.sh` on server. Actions menjalankan
  `/opt/jatahku/deploy.sh`, yang **harus symlink** ke file repo
  (`ls -l /opt/jatahku/deploy.sh` → `-> /opt/jatahku/app/deploy.sh`). Sampai 17 Okt 2026
  itu salinan 4 Okt, jadi perubahan deploy.sh di repo tidak pernah jalan di produksi.
- Runs on push to main via GitHub Actions
- Blog dibangun di CI (job `deploy-blog`) dan di-SCP ke `/tmp/blog-dist-new/`; deploy.sh
  hanya `rsync` ke `blog.jatahku.com/public_html/` (tidak `npm run build` blog di VPS).
- Migrasi: deploy tidak menjalankan alembic, tapi mencetak peringatan dan berakhir exit 2
  bila `alembic current` ≠ `alembic heads` (notifikasi "Deploy GAGAL" terkirim).
- **One deploy at a time.** `.github/workflows/deploy.yml` uses `concurrency`
  (`cancel-in-progress: false`): a newer push waits for the running deploy.
  Keep it — two `deploy.sh` runs overlapping (`git pull` + `npm run build` into
  the same `frontend/dist/`) can publish a broken build, the same failure mode as
  the blank-landing incident. Don't start a manual `deploy.sh` while an Actions
  deploy is running (manual runs are not queued).
- Git repo is at `/opt/jatahku/app/` NOT `/opt/jatahku/`
- Must clean dirty `frontend/dist/` before `git pull`:
  ```bash
  sudo -u jatahku git checkout -- frontend/dist/ 2>/dev/null || true
  ```
- Landing/legal pages dipasang dari repo setiap deploy; `/opt/jatahku/backups/` hanya cadangan bila file repo hilang/kosong
- Deploy fails silently when dist files conflict with repo
- Run as `jatahku` user for git operations, `sudo` for file copies
- **Cek versi yang tayang lewat commit, bukan tebakan.** `GET /health` mengembalikan
  `commit` (kode yang dimuat proses API, `app/core/version.py`, `Cache-Control: no-store`)
  dan `https://jatahku.com/version.json` berisi commit build frontend. deploy.sh
  berhenti bila API lokal tidak menjalankan HEAD; workflow gagal bila API/web publik
  tidak menjalankan `github.sha` (atau yang lebih baru). Jangan menilai versi dari
  `openapi.json` lewat alat fetch — pernah terbaca salinan cache lama.

## Database Schema
- **Never use `DROP TYPE IF EXISTS ... CASCADE`** in migrations — destroys enum types that columns reference, causing 500 errors
- Use `SAEnum` cautiously; better to use plain `String(N)` for enum-like columns
- `ALTER TABLE ADD COLUMN IF NOT EXISTS` is safe
- `ALTER TABLE ALTER COLUMN TYPE` to force column type migration
- `create_all` creates new tables/types but never alters existing

## Service Worker (PWA)
- Service worker at `frontend/src/sw.js`
- Must **bypass API calls** (api.jatahku.com) — return early without `event.respondWith()`:
  ```javascript
  if (url.hostname === 'api.jatahku.com') return;
  ```
- Never cache API responses in SW — they become stale and can return `undefined`
- Test PWA in **incognito/private window** to avoid old SW cache
- Hard refresh (Ctrl+Shift+R) is NOT enough — must unregister old SW or use incognito
- **Offline transaction queue** (IndexedDB `jatahku-offline`): synced by the app
  (`OfflineQueueCenter` in Layout: on load + `online`) and by the SW background
  sync, both through `src/lib/offlineSync.js` — ONE `POST /transactions/batch` per
  sync, only when the queue has items. Never drop a queued transaction silently:
  rejected ones are kept with `rejected: {message}` and shown for fix/retry/delete;
  5xx/401/offline keep them pending. Every item carries a `client_ref`.

## Enum vs String in Python
- `PurposeType.expense` (enum member) does NOT equal `"expense"` (string)
- Always convert with `str(value)` before comparison: `str(getattr(obj, "field", "default"))`
- This applies to all SAEnum/String columns

## Advisor Insights Engine v1 (lama — hanya untuk user di luar flag, dihapus setelah flag `*`)
- `GET /advisor/insights` → `build_advisor_insights()` di `rules/__init__.py`, aturan v1 di `rules/{depletion,subscription,drift,goals,overspend}.py`, loader `context.py`. Dipakai `AttentionCard` (Beranda lama) dan jawaban bot lama.
- Jangan menambah aturan v1. Aturan baru masuk v2 (`rules/{hari,periode,amplop,tagihan,pemasukan,tabungan,data}.py`).
- Tetap dipakai (bukan bagian yang dihapus): `allocation.py` (`/advisor/allocation-recommendation`), `sinking.py` (`/advisor/sinking-funds`, juga `signals.py` v2), `formatting.py`.
- Do NOT wrap advisor route in silent try/except — hides real errors.

## AI Advisor v2 (WAJIB untuk semua sesi AI Advisor)
Dokumen: `docs/ai-advisor/` (mulai dari `00-indeks.md`). Satu sesi = satu PR; status di `docs/ai-advisor/PROGRESS.md`, serah-terima di `SESI-LOG.md`.
1. **Satu sumber angka.** Semua angka periode (dana belanja, terpakai, sisa bebas, J0, J1, laju, proyeksi) hanya dihitung di `app/services/advisor/metrics.py`. Dilarang menulis rumus pembagi hari di route, bot, scheduler, atau frontend.
2. **Teks insight hanya di `app/services/advisor/render.py`.** Aturan mengembalikan data; kalimat dirakit dari template, sama untuk web, chat web, Telegram.
3. **Aturan adalah fungsi murni** `(metrik, sinyal) → insight[]`, tanpa DB, diuji dengan fixture. Loader DB hanya di `snapshot.py`.
4. **Frontend tidak menghitung ulang.** KPI, chip, grafik, dan kartu membaca `GET /advisor/dashboard`; frontend hanya memformat (`rpCompact`, `rpFull`).
5. **CTA pemindah dana lewat `/advisor/plan` → `/advisor/execute`**, dengan `client_ref`. Tidak ada transfer dari frontend tanpa rencana.
6. **Privasi household** tetap lewat `visibility.py`; perencana tidak pernah memakai amplop pribadi anggota lain; cache advisor dihapus per household.
   Cache dashboard dihapus otomatis oleh hook sesi SQLAlchemy (`advisor_cache.install()`, dipasang di `main.py`) setiap commit yang menulis transaksi/pemasukan/alokasi/amplop/langganan/target/cocokkan saldo — jalur tulis baru (route, bot, scheduler) tidak perlu memanggil `invalidate` sendiri.
- **Peta v2** (`app/services/advisor/`): `snapshot.py` (loader, satu-satunya DB) → `metrics.py` (angka) → `signals.py` → `rules/{hari,periode,amplop,tagihan,pemasukan,tabungan,data}.py` → `select.py` (skor, penekanan, slot) → `render.py` (teks) → `dashboard.py` (`GET /advisor/dashboard`, flag, konstanta, cache) / `halaman.py`, `page_transaksi.py`, `page_analitik.py` (`GET /advisor/page/{halaman}`, S11+) / `chat.py` (jawaban chat web & Telegram, ringkasan) / `proaktif.py` (notifikasi proaktif S16: 1/hari, jam tenang, maks 2 permukaan, buku kiriman Redis). Perencana: `planner.py` + `execute.py` (`/advisor/plan`, `/advisor/execute`). Bot: `bot/advisor_cmd.py`. Frontend: `lib/advisorDashboard.js`, `lib/advisorCard.js`, `lib/advisorAction.js`, `lib/envelopeStrip.js`, `lib/analyticsAdvice.js`, `components/{AdvisorChip,AdvisorCard,PlanSheet}.jsx`.
- **Flag `advisor_v2_users`** (AppSetting, `PUT /admin/settings/advisor_v2_users?value=…`): daftar `user_id` dipisah koma, atau `*`. Satu flag untuk Beranda, chat web, Telegram, dan ringkasan — angka yang dilihat user selalu dari satu mesin. Konstanta §11 bisa ditimpa lewat AppSetting `advisor_konstanta` (JSON). Sebelum melebarkan flag, jalankan cek paritas read-only di VPS: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.advisor_paritas` (kode keluar 1 = ada user crash, angka beda, atau amplop pribadi bocor).
- Tes: `pip install -r requirements-test.txt`, lalu `python -m unittest discover -s app/tests -t .`; frontend `cd frontend && node --test src/lib/*.test.js && npm run build`. CI (`.github/workflows/test.yml`) menjalankan yang sama di setiap PR.

## Household Visibility Contract (WAJIB)
- Semua kode yang menampilkan **deskripsi transaksi** ke user HARUS lewat
  `app/services/visibility.py` (`masked_description` / `present_transaction`).
  Jangan pernah render `txn.description` mentah di permukaan lintas-anggota.
- Kontrak: amplop **personal** (`owner_id` terisi) = hanya pemilik; amplop
  **shared** (`owner_id` NULL) = transparan penuh KECUALI deskripsi transaksi
  `is_private=True` milik anggota lain → diganti `"Transaksi privat"`. Nominal,
  tanggal, amplop, dan identitas pencatat SELALU terlihat.
- **Agregat** (saldo, spent, KPI, count di evidence advisor) selalu menghitung
  semua transaksi termasuk yang privat.
- `masked_description` **fail-closed**: viewer/owner ambigu → sembunyikan deskripsi.
  Pemilik transaksi selalu melihat deskripsinya sendiri (short-circuit sebelum
  cek `is_private`).
- Permukaan yang sudah di-enforce: `routes/transactions.py`, `routes/export.py`,
  `bot/handlers.py`, `services/scheduler.py`, advisor `build_sinking_fund_advice`
  (via `select_visible_samples`). Tambahan permukaan baru WAJIB ikut kontrak ini.

## Deploy Checklist — Advisor Foundation Migration (f2a7c9e4b1d3)
Migrasi ini menambah `envelopes.classification`, `transactions.is_private`
(purpose `debt` tidak butuh DDL). CICD tidak menjalankan alembic — jalankan manual:
1. Cek ownership tabel: `sudo -u postgres psql jatahku -c "\dt envelopes" -c "\dt transactions"`
2. Cek head: `alembic current` → harus `d3a9f1c5b820` sebelum upgrade
3. `alembic upgrade head` (jika tabel owned by `postgres`, jalankan sebagai postgres)
4. Verifikasi: `\d envelopes | grep classification`, `\d transactions | grep is_private`
5. `sudo systemctl restart jatahku`

## Deploy Checklist — AI Advisor S1: `envelopes.is_emergency` (c5e9a2d7f4b1)
Menambah `envelopes.is_emergency` (boolean, default false) dan mengisinya `true` untuk amplop
`saving`/`sinking_fund` yang namanya mengandung "darurat"/"emergency". Model sudah memetakan
kolom ini, jadi **API amplop 500 sampai migrasi dijalankan** — jalankan di jam yang sama dengan merge:
1. Cek ownership tabel: `sudo -u postgres psql jatahku -c "\dt envelopes"`
2. Cek head: `alembic current` → harus `a9c3e7d1f5b2` sebelum upgrade
3. `alembic upgrade head` (jika tabel owned by `postgres`, jalankan sebagai postgres)
4. Verifikasi: `\d envelopes | grep is_emergency` dan
   `SELECT name, purpose FROM envelopes WHERE is_emergency;` (hanya amplop tabungan)
5. `sudo systemctl restart jatahku`

## Aplikasi mobile (WAJIB untuk semua sesi mobile)
Dokumen: `docs/mobile/` (mulai dari `00-indeks.md`; keputusan di `02-adr.md`). Buka sesi dengan `/sesi <kode>`, tutup dengan `/tutup-sesi`. Satu paket = satu branch `mobile/<wbs>-*` = satu PR; status di `docs/mobile/PROGRESS.md`, serah-terima di `docs/mobile/SESI-LOG.md`.
1. **Satu bundle, satu UI.** Web, Android, iOS memakai `frontend/` yang sama. Perbedaan platform hanya di `frontend/src/native/`; komponen tidak boleh memeriksa `Capacitor`, user agent, `display-mode`, atau hostname.
2. **API hanya bertambah.** Field/endpoint lama tidak dihapus atau diubah artinya sebelum `min_supported_version` di `/app/config` dinaikkan dan user melihat banner pembaruan. Berlaku juga untuk sesi non-mobile begitu aplikasi pertama terpasang di HP user.
3. **Aplikasi selalu menyebut dirinya** lewat header `X-Jatahku-Client: <platform>/<versi>/<build>`; server mengubah perilaku berdasarkan header ini, tidak pernah berdasarkan tebakan.
4. **Jualan diatur server.** Tombol, tautan, dan teks ajakan beli (termasuk pesan kuota bot) datang dari satu helper yang membaca mode jualan per platform; teks "upgrade" tidak ditulis langsung di komponen atau handler.
5. **Tidak ada transaksi yang hilang.** Di aplikasi, antrean offline disimpan di penyimpanan native; item yang ditolak tetap disimpan.
6. **Rahasia hanya di Keychain/Keystore.** Di aplikasi, token tidak disimpan di `localStorage`, IndexedDB, item antrean, atau URL.
7. **Proyek native di-commit dan di-review.** `mobile/android/` dan `mobile/ios/` tidak dibuat ulang saat build dan tidak ditambal skrip.
8. **OTA hanya untuk web.** Bundle OTA hanya berisi build `frontend/` + versi native minimum; perubahan plugin, izin, atau kode native lewat rilis toko.
9. **Identitas tidak pernah berubah.** ID aplikasi `com.jatahku.app`, origin/skema Capacitor, dan kunci penandatanganan (ADR-M3–M5) hanya berubah dengan keputusan tertulis pemilik produk.
10. **Paritas diuji, bukan diasumsikan.** Daftar periksa paritas (`01-kajian.md`, lampiran WBS) dijalankan di perangkat nyata sebelum setiap rilis toko, termasuk satu Android kelas bawah.
11. **Struk tidak pernah tercatat diam-diam atau dua kali.** Dokumen dari share, unggahan, atau Telegram selalu menunggu konfirmasi user; hash file, nomor referensi, dan `client_ref` mencegah pencatatan ganda; transfer gagal tidak bisa dicatat.
