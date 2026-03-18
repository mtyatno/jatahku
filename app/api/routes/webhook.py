import logging
from fastapi import APIRouter, Request, Response
from telegram import Update
from app.bot.handlers import create_bot_app
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("jatahku.webhook")
router = APIRouter()

_bot_app = None

def get_bot_app():
    global _bot_app
    if _bot_app is None:
        _bot_app = create_bot_app()
    return _bot_app

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
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
async def setup_webhook():
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not configured"}
    bot_app = get_bot_app()
    if not bot_app.running:
        await bot_app.initialize()
    await bot_app.bot.set_webhook(url=settings.TELEGRAM_WEBHOOK_URL)
    info = await bot_app.bot.get_webhook_info()
    return {"status": "ok", "webhook_url": info.url, "pending_updates": info.pending_update_count}

@router.get("/webhook/telegram/info")
async def webhook_info():
    bot_app = get_bot_app()
    if not bot_app.running:
        await bot_app.initialize()
    info = await bot_app.bot.get_webhook_info()
    return {"url": info.url, "pending_updates": info.pending_update_count, "last_error_date": str(info.last_error_date) if info.last_error_date else None, "last_error_message": info.last_error_message}
