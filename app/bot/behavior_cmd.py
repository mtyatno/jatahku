from decimal import Decimal
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.models import Envelope, HouseholdMember
from app.bot.handlers import get_or_create_user, get_household_id, format_currency


async def _get_envelope_by_name(name, hid, user_id, db):
    from sqlalchemy import or_
    result = await db.execute(
        select(Envelope).where(
            Envelope.household_id == hid,
            Envelope.is_active == True,
            or_(Envelope.owner_id == None, Envelope.owner_id == user_id),
            func.lower(Envelope.name) == name.lower(),
        )
    )
    return result.scalar_one_or_none()


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
        await update.message.reply_text(
            "Format: /lock [nama amplop]\n\n"
            "Contoh:\n• /lock Makan\n• /lock Hiburan\n\n"
            "Kirim lagi untuk unlock.")
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
        await update.message.reply_text(
            "Format: /setlimit [nama amplop] [jumlah]\n\n"
            "Contoh:\n• /setlimit Makan 200k\n• /setlimit Hiburan 100rb\n• /setlimit Makan 0  (hapus limit)")
        return

    name = context.args[0]
    amount_text = " ".join(context.args[1:])

    from app.bot.handlers import parse_amount
    parsed = parse_amount(amount_text + " placeholder")
    if not parsed:
        await update.message.reply_text(f"Nggak bisa baca '{amount_text}'. Contoh: 200k, 100rb, 500000")
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
            await update.message.reply_text(f"Amplop '{name}' nggak ditemukan.\n\nAmplop kamu: {names}")
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
        await update.message.reply_text(
            "Format: /setcooling [nama amplop] [jumlah]\n\n"
            "Contoh:\n• /setcooling Makan 500k\n• /setcooling Hiburan 200rb\n• /setcooling Makan 0  (hapus cooling)")
        return

    name = context.args[0]
    amount_text = " ".join(context.args[1:])

    from app.bot.handlers import parse_amount
    parsed = parse_amount(amount_text + " placeholder")
    if not parsed:
        await update.message.reply_text(f"Nggak bisa baca '{amount_text}'. Contoh: 500k, 200rb, 1jt")
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
        await update.message.reply_text("Belum ada amplop.")
        return

    lines = ["⚙️ Behavior controls:\n"]
    for env in envs:
        emoji = env.emoji or "📁"
        controls = []
        if env.is_locked:
            controls.append("🔒 Locked")
        if env.daily_limit:
            controls.append(f"📊 Limit {format_currency(env.daily_limit)}/hari")
        if env.cooling_threshold:
            controls.append(f"⏳ Cooling >= {format_currency(env.cooling_threshold)}")

        status = " · ".join(controls) if controls else "Tidak ada"
        lines.append(f"{emoji} {env.name}\n   {status}")

    lines.append(f"\nKelola:\n/lock [nama] — kunci/buka\n/setlimit [nama] [jumlah]\n/setcooling [nama] [jumlah]")
    await update.message.reply_text("\n".join(lines))
