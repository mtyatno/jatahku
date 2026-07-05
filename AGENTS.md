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
- Located at `/opt/jatahku/app/deploy.sh` on server
- Runs on push to main via GitHub Actions
- Git repo is at `/opt/jatahku/app/` NOT `/opt/jatahku/`
- Must clean dirty `frontend/dist/` before `git pull`:
  ```bash
  sudo -u jatahku git checkout -- frontend/dist/ 2>/dev/null || true
  ```
- Landing page preservation: backup to `/opt/jatahku/backups/` each deploy
- Deploy fails silently when dist files conflict with repo
- Run as `jatahku` user for git operations, `sudo` for file copies

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

## Enum vs String in Python
- `PurposeType.expense` (enum member) does NOT equal `"expense"` (string)
- Always convert with `str(value)` before comparison: `str(getattr(obj, "field", "default"))`
- This applies to all SAEnum/String columns

## Advisor Insights Engine
- Located at `app/services/advisor.py` — `build_advisor_insights()`
- Card types: `env_depletion` (expense), `saving_progress` (saving), `sinking_fund_deadline` (sinking_fund)
- Do NOT wrap advisor route in silent try/except — hides real errors
- Advisor needs `load_advisor_context` to load envelope stats
- New envelopes without spending history still get stats (all zeros) — they won't generate cards but won't crash either

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
