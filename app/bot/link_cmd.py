import httpx
from telegram import Update
from telegram.ext import ContextTypes
from app.core.config import get_settings

settings = get_settings()
API = settings.API_URL

async def cmd_link(update, context):
    tg_user = update.effective_user
    tg_id = str(tg_user.id)
    if context.args and len(context.args) == 1:
        code = context.args[0].strip()
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{API}/auth/link/telegram", json={"code": code, "telegram_id": tg_id})
        if res.status_code == 200:
            data = res.json()
            await update.message.reply_text(
                f"✅ Berhasil! Akun Telegram terhubung dengan {data.get('user_name', '')}.\n\n"
                f"Data Telegram dan WebApp sekarang sync otomatis.")
        else:
            detail = res.json().get("detail", "Gagal menghubungkan")
            await update.message.reply_text(f"❌ {detail}")
    else:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{API}/auth/link/generate-for-telegram", json={"telegram_id": tg_id})
        if res.status_code == 200:
            code = res.json()["code"]
            await update.message.reply_text(
                f"🔗 Kode link: *{code}*\n\n"
                f"Buka {settings.APP_URL}/login → klik 'Punya akun Telegram?' → masukkan kode.\n\n"
                f"Berlaku 5 menit.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Gagal generate kode. Coba lagi.")
