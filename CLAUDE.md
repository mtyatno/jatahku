# Jatahku — Project Context

## Identity
- **App:** Jatahku (jatahku.com) — Indonesian envelope budgeting + behavior control
- **Tagline:** "Setiap rupiah ada jatahnya"
- **Stack:** FastAPI + React/Vite + PostgreSQL + Redis + Telegram Bot
- **VPS:** Ubuntu 24.04, 4GB RAM, 2TB HDD, IP 67.217.58.13, HestiaCP
- **GitHub:** https://github.com/mtyatno/jatahku

## Code Structure
**Backend:** `/opt/jatahku/app/app/`
- `main.py` — FastAPI entry, CORS, rate limiting, security headers
- `core/` — config, database, security, deps
- `models/models.py` — All SQLAlchemy models (User, Envelope, Transaction, Allocation, Income, RecurringTransaction, Notification, NotificationPreference, PaymentOrder, PromoCode, AppSetting, etc.)
- `api/routes/` — auth, envelopes, transactions, incomes, link, snapshots, household, export, recurring, analytics, notifications, user_settings, admin, payment, health
- `bot/handlers.py` — Telegram bot: NLP parser, commands, inline keyboards, Redis-backed callbacks
- `bot/help_cmd.py, link_cmd.py, behavior_cmd.py, recurring_cmd.py, household_cmd.py`
- `bot/web_adapter.py` + `bot/channel.py` + `api/routes/bot_chat.py` — chat bot di webapp memakai handler bot yang sama (lihat `docs/chat-bot-web.md`); perintah/tombol baru didaftarkan di `bot_commands()`/`bot_callbacks()`
- `services/` — behavior.py, merge.py, rollover.py, scheduler.py, summary.py, recurring_processor.py, notification_service.py, email_service.py, plan_limits.py

**Frontend:** `/opt/jatahku/frontend/`
- `src/pages/` — Dashboard, Envelopes, Transactions, Allocate, Langganan, Settings, Login, Analytics, Admin, Upgrade
- `src/components/` — Layout, Onboarding, ExportButtons, NotificationBell, TelegramPrompt
- `src/hooks/useAuth.jsx`, `src/lib/api.js`, `src/lib/utils.js`

**Static pages:** landing.html, privacy.html, terms.html, og-image.png

## Aplikasi mobile (Android & iOS)
- Rencana, ADR, workflow, progres: `docs/mobile/` (mulai `00-indeks.md`). Aturan wajib: `AGENTS.md` bagian "Aplikasi mobile". Buka sesi `/sesi <kode>`, tutup `/tutup-sesi`.

## Key Decisions
- Zero-based budgeting: remaining = allocated - spent (not budget - spent)
- Sinking fund: subscriptions auto-reserve monthly equivalent in envelope
- Free (allocated - spent - reserved) = truly available to spend
- NLP: "kopi 35k", "rp17.000", "sewa server 250k tiap bulan" all work
- Redis key prefix: `link:webapp:{code}`, `txn:{key}`, `sub:{key}`
- Scheduler: hourly per-user timezone-aware dispatch
- DMARC: `none` (not quarantine) for inbox delivery
- SMTP: localhost:587 with auth (noreply@jatahku.com); kredensial hanya di `/opt/jatahku/.env` (`SMTP_*`, lihat `app/core/config.py`), tidak pernah di kode — repo ini publik

## Pricing
- Basic: 6 envelopes, 50 txn/month, 5 subscriptions, household enabled
- Basic txn quota is checked once at the START of an input (web save, bot message): an input started under quota always finishes, even past 50 (receipt per item, multi-item, resends of failed parts via `quota_pass`), then the user is told the quota is used up until the 1st of next month. Next inputs are refused. See `services/plan_limits.py`, `services/quota_pass.py`
- Pro (Rp79k one-time): unlimited everything + behavior controls + export + analytics
- First 100 users: free Pro promotion (all 29 current users are Pro)
- Household sharing: basic user can use shared envelopes from pro user

## Deploy
- Push to main → GitHub Actions → SSH deploy → /opt/jatahku/deploy.sh
- Deploys are queued (`concurrency` in `.github/workflows/deploy.yml`): a push during a running deploy waits for it, so several sessions can merge safely. Manual `deploy.sh` runs are not queued — don't start one while an Actions deploy is running.
- Manual: `sudo /opt/jatahku/deploy.sh`
- Frontend builds to `/home/jatahku/web/jatahku.com/public_html/`
- Nginx: landing.html at /, app.html for React SPA routes
- Backend: systemd `jatahku.service` → uvicorn port 8000
- Verifikasi: `api.jatahku.com/health` → `commit` yang berjalan; `jatahku.com/version.json` → commit build web (dicek otomatis oleh deploy.sh & workflow)

## Current Stats
- 29 users, 3 TG linked, Rp88.8jt managed
- All sessions (1-10) complete
