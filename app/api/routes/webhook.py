import hmac
import logging
from fastapi import APIRouter, Request, Response
from telegram import Update
from app.bot.handlers import create_bot_app
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("jatahku.webhook")
router = APIRouter()


def _verify_admin(request: Request) -> bool:
    """Check X-Admin-Secret header against ADMIN_SECRET setting."""
    if not settings.ADMIN_SECRET:
        return False
    secret = request.headers.get("X-Admin-Secret", "")
    return hmac.compare_digest(secret, settings.ADMIN_SECRET)

_bot_app = None

def get_bot_app():
    global _bot_app
    if _bot_app is None:
        _bot_app = create_bot_app()
    return _bot_app

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    # Validate Telegram webhook secret token when configured
    if settings.TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, settings.TELEGRAM_WEBHOOK_SECRET):
            return Response(status_code=403)
    try:
        bot_app = get_bot_app()
        if not bot_app.running:
            await bot_app.initialize()
        data = await request.json()
        update = Update.de_json(data=data, bot=bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return Response(status_code=200)

@router.get("/webhook/telegram/setup")
async def setup_webhook(request: Request):
    if not _verify_admin(request):
        return Response(status_code=403)
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not configured"}
    bot_app = get_bot_app()
    if not bot_app.running:
        await bot_app.initialize()
    kwargs = {"url": settings.TELEGRAM_WEBHOOK_URL}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        kwargs["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET
    await bot_app.bot.set_webhook(**kwargs)
    info = await bot_app.bot.get_webhook_info()
    return {"status": "ok", "webhook_url": info.url, "pending_updates": info.pending_update_count}

@router.get("/webhook/telegram/info")
async def webhook_info(request: Request):
    if not _verify_admin(request):
        return Response(status_code=403)
    bot_app = get_bot_app()
    if not bot_app.running:
        await bot_app.initialize()
    info = await bot_app.bot.get_webhook_info()
    return {"url": info.url, "pending_updates": info.pending_update_count, "last_error_date": str(info.last_error_date) if info.last_error_date else None, "last_error_message": info.last_error_message}


@router.get("/webhook/telegram/set-commands")
async def set_bot_commands(request: Request):
    if not _verify_admin(request):
        return Response(status_code=403)
    from telegram import BotCommand
    bot_app = get_bot_app()
    if not bot_app.running:
        await bot_app.initialize()
    commands = [
        BotCommand("status", "Ringkasan budget bulan ini"),
        BotCommand("amplop", "Daftar semua amplop"),
        BotCommand("pending", "Transaksi menunggu konfirmasi"),
        BotCommand("langganan", "Daftar langganan aktif"),
        BotCommand("controls", "Status behavior controls"),
        BotCommand("amplop_baru", "Buat amplop baru"),
        BotCommand("template", "Buat amplop dari template"),
        BotCommand("lock", "Kunci/buka amplop"),
        BotCommand("setlimit", "Set limit harian amplop"),
        BotCommand("setcooling", "Set cooling period"),
        BotCommand("tambah_langganan", "Tambah langganan baru"),
        BotCommand("hapus_langganan", "Hapus langganan"),
        BotCommand("invite", "Undang anggota household"),
        BotCommand("join", "Gabung ke household"),
        BotCommand("webapp", "Login ke WebApp tanpa password"),
        BotCommand("link", "Hubungkan ke WebApp"),
        BotCommand("unlink", "Putuskan koneksi Telegram"),
        BotCommand("batal", "Undo transaksi terakhir"),
        BotCommand("help", "Panduan lengkap"),
    ]
    await bot_app.bot.set_my_commands(commands)
    return {"status": "ok", "commands": len(commands)}
