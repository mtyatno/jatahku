# Jatahku — Setiap Rupiah Ada Jatahnya

Aplikasi pengendali keuangan berbasis **envelope budgeting** untuk Indonesia.

🌐 **Website:** [jatahku.com](https://jatahku.com)
📱 **Telegram Bot:** [@JatahkuBot](https://t.me/JatahkuBot)

## Fitur

- ✉️ **Envelope Budgeting** — Zero-based, setiap rupiah punya tujuan
- ⏳ **Cooling Period** — 24 jam hold untuk belanja impulsif
- 🔒 **Envelope Lock & Daily Limit** — Kontrol pengeluaran
- 📱 **Telegram Bot NLP** — Catat via chat: "kopi 35k"
- 👨‍👩‍👧 **Household Sharing** — Budget bersama keluarga
- 🔄 **Sinking Fund** — Auto-reserve untuk langganan
- 📊 **Analytics & Prediksi** — Chart + spending prediction
- 🔔 **Notifikasi** — Telegram + WebApp + Email
- 📦 **Export** — CSV & laporan HTML

## Tech Stack

- **Backend:** FastAPI + PostgreSQL + Redis
- **Frontend:** React + Vite + Tailwind CSS + Recharts
- **Bot:** python-telegram-bot + NLP parser
- **Infrastructure:** Ubuntu 24.04, Nginx, HestiaCP
- **Email:** Exim4 SMTP (DKIM + SPF + DMARC)

## Architecture
```
jatahku.com (landing) ─── React SPA (WebApp)
                             │
api.jatahku.com ──────── FastAPI ──── PostgreSQL
                             │            │
@JatahkuBot ─────────── Telegram Bot    Redis
                             │
                         APScheduler
                     (summaries, recurring)
```

## Setup
```bash
# Clone
git clone https://github.com/mtyatno/jatahku.git
cd jatahku

# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your config
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run build
```

## Deploy

Push to `main` triggers auto-deploy via GitHub Actions.

Manual: `ssh server && /opt/jatahku/deploy.sh`

## API Docs

FastAPI auto-docs: `https://api.jatahku.com/docs`

## License

MIT

---

**Jatahku** — Bukan pencatat pengeluaran. Pengendali keuangan.
