from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.models import Envelope, HouseholdMember
from app.bot.handlers import get_or_create_user, get_household_id, format_currency


async def _get_envelope_by_name(name, hid, user_id, db):
    """Exact match first, then partial/contains fallback (case-insensitive)."""
    from sqlalchemy import or_
    base = select(Envelope).where(
        Envelope.household_id == hid,
        Envelope.is_active == True,
        or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
    )
    # 1. Exact (case-insensitive)
    result = await db.execute(base.where(func.lower(Envelope.name) == name.strip().lower()))
    env = result.scalar_one_or_none()
    if env:
        return env
    # 2. Partial: name is contained in envelope.name (e.g. "rumah" → "Rumah dan isinya")
    result2 = await db.execute(
        base.where(func.lower(Envelope.name).contains(name.strip().lower()))
    )
    envs = result2.scalars().all()
    if len(envs) == 1:
        return envs[0]
    return None


async def _list_envelopes_names(hid, user_id, db):
    from sqlalchemy import or_
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
        ).order_by(Envelope.created_at)
    )
    return result.scalars().all()


async def cmd_lock(update, context):
    """/lock [nama_amplop] — toggle lock on/off"""
    if not context.args:
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            hid = await get_household_id(user, db)
            envs = await _list_envelopes_names(hid, user.id, db)
        if not envs:
            await update.message.reply_text("Belum ada amplop.")
            return
        keyboard = []
        for e in envs:
            emoji = e.emoji or "📁"
            status = "🔴 Locked" if e.is_locked else "🟢"
            keyboard.append([InlineKeyboardButton(
                f"{status} {emoji} {e.name}",
                callback_data=f"lock_{e.id}"
            )])
        await update.message.reply_text(
            "Pilih amplop untuk lock/unlock:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return

    name = " ".join(context.args)
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envelope = await _get_envelope_by_name(name, hid, user.id, db)

        if not envelope:
            envs = await _list_envelopes_names(hid, user.id, db)
            names = ", ".join([f"{e.emoji or '📁'} {e.name}" for e in envs])
            await update.message.reply_text(f"Amplop '{name}' nggak ditemukan.\n\nAmplop kamu: {names}")
            return

        envelope.is_locked = not envelope.is_locked
        await db.commit()
        emoji = envelope.emoji or "📁"

        if envelope.is_locked:
            await update.message.reply_text(f"🔒 {emoji} {envelope.name} dikunci.\nTidak bisa belanja sampai di-unlock.")
        else:
            await update.message.reply_text(f"🔓 {emoji} {envelope.name} di-unlock.\nBisa belanja lagi.")


async def cmd_setlimit(update, context):
    """/setlimit [nama_amplop] [jumlah] — set daily limit, 0 to remove"""
    if not context.args or len(context.args) < 2:
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            hid = await get_household_id(user, db)
            envs = await _list_envelopes_names(hid, user.id, db)
        if not envs:
            await update.message.reply_text("Belum ada amplop.")
            return
        lines = ["Format: /setlimit [nama] [jumlah]\n"]
        for e in envs:
            emoji = e.emoji or "📁"
            limit = f"📊 {format_currency(e.daily_limit)}/hari" if e.daily_limit else "Tidak ada"
            lines.append(f"{emoji} {e.name} — {limit}")
        lines.append("\nContoh: /setlimit Makan 200k\nHapus: /setlimit Makan 0")
        await update.message.reply_text("\n".join(lines))
        return

    # Last arg = amount, everything before = envelope name
    from app.bot.handlers import parse_amount
    amount_text = context.args[-1]
    name = " ".join(context.args[:-1]).strip("'\"")

    parsed = parse_amount(amount_text + " placeholder")
    if not parsed:
        # Maybe user put amount in the middle — show usage
        await update.message.reply_text(
            "Format: /setlimit [nama amplop] [jumlah]\n"
            "Contoh: /setlimit makan 200k\n"
            "        /setlimit Rumah dan isinya 400000"
        )
        return

    limit = parsed[0]
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envelope = await _get_envelope_by_name(name, hid, user.id, db)

        if not envelope:
            envs = await _list_envelopes_names(hid, user.id, db)
            names = ", ".join([f"{e.emoji or '📁'} {e.name}" for e in envs])
            await update.message.reply_text(
                f"Amplop '{name}' nggak ditemukan.\n\n"
                f"Amplop kamu:\n{names}\n\n"
                f"Tip: nama amplop tidak perlu harus persis — 'rumah' sudah cukup kalau unik."
            )
            return

        emoji = envelope.emoji or "📁"
        if limit <= 0:
            envelope.daily_limit = None
            await db.commit()
            await update.message.reply_text(f"✅ Daily limit {emoji} {envelope.name} dihapus.")
        else:
            envelope.daily_limit = limit
            await db.commit()
            await update.message.reply_text(
                f"✅ Daily limit {emoji} {envelope.name}: {format_currency(limit)}/hari\n\n"
                f"Pengeluaran melebihi limit ini akan ditolak.")


async def cmd_setcooling(update, context):
    """/setcooling [nama_amplop] [jumlah] — set cooling threshold, 0 to remove"""
    if not context.args or len(context.args) < 2:
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            hid = await get_household_id(user, db)
            envs = await _list_envelopes_names(hid, user.id, db)
        if not envs:
            await update.message.reply_text("Belum ada amplop.")
            return
        lines = ["Format: /setcooling [nama] [jumlah]\n"]
        for e in envs:
            emoji = e.emoji or "📁"
            cool = f"⏳ >= {format_currency(e.cooling_threshold)}" if e.cooling_threshold else "Tidak ada"
            lines.append(f"{emoji} {e.name} — {cool}")
        lines.append("\nContoh: /setcooling Makan 500k\nHapus: /setcooling Makan 0")
        await update.message.reply_text("\n".join(lines))
        return

    from app.bot.handlers import parse_amount
    amount_text = context.args[-1]
    name = " ".join(context.args[:-1]).strip("'\"")

    parsed = parse_amount(amount_text + " placeholder")
    if not parsed:
        await update.message.reply_text(
            "Format: /setcooling [nama amplop] [jumlah]\n"
            "Contoh: /setcooling makan 500k\n"
            "        /setcooling Rumah dan isinya 1jt"
        )
        return

    threshold = parsed[0]
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envelope = await _get_envelope_by_name(name, hid, user.id, db)

        if not envelope:
            envs = await _list_envelopes_names(hid, user.id, db)
            names = ", ".join([f"{e.emoji or '📁'} {e.name}" for e in envs])
            await update.message.reply_text(f"Amplop '{name}' nggak ditemukan.\n\nAmplop kamu: {names}")
            return

        emoji = envelope.emoji or "📁"
        if threshold <= 0:
            envelope.cooling_threshold = None
            await db.commit()
            await update.message.reply_text(f"✅ Cooling period {emoji} {envelope.name} dihapus.")
        else:
            envelope.cooling_threshold = threshold
            await db.commit()
            await update.message.reply_text(
                f"✅ Cooling period {emoji} {envelope.name}: {format_currency(threshold)}\n\n"
                f"Pembelian >= {format_currency(threshold)} harus tunggu 24 jam.")


async def cmd_controls(update, context):
    """/controls — show all behavior controls status"""
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await get_household_id(user, db)
        envs = await _list_envelopes_names(hid, user.id, db)

    if not envs:
        await update.message.reply_text(
            "Belum ada amplop. Setup dulu di /webapp atau ketik /template."
        )
        return

    active, inactive = [], []
    for env in envs:
        controls = []
        if env.is_locked:
            controls.append("🔒 Terkunci")
        if env.daily_limit:
            controls.append(f"📊 Limit {format_currency(env.daily_limit)}/hari")
        if env.cooling_threshold:
            controls.append(f"⏳ Cooling ≥ {format_currency(env.cooling_threshold)}")
        if controls:
            active.append((env, controls))
        else:
            inactive.append(env)

    lines = ["⚙️ <b>Behavior Controls</b>"]

    if active:
        lines.append("")
        for env, controls in active:
            em = env.emoji or "📁"
            lines.append(f"🟠 {em} <b>{env.name}</b>")
            for c in controls:
                lines.append(f"   {c}")
    else:
        lines.append("\nBelum ada kontrol aktif di amplop manapun.")

    if inactive:
        lines.append("\n─────────────────")
        for env in inactive:
            em = env.emoji or "📁"
            lines.append(f"⚪ {em} {env.name}")

    lines.append("\n─────────────────")
    lines.append(
        "/setlimit [nama] [jumlah] — atur limit harian\n"
        "/setcooling [nama] [jumlah] — atur cooling period\n"
        "/lock [nama] — kunci / buka amplop"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def handle_lock_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 1)
    if len(parts) < 2:
        await query.edit_message_text("Error.")
        return
    envelope_id = parts[1]
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Envelope).where(Envelope.id == envelope_id))
        envelope = result.scalar_one_or_none()
        if not envelope:
            await query.edit_message_text("Amplop nggak ditemukan.")
            return
        envelope.is_locked = not envelope.is_locked
        await db.commit()
        emoji = envelope.emoji or "📁"
        if envelope.is_locked:
            await query.edit_message_text(f"🔒 {emoji} {envelope.name} dikunci.\nTidak bisa belanja sampai di-unlock.")
        else:
            await query.edit_message_text(f"🔓 {emoji} {envelope.name} di-unlock.\nBisa belanja lagi.")
