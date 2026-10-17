# Jatahku — Setiap Rupiah Ada Jatahnya

Aplikasi pengendali keuangan berbasis **envelope budgeting** untuk Indonesia.

🌐 **Website:** [jatahku.com](https://jatahku.com)
📱 **Telegram Bot:** [@JatahkuBot](https://t.me/JatahkuBot)

## Fitur

- ✦ **AI Advisor** — Analisa + tombol aksi di Beranda (chip di tiap KPI + kartu advisor), Amplop, Transaksi, Alokasi, Langganan, chat web, dan Telegram. Mesin aturan deterministik di server (tanpa LLM pihak ketiga), satu sumber angka untuk semua permukaan. Pemindahan dana selalu lewat rencana + konfirmasi.
- ✉️ **Envelope Budgeting** — Zero-based, setiap rupiah punya tujuan
- ⏳ **Cooling Period** — 24 jam hold untuk belanja impulsif
- 🔒 **Envelope Lock & Daily Limit** — Kontrol pengeluaran
- 📱 **Telegram Bot NLP** — Catat via chat: "kopi 35k"; tanya "kapan habis?", "kenapa boros?", "aman beli sepatu 450rb?"
- 💬 **Chat di WebApp** — Handler bot yang sama, langsung dari web
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

**AI Advisor v2** (`app/services/advisor/`): `snapshot.py` (loader DB) → `metrics.py` (satu-satunya rumus angka periode) → `signals.py` → `rules/*` → `select.py` → `render.py` (semua teks) → `dashboard.py` / `halaman.py` / `chat.py`. Perencana dana: `planner.py` + `execute.py`. Spesifikasi & alur kerja: [`docs/ai-advisor/`](docs/ai-advisor/00-indeks.md); aturan kerja di `AGENTS.md`.

## Setup
```bash
# Clone
git clone https://github.com/mtyatno/jatahku.git
cd jatahku

# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Buat .env berisi variabel di app/core/config.py (DATABASE_URL, REDIS_URL, JWT_SECRET, TELEGRAM_BOT_TOKEN, ...)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run build
```

## Tes
```bash
pip install -r requirements.txt -r requirements-test.txt
python -m unittest discover -s app/tests -t .
cd frontend && node --test src/lib/*.test.js && npm run build
```
CI (`.github/workflows/test.yml`) menjalankan ketiganya di setiap PR.

## Deploy

Push to `main` triggers auto-deploy via GitHub Actions.

Manual: `ssh server && /opt/jatahku/deploy.sh`

## API Docs

FastAPI auto-docs: `https://api.jatahku.com/docs`

## License

MIT

---

**Jatahku** — Bukan pencatat pengeluaran. Pengendali keuangan.
