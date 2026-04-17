import secrets
import logging
import json as json_mod
from datetime import date
from decimal import Decimal

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.phone import chat_id_to_phone
from app.models.models import (
    User,
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

    lines = [f'"{description}" — masuk ke amplop mana?\n']
    for i, env in enumerate(env_list, 1):
        lines.append(f"{i}. {env['emoji']} {env['name']}")
    lines.append("\nBalas dengan nomor (1/2/3...)")

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

    idx = next((i for i, item in enumerate(queue) if "env_id" not in item), None)
    if idx is None:
        r = await _redis()
        await r.delete(f"wa:batch:{chat_id}")
        await r.close()
        return

    item = queue[idx]
    skip_value = len(env_list) + 1

    if choice == skip_value:
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

    next_idx = next((i for i, item in enumerate(queue) if "env_id" not in item), None)

    if next_idx is None:
        r = await _redis()
        await r.delete(f"wa:batch:{chat_id}")
        await r.close()
        lines = ["✅ Semua item selesai!\n"] + auto_lines
        await waha_send(chat_id, "\n".join(lines))
    else:
        r = await _redis()
        await r.set(f"wa:batch:{chat_id}", json_mod.dumps(data), ex=600)
        await r.close()
        await _ask_batch_item(chat_id, queue, next_idx, auto_lines, env_list)


# ── Main router ───────────────────────────────────────────────────────────────

async def handle_wa_message(payload: dict) -> None:
    """Entry point from webhook. Routes to appropriate handler."""
    event = payload.get("event")
    msg = payload.get("payload", {})

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
