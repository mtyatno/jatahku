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
- **Login 500 setelah merge berisi migrasi (2026-10-17, PR #116, ±4 menit).**
  `alembic upgrade head` dijalankan **sebelum** merge, saat file migrasi
  `d3b8f1a6c2e9` belum ada di server, jadi tidak ada yang dijalankan. Deploy
  memasang model yang memetakan `users.tokens_revoked_at`, dan setiap query
  `User` (login, lupa sandi, semua endpoint ber-auth) 500 sampai migrasi
  dijalankan ulang setelah deploy. Insiden serupa: `c5e9a2d7f4b1`.
- **Aturan:** migrasi dijalankan **setelah** deploy menarik kode (lihat
  "Urutan merge PR bermigrasi" di bagian Deploy Script), bukan sebelum merge.
- **Produksi berjalan dengan `APP_ENV=development` (ditemukan 2026-11-05).**
  `/opt/jatahku/.env` berisi `APP_ENV=development`, jadi engine SQLAlchemy berjalan dengan
  `echo=True`: setiap query beserta parameternya (email saat login, keterangan transaksi,
  isi laporan) tercatat di journal, dan `/docs` serta `/redoc` terbuka untuk umum.
  Diperbaiki dengan `APP_ENV=production` lalu restart.
- **Aturan:** `.env` produksi harus `APP_ENV=production` (nilai bawaan kode). Cek:
  `sudo grep -n '^APP_ENV' /opt/jatahku/.env` dan
  `curl -s -o /dev/null -w "%{http_code}\n" https://api.jatahku.com/docs` → `404`.

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
- **Urutan merge PR bermigrasi** (label `migrasi`). Model sudah memetakan kolom baru,
  jadi API 500 sejak deploy sampai migrasi jalan; jendela ini harus sesempit mungkin:
  1. Merge, lalu tunggu deploy sampai `git pull` selesai (run Actions "Deploy Jatahku"
     berjalan; `api.jatahku.com/health` → `commit` baru). Run itu boleh berakhir
     "Deploy GAGAL" karena migrasi tertinggal — itu memang tandanya.
  2. Pastikan file migrasinya sudah ada:
     `ls /opt/jatahku/app/alembic/versions/ | grep <revisi>`. Tidak ada = kode belum
     ter-pull; `alembic upgrade head` sebelum ini **tidak menjalankan apa pun**.
  3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`
     (bila tabelnya milik `postgres`, jalankan sebagai postgres; cek pemiliknya dengan query di checklist Kotak Struk), lalu `alembic current` harus
     sama dengan revisi baru.
  4. `sudo systemctl restart jatahku`, lalu cek endpoint yang memakai tabel itu
     (mis. `POST /auth/login` dengan email asal → 401, bukan 500).
  5. Jalankan ulang job deploy yang gagal (Actions → run itu → "Re-run failed jobs"; satu restart lagi) supaya
     langkah "Verifikasi versi yang tayang" memeriksa `/health` dan `version.json`; di run pertama langkah itu
     dilewati karena deploy berhenti di migrasi.
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
- **Workflow "Migrasi"** (`.github/workflows/migrasi.yml`) berjalan di setiap PR yang menyentuh `app/models/**`, `alembic/**`, `alembic.ini`, `app/core/database.py`, atau `requirements.txt`: skema awal dibuat seperti produksi (`create_all` dari model commit dasar PR + `alembic stamp head`), lalu `alembic upgrade head`, `alembic check`, `alembic downgrade` ke head dasar, dan `upgrade head` lagi. **Model yang berubah tanpa migrasi gagal di `alembic check`**, begitu juga migrasi yang tidak cocok dengan model atau `downgrade()` yang rusak; lebih dari satu head juga gagal. Jalankan lokal di database PostgreSQL kosong: `DATABASE_URL=postgresql+asyncpg://… JWT_SECRET=x .github/scripts/cek-migrasi.sh origin/main` (butuh `psycopg2-binary`). `alembic upgrade head` dari database kosong memang gagal: migrasi awal hanya membuat 11 tabel, sisanya dibuat `create_all`.

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
- **Bagikan ke Jatahku** (`POST /bagikan`, `lib/shareInbox.js`): penangannya harus tetap di atas cek
  `request.method !== 'GET'`. Share disimpan di IndexedDB `jatahku-share` (terpisah dari `jatahku-offline`) dan hanya
  dikosongkan saat user sendiri logout. Navigasi: hanya jawaban 2xx `text/html` yang disimpan sebagai app shell offline.

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
- Tes: `pip install -r requirements-test.txt`, lalu `python -m unittest discover -s app/tests -t .`; frontend `cd frontend && node --test src/lib/*.test.js src/native/*.test.js src/plugins/*/*.test.js && npm run build`. CI (`.github/workflows/test.yml`) menjalankan yang sama di setiap PR.

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
1. Cek ownership tabel: `sudo -u postgres psql jatahku_db -c "\dt envelopes" -c "\dt transactions"`
2. Cek head: `alembic current` → harus `d3a9f1c5b820` sebelum upgrade
3. `alembic upgrade head` (jika tabel owned by `postgres`, jalankan sebagai postgres)
4. Verifikasi: `\d envelopes | grep classification`, `\d transactions | grep is_private`
5. `sudo systemctl restart jatahku`

## Deploy Checklist — AI Advisor S1: `envelopes.is_emergency` (c5e9a2d7f4b1)
Menambah `envelopes.is_emergency` (boolean, default false) dan mengisinya `true` untuk amplop
`saving`/`sinking_fund` yang namanya mengandung "darurat"/"emergency". Model sudah memetakan
kolom ini, jadi **API amplop 500 sampai migrasi dijalankan** — jalankan di jam yang sama dengan merge:
1. Cek ownership tabel: `sudo -u postgres psql jatahku_db -c "\dt envelopes"`
2. Cek head: `alembic current` → harus `a9c3e7d1f5b2` sebelum upgrade
3. `alembic upgrade head` (jika tabel owned by `postgres`, jalankan sebagai postgres)
4. Verifikasi: `\d envelopes | grep is_emergency` dan
   `SELECT name, purpose FROM envelopes WHERE is_emergency;` (hanya amplop tabungan)
5. `sudo systemctl restart jatahku`

## Deploy Checklist — Mobile 1.1: `auth_sessions` (d3b8f1a6c2e9) — sudah jalan 2026-10-17
Menambah tabel `auth_sessions` dan `users.tokens_revoked_at`. Model `User` memetakan kolom
ini, jadi **semua query user 500 (termasuk login) sampai migrasi dijalankan**. Ikuti
"Urutan merge PR bermigrasi" di atas; `alembic current` harus `c5e9a2d7f4b1` sebelum upgrade.
Verifikasi: `\d auth_sessions`, `\d users | grep tokens_revoked_at`, login dengan email asal → 401.

## Deploy Checklist — Kotak Struk / Bagikan ke Jatahku, Bagian A (a7c4e2b9d1f3) — sudah jalan 2026-10-28
Memperluas `receipt_scans` (status, `doc_type`, `document`, hash file, dll.) dan menambah tabel
`household_merchants` + `merchant_envelope_map`. Migrasi **idempoten**: `lifespan` (`KOTAK_DDL` + `create_all`)
membuat kolom dan tabel yang sama saat API restart, jadi tidak ada jendela 500 seperti `auth_sessions`; migrasinya
tetap harus dijalankan, kalau tidak `deploy.sh` berakhir exit 2. Paket, folder, dan kunci harus siap **sebelum
merge** karena worker langsung berjalan di restart pertama. Detail: `docs/kotak-struk.md`.
Sebelum merge (aman untuk kode lama):
1. `sudo -u jatahku /opt/jatahku/venv/bin/pip install pypdfium2==5.13.0` (versi sama dengan `requirements.txt`;
   deploy tidak meng-install paket). Tanpa ini PDF menjadi item `gagal` ("Baca bukti sedang tidak bisa"), foto tetap jalan.
2. Folder berkas sementara: `sudo install -d -m 0700 -o jatahku -g jatahku /var/lib/jatahku/kotak`
   (`KOTAK_DIR`; di luar `backup.sh`, isinya sementara). Tanpa ini unggahan gagal (500 di web, "Bukti tidak bisa
   dibaca" di bot), karena user `jatahku` tidak bisa membuat folder di bawah `/var/lib`.
3. Tambahkan `KOTAK_HMAC_KEY=<hasil openssl rand -hex 32>` ke `/opt/jatahku/.env` (kunci HMAC nomor referensi/rekening).
   Isi **sekali** dan jangan diganti: nilai lain membuat `ref_hash` lama tak cocok (cek duplikat dan peta merchant
   terputus). Kosong = diturunkan dari `JWT_SECRET` dengan peringatan di log.
   Cek hak tabel (ditambahkan setelah deploy 28 Okt 2026): restart pertama setelah merge menjalankan `create_all` +
   `KOTAK_DDL` sebagai user DB aplikasi, jadi user itu harus boleh ALTER `receipt_scans` (pemilik) dan REFERENCES
   `households`, `envelopes`, `users`; kalau tidak, API gagal start. Database dan user diambil dari `DATABASE_URL`
   (produksi: database `jatahku_db`, user `jatahku`; per 28 Okt 2026 kelima tabel di bawah milik `jatahku`):
   ```bash
   sudo -u postgres psql jatahku_db -v role=jatahku <<'SQL'
   SELECT c.relname, pg_get_userbyid(c.relowner) AS pemilik, pg_has_role(:'role', c.relowner, 'USAGE') AS bisa_alter,
          has_table_privilege(:'role', c.oid, 'REFERENCES') AS bisa_fk, has_table_privilege(:'role', c.oid, 'UPDATE') AS bisa_update
   FROM pg_class c WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
     AND c.relname IN ('receipt_scans','households','envelopes','users','alembic_version') ORDER BY 1;
   SQL
   ```
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
4. `ls /opt/jatahku/app/alembic/versions/ | grep a7c4e2b9d1f3`; `alembic current` harus `a7c3e9d1f5b2` sebelum upgrade.
5. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`; `alembic current` harus
   `a7c4e2b9d1f3`. Lalu `sudo systemctl restart jatahku`.
6. Uji (saklar mati): kirim foto struk ke bot → pesan struk tanpa baris sisa scan; kirim PDF → hasil, bukan
   "📄 File belum didukung"; `sudo ls -A /var/lib/jatahku/kotak` kosong setelah item selesai; `sudo grep -c '^KOTAK_HMAC_KEY=' /opt/jatahku/.env` → 1.
7. **Saklar `features.receipt_inbox` tetap mati** sampai urutan di `docs/kotak-struk.md` bagian "Menyalakan saklar"
   (gerbang korpus A14 diganti keputusan pemilik produk 1 Nov 2026; mulai dengan checklist "Kotak Struk belajar lintas
   user (e7b3d5a9c1f4)" di bawah). `kotak_corpus eval --real-only` tetap dijalankan dan dilaporkan, bukan gerbang.

## Deploy Checklist — Plugin R1: model ruang (1c7e5a9d3b20) — sudah jalan 2026-11-01
Menambah `households.type` (bawaan `rumah_tangga`), `incomes.kind` (bawaan `pemasukan`) beserta backfill, dan unik
`(user_id, household_id)` di `household_members`. Kolom **idempoten**: `lifespan` (`RUANG_DDL` di
`app/services/ruang_schema.py`) menambahkannya saat restart pertama, jadi tidak ada jendela 500; backfill `kind` dan
constraint hanya dijalankan migrasi, jadi migrasi tetap wajib. Tanpa paket, folder, atau `.env` baru. Detail:
`docs/plugin/04-kontrak-api.md` bagian 0.
Sebelum merge (aman untuk kode lama):
1. Hak tabel: restart pertama menjalankan `ALTER TABLE households` dan `ALTER TABLE incomes` sebagai user DB aplikasi,
   jadi `jatahku` harus pemilik (`bisa_alter` = t) `households`, `incomes`, dan `household_members`; kalau tidak, API
   gagal start. Pakai query di checklist Kotak Struk dengan nama tabel itu di `IN (…)`.
2. Keanggotaan ganda harus kosong, kalau tidak migrasi berhenti (tanpa menghapus apa pun) dan constraint tidak dibuat:
   `sudo -u postgres psql jatahku_db -c "SELECT user_id, household_id, COUNT(*) FROM household_members GROUP BY 1, 2 HAVING COUNT(*) > 1"`
   → 0 baris. Bila ada, rapikan manual dulu (sisakan satu baris per pasangan, utamakan peran tertinggi).
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
3. `ls /opt/jatahku/app/alembic/versions/ | grep 1c7e5a9d3b20`; `alembic current` harus `a7c4e2b9d1f3` sebelum upgrade.
4. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`; `alembic current` harus
   `1c7e5a9d3b20`. Lalu `sudo systemctl restart jatahku` dan jalankan ulang job deploy yang gagal.
5. Verifikasi: `SELECT type, COUNT(*) FROM households GROUP BY 1` → hanya `rumah_tangga`;
   `SELECT kind, COUNT(*) FROM incomes GROUP BY 1` → empat jenis masuk akal (transfer = baris bernominal 0);
   `\d household_members` memuat `uq_household_members_user_household`; Beranda, daftar pemasukan, dan geser dana di
   bot tetap jalan.

## Deploy Checklist — Plugin U1: tabel Buku Usaha (u1b0k0u5aha1)
Plugin pertama (`app/plugins/buku_usaha/`) dan empat tabel plugin baru `p_buku_usaha_kontak`, `p_buku_usaha_income_meta`,
`p_buku_usaha_txn_meta`, `p_buku_usaha_alokasi` (04-kontrak-api.md §5 "Endpoint plugin", §6). **Hanya tabel baru**, tidak
ada kolom baru di tabel lama, jadi tidak ada jendela 500: `lifespan` (`create_all`) membuat tabel yang sama saat restart
dan migrasinya idempoten (`if_not_exists`). Endpoint baru: `/p/buku_usaha/*` (hanya ruang usaha yang memasang plugin)
dan `GET /ruang/{id}/plugins/{plugin_id}/ekspor`. Untuk semua user hari ini tidak ada yang berubah: Buku Usaha hanya
muncul di katalog ruang usaha (flag `ruang_usaha_users`) untuk user di flag `plugin_buku_usaha_users` (kosong sesudah
deploy = tidak ada yang bisa memasang). Tanpa paket atau `.env` baru.
1. Sebelum merge: `alembic current` di VPS = `c9e4a7f2b5d8` (Kotak Struk belajar tahap 2, #197; migrasi U1 menginduk
   ke sana sesudah digabung dengan `main` 5 Nov). Bila belum, jalankan checklist "Kotak Struk belajar tahap 2" (dan
   "Plugin R7" sebelumnya) dulu.
2. Merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`), tunggu deploy; `api.jatahku.com/health` → commit baru;
   `ls /opt/jatahku/app/alembic/versions/ | grep u1b0k0u5aha1`; `journalctl -u jatahku --since "<waktu deploy>" | grep
   "plugin dimuat"` → `plugin dimuat: buku_usaha` tanpa baris `plugin tidak dimuat`.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (FK ke `households`, `users`,
   `envelopes`, `incomes`, `transactions`: bila tabel itu milik `postgres`, jalankan sebagai postgres); `alembic current`
   harus `u1b0k0u5aha1`. Lalu `sudo systemctl restart jatahku` dan jalankan ulang job deploy yang gagal.
4. Verifikasi: `sudo -u postgres psql jatahku_db -c '\d p_buku_usaha_kontak'` (indeks
   `ix_p_buku_usaha_kontak_household_peran_nama`, FK household CASCADE, created_by SET NULL); `cd /opt/jatahku/app &&
   sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0; dengan token sendiri di
   ruang keluarga `GET https://api.jatahku.com/plugins` → `[]` dan `GET /p/buku_usaha/kontak` → 404 `plugin_tidak_aktif`.
5. Gerbang H di produksi (pemilik, ruang usaha uji, flag `plugin_buku_usaha_users` = id pemilik): Fitur Tambahan → Pasang
   (layar izin: hanya "Melihat amplop dan saldonya") → wizard (ubah satu nama, isi anggaran Bahan/Operasional, lepaskan
   satu centang) → aktif: menu Usaha › Buku Usaha, tab Kontak: tambah pelanggan dan pemasok, ubah, hapus; Jeda → menu
   hilang, `/p/buku_usaha` "tidak aktif", Lanjutkan → kontak kembali; Unduh JSON dan CSV (ZIP) dari panel; Copot → arsip,
   tombol unduh masih ada; Pulihkan → wizard lagi (amplop yang ada tercentang terkunci) → Lewati → kontak utuh; saklar
   `PUT /admin/settings/plugin_saklar_darurat?value=buku_usaha` → menu dan rute hilang seketika, status tetap aktif,
   `value=` kosong → kembali. Akun karyawan di ruang itu: tidak ada menu Usaha, `/p/buku_usaha` dialihkan, API 403
   `khusus_admin`. Sesudahnya: `SELECT action, detail FROM plugin_audit_log WHERE plugin_id='buku_usaha' ORDER BY
   created_at` → pasang, lanjut, data:tambah/ubah/hapus (tanpa nilai kolom), ekspor, jeda, copot, pulihkan.

## Deploy Checklist — Plugin R7: Catat cepat dan kamus per ruang (d7r7k4a1m9c3) — sudah jalan 2026-11-05
Migrasi dijalankan pemilik di VPS; run deploy `aa10826` (percobaan ke-2) hijau, termasuk "Verifikasi versi yang tayang";
`ruang_paritas` 109/109 ok.
Menambah satu tabel baru `ruang_kamus`, route `GET`/`DELETE /ruang/{id}/kamus`, field aditif di
`POST /transactions/suggest-envelope(s)` (`sumber`, `aturan`, request `amount`), lembar Catat cepat di ruang usaha, dan
bagian "Kata yang dipelajari" di halaman Anggota (04-kontrak-api.md §2, §3). **Tidak ada kolom baru di tabel lama**, jadi
tidak ada jendela 500: `lifespan` (`create_all`) membuat tabel yang sama saat restart dan migrasinya idempoten
(`if_not_exists`). Kamus hanya diisi dan dibaca di ruang usaha (flag `ruang_usaha_users`); ruang keluarga, bot, dan
Catat lama tidak berubah selain satu kueri tambahan yang kosong saat kata user tidak cocok. Tanpa paket atau `.env`.
1. Sebelum merge: `alembic current` di VPS = `967a27d0c15d` (laporan berkala tahap 1). Bila belum, jalankan checklist
   "Laporan berkala tahap 1 (967a27d0c15d)" dulu (migrasi R7 menginduk ke sana; di-rebase 5 Nov sesudah #190).
2. Merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`), tunggu deploy; `api.jatahku.com/health` → commit baru;
   `ls /opt/jatahku/app/alembic/versions/ | grep d7r7k4a1m9c3`.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (bila `households`/`envelopes`/
   `users` milik `postgres`, FK ke sana butuh hak REFERENCES: jalankan sebagai postgres; cek dengan query di checklist
   Kotak Struk); `alembic current` harus `d7r7k4a1m9c3`. Lalu `sudo systemctl restart jatahku` dan jalankan ulang job
   deploy yang gagal.
4. Verifikasi: `sudo -u postgres psql jatahku_db -c '\d ruang_kamus'` (unik `uq_ruang_kamus`, indeks
   `ix_ruang_kamus_household_keyword`); `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m
   app.scripts.ruang_paritas` → kode keluar 0; catat lewat bot dan web di ruang keluarga seperti biasa → saran amplop
   sama seperti sebelumnya; `sudo -u postgres psql jatahku_db -c "SELECT COUNT(*) FROM ruang_kamus k JOIN households h
   ON h.id = k.household_id WHERE h.type <> 'usaha'"` → 0 (juga kapan pun sesudahnya).
5. Uji dua akun di ruang usaha (flag): pemilik mencatat "kardus 125rb" ke Operasional lewat Catat cepat → karyawan
   mengetik "kardus 50 pcs 125rb" → tebakan Operasional dengan "Kamus <ruang> · diajarkan <pemilik>"; karyawan mengetik
   kata yang biasa ia catat di ruang keluarganya (mis. "pulsa 50rb") → tawaran "Catat di ruang keluarga" → tercatat di
   ruang keluarganya, tidak di ruang usaha; pemilik: halaman Anggota → "Kata yang dipelajari" → hapus "kardus" → log
   ruang "menghapus kata".

## Deploy Checklist — Plugin R6: halaman Anggota dan Beranda karyawan (tanpa migrasi) — sudah jalan 2026-11-04
Halaman Anggota (`/ruang`), Beranda template "Karyawan", menu dan Catat per peran, gabung ruang dengan kode di pemilih
ruang, daftar/cabut undangan, ganti nama ruang. Semuanya hanya di ruang usaha, jadi di balik flag `ruang_usaha_users`;
ruang keluarga tidak berubah (katalog dan template Beranda umum sama). Tanpa migrasi, paket, atau `.env`.
1. Merge, tunggu deploy hijau (`api.jatahku.com/health` dan `jatahku.com/version.json` → commit baru).
2. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0.
3. Uji dengan akun kedua yang ada di flag: pemilik membuka ruang usaha → menu **Anggota** → Undang karyawan → akun
   kedua: pemilih ruang → "Gabung dengan kode". Sebagai karyawan: menu hanya Beranda dan Transaksi; Beranda berisi
   Catat, Hari ini, Menunggu persetujuan, Catatanku hari ini, Batasan dari admin, dan pengingat ruang keluarga; tidak
   ada angka saldo atau laporan. Pemilik: atur batas nominal kecil (tersimpan otomatis) → karyawan mencatat di atasnya
   → "menunggu persetujuan" → pemilik menyetujui dari halaman Anggota (angka di menu berkurang).
4. Flag `ruang_usaha_users` berisi user_id **dipisah koma, tanpa spasi**, termasuk pemilik. Menambah user:
   `UPDATE app_settings SET value = value || ',<user_id>' WHERE key='ruang_usaha_users'`. Bila id menyatu tanpa koma,
   tidak ada user yang cocok (pemilik ikut kehilangan ruang usaha): tulis ulang nilainya utuh dengan `SET value = '<id1>,<id2>'`.

## Deploy Checklist — Plugin R8: prive dua sisi (tanpa migrasi) — sudah jalan 2026-11-04
Endpoint baru `POST /prive` dan nilai baru `incomes.kind = prive` (kolom String, tanpa migrasi). Tanpa paket, `.env`,
atau perubahan tampilan; belum bisa dipakai siapa pun sebelum ada ruang usaha (R4, flag `ruang_usaha_users`).
1. Merge, tunggu deploy hijau (`api.jatahku.com/health` → commit baru).
2. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0.

## Deploy Checklist — Plugin H1: host plugin (a7e3c1f5d9b2) — sudah jalan 2026-11-04
Migrasi dijalankan pemilik di VPS; run deploy `e739245` (percobaan ke-2) hijau, termasuk "Verifikasi versi yang tayang".
Menambah tabel `plugin_installations`, `entitlements`, `plugin_audit_log` dan endpoint `GET /plugins`,
`POST /ruang/{id}/plugins/{plugin_id}/pasang|lanjut|jeda|copot` (04-kontrak-api.md §5). Migrasi **idempoten**
(`if_not_exists`): `lifespan` (`create_all`) membuat tabel yang sama saat API restart, dan tidak ada tabel lama yang
berubah, jadi tidak ada jendela 500. Belum ada plugin di `app/plugins/` (yang pertama datang di U1) dan belum ada
klien yang memanggil endpoint ini (H3), jadi tidak ada perubahan perilaku. Tanpa paket atau `.env` baru.
1. Merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`), tunggu deploy; `api.jatahku.com/health` → commit baru.
2. `ls /opt/jatahku/app/alembic/versions/ | grep a7e3c1f5d9b2`; `alembic current` harus `c5r5a8e2d417` (Plugin R5)
   sebelum upgrade; bila belum, jalankan checklist "Plugin R5" dulu (migrasi H1 menginduk ke migrasi R5).
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (bila `households`/`users`
   milik `postgres`, jalankan sebagai postgres); `alembic current` harus `a7e3c1f5d9b2`.
4. Verifikasi: `sudo -u postgres psql jatahku_db -c '\d plugin_installations'` (indeks parsial
   `uq_plugin_installation_ruang ... WHERE owner_id IS NULL`); `journalctl -u jatahku --since "<waktu deploy>" | grep
   "plugin dimuat"` → `plugin dimuat: (tidak ada)` tanpa baris `plugin tidak dimuat`; dengan token sendiri
   `GET https://api.jatahku.com/plugins` → `[]`.
- **Saklar darurat** (insiden pada plugin tertentu): `PUT /admin/settings/plugin_saklar_darurat?value=<id>[,<id>]`
  (token admin). Berlaku pada permintaan berikutnya, tanpa restart; status per ruang tidak berubah. Matikan dengan
  `value=` kosong.

## Deploy Checklist — Plugin R5: peran, batasan, persetujuan (c5r5a8e2d417) — sudah jalan 2026-11-04
Migrasi dijalankan pemilik di VPS; run deploy `9d26d7c` (percobaan ke-2) hijau, termasuk "Verifikasi versi yang tayang".
Menambah empat tabel baru (`ruang_batasan`, `ruang_undangan`, `ruang_draf`, `ruang_audit`) dan route `/ruang/{id}/…`,
`/ruang/gabung`, `/persetujuan/saya`. **Tidak ada kolom baru di tabel lama**, jadi tidak ada jendela 500: `lifespan`
(`create_all`) membuat tabel yang sama saat restart dan migrasinya idempoten (`if_not_exists`). Perilaku baru hanya
untuk peran `member` di ruang **usaha**, dan ruang usaha hanya terbuka bagi user di flag `ruang_usaha_users` (R4), jadi
tidak ada yang berubah untuk user lain. Karyawan yang diundang juga harus masuk flag itu (`/ruang/gabung` di luar flag →
403 `ruang_usaha_belum_dibuka`). Tanpa paket baru, `.env`, atau perubahan tampilan.
1. Sebelum merge: checklist "Plugin R3" dan "Plugin R4" sudah jalan, dan `alembic current` di VPS = `2d51b9031a6b` (siklus household).
   Bila belum, jalankan checklist siklus household dulu.
2. Merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`), tunggu deploy; `api.jatahku.com/health` → commit baru;
   `ls /opt/jatahku/app/alembic/versions/ | grep c5r5a8e2d417`.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (bila `households`/`users`
   milik `postgres`, FK ke sana butuh hak REFERENCES: jalankan sebagai postgres; cek pemiliknya dengan query di checklist
   Kotak Struk); `alembic current` harus `c5r5a8e2d417`. Lalu `sudo systemctl restart jatahku` dan jalankan ulang job
   deploy yang gagal.
4. Verifikasi: `sudo -u postgres psql jatahku_db -c '\d ruang_draf'` (indeks unik parsial `uq_ruang_draf_client_ref`),
   lalu dengan token sendiri: `GET https://api.jatahku.com/ruang/<id ruang keluarga>/anggota` → 404 (route hanya untuk
   ruang usaha); catat transaksi di web dan bot seperti biasa → 201; `ruang_paritas` kode keluar 0. Di ruang usaha uji
   (flag pemilik): undang akun kedua sebagai karyawan (akun itu ditambahkan ke flag), atur batas nominal kecil, catat di
   atasnya dari akun karyawan → "menunggu persetujuan", setujui dari akun pemilik.
5. Flag `*` tetap menunggu V1 (Paket Usaha dan uji beta), seperti catatan checklist R4.

## Deploy Checklist — Plugin R4: membuat dan berpindah ruang (tanpa migrasi, flag `ruang_usaha_users`)
`GET`/`POST /ruang`, pemilih ruang di sidebar dan header HP, dan header `X-Jatahku-Ruang` dari web dan aplikasi. Selama
flag `ruang_usaha_users` belum diisi, `GET /ruang` hanya berisi ruang keluarga, pemilih tidak tampil, dan klien tidak
mengirim header: tampilan dan data semua user tidak berubah. Tanpa migrasi, paket, atau `.env`.
1. Merge, tunggu deploy hijau (`api.jatahku.com/health` dan `jatahku.com/version.json` → commit baru).
2. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0.
3. **Buka untuk pemilik saja:** `sudo -u postgres psql jatahku_db -c "INSERT INTO app_settings (key, value) VALUES
   ('ruang_usaha_users', '<user_id kamu>') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"`. Muat ulang
   Jatahku: pemilih ruang muncul di bawah logo (HP: menggantikan logo). Buat ruang usaha uji, pindah ke sana: Amplop,
   Transaksi, dan Beranda kosong; catat satu pengeluaran ke amplop baru di ruang itu; pindah ke ruang keluarga: angka
   tidak berubah dan catatan ruang usaha tidak tampil. Chat berlabel "Ruang keluarga" dan tetap mencatat ke ruang keluarga.
4. **Jangan isi `*`** sampai R5 (peran dan batasan) dan V1: undangan ruang usaha belum ada, dan Paket Usaha belum dipasang.
5. **Menutup lagi** kapan saja: value `''`. Ruang usaha yang sudah dibuat tetap di database, tetapi tidak tampil, tidak
   bisa dibuka lewat header (403, klien kembali ke ruang keluarga), dan objeknya tidak bisa ditulis.

## Deploy Checklist — Plugin R3: ruang dari objek saat menulis (tanpa migrasi) — sudah jalan 2026-11-01
`ruang_paritas` di VPS sesudah deploy: 105 user · ok 105 · beda 0 · crash 0 · tanpa household 0. Uji manual (catat web dan
bot, tambah amplop, geser dana, bayar langganan, antrean offline di HP) oleh pemilik.
Penulisan menentukan ruang dari objeknya; objek baru tanpa induk dari header (tanpa header = ruang keluarga); kuota
Basic hanya di ruang keluarga. Tanpa migrasi, paket, `.env`, atau perubahan tampilan: belum ada klien yang mengirim
`X-Jatahku-Ruang` dan belum ada user dengan ruang kedua, jadi semua penulisan tetap jatuh ke ruang keluarga.
1. Merge, tunggu deploy hijau (`api.jatahku.com/health` → commit baru).
2. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0.
   Cek catat transaksi (web dan bot), tambah amplop, geser dana, bayar langganan, dan antrean offline di HP.

## Deploy Checklist — Plugin R2: resolver ruang (tanpa migrasi) — sudah jalan 2026-11-01
Mengganti setiap pencarian "household milik user" dengan `app/services/ruang.py`. Tanpa migrasi, paket, atau `.env`
baru, dan tanpa perubahan tampilan: belum ada klien yang mengirim `X-Jatahku-Ruang` dan belum ada user dengan ruang
kedua. Satu perubahan perilaku yang disengaja: `POST /user/reset` hanya menghapus pemasukan user di household yang
di-reset (dulu pemasukannya di household lama yang masih dipakai anggota lain ikut terhapus).
1. Sebelum merge: tidak ada user dengan lebih dari satu keanggotaan (kode lama galat untuk user itu, kode baru memilih
   ruang keluarga): `sudo -u postgres psql jatahku_db -c "SELECT user_id, COUNT(*) FROM household_members GROUP BY 1 HAVING COUNT(*) > 1"`
   → 0 baris.
2. Merge, tunggu deploy hijau (`api.jatahku.com/health` → commit baru), lalu
   `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.ruang_paritas` → kode keluar 0,
   semua user `ok` atau `tanpa household`. Hasil `beda` atau `crash` = laporkan. Cek Beranda, daftar transaksi, geser
   dana di bot, dan `/sisa` di Telegram.

## Deploy Checklist — Plugin B1: `dashboard_layouts` (b1d4a7c2e9f0) — sudah jalan 2026-11-01
Menambah tabel `dashboard_layouts` (tata letak Beranda per user per ruang, ADR-P8) dan endpoint baru
`/dashboard/*`. Migrasi **idempoten** (`if_not_exists`): `lifespan` (`create_all`) membuat tabel yang sama saat
API restart, dan tidak ada model lama yang memetakan kolom baru, jadi tidak ada jendela 500. Migrasinya tetap
harus dijalankan, kalau tidak `deploy.sh` berakhir exit 2. Frontend belum memanggil `/dashboard/*` (B2, di balik
flag `beranda_registry_users`), jadi tidak ada perubahan tampilan. Tanpa paket baru.
1. Merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`), tunggu deploy; `api.jatahku.com/health` → commit baru.
2. `ls /opt/jatahku/app/alembic/versions/ | grep b1d4a7c2e9f0`; `alembic current` harus `1c7e5a9d3b20` (R1) sebelum upgrade; bila belum, jalankan checklist R1 dulu.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (bila `households`/`users`
   milik `postgres`, jalankan sebagai postgres; cek pemiliknya dengan query di checklist Kotak Struk); `alembic current`
   harus `b1d4a7c2e9f0`.
4. Verifikasi: `sudo -u postgres psql jatahku_db -c '\d dashboard_layouts'` (unik `uq_dashboard_layout`), lalu dengan
   token user sendiri: `GET https://api.jatahku.com/dashboard/layout` → `version: 0` dan 14 kartu;
   `POST /dashboard/data` dengan `{"items":[{"id":"a1","card":"core.kpi.jatah"}]}` → `data.a1.shape = "kpi"`.
   Lihat log `jatahku.dashboard` untuk peringatan anggaran (`journalctl -u jatahku | grep "dashboard batch"`).

## Rilis Beranda registry — Plugin B3 (Gerbang B, flag `beranda_registry_users`)
Tanpa migrasi dan tanpa paket baru. Merge PR B3 → deploy otomatis; tampilan belum berubah sampai flag diisi.
1. **Paritas angka di VPS** (hanya membaca; tidak menulis DB atau cache):
   `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m app.scripts.beranda_paritas`
   → kode keluar 0 dan baris terakhir `Gerbang B: LULUS` (semua user `ok`/`lewati`, p95 batch ≤ 500 ms).
   Keluaran tanpa nama amplop atau nominal: tempel dua baris terakhirnya di issue #140.
   Bila `beda`/`crash`: jangan lanjut; jalankan ulang untuk user itu (`--user <id>`) dan laporkan barisnya.
2. **Banding tampilan** di **laptop** (bukan VPS), akun sendiri (Chrome + `pip install playwright pillow`):
   `read -s JATAHKU_TOKEN && export JATAHKU_TOKEN` (tempel localStorage `jatahku_token`; tidak masuk riwayat shell),
   lalu `python scripts/banding_beranda.py --out /tmp/banding && unset JATAHKU_TOKEN`
   → `Tampilan: SAMA di semua lebar dan tema` (390/820/1100/1440 px, gelap dan terang).
   Di HP sungguhan: buka `jatahku.com/?beranda=lama` lalu `jatahku.com/?beranda=registry`; keduanya harus sama.
3. **Nyalakan bertahap:** `sudo -u postgres psql jatahku_db -c "INSERT INTO app_settings (key, value) VALUES
   ('beranda_registry_users', '<user_id kamu>') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"`, pakai
   sehari, lalu ulangi dengan value `*`. Tiap user pindah ke Beranda registry pada muatan Beranda berikutnya.
4. **Pantau:** `journalctl -u jatahku --since today | grep -E "dashboard (batch|penyedia|sumber)"` — `dashboard batch`
   = satu Beranda > 500 ms (baris itu menyebut tiga sumber terlama); `dashboard sumber … gagal` = endpoint lama gagal.
   `dashboard penyedia` hanya untuk kartu plugin (> 150 ms); kartu inti tidak diperingatkan per kartu, karena kartu
   inti pertama ikut menanggung muat sumber bersama.
5. **Kembali ke Beranda lama** kapan saja: value `''` (kosong). Klien membaca `enabled` di setiap muatan Beranda,
   jadi tidak perlu deploy. `BerandaLama.jsx` baru dihapus setelah `*` stabil (sesi terpisah).

## Deploy Checklist — Kredensial SMTP dari `.env` (langkah 1–2 wajib SEBELUM merge)
`app/services/email_service.py` tidak lagi memuat kredensial; semuanya dibaca dari `/opt/jatahku/.env`
(`app/core/config.py`, `SMTP_*`). Tanpa `SMTP_PASSWORD`, **semua email berhenti** (reset password, konfirmasi hapus
akun, backup, peringatan): startup mencatat peringatan "SMTP_PASSWORD kosong" dan tiap kiriman gagal di log.
`Settings` memakai `extra="ignore"`, jadi variabel ini aman diisi sebelum merge, saat kode lama masih berjalan.
Tanpa migrasi, tanpa paket baru. Urutan di bawah dibuat supaya email tidak pernah mati: kode lama memakai
password yang tertanam di kode, jadi password **belum** boleh diganti sebelum kode baru tayang.
1. Isi di `/opt/jatahku/.env` dengan password yang **sekarang** dipakai (nilai lain sudah sama dengan default):
   ```
   SMTP_PASSWORD=<password saat ini>
   ```
   Hanya bila berbeda dari default, tambahkan juga `SMTP_HOST` (localhost), `SMTP_PORT` (587), `SMTP_USER` /
   `SMTP_FROM` (noreply@jatahku.com), `SMTP_FROM_NAME` (Jatahku). Kunci yang tidak dipakai **dihapus, bukan
   dikosongkan** (`SMTP_PORT=` kosong membuat startup gagal). Cek: `sudo grep -c '^SMTP_PASSWORD=.' /opt/jatahku/.env` → 1.
2. Pastikan tidak ada peringatan saat proses membaca `.env`: `sudo -u jatahku env -i $(sudo cat /opt/jatahku/.env | grep -v '^#' | xargs) \
   /opt/jatahku/venv/bin/python -c "from app.core.config import get_settings; print(bool(get_settings().SMTP_PASSWORD))"`
   dari `/opt/jatahku/app` → `True`.
3. Merge, tunggu deploy (`api.jatahku.com/health` → `commit` baru). Log startup tidak boleh memuat
   "SMTP_PASSWORD kosong": `sudo journalctl -u jatahku --since "5 min ago" | grep -c "SMTP_PASSWORD kosong"` → 0.
4. **Ganti password** akun mail `noreply@jatahku.com` di HestiaCP (password lama pernah ter-commit di repo publik
   dan tetap ada di riwayat git, jadi harus dianggap bocor), tulis password baru ke `SMTP_PASSWORD` di `.env`, lalu
   `sudo systemctl restart jatahku`. Jeda antara ganti password dan restart = satu-satunya jendela email gagal.
5. Uji: "Lupa password?" di halaman login dengan email sendiri → email reset masuk. Bila tidak:
   `sudo journalctl -u jatahku --since "10 min ago" | grep -i "email failed"`.
6. Jangan pernah menulis kredensial di kode atau dokumen repo; repo ini publik.

## Deploy Checklist — Bagikan ke Jatahku, Bagian B (web)
Sudah jalan 29 Okt 2026 (PR #132, deploy `bc4572e`; aturan nginx `/bagikan` terpasang, batas unggah dicek). Tanpa migrasi dan tanpa paket baru (Python maupun npm): merge → deploy otomatis. Saklar
`features.receipt_inbox` tetap mati. Detail: `docs/kotak-struk.md` bagian "Web dan PWA".
1. Merge, tunggu deploy, lalu cek versi yang tayang: `api.jatahku.com/health` → `commit` baru, dan
   `https://jatahku.com/version.json` → commit yang sama (juga dicek `deploy.sh` dan workflow).
2. Uji dengan saklar mati (jendela incognito, supaya service worker lama tidak dipakai):
   - Form Catat: scan foto struk belanja biasa → baris/kartu struk seperti biasa, lalu Simpan tercatat. Tidak ada
     tombol **PDF** di samping Foto/Galeri.
   - Tidak ada banner "Bukti menunggu" di halaman mana pun, dan tidak ada tips berbagi bukti di Settings.
   - `https://jatahku.com/bagikan` dibuka langsung → hanya "Fitur ini segera hadir." (butuh nginx menyajikan
     `app.html` untuk `/bagikan`; kalau masih 404, cek lagi sesudah langkah 3).
   - Admin → Dashboard → Scan Struk → baris "Jenis dokumen: Struk belanja … · QRIS … · Transfer … · Tidak dikenali …"
     (tabel "Per penerbit" baru muncul setelah ada bukti QRIS/transfer yang dibaca saat saklar menyala).
   - Scan ulang foto struk yang baru saja tercatat → baris terblokir "Bukti ini sudah tercatat.", dan Simpan Semua
     menolak.
   - Struk dari periode lalu → "Tanggal di struk: … — di luar periode sekarang (…). Catat untuk tanggal berapa?";
     Simpan Semua meminta "Pilih tanggal catat" sampai salah satu dipilih.
   - × pada baris hasil scan → item dilewati (tab Network: `POST /kotak-struk/{id}/lewati` → 200).
   - Simpan struk hasil scan saat offline (DevTools → Offline), lalu online → tersinkron sekali (satu set transaksi).
     Ulangi dengan struk lain. Sebelum menyimpan offline, kunci **setiap** amplop di rencana kartunya (baris "Dicatat …
     1 per barang"; saran per barang bisa membagi satu struk ke beberapa amplop, mis. KOPI → Makan). Kunci dari tab
     lain supaya form tidak tertutup. Lalu: simpan offline → online (sinkron ditolak) → scan ulang foto yang sama →
     "Struk ini sudah disimpan offline dan menunggu dikirim. Cek pemberitahuan antrean offline.", tanpa baris baru →
     buka kunci → "Coba lagi semua" di pemberitahuan antrean → tercatat sekali (satu set). Bila ada amplop yang tidak
     dikunci, bagian itu tersinkron, struknya jadi tercatat, dan scan ulang menampilkan "Bukti ini sudah tercatat.".
   - HP dengan PWA terpasang (service worker lama, bukan incognito): sebelum merge, catat satu transaksi saat offline
     (masuk antrean), tutup app, dan biarkan HP tetap offline sampai deploy tayang (cek `version.json` dari perangkat
     lain). Kalau HP online lebih dulu, app atau service worker lama sudah mengirim antreannya, dan cek ini tidak
     menguji pembaruan. Sesudah deploy tayang: online-kan HP, buka app, tunggu muat ulang otomatis, lalu
     `https://jatahku.com/version.json` → commit baru, dan transaksi di antrean tetap terkirim (sekali).
3. Pasang aturan nginx `/bagikan` (file HestiaCP `nginx.ssl_conf_bagikan`): langkah dan hasil yang diharapkan ada di
   `docs/kotak-struk.md` bagian "Menyalakan saklar". Boleh langsung sesudah merge; wajib aktif sebelum PR
   `share_target`.
4. Menyalakan saklar (merge dan migrasi `e7b3d5a9c1f4`, `privacy.html` dan DPIA, laporan `eval --real-only` (bukan
   gerbang), `kotak_hari_pertama` dry-run lalu `--apply`, saklar, uji HP tanpa share, PR `share_target`, uji share,
   pemantauan 2 minggu): ikuti urutan di `docs/kotak-struk.md` bagian "Menyalakan saklar"; jangan disalin ke sini.

## Deploy Checklist — Siklus anggaran per household (2d51b9031a6b) — sudah jalan 2026-11-01
Menambah `households.payday_day` (siklus milik rumah; NULL = belum dimigrasi), `monthly_snapshots.allocated_amount` dan
`spent_amount`, beserta backfill `households.payday_day` dari anggota (owner, lalu admin, lalu yang tertua). Migrasi
**idempoten**: `lifespan` (`HOUSEHOLD_CYCLE_DDL` di `app/services/household_cycle_schema.py`) menjalankan DDL dan backfill
yang sama saat API restart, dan kolomnya nullable, jadi tidak ada jendela 500. Migrasinya tetap harus dijalankan, kalau
tidak `deploy.sh` berakhir exit 2. Riwayat snapshot lama dihitung ulang skrip terpisah (langkah 4–6), bukan migrasi.
Tanpa paket, folder, atau `.env` baru. Detail: `docs/siklus-household.md`.
Sebelum merge (aman untuk kode lama):
1. Hak tabel: restart pertama menjalankan `ALTER TABLE households` dan `ALTER TABLE monthly_snapshots` sebagai user DB
   aplikasi, jadi `jatahku` harus pemilik (`bisa_alter` = t) keduanya; kalau tidak, API gagal start (`ADD COLUMN IF NOT
   EXISTS` tetap mensyaratkan pemilik walau kolomnya sudah ada). Pakai query di checklist Kotak Struk dengan
   `IN ('households','monthly_snapshots')`. Bila ada yang bukan `jatahku`, sebagai `postgres`:
   `ALTER TABLE <tabel> OWNER TO jatahku;` sebelum merge.
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
2. `ls /opt/jatahku/app/alembic/versions/ | grep 2d51b9031a6b`; `alembic current` harus `b1d4a7c2e9f0` (Plugin B1;
   R2 dan B3 tanpa migrasi) sebelum upgrade; bila belum, jalankan checklist Plugin R1 dan B1 dulu. Checklist Plugin R2
   juga harus sudah selesai (`ruang_paritas` kode keluar 0, tanpa `beda`): siklus ini membaca keanggotaan ruang keluarga
   lewat resolver R2, dan user dengan dua ruang keluarga membuat langkah 6 dan job harian menyamakan cerminnya
   bergantian ke dua tanggal.
3. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`; `alembic current` harus
   `2d51b9031a6b`. Lalu `sudo systemctl restart jatahku` dan jalankan ulang job deploy yang gagal.
Langkah 4–6 di **hari yang sama dengan merge, sebelum job snapshot harian 00:05 (waktu server) berikutnya**, di jam
sepi yang tidak di sekitar 00:05 (skrip berjalan di proses terpisah, jadi tidak diserialkan dengan job). Job 00:05
pertama sesudah deploy menyamakan anggota household campuran **tanpa notifikasi** (hanya warning di log), dan `--apply`
sesudahnya tidak menemukan siapa pun untuk diberi tahu. Bila job itu sudah jalan lebih dulu:
`journalctl -u jatahku --since "<waktu deploy>" | grep menyimpang` mendaftar anggota yang tanggal gajiannya dipindahkan
(`payday anggota <id user> menyimpang (lama → baru)`); beri tahu mereka manual. `--apply` tetap menghitung ulang riwayat.
4. Migrasi data, dry-run: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m
   app.scripts.siklus_household` (tidak menulis apa pun). Baca daftarnya: baris `CAMPURAN` = household yang anggotanya
   beda payday dan akan disamakan ke `target`; `[usaha]` = ruang usaha (siklusnya sendiri, tidak dicerminkan ke user).
5. Cadangkan `monthly_snapshots` (`--apply` menulis ulang riwayat snapshot semua household dengan force; nilai lamanya
   tidak bisa diambil lagi tanpa ini). Baris kedua harus mencetak satu baris `TABLE DATA public monthly_snapshots`:
   ```bash
   sudo -u postgres pg_dump -Fc -t monthly_snapshots jatahku_db | sudo tee /opt/jatahku/backups/monthly_snapshots-pre-siklus.dump > /dev/null
   sudo pg_restore -l /opt/jatahku/backups/monthly_snapshots-pre-siklus.dump | grep 'TABLE DATA'
   ```
   Mengembalikannya (hanya bila perlu, di jam sepi): `TRUNCATE` lalu data dari backup, dalam **satu transaksi**, supaya
   restore yang gagal tidak meninggalkan tabel kosong; file dibaca lewat `sudo cat`, jadi `postgres` tidak perlu hak baca
   folder backup:
   ```bash
   { echo 'BEGIN; TRUNCATE monthly_snapshots;'
     sudo cat /opt/jatahku/backups/monthly_snapshots-pre-siklus.dump | sudo -u postgres pg_restore --data-only -t monthly_snapshots -f -
     echo 'COMMIT;'; } | sudo -u postgres psql -v ON_ERROR_STOP=1 -q jatahku_db > /dev/null
   ```
   Tanpa `ERROR` = berhasil. `violates foreign key constraint` = ada amplop yang dihapus sejak backup (reset data, hapus
   akun); transaksinya batal dan tabel tidak berubah. Diuji di PostgreSQL 16 (1 Nov 2026): restore identik (jumlah baris
   dan md5 isi sama), dan restore yang gagal tidak mengubah tabel.
6. Sesudah dibaca dan dicadangkan: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/python -m
   app.scripts.siklus_household --apply` (mengisi payday rumah; menghitung ulang riwayat semua household, minimal 12
   periode dan mundur sampai aktivitas pertama tiap household; menyamakan anggota; memberi tahu yang berubah). Gagal di
   tengah (traceback, exit 1) = jalankan ulang; run kedua aman. Exit 1 dengan `N error` (N > 0) di baris terakhir = ada
   error per amplop: rinciannya di log `jatahku.household_cycle` ("punya error") di atasnya; perbaiki sebabnya lalu
   jalankan ulang.
   **Yang perlu diketahui owner:** household yang tidak campuran biasanya tetap dengan angka yang sama, KECUALI bila
   periode tertutupnya diubah setelah snapshot-nya dibuat (transaksi bertanggal mundur, transaksi yang diedit atau
   dihapus, alokasi yang terlambat): recompute kini memasukkan perubahan itu, jadi sebagian saldo rollover bergeser
   (lebih benar) tanpa notifikasi. Pertimbangkan memberi tahu user.
7. Verifikasi: dua anggota satu household → `GET /user/profile` memberi `household_payday_day` yang sama;
   `sudo -u postgres psql jatahku_db -c "SELECT COUNT(*) FROM households h WHERE h.payday_day IS NULL AND EXISTS (SELECT 1
   FROM household_members m WHERE m.household_id = h.id)"` → 0; esok harinya `journalctl -u jatahku | grep menyimpang`
   kosong (job 00:05 tidak menyamakan siapa pun lagi). Bila dry-run menandai household CAMPURAN, cek dashboard anggota
   yang berubah: sisa amplop masuk akal, tanpa transaksi terhitung ganda.

## Deploy Checklist — Kotak Struk belajar lintas user (e7b3d5a9c1f4)
Tahap 1 belajar lintas user (branch `feat/kotak-belajar`, label `migrasi`): kolom `receipt_scans.layout` (JSONB NULL),
tabel `proof_rule_votes` dan `proof_rules` (indeks `ix_proof_rules_status`), API Admin `/admin/kotak/*`, bagian "Aturan
belajar" di kartu Scan Struk, perintah `app.scripts.kotak_hari_pertama`, dan langkah 3–4 job `kotak_maintenance`.
Migrasi **idempoten**: `lifespan` (`KOTAK_DDL` + `create_all`) membuat kolom dan tabel yang sama saat API restart; migrasinya
tetap harus dijalankan, kalau tidak `deploy.sh` berakhir exit 2. **Tanpa paket, folder, atau `.env` baru.** Deploy ini
tidak mengubah saklar `features.receipt_inbox`. Detail: `docs/kotak-struk.md` bagian "Belajar lintas user".
Sebelum merge (aman untuk kode lama):
1. Hak tabel: restart dari deploy (sebelum migrasi) menjalankan `KOTAK_DDL` (`ALTER TABLE receipt_scans ADD COLUMN IF NOT
   EXISTS layout`) dan `create_all` (dua tabel baru ber-FK ke `users`) sebagai user DB aplikasi, jadi `jatahku` harus
   pemilik `receipt_scans` (`bisa_alter` = t) dan boleh REFERENCES `users` (`bisa_fk` = t); kalau tidak, API gagal start.
   Pakai query di checklist Kotak Struk Bagian A dengan `IN ('receipt_scans','users','alembic_version')`. Bila ada yang
   bukan `jatahku`, sebagai `postgres`: `ALTER TABLE <tabel> OWNER TO jatahku;` sebelum merge.
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
2. Tunggu deploy (`api.jatahku.com/health` → `commit` baru; run boleh berakhir "Deploy GAGAL" karena migrasi tertinggal).
   `ls /opt/jatahku/app/alembic/versions/ | grep e7b3d5a9c1f4`; `alembic current` harus `a7e3c1f5d9b2` (Plugin H1)
   sebelum upgrade. Revisi lain = main sudah punya migrasi yang lebih baru: berhenti, `down_revision` PR ini harus
   disesuaikan dulu (satu head).
3. **`alembic upgrade head` sesudah deploy selesai** (langkah 2). Kartu Scan Struk (`GET /admin/receipt-scans/stats`
   membaca `proof_rules` untuk `rules_pending`) dan API `/admin/kotak/*` sudah jalan sejak restart deploy karena
   `lifespan` membuat tabel dan kolomnya (`create_all` + `KOTAK_DDL`), jadi migrasi ini tidak membuat apa pun lagi (IF NOT
   EXISTS) dan hanya menandai revisi: `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head`
   (bila `receipt_scans`/`users` milik `postgres`, jalankan sebagai postgres); `alembic current` harus `e7b3d5a9c1f4`.
   `sudo systemctl restart jatahku` sesudahnya mengikuti urutan umum, tidak wajib. Bila `create_all`/`KOTAK_DDL` gagal
   (biasanya hak tabel, langkah 1), API tidak start sama sekali: deploy berhenti di "API menjalankan … tidak menjawab"
   (exit 1) sebelum cek migrasi; lihat `journalctl -u jatahku`.
4. Jalankan ulang job deploy yang gagal (Actions → run itu → "Re-run failed jobs"), seperti langkah 5 "Urutan merge PR
   bermigrasi", supaya "Verifikasi versi yang tayang" memeriksa `/health` dan `version.json`.
5. Verifikasi:
   - `sudo -u postgres psql jatahku_db -c '\d proof_rules'` (unik `uq_proof_rule` pada `kind, rule_key, value`, indeks
     `ix_proof_rules_status`, FK `decided_by` ON DELETE SET NULL), `-c '\d proof_rule_votes'` (PK `kind, rule_key, value,
     user_id`, FK `user_id` ON DELETE CASCADE), dan `-c '\d receipt_scans' | grep layout` (`jsonb`).
   - Dengan token admin: `GET https://api.jatahku.com/admin/kotak/rules` → 200 dengan `counts` (`{"menunggu": 0,
     "disetujui": 0, "ditolak": 0, "dicabut": 0}` di hari pertama) dan `rules: []`; `GET /admin/receipt-scans/stats` →
     200 dengan `rules_pending`; Admin → Dashboard → Scan Struk menampilkan bagian "Aturan belajar". Token user biasa →
     403 di `/admin/kotak/rules`.
   - Sesudah menit 17 jam berikutnya: `journalctl -u jatahku --since "1 hour ago" | grep kotak_maintenance` tanpa baris
     `gagal` (langkah `purge_layouts` dan `reconcile_proof_rules`).
6. Menyalakan saklar (`privacy.html` + DPIA, laporan `eval --real-only`, `kotak_hari_pertama` dry-run lalu `--apply`,
   saklar, uji HP, PR `share_target`, pemantauan 2 minggu; rollback = saklar mati, migrasi tidak di-downgrade): ikuti
   urutan di `docs/kotak-struk.md` bagian "Menyalakan saklar"; jangan disalin ke sini.

## Deploy Checklist — Laporan berkala tahap 1 (967a27d0c15d) — sudah jalan 2026-11-05
Branch `feat/laporan-berkala` (label `migrasi`): tabel `reports` dan `report_settings`, kolom `users.email_verified_at`,
job `laporan_job` (tiap jam menit 30), API `/laporan*` dan `/user/laporan-pengaturan`, halaman `/laporan`, Pengaturan →
Laporan, dan tombol top bar "Ekspor". Migrasi **idempoten**: `lifespan` (`create_all` + `LAPORAN_DDL`) membuat tabel dan
kolom yang sama saat API restart, dan kolom `users` nullable, jadi tidak ada jendela 500; migrasinya tetap harus
dijalankan, kalau tidak `deploy.sh` berakhir exit 2. **Paket baru dan kunci `.env` baru.** Detail perilaku, batasan, dan
pemulihan: `docs/laporan-berkala.md`.
Sebelum merge (aman untuk kode lama):
1. Paket (deploy tidak meng-install paket; tanpa ini **API gagal start**, karena `main.py` mengimpor route laporan yang
   mengimpor fpdf2 dan cryptography): `sudo -u jatahku /opt/jatahku/venv/bin/pip install fpdf2==2.8.9 cryptography==50.0.2`
   (ikut terpasang: Pillow, fonttools, defusedxml). Cek:
   `sudo -u jatahku /opt/jatahku/venv/bin/python -c "import fpdf, cryptography; from fpdf.enums import EncryptionMethod; print(fpdf.__version__, cryptography.__version__, EncryptionMethod.AES_256)"`
   → `2.8.9 50.0.2 EncryptionMethod.AES_256`. Lalu `sudo systemctl restart jatahku` dan `POST /auth/login` dengan email
   asal → 401, bukan 500 (kode lama tetap jalan dengan `cryptography` baru).
2. Kunci kata sandi laporan: tambahkan `REPORT_SECRET_KEY=<kunci Fernet>` ke `/opt/jatahku/.env`, dibuat dengan
   `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` memakai python venv
   (cryptography pasti ada di sana). Tanpa menampilkan kuncinya di layar (`\n` di depan: baris terakhir `.env` yang tanpa
   akhir baris tidak tersambung dengan kunci):
   ```bash
   sudo sh -c 'printf "\nREPORT_SECRET_KEY=%s\n" "$(/opt/jatahku/venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")" >> /opt/jatahku/.env'
   sudo grep -c '^REPORT_SECRET_KEY=.' /opt/jatahku/.env   # → 1
   ```
   Isi **sekali** dan jangan diganti: kunci lain membuat kata sandi laporan yang tersimpan tak terbaca (user diminta
   mengatur ulang; rotasi di luar cakupan). Jangan pernah menulis kunci ini di repo atau log. Kode lama mengabaikannya
   (`extra="ignore"`).
3. Hak tabel: restart pertama menjalankan `create_all` (dua tabel ber-FK ke `users` dan `households`) dan `LAPORAN_DDL`
   (`ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at`) sebagai user DB aplikasi, jadi `jatahku` harus pemilik
   `users` (`bisa_alter` = t) dan boleh REFERENCES `users` dan `households` (`bisa_fk` = t); kalau tidak, API gagal start.
   Pakai query di checklist Kotak Struk Bagian A dengan `IN ('users','households','alembic_version')`. Bila ada yang
   bukan `jatahku`, sebagai `postgres`: `ALTER TABLE <tabel> OWNER TO jatahku;` sebelum merge.
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
4. Tunggu deploy (`api.jatahku.com/health` → `commit` baru; run boleh berakhir "Deploy GAGAL" karena migrasi tertinggal).
   `ls /opt/jatahku/app/alembic/versions/ | grep 967a27d0c15d`; `alembic current` harus `e7b3d5a9c1f4` (Kotak Struk
   belajar) sebelum upgrade. Masih `a7e3c1f5d9b2`: jalankan checklist "Kotak Struk belajar lintas user (e7b3d5a9c1f4)"
   dulu (migrasi ini menginduk ke sana). Revisi lain = main sudah punya migrasi yang lebih baru: berhenti,
   `down_revision` PR ini harus disesuaikan dulu (satu head).
5. `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic upgrade head` (bila `users`/`households` milik
   `postgres`, jalankan sebagai postgres); `alembic current` harus `967a27d0c15d`. Lalu `sudo systemctl restart jatahku`
   dan jalankan ulang job deploy yang gagal (langkah 5 "Urutan merge PR bermigrasi").
6. Log restart tanpa peringatan kunci: `sudo journalctl -u jatahku --since "10 min ago" | grep -c "REPORT_SECRET_KEY"` → 0
   (ada = kunci kosong atau tidak valid: kata sandi dan PDF laporan menjawab 503; perbaiki `.env`, restart).
7. Verifikasi skema: `sudo -u postgres psql jatahku_db -c '\d reports'` (unik `uq_reports_user_jenis_periode`, indeks
   `ix_reports_email_antrean`, FK `user_id` ON DELETE CASCADE dan `household_id` ON DELETE SET NULL, `data` jsonb),
   `sudo -u postgres psql jatahku_db -c '\d report_settings'` (PK `user_id`, tiga toggle `DEFAULT true NOT NULL`), dan
   kolom baru di `users` (pipa `| grep` di shell, di luar psql):
   `sudo -u postgres psql jatahku_db -c '\d users' | grep email_verified_at` → satu baris dengan tipe
   `timestamp with time zone`.
8. Uji di Postgres sungguhan dengan akun sendiri (jalur JSONB `->>` dan `FOR NO KEY UPDATE` baru diuji di PostgreSQL 16
   lokal): di desktop buka `jatahku.com/laporan` → daftar tampil (`GET /laporan` 200; kosong = "Belum ada laporan. …"),
   lalu Pengaturan → 📄 Laporan → "Atur kata sandi" → "Kata sandi laporan disimpan" dan status "Kata sandi laporan sudah
   diatur." (`PUT /user/laporan-pengaturan` 200). `journalctl -u jatahku --since "10 min ago" | grep -i laporan` tanpa
   traceback. Tombol top bar bernama "Ekspor".
9. **Laporan pertama bisa terbit di jam :30 pertama sesudah restart**, bukan menunggu gajian berikutnya: household yang
   periodenya tutup ≤ 7 hari lalu langsung mendapat laporan beserta lonceng dan Telegram (gajian tanggal 1: "Laporan
   Oktober 2026" bila tayang paling lambat 7 Nov 2026). Setelah jam :30 itu: `journalctl -u jatahku --since "1 hour ago"
   | grep -i laporan` → baris `N laporan terbit`, tanpa `gagal`/`ditunda`; bila akun sendiri ikut, buka laporannya dan
   unduh PDF: terbuka dengan kata sandi laporan, tidak tanpa kata sandi.
10. Hari gajian berikutnya ±07:30 WIB (job :30 sesudah snapshot 00:05 UTC): `journalctl -u jatahku | grep -i laporan`
    dan `/laporan` berisi laporan periode yang baru tutup. Household yang gagal dicoba ulang tiap jam selama 7 hari;
    menjalankan job manual dan mengirim ulang notifikasi: `docs/laporan-berkala.md` bagian "Pemulihan".
- **Menaikkan versi fpdf2:** `app/services/laporan/pdf.py` memakai bagian dalam fpdf2 (membersihkan cache glyph
  `SubsetMap.pick/get_glyph` dan menutup berkas font di `finally` setiap render; `StandardSecurityHandler.prepare_string`
  untuk memeriksa kata sandi). Periksa lagi keduanya, lalu jalankan `app.tests.test_laporan_pdf`, sebelum mengganti pin.
- **Rollback:** revert PR. Jangan `alembic downgrade` (membuang laporan yang sudah terbit dan kata sandi laporan); tabel
  dan kolom baru boleh tetap ada (kode lama tidak memetakannya). Sesudah revert tayang, berkas revisi `967a27d0c15d`
  hilang dari server sehingga `alembic current` gagal dan `deploy.sh` berhenti; tandai ulang ke parent-nya:
  `cd /opt/jatahku/app && sudo -u jatahku /opt/jatahku/venv/bin/alembic stamp --purge e7b3d5a9c1f4` (`--purge`
  mengosongkan `alembic_version` dulu, jadi revisi yang tak dikenal tidak dicari), lalu jalankan ulang job deploy.

## Deploy Checklist — Laporan berkala tahap 2: email (tanpa migrasi)
Branch `feat/laporan-berkala-email`: laporan yang terbit dikirim ke email terverifikasi (ringkasan tanpa nominal, PDF
berkata sandi terlampir), antrean email dengan coba ulang di dalam `laporan_job`, verifikasi email, berhenti berlangganan
satu klik, dan saklar "Kirim laporan ke email" di Pengaturan → Laporan. **Tanpa migrasi, paket, atau `.env` baru** (kolom
email sudah dibuat tahap 1), jadi tidak ada langkah alembic dan tidak ada jendela 500. Detail perilaku, batasan, dan
pemulihan: `docs/laporan-berkala.md` bagian "Email laporan" dan "Pemulihan".
Sebelum merge:
1. SMTP hidup: minta email reset password ke akun sendiri dari halaman Login ("Lupa password?") → email tiba. Tanpa
   ini tautan verifikasi dan laporan tidak terkirim (`SMTP_PASSWORD` kosong di `.env` = kiriman gagal: tombol verifikasi menjawab 502, laporan berstatus `gagal`).
2. `API_URL` dan `APP_URL` di `/opt/jatahku/.env` kosong (bawaan `https://api.jatahku.com` dan `https://jatahku.com`)
   atau berisi URL produksi itu: `sudo grep -E '^(API_URL|APP_URL)=' /opt/jatahku/.env` → tanpa keluaran, atau hanya dua
   URL tersebut. Nilai lain membuat tautan di email salah alamat.
Setelah merge:
3. Tunggu deploy hijau (`api.jatahku.com/health` → `commit` baru; `jatahku.com/version.json` → commit yang sama).
4. Pengaturan → 📄 Laporan: status "Email … belum terverifikasi." (atau banner di `/laporan`) → "Kirim tautan verifikasi" →
   "Tautan verifikasi dikirim ke …" → buka tautan di email → halaman "Verifikasi email kamu" (membukanya belum mengubah
   apa pun: Pengaturan di tab lain, dimuat ulang, masih "belum terverifikasi") → tekan "Verifikasi email" → kembali ke
   Pengaturan dengan "Email terverifikasi. Laporan berikutnya juga dikirim ke email." dan status "Email …
   terverifikasi.". Tautan yang sama dibuka lagi langsung berakhir di Pengaturan dengan pesan yang sama, tanpa halaman
   dan tanpa mengubah apa pun. Akun Google dengan email yang sama sudah terverifikasi sendiri sesudah login Google.
5. Log tanpa alamat (jalankan sesudah langkah 4, lalu lagi sesudah jam :30 yang mengirim email):
   `sudo journalctl -u jatahku --since "1 hour ago" | grep -iE "email laporan|PDF laporan"` → hanya id laporan/user,
   angka, dan teks tetap (mis. `Email laporan terkirim`, `email laporan: N terkirim, …`); tanpa traceback. Tidak ada
   alamat: `sudo journalctl -u jatahku --since "1 hour ago" | grep -iE "email laporan|PDF laporan" | grep -c '@'` → 0, dan
   `sudo journalctl -u jatahku --since "1 hour ago" | grep -i "verifikasi" | grep -c '@'` → 0.
6. Laporan pertama yang terkirim: **laporan yang terbit sebelum merge tidak pernah diemail** (`email_status` NULL, tahap 1),
   jadi tunggu laporan baru. Hari gajian berikutnya ±07:30 WIB (job :30 sesudah snapshot 00:05 UTC): email "Laporan … ·
   Jatahku" tiba di akun yang terverifikasi, badan tanpa nominal rupiah, PDF terlampir terbuka dengan kata sandi laporan
   (tidak tanpa kata sandi), tombol "Buka Laporan di Jatahku →" membuka `/laporan/<id>`. Status: `sudo -u postgres psql jatahku_db -c
   "SELECT email_status, email_alasan, COUNT(*) FROM reports WHERE terbit_at > now() - interval '2 days' GROUP BY 1, 2"`
   (`terkirim`; `dilewati` + `belum_verifikasi`/`tanpa_email`/`dimatikan` untuk yang tidak berhak; `gagal` = periksa
   SMTP, lalu "kirim ulang email" di `docs/laporan-berkala.md` bagian "Pemulihan").
7. Tautan "Berhenti berlangganan" di email: halaman "Berhenti menerima email laporan?" (membukanya tidak mengubah apa pun:
   saklar di Pengaturan masih menyala) → tombol "Berhenti berlangganan" → "Email laporan dimatikan" → saklar "Kirim
   laporan ke email" mati; nyalakan lagi di Pengaturan → menyala dan tersimpan (muat ulang halaman, tetap menyala).
- **Rollback:** revert PR. Tanpa migrasi, tidak ada yang perlu dikembalikan; kolom email di `reports` tetap ada dan tidak
  dipakai kode lama. Laporan berstatus `menunggu`/`mengirim` tidak terkirim lagi sesudah revert (kode lama tidak punya
  antrean) dan dikirim bila kode tahap 2 dipasang lagi.

## Deploy Checklist — Kotak Struk belajar tahap 2 (c9e4a7f2b5d8)
Tahap 2 belajar lintas user (branch `feat/kotak-belajar-2`, label `migrasi`): kolom `receipt_scans.sample_lines` (JSONB
NULL, lewat `KOTAK_DDL`), tabel `proof_sample_consents` dan `proof_samples` (unik `uq_proof_sample_item`, indeks
`ix_proof_samples_user_id` dan `ix_proof_samples_status`), indeks unik parsial `ux_proof_rules_satu_nilai` di
`proof_rules`, API `/user/kotak-donasi`, `/admin/kotak/samples*`, `POST /kotak-struk/{id}/aplikasi`, field opsional
`SkipIn.alasan`/`flags.ask_app`/`flags.app_logo`, langkah 5 `purge_samples` job `kotak_maintenance`, dan saklar baru
`features.kotak_donasi` (bawaan **mati**). **Tanpa paket, folder, atau `.env` baru.** Migrasi idempoten, tetapi **bukan
hanya penanda revisi**: kolom dan dua tabel baru dibuat `lifespan` saat API restart (`KOTAK_DDL` + `create_all`), indeks
`ux_proof_rules_satu_nilai` (G8: satu nilai disetujui per kunci `logo`/`arah`) **hanya** oleh `alembic upgrade head`;
sampai itu pemeriksaan NOT EXISTS di `belajar.decide` yang menjaga. Deploy ini tidak mengubah `receipt_inbox` dan tidak
menyalakan `kotak_donasi`. Detail: `docs/kotak-struk.md` bagian "Belajar lintas user" (tahap 2) dan "Donasi contoh".
Sebelum merge (aman untuk kode lama):
1. Hak tabel: restart dari deploy menjalankan `KOTAK_DDL` (`ALTER TABLE receipt_scans ADD COLUMN IF NOT EXISTS
   sample_lines`) dan `create_all` (dua tabel baru ber-FK ke `users`) sebagai user DB aplikasi, dan migrasinya membuat
   indeks di `proof_rules`: `jatahku` harus pemilik `receipt_scans` dan `proof_rules` (`bisa_alter` = t) dan boleh
   REFERENCES `users` (`bisa_fk` = t). Pakai query di checklist Kotak Struk Bagian A dengan
   `IN ('receipt_scans','proof_rules','users','alembic_version')`. Bila ada yang bukan `jatahku`, sebagai `postgres`:
   `ALTER TABLE <tabel> OWNER TO jatahku;` sebelum merge.
Setelah merge (ikuti "Urutan merge PR bermigrasi", label `migrasi`):
2. Tunggu deploy (`api.jatahku.com/health` → `commit` baru; run boleh berakhir "Deploy GAGAL" karena migrasi tertinggal).
   `ls /opt/jatahku/app/alembic/versions/ | grep c9e4a7f2b5d8`; `alembic current` harus `d7r7k4a1m9c3` (Plugin R7
   `ruang_kamus`, di atas laporan berkala `967a27d0c15d`) sebelum upgrade (bila belum, jalankan migrasi sebelumnya dulu
   sesuai checklist-nya). Revisi lain yang lebih baru = main sudah punya migrasi yang lebih baru: berhenti,
   `down_revision` PR ini harus disesuaikan dulu (satu head).
3. Pra-cek G8, tepat sebelum upgrade (sejak restart kode baru bisa membuat dan menyetujui aturan `logo`/`arah`; dua
   persetujuan bersamaan sebelum indeks ada bisa sama-sama lolos):
   `sudo -u postgres psql jatahku_db -c "SELECT kind, rule_key, count(*) FROM proof_rules WHERE status = 'disetujui' AND kind IN ('logo', 'arah') GROUP BY 1, 2 HAVING count(*) > 1"`
   → **0 baris**. Ada baris → Cabut salah satu nilai kunci itu di Admin → Scan Struk → "Aturan belajar", lalu ulangi;
   kalau tidak, `CREATE UNIQUE INDEX` di migrasi gagal.
4. **`alembic upgrade head` sesudah deploy selesai**: `cd /opt/jatahku/app && sudo -u jatahku
   /opt/jatahku/venv/bin/alembic upgrade head` (bila `receipt_scans`/`proof_rules`/`users` milik `postgres`, jalankan
   sebagai postgres); `alembic current` harus `c9e4a7f2b5d8`. Kolom dan tabelnya sudah ada (IF NOT EXISTS), migrasi
   menambah indeks G8 dan menandai revisi. `sudo systemctl restart jatahku` sesudahnya mengikuti urutan umum, tidak wajib.
   Bila `create_all`/`KOTAK_DDL` gagal (biasanya hak tabel, langkah 1), API tidak start sama sekali: deploy berhenti di
   "API menjalankan … tidak menjawab" (exit 1) sebelum cek migrasi; lihat `journalctl -u jatahku`.
5. Jalankan ulang job deploy yang gagal (Actions → run itu → "Re-run failed jobs"), seperti langkah 5 "Urutan merge PR
   bermigrasi", supaya "Verifikasi versi yang tayang" memeriksa `/health` dan `version.json`.
6. Verifikasi:
   - `sudo -u postgres psql jatahku_db -c '\d proof_samples'` (PK `id`, unik `uq_proof_sample_item` pada `item_id`,
     indeks `ix_proof_samples_user_id` dan `ix_proof_samples_status`, FK `user_id` ON DELETE CASCADE, FK `decided_by`
     ON DELETE SET NULL), `-c '\d proof_sample_consents'` (PK `user_id`, FK ON DELETE CASCADE),
     `-c '\d receipt_scans' | grep sample_lines` (`jsonb`), dan `-c '\d proof_rules'` → ada
     `"ux_proof_rules_satu_nilai" UNIQUE, btree (kind, rule_key) WHERE status = 'disetujui' AND kind IN ('logo','arah')`
     (psql menampilkannya dengan `::text` / `= ANY (ARRAY[...])`), di samping `uq_proof_rule` dan `ix_proof_rules_status`.
   - Dengan token admin: `GET https://api.jatahku.com/admin/kotak/samples` → 200 dengan `counts`
     (`{"menunggu": 0, "disetujui": 0, "ditolak": 0}` di hari pertama) dan `samples: []`; token user biasa → 403. Admin →
     Dashboard → Scan Struk menampilkan bagian "Donasi contoh" (kosong) di bawah "Aturan belajar".
   - Dengan token user biasa: `GET /user/kotak-donasi` → `{"available": false, "consented": false, "consented_at": null}`;
     `PUT /user/kotak-donasi` `{"consented": true}` → 409 "Donasi contoh belum dibuka". Settings tidak menampilkan kartu
     "Bantu Jatahku membaca bukti bayar".
   - Sesudah menit 17 jam berikutnya: `journalctl -u jatahku --since "1 hour ago" | grep kotak_maintenance` tanpa baris
     `gagal` (juga `purge_samples`).
7. **Urutan menyalakan donasi contoh** (pemilik produk; boleh kapan saja sesudah langkah 6, tidak wajib di hari merge):
   a. Pasang paragraf "Donasi contoh (opsional)" dan baris DPIA donasi (teks siap tempel di `docs/kotak-struk.md`
      "Privasi dan masa simpan"; retensi 7 hari) di file sumber `privacy.html` yang dipasang ulang `deploy.sh` dan
      salinannya di `public_html`, seperti paragraf "Belajar dari koreksi". Cek:
      `curl -s https://jatahku.com/privacy.html | grep -c "Donasi contoh"` → 1; ulangi sesudah deploy berikutnya (0 =
      paragraf tertimpa `deploy.sh`). Saklar tidak boleh menyala sebelum ini (K1).
   b. `GET /admin/settings/app_config`, lalu `PUT /admin/settings/app_config` dengan isi lama **digabung**
      `"kotak_donasi": {"web": true}` di dalam `features` (PUT mengganti seluruh nilai: jangan menimpa `receipt_inbox`
      atau kunci lain), mis. `{"features": {"receipt_inbox": {"web": true}, "kotak_donasi": {"web": true}}}`, URL-encode
      seperti di `docs/kotak-struk.md` "Saklar fitur". `GET /app/config` → `features.kotak_donasi` true;
      `GET /user/kotak-donasi` → `available: true`.
   c. Uji dengan akun uji yang menyalakan kartu Settings ("Aktif sejak {tgl}"): satu koreksi sungguhan (mis. bukti
      QRIS/transfer dicatat dengan nominal yang diubah di form Catat, atau "Bukan pengeluaran" dengan alasan yang beda
      dari bacaan) → Admin → "Donasi contoh" → tab Menunggu memuat sampel itu dengan baris tersamar (tanpa deret ≥ 6
      digit, nama yang dikenal sudah nama samaran). Tolak sampel uji itu (atau Setujui → Unduh entri korpus → Hapus
      sesudah disalin). Matikan kartu → "Dimatikan. Contoh yang belum ditinjau sudah dihapus.". Bukti yang terbaca benar
      tidak menjadi sampel; jangan dipaksakan.
   d. Sesudah itu tinjau Admin → "Donasi contoh" rutin: sampel `menunggu` dan yang disetujui terhapus 7 hari sesudah
      dibuat/diputuskan. Entri disetujui diunduh lalu ditambahkan **di checkout lokal** (`python -m
      app.scripts.kotak_corpus add --dari-donasi <berkas>`, exit 3 → `--tahan`) dan masuk lewat PR, **tidak pernah di
      VPS** (checkout deploy harus bersih).
   Log galat tahap 2 (pencatatan tidak terpengaruh): `journalctl -u jatahku --since "1 day ago" | grep -E "donasi|suara arah|jawaban aplikasi|purge_samples gagal"`.
Rollback: matikan `kotak_donasi` (`PUT /admin/settings/app_config` dengan `kotak_donasi` `web: false`, digabung dengan isi
lama): worker berhenti menangkap baris di item berikutnya, `donate` tidak menyimpan sampel (baris yang sudah tertangkap
dikosongkan saat koreksi atau oleh pemeliharaan), menyalakan di Settings → 409, kartu hanya tampil untuk user yang sudah
setuju (supaya bisa menarik). Antrean Admin tetap bisa ditinjau, diunduh, dan dihapus; `purge_samples` tetap jalan. Aturan
`logo`/`arah` yang salah: **Cabut** di Admin (berlaku di bacaan berikutnya), tanpa mematikan `receipt_inbox`. Migrasi tidak
perlu di-downgrade (downgrade hanya bermakna bersama kode lama).

## Aplikasi mobile (WAJIB untuk semua sesi mobile)
Dokumen: `docs/mobile/` (mulai dari `00-indeks.md`; keputusan di `02-adr.md`). Buka sesi dengan `/sesi <kode>`, tutup dengan `/tutup-sesi`. Satu paket = satu branch `mobile/<wbs>-*` = satu PR; status di `docs/mobile/PROGRESS.md`, serah-terima di `docs/mobile/SESI-LOG.md`.
1. **Satu bundle, satu UI.** Web, Android, iOS memakai `frontend/` yang sama. Perbedaan platform hanya di `frontend/src/native/`; komponen tidak boleh memeriksa `Capacitor`, user agent, `display-mode`, atau hostname.
2. **API hanya bertambah.** Field/endpoint lama tidak dihapus atau diubah artinya sebelum `min_supported_version` di `/app/config` dinaikkan dan user melihat banner pembaruan. Berlaku juga untuk sesi non-mobile begitu aplikasi pertama terpasang di HP user. Dicek otomatis di setiap PR oleh workflow "Cek API" (`.github/workflows/openapi.yml`); jalankan lokal dengan `python -m app.scripts.openapi_cek`.
3. **Aplikasi selalu menyebut dirinya** lewat header `X-Jatahku-Client: <platform>/<versi>/<build>`; server mengubah perilaku berdasarkan header ini, tidak pernah berdasarkan tebakan.
4. **Jualan diatur server.** Tombol, tautan, dan teks ajakan beli (termasuk pesan kuota bot) datang dari satu helper yang membaca mode jualan per platform; teks "upgrade" tidak ditulis langsung di komponen atau handler.
5. **Tidak ada transaksi yang hilang.** Di aplikasi, antrean offline disimpan di penyimpanan native; item yang ditolak tetap disimpan.
6. **Rahasia hanya di Keychain/Keystore.** Di aplikasi, token tidak disimpan di `localStorage`, IndexedDB, item antrean, atau URL.
7. **Proyek native di-commit dan di-review.** `mobile/android/` dan `mobile/ios/` tidak dibuat ulang saat build dan tidak ditambal skrip.
8. **OTA hanya untuk web.** Bundle OTA hanya berisi build `frontend/` + versi native minimum; perubahan plugin, izin, atau kode native lewat rilis toko.
9. **Identitas tidak pernah berubah.** ID aplikasi `com.jatahku.app`, origin/skema Capacitor, dan kunci penandatanganan (ADR-M3–M5) hanya berubah dengan keputusan tertulis pemilik produk.
10. **Paritas diuji, bukan diasumsikan.** Daftar periksa paritas (`01-kajian.md`, lampiran WBS) dijalankan di perangkat nyata sebelum setiap rilis toko, termasuk satu Android kelas bawah.
11. **Struk tidak pernah tercatat diam-diam atau dua kali.** Dokumen dari share, unggahan, atau Telegram selalu menunggu konfirmasi user; hash file, nomor referensi, dan `client_ref` mencegah pencatatan ganda; transfer gagal tidak bisa dicatat.

## Plugin dan ruang (WAJIB untuk semua sesi plugin)
Dokumen: `docs/plugin/` (mulai dari `00-indeks.md`; keputusan di `02-adr.md`, bentuk API di `04-kontrak-api.md`). Buka sesi dengan `/sesi-plugin <kode>`, tutup dengan `/tutup-sesi-plugin`. Satu sesi = satu branch `plugin/<kode>-<slug>` = satu PR berjudul `Plugin <kode>: <nama>`; status di `docs/plugin/PROGRESS.md`, serah-terima di `docs/plugin/SESI-LOG.md`. PR berlabel `review-keamanan` direview sesi Claude Code terpisah sebelum merge, dan temuan keamanan dikerjakan sebelum fitur dilanjutkan.
1. **Ruang dari server, bukan dari klien.** Membaca memakai `ruang_aktif` (header `X-Jatahku-Ruang`). Menulis objek yang sudah ada atau yang punya induk menentukan ruang dari objek itu (`ruang_amplop`, `ruang_amplop_satu`, `ruang_objek` di `app/services/ruang.py`), lalu memeriksa keanggotaan; objek ruang lain = 404, dua ruang dalam satu permintaan = 400 `lintas_ruang`. Objek baru tanpa induk memakai ruang dari header yang sah (`ruang_aktif`). `ruang_id` dari body atau query tidak pernah dipercaya. Route menerima ruang header sebagai parameter keyword-only `*, hid: RuangAktif` dan meneruskannya ke services sebagai `household_id`; services tidak pernah mencari household dari keanggotaan sendiri. Kueri `HouseholdMember.user_id == …` baru dan route non-GET baru yang memakai `ruang_aktif` dijaga `app/tests/test_ruang_pagar.py`.
2. **Chat selalu ruang keluarga.** Handler bot memakai `ruang_keluarga(user)`. Tidak ada transaksi ruang usaha atau Fitur Tambahan lewat chat; perintah plugin hanya membaca dan menyatakan `audience` (data keuangan usaha hanya untuk pemilik dan admin).
3. **Batasan peran ditegakkan di server** pada setiap jalur tulis: web, aplikasi, antrean offline (`/transactions/batch`), dan kirim ulang (`client_ref`). Frontend hanya menampilkan. Karyawan (peran `member` di ruang usaha) memakai **tolak-bawaan** (R5): `ruang_aktif` hanya mengizinkan route di `KARYAWAN_BOLEH`, dan pembantu ruang objek (`ruang_objek`, `ruang_amplop`, `ruang_amplop_satu`) menolak karyawan kecuali dipanggil dengan `karyawan=True` (hanya jalur pencatatan: catat/hapus transaksi, pemasukan). Route baru otomatis tertolak untuk karyawan; membukanya butuh alasan dan tes di `app/tests/test_ruang_peran.py`. Beranda karyawan (R6): `/dashboard/*` ada di `KARYAWAN_BOLEH` dan menyaring per kartu dengan `registry.boleh` (kartu `untuk="karyawan"` hanya untuk karyawan, kartu umum tidak pernah); kartu baru yang memuat angka ruang selalu `untuk="umum"`. Tes di `app/tests/test_ruang_r6.py`. Batasan per catatan, jam kerja, jendela ubah, dan draf persetujuan hanya di `app/services/peran.py`.
4. **Plugin hanya lewat `PluginContext`.** Kode di `app/plugins/<id>/` tidak mengimpor model atau route inti dan tidak menulis ke tabel inti secara langsung. Sejak H2: kode plugin hanya mengimpor nama publik `app.plugins.sdk` (`from app.plugins.sdk import …`), paketnya sendiri, plugin di `requires`, dan pustaka di daftar izin `PUSTAKA_BOLEH`; introspeksi, atribut `_`/dunder milik objek lain, serta menambal atau menurunkan kelas SDK ditolak (diperiksa AST oleh validator CI **sebelum** kodenya dijalankan, `app/plugins/host/kode.py`). Fungsi didaftarkan lewat `plugin = Plugin("<id>")`; setiap fungsi harus tercantum di manifest dengan `izin=` bagian dari `permissions` dan dari izin jenisnya (`IZIN_PER_JENIS`: hanya baca, kecuali job yang boleh `notifications:send`). Saat dipanggil, `PluginContext` hanya membuka izin yang disetujui saat pasang ∩ manifest ∩ `izin=` fungsi ∩ izin jenisnya, membaca lewat `visibility.py` (di ruang keluarga hanya pemasukan milik viewer), menolak data keuangan untuk karyawan, mengirim hanya dari job, dan mencatat penolakan serta kiriman yang sampai di `plugin_audit_log`. Keadaan konteks (sesi DB, ruang, peran, izin) dan pemeriksaan izin ada di host (`app/plugins/host/keadaan.py`), dan konteks ditutup sesudah setiap fungsi plugin (`titik.panggil`) serta hanya berlaku di task asyncio pembuatnya (konteks yang disimpan plugin tidak berlaku lagi); kelas `PluginContext` dan `Plugin` tidak bisa ditambal atau diturunkan; `viewer` hanya `PenggunaView` dan periode kartu `PeriodeView`, tidak pernah objek ORM atau objek bersama. Inti memanggil plugin hanya lewat `app/plugins/host/titik.py`, yang memakai `siklus.aktif_dengan_instalasi` (plugin dijeda, dicopot, saklar darurat, atau di luar flag tidak meninggalkan apa pun) dan kembali seketika tanpa kueri bila belum ada plugin yang menyumbang ke titik itu. Kartu plugin selalu kartu `umum` (R6): karyawan tidak pernah memuat datanya. Di web (H3): yang tampil dari plugin hanya yang ada di `GET /plugins/contributions` (menu, aksi cepat, rute `/p/<id>`, kartu); karyawan tidak mendapat kontribusi apa pun. Kode web plugin ada di `frontend/src/plugins/<id>/` dan didaftarkan di `PLUGIN_WEB` (`src/plugins/index.js`), selalu `React.lazy` dan ikut bundle (tidak pernah diunduh per plugin, aturan mobile 8); tautan plugin hanya ke `/p/<id>…`. Pemasangan lewat layar izin mengirim daftar izin yang dilihat (`izin`, 409 `izin_berubah`). **Endpoint plugin (U1):** `@plugin.rute(metode, pola)` + manifest `routes`, dilayani host di `/p/<id>/…` (`titik.jalankan_rute`): ruang dari header (`ruang_aktif`), plugin harus aktif di ruang itu untuk user itu (`terpasang` hanya GET, untuk wizard), karyawan 403; body ≤ 64 KB, jawaban dirapikan (`Decimal` → string, float ditolak). Data plugin hanya lewat `ctx.data("<entitas>")` (`app/plugins/host/data.py`): selalu ruang konteks, hapus lunak, tulis hanya dari rute non-GET dan diaudit (`data:tambah|ubah|hapus` tanpa nilai); plugin tidak pernah memegang sesi DB atau model. Wizard pasang (manifest `setup`) = komponen `wizard` di modul web plugin; amplop bawaan dibuat klien lewat API inti atas nama user. **Tulis inti (U2):** satu-satunya jalan adalah `ctx.catat_pemasukan` (`incomes:write`, `app/plugins/host/inti.py`): hanya rute non-GET, owner/admin dengan user pemicu, amplop aktif ruang konteks, pembagian persis = jumlah, lewat `incomes.catat_pemasukan(commit=False)` sehingga pemasukan + data plugin + audit masuk satu commit route `/p` (langkah sesudah-commit lewat `app/services/setelah_commit.py`). Izin tulis inti lain tidak ada di `IZIN_PER_JENIS`. Izin baru di manifest tidak pernah diberikan diam-diam: `izin_baru` di katalog, persetujuan `POST /ruang/{id}/plugins/{pid}/izin` (409 `izin_berubah`). **Field form (U2):** `tambahan` di `POST /transactions/` diperiksa `titik.periksa_field` sebelum apa pun disimpan (karyawan 422) dan disimpan `@plugin.simpan_field(target)` (hanya `ctx.data()`) sesudah flush dan sebelum commit; gagal = transaksi batal. `select` wajib `options` di manifest. **Review #201:** isian plugin ditolak untuk pengeluaran pribadi (amplop `owner_id` atau `is_private`); tulis pemasukan plugin idempoten lewat `client_ref` (Redis, lingkup per plugin dan ruang; kunci dilepas lewat `setelah_commit.titip_gagal`); pasang/pulihkan plugin berizin tulis wajib membawa daftar izin yang dilihat (`IZIN_TULIS`); tabel pendamping 1:1 data inti tidak kena `BATAS_BARIS_RUANG` (`data.pendamping_inti`). **Angka dan laporan (U3):** angka plugin diambil lewat agregat `ctx.ringkas_transaksi` / `ctx.ringkas_pemasukan` (`app/plugins/host/ringkas.py`, dijumlah database, gagal bila > 1.000 kelompok, tidak pernah memotong), bukan menjumlah baris `ctx.transactions()`/`ctx.incomes()` yang dibatasi 1.000; kelompok dan `meta` tabel pendamping untuk transaksi privat orang lain selalu `None`. Berkas unduhan plugin hanya lewat `Laporan` dari rute GET, digambar host (`app/plugins/host/berkas.py`: PDF fpdf2, CSV `_csv_text`) dan dikirim sebagai lampiran (nosniff, CSP sandbox, no-store, audit `laporan`); kode plugin tidak pernah membuat byte berkas sendiri.
5. **Tabel plugin** memakai awalan `p_<id>_`, kolom wajib (`id`, `household_id`, `created_by`, `created_at`, `updated_at`, `deleted_at`), indeks diawali `household_id`, enum sebagai `String`, JSON lewat `JSON().with_variant(JSONB(), "postgresql")`, dan tidak ada DDL saat plugin dipasang (tabel dibuat migrasi). Sejak U1: model tabel plugin ada di `app/models/models.py` (`PluginTabelMixin`, ikut `alembic check`), dideklarasikan di manifest `entities`, dan aturan di atas ditegakkan validator (`data.aturan_tabel`, saat memuat registry dan di `test_plugin_u1`); id plugin tidak boleh menjadi awalan id plugin lain dan setiap entitas milik satu plugin (`periksa_antarplugin`, review #196); FK ke inti hanya `households`, `users`, `envelopes`, `transactions`, `incomes` (meta 1:1 CASCADE, `created_by` SET NULL). Hapus permanen hanya oleh host: baris hapus lunak > 30 hari (`data.bersihkan_terhapus`, job `plugin_jobs` tiap jam), pembersih arsip 90 hari (`siklus.bersihkan_kedaluwarsa` → `data.hapus_data_ruang`; manifest tidak dimuat = baris instalasi dibiarkan), hapus ruang dan hapus akun (`account_deletion.py` → `hapus_semua_data_ruang`, `hapus_rujukan`, `lepas_pembuat`); ekspor `GET /ruang/{id}/plugins/{plugin_id}/ekspor` (JSON, CSV-ZIP dengan escape PR #136) boleh di semua status sesudah terpasang.
6. **Satu sumber angka.** Angka Buku Usaha hanya dihitung di `app/plugins/buku_usaha/metrics.py`; kartu, laporan, chat, dan AI Advisor membacanya, frontend hanya memformat. Angka inti tetap dari `app/services/advisor/metrics.py` dan layanan yang sudah ada.
7. **Teks dari templat.** Kalimat untuk web, chat web, dan Telegram dirakit dari templat yang sama, seperti aturan `render.py` di AI Advisor.
8. **Tidak ada kueri lintas ruang** selain Prive (`POST /prive`, `app/api/routes/prive.py`: asal dari amplop, hanya owner ruang usaha; tujuan selalu ruang keluarga pemanggil; dua sisi `incomes.kind = prive` dalam satu commit lewat `fund_shift.record_prive`). Data, kamus kata, dan saran dari ruang keluarga tidak pernah dipakai di ruang usaha, dan sebaliknya. Kontrak visibilitas household (`visibility.py`) tetap berlaku di dalam setiap ruang. Kamus ruang (R7, `RuangKamus`): hanya dibaca untuk ruang usaha yang sedang dicari (`txn_nlp.cari_amplop`, gerbang jenis ruang di kueri) dan hanya ditulis dari catatan web bukan-privat ke amplop bersama ruang usaha (`save_learned_keywords(kamus_ruang=True)`; bot dan Kotak Struk tidak). Tawaran "pengeluaran pribadi" di Catat cepat bukan kueri lintas ruang: klien membuat permintaan terpisah tanpa header ruang (ruang keluarga user sendiri), dan server tidak menyimpannya.
9. **Ekspor memakai escape dari PR #136** (HTML, CSP, anti formula-injection) untuk setiap laporan dan CSV baru. Laporan plugin otomatis memenuhinya lewat `host/berkas.py` (U3).
- **Flag (AppSetting, daftar `user_id` atau `*`):** `beranda_registry_users` (B2–B3), `ruang_usaha_users` (sejak R4), `plugin_buku_usaha_users` (sejak U1, kosong = tidak ada yang bisa memasang; umumnya `plugin_<id>_users`, dibaca host); saklar darurat `plugin_saklar_darurat` (H1, daftar id plugin). Yang belum siap selalu di balik flag, karena merge ke `main` berarti deploy produksi.
- **Migrasi:** sesi bertanda migrasi memberi label `migrasi`, menambah checklist deploy di file ini, dan mengikuti "Urutan merge PR bermigrasi"; workflow "Migrasi" harus hijau.
