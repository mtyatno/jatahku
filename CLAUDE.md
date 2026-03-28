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
- `services/` — behavior.py, merge.py, rollover.py, scheduler.py, summary.py, recurring_processor.py, notification_service.py, email_service.py, plan_limits.py

**Frontend:** `/opt/jatahku/frontend/`
- `src/pages/` — Dashboard, Envelopes, Transactions, Allocate, Langganan, Settings, Login, Analytics, Admin, Upgrade
- `src/components/` — Layout, Onboarding, ExportButtons, NotificationBell, TelegramPrompt
- `src/hooks/useAuth.jsx`, `src/lib/api.js`, `src/lib/utils.js`

**Static pages:** landing.html, privacy.html, terms.html, og-image.png

## Key Decisions
- Zero-based budgeting: remaining = allocated - spent (not budget - spent)
- Sinking fund: subscriptions auto-reserve monthly equivalent in envelope
- Free (allocated - spent - reserved) = truly available to spend
- NLP: "kopi 35k", "rp17.000", "sewa server 250k tiap bulan" all work
- Redis key prefix: `link:webapp:{code}`, `txn:{key}`, `sub:{key}`
- Scheduler: hourly per-user timezone-aware dispatch
- DMARC: `none` (not quarantine) for inbox delivery
- SMTP: localhost:587 with auth (noreply@jatahku.com)

## Pricing
- Basic: 6 envelopes, 50 txn/month, 5 subscriptions, household enabled
- Pro (Rp79k one-time): unlimited everything + behavior controls + export + analytics
- First 100 users: free Pro promotion (all 29 current users are Pro)
- Household sharing: basic user can use shared envelopes from pro user

## Deploy
- Push to main → GitHub Actions → SSH deploy → /opt/jatahku/deploy.sh
- Manual: `sudo /opt/jatahku/deploy.sh`
- Frontend builds to `/home/jatahku/web/jatahku.com/public_html/`
- Nginx: landing.html at /, app.html for React SPA routes
- Backend: systemd `jatahku.service` → uvicorn port 8000

## Current Stats
- 29 users, 3 TG linked, Rp88.8jt managed
- All sessions (1-10) complete
