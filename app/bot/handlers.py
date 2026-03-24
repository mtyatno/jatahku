import re
import logging
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
from app.services.behavior import check_behavior, create_pending_transaction, confirm_pending, cancel_pending, get_user_pending

settings = get_settings()
logger = logging.getLogger("jatahku.bot")

# Matches amount anywhere in text: "35k kopi", "kopi 35k", "beli kopi 35rb"
AMOUNT_ANYWHERE = re.compile(
    r"(?:rp\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+(?:[,]\d+)?)\s*(jt|juta|rb|ribu|k)?(?!\w)|(?:rp\.?\s*)(\d+)", re.IGNORECASE
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

CATEGORY_KEYWORDS = {
    "makan": ["makan", "nasi", "ayam", "sate", "bakso", "mie", "noodle", "rice",
              "lunch", "dinner", "breakfast", "sarapan", "siang", "malam",
              "warteg", "padang", "resto", "restaurant", "cafe", "kafe",
              "kopi", "coffee", "starbucks", "mcd", "kfc", "pizza",
              "gofood", "grabfood", "shopeefood", "snack", "jajan"],
    "transport": ["grab", "gojek", "ojek", "taxi", "bensin", "parkir",
                  "tol", "busway", "mrt", "krl", "kereta", "bus",
                  "transport", "uber", "maxim", "indriver"],
    "hiburan": ["nonton", "film", "bioskop", "game", "steam", "netflix",
                "spotify", "youtube", "premium", "langganan", "subscribe",
                "hangout", "karaoke", "mall"],
    "belanja": ["beli", "shopee", "tokped", "tokopedia", "lazada", "belanja", "online", "shop"],
    "tagihan": ["listrik", "air", "pdam", "internet", "wifi", "pulsa",
                "token", "indihome", "telkom", "pln"],
}

def parse_amount(text):
    """Parse amount from anywhere in text. Returns (amount, description) or None."""
    match = AMOUNT_ANYWHERE.search(text.strip())
    if not match:
        return None

    if match.group(1):
        number_str = match.group(1)
        multiplier_str = match.group(2)
    elif match.group(3):
        number_str = match.group(3)
        multiplier_str = None
    else:
        return None

    # Handle Indonesian thousand separator: 17.000 = 17000, 1.500.000 = 1500000
    if re.match(r"^\d{1,3}(\.\d{3})+$", number_str):
        number_str = number_str.replace(".", "")
        number = float(number_str)
    else:
        number_str = number_str.replace(",", ".")
        number = float(number_str)

    try:
        pass
    except ValueError:
        return None

    multiplier = MULTIPLIERS.get(multiplier_str.lower(), 1) if multiplier_str else 1
    amount = Decimal(str(int(number * multiplier)))
    if amount <= 0:
        return None
    # Description = everything except the amount part + clean "rp" prefix
    desc = text.strip()[:match.start()].strip() + " " + text.strip()[match.end():].strip()
    desc = desc.strip()
    # Clean up subscription keywords from description
    for pat, _, _ in SUB_PATTERNS:
        desc = pat.sub("", desc).strip()
    if not desc:
        desc = "Pengeluaran"
    return amount, desc


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
            return amount, clean_desc or desc, freq_name, months
    # Check subscription keywords (sewa, langganan, kontrak, etc) → default monthly
    if SUB_KEYWORDS.search(text):
        clean_desc = SUB_KEYWORDS.sub("", desc).strip()
        # Also clean from original text for better desc
        if not clean_desc:
            clean_desc = desc
        return amount, clean_desc, "monthly", 1
    return None

def guess_envelope_name(description):
    desc_lower = description.lower()
    for envelope_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return envelope_name
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
        return "░" * width
    ratio = min(float(spent / budget), 1.0)
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)

async def get_or_create_user(telegram_id, name, db):
    result = await db.execute(select(User).where(User.telegram_id == str(telegram_id)))
    user = result.scalar_one_or_none()
    if user:
        return user
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

async def get_envelopes_with_spent(household_id, db, user_id=None):
    now = date.today()
    from sqlalchemy import or_
    from app.models.models import Income, RecurringTransaction, RecurringFrequency
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
                func.extract("year", Transaction.transaction_date) == now.year,
                func.extract("month", Transaction.transaction_date) == now.month,
            )
        )
        spent = Decimal(str(spent_result.scalar()))
        alloc_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .join(Income, Allocation.income_id == Income.id)
            .where(
                Allocation.envelope_id == env.id,
                func.extract("year", Income.income_date) == now.year,
                func.extract("month", Income.income_date) == now.month,
            )
        )
        allocated = Decimal(str(alloc_result.scalar()))
        # Reserved from subscriptions
        rec_result = await db.execute(
            select(RecurringTransaction).where(
                RecurringTransaction.envelope_id == env.id,
                RecurringTransaction.is_active == True,
            )
        )
        reserved = Decimal("0")
        for rec in rec_result.scalars().all():
            if rec.frequency == RecurringFrequency.weekly:
                reserved += rec.amount * 4
            elif rec.frequency == RecurringFrequency.yearly:
                reserved += rec.amount / 12
            else:
                reserved += rec.amount
        remaining = allocated - spent
        free = remaining - reserved
        envelope_data.append({
            "envelope": env, "spent": spent, "allocated": allocated,
            "remaining": remaining, "reserved": reserved, "free": free,
        })
    return envelope_data

async def find_best_envelope(description, household_id, db):
    guessed_name = guess_envelope_name(description)
    if guessed_name:
        result = await db.execute(
            select(Envelope).where(
                Envelope.household_id == household_id, Envelope.is_active == True,
                func.lower(Envelope.name) == guessed_name.lower(),
            )
        )
        envelope = result.scalar_one_or_none()
        if envelope:
            return envelope, True
    return None, False

async def _is_setup_complete(user, db):
    """Check if user has linked WebApp + has envelopes."""
    if not user.email:
        return False, "not_linked"
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
            code = arg.replace("link_", "")
            import redis.asyncio as aioredis
            from app.core.config import get_settings
            r = aioredis.from_url(get_settings().REDIS_URL)
            user_id = await r.get(f"link:webapp:{code}")
            await r.close()
            if user_id:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(User).where(User.id == user_id.decode()))
                    webapp_user = result.scalar_one_or_none()
                    if webapp_user:
                        webapp_user.telegram_id = str(tg_user.id)
                        await db.commit()
                        await update.message.reply_text(
                            f"\u2705 Berhasil! Akun terhubung dengan {webapp_user.name}.\n\n"
                            f"Sekarang kirim pengeluaran lewat chat:\n"
                            f"\u2022 `kopi 35k`\n\u2022 `makan 25rb`",
                            parse_mode="Markdown")
                        return
            await update.message.reply_text("\u274c Kode expired. Generate baru di jatahku.com/settings")
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
    elif reason == "no_envelopes":
        await update.message.reply_text(
            f"Hai {tg_user.first_name}! \U0001f44b\n\n"
            f"Akun Telegram sudah terhubung.\n"
            f"Tapi kamu belum setup budget.\n\n"
            f"\U0001f310 Buka *jatahku.com* untuk:\n"
            f"1. Input income bulanan\n"
            f"2. Pilih template amplop\n"
            f"3. Alokasikan dana\n\n"
            f"Setelah itu, kamu bisa catat pengeluaran di sini!",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"Hai {tg_user.first_name}! \U0001f44b\n"
            f"Selamat datang di *Jatahku* \u2014 pengendali keuangan kamu.\n\n"
            f"Untuk mulai, hubungkan Telegram ke WebApp:\n\n"
            f"1\ufe0f\u20e3 Buka *jatahku.com*\n"
            f"2\ufe0f\u20e3 Daftar / Login\n"
            f"3\ufe0f\u20e3 Masuk ke Settings\n"
            f"4\ufe0f\u20e3 Generate kode link\n"
            f"5\ufe0f\u20e3 Kirim `/link KODE` di sini\n\n"
            f"\U0001f4d6 /help untuk panduan lengkap",
            parse_mode="Markdown",
        )


async def cmd_status(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        if not hid:
            await update.message.reply_text("Ketik /start dulu.")
            return
        envelopes = await get_envelopes_with_spent(hid, db, user.id)
    if not envelopes:
        await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
        return
    now = date.today()
    next_month = date(now.year + (1 if now.month == 12 else 0), (now.month % 12) + 1, 1)
    days_left = (next_month - now).days
    total_allocated = sum(e["allocated"] for e in envelopes)
    total_spent = sum(e["spent"] for e in envelopes)
    total_free = sum(e["free"] for e in envelopes)
    lines = [f"📊 Budget {now.strftime('%B %Y')} — {days_left} hari lagi\n"]
    lines.append(f"Dana: {format_currency(total_allocated)} | Terpakai: {format_currency(total_spent)} | Sisa: {format_currency(total_free)}\n")
    for e in envelopes:
        env = e["envelope"]
        spent, allocated, free = e["spent"], e["allocated"], e["free"]
        emoji = env.emoji or "📁"
        bar = progress_bar(spent, allocated)
        if allocated > 0:
            ratio = float(spent / allocated)
            indicator = "🔴" if ratio >= 0.9 else ("🟡" if ratio >= 0.7 else "🟢")
        else:
            indicator = "⚪"
        lines.append(f"{indicator} {emoji} {env.name}\n   {bar} {format_currency(free)}")
    await update.message.reply_text("\n".join(lines))

async def cmd_amplop(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envelopes = await get_envelopes_with_spent(hid, db, user.id)
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
        await update.message.reply_text("Format: /amplop_baru [nama] [budget]\n\nContoh:\n• /amplop_baru Makan 1.5jt\n• /amplop_baru Transport 500k")
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
        db.add(Envelope(household_id=hid, name=name, budget_amount=budget, is_rollover=True))
        await db.commit()
    await update.message.reply_text(f"✅ Amplop '{name}' dibuat! Budget: {format_currency(budget)}/bulan.")

TEMPLATES = {
    "tpl_karyawan": [("🍜","Makan",1500000),("🚗","Transport",500000),("🎬","Hiburan",300000),("📱","Tagihan",500000),("💰","Tabungan",1000000)],
    "tpl_mahasiswa": [("🍜","Makan",800000),("🚗","Transport",200000),("🎬","Hiburan",200000),("📚","Kuliah",300000)],
    "tpl_keluarga": [("🍜","Makan",3000000),("🚗","Transport",1000000),("🏠","Rumah",2000000),("📱","Tagihan",800000),("🎬","Hiburan",500000),("💰","Tabungan",2000000)],
}

async def cmd_template(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        result = await db.execute(select(func.count(Envelope.id)).where(Envelope.household_id == hid, Envelope.is_active == True))
        if result.scalar() > 0:
            await update.message.reply_text("Kamu sudah punya amplop. Gunakan /amplop_baru untuk tambah.")
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
            select(Transaction).where(Transaction.user_id == user.id, Transaction.is_deleted == False)
            .order_by(Transaction.created_at.desc()).limit(1)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            await update.message.reply_text("Nggak ada transaksi yang bisa dibatalkan.")
            return
        txn.is_deleted = True
        await db.commit()
    await update.message.reply_text(f"↩️ Dibatalkan: {format_currency(txn.amount)} — {txn.description}")

async def handle_message(update, context):
    text = update.message.text.strip()
    if text.startswith("/"):
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
                await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com\nKetik /start untuk panduan.")
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
        await update.message.reply_text("Nggak bisa baca itu. Kirim format seperti:\n• 35k starbucks\n• kopi 35rb\n• 2.5jt beli headphone")
        return
    amount, description = parsed
    if not description:
        description = "Pengeluaran"
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)

        setup_ok, reason = await _is_setup_complete(user, db)
        if not setup_ok:
            if reason == "not_linked":
                await update.message.reply_text(
                    "⚠️ Hubungkan Telegram ke WebApp dulu.\n"
                    "Buka jatahku.com → Settings → Link Telegram\n\n"
                    "Ketik /start untuk panduan.")
            else:
                await update.message.reply_text(
                    "⚠️ Belum ada amplop. Setup budget dulu di jatahku.com\n\n"
                    "Ketik /start untuk panduan.")
            return

        hid = await get_household_id(user, db)
        envelope, confident = await find_best_envelope(description, hid, db)
        if not envelope:
            envelopes_check = await get_envelopes_with_spent(hid, db, user.id)
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
            # Run behavior checks
            check = await check_behavior(envelope.id, user.id, amount, db)
            if not check.allowed:
                if check.check_type == "locked":
                    await update.message.reply_text(f"🔒 {check.reason}")
                    return
                elif check.check_type == "not_funded":
                    await update.message.reply_text(
                        f"💸 {check.reason}\n\nBuka jatahku.com/allocate untuk alokasi income.")
                    return
                elif check.check_type == "insufficient":
                    d = check.details
                    await update.message.reply_text(
                        f"💸 {check.reason}\n\n"
                        f"Sisa dana: {format_currency(d['available'])}\n"
                        f"Diminta: {format_currency(d['requested'])}")
                    return
                elif check.check_type == "daily_limit":
                    d = check.details
                    await update.message.reply_text(
                        f"⚠️ {check.reason}\n\n"
                        f"Limit harian: {format_currency(d['daily_limit'])}\n"
                        f"Sudah terpakai: {format_currency(d['spent_today'])}\n"
                        f"Sisa limit: {format_currency(d['remaining_today'])}\n"
                        f"Diminta: {format_currency(d['requested'])}")
                    return
                elif check.check_type == "cooling":
                    pending = await create_pending_transaction(
                        envelope.id, user.id, amount, description,
                        TransactionSource.telegram, cooling_hours=24, db=db)
                    from datetime import datetime, timezone
                    confirm_time = pending.confirm_after.strftime("%d %b %H:%M")
                    keyboard = [
                        [InlineKeyboardButton("❌ Batalkan", callback_data=f"cool_cancel_{pending.id}")],
                    ]
                    emoji = envelope.emoji or "📁"
                    await update.message.reply_text(
                        f"⏳ Cooling period aktif\n\n"
                        f"{format_currency(amount)} — {description}\n"
                        f"Amplop: {emoji} {envelope.name}\n\n"
                        f"Transaksi bisa dikonfirmasi setelah:\n"
                        f"🕐 {confirm_time} WIB (24 jam)\n\n"
                        f"Saya akan kirim reminder saat sudah bisa dikonfirmasi.",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return

            txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
                description=description, source=TransactionSource.telegram, transaction_date=date.today())
            db.add(txn)
            await db.commit()
            envelopes = await get_envelopes_with_spent(hid, db, user.id)
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
            await update.message.reply_text(
                f"✅ {format_currency(amount)} — {description}\n"
                f"Masuk ke {emoji} {envelope.name}\n\n"
                f"Sisa: {format_currency(remaining)} (dana {format_currency(budget)}){warning}"
            )
        else:
            envelopes_data = await get_envelopes_with_spent(hid, db, user.id)
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
    if not envelope_id:
        await query.edit_message_text("Error: amplop tidak valid.")
        return
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        result = await db.execute(select(Envelope).where(Envelope.id == envelope_id))
        envelope = result.scalar_one_or_none()
        if not envelope:
            await query.edit_message_text("Amplop nggak ditemukan.")
            return

        # Run behavior checks
        check = await check_behavior(envelope.id, user.id, amount, db)
        if not check.allowed:
            if check.check_type == "locked":
                await query.edit_message_text(f"🔒 {check.reason}")
                return
            elif check.check_type == "not_funded":
                await query.edit_message_text(
                    f"💸 {check.reason}\nBuka jatahku.com/allocate untuk alokasi income.")
                return
            elif check.check_type == "insufficient":
                d = check.details
                await query.edit_message_text(
                    f"💸 {check.reason}\n"
                    f"Sisa dana: {format_currency(d['available'])}\n"
                    f"Diminta: {format_currency(d['requested'])}")
                return
            elif check.check_type == "daily_limit":
                d = check.details
                await query.edit_message_text(
                    f"⚠️ {check.reason}\n\n"
                    f"Limit harian: {format_currency(d['daily_limit'])}\n"
                    f"Sudah terpakai: {format_currency(d['spent_today'])}\n"
                    f"Sisa limit: {format_currency(d['remaining_today'])}\n"
                    f"Diminta: {format_currency(d['requested'])}")
                return
            elif check.check_type == "cooling":
                pending = await create_pending_transaction(
                    envelope.id, user.id, amount, description,
                    TransactionSource.telegram, cooling_hours=24, db=db)
                confirm_time = pending.confirm_after.strftime("%d %b %H:%M")
                emoji = envelope.emoji or "📁"
                await query.edit_message_text(
                    f"⏳ Cooling period aktif\n\n"
                    f"{format_currency(amount)} — {description}\n"
                    f"Amplop: {emoji} {envelope.name}\n\n"
                    f"Bisa dikonfirmasi setelah:\n"
                    f"🕐 {confirm_time} WIB (24 jam)\n\n"
                    f"Ketik /pending untuk lihat status.")
                return

        txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
            description=description, source=TransactionSource.telegram, transaction_date=date.today())
        db.add(txn)
        await db.commit()
        envelopes = await get_envelopes_with_spent(hid, db, user.id)
        env_data = next((e for e in envelopes if e["envelope"].id == envelope.id), None)
        remaining = env_data["remaining"] if env_data else Decimal("0")
    emoji = envelope.emoji or "📁"
    await query.edit_message_text(
        f"✅ {format_currency(amount)} — {description}\n"
        f"Masuk ke {emoji} {envelope.name}\n\n"
        f"Sisa: {format_currency(remaining)} (dana {format_currency(envelope.budget_amount)})"
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
            f"💰 {format_currency(p.amount)} — {p.description}\n"
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
    pending_id = parts[2]
    async with AsyncSessionLocal() as db:
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
            description=f"🔄 {desc}", source=TransactionSource.telegram,
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
    if update.message.photo:
        await update.message.reply_text(
            "📸 Fitur scan struk belum tersedia.\n"
            "Untuk catat pengeluaran, kirim seperti:\n"
            "• `35k starbucks`\n• `kopi 35rb`",
            parse_mode="Markdown")
    elif update.message.sticker:
        await update.message.reply_text("😄 Stiker lucu! Tapi saya cuma bisa bantu catat pengeluaran.\nKirim: `35k kopi`", parse_mode="Markdown")
    elif update.message.voice or update.message.audio:
        await update.message.reply_text("🎤 Voice message belum didukung.\nKirim teks: `35k kopi`", parse_mode="Markdown")
    elif update.message.document:
        await update.message.reply_text("📄 File belum didukung.\nKirim teks: `35k kopi`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Kirim pengeluaran seperti:\n• `35k starbucks`\n• `kopi 150rb`", parse_mode="Markdown")


def create_bot_app():
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    from app.bot.help_cmd import cmd_help
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("amplop", cmd_amplop))
    app.add_handler(CommandHandler("amplop_baru", cmd_amplop_baru))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("batal", cmd_batal))
    from app.bot.link_cmd import cmd_link, cmd_unlink, handle_merge_callback, handle_unlink_callback
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("unlink", cmd_unlink))
    app.add_handler(CommandHandler("pending", cmd_pending))
    from app.bot.behavior_cmd import cmd_lock, cmd_setlimit, cmd_setcooling, cmd_controls, handle_lock_callback
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))
    app.add_handler(CommandHandler("setcooling", cmd_setcooling))
    app.add_handler(CommandHandler("controls", cmd_controls))
    app.add_handler(CallbackQueryHandler(handle_lock_callback, pattern=r"^lock_"))
    from app.bot.recurring_cmd import cmd_langganan, cmd_tambah_langganan, cmd_hapus_langganan, handle_delrec_callback, handle_recpay_callback, handle_recskip_callback, handle_recstop_callback
    app.add_handler(CommandHandler("langganan", cmd_langganan))
    app.add_handler(CommandHandler("tambah_langganan", cmd_tambah_langganan))
    app.add_handler(CommandHandler("hapus_langganan", cmd_hapus_langganan))
    app.add_handler(CallbackQueryHandler(handle_delrec_callback, pattern=r"^delrec_"))
    app.add_handler(CallbackQueryHandler(handle_recpay_callback, pattern=r"^recpay_"))
    app.add_handler(CallbackQueryHandler(handle_recskip_callback, pattern=r"^recskip_"))
    app.add_handler(CallbackQueryHandler(handle_recstop_callback, pattern=r"^recstop_"))
    app.add_handler(CallbackQueryHandler(handle_addsub_callback, pattern=r"^addsub_"))
    app.add_handler(CallbackQueryHandler(handle_merge_callback, pattern=r"^merge_"))
    app.add_handler(CallbackQueryHandler(handle_unlink_callback, pattern=r"^unlink_"))
    app.add_handler(CallbackQueryHandler(handle_cooling_callback, pattern=r"^cool_"))
    from app.bot.household_cmd import cmd_invite, cmd_join
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CallbackQueryHandler(handle_template_callback, pattern=r"^tpl_"))
    app.add_handler(CallbackQueryHandler(handle_txn_callback, pattern=r"^t_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    from telegram.ext import MessageHandler as MsgHandler
    app.add_handler(MsgHandler(filters.PHOTO | filters.Sticker.ALL | filters.VOICE | filters.AUDIO | filters.Document.ALL, handle_non_text))

    return app
