# WhatsApp Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WhatsApp as a second messaging channel for Jatahku using self-hosted WAHA, supporting NLP transaction input, /status, /amplop, /webapp, and hybrid account linking.

**Architecture:** WAHA Docker container on the same VPS receives WhatsApp messages and forwards them as webhooks to a new `POST /webhook/whatsapp` endpoint. A standalone `wa_handlers.py` module handles routing and shares NLP/DB logic with the Telegram bot. Account linking uses a 6-digit code exchange (primary) or phone number auto-match (secondary).

**Tech Stack:** WAHA (devlikeapro/waha Docker image), FastAPI, httpx (already in requirements), Redis, SQLAlchemy async, Alembic.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/core/config.py` | Modify | Add WAHA_URL, WAHA_API_KEY settings |
| `app/models/models.py` | Modify | Add `whatsapp_id`, `phone` to User |
| `alembic/versions/<hash>_add_whatsapp_fields.py` | Create | DB migration for new columns |
| `app/bot/wa_handlers.py` | Create | All WA message handling logic |
| `app/api/routes/webhook.py` | Modify | Add `POST /webhook/whatsapp` endpoint |
| `app/api/routes/link.py` | Modify | Add WA link/unlink/status/phone endpoints |
| `app/core/phone.py` | Create | Phone number normalization utility |
| `frontend/src/lib/api.js` | Modify | Add WA link/unlink/status/phone methods |
| `frontend/src/pages/Settings.jsx` | Modify | Add WA linking UI section |
| `/opt/jatahku/docker-compose.waha.yml` | Create | WAHA Docker Compose config |

---

## Task 1: Config + Phone Utility

**Files:**
- Modify: `app/core/config.py`
- Create: `app/core/phone.py`

- [ ] **Step 1: Add WAHA settings to config.py**

In `app/core/config.py`, add after the Telegram block:

```python
# WhatsApp (WAHA)
WAHA_URL: str = "http://localhost:3000"
WAHA_API_KEY: str = ""
WAHA_SESSION: str = "default"
```

- [ ] **Step 2: Create phone normalization utility**

Create `app/core/phone.py`:

```python
import re


def normalize_phone(phone: str) -> str:
    """Normalize phone to 62xxxxxxxxx format (digits only).

    Handles: +62xxx, 62xxx, 08xxx, 8xxx
    Returns empty string if input has fewer than 7 digits.
    """
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return ""
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif not digits.startswith("62"):
        digits = "62" + digits
    return digits


def chat_id_to_phone(chat_id: str) -> str:
    """Extract phone from WAHA chat_id format '628xxx@c.us'."""
    return chat_id.replace("@c.us", "").replace("@s.whatsapp.net", "")
```

- [ ] **Step 3: Verify normalization logic manually**

```python
# Quick sanity check — run in Python REPL:
# python -c "from app.core.phone import normalize_phone; print(normalize_phone('08123456789'))"
# Expected: 628123456789
# python -c "from app.core.phone import normalize_phone; print(normalize_phone('+6281234'))"
# Expected: 6281234
```

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py app/core/phone.py
git commit -m "feat: add WAHA config settings and phone normalization utility"
```

---

## Task 2: Database Model + Migration

**Files:**
- Modify: `app/models/models.py`
- Create: `alembic/versions/<hash>_add_whatsapp_fields.py`

- [ ] **Step 1: Add columns to User model**

In `app/models/models.py`, find the User class. After the `telegram_id` line:

```python
telegram_id: Mapped[str | None] = mapped_column(
    String(50), unique=True, index=True
)
```

Add:

```python
whatsapp_id: Mapped[str | None] = mapped_column(
    String(50), unique=True, index=True, nullable=True
)
phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run on the VPS (or locally if DB is accessible):

```bash
cd /opt/jatahku/app
source ../venv/bin/activate
alembic revision --autogenerate -m "add whatsapp fields to users"
```

- [ ] **Step 3: Review generated migration file**

Open the generated file in `alembic/versions/`. It should contain:

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('whatsapp_id', sa.String(50), nullable=True))
    op.create_index(op.f('ix_users_whatsapp_id'), 'users', ['whatsapp_id'], unique=True)
    op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))

def downgrade() -> None:
    op.drop_column('users', 'phone')
    op.drop_index(op.f('ix_users_whatsapp_id'), table_name='users')
    op.drop_column('users', 'whatsapp_id')
```

If autogenerate missed anything, edit manually to match the above.

- [ ] **Step 4: Run migration on VPS**

```bash
cd /opt/jatahku/app
source ../venv/bin/activate
alembic upgrade head
```

Expected output ends with: `Running upgrade <prev_hash> -> <new_hash>, add whatsapp fields to users`

- [ ] **Step 5: Commit**

```bash
git add app/models/models.py alembic/versions/
git commit -m "feat: add whatsapp_id and phone columns to users table"
```

---

## Task 3: WA Link Backend Routes

**Files:**
- Modify: `app/api/routes/link.py`

These endpoints are mounted at `/auth` prefix (see `main.py` line 50), so final paths are:
- `POST /auth/link/whatsapp`
- `POST /auth/link/unlink-whatsapp`
- `GET /auth/link/whatsapp-status`
- `PUT /auth/link/whatsapp-phone`

- [ ] **Step 1: Add imports at top of link.py**

Find the existing imports block in `app/api/routes/link.py` and add:

```python
from app.core.phone import normalize_phone
```

- [ ] **Step 2: Add WA link endpoint — claim code from WebApp**

At the bottom of `app/api/routes/link.py`, add:

```python
# ── WhatsApp linking ──

class LinkWhatsAppRequest(BaseModel):
    code: str


@router.post("/link/whatsapp")
async def link_whatsapp_account(
    req: LinkWhatsAppRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """WebApp submits code generated by WA bot to complete linking."""
    r = await _redis()
    raw = await r.get(f"link:whatsapp:{req.code}")
    await r.close()

    if not raw:
        raise HTTPException(status_code=400, detail="Kode tidak valid atau sudah expired")

    whatsapp_id = raw.decode()

    # Check if this WA number is already linked to another user
    existing = await db.execute(select(User).where(User.whatsapp_id == whatsapp_id))
    existing_user = existing.scalar_one_or_none()
    if existing_user and str(existing_user.id) != str(user.id):
        raise HTTPException(status_code=400, detail="Nomor WhatsApp sudah terhubung ke akun lain")

    user.whatsapp_id = whatsapp_id
    await db.commit()

    r = await _redis()
    await r.delete(f"link:whatsapp:{req.code}")
    await r.close()

    return {"status": "linked"}


@router.post("/link/unlink-whatsapp")
async def unlink_whatsapp(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.whatsapp_id:
        raise HTTPException(status_code=400, detail="WhatsApp belum terhubung")
    user.whatsapp_id = None
    await db.commit()
    return {"status": "unlinked"}


@router.get("/link/whatsapp-status")
async def whatsapp_status(user: User = Depends(get_current_user)):
    return {
        "linked": bool(user.whatsapp_id),
        "whatsapp_id": user.whatsapp_id,
        "phone": user.phone,
    }


class SavePhoneRequest(BaseModel):
    phone: str


@router.put("/link/whatsapp-phone")
async def save_whatsapp_phone(
    req: SavePhoneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save phone number for auto-link when WA message arrives."""
    normalized = normalize_phone(req.phone)
    if not normalized:
        raise HTTPException(status_code=400, detail="Format nomor tidak valid")
    user.phone = normalized
    await db.commit()
    return {"status": "saved", "phone": normalized}
```

- [ ] **Step 3: Verify routes compile**

```bash
cd /opt/jatahku/app
source ../venv/bin/activate
python -c "from app.api.routes.link import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/api/routes/link.py
git commit -m "feat: add WhatsApp link/unlink/status/phone endpoints"
```

---

## Task 4: WA Webhook Endpoint

**Files:**
- Modify: `app/api/routes/webhook.py`

- [ ] **Step 1: Add WhatsApp webhook endpoint**

In `app/api/routes/webhook.py`, add after the existing Telegram endpoints:

```python
@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receive messages from WAHA and dispatch to WA handler."""
    # Validate API key
    if settings.WAHA_API_KEY:
        key = request.headers.get("X-Api-Key", "")
        if not hmac.compare_digest(key, settings.WAHA_API_KEY):
            return Response(status_code=403)

    try:
        data = await request.json()
        from app.bot.wa_handlers import handle_wa_message
        await handle_wa_message(data)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"WA webhook error: {e}", exc_info=True)
        return Response(status_code=200)
```

- [ ] **Step 2: Verify webhook.py compiles**

```bash
cd /opt/jatahku/app
source ../venv/bin/activate
python -c "from app.api.routes.webhook import router; print('OK')"
```

Expected: `OK` (wa_handlers doesn't exist yet — this will fail until Task 5. Skip if not ready.)

- [ ] **Step 3: Commit**

```bash
git add app/api/routes/webhook.py
git commit -m "feat: add POST /webhook/whatsapp endpoint with API key validation"
```

---

## Task 5: WA Bot Core (wa_handlers.py)

**Files:**
- Create: `app/bot/wa_handlers.py`

This file handles all incoming WA messages. It imports shared logic from `handlers.py` and `nlp_cmd.py`.

- [ ] **Step 1: Create wa_handlers.py with WAHA client and user lookup**

Create `app/bot/wa_handlers.py`:

```python
import re
import secrets
import logging
import json as json_mod
from datetime import date
from decimal import Decimal

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, func

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.phone import normalize_phone, chat_id_to_phone
from app.models.models import (
    User, Household, HouseholdMember, HouseholdRole,
    Envelope, Transaction, TransactionSource,
)
from app.bot.handlers import (
    parse_amount, find_best_envelope, get_household_id,
    get_envelopes_with_spent, format_currency, save_learned_keywords,
)
from app.bot.nlp_cmd import parse_multi_expense

settings = get_settings()
logger = logging.getLogger("jatahku.wa")


# ── WAHA client ───────────────────────────────────────────────────────────────

async def waha_send(chat_id: str, text: str) -> None:
    """Send a text message via WAHA REST API. Fire-and-forget — errors are logged, not raised."""
    if not settings.WAHA_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.WAHA_URL}/api/sendText",
                json={"chatId": chat_id, "text": text, "session": settings.WAHA_SESSION},
                headers={"X-Api-Key": settings.WAHA_API_KEY} if settings.WAHA_API_KEY else {},
            )
    except Exception as e:
        logger.warning(f"waha_send failed to {chat_id}: {e}")


# ── Redis helper ──────────────────────────────────────────────────────────────

async def _redis():
    return aioredis.from_url(settings.REDIS_URL)


# ── User lookup + auto-link ───────────────────────────────────────────────────

async def get_wa_user(chat_id: str, db) -> User | None:
    """Look up user by whatsapp_id. If not found, try phone auto-link."""
    result = await db.execute(select(User).where(User.whatsapp_id == chat_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    # Phone auto-link: extract phone from chat_id and match against user.phone
    phone = chat_id_to_phone(chat_id)
    if phone:
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if user:
            user.whatsapp_id = chat_id
            await db.commit()
            await db.refresh(user)
            await waha_send(chat_id,
                f"✅ Akun otomatis terhubung ke {user.name}!\n\n"
                "Sekarang kamu bisa catat pengeluaran di sini. Contoh: kopi 35k"
            )
            return user

    return None


async def get_or_create_wa_user(chat_id: str, db) -> User:
    """Get existing user or return None (WA users must link first, unlike TG)."""
    return await get_wa_user(chat_id, db)
```

- [ ] **Step 2: Add /status command handler**

Append to `app/bot/wa_handlers.py`:

```python
# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_status(chat_id: str, user: User) -> None:
    async with AsyncSessionLocal() as db:
        hid = await get_household_id(user, db)
        if not hid:
            await waha_send(chat_id, "⚠️ Setup budget dulu di jatahku.com")
            return
        envs = await get_envelopes_with_spent(hid, db, user_id=user.id, payday_day=user.payday_day or 1)

    if not envs:
        await waha_send(chat_id, "Belum ada amplop. Buat dulu di jatahku.com")
        return

    total_alloc = sum(e["allocated"] for e in envs)
    total_spent = sum(e["spent"] for e in envs)
    total_free = sum(e["free"] for e in envs)

    lines = ["💰 Budget bulan ini:\n"]
    lines.append(f"Dana     {format_currency(total_alloc)}")
    lines.append(f"Terpakai {format_currency(total_spent)}")
    lines.append(f"Sisa     {format_currency(total_free)}\n")

    for e in envs:
        env = e["envelope"]
        emoji = env.emoji or "📁"
        lines.append(f"{emoji} {env.name}: {format_currency(e['spent'])} / {format_currency(e['allocated'])}")

    await waha_send(chat_id, "\n".join(lines))


async def handle_amplop(chat_id: str, user: User) -> None:
    async with AsyncSessionLocal() as db:
        hid = await get_household_id(user, db)
        if not hid:
            await waha_send(chat_id, "⚠️ Setup budget dulu di jatahku.com")
            return
        envs = await get_envelopes_with_spent(hid, db, user_id=user.id, payday_day=user.payday_day or 1)

    if not envs:
        await waha_send(chat_id, "Belum ada amplop. Buat dulu di jatahku.com")
        return

    lines = ["📋 Amplop aktif:\n"]
    for e in envs:
        env = e["envelope"]
        emoji = env.emoji or "📁"
        sisa = e["free"]
        lines.append(f"{emoji} {env.name}  sisa {format_currency(sisa)}")

    await waha_send(chat_id, "\n".join(lines))


async def handle_webapp(chat_id: str, user: User) -> None:
    token = secrets.token_urlsafe(32)
    r = await _redis()
    await r.set(f"tglogin:{token}", str(user.id), ex=300)
    await r.close()
    login_url = f"{settings.APP_URL}/auth/tg?token={token}"
    await waha_send(chat_id,
        f"🔐 Login ke Jatahku WebApp\n\n"
        f"Buka link ini:\n{login_url}\n\n"
        f"Berlaku 5 menit dan hanya sekali pakai."
    )


async def handle_link(chat_id: str) -> None:
    """Generate 6-digit code for WebApp to claim."""
    code = str(secrets.randbelow(900000) + 100000)
    r = await _redis()
    await r.set(f"link:whatsapp:{code}", chat_id, ex=300)
    await r.close()
    await waha_send(chat_id,
        f"Kode link WhatsApp kamu: *{code}*\n\n"
        f"Langkah:\n"
        f"1. Buka jatahku.com/settings\n"
        f"2. Scroll ke bagian WhatsApp\n"
        f"3. Masukkan kode di atas\n\n"
        f"Berlaku 5 menit."
    )


async def handle_unknown(chat_id: str) -> None:
    await waha_send(chat_id,
        "Perintah yang tersedia:\n\n"
        "Catat pengeluaran: ketik langsung, misal 'kopi 35k'\n"
        "Multi: tiap baris = satu transaksi\n\n"
        "/status  - ringkasan budget\n"
        "/amplop  - daftar amplop\n"
        "/webapp  - login ke WebApp\n"
        "/link    - hubungkan akun"
    )
```

- [ ] **Step 3: Commit progress so far**

```bash
git add app/bot/wa_handlers.py
git commit -m "feat: add wa_handlers.py with WAHA client, user lookup, and core commands"
```

---

## Task 6: WA Bot Single Transaction

**Files:**
- Modify: `app/bot/wa_handlers.py`

- [ ] **Step 1: Add single expense handler**

Append to `app/bot/wa_handlers.py`:

```python
# ── Single transaction ────────────────────────────────────────────────────────

async def handle_single_expense(chat_id: str, user: User, amount: Decimal, description: str) -> None:
    """NLP parsed one transaction — find envelope or ask."""
    async with AsyncSessionLocal() as db:
        hid = await get_household_id(user, db)
        if not hid:
            await waha_send(chat_id, "⚠️ Setup budget dulu di jatahku.com")
            return

        envelope, confident = await find_best_envelope(description, hid, db, user_id=user.id)

        if envelope and confident:
            db.add(Transaction(
                user_id=user.id,
                envelope_id=envelope.id,
                amount=amount,
                description=description,
                transaction_date=date.today(),
                source=TransactionSource.webapp,
            ))
            await save_learned_keywords(user.id, description, envelope.id, db)
            await db.commit()
            await waha_send(chat_id,
                f"✅ {envelope.emoji or '📁'} {envelope.name}: {format_currency(amount)} — {description}"
            )
            return

        # Need to ask — get all envelopes for numbered list
        env_result = await db.execute(
            select(Envelope).where(Envelope.household_id == hid, Envelope.is_active == True)
            .order_by(Envelope.created_at)
        )
        all_envs = env_result.scalars().all()
        env_list = [{"id": str(e.id), "name": e.name, "emoji": e.emoji or "📁"} for e in all_envs]

    if not env_list:
        await waha_send(chat_id, "Belum ada amplop. Buat dulu di jatahku.com")
        return

    # Build numbered list, pre-select best guess at top if partially confident
    lines = [f'"{description}" — masuk ke amplop mana?\n']
    for i, env in enumerate(env_list, 1):
        lines.append(f"{i}. {env['emoji']} {env['name']}")
    lines.append("\nBalas dengan nomor (1/2/3...)")

    # Store pending state in Redis
    r = await _redis()
    await r.set(f"wa:pending:{chat_id}", json_mod.dumps({
        "amount": int(amount),
        "desc": description,
        "envs": env_list,
        "user_id": str(user.id),
    }), ex=120)
    await r.close()

    await waha_send(chat_id, "\n".join(lines))


async def handle_envelope_reply(chat_id: str, user: User, choice: int, raw: bytes) -> None:
    """User replied with a number to select envelope for a pending single transaction."""
    data = json_mod.loads(raw.decode())
    env_list = data["envs"]

    # Delete pending state
    r = await _redis()
    await r.delete(f"wa:pending:{chat_id}")
    await r.close()

    if choice == 0 or choice > len(env_list):
        await waha_send(chat_id, f"❌ Pilih angka antara 1 dan {len(env_list)}")
        return

    chosen = env_list[choice - 1]
    amount = Decimal(str(data["amount"]))
    description = data["desc"]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Envelope).where(Envelope.id == chosen["id"]))
        envelope = result.scalar_one_or_none()
        if not envelope:
            await waha_send(chat_id, "❌ Amplop tidak ditemukan")
            return

        db.add(Transaction(
            user_id=user.id,
            envelope_id=envelope.id,
            amount=amount,
            description=description,
            transaction_date=date.today(),
            source=TransactionSource.webapp,
        ))
        await save_learned_keywords(user.id, description, envelope.id, db)
        await db.commit()

    await waha_send(chat_id,
        f"✅ {chosen['emoji']} {chosen['name']}: {format_currency(amount)} — {description}"
    )
```

- [ ] **Step 2: Commit**

```bash
git add app/bot/wa_handlers.py
git commit -m "feat: add WA single transaction handler with envelope selection"
```

---

## Task 7: WA Bot Multi-input Batch

**Files:**
- Modify: `app/bot/wa_handlers.py`

- [ ] **Step 1: Add multi-expense handler**

Append to `app/bot/wa_handlers.py`:

```python
# ── Multi-input batch ─────────────────────────────────────────────────────────

async def handle_multi_expense(chat_id: str, user: User, items: list) -> None:
    """Process multi-expense input. Auto-record matched, queue unmatched."""
    async with AsyncSessionLocal() as db:
        hid = await get_household_id(user, db)
        if not hid:
            await waha_send(chat_id, "⚠️ Setup budget dulu di jatahku.com")
            return

        env_result = await db.execute(
            select(Envelope).where(Envelope.household_id == hid, Envelope.is_active == True)
            .order_by(Envelope.created_at)
        )
        all_envs = env_result.scalars().all()
        env_list = [{"id": str(e.id), "name": e.name, "emoji": e.emoji or "📁"} for e in all_envs]

        recorded = []
        unmatched = []
        for amount, description in items:
            envelope, _ = await find_best_envelope(description, hid, db, user_id=user.id)
            if envelope:
                db.add(Transaction(
                    user_id=user.id,
                    envelope_id=envelope.id,
                    amount=amount,
                    description=description,
                    transaction_date=date.today(),
                    source=TransactionSource.webapp,
                ))
                await save_learned_keywords(user.id, description, envelope.id, db)
                recorded.append((amount, description, envelope))
            else:
                unmatched.append({"amount": int(amount), "desc": description})

        if recorded:
            await db.commit()

    auto_lines = [
        f"{e.emoji or '📁'} {e.name}: {format_currency(a)} — {d}"
        for a, d, e in recorded
    ]

    if not unmatched:
        total = sum(a for a, _, _ in recorded)
        lines = [f"✅ {len(recorded)} transaksi dicatat\n"] + auto_lines
        lines.append(f"\n💸 Total: {format_currency(total)}")
        await waha_send(chat_id, "\n".join(lines))
        return

    # Store batch queue in Redis
    r = await _redis()
    await r.set(f"wa:batch:{chat_id}", json_mod.dumps({
        "queue": unmatched,
        "auto_lines": auto_lines,
        "user_id": str(user.id),
        "envs": env_list,
    }), ex=600)
    await r.close()

    await _ask_batch_item(chat_id, unmatched, 0, auto_lines, env_list)


async def _ask_batch_item(chat_id: str, queue: list, idx: int, auto_lines: list, env_list: list) -> None:
    item = queue[idx]
    header = ("\n".join(auto_lines) + "\n" + "─" * 20 + "\n") if auto_lines else ""
    progress = f" ({idx + 1}/{len(queue)})" if len(queue) > 1 else ""

    lines = [f"{header}💰 {format_currency(item['amount'])} — {item['desc']}{progress}"]
    lines.append("Masuk ke amplop mana?\n")
    for i, env in enumerate(env_list, 1):
        lines.append(f"{i}. {env['emoji']} {env['name']}")
    lines.append(f"{len(env_list) + 1}. ⏭ Lewati")
    lines.append("\nBalas dengan nomor")

    await waha_send(chat_id, "\n".join(lines))


async def handle_batch_reply(chat_id: str, user: User, choice: int, raw: bytes) -> None:
    """User replied with a number for an item in the batch queue."""
    data = json_mod.loads(raw.decode())
    queue = data["queue"]
    auto_lines = data["auto_lines"]
    env_list = data["envs"]

    # Find current unresolved index (first item without env_id set)
    idx = next((i for i, item in enumerate(queue) if "env_id" not in item), None)
    if idx is None:
        r = await _redis()
        await r.delete(f"wa:batch:{chat_id}")
        await r.close()
        return

    item = queue[idx]
    skip_value = len(env_list) + 1

    if choice == skip_value:
        # Skip this item
        queue[idx]["env_id"] = None  # mark resolved, skipped
    elif 1 <= choice <= len(env_list):
        chosen = env_list[choice - 1]
        amount = Decimal(str(item["amount"]))

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Envelope).where(Envelope.id == chosen["id"]))
            envelope = result.scalar_one_or_none()
            if envelope:
                db.add(Transaction(
                    user_id=user.id,
                    envelope_id=envelope.id,
                    amount=amount,
                    description=item["desc"],
                    transaction_date=date.today(),
                    source=TransactionSource.webapp,
                ))
                await save_learned_keywords(user.id, item["desc"], envelope.id, db)
                await db.commit()

        queue[idx]["env_id"] = chosen["id"]
        auto_lines = auto_lines + [f"{chosen['emoji']} {chosen['name']}: {format_currency(amount)} — {item['desc']}"]
        data["auto_lines"] = auto_lines
    else:
        await waha_send(chat_id, f"❌ Pilih angka antara 1 dan {skip_value}")
        return

    data["queue"] = queue

    # Find next unresolved
    next_idx = next((i for i, item in enumerate(queue) if "env_id" not in item), None)

    if next_idx is None:
        # All done
        r = await _redis()
        await r.delete(f"wa:batch:{chat_id}")
        await r.close()
        lines = ["✅ Semua item selesai!\n"] + auto_lines
        await waha_send(chat_id, "\n".join(lines))
    else:
        # Update Redis and ask next
        r = await _redis()
        await r.set(f"wa:batch:{chat_id}", json_mod.dumps(data), ex=600)
        await r.close()
        await _ask_batch_item(chat_id, queue, next_idx, auto_lines, env_list)
```

- [ ] **Step 2: Commit**

```bash
git add app/bot/wa_handlers.py
git commit -m "feat: add WA multi-input batch handler matching Telegram behaviour"
```

---

## Task 8: Main Message Router

**Files:**
- Modify: `app/bot/wa_handlers.py`

- [ ] **Step 1: Add the main handle_wa_message router**

Append to `app/bot/wa_handlers.py`:

```python
# ── Main router ───────────────────────────────────────────────────────────────

async def handle_wa_message(payload: dict) -> None:
    """Entry point from webhook. Routes to appropriate handler."""
    event = payload.get("event")
    msg = payload.get("payload", {})

    # Only process incoming text messages
    if event != "message":
        return
    if msg.get("fromMe"):
        return
    if msg.get("type") != "chat":
        return

    chat_id = msg.get("from", "")
    text = msg.get("body", "").strip()

    if not chat_id or not text:
        return

    logger.info(f"WA message from {chat_id}: {text[:50]}")

    # Command routing
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        async with AsyncSessionLocal() as db:
            user = await get_wa_user(chat_id, db)

        if cmd == "/link":
            await handle_link(chat_id)
            return

        if not user:
            await waha_send(chat_id,
                "Akun kamu belum terhubung.\n\n"
                "Ketik /link untuk dapat kode, lalu masukkan di jatahku.com/settings."
            )
            return

        if cmd == "/status":
            await handle_status(chat_id, user)
        elif cmd == "/amplop":
            await handle_amplop(chat_id, user)
        elif cmd == "/webapp":
            await handle_webapp(chat_id, user)
        else:
            await handle_unknown(chat_id)
        return

    # NLP path — user must be linked
    async with AsyncSessionLocal() as db:
        user = await get_wa_user(chat_id, db)

    if not user:
        await waha_send(chat_id,
            "👋 Halo!\n\n"
            "Untuk catat pengeluaran, hubungkan akun dulu.\n"
            "Ketik /link untuk mulai."
        )
        return

    # Check for pending number replies (single or batch)
    r = await _redis()
    pending_raw = await r.get(f"wa:pending:{chat_id}")
    batch_raw = await r.get(f"wa:batch:{chat_id}")
    await r.close()

    if text.isdigit():
        n = int(text)
        if batch_raw:
            await handle_batch_reply(chat_id, user, n, batch_raw)
            return
        if pending_raw:
            await handle_envelope_reply(chat_id, user, n, pending_raw)
            return

    # Multi-input check
    multi_items = parse_multi_expense(text)
    if multi_items:
        await handle_multi_expense(chat_id, user, multi_items)
        return

    # Single transaction
    parsed = parse_amount(text)
    if parsed:
        amount, description = parsed
        await handle_single_expense(chat_id, user, amount, description)
        return

    await handle_unknown(chat_id)
```

- [ ] **Step 2: Verify full wa_handlers.py compiles**

```bash
cd /opt/jatahku/app
source ../venv/bin/activate
python -c "from app.bot.wa_handlers import handle_wa_message; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify webhook.py compiles with wa_handlers in place**

```bash
python -c "from app.api.routes.webhook import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/bot/wa_handlers.py
git commit -m "feat: add WA message router (handle_wa_message entry point)"
```

---

## Task 9: WAHA Docker Setup

**Files:**
- Create: `/opt/jatahku/docker-compose.waha.yml`

This file lives on the VPS, not in the git repo (contains env vars that should go in `.env`).

- [ ] **Step 1: Create docker-compose.waha.yml on VPS**

SSH into VPS and run:

```bash
cat > /opt/jatahku/docker-compose.waha.yml << 'EOF'
services:
  waha:
    image: devlikeapro/waha
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - /opt/jatahku/waha-sessions:/app/.sessions
    environment:
      - WAHA_API_KEY=CHANGE_THIS_TO_RANDOM_SECRET
      - WHATSAPP_HOOK_URL=https://jatahku.com/api/webhook/whatsapp
      - WHATSAPP_HOOK_EVENTS=message
      - WAHA_DASHBOARD_ENABLED=true
      - WAHA_SESSION=default
EOF
```

- [ ] **Step 2: Replace CHANGE_THIS_TO_RANDOM_SECRET**

Generate a secure key and update the file:

```bash
SECRET=$(openssl rand -hex 24)
sed -i "s/CHANGE_THIS_TO_RANDOM_SECRET/$SECRET/" /opt/jatahku/docker-compose.waha.yml
echo "WAHA_API_KEY=$SECRET" >> /opt/jatahku/.env
echo "WAHA_URL=http://localhost:3000" >> /opt/jatahku/.env
```

- [ ] **Step 3: Create session volume directory**

```bash
mkdir -p /opt/jatahku/waha-sessions
```

- [ ] **Step 4: Pull and start WAHA**

```bash
cd /opt/jatahku
docker compose -f docker-compose.waha.yml pull
docker compose -f docker-compose.waha.yml up -d
```

- [ ] **Step 5: Verify WAHA is running**

```bash
docker compose -f docker-compose.waha.yml ps
curl -s http://localhost:3000/api/version -H "X-Api-Key: $(grep WAHA_API_KEY /opt/jatahku/.env | cut -d= -f2)"
```

Expected: JSON with version info like `{"version":"2025.x.x",...}`

- [ ] **Step 6: Scan QR code to link WhatsApp number**

From your local machine, open an SSH tunnel to access WAHA dashboard:

```bash
ssh -L 3000:localhost:3000 yatno@67.217.58.13
```

Then open `http://localhost:3000` in your browser. Use the WAHA dashboard to:
1. Create a session named `default`
2. Click "Start" → scan the QR code with the dedicated Jatahku WA number
3. Wait for status to show "WORKING"

- [ ] **Step 7: Test webhook delivery**

After session is active, send a test message to the bot number from any WA account, then check FastAPI logs:

```bash
journalctl -u jatahku -n 50 --no-pager | grep "WA message"
```

---

## Task 10: Frontend api.js

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add WA methods to ApiClient**

Find the end of the `ApiClient` class in `frontend/src/lib/api.js` (before the closing `}` and `export const api = new ApiClient()`). Add:

```javascript
async getWhatsAppStatus() {
  const res = await this.request('/auth/link/whatsapp-status');
  return res.ok ? res.json() : { linked: false, whatsapp_id: null, phone: null };
}

async linkWhatsApp(code) {
  return this.request('/auth/link/whatsapp', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

async unlinkWhatsApp() {
  return this.request('/auth/link/unlink-whatsapp', { method: 'POST' });
}

async saveWhatsAppPhone(phone) {
  return this.request('/auth/link/whatsapp-phone', {
    method: 'PUT',
    body: JSON.stringify({ phone }),
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: add WhatsApp link/unlink/status/phone API methods"
```

---

## Task 11: Frontend Settings.jsx

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Add WA state variables**

In `Settings()` function, find the `// Link TG` comment block (around line 121). Add WA state after it:

```javascript
// Link WA
const [waStatus, setWaStatus] = useState(null);
const [waCode, setWaCode] = useState('');
const [waCodeInput, setWaCodeInput] = useState('');
const [waLinking, setWaLinking] = useState(false);
const [waPhone, setWaPhone] = useState('');
const [waSavingPhone, setWaSavingPhone] = useState(false);
```

- [ ] **Step 2: Fetch WA status on load**

In the `load` function (around line 134), after `setLoading(false)`, add:

```javascript
const waRes = await api.getWhatsAppStatus();
setWaStatus(waRes);
setWaPhone(waRes.phone || '');
```

- [ ] **Step 3: Add WA action handlers**

After the `generateLinkCode` function (around line 229), add:

```javascript
const linkWhatsApp = async () => {
  if (!waCodeInput.trim()) return;
  setWaLinking(true);
  const res = await api.linkWhatsApp(waCodeInput.trim());
  setWaLinking(false);
  if (res.ok) {
    setWaCodeInput('');
    flash('WhatsApp terhubung!', 'wa');
    load();
  } else {
    const d = await res.json();
    flashErr(d.detail || 'Kode tidak valid', 'wa');
  }
};

const unlinkWhatsApp = async () => {
  if (!confirm('Putuskan koneksi WhatsApp?')) return;
  await api.unlinkWhatsApp();
  flash('WhatsApp diputus', 'wa');
  load();
};

const saveWaPhone = async () => {
  setWaSavingPhone(true);
  const res = await api.saveWhatsAppPhone(waPhone);
  setWaSavingPhone(false);
  if (res.ok) flash('Nomor HP disimpan', 'wa-phone');
  else flashErr('Format nomor tidak valid', 'wa-phone');
};
```

- [ ] **Step 4: Add WA section to JSX**

Find the closing `)}` of the Telegram section in the JSX (around line 422, after `{!profile.telegram_id ? ... : ...}`). Add the WA section right after it:

```jsx
{/* WhatsApp */}
{waStatus && !waStatus.linked ? (
  <div className="card border-brand-200">
    <h3 className="font-semibold text-sm mb-2">💬 Hubungkan WhatsApp</h3>
    <p className="text-xs text-gray-500 mb-4">
      Catat pengeluaran via WhatsApp dengan NLP yang sama seperti Telegram.
    </p>
    <div className="space-y-4">
      <div>
        <p className="text-sm font-medium text-gray-700 mb-1">Cara 1: Kode dari bot</p>
        <p className="text-xs text-gray-500 mb-2">
          Kirim <code className="bg-gray-100 px-1 rounded">/link</code> ke nomor WhatsApp Jatahku, lalu masukkan kode di bawah.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            className="input flex-1"
            placeholder="Masukkan kode 6 digit"
            value={waCodeInput}
            onChange={e => setWaCodeInput(e.target.value)}
            maxLength={6}
          />
          <button
            onClick={linkWhatsApp}
            disabled={waLinking || waCodeInput.length !== 6}
            className="btn-primary disabled:opacity-50 whitespace-nowrap"
          >
            {waLinking ? '...' : 'Hubungkan'}
          </button>
        </div>
        <InlineFlash k="wa" />
      </div>
      <div className="border-t border-gray-100 pt-3">
        <p className="text-sm font-medium text-gray-700 mb-1">Cara 2: Nomor HP (auto-link)</p>
        <p className="text-xs text-gray-500 mb-2">
          Simpan nomor HP kamu. Bot akan otomatis mengenali nomor saat pesan pertama masuk.
        </p>
        <div className="flex gap-2">
          <input
            type="tel"
            className="input flex-1"
            placeholder="08123456789"
            value={waPhone}
            onChange={e => setWaPhone(e.target.value)}
          />
          <button
            onClick={saveWaPhone}
            disabled={waSavingPhone || !waPhone}
            className="btn-outline disabled:opacity-50 whitespace-nowrap"
          >
            {waSavingPhone ? '...' : 'Simpan'}
          </button>
        </div>
        <InlineFlash k="wa-phone" />
      </div>
    </div>
  </div>
) : waStatus?.linked ? (
  <div className="card">
    <h3 className="font-semibold text-sm mb-2">💬 WhatsApp</h3>
    <div className="flex items-center justify-between">
      <span className="text-sm text-brand-600">✅ Terhubung</span>
      <button onClick={unlinkWhatsApp} className="text-xs text-gray-400 hover:text-danger-400">
        Putuskan
      </button>
    </div>
  </div>
) : null}
```

- [ ] **Step 5: Build frontend and verify no errors**

```bash
cd /opt/jatahku/frontend
npm run build
```

Expected: build completes with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Settings.jsx
git commit -m "feat: add WhatsApp linking UI to Settings page"
```

---

## Task 12: Deploy and End-to-End Test

- [ ] **Step 1: Deploy to VPS**

```bash
git push origin main
```

GitHub Actions will run deploy. Or manually on VPS:

```bash
sudo /opt/jatahku/deploy.sh
```

- [ ] **Step 2: Restart FastAPI to load new .env values**

```bash
sudo systemctl restart jatahku
sudo systemctl status jatahku
```

Expected: `active (running)`

- [ ] **Step 3: Test /link flow**

From the Jatahku WA number (in WAHA session), message any WA account you control:
- Send `/link` from your test WA account to the bot number
- Verify bot replies with 6-digit code
- Open jatahku.com/settings → enter the code under WhatsApp section
- Verify page shows "✅ Terhubung"

- [ ] **Step 4: Test /status**

Send `/status` to the bot number from the now-linked account.
Expected: Budget summary with envelope breakdown.

- [ ] **Step 5: Test single NLP transaction**

Send `kopi 35k` to the bot.
Expected: either auto-recorded (if keyword learned) or numbered list of envelopes.

- [ ] **Step 6: Test multi-input**

Send:
```
kopi 35k
parkir 5k
beli baju 120k
```

Expected: auto-records kopi + parkir (if learned), asks envelope for baju.

- [ ] **Step 7: Test /webapp**

Send `/webapp` to the bot.
Expected: login URL that opens jatahku.com and logs you in automatically.

- [ ] **Step 8: Test phone auto-link**

1. Unlink WA account in Settings
2. Save your phone number in Settings → WhatsApp → Cara 2
3. Send any message to bot from that WA number
4. Verify bot sends auto-link confirmation and account is now linked

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Section 2 (Architecture) — Task 4 + 5 + 8
- ✅ Section 3 (DB) — Task 2
- ✅ Section 4 (Linking — hybrid) — Task 3 (code exchange) + Task 5 `get_wa_user` (phone auto-link)
- ✅ Section 5 (Commands) — Task 5 (status/amplop/webapp/link), Task 6 (single), Task 7 (multi)
- ✅ Section 6 (WAHA setup) — Task 9
- ✅ Section 7 (Security) — Task 4 (X-Api-Key validation)
- ✅ Section 8 (API Endpoints) — Task 3
- ✅ Section 10 (File changes) — all tasks cover all listed files

**Notes for implementer:**
- `TransactionSource.webapp` is used for WA transactions (no `whatsapp` enum value exists; adding one is out of scope for v1)
- Link routes are at `/auth/link/whatsapp*` not `/link/whatsapp*` — because `link.router` is mounted at `/auth` prefix in `main.py`
- WAHA `from` field format: `628xxx@c.us` — this is the full `whatsapp_id` stored in DB
- Phone auto-link normalizes via `normalize_phone()` — user saves `628xxx`, WAHA sends `628xxx@c.us`, `chat_id_to_phone()` strips suffix
