"""Bot: kirim foto struk → scan (RapidOCR) → pilih amplop → tersimpan.

Pemilihan amplop memakai callback `t_{key}_{idx}` yang sudah ada
(handle_txn_callback), dengan tambahan field opsional di Redis:
"date" (tanggal struk) dan "scan_id" (untuk feedback belajar).
"""
import json
import logging
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger("jatahku.bot")

MAX_BOT_PHOTO_BYTES = 8 * 1024 * 1024
BOT_SCAN_PER_HOUR = 20

CONF_TEXT = {
    "tinggi": "✅ cocok dengan pembayaran",
    "sedang": "⚠️ cek lagi nominalnya",
    "rendah": "⚠️ kurang yakin, mohon dicek",
}

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "hari ini"
    y, m, d = iso.split("-")
    return f"{int(d)} {BULAN[int(m) - 1]} {y}"


def _rp(n) -> str:
    return "Rp " + f"{int(n):,}".replace(",", ".")


MAX_ITEM_LINES = 12


def _items_summary(result: dict) -> str:
    """Rincian ringkas untuk pesan bot (teks biasa, tanpa Markdown)."""
    items = result.get("items") or []
    rec = result.get("reconciliation") or {}
    if not items:
        return ""
    n = len(items)
    if rec.get("status") == "cocok":
        head = f"Rincian {n} barang ✅ cocok dengan total"
    else:
        diff = rec.get("diff") or 0
        word = "kurang" if diff > 0 else "lebih"
        head = f"Rincian {n} barang ⚠️ {word} {_rp(abs(diff))} dari total"
    lines = [head]
    for it in items[:MAX_ITEM_LINES]:
        name = (it.get("name") or "Barang")[:28]
        row = f"• {name}  {_rp(it.get('amount') or 0)}"
        if it.get("discount"):
            row += f" (voucher −{_rp(it['discount'])})"
        if it.get("flag") == "cek":
            sug = it.get("suggestion")
            row += " ⚠️ " + ("terbaca dobel?" if sug == 0 else f"mungkin {_rp(sug)}?" if sug else "cek")
        lines.append(row)
    if n > MAX_ITEM_LINES:
        lines.append(f"… +{n - MAX_ITEM_LINES} barang lagi")
    for adj in result.get("adjustments") or []:
        sign = "−" if adj.get("kind") == "discount" else "+"
        lines.append(f"{(adj.get('label') or 'Penyesuaian')[:28]}  {sign}{_rp(adj.get('amount') or 0)}")
    if rec.get("status") != "cocok":
        lines.append("💡 Koreksi rincian & pecah per amplop bisa di webapp (tombol Struk).")
    return "\n".join(lines)


async def _rate_limited(tg_id) -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(get_settings().REDIS_URL)
        key = f"bot:scan:{tg_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 3600)
        await r.aclose()
        return n > BOT_SCAN_PER_HOUR
    except Exception:
        return False  # Redis mati → fail open (kuota bulanan tetap berlaku)


async def _download(message) -> tuple[bytes, str] | None:
    """Foto terbesar dari pesan foto, atau dokumen gambar (dikirim sebagai file)."""
    if message.photo:
        tg_file = await message.photo[-1].get_file()
        mime = "image/jpeg"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        if (message.document.file_size or 0) > MAX_BOT_PHOTO_BYTES:
            return None
        tg_file = await message.document.get_file()
        mime = message.document.mime_type
    else:
        return None
    data = bytes(await tg_file.download_as_bytearray())
    return data, mime


async def handle_receipt_photo(update, context):
    from app.bot.handlers import (
        get_or_create_user, get_household_id, get_envelopes_with_spent, _is_setup_complete,
    )
    from app.bot.tglogin_cmd import reply_setup_needed
    from app.services.receipt_ocr import OcrBusy, OcrFailed, OcrUnavailable
    from app.services.receipt_scan import ScanQuotaExceeded, scan_receipt
    from app.services.txn_nlp import find_best_envelope

    message = update.message
    tg_user = update.effective_user
    if await _rate_limited(tg_user.id):
        await message.reply_text("⏳ Terlalu banyak scan. Coba lagi sebentar.")
        return

    downloaded = await _download(message)
    if not downloaded:
        await message.reply_text("📄 Kirim struk sebagai foto (JPG/PNG), maksimal 8 MB.")
        return
    data, mime = downloaded

    status = await message.reply_text("🧾 Membaca struk...")
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        setup_ok, _ = await _is_setup_complete(user, db)
        if not setup_ok:
            await status.delete()
            await reply_setup_needed(update, user)
            return
        try:
            result = await scan_receipt(user, data, mime, db)
        except ScanQuotaExceeded as exc:
            await status.edit_text(
                f"📸 Kuota scan struk bulan ini ({exc.limit}x) sudah habis.\n"
                "Catat manual dulu, misalnya: `indomaret 45rb`\n\n"
                "Upgrade ke Pro di jatahku.com/settings untuk scan tanpa batas.",
                parse_mode="Markdown")
            return
        except OcrBusy:
            await status.edit_text("⏳ Scan struk sedang ramai. Kirim ulang fotonya sebentar lagi ya.")
            return
        except (OcrUnavailable, OcrFailed) as exc:
            logger.warning("scan struk gagal: %s", exc)
            await status.edit_text("😕 Scan struk sedang tidak bisa. Catat manual dulu, misalnya: `kopi 35rb`",
                                   parse_mode="Markdown")
            return

        total = result.get("total")
        merchant = result.get("merchant") or "Belanja"
        quota = result.get("quota") or {}
        quota_line = (f"\n📸 Sisa scan bulan ini: {quota['remaining']}/{quota['limit']}"
                      if quota.get("limit") is not None else "")

        if not total:
            # Tanpa parse_mode: nama toko dari OCR bisa mengandung karakter Markdown.
            await status.edit_text(
                "😕 Total struk tidak terbaca.\n\n"
                "Tips: foto tegak lurus, terang, tanpa bayangan. Atau ketik manual, misalnya:\n"
                f"{merchant.lower()} 45rb{quota_line}")
            return

        hid = await get_household_id(user, db)
        payday_day = getattr(user, "payday_day", 1) or 1
        envs = [e for e in await get_envelopes_with_spent(hid, db, user.id, payday_day=payday_day)
                if str(getattr(e["envelope"], "purpose", "expense")) not in ("saving", "sinking_fund")]
        if not envs:
            await status.edit_text("Belum ada amplop. Ketik /template untuk buat.")
            return
        suggested, confident = await find_best_envelope(merchant, hid, db, user_id=user.id)

    # Amplop yang disarankan di urutan teratas.
    if suggested and confident:
        envs.sort(key=lambda e: e["envelope"].id != suggested.id)

    txn_key = secrets.token_hex(4)
    payload = {
        "amount": int(total), "desc": merchant,
        "envs": {str(i): str(e["envelope"].id) for i, e in enumerate(envs)},
        "date": result.get("date"), "scan_id": result.get("scan_id"),
    }
    import redis.asyncio as aioredis
    r = aioredis.from_url(get_settings().REDIS_URL)
    await r.set(f"txn:{txn_key}", json.dumps(payload), ex=600)
    await r.aclose()

    keyboard = []
    for i, e in enumerate(envs):
        env = e["envelope"]
        star = "⭐ " if (suggested and confident and env.id == suggested.id) else ""
        keyboard.append([InlineKeyboardButton(f"{star}{env.emoji or '📁'} {env.name}", callback_data=f"t_{txn_key}_{i}")])
    keyboard.append([InlineKeyboardButton("✏️ Nominal salah", callback_data=f"struk_fix_{result['scan_id']}"),
                     InlineKeyboardButton("❌ Batal", callback_data=f"struk_no_{result['scan_id']}")])

    conf = CONF_TEXT.get(result.get("confidence"), "")
    summary = _items_summary(result)
    await status.edit_text(
        f"🧾 Struk {merchant} · {_fmt_date(result.get('date'))}\n"
        f"Total: {_rp(total)}  {conf}\n\n"
        + (f"{summary}\n\n" if summary else "")
        + f"Masuk ke amplop mana?{quota_line}",
        reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_struk_callback(update, context):
    """struk_no_{scan_id} = batal; struk_fix_{scan_id} = nominal salah → catat manual."""
    from app.bot.handlers import get_or_create_user
    from app.services.receipt_scan import apply_feedback

    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        return
    action, scan_id = parts[1], parts[2]
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(update.effective_user.id), update.effective_user.first_name, db)
        try:
            await apply_feedback(user, scan_id, db, saved=False, wrong=(action == "fix"))
        except Exception as exc:  # feedback best-effort
            logger.warning("feedback struk gagal: %s", exc)
    if action == "fix":
        await query.edit_message_text(
            "✏️ Oke, ketik manual nominal yang benar, misalnya:\n`indomaret 140500`\n\n"
            "Laporan ini membantu scan struk makin akurat 🙏", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Struk dibatalkan.")
