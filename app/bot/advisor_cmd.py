"""Jawaban bot dari AI Advisor v2 (S9) — Telegram dan chat web memakai handler yang sama.

Handler lama (`nlp_cmd`, `handlers.cmd_status`, `checkin_cmd`) memanggil `jawab(...)` setelah
cek setup. Bila user ada di flag `advisor_v2_users`, balasan disusun `services/advisor/chat.py`
(metrics + render, angka sama dengan Beranda) dan fungsi ini mengembalikan True. Di luar flag,
atau bila mesin gagal, mengembalikan False dan handler memakai jawaban lama — jadi bot tidak
pernah diam karena advisor. Jawaban lama dihapus setelah flag `*` (S10).
"""
import logging

from app.services.advisor import chat

logger = logging.getLogger("jatahku.bot.advisor")

INTENT = {
    "status": lambda a, **kw: chat.jawab_status(a),
    "sisa": lambda a, **kw: chat.jawab_sisa(a),
    "limit_harian": lambda a, **kw: chat.jawab_limit_harian(a),
    "proyeksi": lambda a, **kw: chat.jawab_proyeksi(a),
    "hari_ini": lambda a, **kw: chat.jawab_hari_ini(a),
    "kenapa": lambda a, teks="", **kw: chat.jawab_kenapa(a, teks),
    "aman_beli": lambda a, amplop_id=None, jumlah=0, **kw: chat.jawab_aman_beli(a, amplop_id, jumlah),
}


async def analisa(user):
    """Analisa v2 untuk `user`, atau None (di luar flag / belum ada amplop / gagal)."""
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            return await chat.muat(user, db)
    except Exception:
        logger.exception("advisor chat: gagal memuat analisa user=%s", getattr(user, "id", None))
        return None


async def jawab(update, user, intent: str, tambahan: list[str] | None = None, **kw) -> bool:
    """Balas `update` dengan jawaban v2 untuk `intent`. False → pakai jawaban lama."""
    a = await analisa(user)
    if a is None:
        return False
    try:
        teks = INTENT[intent](a, **kw)
    except Exception:
        logger.exception("advisor chat: gagal menyusun %s user=%s", intent, getattr(user, "id", None))
        return False
    if not teks:
        return False
    if tambahan:
        teks = "\n".join([teks, *tambahan])
    await update.message.reply_text(teks, parse_mode="HTML")
    return True
