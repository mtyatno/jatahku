import re
from decimal import Decimal
from app.bot.handlers import (
    parse_amount, find_best_envelope, get_envelopes_with_spent,
    get_or_create_user, get_household_id, _is_setup_complete, format_currency,
)

# Trigger patterns: "aman gak", "cukup ga", "kalau beli", "masuk budget", etc.
WHATIF_RE = re.compile(
    r"(?:aman|cukup|bisa|sanggup)\s*(?:gak|ga|nggak|ngga|tidak|enggak|kan)\?*|"
    r"(?:kalo|kalau)\s+(?:gw|gue|saya|aku|w\b)?\s*beli|"
    r"masuk\s*budget|"
    r"boleh\s*beli",
    re.IGNORECASE,
)


def is_whatif(text: str) -> bool:
    return bool(WHATIF_RE.search(text))


async def handle_whatif(update, context):
    from app.core.database import AsyncSessionLocal

    text = update.message.text.strip()
    parsed = parse_amount(text)
    if not parsed:
        await update.message.reply_text(
            "Sebutkan jumlahnya juga ya.\n"
            "Contoh: _kalau beli kopi 15k aman gak?_",
            parse_mode="Markdown",
        )
        return

    amount, description = parsed
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        setup_ok, _ = await _is_setup_complete(user, db)
        if not setup_ok:
            await update.message.reply_text(
                "⚠️ Setup budget dulu di jatahku.com"
            )
            return

        hid = await get_household_id(user, db)
        envelope, confident = await find_best_envelope(description, hid, db)
        all_envs = await get_envelopes_with_spent(hid, db, user.id)

    if envelope:
        # Find this envelope's data
        env_data = next((e for e in all_envs if e["envelope"].id == envelope.id), None)
        if not env_data:
            await update.message.reply_text("Tidak bisa cek saldo amplop.")
            return

        free = env_data["free"]
        emoji = envelope.emoji or "📁"
        after = free - amount

        if free >= amount * 2:
            status = "✅ Aman!"
        elif free >= amount:
            status = "⚠️ Pas-pasan, tapi masih cukup."
        else:
            status = "❌ Tidak cukup."

        lines = [
            f"{status}",
            f"",
            f"{emoji} *{envelope.name}*",
            f"Saldo bebas : {format_currency(free)}",
            f"Harga       : {format_currency(amount)}",
            f"Sisa setelah: {format_currency(after) if after >= 0 else '❌ ' + format_currency(abs(after)) + ' kurang'}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    else:
        # Envelope not detected — show all envelopes so user can compare
        if not all_envs:
            await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
            return

        lines = [f"💬 *Cek budget untuk {format_currency(amount)}*\n"]
        for e in all_envs:
            env = e["envelope"]
            free = e["free"]
            emoji = env.emoji or "📁"
            if free >= amount * 2:
                marker = "✅"
            elif free >= amount:
                marker = "⚠️"
            else:
                marker = "❌"
            lines.append(f"{marker} {emoji} {env.name}: {format_currency(free)} bebas")

        lines.append("\n_Sebutkan nama amplop untuk cek lebih detail._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
