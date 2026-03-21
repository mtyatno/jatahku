from telegram import Update
from telegram.ext import ContextTypes


async def cmd_help(update, context):
    await update.message.reply_text(
        "📖 *Jatahku — Panduan Lengkap*\n"
        "Setiap rupiah ada jatahnya.\n\n"

        "💰 *Catat Pengeluaran*\n"
        "Kirim langsung seperti chat biasa:\n"
        "• `35k starbucks`\n"
        "• `150rb nasi padang`\n"
        "• `2.5jt beli headphone`\n\n"

        "📊 *Informasi*\n"
        "/status — Ringkasan budget bulan ini\n"
        "/amplop — Daftar semua amplop\n"
        "/pending — Transaksi yang menunggu konfirmasi\n"
        "/langganan — Daftar langganan aktif\n"
        "/controls — Status behavior controls\n\n"

        "✉️ *Kelola Amplop*\n"
        "/amplop\\_baru [nama] [budget] — Buat amplop\n"
        "/template — Buat amplop dari template\n\n"

        "⚙️ *Behavior Controls*\n"
        "/lock — Kunci/buka amplop\n"
        "/setlimit [nama] [jumlah] — Set limit harian\n"
        "/setcooling [nama] [jumlah] — Set cooling period\n\n"

        "🔄 *Langganan*\n"
        "/tambah\\_langganan [nama] [jumlah] [amplop]\n"
        "/hapus\\_langganan — Hapus langganan\n\n"

        "🔗 *Akun*\n"
        "/link [kode] — Hubungkan ke WebApp\n"
        "/unlink — Putuskan koneksi Telegram\n\n"

        "🏠 *Household*\n"
        "/invite — Undang anggota baru\n"
        "/join [kode] — Gabung ke household\n\n"

        "↩️ *Lainnya*\n"
        "/batal — Undo transaksi terakhir\n"
        "/help — Tampilkan panduan ini\n\n"

        "🌐 WebApp: jatahku.com",
        parse_mode="Markdown",
    )
