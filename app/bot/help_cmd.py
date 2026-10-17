from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# Menu perintah Telegram (set_my_commands) — satu daftar untuk `post_init` dan
# `GET /webhook/telegram/set-commands`. Perintah baru juga didaftarkan di `bot_commands()`.
BOT_COMMANDS = [
    ("status", "Ringkasan budget periode ini"),
    ("tanya", "Tanya AI Advisor (sisa, kapan habis, tagihan…)"),
    ("amplop", "Daftar amplop & sisa dana"),
    ("tagihan", "Tagihan bulan ini"),
    ("target", "Progres target tabungan"),
    ("pending", "Transaksi menunggu konfirmasi"),
    ("langganan", "Daftar langganan aktif"),
    ("batal", "Undo transaksi terakhir"),
    ("amplop_baru", "Buat amplop baru"),
    ("template", "Pilih template amplop"),
    ("lock", "Kunci/buka amplop"),
    ("setlimit", "Set limit harian amplop"),
    ("setcooling", "Set cooling period"),
    ("controls", "Status behavior controls"),
    ("tambah_langganan", "Tambah langganan baru"),
    ("hapus_langganan", "Hapus langganan"),
    ("invite", "Undang anggota household"),
    ("join", "Gabung ke household"),
    ("webapp", "Login ke WebApp tanpa password"),
    ("link", "Hubungkan ke WebApp"),
    ("unlink", "Putuskan koneksi Telegram"),
    ("help", "Panduan lengkap"),
]

# Pertanyaan yang pasti terjawab mesin AI Advisor (02-aturan.md §6H) — tombol /tanya.
# Kunci = intent di `intent_learning.intent_handlers()`.
PERTANYAAN = [
    ("sisa", "💰 Sisa dana"),
    ("harian", "📅 Jatah harian"),
    ("proyeksi", "🔮 Kapan habis?"),
    ("kenapa_boros", "🤔 Kenapa boros?"),
    ("pengeluaran_hari_ini", "🧾 Pengeluaran hari ini"),
    ("tagihan", "📆 Tagihan bulan ini"),
    ("target", "🎯 Target tabungan"),
]


AKUN_TELEGRAM = """*Akun:*
/webapp — Login ke WebApp tanpa password
/link \\[kode\\] — Hubungkan dengan WebApp
/unlink — Lepas koneksi Telegram

"""


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send comprehensive help guide."""
    text = """📖 *Panduan Jatahku*

*Catat Pengeluaran* (kirim langsung):
- `kopi 35k` atau `35rb kopi`
- `makan siang rp25.000`
- `grab 15000`
- 📸 Kirim *foto struk* — total & tanggal terbaca otomatis

*Langganan Otomatis:*
- `sewa server 250k tiap bulan`
- `langganan netflix 54k`
- `kontrak rumah 5jt tiap tahun`

*Tanya AI Advisor* (ketik biasa, atau /tanya):
- `sisa` · `limit harian` · `kapan habis`
- `kenapa boros?` · `kenapa makan habis?`
- `aman gak beli sepatu 300k`
- `tagihan bulan ini` · `target liburan`

*Perintah Utama:*
/status — Ringkasan budget periode ini
/tanya — Pilih pertanyaan untuk AI Advisor
/tagihan — Tagihan bulan ini
/target \\[nama\\] — Progres target tabungan
/amplop — Daftar amplop & sisa dana
/pending — Transaksi yang menunggu cooling
/langganan — Daftar langganan aktif
/batal — Undo transaksi terakhir

*Kelola Amplop:*
/amplop\\_baru \\[nama\\] \\[budget\\]
/template — Pilih template amplop
/lock \\[nama\\] — Kunci/buka amplop
/setlimit \\[nama\\] \\[jumlah\\] — Limit harian
/setcooling \\[nama\\] \\[jumlah\\] — Cooling threshold
/controls — Status behavior controls

*Household:*
/invite — Buat kode invite
/join \\[kode\\] — Gabung household

{akun}*Tips:*
- Ketik angka dengan format apapun: 35k, 35rb, 35.000, rp35000
- Bot otomatis pilih amplop yang tepat
- Jika ragu, bot akan tanya amplop mana

🌐 Dashboard: jatahku.com
⭐ Upgrade Pro: jatahku.com/upgrade"""

    from app.bot.channel import is_web
    # Perintah akun hanya bermakna di Telegram; di chat webapp user sudah login.
    text = text.replace("{akun}", "" if is_web() else AKUN_TELEGRAM)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_tanya(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tanya — pertanyaan yang tersedia sebagai tombol (§6H: user diarahkan ke pertanyaan
    yang pasti terjawab)."""
    tombol = [InlineKeyboardButton(label, callback_data=f"tanya:{kunci}") for kunci, label in PERTANYAAN]
    await update.message.reply_text(
        "Mau tanya apa? Pilih di bawah, atau ketik sendiri.\n"
        "Untuk cek belanja: _aman gak beli sepatu 300k_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([tombol[i:i + 2] for i in range(0, len(tombol), 2)]),
    )


async def handle_tanya_callback(update, context):
    """Tombol /tanya → handler intent yang sama dengan pesan teks (jawaban jadi pesan baru)."""
    from app.bot.intent_learning import intent_handlers
    query = update.callback_query
    await query.answer()
    kunci = (query.data or "").split(":", 1)[-1]
    handler = intent_handlers().get(kunci)
    if handler is None:
        return

    class _Update:
        effective_user = query.from_user
        message = query.message
        effective_message = query.message  # dipakai reply_setup_needed

    await handler(_Update(), context)
