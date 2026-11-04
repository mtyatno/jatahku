"""Perintah bot Fitur Tambahan (Plugin H2, titik `bot_commands`; ADR-P2, P3).

Didaftarkan sekali saat start lewat `handlers.bot_commands()` (Telegram dan chat web memakai daftar yang sama).
Saat dipanggil, `app/plugins/host/titik.perintah` memeriksa plugin aktif dan peran user per ruang; jawabannya
teks polos berawalan nama ruang. Perintah plugin hanya membaca: tidak ada transaksi lewat chat (ADR-P2).
"""
from app.bot.channel import find_chat_user
from app.core.database import AsyncSessionLocal


def handler_perintah(plugin_id: str, command: str):
    async def jalankan(update, context):
        from app.plugins.host import titik
        tg_user = update.effective_user
        async with AsyncSessionLocal() as db:
            user = await find_chat_user(str(tg_user.id), db)
            if user is None:
                await update.message.reply_text("Ketik /start dulu.")
                return
            pesan = await titik.perintah(db, user, plugin_id, command)
        for teks in pesan:
            await update.message.reply_text(teks)     # tanpa parse_mode: teks plugin tidak ditafsirkan sebagai HTML
    jalankan.__name__ = f"plugin_{plugin_id}_{command}"
    return jalankan


def perintah_plugin() -> dict:
    """Perintah /nama → handler untuk setiap perintah plugin yang punya fungsi (registry saat ini)."""
    from app.plugins.host import titik
    return {nama: handler_perintah(pid, cmd) for nama, (pid, cmd) in titik.perintah_plugin().items()}
