from decimal import Decimal
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, or_
from app.core.database import AsyncSessionLocal
from app.models.models import Envelope, RecurringTransaction, RecurringFrequency
from app.bot.handlers import get_or_create_user, ruang_keluarga, format_currency, parse_amount
from app.bot.channel import txn_source
from app.services.recurring_status import payment_window_error


def _visible_to(user_id):
    """Amplop shared (owner_id NULL) atau milik user sendiri — kontrak
    visibilitas household yang sama dengan API web."""
    return or_(Envelope.owner_id == None, Envelope.owner_id == user_id)


async def _visible_rec(query, db):
    """(user, langganan) dari tombol, hanya bila langganan itu ada di household
    user dan amplopnya terlihat olehnya. Selain itu (None, None)."""
    import uuid
    try:
        rec_id = uuid.UUID(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        return None, None
    tg_user = query.from_user
    user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
    hid = await ruang_keluarga(user, db)
    result = await db.execute(
        select(RecurringTransaction)
        .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
        .where(RecurringTransaction.id == rec_id, Envelope.household_id == hid, _visible_to(user.id))
    )
    return user, result.scalar_one_or_none()


async def cmd_langganan(update, context):
    """/langganan — list all recurring transactions"""
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await ruang_keluarga(user, db)
        if not hid:
            await update.message.reply_text("Ketik /start dulu.")
            return

        result = await db.execute(
            select(RecurringTransaction, Envelope.name, Envelope.emoji)
            .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
            .where(Envelope.household_id == hid, RecurringTransaction.is_active == True,
                   _visible_to(user.id))
            .order_by(RecurringTransaction.next_run)
        )
        rows = result.all()

    if not rows:
        await update.message.reply_text(
            "Belum ada langganan.\n\n"
            "Tambah dengan:\n"
            "/tambah_langganan [nama] [jumlah] [amplop]\n\n"
            "Contoh:\n"
            "• /tambah_langganan Netflix 54k Hiburan\n"
            "• /tambah_langganan Spotify 55k Hiburan\n"
            "• /tambah_langganan Internet 350k Tagihan"
        )
        return

    freq_label = {"weekly": "Mingguan", "monthly": "Bulanan", "yearly": "Tahunan"}
    lines = ["🔄 Langganan aktif:\n"]
    total = Decimal("0")
    for rec, env_name, env_emoji in rows:
        emoji = env_emoji or "📁"
        freq = freq_label.get(rec.frequency.value, rec.frequency.value)
        lines.append(
            f"{emoji} {rec.description}\n"
            f"   {format_currency(rec.amount)} · {freq} · Next: {rec.next_run.strftime('%d %b')}"
        )
        if rec.frequency == RecurringFrequency.monthly:
            total += rec.amount
        elif rec.frequency == RecurringFrequency.weekly:
            total += rec.amount * 4
        elif rec.frequency == RecurringFrequency.yearly:
            total += rec.amount / 12

    lines.append(f"\n💰 Estimasi bulanan: {format_currency(total)}")
    lines.append(f"\nKelola: /tambah_langganan atau /hapus_langganan")
    await update.message.reply_text("\n".join(lines))


async def cmd_tambah_langganan(update, context):
    """/tambah_langganan [nama] [jumlah] [amplop]"""
    if not context.args or len(context.args) < 3:
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
            hid = await ruang_keluarga(user, db)
            env_result = await db.execute(
                select(Envelope).where(
                    Envelope.household_id == hid, Envelope.is_active == True,
                    or_(Envelope.owner_id == None, Envelope.owner_id == user.id),
                ).order_by(Envelope.created_at)
            )
            envs = env_result.scalars().all()
        names = ", ".join([f"{e.emoji or '📁'} {e.name}" for e in envs])
        await update.message.reply_text(
            "Format: /tambah_langganan [nama] [jumlah] [amplop]\n\n"
            "Contoh:\n"
            "• /tambah_langganan Netflix 54k Hiburan\n"
            "• /tambah_langganan Spotify 55k Jajanku\n"
            "• /tambah_langganan Internet 350k Tagihan\n\n"
            f"Amplop: {names}"
        )
        return

    desc = context.args[0]
    amount_text = context.args[1]
    env_name = " ".join(context.args[2:])

    parsed = parse_amount(amount_text + " placeholder")
    if not parsed:
        await update.message.reply_text(f"Nggak bisa baca jumlah '{amount_text}'.")
        return
    amount = parsed[0]

    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await ruang_keluarga(user, db)

        from sqlalchemy import func as sqlfunc
        env_result = await db.execute(
            select(Envelope).where(
                Envelope.household_id == hid, Envelope.is_active == True,
                sqlfunc.lower(Envelope.name) == env_name.lower(),
                _visible_to(user.id),
            ).order_by(Envelope.created_at)
        )
        envelope = env_result.scalars().first()
        if not envelope:
            await update.message.reply_text(f"Amplop '{env_name}' nggak ditemukan.")
            return

        # Next run = same day next month
        now = date.today()
        if now.month == 12:
            next_run = date(now.year + 1, 1, min(now.day, 28))
        else:
            next_run = date(now.year, now.month + 1, min(now.day, 28))

        rec = RecurringTransaction(
            envelope_id=envelope.id,
            amount=amount,
            description=desc,
            frequency=RecurringFrequency.monthly,
            next_run=next_run,
            is_active=True,
        )
        db.add(rec)
        await db.commit()

    emoji = envelope.emoji or "📁"
    await update.message.reply_text(
        f"✅ Langganan ditambahkan!\n\n"
        f"🔄 {desc} — {format_currency(amount)}/bulan\n"
        f"Amplop: {emoji} {envelope.name}\n"
        f"Reminder dikirim saat jatuh tempo\n"
        f"Jatuh tempo berikut: {next_run.strftime('%d %b %Y')}"
    )


async def cmd_hapus_langganan(update, context):
    """/hapus_langganan — show list to delete"""
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        hid = await ruang_keluarga(user, db)

        result = await db.execute(
            select(RecurringTransaction, Envelope.emoji)
            .join(Envelope, RecurringTransaction.envelope_id == Envelope.id)
            .where(Envelope.household_id == hid, RecurringTransaction.is_active == True,
                   _visible_to(user.id))
        )
        rows = result.all()

    if not rows:
        await update.message.reply_text("Belum ada langganan.")
        return

    keyboard = []
    for rec, emoji in rows:
        e = emoji or "📁"
        keyboard.append([InlineKeyboardButton(
            f"❌ {e} {rec.description} ({format_currency(rec.amount)})",
            callback_data=f"delrec_{rec.id}"
        )])
    keyboard.append([InlineKeyboardButton("Batal", callback_data="delrec_cancel")])

    await update.message.reply_text(
        "Pilih langganan yang mau dihapus:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_delrec_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "delrec_cancel":
        await query.edit_message_text("👍 Dibatalkan.")
        return

    async with AsyncSessionLocal() as db:
        _, rec = await _visible_rec(query, db)
        if not rec:
            await query.edit_message_text("Tidak ditemukan.")
            return
        desc = rec.description
        rec.is_active = False
        await db.commit()

    await query.edit_message_text(f"✅ Langganan '{desc}' dihapus.")



async def handle_recpay_callback(update, context):
    """User confirms payment — record transaction + advance next_run."""
    query = update.callback_query
    await query.answer()

    from app.models.models import Transaction, TransactionSource
    async with AsyncSessionLocal() as db:
        user, rec = await _visible_rec(query, db)
        if not rec:
            await query.edit_message_text("Langganan tidak ditemukan.")
            return
        # Aturan sama dengan web: hanya jatuh tempo di periode aktif (juga mencegah tombol lama ditekan dua kali).
        err = payment_window_error(rec.next_run, user.payday_day, date.today())
        if err:
            await query.edit_message_text(f"⏳ {rec.description}: {err}")
            return

        env_result = await db.execute(
            select(Envelope).where(Envelope.id == rec.envelope_id)
        )
        envelope = env_result.scalar_one_or_none()

        # Record transaction
        txn = Transaction(
            envelope_id=rec.envelope_id,
            user_id=user.id,
            amount=rec.amount,
            description=f"🔄 {rec.description}",
            source=txn_source(),
            transaction_date=date.today(),
        )
        db.add(txn)

        # Advance next_run
        from app.services.recurring_processor import _next_date
        rec.next_run = _next_date(rec.next_run, rec.frequency)
        await db.commit()

    emoji = envelope.emoji or "📁" if envelope else "📁"
    await query.edit_message_text(
        f"✅ Pembayaran tercatat!\n\n"
        f"🔄 {rec.description} — {format_currency(rec.amount)}\n"
        f"Amplop: {emoji} {envelope.name if envelope else '-'}\n"
        f"Jatuh tempo berikut: {rec.next_run.strftime('%d %b %Y')}"
    )


async def handle_recskip_callback(update, context):
    """Skip this month — advance next_run without recording."""
    query = update.callback_query
    await query.answer()

    async with AsyncSessionLocal() as db:
        user, rec = await _visible_rec(query, db)
        if not rec:
            await query.edit_message_text("Langganan tidak ditemukan.")
            return
        err = payment_window_error(rec.next_run, user.payday_day, date.today())
        if err:
            await query.edit_message_text(f"⏳ {rec.description}: {err}")
            return

        from app.services.recurring_processor import _next_date
        rec.next_run = _next_date(rec.next_run, rec.frequency)
        await db.commit()

    await query.edit_message_text(
        f"⏭️ {rec.description} di-skip bulan ini.\n"
        f"Reminder berikut: {rec.next_run.strftime('%d %b %Y')}"
    )


async def handle_recstop_callback(update, context):
    """Stop subscription entirely."""
    query = update.callback_query
    await query.answer()

    async with AsyncSessionLocal() as db:
        _, rec = await _visible_rec(query, db)
        if not rec:
            await query.edit_message_text("Langganan tidak ditemukan.")
            return

        desc = rec.description
        rec.is_active = False
        await db.commit()

    await query.edit_message_text(f"❌ Langganan '{desc}' dihentikan.")
