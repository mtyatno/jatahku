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
7. **Saklar `features.receipt_inbox` tetap mati** sampai gerbang korpus A14 lulus: `cd /opt/jatahku/app && sudo -u jatahku
   /opt/jatahku/venv/bin/python -m app.scripts.kotak_corpus eval --real-only` (kode keluar 0; `docs/kotak-struk.md` bagian
   "Alat korpus dan gerbang rilis"). Menyalakannya = keputusan pemilik produk.

## Deploy Checklist — Plugin R1: model ruang (1c7e5a9d3b20)
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

## Deploy Checklist — Siklus anggaran per household (2d51b9031a6b)
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
2. `ls /opt/jatahku/app/alembic/versions/ | grep 2d51b9031a6b`; `alembic current` harus `b1d4a7c2e9f0` (Plugin B1)
   sebelum upgrade; bila belum, jalankan checklist Plugin R1 dan B1 dulu.
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

## Deploy Checklist — Plugin B1: `dashboard_layouts` (b1d4a7c2e9f0)
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
4. Menyalakan saklar (gerbang A14, batas unggah `api.jatahku.com`, keputusan hari pertama, saklar, uji HP tanpa share,
   PR `share_target`, uji share): ikuti urutan di `docs/kotak-struk.md` bagian "Menyalakan saklar"; jangan disalin ke
   sini.

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
1. **Ruang dari server, bukan dari klien.** Membaca memakai `ruang_aktif(user, request)` (header `X-Jatahku-Ruang`); menulis menentukan ruang dari objek yang ditulis, lalu memeriksa keanggotaan. `ruang_id` dari body atau query tidak pernah dipercaya.
2. **Chat selalu ruang keluarga.** Handler bot memakai `ruang_keluarga(user)`. Tidak ada transaksi ruang usaha atau Fitur Tambahan lewat chat; perintah plugin hanya membaca dan menyatakan `audience` (data keuangan usaha hanya untuk pemilik dan admin).
3. **Batasan peran ditegakkan di server** pada setiap jalur tulis: web, aplikasi, antrean offline (`/transactions/batch`), dan kirim ulang (`client_ref`). Frontend hanya menampilkan.
4. **Plugin hanya lewat `PluginContext`.** Kode di `app/plugins/<id>/` tidak mengimpor model atau route inti dan tidak menulis ke tabel inti secara langsung.
5. **Tabel plugin** memakai awalan `p_<id>_`, kolom wajib (`id`, `household_id`, `created_by`, `created_at`, `updated_at`, `deleted_at`), indeks diawali `household_id`, enum sebagai `String`, JSON lewat `JSON().with_variant(JSONB(), "postgresql")`, dan tidak ada DDL saat plugin dipasang (tabel dibuat migrasi).
6. **Satu sumber angka.** Angka Buku Usaha hanya dihitung di `app/plugins/buku_usaha/metrics.py`; kartu, laporan, chat, dan AI Advisor membacanya, frontend hanya memformat. Angka inti tetap dari `app/services/advisor/metrics.py` dan layanan yang sudah ada.
7. **Teks dari templat.** Kalimat untuk web, chat web, dan Telegram dirakit dari templat yang sama, seperti aturan `render.py` di AI Advisor.
8. **Tidak ada kueri lintas ruang** selain Prive. Data, kamus kata, dan saran dari ruang keluarga tidak pernah dipakai di ruang usaha, dan sebaliknya. Kontrak visibilitas household (`visibility.py`) tetap berlaku di dalam setiap ruang.
9. **Ekspor memakai escape dari PR #136** (HTML, CSP, anti formula-injection) untuk setiap laporan dan CSV baru.
- **Flag (AppSetting, daftar `user_id` atau `*`):** `beranda_registry_users` (B2–B3), `ruang_usaha_users` (sejak R4), `plugin_buku_usaha_users` (sejak U1); saklar darurat plugin (H1). Yang belum siap selalu di balik flag, karena merge ke `main` berarti deploy produksi.
- **Migrasi:** sesi bertanda migrasi memberi label `migrasi`, menambah checklist deploy di file ini, dan mengikuti "Urutan merge PR bermigrasi"; workflow "Migrasi" harus hijau.
