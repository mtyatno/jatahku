"""
Global intent phrase learning.
When the bot can't recognize a message, it shows intent suggestion buttons.
If the user confirms one, the phrase is saved globally — all users benefit immediately.
"""
import re
import json
import secrets
from sqlalchemy import select
from app.models.models import GlobalIntentPhrase

# ── Normalization ─────────────────────────────────────────────────────────────

_FILLER = {
    "gue", "gw", "aku", "saya", "ku", "w", "g",
    "dong", "nih", "sih", "ya", "kan", "deh", "lah",
    "bro", "cuy", "bang", "bos", "bosku", "njir", "woy",
    "tolong", "minta", "coba", "hayuk", "ayo",
}

def normalize(text: str) -> str:
    """Lowercase, strip punctuation, remove filler words."""
    text = re.sub(r"[^\w\s]", "", text.lower().strip())
    words = [w for w in text.split() if w not in _FILLER]
    return " ".join(words)


# ── Intent registry ───────────────────────────────────────────────────────────
# intent_key → (button label, handler import path)
INTENTS = {
    "pengeluaran_hari_ini": "🧾 Pengeluaran hari ini",
    "sisa":                 "💰 Sisa saldo amplop",
    "harian":               "📅 Jatah harian",
    "proyeksi":             "🔮 Kapan budget habis?",
    "comparison":           "📊 Bandingkan bulan ini vs lalu",
    "santai":               "😬 Status budget (aman/boncos?)",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def lookup_intent(text: str, db) -> str | None:
    """Return learned intent for this phrase, or None."""
    phrase = normalize(text)
    if not phrase:
        return None
    result = await db.execute(
        select(GlobalIntentPhrase).where(GlobalIntentPhrase.phrase == phrase)
    )
    row = result.scalar_one_or_none()
    return row.intent if row else None


async def save_intent(text: str, intent: str, db) -> None:
    """Save or increment a phrase → intent mapping."""
    phrase = normalize(text)
    if not phrase:
        return
    result = await db.execute(
        select(GlobalIntentPhrase).where(GlobalIntentPhrase.phrase == phrase)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.count += 1
        existing.intent = intent  # allow correction if intent changes
    else:
        db.add(GlobalIntentPhrase(phrase=phrase, intent=intent))
    await db.commit()


# ── Bot interaction ───────────────────────────────────────────────────────────

async def store_pending_phrase(text: str, user_id: int, settings) -> str:
    """Store original text in Redis, return token for callback."""
    import redis.asyncio as aioredis
    token = secrets.token_hex(8)
    r = aioredis.from_url(settings.REDIS_URL)
    await r.setex(f"intent_pending:{user_id}:{token}", 300, text)  # 5 min TTL
    await r.aclose()
    return token


async def get_pending_phrase(user_id: int, token: str, settings) -> str | None:
    """Retrieve original text from Redis."""
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL)
    val = await r.get(f"intent_pending:{user_id}:{token}")
    await r.aclose()
    return val.decode() if val else None


async def show_intent_suggestions(update, text: str, settings):
    """Show intent suggestion buttons when message is not recognized."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user_id = update.effective_user.id
    token = await store_pending_phrase(text, user_id, settings)

    buttons = [
        [InlineKeyboardButton(label, callback_data=f"intentlearn:{token}:{key}")]
        for key, label in INTENTS.items()
    ]
    buttons.append([InlineKeyboardButton("❌ Bukan itu", callback_data=f"intentlearn:{token}:none")])

    await update.message.reply_text(
        "Hmm, belum ngerti maksudnya. Kamu mau tanya soal apa?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_intent_learn_callback(query, context, settings):
    """Handle user's intent confirmation button press."""
    from app.core.database import AsyncSessionLocal
    from app.bot.nlp_cmd import (
        handle_pengeluaran_hari_ini, handle_sisa, handle_limit_harian,
        handle_proyeksi, handle_comparison, handle_santai,
    )

    parts = query.data.split(":", 2)  # intentlearn:{token}:{intent}
    if len(parts) != 3:
        await query.answer()
        return

    _, token, intent_key = parts
    user_id = query.from_user.id

    original_text = await get_pending_phrase(user_id, token, settings)

    if intent_key == "none" or not original_text:
        await query.edit_message_text(
            "Oke, coba ketik ulang ya. Contoh:\n"
            "• `35k kopi` — catat pengeluaran\n"
            "• `sisa` — cek saldo amplop\n"
            "• `pengeluaran hari ini` — rekap hari ini",
            parse_mode="Markdown",
        )
        return

    # Save to global DB
    async with AsyncSessionLocal() as db:
        await save_intent(original_text, intent_key, db)

    await query.answer("✅ Dipelajari! Lain kali langsung dimengerti.")

    # Execute the confirmed intent immediately
    handlers = {
        "pengeluaran_hari_ini": handle_pengeluaran_hari_ini,
        "sisa":                 handle_sisa,
        "harian":               handle_limit_harian,
        "proyeksi":             handle_proyeksi,
        "comparison":           handle_comparison,
        "santai":               handle_santai,
    }
    handler = handlers.get(intent_key)
    if handler:
        await query.edit_message_text("⏳")
        # Wrap query as update-like object so nlp handlers can use update.message
        class _FakeUpdate:
            effective_user = query.from_user
            message = query.message
        await handler(_FakeUpdate(), context)
