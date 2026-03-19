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
)

settings = get_settings()
logger = logging.getLogger("jatahku.bot")

AMOUNT_PATTERN = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu|k)?\s*(.+)?$", re.IGNORECASE
)
MULTIPLIERS = {"jt": 1_000_000, "juta": 1_000_000, "rb": 1_000, "ribu": 1_000, "k": 1_000}

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
    match = AMOUNT_PATTERN.match(text.strip())
    if not match:
        return None
    number_str = match.group(1).replace(",", ".")
    multiplier_str = match.group(2)
    description = (match.group(3) or "").strip()
    try:
        number = float(number_str)
    except ValueError:
        return None
    multiplier = MULTIPLIERS.get(multiplier_str.lower(), 1) if multiplier_str else 1
    amount = Decimal(str(int(number * multiplier)))
    if amount <= 0:
        return None
    return amount, description

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

async def get_envelopes_with_spent(household_id, db):
    now = date.today()
    result = await db.execute(
        select(Envelope).where(Envelope.household_id == household_id, Envelope.is_active == True).order_by(Envelope.created_at)
    )
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
        allocated_result = await db.execute(
            select(func.coalesce(func.sum(Allocation.amount), 0)).where(Allocation.envelope_id == env.id)
        )
        allocated = Decimal(str(allocated_result.scalar()))
        remaining = env.budget_amount + allocated - spent
        envelope_data.append({"envelope": env, "spent": spent, "allocated": allocated, "remaining": remaining})
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

async def cmd_start(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name or "User", db)
        hid = await get_household_id(user, db)
        result = await db.execute(
            select(func.count(Envelope.id)).where(Envelope.household_id == hid, Envelope.is_active == True)
        )
        envelope_count = result.scalar()
    if envelope_count == 0:
        await update.message.reply_text(
            f"Halo {tg_user.first_name}! Selamat datang di Jatahku 🎉\n\n"
            f"Setiap rupiah ada jatahnya.\n\n"
            f"Kamu belum punya amplop. Ketik /template untuk pakai template siap pakai."
        )
    else:
        await update.message.reply_text(
            f"Halo {tg_user.first_name}! 👋\n\nKamu punya {envelope_count} amplop aktif.\n\n"
            f"Cara pakai:\n• Kirim: 35k starbucks\n• /status — ringkasan budget\n"
            f"• /amplop — list amplop\n• /batal — undo terakhir"
        )

async def cmd_status(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        if not hid:
            await update.message.reply_text("Ketik /start dulu.")
            return
        envelopes = await get_envelopes_with_spent(hid, db)
    if not envelopes:
        await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
        return
    now = date.today()
    next_month = date(now.year + (1 if now.month == 12 else 0), (now.month % 12) + 1, 1)
    days_left = (next_month - now).days
    total_budget = sum(e["envelope"].budget_amount for e in envelopes)
    total_spent = sum(e["spent"] for e in envelopes)
    total_remaining = total_budget - total_spent
    lines = [f"📊 Budget {now.strftime('%B %Y')} — {days_left} hari lagi\n"]
    lines.append(f"Total: {format_currency(total_remaining)} / {format_currency(total_budget)}\n")
    for e in envelopes:
        env = e["envelope"]
        spent, remaining, budget = e["spent"], e["remaining"], env.budget_amount
        emoji = env.emoji or "📁"
        bar = progress_bar(spent, budget)
        if budget > 0:
            ratio = float(spent / budget)
            indicator = "🔴" if ratio >= 0.9 else ("🟡" if ratio >= 0.7 else "🟢")
        else:
            indicator = "⚪"
        lines.append(f"{indicator} {emoji} {env.name}\n   {bar} {format_currency(remaining)}")
    await update.message.reply_text("\n".join(lines))

async def cmd_amplop(update, context):
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envelopes = await get_envelopes_with_spent(hid, db)
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
    parsed = parse_amount(text)
    if not parsed:
        await update.message.reply_text("Nggak bisa baca itu. Kirim format seperti:\n• 35k starbucks\n• 150rb nasi padang\n• 2.5jt beli headphone")
        return
    amount, description = parsed
    if not description:
        description = "Pengeluaran"
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        if not hid:
            await update.message.reply_text("Ketik /start dulu.")
            return
        envelope, confident = await find_best_envelope(description, hid, db)
        if not envelope:
            envelopes_check = await get_envelopes_with_spent(hid, db)
            if not envelopes_check:
                await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
                return
            keyboard = []
            for e in envelopes_check:
                env = e["envelope"]
                emoji = env.emoji or "📁"
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {env.name} (sisa {format_currency(e['remaining'])})",
                    callback_data=f"txn_{env.id}_{amount}_{description[:50]}")])
            await update.message.reply_text(
                f"💰 {format_currency(amount)} — {description}\n\nMasuk ke amplop mana?",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return
        if confident:
            txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
                description=description, source=TransactionSource.telegram, transaction_date=date.today())
            db.add(txn)
            await db.commit()
            envelopes = await get_envelopes_with_spent(hid, db)
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
                f"Sisa amplop: {format_currency(remaining)} / {format_currency(budget)}{warning}"
            )
        else:
            envelopes_data = await get_envelopes_with_spent(hid, db)
            keyboard = []
            for e in envelopes_data:
                env = e["envelope"]
                emoji = env.emoji or "📁"
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {env.name} (sisa {format_currency(e['remaining'])})",
                    callback_data=f"txn_{env.id}_{amount}_{description[:50]}"
                )])
            await update.message.reply_text(
                f"💰 {format_currency(amount)} — {description}\n\nMasuk ke amplop mana?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_txn_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 3)
    if len(parts) < 4:
        await query.edit_message_text("Error: data nggak valid.")
        return
    envelope_id, amount, description = parts[1], Decimal(parts[2]), parts[3]
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        result = await db.execute(select(Envelope).where(Envelope.id == envelope_id))
        envelope = result.scalar_one_or_none()
        if not envelope:
            await query.edit_message_text("Amplop nggak ditemukan.")
            return
        txn = Transaction(envelope_id=envelope.id, user_id=user.id, amount=amount,
            description=description, source=TransactionSource.telegram, transaction_date=date.today())
        db.add(txn)
        await db.commit()
        envelopes = await get_envelopes_with_spent(hid, db)
        env_data = next((e for e in envelopes if e["envelope"].id == envelope.id), None)
        remaining = env_data["remaining"] if env_data else Decimal("0")
    emoji = envelope.emoji or "📁"
    await query.edit_message_text(
        f"✅ {format_currency(amount)} — {description}\n"
        f"Masuk ke {emoji} {envelope.name}\n\n"
        f"Sisa amplop: {format_currency(remaining)} / {format_currency(envelope.budget_amount)}"
    )

def create_bot_app():
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("amplop", cmd_amplop))
    app.add_handler(CommandHandler("amplop_baru", cmd_amplop_baru))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("batal", cmd_batal))
    from app.bot.link_cmd import cmd_link
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CallbackQueryHandler(handle_template_callback, pattern=r"^tpl_"))
    app.add_handler(CallbackQueryHandler(handle_txn_callback, pattern=r"^txn_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
