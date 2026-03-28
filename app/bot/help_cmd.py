from telegram import Update
from telegram.ext import ContextTypes


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send comprehensive help guide."""
    text = """📖 *Panduan Jatahku*

*Catat Pengeluaran* (kirim langsung):
- `kopi 35k` atau `35rb kopi`
- `makan siang rp25.000`
- `grab 15000`

*Langganan Otomatis:*
- `sewa server 250k tiap bulan`
- `langganan netflix 54k`
- `kontrak rumah 5jt tiap tahun`

*Perintah Utama:*
/status — Ringkasan budget bulan ini
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

*Akun:*
/webapp — Login ke WebApp tanpa password
/link \\[kode\\] — Hubungkan dengan WebApp
/unlink — Lepas koneksi Telegram

*Tips:*
- Ketik angka dengan format apapun: 35k, 35rb, 35.000, rp35000
- Bot otomatis pilih amplop yang tepat
- Jika ragu, bot akan tanya amplop mana

🌐 Dashboard: jatahku.com
⭐ Upgrade Pro: jatahku.com/upgrade"""

    await update.message.reply_text(text, parse_mode="Markdown")

