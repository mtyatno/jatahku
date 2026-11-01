"""Jawaban bot dari AI Advisor v2 (S9, S17) — Telegram dan chat web memakai handler yang sama.

Handler lama (`nlp_cmd`, `handlers.cmd_status`, `checkin_cmd`) memanggil `jawab(...)` setelah
cek setup. Bila user ada di flag `advisor_v2_users`, balasan disusun `services/advisor/chat.py`
(metrics + render, angka sama dengan Beranda) dan fungsi ini mengembalikan True. Di luar flag,
atau bila mesin gagal, mengembalikan False dan handler memakai jawaban lama — jadi bot tidak
pernah diam karena advisor. Jawaban lama dihapus setelah flag `*` (S10).

S17: intent "tagihan bulan ini" dan "target {nama}" (tanpa jawaban lama: di luar flag bot
mengarahkan ke /langganan atau halaman Amplop), dan tombol "ganti amplop" SIM-01
(`sim:{jumlah}:{amplop_id}`, tanpa Redis: callback_data hanya datang dari tombol yang dikirim bot,
dan amplop yang bukan milik viewer jatuh ke tebakan karena `chat.amplop_simulasi` hanya
menerima amplop terlihat).
"""
import logging
from decimal import Decimal, InvalidOperation

from app.services.advisor import chat, render

logger = logging.getLogger("jatahku.bot.advisor")

SIM_PREFIX = "sim:"

INTENT = {
    "status": lambda a, **kw: chat.jawab_status(a),
    "sisa": lambda a, **kw: chat.jawab_sisa(a),
    "limit_harian": lambda a, **kw: chat.jawab_limit_harian(a),
    "proyeksi": lambda a, **kw: chat.jawab_proyeksi(a),
    "hari_ini": lambda a, **kw: chat.jawab_hari_ini(a),
    "kenapa": lambda a, teks="", **kw: chat.jawab_kenapa(a, teks),
    "aman_beli": lambda a, amplop_id=None, jumlah=0, **kw: chat.jawab_aman_beli(a, amplop_id, jumlah),
    "tagihan": lambda a, **kw: chat.jawab_tagihan(a),
    "target": lambda a, teks="", **kw: chat.jawab_target(a, teks),
}


async def analisa(user):
    """Analisa v2 untuk `user`, atau None (di luar flag / belum ada amplop / gagal)."""
    from app.core.database import AsyncSessionLocal
    from app.services.ruang import ruang_keluarga
    try:
        async with AsyncSessionLocal() as db:
            return await chat.muat(user, db, household_id=await ruang_keluarga(user, db))  # ADR-P2
    except Exception:
        logger.exception("advisor chat: gagal memuat analisa user=%s", getattr(user, "id", None))
        return None


def tombol_ganti_amplop(a, jumlah, eid: str | None):
    """Tombol "ganti amplop" SIM-01: amplop belanja lain (urut porsi 7 hari), atau None."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    pilihan = chat.pilihan_amplop(a, kecuali=eid)
    if not pilihan:
        return None
    n = int(Decimal(str(jumlah)))
    tombol = [InlineKeyboardButton(render.label_tombol_amplop(a.ctx, pid), callback_data=f"{SIM_PREFIX}{n}:{pid}")
              for pid, _ in pilihan]
    return InlineKeyboardMarkup([tombol[i:i + 2] for i in range(0, len(tombol), 2)])


def _markup(a, intent: str, kw: dict):
    if intent != "aman_beli":
        return None
    eid, ditebak = chat.amplop_simulasi(a, kw.get("amplop_id"))
    return tombol_ganti_amplop(a, kw.get("jumlah", 0), eid) if ditebak and eid else None


async def jawab(update, user, intent: str, tambahan: list[str] | None = None, **kw) -> bool:
    """Balas `update` dengan jawaban v2 untuk `intent`. False → pakai jawaban lama."""
    a = await analisa(user)
    if a is None:
        return False
    try:
        teks = INTENT[intent](a, **kw)
        markup = _markup(a, intent, kw) if teks else None
    except Exception:
        logger.exception("advisor chat: gagal menyusun %s user=%s", intent, getattr(user, "id", None))
        return False
    if not teks:
        return False
    if tambahan:
        teks = "\n".join([teks, *tambahan])
    await update.message.reply_text(teks, parse_mode="HTML", reply_markup=markup)
    return True


def parse_sim(data: str) -> tuple[Decimal, str] | None:
    """`sim:{jumlah}:{amplop_id}` → (jumlah, amplop_id), atau None bila rusak."""
    if not data.startswith(SIM_PREFIX):
        return None
    jumlah, _, eid = data[len(SIM_PREFIX):].partition(":")
    try:
        n = Decimal(jumlah)
    except InvalidOperation:
        return None
    if n <= 0 or not eid:
        return None
    return n, eid


async def handle_sim_callback(update, context):
    """Tombol "ganti amplop" SIM-01: simulasi ulang di amplop pilihan, tombol amplop lain tetap ada."""
    from app.bot.channel import find_chat_user
    from app.core.database import AsyncSessionLocal
    query = update.callback_query
    await query.answer()
    parsed = parse_sim(query.data or "")
    if parsed is None:
        return
    jumlah, eid = parsed
    async with AsyncSessionLocal() as db:
        user = await find_chat_user(str(query.from_user.id), db)
    if not user:
        await query.edit_message_text("⚠️ User tidak ditemukan.")
        return
    a = await analisa(user)
    if a is None:
        await query.edit_message_text("⚠️ Simulasi belum tersedia. Coba kirim ulang pertanyaannya.")
        return
    try:
        teks = chat.jawab_aman_beli(a, eid, jumlah)
        dipakai, _ = chat.amplop_simulasi(a, eid)
        markup = tombol_ganti_amplop(a, jumlah, dipakai)
    except Exception:
        logger.exception("advisor chat: gagal simulasi ganti amplop user=%s", getattr(user, "id", None))
        teks, markup = None, None
    if not teks:
        await query.edit_message_text("⚠️ Simulasi belum tersedia. Coba kirim ulang pertanyaannya.")
        return
    await query.edit_message_text(teks, parse_mode="HTML", reply_markup=markup)
