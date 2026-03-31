import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from app.core.config import get_settings

settings = get_settings()
API = settings.API_URL


async def cmd_link(update, context):
    tg_user = update.effective_user
    tg_id = str(tg_user.id)

    if context.args and len(context.args) == 1:
        code = context.args[0].strip()
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{API}/auth/link/telegram",
                json={"code": code, "telegram_id": tg_id},
            )
        data = res.json()

        if res.status_code == 200:
            if data.get("status") == "conflict":
                # Show merge options
                conflict = data["conflict"]
                src = conflict["source"]
                tgt = conflict["target"]

                text = (
                    f"⚠️ Akun Telegram kamu sudah punya data:\n\n"
                    f"📱 Akun Telegram: {src['name']}\n"
                    f"   🏠 {src['household_name']} ({src['envelopes']} amplop, {src['transactions']} transaksi)\n\n"
                    f"🌐 Akun WebApp: {tgt['name']}\n"
                    f"   🏠 {tgt['household_name']} ({tgt['envelopes']} amplop)\n\n"
                    f"Data akan di-merge. Pilih household mana yang mau dipakai:"
                )

                keyboard = []
                if src.get("household_id"):
                    keyboard.append([InlineKeyboardButton(
                        f"🏠 {src['household_name']} (dari Telegram)",
                        callback_data=f"merge_{code}_{src['household_id']}"
                    )])
                if tgt.get("household_id"):
                    keyboard.append([InlineKeyboardButton(
                        f"🏠 {tgt['household_name']} (dari WebApp)",
                        callback_data=f"merge_{code}_{tgt['household_id']}"
                    )])
                keyboard.append([InlineKeyboardButton("❌ Batalkan", callback_data="merge_cancel")])

                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(
                    f"✅ Berhasil! Akun Telegram terhubung dengan {data.get('user_name', '')}.\n\n"
                    f"Data Telegram dan WebApp sekarang sync otomatis."
                )
        else:
            detail = data.get("detail", "Gagal menghubungkan")
            await update.message.reply_text(f"❌ {detail}")
    else:
        # Check if this Telegram ID is already linked to a WebApp account
        from app.core.database import AsyncSessionLocal
        from app.models.models import User
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.telegram_id == tg_id))
            linked_user = result.scalar_one_or_none()

        if linked_user:
            await update.message.reply_text(
                f"✅ <b>Telegram sudah terhubung ke WebApp!</b>\n\n"
                f"Akun: <b>{linked_user.name or linked_user.email}</b>\n\n"
                f"Tidak perlu link ulang. Kamu bisa langsung:\n"
                f"• Catat pengeluaran via chat\n"
                f"• /status — cek budget\n"
                f"• /webapp — buka dashboard\n\n"
                f"Mau putus koneksi? Ketik /unlink.",
                parse_mode="HTML",
            )
            return

        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{API}/auth/link/generate-for-telegram",
                json={"telegram_id": tg_id},
            )
        if res.status_code == 200:
            code = res.json()["code"]
            await update.message.reply_text(
                f"🔗 Kode link: <b>{code}</b>\n\n"
                f"Buka {settings.APP_URL}/login → klik 'Punya akun Telegram?' → masukkan kode.\n\n"
                f"Berlaku 5 menit.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("❌ Gagal generate kode. Coba lagi.")


async def handle_merge_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "merge_cancel":
        await query.edit_message_text("❌ Link dibatalkan.")
        return

    # Parse: merge_{code}_{household_id}
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("Error: data tidak valid.")
        return

    code = parts[1]
    household_id = parts[2]

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{API}/auth/link/merge",
            json={"code": code, "keep_household_id": household_id},
        )

    if res.status_code == 200:
        await query.edit_message_text(
            "✅ Akun berhasil di-merge!\n\n"
            "Semua data (amplop, transaksi) sudah digabungkan.\n"
            "Telegram dan WebApp sekarang sync."
        )
    else:
        detail = res.json().get("detail", "Gagal merge")
        await query.edit_message_text(f"❌ {detail}")


async def cmd_unlink(update, context):
    keyboard = [
        [InlineKeyboardButton("Ya, unlink Telegram", callback_data="unlink_confirm")],
        [InlineKeyboardButton("Batalkan", callback_data="unlink_cancel")],
    ]
    await update.message.reply_text(
        "⚠️ Yakin mau unlink akun Telegram?\n\n"
        "Data kamu tetap aman di akun WebApp. "
        "Tapi kamu nggak bisa catat lewat Telegram sampai link ulang.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_unlink_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "unlink_cancel":
        await query.edit_message_text("👍 Unlink dibatalkan.")
        return

    tg_id = str(query.from_user.id)
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{API}/auth/link/unlink-bot?telegram_id={tg_id}")

    if res.status_code == 200:
        await query.edit_message_text(
            "✅ Telegram berhasil di-unlink.\n\n"
            "Ketik /start kapan saja untuk mulai lagi, "
            "atau /link KODE untuk link ke akun WebApp."
        )
    else:
        detail = res.json().get("detail", "Gagal unlink")
        await query.edit_message_text(f"❌ {detail}")
