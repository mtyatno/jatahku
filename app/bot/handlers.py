import re
import logging
import uuid
from decimal import Decimal
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    User, Household, HouseholdMember, HouseholdRole,
    Envelope, Transaction, Allocation, Income, TransactionSource,
    PendingTransaction, PendingTransactionStatus,
)
from app.services.behavior import check_behavior, confirm_pending, cancel_pending, get_user_pending
from app.services.visibility import masked_description
from app.services.expense_rules import (
    FUNDS_BLOCKS, after_expense_recorded, check_expense, is_spendable,
)
from app.bot.channel import find_chat_user, is_web, is_web_chat_id, txn_source
from app.bot.link_cmd import link_with_code
from app.bot.tglogin_cmd import reply_setup_needed
from app.services.txn_nlp import (
    STOPWORDS, CATEGORY_KEYWORDS, extract_keywords, guess_envelope_name,
    save_learned_keywords, find_best_envelope,
)

settings = get_settings()
logger = logging.getLogger("jatahku.bot")

# ── Parser nominal — port 1:1 dari frontend/src/lib/parseAmount.js ──────────
# Web dan bot WAJIB membaca teks yang sama dengan cara yang sama. Kasus uji
# bersama: frontend/src/lib/parseAmount.cases.json (dipakai tes JS & Python).
# Ubah keduanya sekaligus.

# Matches amount anywhere in text: "35k kopi", "kopi 35k", "beli kopi 35rb"
AMOUNT_ANYWHERE = re.compile(
    r"(?:rp\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+\.\d{1,2}|\d+(?:[,]\d+)?)\s*(jt|juta|rb|ribu|k)?(?!\w)|(?:rp\.?\s*)(\d+)", re.IGNORECASE
)
MULTIPLIERS = {"jt": 1_000_000, "juta": 1_000_000, "rb": 1_000, "ribu": 1_000, "k": 1_000}

# Subscription patterns — frequency keywords (order matters: specific first)
SUB_INTERVAL = re.compile(r"(?:tiap|setiap|per)\s+(\d+)\s*(bulan|minggu|tahun)", re.IGNORECASE)
SUB_PATTERNS = [
    (re.compile(r"(?:tiap|setiap|per)\s+(?:setengah\s+tahun|6\s*bulan)", re.IGNORECASE), "biannual", 6),
    (re.compile(r"(?:tiap|setiap|per)\s+tahun(?:an)?|tahun(?:an)", re.IGNORECASE), "yearly", 12),
    (re.compile(r"(?:tiap|setiap|per)\s+(?:2\s*minggu|dua\s*minggu)", re.IGNORECASE), "biweekly", 0.5),
    (re.compile(r"(?:tiap|setiap|per)\s+minggu(?:an)?|minggu(?:an)", re.IGNORECASE), "weekly", 0.25),
    (re.compile(r"(?:tiap|setiap|per)\s+bulan(?:an)?|bulan(?:an)?|/bul(?:an)?", re.IGNORECASE), "monthly", 1),
]
# Keywords that imply recurring/subscription
SUB_KEYWORDS = re.compile(r"\b(?:langganan|sewa|nyewa|kontrak|ngontrak|subscribe|subscription|berlangganan)\b", re.IGNORECASE)


def _amount_candidates(text):
    """Semua kandidat nominal di teks: list dict(amount, multiplier, start, end)."""
    from decimal import ROUND_HALF_UP
    out = []
    for m in AMOUNT_ANYWHERE.finditer(text):
        if m.group(1):
            number_str, mult_str = m.group(1), m.group(2)
        elif m.group(3):
            number_str, mult_str = m.group(3), None
        else:
            continue
        # dot-thousand 1.500 / comma-thousand 1,500 / decimal comma 1,5
        if re.match(r"^\d{1,3}(\.\d{3})+$", number_str):
            number_str = number_str.replace(".", "")
        elif re.match(r"^\d{1,3}(,\d{3})+$", number_str):
            number_str = number_str.replace(",", "")
        else:
            number_str = number_str.replace(",", ".")
        try:
            number = Decimal(number_str)
        except Exception:
            continue
        multiplier = MULTIPLIERS.get(mult_str.lower(), 1) if mult_str else 1
        amount = (number * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if amount <= 0:
            continue
        out.append({"amount": amount, "multiplier": multiplier, "start": m.start(), "end": m.end()})
    return out


def parse_amount(text):
    """Parse nominal + deskripsi. Returns (amount, description) or None.

    Sama dengan parseAmount() web: nominal ber-pengali (ribu/juta/jt/rb/k)
    menang atas angka polos yang bisa jadi kuantitas ("beli 2 kopi 25 ribu" →
    25 ribu); di antaranya yang terbesar. Tanpa pengali: angka pertama.
    """
    trimmed = text.strip()
    cands = _amount_candidates(trimmed)
    if not cands:
        return None
    with_mult = [c for c in cands if c["multiplier"] > 1]
    chosen = max(with_mult, key=lambda c: c["amount"]) if with_mult else cands[0]
    desc = (trimmed[:chosen["start"]].strip() + " " + trimmed[chosen["end"]:].strip()).strip()
    if not desc:
        desc = "Pengeluaran"
    return Decimal(str(int(chosen["amount"]))), desc


# Pemisah item — lihat komentar di parseAmount.js untuk alasan tiap aturan.
_COMMA_SEP = re.compile(r"\s*,(?!\d)\s*|;")
_WORD_SEPS = [re.compile(r"\s+(?:terus|lalu)\s+", re.IGNORECASE), re.compile(r"\s+dan\s+", re.IGNORECASE)]
_MULTIPLIER_GLUE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s+(juta|jt|ribu|rb|k)\b", re.IGNORECASE)
_RP_GLUE_RE = re.compile(r"\b(rp\.?)\s+(?=\d)", re.IGNORECASE)  # "Rp 5.000" → "Rp5.000"
_MULTIPLIER_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?(juta|jt|ribu|rb|k)$", re.IGNORECASE)
_DOTTED_AMOUNT_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")
_RP_AMOUNT_RE = re.compile(r"^rp\.?\s*\d", re.IGNORECASE)


def _is_amount_token(tok):
    """Token yang PASTI nominal: angka+pengali, ribuan bertitik, atau Rp...
    Angka polos ("2", "12") bukan — sering kali kuantitas."""
    return bool(_MULTIPLIER_TOKEN_RE.match(tok) or _DOTTED_AMOUNT_RE.match(tok) or _RP_AMOUNT_RE.match(tok))


def _split_by_spaces(text):
    """Pecah item yang hanya dipisah spasi: "kopi 6jt gojek 1juta",
    "35k kopi 20k parkir". None bila hanya satu item."""
    glued = _RP_GLUE_RE.sub(r"\1", _MULTIPLIER_GLUE_RE.sub(r"\1\2", text))
    tokens = [t for t in re.split(r"\s+", glued) if t.strip()]
    items, current = [], []
    amount_first = bool(tokens) and _is_amount_token(tokens[0])
    for i, tok in enumerate(tokens):
        if amount_first:
            # "35k kopi 20k parkir": item baru dimulai di setiap nominal
            if i > 0 and _is_amount_token(tok) and current:
                items.append(" ".join(current))
                current = []
            current.append(tok)
        else:
            # "kopi 35k parkir 20k": item ditutup setelah nominal, selama
            # masih ada nominal lain di sisa teks
            current.append(tok)
            if _is_amount_token(tok) and any(_is_amount_token(t) for t in tokens[i + 1:]):
                items.append(" ".join(current))
                current = []
    if current:
        items.append(" ".join(current))
    return items if len(items) >= 2 else None


def parse_subscription(text):
    """Detect subscription intent. Returns (amount, description, frequency, months) or None."""
    parsed = parse_amount(text)
    if not parsed:
        return None
    amount, desc = parsed

    # Check custom interval first: "tiap 2 bulan", "tiap 3 tahun", etc.
    interval_match = SUB_INTERVAL.search(text)
    if interval_match:
        num = int(interval_match.group(1))
        unit = interval_match.group(2).lower()
        if unit == "bulan":
            freq_name = f"{num}monthly"
            months = num
        elif unit == "minggu":
            freq_name = f"{num}weekly"
            months = num * 0.25
        elif unit == "tahun":
            freq_name = f"{num}yearly"
            months = num * 12
        else:
            freq_name = "monthly"
            months = 1
        clean_desc = desc
        # Remove full interval pattern + fragments
        clean_desc = SUB_INTERVAL.sub("", clean_desc).strip()
        clean_desc = re.sub(r"(?:tiap|setiap|per)\s*\d*\s*", "", clean_desc, flags=re.IGNORECASE).strip()
        clean_desc = SUB_KEYWORDS.sub("", clean_desc).strip()
        clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
        return amount, clean_desc or desc, freq_name, months

    # Check explicit frequency patterns
    for pat, freq_name, months in SUB_PATTERNS:
        if pat.search(text):
            # Clean freq keywords from desc
            clean_desc = desc
            for p, _, _ in SUB_PATTERNS:
                clean_desc = p.sub("", clean_desc).strip()
            clean_desc = SUB_KEYWORDS.sub("", clean_desc).strip()
            clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
            return amount, clean_desc or desc, freq_name, months
    # Check subscription keywords (sewa, langganan, kontrak, etc) → default monthly
    if SUB_KEYWORDS.search(text):
        clean_desc = SUB_KEYWORDS.sub("", desc).strip()
        # Also clean from original text for better desc
        if not clean_desc:
            clean_desc = desc
        return amount, clean_desc, "monthly", 1
    return None

def format_currency(amount):
    val = int(amount)
    if val >= 1_000_000:
        jt = val / 1_000_000
        if jt == int(jt):
            return f"Rp{int(jt)}jt"
        return f"Rp{jt:,.2f}jt".replace(",", ".")
    elif val >= 1_000:
        rb = val / 1_000
        if rb == int(rb):
            return f"Rp{int(rb)}rb"
        return f"Rp{rb:,.1f}rb".replace(",", ".")
    return f"Rp{val:,}".replace(",", ".")

def progress_bar(spent, budget, width=10):
    if budget == 0:
        return "▱" * width
    ratio = min(float(spent / budget), 1.0)
    filled = int(ratio * width)
    return "▰" * filled + "▱" * (width - filled)

async def get_or_create_user(telegram_id, name, db):
    """User pemilik percakapan. `telegram_id` bisa juga id chat web
    (`web:<uuid>`, lihat app/bot/channel.py): akun web tidak pernah dibuat
    dari sini — sudah ada karena user sudah login."""
    user = await find_chat_user(telegram_id, db)
    if user:
        return user
    if is_web_chat_id(telegram_id):
        raise LookupError("akun chat web tidak ditemukan")
    user = User(telegram_id=str(telegram_id), name=name)
    db.add(user)
    await db.flush()
    household = Household(name=f"Rumah {name}")
    db.add(household)
    await db.flush()
    membership = HouseholdMember(user_id=user.id, household_id=household.id, role=HouseholdRole.owner)
    db.add(membership)
    await db.commit()
    await db.refresh(user)
    return user

async def get_household_id(user, db):
    result = await db.execute(select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id))
    return result.scalar_one_or_none()

def _streak_text(res) -> str:
    """Baris streak untuk balasan chat dari hasil record_activity (boleh None)."""
    try:
        from app.services.streak import milestone_message
        if res is None or not res.advanced:
            return ""
        celebrate = milestone_message(res)
        if celebrate:
            return f"\n\n🔥 {celebrate}"
        if res.current_streak >= 2:
            return f"\n\n🔥 Streak {res.current_streak} hari!"
        return ""
    except Exception:
        return ""


async def _streak_line(db, user) -> str:
    """Record today's activity and return a short streak line for chat replies.

    Best-effort: a streak failure must never break expense logging."""
    try:
        from app.services.streak import record_activity
        return _streak_text(await record_activity(db, user.id, getattr(user, "timezone", None)))
    except Exception:
        return ""


def _spendable_rows(env_data):
    """Pilihan amplop untuk pengeluaran — tanpa tabungan/sinking fund, sama
    dengan dropdown web."""
    return [e for e in env_data if is_spendable(e["envelope"])]


async def _quota_line(user, db, html: bool = False) -> str:
    """Baris pemberitahuan sesudah input tercatat bila kuota Basic bulan ini kini
    habis (input berikutnya menunggu reset bulan depan). Best-effort."""
    try:
        from app.services.plan_limits import quota_notice_after_input
        notice = await quota_notice_after_input(user, db)
    except Exception:
        return ""
    if not notice:
        return ""
    return f"\n\n⚠️ {_esc(notice) if html else notice}"


async def _reply_blocked_basic(send_fn, check) -> bool:
    """Balasan untuk blok yang tidak punya alur lanjutan. True bila ditangani."""
    if check.check_type == "locked":
        await send_fn(f"🔒 {check.reason}")
    elif check.check_type == "not_spendable":
        await send_fn(f"🏦 {check.reason}")
    elif check.check_type == "plan_limit":
        await send_fn(f"⚠️ {check.reason}\n\nUpgrade di jatahku.com/settings")
    elif check.check_type == "error":
        await send_fn(f"⚠️ {check.reason}")
    else:
        return False
    return True

async def get_envelopes_with_spent(household_id, db, user_id=None, payday_day: int = 1):
    from sqlalchemy import or_
    from app.models.models import Income, MonthlySnapshot
    from app.core.period import get_budget_period, get_previous_period
    from app.services.reserved import envelope_reserved
    period_start, period_end = get_budget_period(payday_day)
    prev_start, _ = get_previous_period(payday_day)
    query = select(Envelope).where(Envelope.household_id == household_id, Envelope.is_active == True)
    if user_id:
        query = query.where(or_(Envelope.owner_id == None, Envelope.owner_id == user_id))
    result = await db.execute(query.order_by(Envelope.created_at))
    envelopes = result.scalars().all()
    envelope_data = []
    for env in envelopes:
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.envelope_id == env.id, Transaction.is_deleted == False,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
        )
        spent = Decimal(str(spent_result.scalar()))
        alloc_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .where(
                Allocation.envelope_id == env.id,
                Income.income_date >= period_start,
                Income.income_date <= period_end,
            )
        )
        allocated = Decimal(str(alloc_result.scalar()))
        # Rollover from previous period
        rollover = Decimal("0")
        if env.is_rollover:
            snap_result = await db.execute(
                select(MonthlySnapshot).where(
                    MonthlySnapshot.envelope_id == env.id,
                    MonthlySnapshot.year == prev_start.year,
                    MonthlySnapshot.month == prev_start.month,
                )
            )
            snap = snap_result.scalar_one_or_none()
            if snap and snap.rollover_amount:
                rollover = snap.rollover_amount
        # Reserved from subscriptions
        reserved = await envelope_reserved(db, env.id, period_start, period_end)
        remaining = allocated + rollover - spent
        free = remaining - reserved
        envelope_data.append({
            "envelope": env, "spent": spent, "allocated": allocated,
            "remaining": remaining, "reserved": reserved, "free": free,
        })
    return envelope_data

async def _is_setup_complete(user, db):
    """Siap dipakai lewat bot = punya household dengan minimal satu amplop aktif.
    Email tidak disyaratkan: akun dari /start onboarding lewat login sekali ketuk."""
    hid = await get_household_id(user, db)
    if not hid:
        return False, "no_household"
    env_count = await db.execute(
        select(func.count(Envelope.id)).where(
            Envelope.household_id == hid, Envelope.is_active == True
        )
    )
    if env_count.scalar() == 0:
        return False, "no_envelopes"
    return True, "ok"


async def cmd_start(update, context):
    tg_user = update.effective_user
    import logging; logging.getLogger("jatahku").warning(f"cmd_start args: {context.args}")
    # Handle deep link: /start link_XXXXXX
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("link_"):
            # Lewat API yang sama dengan /link KODE: bentrok dengan akun bot
            # dari /start ditangani di sana (gabung otomatis / pilihan merge).
            await link_with_code(update, arg[len("link_"):])
            return
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name or "User", db)
        setup_ok, reason = await _is_setup_complete(user, db)

    if setup_ok:
        await update.message.reply_text(
            f"Hai {tg_user.first_name}! \U0001f44b\n\n"
            f"Kirim pengeluaran seperti chat biasa:\n"
            f"\u2022 `35k starbucks`\n"
            f"\u2022 `150rb nasi padang`\n\n"
            f"Ketik /status untuk cek budget atau /help untuk panduan.",
            parse_mode="Markdown",
        )
    else:
        await reply_setup_needed(update, user)


async def _receipt_feedback_saved(user_id, scan_id, amount, txn_date, description):
    """Feedback belajar scan struk setelah transaksinya tersimpan (best-effort).

    Sesi terpisah: apply_feedback meng-commit sendiri, dan kalau gagal, sesi
    pemanggil tidak perlu rollback penuh (yang meng-expire objek sesi dan
    membuat akses atribut sesudahnya gagal di async — MissingGreenlet)."""
    if not scan_id:
        return
    try:
        from app.services.receipt_scan import apply_feedback
        async with AsyncSessionLocal() as fdb:
            fuser = await fdb.get(User, user_id)
            if fuser is not None:
                await apply_feedback(fuser, scan_id, fdb, saved=True, total=int(amount),
                                     txn_date=txn_date, merchant=description)
    except Exception as exc:
        logger.warning("feedback struk gagal: %s", exc)


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


# ── Daily-limit bypass helpers ────────────────────────────────────────────────

async def _send_daily_limit_blocked(send_fn, user_id, d, envelope, settings):
    """Show a friendly daily-limit block with a temporary-raise offer."""
    import secrets, json
    import redis.asyncio as aioredis
    from datetime import datetime

    daily_limit  = d["daily_limit"]
    spent_today  = d["spent_today"]
    remaining    = d["remaining_today"]
    requested    = d["requested"]
    over         = requested - remaining
    emoji        = envelope.emoji or "📁"
    name         = envelope.name

    # Store pending bypass payload in Redis (10-min TTL)
    token   = secrets.token_hex(8)
    payload = json.dumps({
        "envelope_id": str(envelope.id),
        "amount":      str(requested),
        "description": d.get("description", ""),
        # dari scan struk (opsional): tanggal struk + scan_id untuk feedback
        "date":        d.get("date"),
        "scan_id":     d.get("scan_id"),
    })
    r = aioredis.from_url(settings.REDIS_URL)
    await r.setex(f"dlimit_pending:{user_id}:{token}", 600, payload)
    await r.aclose()

    text = (
        f"⚠️ <b>Limit harian terlampaui</b>\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"Diminta   <b>{format_currency(requested)}</b>\n"
        f"Limit     {format_currency(daily_limit)}\n"
        f"Terpakai  {format_currency(spent_today)}\n"
        f"Kelebihan <b>{format_currency(over)}</b>\n\n"
        f"Mau tetap catat? Limit hari ini akan dinaikkan sementara "
        f"dan otomatis kembali ke <b>{format_currency(daily_limit)}</b> besok."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Catat, naikkan limit hari ini", callback_data=f"dlimit:confirm:{token}")],
        [InlineKeyboardButton("❌ Batalkan", callback_data=f"dlimit:cancel:{token}")],
    ])
    await send_fn(text, parse_mode="HTML", reply_markup=keyboard)


async def handle_daily_limit_callback(update, context):
    """Handle ✅ / ❌ for daily-limit bypass."""
    import json
    from datetime import datetime, time, timedelta
    import redis.asyncio as aioredis

    query = update.callback_query
    await query.answer()

    settings = get_settings()
    parts = query.data.split(":", 2)   # dlimit : confirm/cancel : token
    if len(parts) != 3:
        return
    _, action, token = parts
    user_id = str(query.from_user.id)

    r = aioredis.from_url(settings.REDIS_URL)

    # Cancel path — explicit user request
    if action == "cancel":
        await r.delete(f"dlimit_pending:{user_id}:{token}")
        await r.aclose()
        await query.edit_message_text("❌ Transaksi dibatalkan.")
        return

    # Confirm path — use getdel (atomic fetch+delete) to prevent double-processing
    raw = await r.getdel(f"dlimit_pending:{user_id}:{token}")
    await r.aclose()

    if not raw:
        # Key missing: already processed or session expired
        await query.edit_message_text("⏰ Transaksi sudah diproses atau sesi expired. Cek /status.")
        return

    payload     = json.loads(raw)
    envelope_id = payload["envelope_id"]
    amount      = Decimal(payload["amount"])
    description = payload.get("description", "")
    txn_date    = _parse_iso_date(payload.get("date")) or date.today()
    scan_id     = payload.get("scan_id")

    # Record transaction
    import uuid
    async with AsyncSessionLocal() as db:
        from app.models.models import Envelope as EnvModel
        env_r = await db.execute(select(EnvModel).where(EnvModel.id == uuid.UUID(envelope_id)))
        envelope = env_r.scalar_one_or_none()
        if not envelope:
            await query.edit_message_text("⚠️ Amplop tidak ditemukan.")
            return

        user = await find_chat_user(user_id, db)
        if not user:
            await query.edit_message_text("⚠️ User tidak ditemukan.")
            return

        txn = Transaction(
            envelope_id=envelope.id,
            user_id=user.id,
            amount=amount,
            description=description,
            source=txn_source(),
            transaction_date=txn_date,
        )
        db.add(txn)
        await db.commit()
        await after_expense_recorded(db, user, envelope.id, description)
        await _receipt_feedback_saved(user.id, scan_id, amount, txn_date, description)

        # Limit dinaikkan sampai tengah malam — fungsi yang sama dengan web
        from app.services.behavior import raise_daily_limit_today
        await raise_daily_limit_today(user.id, envelope.id)

        # Fetch updated remaining for envelope
        from app.bot.nlp_cmd import _get_user_envelopes
        _, _, envs = await _get_user_envelopes(query.from_user, db)
        env_data = next((e for e in (envs or []) if e["envelope"].id == envelope.id), None)
        remaining = env_data["remaining"] if env_data else Decimal("0")
        quota_line = await _quota_line(user, db, html=True)

    emoji = envelope.emoji or "📁"
    await query.edit_message_text(
        f"✅ <b>{format_currency(amount)}</b> — {description}\n"
        f"{emoji} {envelope.name} · sisa <b>{format_currency(remaining)}</b>\n\n"
        f"<i>Limit harian dinaikkan sementara sampai tengah malam.</i>{quota_line}",
        parse_mode="HTML",
    )


# ── Geser dana saat amplop kurang dana ────────────────────────────────────────
# Padanan FundEnvelopeModal di web: pengeluaran yang terblokir "not_funded" /
# "insufficient" ditawari menggeser kekurangannya dari amplop lain, lalu
# transaksinya langsung dicatat.

FUND_SHIFT_TTL = 600  # detik


def _esc(text) -> str:
    import html
    return html.escape(str(text or ""), quote=False)


async def _notify_goals(db, user, goals_before):
    """Notifikasi goal yang baru tercapai karena dana tambahan (app/services/goal_notify.py)."""
    if goals_before:
        from app.services.goal_notify import notify_goals_reached
        await notify_goals_reached(db, user, goals_before)


def _funding_line(kind, amount, target_env, source_env=None) -> str:
    """Satu baris ringkas tentang dana yang ditambahkan ke amplop tujuan."""
    dst = f"{target_env.emoji or '📁'} {_esc(target_env.name)}"
    if kind == "shift":
        return (f"🔁 {format_currency(amount)} digeser dari "
                f"{source_env.emoji or '📁'} {_esc(source_env.name)} → {dst}")
    return f"💰 Top-up pemasukan {format_currency(amount)} → {dst}"


async def _send_fund_shift_offer(send_fn, tg_user_id, user, hid, envelope, amount, description, db,
                                 txn_date=None, scan_id=None):
    """Tampilkan kekurangan dana + dua cara mengisinya, sama dengan modal web:
    geser dari amplop lain (tombol per amplop sumber) atau top-up pemasukan."""
    import secrets, json
    import redis.asyncio as aioredis
    from app.services.fund_shift import compute_shortfall, pick_sources

    payday_day = getattr(user, "payday_day", 1) or 1
    env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    target = next((e for e in env_data if e["envelope"].id == envelope.id), None)
    target_remaining = target["remaining"] if target else Decimal("0")
    shortfall = compute_shortfall(target_remaining, amount)
    sources = pick_sources(env_data, envelope.id, shortfall)

    emoji = envelope.emoji or "📁"
    text = (
        f"💸 <b>Dana amplop kurang</b>\n\n"
        f"{format_currency(amount)} — {_esc(description)}\n"
        f"{emoji} {_esc(envelope.name)} · sisa {format_currency(max(target_remaining, Decimal('0')))}\n"
        f"Kurang <b>{format_currency(shortfall)}</b>\n\n"
    )
    if sources:
        text += (f"Geser <b>{format_currency(shortfall)}</b> dari amplop lain, atau catat "
                 f"pemasukan sebesar kekurangannya, supaya transaksi ini tetap tercatat?")
    else:
        text += (f"Tidak ada amplop lain yang sisanya cukup. Catat pemasukan "
                 f"<b>{format_currency(shortfall)}</b> ke {emoji} {_esc(envelope.name)} "
                 f"supaya transaksi ini tetap tercatat?")

    token = secrets.token_hex(8)
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        await r.setex(f"fshift:{tg_user_id}:{token}", FUND_SHIFT_TTL, json.dumps({
            "envelope_id": str(envelope.id),
            "amount": str(amount),
            "description": description,
            "sources": [str(s["envelope"].id) for s in sources],
            # dari scan struk (opsional): tanggal struk + scan_id untuk feedback
            "date": txn_date.isoformat() if txn_date else None,
            "scan_id": scan_id,
        }))
    finally:
        await r.aclose()

    keyboard = []
    for idx, s in enumerate(sources):
        src = s["envelope"]
        keyboard.append([InlineKeyboardButton(
            f"🔁 {src.emoji or '📁'} {src.name} (sisa {format_currency(s['remaining'])})",
            callback_data=f"fshift:{token}:{idx}",
        )])
    keyboard.append([InlineKeyboardButton(
        f"💰 Top-up pemasukan {format_currency(shortfall)}", callback_data=f"fshift:{token}:t")])
    keyboard.append([InlineKeyboardButton("❌ Batalkan", callback_data=f"fshift:{token}:x")])

    await send_fn(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_fund_shift_callback(update, context):
    """fshift:{token}:{idx|t|x} — geser dari amplop terpilih (idx) atau top-up
    pemasukan (t) sebesar kekurangan, lalu catat transaksinya; x = batal."""
    import json
    import redis.asyncio as aioredis
    from app.services.fund_shift import (
        compute_shortfall, record_topup, record_transfer, transfer_error,
    )

    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3:
        return
    _, token, choice = parts
    tg_user_id = str(query.from_user.id)
    key = f"fshift:{tg_user_id}:{token}"

    r = aioredis.from_url(settings.REDIS_URL)
    try:
        if choice == "x":
            await r.delete(key)
            await query.edit_message_text("❌ Transaksi dibatalkan. Dana tidak diubah.")
            return
        # getdel: ambil sekaligus hapus → tombol yang diketuk dua kali tidak diproses dua kali
        raw = await r.getdel(key)
    finally:
        await r.aclose()

    if not raw:
        await query.edit_message_text("⏰ Transaksi sudah diproses atau sesi expired. Kirim ulang.")
        return

    payload = json.loads(raw)
    topup = choice == "t"
    source_id = None
    if not topup:
        try:
            source_id = payload["sources"][int(choice)]
        except (ValueError, IndexError):
            await query.edit_message_text("Error: pilihan tidak valid.")
            return
    target_id = payload["envelope_id"]
    amount = Decimal(payload["amount"])
    description = payload.get("description") or "Pengeluaran"
    txn_date = _parse_iso_date(payload.get("date")) or date.today()
    scan_id = payload.get("scan_id")

    async with AsyncSessionLocal() as db:
        user = await find_chat_user(tg_user_id, db)
        if not user:
            await query.edit_message_text("⚠️ User tidak ditemukan.")
            return
        hid = await get_household_id(user, db)
        payday_day = getattr(user, "payday_day", 1) or 1

        # Hitung ulang dari data terbaru: saldo bisa berubah selama tombol menunggu.
        # get_envelopes_with_spent juga membatasi ke amplop aktif yang boleh diakses user.
        env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
        by_id = {str(e["envelope"].id): e for e in env_data}
        target = by_id.get(target_id)
        source = by_id.get(source_id) if source_id else None
        if not target or (not topup and not source):
            await query.edit_message_text("⚠️ Amplop sudah tidak tersedia. Kirim ulang transaksinya.")
            return
        target_env = target["envelope"]
        source_env = source["envelope"] if source else None

        funded = compute_shortfall(target["remaining"], amount)
        savepoint = None
        goals_before = {}
        if funded > 0:
            from app.services.goal_notify import goal_snapshot
            goals_before = await goal_snapshot(db, hid)
            if not topup:
                error = transfer_error(source, target, funded)
                if error:
                    await query.edit_message_text(
                        f"⚠️ {_esc(error)}. Dana tidak digeser — kirim ulang transaksinya.",
                        parse_mode="HTML")
                    return
            # Savepoint, bukan db.rollback(): rollback penuh meng-expire objek sesi
            # (lihat batch_cmd._record_item).
            savepoint = await db.begin_nested()
            if topup:
                record_topup(db, hid, user.id, target_env, funded)
            else:
                record_transfer(db, hid, user.id, source_env, target_env, funded)
            await db.flush()

        funding_line = (_funding_line("topup" if topup else "shift", funded, target_env, source_env)
                        if funded > 0 else "")
        undone = "Pemasukan tidak dicatat." if topup else "Dana tidak digeser."

        # Semua aturan lagi (sama dengan web) dengan dana yang sudah ditambahkan.
        # Kuota Basic sudah lolos di awal input ini (tawaran geser dana hanya muncul
        # sesudah cek kuota) → input diselesaikan walau kuota terlewati sementara itu.
        check = await check_expense(target_env, user, amount, db, skip_plan_limit=True)
        if not check.allowed:
            if check.check_type == "daily_limit":
                # Dana tambahan tetap disimpan: alur konfirmasi limit harian mencatat
                # transaksi tanpa cek dana ulang, jadi dananya harus sudah ada.
                await db.commit()
                await _notify_goals(db, user, goals_before)
                d = check.details
                d["description"] = description
                d["date"] = txn_date.isoformat()
                d["scan_id"] = scan_id
                prefix = funding_line + "\n\n" if funding_line else ""
                await _send_daily_limit_blocked(
                    lambda t, **kw: query.edit_message_text(prefix + t, **kw),
                    tg_user_id, d, target_env, settings,
                )
                return
            if savepoint is not None:
                await savepoint.rollback()
            await query.edit_message_text(
                f"⚠️ {_esc(check.reason)}\n\n{undone if funded > 0 else 'Transaksi tidak dicatat.'}",
                parse_mode="HTML")
            return

        db.add(Transaction(
            envelope_id=target_env.id, user_id=user.id, amount=amount,
            description=description, source=txn_source(),
            transaction_date=txn_date,
        ))
        await db.commit()
        await _notify_goals(db, user, goals_before)
        streak_line = _streak_text(await after_expense_recorded(db, user, target_env.id, description))
        await _receipt_feedback_saved(user.id, scan_id, amount, txn_date, description)

        env_data = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
        by_id = {str(e["envelope"].id): e for e in env_data}
        target_left = by_id[target_id]["remaining"] if target_id in by_id else Decimal("0")
        source_left = by_id[source_id]["remaining"] if source_id in by_id else Decimal("0")
        quota_line = await _quota_line(user, db, html=True)

    lines = [f"✅ {format_currency(amount)} — {_esc(description)}"]
    if funding_line:
        lines.append(funding_line)
    lines.append("")
    lines.append(f"{target_env.emoji or '📁'} {_esc(target_env.name)} · sisa <b>{format_currency(target_left)}</b>")
    if source_env is not None and funded > 0:
        lines.append(f"{source_env.emoji or '📁'} {_esc(source_env.name)} · sisa <b>{format_currency(source_left)}</b>")
    await query.edit_message_text("\n".join(lines) + _esc(streak_line) + quota_line, parse_mode="HTML")


async def cmd_status(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        if not hid:
            await update.message.reply_text("Ketik /start dulu.")
            return
        payday_day = getattr(user, 'payday_day', 1) or 1
        envelopes = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    if not envelopes:
        await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
        return

    from app.core.period import get_period_info
    from decimal import Decimal as _D
    info = get_period_info(payday_day)
    days_left = info["days_remaining"]
    days_used = info.get("days_used", 1) or 1
    period_label = f"{info['period_start'].strftime('%d %b')} – {info['period_end'].strftime('%d %b')}"

    total_allocated = sum(e["allocated"] for e in envelopes)
    total_spent     = sum(e["spent"]     for e in envelopes)
    total_free      = sum(e["free"]      for e in envelopes)

    # Burn rate & prediction
    daily_avg = total_spent / days_used if days_used > 0 else _D("0")
    predicted  = daily_avg * (days_used + days_left)
    on_track   = total_allocated <= 0 or predicted <= total_allocated

    # Budget-level bar (how much of budget is spent)
    pct_spent = int(float(total_spent / total_allocated * 100)) if total_allocated > 0 else 0
    filled = round(pct_spent / 100 * 6)
    budget_bar = "▰" * filled + "▱" * (6 - filled)

    lines = [f"📊 <b>Budget · {period_label}</b>"]
    lines.append(
        f"\nDana      <b>{format_currency(total_allocated)}</b>\n"
        f"Terpakai  <b>{format_currency(total_spent)}</b>  {budget_bar} {pct_spent}%\n"
        f"Sisa      <b>{format_currency(total_free)}</b> · {days_left} hari lagi"
    )

    lines.append("\n─────────────────")
    for e in envelopes:
        env = e["envelope"]
        spent, allocated, free = e["spent"], e["allocated"], e["free"]
        emoji = env.emoji or "📁"
        name  = env.name or "—"
        free_str = format_currency(free) if free > 0 else "habis"

        if allocated > 0:
            ratio = float(spent / allocated)
            indicator = "🔴" if ratio >= 0.9 else ("🟡" if ratio >= 0.7 else "🟢")
            if spent > 0:
                pct = int(ratio * 100)
                f2 = round(ratio * 6)
                bar = "▰" * f2 + "▱" * (6 - f2)
                lines.append(f"{indicator} {emoji} {name} · <b>{free_str}</b>  {bar} {pct}%")
            else:
                lines.append(f"{indicator} {emoji} {name} · <b>{free_str}</b>")
        else:
            lines.append(f"⚪ {emoji} {name} · <b>{free_str}</b>")

    lines.append("─────────────────")
    if on_track:
        lines.append(f"✅ On track · avg <b>{format_currency(daily_avg)}</b>/hari")
    else:
        over = predicted - total_allocated
        safe = total_free / days_left if days_left > 0 else _D("0")
        lines.append(f"⚠️ Hati-hati · prediksi overspend <b>{format_currency(over)}</b>")
        lines.append(f"💡 Max <b>{format_currency(safe)}</b>/hari biar aman")

    try:
        from app.services.streak import get_streak
        async with AsyncSessionLocal() as sdb:
            s = await get_streak(sdb, user.id, getattr(user, "timezone", None))
        if s.current_streak >= 2:
            lines.append(f"🔥 Streak <b>{s.current_streak} hari</b> · rekor {s.longest_streak} hari")
        elif s.longest_streak >= 2:
            lines.append(f"💤 Streak putus · rekormu {s.longest_streak} hari. Yuk mulai lagi!")
    except Exception:
        pass

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_amplop(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        payday_day = getattr(user, 'payday_day', 1) or 1
        envelopes = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
    if not envelopes:
        await update.message.reply_text("Belum ada amplop. Ketik /amplop_baru untuk buat.")
        return
    lines = ["📋 Amplop aktif:\n"]
    for e in envelopes:
        env = e["envelope"]
        emoji = env.emoji or "📁"
        lines.append(f"{emoji} {env.name} — sisa {format_currency(e['remaining'])} (budget {format_currency(env.budget_amount)})")
    await update.message.reply_text("\n".join(lines))

async def cmd_amplop_baru(update, context):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Format: /amplop_baru [nama] [budget]\n\n"
            "Contoh:\n• /amplop_baru Makan 1.5jt\n• /amplop_baru Transport 500k\n\n"
            + ("Tip: amplop dan alokasi lebih mudah diatur di menu Amplop." if is_web()
               else "Tip: amplop dan alokasi lebih mudah diatur lewat /webapp.")
        )
        return
    name = context.args[0]
    parsed = parse_amount(context.args[1] + " placeholder")
    if not parsed:
        await update.message.reply_text(f"Nggak bisa baca budget '{context.args[1]}'. Contoh: 1.5jt, 500k, 300rb")
        return
    budget = parsed[0]
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        from app.services.plan_limits import check_envelope_limit
        allowed, limit_msg = await check_envelope_limit(user, db)
        if not allowed:
            await update.message.reply_text(f"⚠️ {limit_msg}\n\nUpgrade di jatahku.com/upgrade")
            return
        db.add(Envelope(household_id=hid, name=name, budget_amount=budget, is_rollover=True))
        await db.commit()
    await update.message.reply_text(f"✅ Amplop '{name}' dibuat! Budget: {format_currency(budget)}/bulan.")

TEMPLATES = {
    "tpl_karyawan": [("🍜","Makan",1500000),("🚗","Transport",500000),("🎬","Hiburan",300000),("📱","Tagihan",500000),("💰","Tabungan",1000000)],
    "tpl_mahasiswa": [("🍜","Makan",800000),("🚗","Transport",200000),("🎬","Hiburan",200000),("📚","Kuliah",300000)],
    "tpl_keluarga": [("🍜","Makan",3000000),("🚗","Transport",1000000),("🏠","Rumah",2000000),("📱","Tagihan",800000),("🎬","Hiburan",500000),("💰","Tabungan",2000000)],
}

async def _visible_envelopes(db, hid, user_id):
    """Amplop aktif household yang terlihat oleh user (shared + miliknya)."""
    from sqlalchemy import or_
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid, Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
        ).order_by(Envelope.created_at)
    )
    return result.scalars().all()


async def cmd_template(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        existing = await _visible_envelopes(db, hid, user.id)

    if existing:
        env_lines = "\n".join(f"{e.emoji or '📁'} {e.name}" for e in existing)
        is_linked = bool(user.telegram_id)
        if is_web():
            webapp_hint = "Kelola amplop di menu Amplop."
        else:
            webapp_hint = "Ketik /webapp untuk buka dashboard WebApp." if is_linked else "Buka jatahku.com untuk kelola amplop."
        await update.message.reply_text(
            f"✅ <b>Budget kamu sudah siap!</b>\n\n"
            f"<b>{len(existing)} amplop aktif:</b>\n{env_lines}\n\n"
            f"Template tidak diperlukan lagi — amplop sudah ada.\n\n"
            f"Tambah amplop baru: /amplop_baru\n"
            f"Cek status budget: /status\n"
            f"{webapp_hint}",
            parse_mode="HTML",
        )
        return

    keyboard = [
        [InlineKeyboardButton("💼 Karyawan (5 amplop)", callback_data="tpl_karyawan")],
        [InlineKeyboardButton("🎓 Mahasiswa (4 amplop)", callback_data="tpl_mahasiswa")],
        [InlineKeyboardButton("👨‍👩‍👧 Keluarga (6 amplop)", callback_data="tpl_keluarga")],
    ]
    await update.message.reply_text("Pilih template:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_template_callback(update, context):
    query = update.callback_query
    await query.answer()
    tpl_key = query.data
    if tpl_key not in TEMPLATES:
        await query.edit_message_text("Template nggak ditemukan.")
        return
    template = TEMPLATES[tpl_key]
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        # Tombol template bisa ditekan dua kali / setelah amplop dibuat di tempat lain.
        if await _visible_envelopes(db, hid, user.id):
            await query.edit_message_text("✅ Amplop sudah ada — template tidak dibuat lagi. Cek /status.")
            return
        from app.services.plan_limits import check_envelope_limit
        allowed, limit_msg = await check_envelope_limit(user, db)
        if not allowed:
            await query.edit_message_text(f"⚠️ {limit_msg}")
            return
        for emoji, name, budget in template:
            db.add(Envelope(household_id=hid, name=name, emoji=emoji, budget_amount=Decimal(str(budget)), is_rollover=True))
        await db.commit()
    lines = [f"✅ {len(template)} amplop dibuat!\n"]
    for emoji, name, budget in template:
        lines.append(f"{emoji} {name} — {format_currency(Decimal(str(budget)))}")
    lines.append(f"\nKirim pengeluaran: 35k starbucks\nAtau /status untuk lihat budget.")
    await query.edit_message_text("\n".join(lines))

async def cmd_batal(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        result = await db.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.is_deleted == False,
                # penyesuaian cocokkan saldo bukan "transaksi terakhir yang user input"
                Transaction.balance_check_id.is_(None),
            )
            .order_by(Transaction.created_at.desc()).limit(1)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            await update.message.reply_text("Nggak ada transaksi yang bisa dibatalkan.")
            return
        txn.is_deleted = True
        await db.commit()
    await update.message.reply_text(f"↩️ Dibatalkan: {format_currency(txn.amount)} — {masked_description(user.id, txn)}")

async def handle_message(update, context):
    text = update.message.text.strip()
    if text.startswith("/"):
        return

    # Input length guard
    if len(text) > 500:
        await update.message.reply_text("⚠️ Pesan terlalu panjang.")
        return

    # Per-user Redis rate limit: max 30 messages/minute
    user_id = update.effective_user.id
    try:
        import redis.asyncio as aioredis
        _r = aioredis.from_url(settings.REDIS_URL)
        rl_key = f"bot:rl:{user_id}"
        count = await _r.incr(rl_key)
        if count == 1:
            await _r.expire(rl_key, 60)
        await _r.aclose()
        if count > 30:
            await update.message.reply_text("⏳ Terlalu banyak pesan. Coba lagi sebentar.")
            return
    except Exception:
        pass  # Redis down → fail open
    # Check for what-if question first
    from app.bot.checkin_cmd import is_whatif, handle_whatif
    if is_whatif(text):
        await handle_whatif(update, context)
        return

    # Natural language query handlers (no amount = pure query intent)
    from app.bot.nlp_cmd import (
        is_sisa, is_harian, is_proyeksi, is_comparison,
        is_santai, is_emosi, is_koreksi, is_nabung, parse_multi_expense,
        is_pengeluaran_hari_ini, is_pengeluaran_hari_lalu, strip_date_numbers,
        handle_sisa, handle_limit_harian, handle_proyeksi, handle_comparison,
        handle_santai, handle_emosi, handle_koreksi, handle_nabung,
        handle_pengeluaran_hari_ini, handle_pengeluaran_hari_lalu,
    )
    if is_emosi(text) and not parse_amount(text):
        await handle_emosi(update, context)
        return
    if is_koreksi(text):
        await handle_koreksi(update, context)
        return
    if is_nabung(text) and not parse_subscription(text):
        await handle_nabung(update, context)
        return
    # Specific queries before general balance (avoids SISA_RE swallowing them)
    if is_pengeluaran_hari_ini(text) and not parse_amount(text):
        await handle_pengeluaran_hari_ini(update, context)
        return
    if is_pengeluaran_hari_lalu(text) and not parse_amount(strip_date_numbers(text)):
        await handle_pengeluaran_hari_lalu(update, context)
        return
    if is_harian(text) and not parse_amount(text):
        await handle_limit_harian(update, context)
        return
    if is_proyeksi(text):
        await handle_proyeksi(update, context)
        return
    if is_comparison(text) and not parse_amount(text):
        await handle_comparison(update, context)
        return
    if is_sisa(text) and not parse_amount(text):
        await handle_sisa(update, context)
        return
    if is_santai(text) and not parse_amount(text):
        await handle_santai(update, context)
        return

    # Multi-expense: "makan 30k, parkir 5k, kopi 20k"
    multi_items = parse_multi_expense(text)
    if multi_items:
        from app.bot.batch_cmd import handle_multi_expense
        await handle_multi_expense(update, context, multi_items)
        return

    # Check for subscription intent first
    sub = parse_subscription(text)
    if sub:
        amount, description, freq_name, months = sub
        freq_map = {"weekly": "mingguan", "biweekly": "2 mingguan", "monthly": "bulanan", "biannual": "6 bulanan", "yearly": "tahunan"}
        # Handle custom intervals like "2monthly", "3yearly"
        if freq_name.endswith("monthly") and freq_name != "monthly":
            n = freq_name.replace("monthly", "")
            freq_label = f"setiap {n} bulan"
        elif freq_name.endswith("weekly") and freq_name not in ("weekly", "biweekly"):
            n = freq_name.replace("weekly", "")
            freq_label = f"setiap {n} minggu"
        elif freq_name.endswith("yearly") and freq_name != "yearly":
            n = freq_name.replace("yearly", "")
            freq_label = f"setiap {n} tahun"
        else:
            freq_label = freq_map.get(freq_name, freq_name)
        from app.models.models import RecurringFrequency
        freq_db_map = {"weekly": RecurringFrequency.weekly, "monthly": RecurringFrequency.monthly, "yearly": RecurringFrequency.yearly, "biannual": RecurringFrequency.monthly, "biweekly": RecurringFrequency.weekly}
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            setup_ok, reason = await _is_setup_complete(user, db)
            if not setup_ok:
                await reply_setup_needed(update, user)
                return
            hid = await get_household_id(user, db)
            from sqlalchemy import or_ as sql_or
            env_result = await db.execute(
                select(Envelope).where(Envelope.household_id == hid, Envelope.is_active == True,
                    sql_or(Envelope.owner_id == None, Envelope.owner_id == user.id))
                .order_by(Envelope.created_at))
            envs = env_result.scalars().all()
        # Store sub data in Redis (callback_data has 64 byte limit)
        import redis.asyncio as aioredis, json as json_mod, secrets
        from app.core.config import get_settings
        sub_key = secrets.token_hex(4)
        r = aioredis.from_url(get_settings().REDIS_URL)
        await r.set(f"sub:{sub_key}", json_mod.dumps({
            "amount": int(amount), "desc": description, "freq": freq_name,
        }), ex=300)
        await r.close()
        keyboard = []
        for e in envs:
            emoji = e.emoji or "📁"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {e.name}",
                callback_data=f"addsub_{sub_key}_{e.id}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="addsub_cancel")])
        await update.message.reply_text(
            f"🔄 Langganan terdeteksi!\n\n"
            f"{format_currency(amount)} — {description}\n"
            f"Frekuensi: {freq_label}\n\n"
            f"Masuk ke amplop mana?",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return

    parsed = parse_amount(text)
    if not parsed:
        # Check global learned intent phrases before giving up
        from app.bot.intent_learning import lookup_intent, show_intent_suggestions
        from app.core.database import AsyncSessionLocal as _ASL
        async with _ASL() as _db:
            learned = await lookup_intent(text, _db)
        if learned:
            from app.bot.nlp_cmd import (
                handle_pengeluaran_hari_ini, handle_sisa, handle_limit_harian,
                handle_proyeksi, handle_comparison, handle_santai,
            )
            _intent_handlers = {
                "pengeluaran_hari_ini": handle_pengeluaran_hari_ini,
                "sisa": handle_sisa,
                "harian": handle_limit_harian,
                "proyeksi": handle_proyeksi,
                "comparison": handle_comparison,
                "santai": handle_santai,
            }
            _h = _intent_handlers.get(learned)
            if _h:
                await _h(update, context)
                return
        # Unknown — show learning suggestion buttons
        await show_intent_suggestions(update, text, settings)
        return
    amount, description = parsed
    if not description:
        description = "Pengeluaran"
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)

        setup_ok, reason = await _is_setup_complete(user, db)
        if not setup_ok:
            await reply_setup_needed(update, user)
            return

        hid = await get_household_id(user, db)
        payday_day = getattr(user, 'payday_day', 1) or 1
        envelope, confident = await find_best_envelope(description, hid, db, user_id=user.id)
        if not envelope:
            envelopes_check = _spendable_rows(await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day))
            if not envelopes_check:
                await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
                return
            import logging
            logging.getLogger("jatahku").warning(f"No envelope match for '{description}', showing keyboard with {len(envelopes_check)} options")
            import redis.asyncio as aioredis, json as json_mod, secrets
            from app.core.config import get_settings
            txn_key = secrets.token_hex(4)
            r = aioredis.from_url(get_settings().REDIS_URL)
            env_map = {}
            for idx, e in enumerate(envelopes_check):
                env_map[str(idx)] = str(e["envelope"].id)
            await r.set(f"txn:{txn_key}", json_mod.dumps({
                "amount": int(amount), "desc": description, "envs": env_map,
            }), ex=300)
            await r.close()
            keyboard = []
            for idx, e in enumerate(envelopes_check):
                env = e["envelope"]
                emoji = env.emoji or "\U0001f4c1"
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {env.name}",
                    callback_data=f"t_{txn_key}_{idx}")])
            await update.message.reply_text(
                f"\U0001f4b0 {format_currency(amount)} \u2014 {description}\n\nMasuk ke amplop mana?",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return
        if confident:
            # Aturan yang sama dengan web (app/services/expense_rules.py)
            check = await check_expense(envelope, user, amount, db)
            if not check.allowed:
                if await _reply_blocked_basic(update.message.reply_text, check):
                    return
                elif check.check_type in FUNDS_BLOCKS:
                    await _send_fund_shift_offer(
                        lambda t, **kw: update.message.reply_text(t, **kw),
                        str(tg_user.id), user, hid, envelope, amount, description, db,
                    )
                    return
                elif check.check_type == "daily_limit":
                    d = check.details
                    d["description"] = description
                    await _send_daily_limit_blocked(
                        lambda t, **kw: update.message.reply_text(t, **kw),
                        str(tg_user.id), d, envelope, settings,
                    )
                    return

            txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
                description=description, source=txn_source(), transaction_date=date.today())
            db.add(txn)
            await db.commit()
            streak_line = _streak_text(await after_expense_recorded(db, user, envelope.id, description))
            envelopes = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
            env_data = next((e for e in envelopes if e["envelope"].id == envelope.id), None)
            remaining = env_data["remaining"] if env_data else Decimal("0")
            budget = envelope.budget_amount
            now = date.today()
            next_month = date(now.year + (1 if now.month == 12 else 0), (now.month % 12) + 1, 1)
            days_left = (next_month - now).days
            warning = ""
            if budget > 0:
                ratio = float((budget - remaining) / budget)
                if remaining <= 0:
                    warning = "\n\n🔴 Amplop ini sudah habis!"
                elif ratio >= 0.9:
                    warning = f"\n\n🔴 Hampir habis! Cukup {days_left} hari lagi?"
                elif ratio >= 0.7:
                    warning = f"\n\n🟡 Mulai menipis. Sisa untuk {days_left} hari."
            emoji = envelope.emoji or "📁"
            quota_line = await _quota_line(user, db)
            await update.message.reply_text(
                f"✅ {format_currency(amount)} — {description}\n"
                f"Masuk ke {emoji} {envelope.name}\n\n"
                f"Sisa: {format_currency(remaining)} (dana {format_currency(budget)}){warning}{streak_line}{quota_line}"
            )
        else:
            envelopes_data = _spendable_rows(await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day))
            import redis.asyncio as aioredis, json as json_mod, secrets
            from app.core.config import get_settings
            txn_key = secrets.token_hex(4)
            r = aioredis.from_url(get_settings().REDIS_URL)
            env_map = {}
            for idx, e in enumerate(envelopes_data):
                env_map[str(idx)] = str(e["envelope"].id)
            await r.set(f"txn:{txn_key}", json_mod.dumps({
                "amount": int(amount), "desc": description, "envs": env_map,
            }), ex=300)
            await r.close()
            keyboard = []
            for idx, e in enumerate(envelopes_data):
                env = e["envelope"]
                emoji = env.emoji or "\U0001f4c1"
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {env.name}",
                    callback_data=f"t_{txn_key}_{idx}")])
            await update.message.reply_text(
                f"\U0001f4b0 {format_currency(amount)} \u2014 {description}\n\nMasuk ke amplop mana?",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return
async def handle_txn_callback(update, context):
    """Kunci per sesi tombol (SET NX) supaya dua ketukan cepat — yang di mode
    webhook diproses bersamaan — tidak menyimpan transaksi ganda."""
    parts = (update.callback_query.data or "").split("_", 2)
    lock_key = f"txnlock:{parts[1]}" if len(parts) >= 3 else None
    r = None
    if lock_key:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL)
            if not await r.set(lock_key, "1", nx=True, ex=30):
                await r.aclose()
                await update.callback_query.answer("Sedang diproses...")
                return
        except Exception:
            r = None  # Redis mati → lanjut tanpa kunci (fail open, perilaku lama)
    try:
        await _handle_txn_callback(update, context)
    finally:
        if r is not None:
            try:
                await r.delete(lock_key)
                await r.aclose()
            except Exception:
                pass


async def _handle_txn_callback(update, context):
    query = update.callback_query
    await query.answer()
    # t_{redis_key}_{env_idx}
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("Error: data nggak valid.")
        return
    txn_key, env_idx = parts[1], parts[2]
    import redis.asyncio as aioredis, json as json_mod
    from app.core.config import get_settings
    r = aioredis.from_url(get_settings().REDIS_URL)
    txn_data = await r.get(f"txn:{txn_key}")
    await r.close()
    if not txn_data:
        await query.edit_message_text("\u23f0 Session expired. Kirim ulang.")
        return
    data = json_mod.loads(txn_data.decode())
    amount = Decimal(str(data["amount"]))
    description = data["desc"]
    envelope_id = data["envs"].get(env_idx)
    try:
        envelope_id = uuid.UUID(str(envelope_id)) if envelope_id else None
    except ValueError:
        envelope_id = None
    # Dari scan struk: tanggal struk + scan_id untuk feedback belajar (opsional).
    txn_date = date.today()
    if data.get("date"):
        try:
            txn_date = date.fromisoformat(data["date"])
        except ValueError:
            pass
    scan_id = data.get("scan_id")
    if not envelope_id:
        await query.edit_message_text("Error: amplop tidak valid.")
        return
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        payday_day = getattr(user, 'payday_day', 1) or 1
        import uuid as _uuid
        try:
            env_uuid = _uuid.UUID(str(envelope_id))
        except ValueError:
            await query.edit_message_text("Error: amplop tidak valid.")
            return
        result = await db.execute(select(Envelope).where(Envelope.id == env_uuid))
        envelope = result.scalar_one_or_none()
        if not envelope:
            await query.edit_message_text("Amplop nggak ditemukan.")
            return

        # Aturan yang sama dengan web (app/services/expense_rules.py)
        check = await check_expense(envelope, user, amount, db)
        if not check.allowed:
            if await _reply_blocked_basic(query.edit_message_text, check):
                return
            elif check.check_type in FUNDS_BLOCKS:
                await _send_fund_shift_offer(
                    lambda t, **kw: query.edit_message_text(t, **kw),
                    str(tg_user.id), user, hid, envelope, amount, description, db,
                    txn_date=txn_date, scan_id=scan_id,
                )
                return
            elif check.check_type == "daily_limit":
                d = check.details
                d["description"] = description
                d["date"] = txn_date.isoformat()
                d["scan_id"] = scan_id
                await _send_daily_limit_blocked(
                    lambda t, **kw: query.edit_message_text(t, **kw),
                    str(query.from_user.id), d, envelope, settings,
                )
                return

        txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
            description=description, source=txn_source(), transaction_date=txn_date)
        db.add(txn)
        await db.commit()
        streak_line = _streak_text(await after_expense_recorded(db, user, envelope.id, description))
        if scan_id:
            # Sesi terpisah — dulu db.rollback() di sini meng-expire user/amplop
            # sehingga baris di bawah (user.id, envelope.emoji) gagal (MissingGreenlet).
            await _receipt_feedback_saved(user.id, scan_id, amount, txn_date, description)
            r = aioredis.from_url(get_settings().REDIS_URL)
            await r.delete(f"txn:{txn_key}")  # cegah tersimpan dua kali dari tombol yang sama
            await r.aclose()
        envelopes = await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
        env_data = next((e for e in envelopes if e["envelope"].id == envelope.id), None)
        remaining = env_data["remaining"] if env_data else Decimal("0")
        quota_line = await _quota_line(user, db)
    emoji = envelope.emoji or "📁"
    await query.edit_message_text(
        f"✅ {format_currency(amount)} — {description}\n"
        f"Masuk ke {emoji} {envelope.name}\n\n"
        f"Sisa: {format_currency(remaining)} (dana {format_currency(envelope.budget_amount)}){streak_line}{quota_line}"
    )

async def handle_checkin_callback(update, context):
    """User tapped a button on the daily check-in nudge.

    checkin_none  → no spending today, but still keep the streak alive.
    """
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        from app.services.streak import record_activity, milestone_message
        res = await record_activity(db, user.id, getattr(user, "timezone", None))
    celebrate = milestone_message(res)
    tail = f"\n\n🔥 {celebrate}" if celebrate else (
        f"\n\n🔥 Streak {res.current_streak} hari!" if res.current_streak >= 2 else ""
    )
    await query.edit_message_text(
        f"👍 Oke, dicatat: hari ini tanpa pengeluaran.\n"
        f"Yang penting kamu tetap pantau — streak aman.{tail}"
    )

async def cmd_pending(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        pendings = await get_user_pending(user.id, db)
    if not pendings:
        await update.message.reply_text("Tidak ada transaksi pending.")
        return
    for p in pendings:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        can_confirm = now >= p.confirm_after
        confirm_time = p.confirm_after.strftime("%d %b %H:%M")
        keyboard = []
        if can_confirm:
            keyboard.append([InlineKeyboardButton("✅ Konfirmasi", callback_data=f"cool_confirm_{p.id}")])
        keyboard.append([InlineKeyboardButton("❌ Batalkan", callback_data=f"cool_cancel_{p.id}")])
        status_text = "✅ Bisa dikonfirmasi" if can_confirm else f"⏳ Tunggu sampai {confirm_time}"
        await update.message.reply_text(
            f"💰 {format_currency(p.amount)} — {masked_description(user.id, p)}\n"
            f"Status: {status_text}",
            reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_cooling_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("Error: data tidak valid.")
        return
    action = parts[1]  # confirm or cancel
    try:
        pending_id = uuid.UUID(parts[2])
    except ValueError:
        await query.edit_message_text("Error: data tidak valid.")
        return
    async with AsyncSessionLocal() as db:
        # Hanya transaksi pending milik user sendiri.
        tg_user = query.from_user
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        owned = await db.execute(select(PendingTransaction.id).where(
            PendingTransaction.id == pending_id, PendingTransaction.user_id == user.id,
        ))
        if owned.scalar_one_or_none() is None:
            await query.edit_message_text("❌ Transaksi pending tidak ditemukan")
            return
        if action == "confirm":
            result = await confirm_pending(pending_id, db)
            if "error" in result:
                await query.edit_message_text(f"❌ {result['error']}")
            else:
                await query.edit_message_text("✅ Transaksi dikonfirmasi dan tercatat!")
        elif action == "cancel":
            result = await cancel_pending(pending_id, db)
            if "error" in result:
                await query.edit_message_text(f"❌ {result['error']}")
            else:
                await query.edit_message_text("↩️ Transaksi pending dibatalkan.")


async def handle_addsub_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "addsub_cancel":
        await query.edit_message_text("❌ Dibatalkan.")
        return
    # addsub_{sub_key}_{env_id}
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("Error.")
        return
    sub_key, env_id = parts[1], parts[2]

    import redis.asyncio as aioredis, json as json_mod
    from app.core.config import get_settings
    r = aioredis.from_url(get_settings().REDIS_URL)
    sub_data = await r.get(f"sub:{sub_key}")
    await r.close()
    if not sub_data:
        await query.edit_message_text("⏰ Session expired. Kirim ulang.")
        return
    data = json_mod.loads(sub_data.decode())
    amount = Decimal(str(data["amount"]))
    desc = data["desc"]
    freq_name = data["freq"]

    from app.models.models import RecurringTransaction, RecurringFrequency
    # Map to DB frequency (closest match)
    if "weekly" in freq_name:
        db_freq = RecurringFrequency.weekly
    elif "yearly" in freq_name:
        db_freq = RecurringFrequency.yearly
    else:
        db_freq = RecurringFrequency.monthly

    # Calculate next_run based on freq_name
    from datetime import timedelta
    import re as re_mod
    now = date.today()
    num_match = re_mod.match(r"(\d+)", freq_name)
    num = int(num_match.group(1)) if num_match else 1

    if "weekly" in freq_name:
        next_run = now + timedelta(weeks=num)
    elif "yearly" in freq_name:
        next_run = date(now.year + num, now.month, min(now.day, 28))
    else:  # monthly variants
        m = now.month + num
        y = now.year
        while m > 12:
            m -= 12
            y += 1
        next_run = date(y, m, min(now.day, 28))

    tg_user = query.from_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)

        rec = RecurringTransaction(
            envelope_id=env_id, amount=amount, description=desc,
            frequency=db_freq, next_run=next_run, is_active=True,
        )
        db.add(rec)

        # Also record first payment as transaction
        from app.models.models import Transaction as TxnModel, TransactionSource
        txn = TxnModel(
            envelope_id=env_id, user_id=user.id, amount=amount,
            description=f"🔄 {desc}", source=txn_source(),
            transaction_date=date.today(),
        )
        db.add(txn)
        await db.commit()

        env_result = await db.execute(select(Envelope).where(Envelope.id == env_id))
        envelope = env_result.scalar_one_or_none()

    freq_map_label = {"weekly": "mingguan", "biweekly": "2 mingguan", "monthly": "bulanan", "biannual": "6 bulanan", "yearly": "tahunan"}
    if freq_name.endswith("monthly") and freq_name != "monthly":
        n = freq_name.replace("monthly", "")
        freq_display = f"setiap {n} bulan"
    elif freq_name.endswith("yearly") and freq_name != "yearly":
        n = freq_name.replace("yearly", "")
        freq_display = f"setiap {n} tahun"
    elif freq_name.endswith("weekly") and freq_name not in ("weekly", "biweekly"):
        n = freq_name.replace("weekly", "")
        freq_display = f"setiap {n} minggu"
    else:
        freq_display = freq_map_label.get(freq_name, freq_name)
    emoji = envelope.emoji if envelope else "📁"
    await query.edit_message_text(
        f"✅ Langganan ditambahkan + pembayaran pertama tercatat!\n\n"
        f"🔄 {desc} — {format_currency(amount)}/{freq_display}\n"
        f"Amplop: {emoji} {envelope.name if envelope else '-'}\n"
        f"💸 Pembayaran: -{format_currency(amount)}\n"
        f"Reminder berikut: {next_run.strftime('%d %b %Y')}"
    )


async def handle_non_text(update, context):
    """Handle photos, stickers, voice, etc."""
    doc = update.message.document
    if update.message.photo or (doc and (doc.mime_type or "").startswith("image/")):
        from app.bot.receipt_cmd import handle_receipt_photo
        await handle_receipt_photo(update, context)
    elif update.message.sticker:
        await update.message.reply_text("😄 Stiker lucu! Tapi saya cuma bisa bantu catat pengeluaran.\nKirim: `35k kopi`", parse_mode="Markdown")
    elif update.message.voice or update.message.audio:
        await update.message.reply_text("🎤 Voice message belum didukung.\nKirim teks: `35k kopi`", parse_mode="Markdown")
    elif update.message.document:
        await update.message.reply_text("📄 File belum didukung.\nKirim teks: `35k kopi`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Kirim pengeluaran seperti:\n• `35k starbucks`\n• `kopi 150rb`", parse_mode="Markdown")


async def post_init(application):
    """Set bot commands menu."""
    await application.bot.set_my_commands([
        ("status", "Ringkasan budget bulan ini"),
        ("amplop", "Daftar amplop & sisa dana"),
        ("pending", "Transaksi cooling period"),
        ("langganan", "Daftar langganan aktif"),
        ("batal", "Undo transaksi terakhir"),
        ("amplop_baru", "Buat amplop baru"),
        ("template", "Pilih template amplop"),
        ("lock", "Kunci/buka amplop"),
        ("controls", "Status behavior controls"),
        ("invite", "Buat kode invite household"),
        ("help", "Panduan lengkap"),
    ])


def bot_commands() -> dict:
    """Perintah /nama → handler. Satu daftar untuk Telegram dan chat webapp
    (app/bot/web_adapter.py), supaya keduanya selalu punya perintah yang sama."""
    from app.bot.help_cmd import cmd_help
    from app.bot.link_cmd import cmd_link, cmd_unlink
    from app.bot.behavior_cmd import cmd_lock, cmd_setlimit, cmd_setcooling, cmd_controls
    from app.bot.recurring_cmd import cmd_langganan, cmd_tambah_langganan, cmd_hapus_langganan
    from app.bot.household_cmd import cmd_invite, cmd_join
    from app.bot.tglogin_cmd import cmd_webapp
    return {
        "start": cmd_start,
        "help": cmd_help,
        "status": cmd_status,
        "amplop": cmd_amplop,
        "amplop_baru": cmd_amplop_baru,
        "template": cmd_template,
        "batal": cmd_batal,
        "link": cmd_link,
        "unlink": cmd_unlink,
        "pending": cmd_pending,
        "lock": cmd_lock,
        "setlimit": cmd_setlimit,
        "setcooling": cmd_setcooling,
        "controls": cmd_controls,
        "langganan": cmd_langganan,
        "tambah_langganan": cmd_tambah_langganan,
        "hapus_langganan": cmd_hapus_langganan,
        "invite": cmd_invite,
        "join": cmd_join,
        "webapp": cmd_webapp,
    }


async def handle_intent_learn(update, context):
    from app.bot.intent_learning import handle_intent_learn_callback
    await handle_intent_learn_callback(update.callback_query, context, settings)


def bot_callbacks() -> list:
    """(pola callback_data, handler) berurutan — yang pertama cocok dipakai.
    Satu daftar untuk Telegram dan chat webapp."""
    from app.bot.link_cmd import handle_merge_callback, handle_unlink_callback
    from app.bot.behavior_cmd import handle_lock_callback
    from app.bot.recurring_cmd import (
        handle_delrec_callback, handle_recpay_callback, handle_recskip_callback,
        handle_recstop_callback,
    )
    from app.bot.batch_cmd import (
        handle_batch_callback, handle_batch_limit_callback, handle_batch_shift_callback,
    )
    from app.bot.receipt_cmd import handle_struk_callback
    return [
        (r"^lock_", handle_lock_callback),
        (r"^delrec_", handle_delrec_callback),
        (r"^recpay_", handle_recpay_callback),
        (r"^recskip_", handle_recskip_callback),
        (r"^recstop_", handle_recstop_callback),
        (r"^addsub_", handle_addsub_callback),
        (r"^merge_", handle_merge_callback),
        (r"^unlink_", handle_unlink_callback),
        (r"^cool_", handle_cooling_callback),
        (r"^checkin_", handle_checkin_callback),
        (r"^tpl_", handle_template_callback),
        (r"^t_", handle_txn_callback),
        (r"^batch_", handle_batch_callback),
        (r"^bshift_", handle_batch_shift_callback),
        (r"^blimit_", handle_batch_limit_callback),
        (r"^struk_", handle_struk_callback),
        (r"^intentlearn:", handle_intent_learn),
        (r"^dlimit:", handle_daily_limit_callback),
        (r"^fshift:", handle_fund_shift_callback),
    ]


def create_bot_app():
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    for name, handler in bot_commands().items():
        app.add_handler(CommandHandler(name, handler))
    for pattern, handler in bot_callbacks():
        app.add_handler(CallbackQueryHandler(handler, pattern=pattern))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Sticker.ALL | filters.VOICE | filters.AUDIO | filters.Document.ALL, handle_non_text))

    return app
