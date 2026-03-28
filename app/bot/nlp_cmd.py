"""Natural language query handlers for the Telegram bot.

Handles: sisa/balance, daily limit, projection, comparison,
         casual status checks, emotional queries, corrections, multi-expense.
"""
import re
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import select, func

from app.bot.handlers import (
    parse_amount, find_best_envelope, get_envelopes_with_spent,
    get_or_create_user, get_household_id, _is_setup_complete, format_currency,
)

# ── Detection patterns ────────────────────────────────────────────────────────

SISA_RE = re.compile(
    # 1. Exact single/double-word triggers (common short queries)
    r"^(sisa|saldo|rekap|rekapan|cek|info|amplop|jatah|dompet|status|uangku|duitku"
    r"|sisa\s+uang|sisa\s+duit|cek\s+saldo|tinggal\s+berapa|sisa\s+jatah|cek\s+jatah"
    r"|info\s+saldo|rekap\s+amplop|sisa\s+berapa|duit\s+sisa|cek\s+duit|uang\s+sisa"
    r"|sisa\s+saldo|saldo\s+dong|cek\s+dompet|jatah\s+sisa|info\s+jatah|lihat\s+saldo"
    r"|saldo\s+sisa)$|"

    # 2. Core balance keywords — these alone trigger balance check
    r"\b(sisa|tersisa|saldo|rekap|rekapan|jatah|amplop|cuan|amunisi)\b|"

    # 3. "tinggal" in balance context
    r"\btinggal\s+(berapa|sisa|duit|uang|saldo|sedikit)\b|"
    r"\b(duit|uang|saldo|jatah)\s*(gue|gw|ku|aku|saya|w\b)?\s*tinggal\b|"

    # 4. "berapa" + money words
    r"\bberapa\s+(sisa|uang|duit|jatah|saldo|lagi|perak|cuan)\b|"
    r"\b(duit|uang|saldo)\s*(gue|gw|ku|aku|saya|w\b)?\s*berapa\b|"

    # 5. Action words + budget context
    r"\b(cek|lihat|liat|info|minta|report|tolong)\s+"
    r"(saldo|duit|uang|jatah|amplop|dompet|kantong|keuangan|posisi|sisa|cuan|rekap)\b|"

    # 6. "posisi/status" + money context
    r"\b(posisi|status)\s+(dompet|kantong|keuangan|duit|uang|amplop)\b|"

    # 7. Dompet / kantong (wallet slang — alone or with descriptors)
    r"\b(dompet|kantong)\b|"

    # 8. "masih ada/sisa/punya" + money
    r"\bmasih\s+(ada\s+)?(duit|uang|jatah|saldo)\b|"
    r"\bmasih\s+(sisa|punya\s+duit|ada\s+duit|bisa\s+jajan|kaya|nafas|tebel)\b|"
    r"\budah\s+miskin\b|"

    # 9. Slang states (sekarat/menipis/etc near wallet/money words)
    r"\b(duit|uang|dompet|kantong).{0,25}(sekarat|menipis|nafas|tebel)\b|"
    r"\b(sekarat|menipis|nafas|tebel).{0,25}(duit|uang|dompet|kantong)\b",

    re.IGNORECASE,
)

HARIAN_RE = re.compile(
    r"\bjatah\s+harian\b|"
    r"\blimit\s+harian\b|"
    r"\bper\s+hari\s+(berapa|bisa)\b|"
    r"\bberapa\s+per\s+hari\b|"
    r"\bmaksimal.{0,15}hari\s+ini\b|"
    r"\bhari\s+ini\s+maksimal\b|"
    r"\bbisa\s+keluar\s+berapa\b",
    re.IGNORECASE,
)

PROYEKSI_RE = re.compile(
    r"\b(cukup|aman|tahan)\s+(sampai|hingga)\s+(kapan|akhir)\b|"
    r"\bhabis\s+(tanggal|kapan)\b|"
    r"\bsampai\s+kapan\s+(cukup|aman|bertahan)\b|"
    r"\bkalau\s+begini\s+terus\b|"
    r"\bcukup\s+sampai\s+akhir\s+bulan\b",
    re.IGNORECASE,
)

COMPARISON_RE = re.compile(
    r"\blebih\s+(boros|hemat)\s*(dari\s+bulan\s+lalu|bulan\s+lalu)?\b|"
    r"\bbulan\s+lalu\s*(gimana|berapa|lebih|dibanding)?\b|"
    r"\bpengeluaran\s+terbesar\b|"
    r"\bterbesar\s+(apa|bulan\s+ini)\b",
    re.IGNORECASE,
)

SANTAI_RE = re.compile(
    # "boncos/bokek" — no money context needed, purely about status
    r"\b(boncos|bokek)\b|"
    # "parah/gawat" as a question about finances
    r"\b(parah|gawat)\s*(gak|nggak|banget|sih)\b|"
    # "aman gak?" without money/wallet word (those are caught by SISA_RE first)
    r"\b(aman|sehat)\s+(gak|nggak|kan|gak\s+sih|nih)\b",
    re.IGNORECASE,
)

EMOSI_RE = re.compile(
    r"\b(kenapa|kok)\s+.{0,25}(cepet\s+)?habis\b|"
    r"\bgak\s+(pernah\s+)?bisa\s+nabung\b|"
    r"\bsusah\s+(banget\s+)?nabung\b|"
    r"\bselalu\s+boncos\b",
    re.IGNORECASE,
)

KOREKSI_RE = re.compile(
    r"\b(tadi|barusan)\s*(salah|keliru|typo|ngaco)\b|"
    r"\bharusnya\s+\d|"
    r"\b(ganti|ubah|koreksi)\s+.{0,20}(tadi|terakhir)\b",
    re.IGNORECASE,
)

NABUNG_RE = re.compile(
    r"\bnabung\s+.{0,20}\b(dalam|selama|bulan|hari|minggu)\b|"
    r"\btarget\s+.{0,20}\b(dalam|bulan|hari)\b|"
    r"\bnyisih\s+berapa",
    re.IGNORECASE,
)


def is_sisa(text): return bool(SISA_RE.search(text))
def is_harian(text): return bool(HARIAN_RE.search(text))
def is_proyeksi(text): return bool(PROYEKSI_RE.search(text))
def is_comparison(text): return bool(COMPARISON_RE.search(text))
def is_santai(text): return bool(SANTAI_RE.search(text))
def is_emosi(text): return bool(EMOSI_RE.search(text))
def is_koreksi(text): return bool(KOREKSI_RE.search(text))
def is_nabung(text): return bool(NABUNG_RE.search(text))


def parse_multi_expense(text):
    """Parse comma/semicolon-separated expenses. Returns list of (amount, desc) or None."""
    parts = re.split(r"[,;]", text)
    if len(parts) < 2:
        return None
    results = []
    for part in parts:
        part = part.strip()
        if part:
            parsed = parse_amount(part)
            if parsed:
                results.append(parsed)
    return results if len(results) >= 2 else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_left_in_month():
    now = date.today()
    next_month = date(now.year + (1 if now.month == 12 else 0), (now.month % 12) + 1, 1)
    return (next_month - now).days


def _fmt_date(d):
    return f"{d.day} {d.strftime('%B')}"


async def _get_user_envelopes(tg_user, db):
    user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
    setup_ok, _ = await _is_setup_complete(user, db)
    if not setup_ok:
        return user, None, None
    hid = await get_household_id(user, db)
    envelopes = await get_envelopes_with_spent(hid, db, user.id)
    return user, hid, envelopes


# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_sisa(update, context):
    """Show remaining free balance per envelope."""
    from app.core.database import AsyncSessionLocal
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        user, hid, envelopes = await _get_user_envelopes(tg_user, db)

    if envelopes is None:
        await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
        return
    if not envelopes:
        await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
        return

    total_free = sum(e["free"] for e in envelopes)
    total_spent = sum(e["spent"] for e in envelopes)
    total_allocated = sum(e["allocated"] for e in envelopes)
    days_left = _days_left_in_month()
    now = date.today()

    lines = [f"💰 *Sisa budget {now.strftime('%B')}*\n"]
    lines.append(f"Bebas: *{format_currency(total_free)}* | Keluar: {format_currency(total_spent)} | Sisa {days_left}h\n")

    for e in envelopes:
        env = e["envelope"]
        free = e["free"]
        emoji = env.emoji or "📁"
        if free >= 0:
            lines.append(f"{emoji} {env.name}: {format_currency(free)}")
        else:
            lines.append(f"🔴 {env.name}: minus {format_currency(abs(free))}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_limit_harian(update, context):
    """Calculate safe daily spending limit."""
    from app.core.database import AsyncSessionLocal
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        _, _, envelopes = await _get_user_envelopes(tg_user, db)

    if envelopes is None:
        await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
        return

    total_free = sum(e["free"] for e in envelopes)
    days_left = _days_left_in_month()

    if total_free <= 0:
        await update.message.reply_text(
            f"😬 Budget kamu sudah habis atau minus.\n"
            f"Total bebas: {format_currency(total_free)}"
        )
        return

    daily = total_free / days_left

    lines = [
        f"📅 *Jatah harian — {days_left} hari tersisa*\n",
        f"Total bebas: {format_currency(total_free)}",
        f"💡 Per hari: *{format_currency(daily)}*\n",
        "Per amplop:",
    ]
    for e in envelopes:
        if e["free"] > 0:
            env = e["envelope"]
            emoji = env.emoji or "📁"
            lines.append(f"{emoji} {env.name}: {format_currency(e['free'] / days_left)}/hari")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_proyeksi(update, context):
    """Estimate when budget runs out based on current burn rate."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction
    tg_user = update.effective_user
    now = date.today()

    async with AsyncSessionLocal() as db:
        user, hid, envelopes = await _get_user_envelopes(tg_user, db)
        if envelopes is None:
            await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
            return

        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.is_deleted == False,
                Transaction.user_id == user.id,
                func.extract("year", Transaction.transaction_date) == now.year,
                func.extract("month", Transaction.transaction_date) == now.month,
            )
        )
        total_spent = Decimal(str(spent_result.scalar()))

    days_elapsed = now.day
    days_left = _days_left_in_month()
    total_free = sum(e["free"] for e in envelopes)
    total_allocated = sum(e["allocated"] for e in envelopes)

    if days_elapsed <= 1:
        await update.message.reply_text(
            f"💰 Budget: {format_currency(total_allocated)}\n"
            f"Masih hari pertama, belum ada data untuk proyeksi. Tanya lagi besok!"
        )
        return

    if total_spent == 0:
        await update.message.reply_text("Belum ada pengeluaran bulan ini untuk diproyeksi.")
        return

    daily_rate = total_spent / days_elapsed
    days_can_last = int(total_free / daily_rate) if daily_rate > 0 else 999
    projected_end = now + timedelta(days=days_can_last)
    projected_eom = total_spent + daily_rate * days_left
    ideal_daily = total_free / days_left

    if days_can_last >= days_left:
        tone = "✅ Budget aman sampai akhir bulan!"
        sisa_eom = total_allocated - projected_eom
        detail = f"Proyeksi sisa akhir bulan: {format_currency(max(sisa_eom, Decimal('0')))}"
    elif days_can_last >= days_left * Decimal("0.7"):
        tone = "⚠️ Budget mulai menipis di akhir bulan."
        detail = f"Perkiraan habis: {_fmt_date(projected_end)}"
    else:
        tone = f"🔴 Waspada! Perkiraan habis {_fmt_date(projected_end)} ({days_can_last} hari lagi)"
        detail = f"Di kecepatan ini kamu butuh {format_currency(projected_eom)} tapi budget {format_currency(total_allocated)}"

    lines = [
        f"{tone}\n",
        f"Rata-rata harian: {format_currency(daily_rate)}/hari",
        f"Sisa bebas: {format_currency(total_free)}",
        f"Sisa {days_left} hari\n",
        detail,
    ]
    if days_can_last < days_left:
        lines.append(f"\n💡 Idealnya maks {format_currency(ideal_daily)}/hari agar cukup sampai akhir bulan.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_comparison(update, context):
    """Compare this month vs last month spending."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction, Envelope
    tg_user = update.effective_user
    now = date.today()

    if now.month == 1:
        last_year, last_month = now.year - 1, 12
    else:
        last_year, last_month = now.year, now.month - 1

    async with AsyncSessionLocal() as db:
        user, hid, envelopes = await _get_user_envelopes(tg_user, db)
        if envelopes is None:
            await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
            return

        def spend_query(y, m):
            return (
                select(func.coalesce(func.sum(Transaction.amount), 0))
                .join(Envelope, Transaction.envelope_id == Envelope.id)
                .where(
                    Envelope.household_id == hid,
                    Transaction.is_deleted == False,
                    func.extract("year", Transaction.transaction_date) == y,
                    func.extract("month", Transaction.transaction_date) == m,
                )
            )

        this_total = Decimal(str((await db.execute(spend_query(now.year, now.month))).scalar()))
        last_total = Decimal(str((await db.execute(spend_query(last_year, last_month))).scalar()))

    last_month_name = date(last_year, last_month, 1).strftime("%B")
    this_month_name = now.strftime("%B")
    top_envs = sorted(envelopes, key=lambda e: e["spent"], reverse=True)[:3]

    if last_total == 0:
        await update.message.reply_text(
            f"📊 {this_month_name}: {format_currency(this_total)}\n"
            f"Data {last_month_name} belum ada untuk perbandingan."
        )
        return

    diff = this_total - last_total
    pct = abs(int(diff / last_total * 100))
    verdict = (
        f"🔴 Lebih *boros {pct}%* dari {last_month_name}." if diff > 0
        else f"✅ Lebih *hemat {pct}%* dari {last_month_name}!" if diff < 0
        else "➡️ Sama persis dengan bulan lalu."
    )

    lines = [
        f"📊 *{this_month_name} vs {last_month_name}*\n",
        f"{last_month_name}: {format_currency(last_total)}",
        f"{this_month_name}: {format_currency(this_total)}",
        f"\n{verdict}",
        f"\n🔝 Terbesar bulan ini:",
    ]
    for e in top_envs:
        if e["spent"] > 0:
            env = e["envelope"]
            lines.append(f"{env.emoji or '📁'} {env.name}: {format_currency(e['spent'])}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_santai(update, context):
    """Handle casual slang budget status checks."""
    from app.core.database import AsyncSessionLocal
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        _, _, envelopes = await _get_user_envelopes(tg_user, db)

    if envelopes is None:
        await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
        return

    total_free = sum(e["free"] for e in envelopes)
    total_allocated = sum(e["allocated"] for e in envelopes)
    total_spent = sum(e["spent"] for e in envelopes)

    if total_allocated == 0:
        await update.message.reply_text("Belum ada alokasi budget bulan ini.")
        return

    now = date.today()
    days_left = _days_left_in_month()
    days_elapsed = now.day
    spend_ratio = float(total_spent / total_allocated)
    time_ratio = days_elapsed / (days_elapsed + days_left)

    if spend_ratio > 1.0:
        status = "🔴 *Boncos parah!* Budget udah lewat batas."
        advice = "Perlu rem keras sampai akhir bulan."
    elif spend_ratio > 0.9:
        status = "🟠 *Mepet banget.* Hampir habis nih."
        advice = f"Sisa {format_currency(total_free)} buat {days_left} hari lagi."
    elif spend_ratio > time_ratio + 0.15:
        status = "🟡 *Agak boros.* Lebih cepat dari jadwal."
        advice = (
            f"Sudah {days_elapsed} hari ({int(time_ratio*100)}% bulan), "
            f"tapi {int(spend_ratio*100)}% budget terpakai."
        )
    elif spend_ratio < time_ratio - 0.2:
        status = "✅ *Hemat banget!* Jauh di bawah jadwal."
        advice = (
            f"Baru {int(spend_ratio*100)}% terpakai, padahal sudah {int(time_ratio*100)}% jalan bulan ini."
        )
    else:
        status = "✅ *Aman!* On track."
        advice = f"Terpakai {int(spend_ratio*100)}% dari total budget."

    await update.message.reply_text(
        f"{status}\n\n{advice}\n\nSisa bebas: *{format_currency(total_free)}*",
        parse_mode="Markdown",
    )


async def handle_emosi(update, context):
    """Handle emotional queries with actionable spending insights."""
    from app.core.database import AsyncSessionLocal
    tg_user = update.effective_user
    async with AsyncSessionLocal() as db:
        _, _, envelopes = await _get_user_envelopes(tg_user, db)

    if envelopes is None:
        await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
        return

    total_spent = sum(e["spent"] for e in envelopes)
    total_allocated = sum(e["allocated"] for e in envelopes)
    top = max(envelopes, key=lambda e: e["spent"], default=None)

    if not top or total_spent == 0:
        await update.message.reply_text(
            "Belum ada data pengeluaran bulan ini.\n"
            "Mulai catat dulu, baru kita bisa analisis polanya! 💪"
        )
        return

    top_pct = int(top["spent"] / total_spent * 100)
    spend_ratio = float(total_spent / total_allocated) if total_allocated > 0 else 0
    top_env = top["envelope"]

    lines = [
        "🔍 *Insight pengeluaran kamu:*\n",
        f"Terbesar: *{top_env.emoji or '📁'} {top_env.name}* ({top_pct}% dari total pengeluaran)",
        f"Total keluar bulan ini: {format_currency(total_spent)}",
    ]

    if spend_ratio > 0.8:
        lines.append(
            f"\n💡 {int(spend_ratio*100)}% budget udah terpakai — "
            f"pola {top_env.name} yang paling banyak menyedot."
        )
        lines.append(f"Coba set limit harian untuk amplop itu via /setlimit")
    elif spend_ratio > 0.5:
        lines.append(f"\n💡 Sebenarnya masih {int((1-spend_ratio)*100)}% tersisa. Masih bisa diatur!")
    else:
        lines.append(f"\n💡 Kamu masih aman — baru {int(spend_ratio*100)}% terpakai.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_koreksi(update, context):
    """Correct the amount of the last transaction."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction
    tg_user = update.effective_user
    text = update.message.text.strip()

    new_parsed = parse_amount(text)
    if not new_parsed:
        await update.message.reply_text(
            "Sebutkan jumlah yang benar ya.\n"
            "_Contoh: tadi salah, harusnya 20k_",
            parse_mode="Markdown",
        )
        return

    new_amount, _ = new_parsed

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        result = await db.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.is_deleted == False)
            .order_by(Transaction.created_at.desc())
            .limit(1)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            await update.message.reply_text("Tidak ada transaksi yang bisa dikoreksi.")
            return
        old_amount = txn.amount
        txn.amount = new_amount
        await db.commit()

    await update.message.reply_text(
        f"✅ *Dikoreksi!*\n\n"
        f"_{txn.description}_\n"
        f"{format_currency(old_amount)} → *{format_currency(new_amount)}*",
        parse_mode="Markdown",
    )


async def handle_nabung(update, context):
    """Calculate savings plan: how much to set aside per day/month."""
    text = update.message.text.strip()
    parsed = parse_amount(text)
    if not parsed:
        await update.message.reply_text(
            "Sebutkan target nabungnya ya.\n"
            "_Contoh: mau nabung 1 juta dalam 2 bulan_",
            parse_mode="Markdown",
        )
        return

    target, _ = parsed

    # Extract duration
    duration_match = re.search(
        r"(\d+)\s*(bulan|hari|minggu|tahun)", text, re.IGNORECASE
    )
    if not duration_match:
        await update.message.reply_text(
            "Sebutkan jangka waktunya ya.\n"
            "_Contoh: mau nabung 500k dalam 3 bulan_",
            parse_mode="Markdown",
        )
        return

    num = int(duration_match.group(1))
    unit = duration_match.group(2).lower()

    if unit == "hari":
        days = num
    elif unit == "minggu":
        days = num * 7
    elif unit == "bulan":
        days = num * 30
    elif unit == "tahun":
        days = num * 365
    else:
        days = num * 30

    per_hari = target / days
    per_bulan = target / (days / 30)

    await update.message.reply_text(
        f"🎯 *Target nabung {format_currency(target)}*\n"
        f"Dalam {num} {unit} ({days} hari)\n\n"
        f"Harus sisihkan:\n"
        f"• Per hari: *{format_currency(per_hari)}*\n"
        f"• Per bulan: *{format_currency(per_bulan)}*\n\n"
        f"💡 Buat amplop Tabungan di jatahku.com dan alokasikan rutin setiap bulan.",
        parse_mode="Markdown",
    )


async def handle_multi_expense(update, context, items):
    """Record multiple comma-separated expenses in one message."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction, TransactionSource
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        setup_ok, _ = await _is_setup_complete(user, db)
        if not setup_ok:
            await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
            return
        hid = await get_household_id(user, db)

        recorded = []
        unmatched = []
        for amount, description in items:
            envelope, _ = await find_best_envelope(description, hid, db)
            if envelope:
                db.add(Transaction(
                    user_id=user.id,
                    envelope_id=envelope.id,
                    amount=amount,
                    description=description,
                    transaction_date=date.today(),
                    source=TransactionSource.telegram,
                ))
                recorded.append((amount, description, envelope))
            else:
                unmatched.append((amount, description))

        if recorded:
            await db.commit()

    if not recorded:
        await update.message.reply_text(
            "Nggak bisa mencocokkan ke amplop manapun.\n"
            "Coba catat satu per satu."
        )
        return

    total = sum(a for a, _, _ in recorded)
    lines = [f"✅ *{len(recorded)} transaksi dicatat*\n"]
    for amount, desc, env in recorded:
        lines.append(f"{env.emoji or '📁'} {env.name}: {format_currency(amount)} — {desc}")
    lines.append(f"\n💸 Total: *{format_currency(total)}*")

    if unmatched:
        lines.append(f"\n⚠️ Tidak dikenali amplop untuk:")
        for amount, desc in unmatched:
            lines.append(f"• {desc} {format_currency(amount)}")
        lines.append("_Catat satu per satu untuk pilih amplop._")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
