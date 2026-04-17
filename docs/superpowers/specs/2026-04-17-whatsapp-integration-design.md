# WhatsApp Integration Design — Jatahku
**Date:** 2026-04-17  
**Status:** Approved  
**Scope:** Core bot features via self-hosted WAHA (WhatsApp HTTP API)

---

## 1. Overview

Tambah channel WhatsApp ke Jatahku menggunakan WAHA (self-hosted WhatsApp Web API via Docker). User bisa catat transaksi, cek status budget, lihat amplop, dan login WebApp via WA — tanpa mengubah kode Telegram yang sudah berjalan.

**Tidak berubah:** Telegram bot, semua routes, NLP parser.

---

## 2. Arsitektur

```
WhatsApp User
     │ kirim pesan
     ▼
[WAHA Docker :3000]  ──webhook POST──▶  /api/webhook/whatsapp
     ▲                                        │
     │ REST API sendText                       ▼
     └──────────────────────────── app/bot/wa_handlers.py
                                              │
                                    parse_amount()  ◄── import dari handlers.py
                                    category matching
                                              │
                                    DB / Redis / existing API logic
```

**Komponen baru:**
- `app/bot/wa_handlers.py` — semua logic pesan WA masuk
- `app/api/routes/webhook.py` — tambah `POST /webhook/whatsapp`
- `app/api/routes/link.py` — tambah endpoints linking WA
- `/opt/jatahku/docker-compose.waha.yml` — WAHA Docker setup
- 2 kolom baru di `users` table: `whatsapp_id`, `phone`

---

## 3. Database Changes

Tambah 2 kolom ke model `User` (`app/models/models.py`):

```python
whatsapp_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

Alembic migration diperlukan. Kedua kolom nullable dan tidak breaking.

---

## 4. Account Linking — Hybrid

### Flow A: Code Exchange (primary)
1. User ketik `/link` di WA
2. Bot generate kode 6 digit, simpan di Redis: `link:whatsapp:{code}` → `whatsapp_id` (TTL 300 detik)
3. User buka WebApp Settings → masukkan kode
4. WebApp panggil `POST /link/whatsapp` → simpan `whatsapp_id` ke user

### Flow B: Phone Auto-link (secondary)
1. User simpan nomor HP di WebApp Settings (field baru `phone`)
2. Saat pesan WA masuk dan user belum ter-link, cek `user.phone` vs nomor pengirim
3. Jika cocok → auto-link `whatsapp_id`, kirim notifikasi konfirmasi ke user

### Unlink
- `POST /link/unlink-whatsapp` — set `whatsapp_id = None`
- Tersedia di WebApp Settings

---

## 5. Bot Commands & Fitur

| Input | Behaviour |
|---|---|
| `kopi 35k` / `35k makan siang` | NLP parse → pilih amplop (tombol teks) → konfirmasi → catat transaksi |
| `/status` | Ringkasan budget: dana dialokasi, terpakai, sisa, per amplop |
| `/amplop` | List semua amplop dengan emoji, nama, sisa budget |
| `/webapp` | Generate magic link token → kirim URL login WebApp |
| `/link` | Mulai flow code exchange linking |
| Pesan tidak dikenal | Kirim pesan bantuan singkat |

**Format respons:** plain text + emoji (WA tidak support Markdown formatting seperti Telegram). Contoh:

```
💰 Budget bulan ini:
Dana: Rp2.500.000
Terpakai: Rp1.200.000
Sisa: Rp1.300.000

🍽️ Makan: Rp400k / Rp600k
🚗 Transport: Rp200k / Rp300k
```

### Pemilihan Amplop via Teks
WA tidak punya inline keyboard seperti Telegram. Saat NLP parse berhasil dan ada multiple amplop, bot kirim numbered list:

```
"kopi 35k" — pilih amplop:
1. ☕ Jajan/Kopi
2. 🍽️ Makan
3. 💼 Lainnya

Balas dengan nomor (1/2/3)
```

State pilihan disimpan di Redis sementara (TTL 2 menit): `wa:pending:{whatsapp_id}`.

---

## 6. WAHA Setup

```yaml
# /opt/jatahku/docker-compose.waha.yml
services:
  waha:
    image: devlikeapro/waha
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - /opt/jatahku/waha-sessions:/app/.sessions
    environment:
      - WHATSAPP_HOOK_URL=https://jatahku.com/api/webhook/whatsapp
      - WHATSAPP_HOOK_EVENTS=message
      - WAHA_DASHBOARD_ENABLED=true
```

- Port 3000 hanya bind ke `127.0.0.1` — tidak expose ke internet
- Session WA disimpan di `/opt/jatahku/waha-sessions` (persistent volume)
- WAHA Dashboard tersedia via SSH tunnel untuk scan QR saat setup awal

**Setup awal:**
1. `docker compose -f docker-compose.waha.yml up -d`
2. Akses WAHA dashboard via SSH tunnel: `ssh -L 3000:localhost:3000 user@67.217.58.13`
3. Buka `http://localhost:3000` → scan QR dengan nomor WA khusus Jatahku
4. Session aktif dan persistent

**Nomor WA:** Harus nomor tersendiri (bukan nomor pribadi). Bisa SIM card murah atau nomor eSIM.

---

## 7. Webhook Security

WAHA mengirim webhook tanpa signature default. Proteksi dengan `WAHA_API_KEY`:

```yaml
# docker-compose.waha.yml
environment:
  - WAHA_API_KEY=<random-secret>
  - WHATSAPP_HOOK_URL=https://jatahku.com/api/webhook/whatsapp
```

FastAPI endpoint validasi header `X-Api-Key` vs `settings.WAHA_API_KEY`. Jika tidak cocok → return 403. Sama polanya dengan `TELEGRAM_WEBHOOK_SECRET` yang sudah ada.

---

## 8. New API Endpoints

```
POST /webhook/whatsapp          — terima pesan dari WAHA
POST /link/whatsapp             — claim link code dari WebApp
POST /link/unlink-whatsapp      — unlink WA dari WebApp
GET  /link/whatsapp-status      — cek apakah user sudah ter-link
```

---

## 9. Out of Scope (v1)

- Behavior controls via WA (cooling period, lock, daily limit settings)
- Household invite via WA
- Subscription management via WA
- Group chat support
- Media/voice message parsing

---

## 10. File Changes Summary

| File | Perubahan |
|---|---|
| `app/models/models.py` | Tambah `whatsapp_id`, `phone` ke User |
| `app/bot/wa_handlers.py` | **Baru** — semua WA message handling |
| `app/api/routes/webhook.py` | Tambah `POST /webhook/whatsapp` |
| `app/api/routes/link.py` | Tambah 3 endpoints WA linking |
| `app/core/config.py` | Tambah `WAHA_URL`, `WAHA_API_KEY` settings |
| `frontend/src/pages/Settings.jsx` | Tambah WA linking UI + phone field |
| `frontend/src/lib/api.js` | Tambah WA link/unlink/status methods |
| `/opt/jatahku/docker-compose.waha.yml` | **Baru** — WAHA Docker config |
| Alembic migration | `whatsapp_id`, `phone` columns |
