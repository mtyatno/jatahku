"""Natural language query handlers for the Telegram bot."""
import re
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import select, func

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.bot.handlers import (
    parse_amount, find_best_envelope, get_envelopes_with_spent,
    get_or_create_user, get_household_id, _is_setup_complete, format_currency,
)

# ── Detection patterns ────────────────────────────────────────────────────────

SISA_RE = re.compile(
    # Exact single/short triggers (1-3 kata)
    r"^(sisa|saldo|rekap|rekapan|cek|info|amplop|jatah|dompet|status|uangku|duitku"
    r"|sisa\s+uang|sisa\s+duit|cek\s+saldo|tinggal\s+berapa|sisa\s+jatah|cek\s+jatah"
    r"|info\s+saldo|rekap\s+amplop|sisa\s+berapa|duit\s+sisa|cek\s+duit|uang\s+sisa"
    r"|sisa\s+saldo|saldo\s+dong|cek\s+dompet|jatah\s+sisa|info\s+jatah|lihat\s+saldo"
    r"|saldo\s+sisa)$|"

    # Core balance keywords — match anywhere
    r"\b(sisa|tersisa|saldo|rekap|rekapan|jatah|amplop|cuan|amunisi)\b|"

    # "tinggal" in balance context
    r"\btinggal\s+(berapa|sisa|duit|uang|saldo|sedikit)\b|"
    r"\b(duit|uang|saldo|jatah)\s*(gue|gw|ku|aku|saya|w\b)?\s*tinggal\b|"

    # "berapa" + money words
    r"\bberapa\s+(sisa|uang|duit|jatah|saldo|lagi|perak|cuan)\b|"
    r"\b(duit|uang|saldo)\s*(gue|gw|ku|aku|saya|w\b)?\s*berapa\b|"

    # Action word + budget context
    r"\b(cek|lihat|liat|info|minta|report|tolong)\s+"
    r"(saldo|duit|uang|jatah|amplop|dompet|kantong|keuangan|posisi|sisa|cuan|rekap)\b|"

    # "posisi/status" + money context
    r"\b(posisi|status)\s+(dompet|kantong|keuangan|duit|uang|amplop)\b|"

    # Dompet/kantong/keuangan (wallet words)
    r"\b(dompet|kantong|keuangan)\b|"

    # "masih ada/sisa/punya duit"
    r"\bmasih\s+(ada\s+)?(duit|uang|jatah|saldo)\b|"
    r"\bmasih\s+(sisa|punya\s+duit|ada\s+duit|bisa\s+jajan)\b|"

    # Slang near wallet words
    r"\b(duit|uang|dompet|kantong).{0,25}(sekarat|menipis|nafas|tebel)\b|"
    r"\b(sekarat|menipis).{0,25}(duit|uang|dompet|kantong)\b",

    re.IGNORECASE,
)

HARIAN_RE = re.compile(
    # "harian" is the main signal
    r"\bharian\b|"
    r"\bperhari\b|"

    # "per hari" — very strong signal
    r"\bper\s+hari\b|"

    # "hari ini" + budget query keyword
    r"\bhari\s+ini\s+(berapa|maksimal|boleh|bisa|jatah|limit|budget|jatahnya|budgetnya)\b|"

    # budget keyword + "hari ini"
    r"\b(maksimal|boleh|bisa|jatah|limit|budget)\s+(jajan\s+|keluar\s+|habis\s+|ngeluarin\s+)?hari\s+ini\b|"

    # "batas pengeluaran hari ini"
    r"\b(batas|limit)\s+(pengeluaran\s+)?hari\s+ini\b",

    re.IGNORECASE,
)

PROYEKSI_RE = re.compile(
    # When will money run out
    r"\bkapan\s+(habis|ludes|kere|abis|tewas|modar|bokek|kosong|nol)\b|"
    r"\b(habis|ludes|abis)\s+(tanggal|kapan)\b|"
    r"\b(uang|duit|saldo|jatah|sisa).{0,25}(habis|ludes|abis)\s*(kapan|tanggal|bulan)?\b|"

    # "tahan/kuat/cukup sampai kapan"
    r"\b(cukup|aman|tahan|kuat|bertahan)\s+(sampai|hingga)\s*(kapan|akhir|tanggal|berapa)?\b|"
    r"\bsampai\s+kapan\b|"

    # "nyampe" slang
    r"\bnyampe\s+(kapan|akhir|gajian|tanggal|bulan\s+depan)?\b|"

    # How many days remaining
    r"\b(tahan|kuat|cukup|bertahan|sisa)\s+berapa\s+hari\b|"
    r"\bberapa\s+hari\s+(lagi|sisa)\b|"
    r"\bsisa\s+berapa\s+hari\b|"

    # Scenario: "kalau begini terus"
    r"\bkalau\s+(begini|gini|kayak\s+gini)\s*(terus|aja)?\b|"
    r"\bbegini\s+terus\b|"
    r"\bburn\s+rate\b|"

    # Slang states
    r"\bkapan\s+(kere|bokek)\b|"
    r"\b(sisa|umur)\s+(nafas|duit|saldo).{0,15}(berapa|hari|kapan)\b|"
    r"\bumur\s+(duit|saldo)\b|"

    # Short exact forms
    r"^(habis\s+kapan|tahan\s+berapa\s+hari|sisa\s+berapa\s+hari|nyampe\s+kapan"
    r"|kapan\s+habis|cukup\s+berapa\s+hari|kuat\s+berapa\s+hari|habis\s+tanggal\s+berapa"
    r"|cukup\s+sampe\s+kapan|abis\s+kapan|kapan\s+kere|kapan\s+ludes|kapan\s+bokek)$",

    re.IGNORECASE,
)

COMPARISON_RE = re.compile(
    # Compare this month vs last
    r"\blebih\s+(boros|hemat|parah|ngirit|saving|ambyar|boncos|gila|waras)\b|"
    r"\b(bulan\s+lalu|bulan\s+kemarin|kemaren|kemarin)\b|"
    r"\b(bandingin|bandingkan|komparasi|perbandingan|evaluasi)\b|"
    r"\bboros\s+mana\b|"
    r"\bhemat\s+mana\b|"
    r"\bbulan\s+ini\s+vs\b|"

    # Top spending
    r"\b(pengeluaran|expense|jajan|spender)\s+terbesar\b|"
    r"\btop\s+(pengeluaran|expense|jajan|spender|jebol)\b|"
    r"\bpaling\s+(boros|gede|banyak|nyedot|nguras|parah|cepet\s+abis)\b|"
    r"\b(uang|duit)\s+paling\s+(banyak|gede)\s+(abis|lari|kesedot|kepake|kemana)\b|"
    r"\byang\s+(bikin|nyedot|nguras)\s+(boros|dompet|tipis|bokek|habis)\b|"
    r"\btren\s+(pengeluaran|boros|jajan)\b|"
    r"\bkategori\s+terboros\b",

    re.IGNORECASE,
)

SANTAI_RE = re.compile(
    r"\b(boncos|bokek)\b|"
    r"\b(overbudget|over\s+budget|over\s+limit|tekor|jebol|kritis|minus)\s*(ga|gak|nggak|dong|nih|belum)?\b|"
    r"\b(parah|gawat)\s*(gak|nggak|banget|sih)\b|"
    r"\b(aman|sehat)\s+(gak|nggak|kan|gak\s+sih|nih|bro|cuy|bang)\b|"
    r"\bmasih\s+(waras|oke|chill|kuat\s+nafas|panjang\s+nafas|tebel|ambyar)\b|"
    r"\bgue\s+(masih\s+)?(kaya|miskin)\b|"
    r"\budah\s+(kere|miskin)\b",

    re.IGNORECASE,
)

EMOSI_RE = re.compile(
    # Why does it disappear
    r"\b(kenapa|kok)\s+.{0,30}(cepet\s+)?(habis|ludes|abis|ilang|ambyar|tewas|kering|tipis|susut)\b|"
    r"\bkok\s+(abis|habis|ludes)\s+terus\b|"
    r"\bkok\s+cepet\s+(abis|habis|ludes)\b|"

    # Where did it go
    r"\b(duit|uang)\s+(lari|abis|ilang|kesedot|menguap|nguap)\s+(kemana|ke\s+mana)\b|"
    r"\bkemana\s+(aja\s+)?(duit|uang)\b|"
    r"\b(duit|uang).{0,20}(lari|kesedot|abis|pergi)\s*(kemana|buat\s+apa)\b|"
    r"\bbocor\s+halus\b|"

    # "perasaan ga beli apa-apa kok abis"
    r"\bperasaan\s+(ga|gak|nggak)\s+(beli|jajan|boros|ngeluarin|foya)\b|"
    r"\b(ga|gak|nggak)\s+(jajan|beli)\s+(banyak|mahal|apa-apa).{0,20}(abis|habis|ludes)\b|"

    # Can't save
    r"\bgak\s+(pernah\s+)?bisa\s+(nabung|irit|ngumpul|nyimpen)\b|"
    r"\bsusah\s+(banget\s+)?nabung\b|"
    r"\b(selalu|terus)\s+boncos\b|"
    r"\bduit\s+kayak\s+(air|ditiup|nguap|numpang\s+lewat)\b|"
    r"\btuyul\b",

    re.IGNORECASE,
)

KOREKSI_RE = re.compile(
    # Edit amount
    r"\b(tadi|barusan)\s*(salah|keliru|typo|ngaco|salah\s+ketik)\b|"
    r"\beh\s+salah\b|"
    r"\btypo\b|"
    r"\b(ralat|edit|koreksi)\b|"
    r"\bharusnya\s+\d|"
    r"\b(ganti|ubah)\s+.{0,20}(tadi|terakhir|barusan)\b|"

    # Delete/undo/cancel
    r"\b(batalin|cancel|undo)\s*(yang\s+)?(barusan|tadi|terakhir|ini)?\b|"
    r"\bgajadi\b|"
    r"\bhapus\s+(transaksi|input|catatan|data|entry|yang\s+(barusan|tadi)|terakhir|barusan)\b",

    re.IGNORECASE,
)

NABUNG_RE = re.compile(
    # With duration keywords
    r"\b(nabung|ngumpulin|ngumpul|kumpul|nyisih|nyisihin|sisih|sisihkan)\s*.{0,30}\b(dalam|selama|bulan|hari|minggu|tahun)\b|"
    r"\btarget\s+.{0,30}\b(dalam|bulan|hari|minggu|tahun)\b|"
    r"\bharus\s+(nyisih|sisih|nabung|sisihkan)\s+(berapa|per)\b|"
    r"\bper\s+(hari|bulan|minggu)\s+(buat|untuk|target|dapet|capai)\b|"
    r"\b(pengen|mau|ingin)\s+(beli|dapet|dapetin|punya).{0,30}\b(bulan|hari|minggu)\b",

    re.IGNORECASE,
)


PENGELUARAN_HARI_INI_RE = re.compile(
    # ── Exact standalone triggers (no "hari ini" needed) ─────────────────────
    r"^(spend|expend|pengeluaran|jajan\s+hari\s+ini|keluar\s+hari\s+ini"
    r"|total\s+hari\s+ini|rekap\s+hari\s+ini|expend\s+hari\s+ini"
    r"|pengeluaran\s+hari\s+ini|spend\s+hari\s+ini"
    r"|total\s+keluar|total\s+jajan|total\s+belanja|rekap\s+harian"
    r"|total\s+pengeluaran|pengeluaran\s+harian|spend\s+harian|expend\s+harian"
    r"|totalan\s+hari\s+ini|total\s+spend|kepake\s+hari\s+ini"
    r"|duit\s+keluar\s+hari\s+ini|rekap\s+jajan|total\s+duit\s+keluar"
    r"|abis\s+brp|jajan\s+brp\s+hari\s+ini|total\s+hari\s+ini\s+dong)$"

    # ── "berapa" + expense verb (+ optional "hari ini") ──────────────────────
    r"|\bberapa\s+(spend|expend|keluar|jajan|belanja|pengeluaran|habis|abis"
    r"|ngeluarin|ngabisin|kepake|terpakai)\b"

    # ── "hari ini" + sudah/udah + expense verb ───────────────────────────────
    r"|\bhari\s+ini\s+(udah|sudah)?\s*"
    r"(expend|spend|keluar|habis|jajan|belanja|ngeluarin|ngabisin|terpakai|kepake|abis"
    r"|boros|bakar\s+duit|ludes|foya|boncos|ambyar|bocor|tewas|nguras|buang\s+duit"
    r"|narik|nyumbang|cuan\s+keluar)\b"

    # ── expense verb + "hari ini" ────────────────────────────────────────────
    r"|\b(expend|spend|ngeluarin|ngabisin|belanja|jajan|abis|ludes|boncos|ambyar|tewas"
    r"|bakar\s+duit|buang\s+duit|foya|khilaf|boros)\b.{0,30}\bhari\s+ini\b"

    # ── "udah/sudah" + expense verb (+ "hari ini" context) ──────────────────
    r"|\b(udah|sudah)\s+(expend|spend|keluar|jajan|belanja|ngeluarin|ngabisin"
    r"|kepake|abis|boros|bakar|boncos|ambyar|khilaf|foya|ludes|bocor)\b"
    r".{0,40}\bhari\s+ini\b"

    r"|\bhari\s+ini\b.{0,40}\b(udah|sudah)\s+(expend|spend|keluar|jajan|belanja"
    r"|ngeluarin|ngabisin|kepake|abis|boros|bakar|boncos|ambyar|khilaf|foya|ludes)\b"

    # ── rekap / total + hari ini / pagi ──────────────────────────────────────
    r"|\b(total|rekap|rekapin|totalin|akumulasi|hitungin|minta\s+total|minta\s+rekap)\b"
    r".{0,25}(hari\s+ini|harian|dari\s+pagi|pagi\s+sampai)"

    # ── "dompet/kantong bocor/jebol" hari ini ────────────────────────────────
    r"|\b(dompet|kantong).{0,20}(bocor|jebol|nguras|terkuras|berkurang).{0,20}hari\s+ini\b"
    r"|\bhari\s+ini.{0,20}(dompet|kantong).{0,20}(bocor|jebol|nguras|berkurang)\b"

    # ── singkat / typo ────────────────────────────────────────────────────────
    r"|\b(abis|habis|keluar)\s+brp\s+hari\s+ini\b"
    r"|\bhari\s+ini\s+(abis|keluar|expend|spend|jajan)\s+(brp|berapa)\b"
    r"|\bhari\s+ini\s+(brp|berapa)\b(?!.*(boleh|bisa|maksimal|limit|jatah|budget))",

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
def is_pengeluaran_hari_ini(text): return bool(PENGELUARAN_HARI_INI_RE.search(text))


def parse_multi_expense(text):
    """Parse multi-expense input. Supports separators: newline, , ; terus lalu dan.
    Returns list of (amount, desc) with >= 2 items, or None.
    """
    # Try separators in priority order
    sep_patterns = [
        r"\s*\n+\s*",           # newline / Enter (highest priority)
        r"\s*[,;]\s*",
        r"\s+(?:terus|lalu)\s+",
        r"\s+dan\s+",
    ]
    for sep in sep_patterns:
        parts = re.split(sep, text, flags=re.IGNORECASE)
        if len(parts) >= 2:
            results = [parse_amount(p.strip()) for p in parts if p.strip()]
            results = [r for r in results if r is not None]
            if len(results) >= 2:
                return results
    return None


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
        detail = f"Di kecepatan ini butuh {format_currency(projected_eom)} tapi budget {format_currency(total_allocated)}"

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
        advice = f"Baru {int(spend_ratio*100)}% terpakai, padahal sudah {int(time_ratio*100)}% jalan bulan ini."
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
        lines.append("Coba set limit harian untuk amplop itu via /setlimit")
    elif spend_ratio > 0.5:
        lines.append(f"\n💡 Sebenarnya masih {int((1-spend_ratio)*100)}% tersisa. Masih bisa diatur!")
    else:
        lines.append(f"\n💡 Kamu masih aman — baru {int(spend_ratio*100)}% terpakai.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_koreksi(update, context):
    """Correct or delete the last transaction.
    - With new amount → edit the amount
    - Without amount (undo/batalin/hapus) → soft-delete
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction
    tg_user = update.effective_user
    text = update.message.text.strip()

    new_parsed = parse_amount(text)

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

        if new_parsed:
            new_amount, _ = new_parsed
            old_amount = txn.amount
            txn.amount = new_amount
            await db.commit()
            await update.message.reply_text(
                f"✅ *Dikoreksi!*\n\n_{txn.description}_\n"
                f"{format_currency(old_amount)} → *{format_currency(new_amount)}*",
                parse_mode="Markdown",
            )
        else:
            # No amount → treat as undo/delete
            txn.is_deleted = True
            await db.commit()
            await update.message.reply_text(
                f"↩️ Dibatalkan: {format_currency(txn.amount)} — {txn.description}"
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
    duration_match = re.search(r"(\d+)\s*(bulan|hari|minggu|tahun)", text, re.IGNORECASE)
    if not duration_match:
        await update.message.reply_text(
            "Sebutkan jangka waktunya ya.\n"
            "_Contoh: mau nabung 500k dalam 3 bulan_",
            parse_mode="Markdown",
        )
        return

    num = int(duration_match.group(1))
    unit = duration_match.group(2).lower()
    unit_days = {"hari": 1, "minggu": 7, "bulan": 30, "tahun": 365}
    days = num * unit_days.get(unit, 30)

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
    """Record multiple expenses in one message.
    Auto-records matched items, queues unknown items for inline keyboard selection.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction, TransactionSource, Envelope
    from app.bot.handlers import save_learned_keywords
    import redis.asyncio as aioredis, json as json_mod, secrets
    from app.core.config import get_settings
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(str(tg_user.id), tg_user.first_name, db)
        setup_ok, _ = await _is_setup_complete(user, db)
        if not setup_ok:
            await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
            return
        hid = await get_household_id(user, db)

        # Fetch all envelopes once for the keyboard
        env_result = await db.execute(
            select(Envelope).where(Envelope.household_id == hid, Envelope.is_active == True)
            .order_by(Envelope.created_at)
        )
        all_envs = env_result.scalars().all()

        recorded = []
        unmatched = []
        for amount, description in items:
            envelope, _ = await find_best_envelope(description, hid, db, user_id=user.id)
            if envelope:
                db.add(Transaction(
                    user_id=user.id,
                    envelope_id=envelope.id,
                    amount=amount,
                    description=description,
                    transaction_date=date.today(),
                    source=TransactionSource.telegram,
                ))
                await save_learned_keywords(user.id, description, envelope.id, db)
                recorded.append((amount, description, envelope))
            else:
                unmatched.append({"amount": int(amount), "desc": description})

        if recorded:
            await db.commit()

        hid_str = str(hid)
        user_id_str = str(user.id)
        env_list = [{"id": str(e.id), "name": e.name, "emoji": e.emoji or "📁"} for e in all_envs]

    # Build summary of auto-recorded items
    auto_lines = []
    for amount, desc, env in recorded:
        auto_lines.append(f"{env.emoji or '📁'} {env.name}: {format_currency(amount)} — {desc}")

    if not unmatched:
        # All matched — show summary
        total = sum(a for a, _, _ in recorded)
        lines = [f"✅ *{len(recorded)} transaksi dicatat*\n"] + auto_lines
        lines.append(f"\n💸 Total: *{format_currency(total)}*")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if not recorded and not all_envs:
        await update.message.reply_text("Belum ada amplop. Ketik /template untuk buat.")
        return

    # Store queue in Redis, ask for first unmatched item
    batch_key = secrets.token_hex(4)
    r = aioredis.from_url(get_settings().REDIS_URL)
    await r.set(f"batch:{batch_key}", json_mod.dumps({
        "queue": unmatched,
        "auto_lines": auto_lines,
        "user_id": user_id_str,
        "hid": hid_str,
        "envs": env_list,
    }), ex=600)
    await r.aclose()

    await _ask_batch_item(update, batch_key, unmatched, 0, auto_lines, env_list, is_edit=False)


async def _ask_batch_item(update_or_query, batch_key, queue, idx, auto_lines, env_list, is_edit=False):
    """Show inline keyboard for queue[idx]."""
    item = queue[idx]
    remaining_count = len(queue) - idx

    header = ""
    if auto_lines:
        header = "\n".join(auto_lines) + "\n" + "─" * 20 + "\n"

    progress = f"({idx + 1}/{len(queue)})" if len(queue) > 1 else ""
    text = (
        f"{header}"
        f"💰 {format_currency(item['amount'])} — {item['desc']} {progress}\n\n"
        f"Masuk ke amplop mana?"
    )
    keyboard = []
    for env in env_list:
        keyboard.append([InlineKeyboardButton(
            f"{env['emoji']} {env['name']}",
            callback_data=f"batch_{batch_key}_{idx}_{env['id']}"
        )])
    keyboard.append([InlineKeyboardButton("⏭ Lewati", callback_data=f"batch_{batch_key}_{idx}_skip")])

    markup = InlineKeyboardMarkup(keyboard)
    if is_edit:
        await update_or_query.edit_message_text(text, reply_markup=markup)
    else:
        await update_or_query.message.reply_text(text, reply_markup=markup)


async def handle_pengeluaran_hari_ini(update, context):
    """Show total spending today, broken down by envelope."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import Transaction, Envelope
    from sqlalchemy import select, func
    tg_user = update.effective_user

    async with AsyncSessionLocal() as db:
        user, hid, envelopes = await _get_user_envelopes(tg_user, db)
        if envelopes is None:
            await update.message.reply_text("⚠️ Setup budget dulu di jatahku.com")
            return

        today = date.today()

        # Query today's transactions grouped by envelope
        rows = await db.execute(
            select(Transaction.envelope_id, func.sum(Transaction.amount).label("total"))
            .join(Envelope, Envelope.id == Transaction.envelope_id)
            .where(
                Transaction.user_id == user.id,
                Transaction.transaction_date == today,
                Transaction.amount > 0,
            )
            .group_by(Transaction.envelope_id)
        )
        by_envelope = {r.envelope_id: r.total for r in rows}

        # Also query latest 3 transactions today for mini riwayat
        recent_rows = await db.execute(
            select(Transaction)
            .where(
                Transaction.user_id == user.id,
                Transaction.transaction_date == today,
                Transaction.amount > 0,
            )
            .order_by(Transaction.id.desc())
            .limit(5)
        )
        recent_txns = recent_rows.scalars().all()

    total_today = sum(by_envelope.values()) if by_envelope else Decimal("0")

    # Calculate daily limit for comparison
    total_free = sum(e["free"] for e in envelopes)
    days_left = _days_left_in_month()
    daily_limit = total_free / days_left if days_left > 0 else Decimal("0")

    env_map = {e["envelope"].id: e["envelope"] for e in envelopes}

    # ── Header ─────────────────────────────────────────────────────
    _DAY = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    day_str = _DAY[today.weekday()]
    date_str = today.strftime("%d %b")
    txn_count = sum(
        1 for t in recent_txns
    )  # recent_txns is already limited to 5; re-count from by_envelope not needed
    # actual count: we do have recent_txns limited to 5 but total count unknown — use by_envelope sum proxy
    total_count_approx = len(recent_txns)

    lines = [f"🧾 <b>Pengeluaran · {day_str}, {date_str}</b>"]

    if total_today == 0:
        lines.append("\n🌱 Belum ada pengeluaran hari ini.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    lines.append(f"\n💸 <b>{format_currency(total_today)}</b>")

    # Status vs daily limit
    if daily_limit > 0 and total_today > daily_limit:
        over = total_today - daily_limit
        lines.append(f"⚠️ Lewat jatah harian <b>{format_currency(over)}</b> (jatah: {format_currency(daily_limit)})")
    elif daily_limit > 0:
        sisa = daily_limit - total_today
        lines.append(f"✅ Sisa jatah hari ini: <b>{format_currency(sisa)}</b>")

    # ── Per-envelope breakdown with composition bar ─────────────────
    sorted_env = sorted(by_envelope.items(), key=lambda x: -x[1])
    lines.append("\n─────────────────")
    for env_id, spent in sorted_env:
        env = env_map.get(env_id)
        if not env:
            continue
        emoji = env.emoji or "📁"
        name = env.name or "—"
        pct = int(float(spent / total_today) * 100) if total_today > 0 else 0
        filled = round(pct / 100 * 6)
        bar = "▓" * filled + "░" * (6 - filled)
        lines.append(f"{emoji} {name}  {bar} <b>{format_currency(spent)}</b> ({pct}%)")

    # ── Recent transactions ─────────────────────────────────────────
    if recent_txns:
        lines.append("\n─────────────────")
        lines.append("5 terakhir:")
        for t in recent_txns:
            env = env_map.get(t.envelope_id)
            em = env.emoji if env else "📁"
            desc = t.description or "—"
            lines.append(f"{em} {desc} — <b>{format_currency(t.amount)}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
